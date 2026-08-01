"""Public response models for baseball."""

from enum import StrEnum
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.shared.models import (
    BaseballMarketProjection,
    SportDailyPredictionResponse,
    SportGamePrediction,
    TwoWayProbabilitySet,
)


class BaseballLeague(StrEnum):
    ALL = "all"
    MLB = "mlb"
    KBO = "kbo"


class BaseballPredictionRequest(BaseModel):
    date: date
    timezone: str = "America/Mexico_City"
    limit: int = Field(default=20, ge=1, le=20)
    league: BaseballLeague = BaseballLeague.ALL


class BaseballResultsUpdateRequest(BaseModel):
    date: date
    league: BaseballLeague


class BaseballResultsUpdateResponse(BaseModel):
    date: date
    league: str
    official_games: int
    final_games: int
    predictions_matched: int
    predictions_updated: int
    not_found: list[str] = Field(default_factory=list)


class StoredBaseballPrediction(BaseModel):
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
    status: str = "pending"
    settlement: dict[str, Any] | None = None


class OfficialBaseballGame(BaseModel):
    official_id: int
    league: str
    game_date: datetime
    status: str
    detailed_status: str
    home_team: str
    away_team: str
    home_score: int | None = None
    away_score: int | None = None
    is_final: bool


__all__ = [
    "BaseballLeague",
    "BaseballMarketProjection",
    "BaseballPredictionRequest",
    "BaseballResultsUpdateRequest",
    "BaseballResultsUpdateResponse",
    "OfficialBaseballGame",
    "StoredBaseballPrediction",
    "SportDailyPredictionResponse",
    "SportGamePrediction",
    "TwoWayProbabilitySet",
]
