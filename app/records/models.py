"""Modelos del registro manual (sustituye a la generación de predicciones)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.prompts.models import PromptReference

MANUAL_MODEL_VERSION = "manual-v1"

SportName = Literal["football", "nba", "baseball", "tennis"]
Pick = Literal["home", "draw", "away"]


class RecordCreateRequest(BaseModel):
    """Datos que el analista envía para registrar un partido y su pick."""

    sport: SportName
    date: Annotated[date, Field(description="Fecha del partido (YYYY-MM-DD).")]
    league: str = Field(
        min_length=1,
        description=(
            "Competición tal como la usa la API. Fútbol: Liga MX, "
            "Brasileirão Betano o Leagues Cup. NBA: NBA, WNBA o "
            "NBA - Summer League. Béisbol: MLB o KBO. Tenis: ATP o WTA."
        ),
    )
    event_id: int | None = Field(
        default=None,
        description=(
            "Identificador del partido en su fuente. Obligatorio en fútbol, "
            "NBA y tenis. En béisbol se calcula desde liga, fecha y equipos "
            "si no se envía."
        ),
    )
    home_team: str = Field(
        min_length=1,
        description="Local. En tenis, jugador uno.",
    )
    away_team: str = Field(
        min_length=1,
        description="Visitante. En tenis, jugador dos.",
    )
    pick: Pick = Field(
        description=(
            "Tu selección: home, draw o away. El empate solo existe en "
            "fútbol. En tenis, home es el jugador uno y away el jugador dos."
        )
    )
    analysis_prompt_version_id: str = Field(
        pattern=r"^[A-Fa-f0-9]{32}$",
        description=(
            "version_id exacto del prompt de análisis usado en esta ejecución. "
            "No sustituye a model_version ni a method_version."
        ),
    )
    kickoff: datetime | None = Field(
        default=None,
        description=(
            "Inicio en ISO-8601 con offset. Si se omite, se usa la fecha a "
            "las 00:00 con offset -06:00."
        ),
    )
    timezone: str = Field(default="America/Mexico_City")
    probability: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Probabilidad que le asignas a tu pick (0-100).",
    )
    odds: float | None = Field(
        default=None,
        gt=1,
        description="Cuota decimal del pick. Solo informativa.",
    )
    stake: float | None = Field(
        default=None,
        gt=0,
        description="Unidades apostadas. Solo informativa.",
    )
    tournament: str | None = Field(
        default=None,
        description="Torneo de tenis (Wimbledon, US Open...). Opcional.",
    )
    home_team_id: int | None = Field(
        default=None,
        description="Id del local o jugador uno en la fuente. Mejora la liquidación.",
    )
    away_team_id: int | None = Field(
        default=None,
        description="Id del visitante o jugador dos en la fuente.",
    )
    markets: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Mercados adicionales con la forma que espera la liquidación. "
            "Si se omite, solo se liquida el ganador."
        ),
    )
    notes: str | None = Field(default=None, description="Nota libre del analista.")

    @model_validator(mode="after")
    def _validate_consistency(self) -> "RecordCreateRequest":
        if self.pick == "draw" and self.sport != "football":
            raise ValueError("El empate (draw) solo aplica a fútbol.")
        if self.sport != "baseball" and self.event_id is None:
            raise ValueError(f"event_id es obligatorio para {self.sport}.")
        return self


class StoredRecord(BaseModel):
    """Documento guardado en MongoDB, tal como se devuelve al analista."""

    document_id: str
    sport: str
    event_id: int
    requested_date: str
    model_version: str
    provider: str
    timezone: str
    prediction: dict[str, Any]
    analysis_prompt: PromptReference | None = Field(
        default=None,
        description=(
            "Referencia exacta al prompt. Ausente en registros históricos "
            "cuyo prompt usado no se puede comprobar."
        ),
    )
    generated_at: datetime
    updated_at: datetime
    created_at: datetime
    settlement: dict[str, Any] | None = None


__all__ = [
    "MANUAL_MODEL_VERSION",
    "Pick",
    "RecordCreateRequest",
    "SportName",
    "StoredRecord",
]
