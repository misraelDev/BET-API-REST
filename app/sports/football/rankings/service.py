"""Validation, immutable versioning, and read-only queries for rankings."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from app.prompts.models import PromptReference
from app.prompts.repository import PromptRepository
from app.sports.football.predictions.catalog import FootballLeague
from app.sports.football.predictions.repository import FootballPredictionRepository
from app.sports.football.rankings.models import (
    FootballRankingBatchCreate,
    FootballRankingBatchItem,
    FootballRankingBatchResponse,
    FootballRankingCreate,
    FootballRankingDetailResponse,
    FootballRankingListResponse,
    RankingScope,
    StoredFootballRanking,
)
from app.sports.football.rankings.repository import (
    FootballRankingRepository,
    RankingRepositoryConflict,
)

logger = logging.getLogger(__name__)


class RankingNotFound(LookupError):
    pass


class RankingReferenceNotFound(LookupError):
    pass


class StoredRankingInvalid(RuntimeError):
    """A persisted ranking cannot be reconstructed from its stored document."""


class RankingService:
    def __init__(
        self,
        repository: FootballRankingRepository,
        *,
        prompt_repository: PromptRepository,
        prediction_repository: FootballPredictionRepository,
        clock: Any = None,
    ) -> None:
        self._repository = repository
        self._prompt_repository = prompt_repository
        self._prediction_repository = prediction_repository
        self._clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )

    @classmethod
    def _request_hash(
        cls,
        payload: FootballRankingCreate,
        prompt_reference: PromptReference,
    ) -> str:
        value = payload.model_dump(
            mode="json",
            exclude={"idempotency_key", "ranking_id"},
            exclude_none=True,
        )
        value["analysis_prompt"] = prompt_reference.model_dump(mode="json")
        return hashlib.sha256(cls._canonical(value).encode("utf-8")).hexdigest()

    async def _prompt_reference(self, version_id: str) -> PromptReference:
        document = await self._prompt_repository.get_version_by_id(
            "football", "analysis", version_id
        )
        if document is None:
            raise RankingReferenceNotFound(
                "analysis_prompt_version_id debe existir para football/analysis."
            )
        return PromptReference(
            prompt_id=document.get("prompt_id", "football.analysis"),
            version=int(document["version"]),
            version_id=document["version_id"],
        )

    async def _validate_prediction_references(
        self, payloads: list[FootballRankingCreate]
    ) -> None:
        for payload in payloads:
            for row in payload.rows:
                if row.prediction_id is None or row.version_id is None:
                    continue
                document = await self._prediction_repository.get_version_by_id(
                    row.prediction_id, row.version_id
                )
                if document is None:
                    raise RankingReferenceNotFound(
                        f"No existe prediction_id={row.prediction_id} con "
                        f"version_id={row.version_id}."
                    )
                match = document.get("match") or {}
                checks = {
                    "event_id": (document.get("event_id"), row.event_id),
                    "league": (match.get("league"), row.league.value),
                    "market": (document.get("market"), row.market.value),
                    "period": (document.get("period"), row.period.value),
                    "selection": (document.get("selection"), row.selection),
                    "line": (document.get("line"), row.line),
                    "team": (document.get("team"), row.team),
                    "player_id": (document.get("player_id"), row.player_id),
                }
                mismatch = [
                    key for key, (stored, submitted) in checks.items()
                    if stored != submitted
                ]
                if mismatch:
                    raise RankingReferenceNotFound(
                        "La referencia al pronóstico no coincide con la fila en: "
                        + ", ".join(mismatch)
                        + "."
                    )

    async def register_batch(
        self, batch: FootballRankingBatchCreate
    ) -> FootballRankingBatchResponse:
        received_at = self._clock().astimezone(UTC)

        # Preflight every external reference before any insert so a bad
        # reference cannot leave a partially accepted batch.
        references: list[PromptReference] = []
        for item in batch.items:
            references.append(await self._prompt_reference(item.analysis_prompt_version_id))
        await self._validate_prediction_references(batch.items)

        results: list[FootballRankingBatchItem] = []
        for item, prompt_reference in zip(batch.items, references, strict=True):
            try:
                results.append(
                    await self._register_one(item, prompt_reference, received_at)
                )
            except RankingRepositoryConflict as exc:
                results.append(
                    FootballRankingBatchItem(
                        status="rejected",
                        ranking_id=item.ranking_id,
                        idempotency_key=item.idempotency_key,
                        error=str(exc),
                    )
                )
        created = sum(result.status == "created" for result in results)
        replayed = sum(result.status == "replayed" for result in results)
        rejected = sum(result.status == "rejected" for result in results)
        return FootballRankingBatchResponse(
            received_at=received_at,
            total=len(results),
            created=created,
            replayed=replayed,
            rejected=rejected,
            items=results,
        )

    async def _register_one(
        self,
        payload: FootballRankingCreate,
        prompt_reference: PromptReference,
        received_at: datetime,
    ) -> FootballRankingBatchItem:
        request_hash = self._request_hash(payload, prompt_reference)
        existing = await self._repository.find_by_idempotency_key(
            payload.idempotency_key
        )
        if existing is not None:
            if existing.get("request_hash") != request_hash:
                return FootballRankingBatchItem(
                    status="rejected",
                    ranking_id=existing.get("ranking_id"),
                    idempotency_key=payload.idempotency_key,
                    error="idempotency_key ya existe con contenido distinto.",
                )
            return FootballRankingBatchItem(
                status="replayed",
                ranking_id=existing["ranking_id"],
                version=int(existing["version"]),
                version_id=existing["version_id"],
                idempotency_key=payload.idempotency_key,
                ranking=StoredFootballRanking(**existing),
            )

        ranking_id = payload.ranking_id or uuid.uuid4().hex
        previous = await self._repository.get_current(ranking_id)
        if previous is not None:
            identity = (
                "target_date", "analyst", "scope", "competition", "ranking_type"
            )
            new = payload.model_dump(mode="json")
            changed = [
                field for field in identity
                if previous.get(field) != new.get(field)
            ]
            if changed:
                return FootballRankingBatchItem(
                    status="rejected",
                    ranking_id=ranking_id,
                    idempotency_key=payload.idempotency_key,
                    error=(
                        "Una nueva versión debe conservar la identidad del ranking: "
                        + ", ".join(changed)
                        + "."
                    ),
                )

        document = payload.model_dump(mode="python")
        document["target_date"] = payload.target_date.isoformat()
        document.update(
            {
                "ranking_id": ranking_id,
                "version": int(previous["version"]) + 1 if previous else 1,
                "version_id": uuid.uuid4().hex,
                "is_current": True,
                "supersedes_version_id": (
                    previous.get("version_id") if previous else None
                ),
                "analysis_prompt": prompt_reference.model_dump(mode="json"),
                "received_at": received_at,
                "request_hash": request_hash,
            }
        )
        stored = await self._repository.publish(document, previous)
        return FootballRankingBatchItem(
            status="created",
            ranking_id=ranking_id,
            version=int(stored["version"]),
            version_id=stored["version_id"],
            idempotency_key=payload.idempotency_key,
            ranking=StoredFootballRanking(**stored),
        )

    async def list_rankings(
        self,
        *,
        target_date: date,
        league: FootballLeague | None = None,
        analyst: str | None = None,
        scope: RankingScope | None = None,
        ranking_type: str | None = None,
        include_versions: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> FootballRankingListResponse:
        query: dict[str, Any] = {"target_date": target_date.isoformat()}
        if not include_versions:
            query["is_current"] = True
        if league is not None:
            query["competition"] = league.value
        if analyst:
            query["analyst"] = analyst
        if scope is not None:
            query["scope"] = getattr(scope, "value", scope)
        if ranking_type is not None:
            query["ranking_type"] = getattr(ranking_type, "value", ranking_type)
        total = await self._repository.count_rankings(query)
        documents = await self._repository.find_rankings(
            query, skip=(page - 1) * page_size, limit=page_size
        )
        valid_items: list[StoredFootballRanking] = []
        for document in documents:
            try:
                valid_items.append(StoredFootballRanking(**document))
            except ValidationError:
                logger.exception(
                    "football_ranking.invalid_stored_document ranking_id=%s version=%s",
                    document.get("ranking_id"),
                    document.get("version"),
                )
        return FootballRankingListResponse(
            date=target_date,
            timezone="America/Mexico_City",
            page=page,
            page_size=page_size,
            total=total,
            items=valid_items,
        )

    async def get_ranking(
        self,
        ranking_id: str,
        *,
        version: int | None = None,
        version_id: str | None = None,
        history_page: int = 1,
        history_page_size: int = 50,
    ) -> FootballRankingDetailResponse:
        if version is not None and version_id is not None:
            raise ValueError("Especifica version o version_id, no ambos.")
        if version is not None:
            selected = await self._repository.get_version(ranking_id, version)
        elif version_id is not None:
            selected = await self._repository.get_version_by_id(ranking_id, version_id)
        else:
            selected = await self._repository.get_current(ranking_id)
        if selected is None:
            raise RankingNotFound(ranking_id)
        current = await self._repository.get_current(ranking_id)
        if current is None:
            raise RankingNotFound(ranking_id)
        total = await self._repository.count_rankings({"ranking_id": ranking_id})
        versions = await self._repository.list_versions(
            ranking_id,
            skip=(history_page - 1) * history_page_size,
            limit=history_page_size,
        )
        try:
            selected_model = StoredFootballRanking(**selected)
            version_models = [StoredFootballRanking(**item) for item in versions]
        except ValidationError as exc:
            logger.exception(
                "football_ranking.invalid_stored_document ranking_id=%s",
                ranking_id,
            )
            raise StoredRankingInvalid(
                f"El documento almacenado del ranking {ranking_id} no cumple "
                "el esquema de lectura."
            ) from exc
        return FootballRankingDetailResponse(
            ranking=selected_model,
            current_version=int(current["version"]),
            total_versions=total,
            history_page=history_page,
            history_page_size=history_page_size,
            versions=version_models,
        )
