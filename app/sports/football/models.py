"""Public response models for football."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.shared.models import (
    DailyPredictionResponse,
    FixturePrediction,
    ProbabilitySet,
    WeightContribution,
)


class FootballResultsUpdateRequest(BaseModel):
    date: date


class FootballResultsUpdateResponse(BaseModel):
    date: date
    official_fixtures: int
    final_fixtures: int
    predictions_matched: int
    predictions_updated: int


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
