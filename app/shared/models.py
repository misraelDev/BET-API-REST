from datetime import date, datetime

from pydantic import BaseModel, Field


class PersistenceSummary(BaseModel):
    enabled: bool
    inserted: int = 0
    updated: int = 0
    collection: str | None = None
    error: str | None = None


class ProbabilitySet(BaseModel):
    home: float = Field(ge=0, le=100)
    draw: float = Field(ge=0, le=100)
    away: float = Field(ge=0, le=100)


class WeightContribution(BaseModel):
    component: str
    configured_weight: float
    effective_weight: float
    available: bool
    probabilities: ProbabilitySet | None = None


class FootballMarketProjection(BaseModel):
    selection: str | None = None
    line: float | None = None
    probability: float | None = Field(default=None, ge=0, le=100)
    projected_total: float | None = Field(default=None, ge=0)
    available: bool = False
    reason: str | None = None


class FootballMarkets(BaseModel):
    handicap: FootballMarketProjection
    double_chance: FootballMarketProjection
    goals: FootballMarketProjection
    corners: FootballMarketProjection
    cards: FootballMarketProjection


class FootballFusionSummary(BaseModel):
    method: str = "reliability_weighted_consensus"
    source_count: int
    providers: list[str]
    agreement: float = Field(ge=0, le=100)


class FixturePrediction(BaseModel):
    fixture_id: int
    kickoff: datetime
    timezone: str
    league_id: int
    league: str
    country: str | None = None
    home_team_id: int
    home_team: str
    away_team_id: int
    away_team: str
    data_quality_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    probabilities: ProbabilitySet
    predicted_result: str
    expected_goals_home: float | None = None
    expected_goals_away: float | None = None
    advice: str | None = None
    markets: FootballMarkets | None = None
    fusion: FootballFusionSummary | None = None
    weights: list[WeightContribution]
    warnings: list[str] = Field(default_factory=list)


class DailyPredictionResponse(BaseModel):
    requested_date: date
    timezone: str
    fixtures_found: int
    fixtures_eligible: int
    fixtures_returned: int
    model_version: str
    weights: dict[str, float]
    predictions: list[FixturePrediction]
    warnings: list[str] = Field(default_factory=list)
    persistence: PersistenceSummary | None = None


class TwoWayProbabilitySet(BaseModel):
    home: float = Field(ge=0, le=100)
    away: float = Field(ge=0, le=100)


class BaseballMarketProjection(BaseModel):
    scope: str = "full_game"
    handicap_team: str | None = None
    handicap_line: float | None = None
    handicap_confidence: float | None = Field(default=None, ge=0, le=100)
    total_line: float | None = None
    total_pick: str | None = None
    projected_total: float | None = Field(default=None, ge=0)
    total_confidence: float | None = Field(default=None, ge=0, le=100)


class SportGamePrediction(BaseModel):
    game_id: int
    kickoff: datetime
    league: str
    season: str
    home_team_id: int
    home_team: str
    away_team_id: int
    away_team: str
    data_quality_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    probabilities: TwoWayProbabilitySet
    predicted_result: str
    expected_score_home: float | None = None
    expected_score_away: float | None = None
    markets: BaseballMarketProjection | None = None
    available_components: list[str]
    warnings: list[str] = Field(default_factory=list)


class SportDailyPredictionResponse(BaseModel):
    sport: str
    requested_date: date
    timezone: str
    games_found: int
    games_returned: int
    model_version: str
    weights: dict[str, float]
    filters: dict[str, str] = Field(default_factory=dict)
    predictions: list[SportGamePrediction]
    warnings: list[str] = Field(default_factory=list)
    persistence: PersistenceSummary | None = None


class SportCapability(BaseModel):
    sport: str
    provider_product: str | None
    supported: bool
    endpoint: str | None
    model_version: str | None
    limitation: str | None = None
