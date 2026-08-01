"""Public response models for basketball."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.shared.models import (
    SportDailyPredictionResponse,
    SportGamePrediction,
    TwoWayProbabilitySet,
)


class BasketballLeague(StrEnum):
    ALL = "all"
    NBA = "nba"
    WNBA = "wnba"
    SUMMER_LEAGUE = "summer_league"


class NbaPredictionRequest(BaseModel):
    date: date
    timezone: str = "America/Mexico_City"
    limit: int = Field(default=20, ge=1, le=20)
    league: BasketballLeague = BasketballLeague.NBA


class NbaResultsUpdateRequest(BaseModel):
    date: date
    league: BasketballLeague = BasketballLeague.NBA


class NbaResultsUpdateResponse(BaseModel):
    date: date
    league: str
    official_games: int
    final_games: int
    predictions_matched: int
    predictions_updated: int


class StoredNbaPrediction(BaseModel):
    document_id: str
    sport: str
    event_id: int
    requested_date: str
    model_version: str
    provider: str
    timezone: str
    prediction: dict[str, Any]
    generated_at: datetime
    updated_at: datetime
    created_at: datetime
    settlement: dict[str, Any] | None = None

__all__ = [
    "SportDailyPredictionResponse",
    "SportGamePrediction",
    "TwoWayProbabilitySet",
]
