"""Contracts for versioned analyst prompts."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PromptSport(StrEnum):
    FOOTBALL = "football"
    NBA = "nba"
    BASEBALL = "baseball"
    TENNIS = "tennis"


class PromptType(StrEnum):
    ANALYSIS = "analysis"
    EVALUATION = "evaluation"


VERSION_ID_PATTERN = r"^[A-Fa-f0-9]{32}$"


class PromptCreate(BaseModel):
    """Publish a new immutable prompt revision, based on an exact revision."""

    model_config = ConfigDict(extra="forbid")

    base_version_id: str | None = Field(
        description=(
            "Exact current version being revised. Send null only when creating "
            "the first version; required to prevent stale concurrent updates."
        ),
        examples=["9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f"],
    )
    prompt: str = Field(min_length=1, max_length=100_000)
    author: str = Field(min_length=1, max_length=120)
    change_summary: str = Field(min_length=1, max_length=1000)

    @field_validator("base_version_id")
    @classmethod
    def _validate_base_version_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(VERSION_ID_PATTERN, value):
            raise ValueError("base_version_id debe ser un version_id válido.")
        return value

    @field_validator("prompt", "author", "change_summary")
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El valor no puede quedar vacío.")
        return value


class Prompt(BaseModel):
    """Stored immutable prompt revision returned by the prompt API."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    sport: PromptSport
    prompt_type: PromptType
    version: int = Field(ge=1)
    version_id: str = Field(pattern=VERSION_ID_PATTERN)
    is_current: bool
    supersedes_version_id: str | None = Field(
        default=None, pattern=VERSION_ID_PATTERN
    )
    prompt: str
    author: str
    change_summary: str
    created_at: datetime
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _created_at_is_aware(self) -> Self:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at debe incluir zona horaria.")
        if (
            self.updated_at is not None
            and (self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None)
        ):
            raise ValueError("updated_at debe incluir zona horaria.")
        return self


class PromptVersionListResponse(BaseModel):
    sport: PromptSport
    prompt_type: PromptType
    total: int = Field(ge=0)
    current_version: int | None = None
    items: list[Prompt]
