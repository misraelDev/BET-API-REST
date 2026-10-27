"""Contracts for the persisted football competition catalog."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COMPETITION_CODE_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


class CompetitionType(StrEnum):
    LEAGUE = "league"
    CUP = "cup"


class CompetitionCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: bool = True
    automatic_settlement: bool = False


class CompetitionProvider(BaseModel):
    """External identifiers are declarative; they do not imply an adapter exists."""

    model_config = ConfigDict(extra="allow")

    competition_id: str | int | None = None
    league_id: str | int | None = None
    country_id: str | int | None = None


class CompetitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=COMPETITION_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    country: str = Field(min_length=1, max_length=100)
    type: CompetitionType
    active: bool = True
    registration_available: bool = True
    providers: dict[str, CompetitionProvider] | None = None
    capabilities: CompetitionCapabilities = Field(
        default_factory=CompetitionCapabilities
    )

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not re.fullmatch(COMPETITION_CODE_PATTERN, value):
            raise ValueError(
                "code debe ser un identificador slug estable en minúsculas."
            )
        return value

    @field_validator("name", "country")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("El campo no puede quedar vacío.")
        return value

    @model_validator(mode="after")
    def _consistent_capabilities(self) -> Self:
        espn = (self.providers or {}).get("espn")
        if self.capabilities.automatic_settlement and not (
            espn and (espn.competition_id or espn.league_id)
        ):
            raise ValueError(
                "automatic_settlement requiere el adaptador ESPN y su "
                "competition_id/league_id; configurar el identificador no "
                "garantiza datos verificables."
            )
        return self


class CompetitionPatch(BaseModel):
    """Only explicitly supplied fields are patched; nested capabilities merge."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    country: str | None = Field(default=None, min_length=1, max_length=100)
    type: CompetitionType | None = None
    active: bool | None = None
    registration_available: bool | None = None
    providers: dict[str, CompetitionProvider] | None = None
    capabilities: dict[str, bool] | None = None

    @field_validator("name", "country")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("El campo no puede quedar vacío.")
        return value

    @field_validator("capabilities")
    @classmethod
    def _valid_capabilities(
        cls, value: dict[str, bool] | None
    ) -> dict[str, bool] | None:
        if value is not None:
            unknown = set(value) - {"query", "automatic_settlement"}
            if unknown:
                raise ValueError(
                    "Capacidades desconocidas: " + ", ".join(sorted(unknown))
                )
        return value

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("PATCH debe incluir al menos un campo.")
        null_disallowed = self.model_fields_set - {"providers", "capabilities"}
        for field in null_disallowed:
            if getattr(self, field) is None:
                raise ValueError(
                    f"{field} no puede ser null; omite el campo para conservarlo."
                )
        return self


class CompetitionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    country: str
    type: CompetitionType
    active: bool
    registration_available: bool
    providers: dict[str, CompetitionProvider] | None = None
    capabilities: CompetitionCapabilities
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class CompetitionListResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[CompetitionRecord]


__all__ = [
    "CompetitionCapabilities",
    "CompetitionCreate",
    "CompetitionListResponse",
    "CompetitionPatch",
    "CompetitionProvider",
    "CompetitionRecord",
    "CompetitionType",
]
