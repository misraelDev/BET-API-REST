"""Prompt history and publication rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.prompts.models import Prompt, PromptCreate, PromptSport, PromptType
from app.prompts.repository import PromptRepository
from app.sports.football.predictions.repository import RepositoryConflict


class PromptNotFound(LookupError):
    pass


class PromptService:
    def __init__(self, repository: PromptRepository) -> None:
        self._repository = repository

    async def get(
        self,
        sport: PromptSport,
        prompt_type: PromptType,
        *,
        version: int | None = None,
        version_id: str | None = None,
    ) -> Prompt:
        if version is not None and version_id is not None:
            raise ValueError("Especifica version o version_id, no ambos.")
        if version is not None:
            document = await self._repository.get_version(
                sport.value, prompt_type.value, version
            )
        elif version_id is not None:
            document = await self._repository.get_version_by_id(
                sport.value, prompt_type.value, version_id
            )
        else:
            document = await self._repository.get_current(
                sport.value, prompt_type.value
            )
        if document is None:
            raise PromptNotFound(
                f"No hay prompt {sport.value}/{prompt_type.value} para esa versión."
            )
        document.pop("_id", None)
        return Prompt.model_validate(document)

    async def history(
        self, sport: PromptSport, prompt_type: PromptType
    ) -> list[Prompt]:
        documents = await self._repository.list_versions(
            sport.value, prompt_type.value
        )
        for document in documents:
            document.pop("_id", None)
        return [Prompt.model_validate(document) for document in documents]

    async def publish(
        self,
        sport: PromptSport,
        prompt_type: PromptType,
        payload: PromptCreate,
    ) -> Prompt:
        previous = await self._repository.get_current(
            sport.value, prompt_type.value
        )
        actual_base = previous.get("version_id") if previous else None
        if payload.base_version_id != actual_base:
            raise RepositoryConflict(
                "base_version_id no coincide con la versión vigente; consulta el prompt actual."
            )

        now = datetime.now(UTC)
        document: dict[str, Any] = {
            "sport": sport.value,
            "prompt_type": prompt_type.value,
            "prompt_id": f"{sport.value}.{prompt_type.value}",
            "version": int(previous["version"]) + 1 if previous else 1,
            "version_id": uuid.uuid4().hex,
            "is_current": True,
            "supersedes_version_id": actual_base,
            "prompt": payload.prompt,
            "author": payload.author,
            "change_summary": payload.change_summary,
            "created_at": now,
            "updated_at": now,
        }
        stored = await self._repository.publish(document, previous)
        stored.pop("_id", None)
        return Prompt.model_validate(stored)
