"""Business rules for creating and administering football competitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.sports.football.competitions.models import (
    CompetitionCreate,
    CompetitionListResponse,
    CompetitionPatch,
    CompetitionRecord,
)
from app.sports.football.competitions.repository import CompetitionRepository


class CompetitionNotFound(LookupError):
    pass


class CompetitionUnavailable(LookupError):
    pass


class CompetitionService:
    def __init__(self, repository: CompetitionRepository, *, clock: Any = None) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(self, payload: CompetitionCreate) -> CompetitionRecord:
        now = self._clock().astimezone(UTC)
        document = payload.model_dump(mode="python")
        document.update({"created_at": now, "updated_at": now})
        try:
            stored = await self._repository.create(document)
        except ValueError:
            raise
        return CompetitionRecord(**stored)

    async def get(self, code: str) -> CompetitionRecord:
        document = await self._repository.get(code)
        if document is None:
            raise CompetitionNotFound(code)
        return CompetitionRecord(**document)

    async def require_registration(self, code: str) -> CompetitionRecord:
        competition = await self.get(code)
        if not competition.active:
            raise CompetitionUnavailable(f"La competición {code} está inactiva.")
        if not competition.registration_available:
            raise CompetitionUnavailable(
                f"La competición {code} no acepta nuevos registros."
            )
        return competition

    async def list(
        self,
        *,
        active: bool | None = None,
        country: str | None = None,
        competition_type: str | None = None,
        registration_available: bool | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> CompetitionListResponse:
        query: dict[str, Any] = {}
        if active is not None:
            query["active"] = active
        if country:
            query["country"] = country
        if competition_type:
            query["type"] = competition_type
        if registration_available is not None:
            query["registration_available"] = registration_available
        total = await self._repository.count(query)
        documents = await self._repository.list(
            query, skip=(page - 1) * page_size, limit=page_size
        )
        return CompetitionListResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=[CompetitionRecord(**item) for item in documents],
        )

    async def patch(
        self, code: str, payload: CompetitionPatch
    ) -> CompetitionRecord:
        current = await self._repository.get(code)
        if current is None:
            raise CompetitionNotFound(code)
        changes: dict[str, Any] = {}
        for field in payload.model_fields_set:
            value = getattr(payload, field)
            if field == "capabilities":
                if value is None:
                    continue
                for capability, flag in value.items():
                    changes[f"capabilities.{capability}"] = flag
            elif field == "providers":
                changes[field] = (
                    None
                    if value is None
                    else {
                        name: provider.model_dump(mode="python")
                        for name, provider in value.items()
                    }
                )
            elif value is not None:
                changes[field] = (
                    value.model_dump(mode="python")
                    if hasattr(value, "model_dump")
                    else value
                )

        resulting_providers = (
            changes.get("providers", current.get("providers"))
        )
        resulting_automatic = changes.get(
            "capabilities.automatic_settlement",
            (current.get("capabilities") or {}).get("automatic_settlement", False),
        )
        espn_provider = (resulting_providers or {}).get("espn") or {}
        if resulting_automatic and not (
            espn_provider.get("competition_id") or espn_provider.get("league_id")
        ):
            raise ValueError(
                "La liquidación automática requiere ESPN y su "
                "competition_id/league_id."
            )
        stored = await self._repository.patch(code, changes)
        if stored is None:
            raise CompetitionNotFound(code)
        return CompetitionRecord(**stored)
