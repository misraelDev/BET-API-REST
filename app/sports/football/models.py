"""Public response models for football."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.shared.models import (
    DailyPredictionResponse,
    FixturePrediction,
    ProbabilitySet,
    WeightContribution,
)
from app.sports.football.predictions.models import FootballResultsUpdateError


class FootballResultsUpdateRequest(BaseModel):
    date: date


class FootballResultsUpdateResponse(BaseModel):
    date: date
    source: str = Field(
        default="ESPN public summary + TheSportsDB public schedule",
        description="Fuentes consultadas para actualizar resultados.",
    )
    official_fixtures: int
    final_fixtures: int
    predictions_matched: int = Field(
        description="Contador heredado de la colección predictions."
    )
    predictions_updated: int = Field(
        description="Contador heredado de la colección predictions."
    )
    football_predictions_matched: int = 0
    football_predictions_settled: int = 0
    football_predictions_updated: int = 0
    football_predictions_pending: int = 0
    unmatched_event_ids: list[str] = Field(default_factory=list)
    fixtures_without_predictions: list[int] = Field(default_factory=list)
    errors: list[FootballResultsUpdateError] = Field(default_factory=list)


class StoredFootballPrediction(BaseModel):
    document_id: str
    event_id: int
    requested_date: str
    model_version: str
    prediction: dict[str, Any]
    generated_at: datetime
    updated_at: datetime
    settlement: dict[str, Any] | None = None

__all__ = [
    "DailyPredictionResponse",
    "FixturePrediction",
    "ProbabilitySet",
    "WeightContribution",
    "FootballResultsUpdateRequest",
    "FootballResultsUpdateResponse",
    "StoredFootballPrediction",
]
