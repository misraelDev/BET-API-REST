from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.shared.models import PersistenceSummary


class TennisTour(StrEnum):
    ALL = "all"
    ATP = "atp"
    WTA = "wta"


class TennisPredictionRequest(BaseModel):
    date: date
    timezone: str = "America/Mexico_City"
    limit: int = Field(default=20, ge=1, le=200)
    page: int = Field(default=1, ge=1)
    tour: TennisTour = TennisTour.ALL


class TennisResultsUpdateRequest(BaseModel):
    date: date
    tour: TennisTour = TennisTour.ALL


class TennisResultsUpdateResponse(BaseModel):
    date: date
    tour: str
    official_matches: int
    final_matches: int
    predictions_matched: int
    predictions_updated: int


class TennisMatchCountResponse(BaseModel):
    date: date
    tour: str
    matches_found: int


class TennisProbabilities(BaseModel):
    player_one: float = Field(ge=0, le=100)
    player_two: float = Field(ge=0, le=100)


class TennisMarketProjection(BaseModel):
    selection: str | None = None
    line: float | None = None
    probability: float | None = Field(default=None, ge=0, le=100)
    projected_total: float | None = Field(default=None, ge=0)
    available: bool = False
    reason: str | None = None


class TennisMarkets(BaseModel):
    winner: TennisMarketProjection
    set_handicap: TennisMarketProjection
    total_games: TennisMarketProjection
    exact_sets: TennisMarketProjection


class TennisMatchPrediction(BaseModel):
    match_id: int
    kickoff: datetime
    league: str
    tour: str
    tournament: str
    season: str
    round: str | None = None
    player_one_id: str
    player_one: str
    player_two_id: str
    player_two: str
    data_quality_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    probabilities: TennisProbabilities
    predicted_winner: str
    markets: TennisMarkets
    available_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TennisDailyPredictionResponse(BaseModel):
    sport: str = "tennis"
    requested_date: date
    timezone: str
    matches_found: int
    matches_returned: int
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
    model_version: str = "tennis-form-v1"
    filters: dict[str, str] = Field(default_factory=dict)
    predictions: list[TennisMatchPrediction]
    warnings: list[str] = Field(default_factory=list)
    persistence: PersistenceSummary | None = None


class StoredTennisPrediction(BaseModel):
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
