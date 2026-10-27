"""Servicio de registro, consulta, versionado y liquidación de pronósticos."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol

from app.prompts.models import PromptReference, PromptSport, PromptType
from app.sports.football.competitions.repository import CompetitionRepository
from app.sports.football.competitions.service import (
    CompetitionNotFound,
    CompetitionUnavailable,
)
from app.sports.football.predictions.catalog import (
    FootballLeague,
    KickoffSource,
    Period,
    SettlementStatus,
    TimingStatus,
    league_info,
)
from app.sports.football.predictions.models import (
    FootballEvaluationListResponse,
    FootballPredictionBatchItemResult,
    FootballPredictionBatchRequest,
    FootballPredictionBatchResponse,
    FootballPredictionCreate,
    FootballPredictionDetailResponse,
    FootballPredictionEvaluationCreate,
    FootballPredictionListResponse,
    FootballResultsUpdateError,
    StoredEvaluation,
    StoredPrediction,
)
from app.sports.football.predictions.observation import FootballObservation
from app.sports.football.predictions.repository import (
    FootballPredictionRepository,
    RepositoryConflict,
)
from app.sports.football.predictions.settlement import settle_prediction

if TYPE_CHECKING:
    from app.prompts.repository import PromptRepository

logger = logging.getLogger(__name__)

CDMX = timezone(timedelta(hours=-6))
IDENTITY_FIELDS = (
    "event_id",
    "market",
    "period",
    "selection",
    "line",
    "team",
    "player",
    "player_id",
    "home_goals",
    "away_goals",
)


class PredictionNotFound(LookupError):
    pass


class VersionNotFound(LookupError):
    pass


class PromptVersionNotFound(LookupError):
    pass


class KickoffResolver(Protocol):
    async def resolve_many(
        self, requests: list[tuple[int, str]]
    ) -> dict[int, datetime]: ...


class ObservationProvider(Protocol):
    async def get_observation(
        self, event_id: int, league_slug: str | None = None
    ) -> FootballObservation | None: ...


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _request_hash(
    item: FootballPredictionCreate, analysis_prompt: PromptReference
) -> str:
    payload = item.model_dump(
        mode="json",
        exclude={"idempotency_key"},
        exclude_none=True,
    )
    payload["analysis_prompt"] = analysis_prompt.model_dump(mode="json")
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _identity_hash(values: dict[str, Any]) -> str:
    subset = {key: values.get(key) for key in IDENTITY_FIELDS}
    return hashlib.sha256(_canonical(subset).encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class EspnKickoffResolver:
    """Resuelve el inicio real del partido desde el resumen de ESPN."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def resolve_many(
        self, requests: list[tuple[int, str]]
    ) -> dict[int, datetime]:
        unique: dict[int, str] = {}
        for event_id, league_slug in requests:
            unique.setdefault(event_id, league_slug)
        results = await asyncio.gather(
            *(
                self._client.get_kickoff(event_id, league_slug)
                for event_id, league_slug in unique.items()
            ),
            return_exceptions=True,
        )
        resolved: dict[int, datetime] = {}
        for (event_id, _), result in zip(unique.items(), results, strict=True):
            if isinstance(result, datetime):
                resolved[event_id] = _utc(result)
            elif isinstance(result, Exception):
                logger.warning(
                    "football.predictions.kickoff_lookup_failed event_id=%s type=%s",
                    event_id,
                    result.__class__.__name__,
                )
        return resolved


class FootballPredictionService:
    def __init__(
        self,
        repository: FootballPredictionRepository,
        *,
        kickoff_resolver: KickoffResolver | None = None,
        observation_provider: ObservationProvider | None = None,
        kickoff_timeout_seconds: float = 8.0,
        prompt_repository: PromptRepository | None = None,
        competition_repository: CompetitionRepository | None = None,
        clock: Any = None,
    ) -> None:
        self._repository = repository
        self._kickoff_resolver = kickoff_resolver
        self._observation_provider = observation_provider
        self._kickoff_timeout_seconds = kickoff_timeout_seconds
        self._prompt_repository = prompt_repository
        self._competition_repository = competition_repository
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _competition(self, code: str) -> dict[str, Any]:
        if self._competition_repository is not None:
            document = await self._competition_repository.get(code)
            if document is None:
                raise CompetitionNotFound(code)
            return document
        try:
            info = league_info(code)
        except (KeyError, ValueError) as exc:
            raise CompetitionNotFound(code) from exc
        return {
            "code": code,
            "name": info.name,
            "country": info.country,
            "active": True,
            "registration_available": True,
            "providers": {"espn": {"competition_id": info.espn_slug}},
            "capabilities": {
                "query": True,
                "automatic_settlement": info.automatic_settlement,
            },
        }

    async def register_batch(
        self, payload: FootballPredictionBatchRequest
    ) -> FootballPredictionBatchResponse:
        received_at = _utc(self._clock())
        if self._prompt_repository is None:
            raise RuntimeError("Repositorio de prompts no configurado.")
        prompt_document = await self._prompt_repository.get_version_by_id(
            PromptSport.FOOTBALL.value,
            PromptType.ANALYSIS.value,
            payload.analysis_prompt_version_id,
        )
        if prompt_document is None:
            raise PromptVersionNotFound(
                "analysis_prompt_version_id no existe para football/analysis."
            )
        analysis_prompt = PromptReference(
            prompt_id=prompt_document.get("prompt_id", "football.analysis"),
            version=int(prompt_document["version"]),
            version_id=prompt_document["version_id"],
        )
        competitions = {
            code: await self._competition(code)
            for code in {item.league for item in payload.items}
        }
        resolved: dict[int, datetime] = {}
        if self._kickoff_resolver is not None:
            requests: list[tuple[int, str]] = []
            seen: set[tuple[int, str]] = set()
            for item in payload.items:
                provider = (
                    competitions[item.league].get("providers") or {}
                ).get("espn") or {}
                provider_id = provider.get("competition_id") or provider.get(
                    "league_id"
                )
                if not provider_id:
                    continue
                key = (item.event_id, str(provider_id))
                if key not in seen:
                    seen.add(key)
                    requests.append(key)
            try:
                resolved = await asyncio.wait_for(
                    self._kickoff_resolver.resolve_many(requests),
                    timeout=self._kickoff_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - la fuente no debe bloquear
                logger.warning(
                    "football.predictions.kickoff_lookup_timeout type=%s",
                    exc.__class__.__name__,
                )

        results: list[FootballPredictionBatchItemResult] = []
        for item in payload.items:
            try:
                result = await self._register_item(
                    item, received_at, resolved, analysis_prompt,
                    competitions[item.league],
                )
            except RepositoryConflict as exc:
                result = self._rejected(item, str(exc))
            except CompetitionUnavailable as exc:
                result = self._rejected(item, str(exc))
            except RuntimeError:
                raise
            except Exception as exc:  # noqa: BLE001 - aislamos cada selección
                logger.exception(
                    "football.predictions.register_failed analyst=%s key=%s",
                    item.analyst,
                    item.idempotency_key,
                )
                result = self._rejected(
                    item,
                    f"Error inesperado al registrar: {exc.__class__.__name__}",
                )
            results.append(result)

        created = sum(1 for item in results if item.status == "created")
        replayed = sum(1 for item in results if item.status == "replayed")
        rejected = sum(1 for item in results if item.status == "rejected")
        return FootballPredictionBatchResponse(
            received_at=received_at,
            total=len(results),
            created=created,
            replayed=replayed,
            rejected=rejected,
            items=results,
        )

    async def _register_item(
        self,
        item: FootballPredictionCreate,
        received_at: datetime,
        resolved: dict[int, datetime],
        analysis_prompt: PromptReference,
        competition: dict[str, Any],
    ) -> FootballPredictionBatchItemResult:
        request_hash = _request_hash(item, analysis_prompt)
        existing = await self._repository.find_by_idempotency_key(
            item.idempotency_key
        )
        if existing is not None:
            if existing.get("request_hash") == request_hash:
                return self._replayed(existing)
            return self._rejected(
                item,
                "idempotency_key ya existe con un cuerpo distinto.",
            )

        if not competition.get("active") or not competition.get(
            "registration_available"
        ):
            raise CompetitionUnavailable(
                f"La competición {item.league} está inactiva o no acepta registros."
            )

        prediction_id = item.prediction_id or uuid.uuid4().hex
        previous = (
            await self._repository.get_current(prediction_id)
            if item.prediction_id
            else None
        )
        if previous is not None:
            if _identity_hash(previous) != _identity_hash(
                item.model_dump(mode="json")
            ):
                return self._rejected(
                    item,
                    "La nueva versión debe conservar event_id, market, period y "
                    "la identidad de la selección (selection, line, team, "
                    "player, player_id, home_goals, away_goals).",
                )
            version = int(previous["version"]) + 1
            supersedes = previous.get("version_id")
        else:
            version = 1
            supersedes = None

        document = self._build_document(
            item,
            received_at=received_at,
            prediction_id=prediction_id,
            version=version,
            supersedes_version_id=supersedes,
            request_hash=request_hash,
            previous=previous,
            provider_kickoff=resolved.get(item.event_id),
            analysis_prompt=analysis_prompt,
            competition=competition,
        )
        try:
            stored = await self._repository.insert_version(document, previous)
        except RepositoryConflict:
            # La operación que ganó puede haber confirmado el insert unos ms
            # después de que la restricción única rechazó esta petición.
            existing = None
            for attempt in range(5):
                existing = await self._repository.find_by_idempotency_key(
                    item.idempotency_key
                )
                if existing is not None:
                    break
                await asyncio.sleep(0.01 * (attempt + 1))
            if existing is not None and existing.get("request_hash") == request_hash:
                return self._replayed(existing)
            raise
        return self._created(stored)

    def _build_document(
        self,
        item: FootballPredictionCreate,
        *,
        received_at: datetime,
        prediction_id: str,
        version: int,
        supersedes_version_id: str | None,
        request_hash: str,
        previous: dict[str, Any] | None,
        provider_kickoff: datetime | None,
        analysis_prompt: PromptReference,
        competition: dict[str, Any],
    ) -> dict[str, Any]:
        kickoff_verified = provider_kickoff is not None
        if provider_kickoff is not None:
            kickoff = _utc(provider_kickoff)
            kickoff_source = KickoffSource.PROVIDER
        elif item.kickoff is not None:
            kickoff = _utc(item.kickoff)
            kickoff_source = KickoffSource.REQUEST
        elif previous is not None and previous.get("match", {}).get("kickoff"):
            kickoff = _utc(previous["match"]["kickoff"])
            kickoff_source = KickoffSource(
                previous["match"].get("kickoff_source")
                or KickoffSource.UNKNOWN
            )
            kickoff_verified = bool(
                previous["match"].get("kickoff_verified")
            )
        else:
            kickoff = None
            kickoff_source = KickoffSource.UNKNOWN
            kickoff_verified = False

        if kickoff is None or not kickoff_verified:
            timing_status = TimingStatus.UNVERIFIED
            received_before_kickoff = None
        else:
            received_before_kickoff = received_at < kickoff
            timing_status = (
                TimingStatus.PRE_MATCH
                if received_before_kickoff
                else TimingStatus.LATE
            )

        match_date = (
            kickoff.astimezone(CDMX).date()
            if kickoff is not None
            else item.match_date
        )

        return {
            "prediction_id": prediction_id,
            "version": version,
            "version_id": uuid.uuid4().hex,
            "is_current": True,
            "supersedes_version_id": supersedes_version_id,
            "idempotency_key": item.idempotency_key,
            "request_hash": request_hash,
            "event_id": item.event_id,
            "match": {
                "event_id": item.event_id,
                "date": match_date.isoformat(),
                "declared_date": item.match_date.isoformat(),
                "league": item.league,
                "league_name": competition["name"],
                "country": competition["country"],
                "home_team": item.home_team,
                "away_team": item.away_team,
                "kickoff": kickoff,
                "kickoff_source": kickoff_source.value,
                "kickoff_verified": kickoff_verified,
            },
            "market": item.market.value,
            "period": item.period.value,
            "selection": item.selection,
            "line": item.line,
            "team": item.team,
            "player": item.player,
            "player_id": item.player_id,
            "home_goals": item.home_goals,
            "away_goals": item.away_goals,
            "probability": item.probability,
            "confidence": item.confidence,
            "rationale": item.rationale,
            "sources": [
                source.model_dump(mode="json") for source in item.sources
            ],
            "analyst": item.analyst,
            "method_version": item.method_version,
            "analysis_prompt": analysis_prompt.model_dump(mode="json"),
            "generated_at": (
                _utc(item.generated_at) if item.generated_at else None
            ),
            "received_at": received_at,
            "timing": {
                "status": timing_status.value,
                "received_before_kickoff": received_before_kickoff,
            },
            "settlement_status": SettlementStatus.PENDIENTE.value,
            "settlement": None,
            "notes": item.notes,
            "created_at": received_at,
            "updated_at": received_at,
        }

    @staticmethod
    def _summary_fields(
        document: dict[str, Any],
    ) -> dict[str, Any]:
        timing = document.get("timing") or {}
        return {
            "prediction_id": document["prediction_id"],
            "version": document.get("version"),
            "version_id": document.get("version_id"),
            "idempotency_key": document["idempotency_key"],
            "analyst": document["analyst"],
            "probability": document["probability"],
            "received_before_kickoff": timing.get(
                "received_before_kickoff"
            ),
        }

    def _created(
        self, document: dict[str, Any]
    ) -> FootballPredictionBatchItemResult:
        return FootballPredictionBatchItemResult(
            status="created",
            record=StoredPrediction(**document),
            **self._summary_fields(document),
        )

    def _replayed(
        self, document: dict[str, Any]
    ) -> FootballPredictionBatchItemResult:
        return FootballPredictionBatchItemResult(
            status="replayed",
            record=StoredPrediction(**document),
            **self._summary_fields(document),
        )

    def _rejected(
        self, item: FootballPredictionCreate, error: str
    ) -> FootballPredictionBatchItemResult:
        return FootballPredictionBatchItemResult(
            prediction_id=item.prediction_id,
            version=None,
            version_id=None,
            idempotency_key=item.idempotency_key,
            status="rejected",
            error=error,
            analyst=item.analyst,
            probability=item.probability,
            received_before_kickoff=None,
        )

    async def list_predictions(
        self,
        *,
        match_date: date | None = None,
        match_date_from: date | None = None,
        match_date_to: date | None = None,
        received_date: date | None = None,
        league: str | None = None,
        event_id: int | None = None,
        analyst: str | None = None,
        market: str | None = None,
        settlement_status: SettlementStatus | None = None,
        period: Period | None = None,
        timing: TimingStatus | None = None,
        include_versions: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> FootballPredictionListResponse:
        query: dict[str, Any] = {}
        if not include_versions:
            query["is_current"] = True
        if match_date is not None:
            query["match.date"] = match_date.isoformat()
        elif match_date_from is not None or match_date_to is not None:
            date_filter: dict[str, str] = {}
            if match_date_from is not None:
                date_filter["$gte"] = match_date_from.isoformat()
            if match_date_to is not None:
                date_filter["$lte"] = match_date_to.isoformat()
            query["match.date"] = date_filter
        if received_date is not None:
            start = datetime.combine(
                received_date, datetime.min.time(), tzinfo=CDMX
            )
            end = start + timedelta(days=1)
            query["received_at"] = {
                "$gte": start.astimezone(UTC),
                "$lt": end.astimezone(UTC),
            }
        if league is not None:
            query["match.league"] = league
        if event_id is not None:
            query["event_id"] = event_id
        if analyst:
            query["analyst"] = analyst
        if market:
            query["market"] = market
        if settlement_status is not None:
            query["settlement_status"] = settlement_status.value
        if period is not None:
            query["period"] = period.value
        if timing is not None:
            query["timing.status"] = TimingStatus(timing).value

        total = await self._repository.count_predictions(query)
        documents = await self._repository.find_predictions(
            query,
            skip=(page - 1) * page_size,
            limit=page_size,
        )
        return FootballPredictionListResponse(
            items=[StoredPrediction(**document) for document in documents],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_prediction(
        self, prediction_id: str
    ) -> FootballPredictionDetailResponse:
        documents = await self._repository.list_versions(prediction_id)
        if not documents:
            raise PredictionNotFound(prediction_id)
        current = next(
            (item for item in documents if item.get("is_current")), None
        )
        pre_match = self._latest_verified_pre_match(documents)
        return FootballPredictionDetailResponse(
            prediction_id=prediction_id,
            total_versions=len(documents),
            current_version=(
                int(current["version"]) if current is not None else None
            ),
            latest_verified_pre_match_version=(
                int(pre_match["version"]) if pre_match is not None else None
            ),
            latest_verified_pre_match=(
                StoredPrediction(**pre_match) if pre_match is not None else None
            ),
            versions=[
                StoredPrediction(**document) for document in documents
            ],
        )

    @staticmethod
    def _latest_verified_pre_match(
        documents: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        candidates = [
            item
            for item in documents
            if (item.get("timing") or {}).get("status")
            == TimingStatus.PRE_MATCH.value
            and item.get("match", {}).get("kickoff_verified") is True
            and (item.get("timing") or {}).get("received_before_kickoff") is True
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: int(item["version"]))

    async def add_evaluation(
        self,
        prediction_id: str,
        payload: FootballPredictionEvaluationCreate,
    ) -> StoredEvaluation:
        documents = await self._repository.list_versions(prediction_id)
        if not documents:
            raise PredictionNotFound(prediction_id)
        target = next(
            (
                item
                for item in documents
                if item["version_id"] == payload.version_id
            ),
            None,
        )
        if target is None:
            raise VersionNotFound(
                f"{prediction_id} version_id {payload.version_id}"
            )
        if self._prompt_repository is None:
            raise RuntimeError("Repositorio de prompts no configurado.")
        evaluation_prompt_document = await self._prompt_repository.get_version_by_id(
            PromptSport.FOOTBALL.value,
            PromptType.EVALUATION.value,
            payload.evaluation_prompt_version_id,
        )
        if evaluation_prompt_document is None:
            raise PromptVersionNotFound(
                "evaluation_prompt_version_id no existe para football/evaluation."
            )
        evaluation_prompt = PromptReference(
            prompt_id=evaluation_prompt_document.get(
                "prompt_id", "football.evaluation"
            ),
            version=int(evaluation_prompt_document["version"]),
            version_id=evaluation_prompt_document["version_id"],
        )
        now = _utc(self._clock())
        document = {
            "prediction_id": prediction_id,
            "version": int(target["version"]),
            "version_id": target["version_id"],
            "evaluation_prompt": evaluation_prompt.model_dump(mode="json"),
            "analyst": payload.analyst,
            "diagnosis": payload.diagnosis,
            "learnings": payload.learnings,
            "sources": [
                source.model_dump(mode="json") for source in payload.sources
            ],
            "outcome_comment": payload.outcome_comment,
            "tags": payload.tags,
            "created_at": now,
        }
        stored = await self._repository.insert_evaluation(document)
        return StoredEvaluation(**stored)

    async def list_evaluations(
        self,
        prediction_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> FootballEvaluationListResponse:
        documents = await self._repository.list_versions(prediction_id)
        if not documents:
            raise PredictionNotFound(prediction_id)
        query = {"prediction_id": prediction_id}
        total = await self._repository.count_evaluations(query)
        items = await self._repository.find_evaluations(
            query, skip=(page - 1) * page_size, limit=page_size
        )
        return FootballEvaluationListResponse(
            items=[StoredEvaluation(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def settle_date(self, target_date: date) -> dict[str, Any]:
        if self._observation_provider is None:
            raise RuntimeError("No hay proveedor de observaciones configurado.")
        documents = await self._repository.find_predictions(
            {
                "match.date": target_date.isoformat(),
                "is_current": True,
            },
            limit=500,
            sort=[("event_id", 1)],
        )
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for document in documents:
            grouped[int(document["event_id"])].append(document)

        summary: dict[str, Any] = {
            "predictions_matched": len(documents),
            "predictions_settled": 0,
            "predictions_updated": 0,
            "predictions_pending": 0,
            "unmatched_event_ids": [],
            "errors": [],
        }
        settled_at = _utc(self._clock())
        for event_id, group in grouped.items():
            league = str(group[0]["match"]["league"])
            competition: dict[str, Any] | None = None
            if self._competition_repository is not None:
                competition = await self._competition_repository.get(league)
                provider = (competition or {}).get("providers") or {}
                espn = provider.get("espn") or {}
                league_slug = espn.get("competition_id") or espn.get("league_id")
                automatic_settlement = bool(
                    ((competition or {}).get("capabilities") or {}).get(
                        "automatic_settlement", False
                    )
                )
                competition_name = (competition or {}).get("name", league)
            else:
                try:
                    info = league_info(league)
                    league_slug = info.espn_slug
                    automatic_settlement = info.automatic_settlement
                    competition_name = info.name
                except (KeyError, ValueError):
                    league_slug = None
                    automatic_settlement = False
                    competition_name = league
            if not automatic_settlement or not league_slug:
                summary["predictions_pending"] += len(group)
                summary["errors"].append(
                    FootballResultsUpdateError(
                        event_id=event_id,
                        stage="coverage",
                        message=(
                            f"{competition_name} está habilitada para registro, "
                            "pero no tiene cobertura verificada para "
                            "liquidación automática."
                        ),
                    )
                )
                continue
            try:
                observation = await self._observation_provider.get_observation(
                    event_id, league_slug
                )
            except Exception as exc:  # noqa: BLE001 - se reporta por partido
                logger.warning(
                    "football.predictions.observation_failed event_id=%s type=%s",
                    event_id,
                    exc.__class__.__name__,
                )
                summary["errors"].append(
                    FootballResultsUpdateError(
                        event_id=event_id,
                        stage="observation",
                        message=(
                            "No se pudo consultar la fuente: "
                            f"{exc.__class__.__name__}."
                        ),
                    )
                )
                continue
            if observation is None:
                summary["unmatched_event_ids"].append(str(event_id))
                summary["errors"].append(
                    FootballResultsUpdateError(
                        event_id=event_id,
                        stage="observation",
                        message="La fuente no devolvió datos del partido.",
                    )
                )
                continue
            for document in group:
                result = settle_prediction(document, observation)
                summary["predictions_settled"] += 1
                if result.status == SettlementStatus.PENDIENTE:
                    summary["predictions_pending"] += 1
                    continue
                previous = document.get("settlement") or {}
                if (
                    previous.get("status") == result.status.value
                    and previous.get("observed") == result.observed
                    and previous.get("summary") == result.summary
                ):
                    continue
                settlement = {
                    "status": result.status.value,
                    "observed": result.observed,
                    "summary": result.summary,
                    "reason": result.reason,
                    "source": {
                        "name": observation.source.name,
                        "url": observation.source.url,
                        "retrieved_at": observation.source.retrieved_at,
                    },
                    "settled_at": settled_at,
                    "rule_version": result.rule_version,
                }
                summary["predictions_updated"] += (
                    await self._repository.update_settlement(
                        document["version_id"], settlement
                    )
                )
        return summary


__all__ = [
    "EspnKickoffResolver",
    "FootballPredictionService",
    "KickoffResolver",
    "ObservationProvider",
    "PredictionNotFound",
    "VersionNotFound",
]
