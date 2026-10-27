"""Schemas for analyst-authored football rankings."""

from __future__ import annotations

import math
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.prompts.models import PromptReference
from app.sports.football.predictions.catalog import (
    Market,
    Period,
    market_rule,
)

RANKING_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"


class RankingScope(StrEnum):
    LEAGUE = "league"
    GENERAL = "general"


class RankingType(StrEnum):
    FIRST_TEAM_TO_SCORE = "first_team_to_score"
    WINNER = "winner"
    BTTS = "btts"
    OVER_1_5_GOALS = "over_1_5_goals"
    SHOTS_MATCH = "shots_match"
    SHOTS_TEAM = "shots_team"
    SHOTS_PLAYER = "shots_player"
    SHOTS_ON_TARGET_MATCH = "shots_on_target_match"
    SHOTS_ON_TARGET_TEAM = "shots_on_target_team"
    SHOTS_ON_TARGET_PLAYER = "shots_on_target_player"
    CORNERS_MATCH = "corners_match"
    CORNERS_TEAM = "corners_team"
    CORNERS_HANDICAP = "corners_handicap"
    CORNERS_MOST = "corners_most"
    LEAGUE_MAIN_SELECTIONS = "league_main_selections"
    OVERALL_HIGH_CONFIDENCE = "overall_high_confidence"


class RankingMatchStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PLAY = "in_play"
    FINISHED = "finished"
    SUSPENDED = "suspended"
    POSTPONED = "postponed"
    UNKNOWN = "unknown"


class RankingRow(BaseModel):
    """A submitted row. Its list position and content are preserved verbatim."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1)
    league: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    event_id: int = Field(gt=0)
    home_team: str = Field(min_length=1, max_length=120)
    away_team: str = Field(min_length=1, max_length=120)
    kickoff: datetime | None = None
    match_status: RankingMatchStatus = RankingMatchStatus.UNKNOWN
    market: Market
    period: Period
    selection: str | None = None
    line: float | None = None
    team: Literal["home", "away"] | None = None
    player_id: str | None = Field(default=None, max_length=64)
    player: str | None = Field(default=None, max_length=120)
    home_goals: int | None = Field(default=None, ge=0, le=20)
    away_goals: int | None = Field(default=None, ge=0, le=20)
    estimate_status: Literal["estimated", "not_estimated"]
    probability: float | None = Field(default=None, ge=0, le=100)
    confidence: int | None = Field(default=None, ge=1, le=5)
    no_estimate_reason: str | None = Field(default=None, max_length=500)
    rationale: str | None = Field(default=None, max_length=4000)
    risk: str | None = Field(default=None, max_length=1000)
    expected_value: float | None = None
    expected_value_unit: str | None = Field(default=None, max_length=40)
    prediction_id: str | None = Field(default=None, pattern=RANKING_ID_PATTERN)
    version_id: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{32}$")

    @field_validator("kickoff")
    @classmethod
    def _aware_kickoff(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("kickoff debe incluir zona horaria.")
        return value

    @model_validator(mode="after")
    def _validate_row(self) -> Self:
        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError("home_team y away_team deben ser distintos.")
        if (self.prediction_id is None) != (self.version_id is None):
            raise ValueError("prediction_id y version_id deben enviarse juntos.")
        if (self.player_id is not None or self.player is not None) and not (
            self.player_id or self.player
        ):
            raise ValueError("La selección de jugador necesita una identidad.")

        rule = market_rule(self.market)
        if self.period not in rule.periods:
            raise ValueError(
                f"El mercado {self.market.value} no admite {self.period.value}."
            )
        if self.line is not None:
            step = 0.25 if self.market == Market.ASIAN_HANDICAP else 0.5
            if not math.isclose(self.line / step, round(self.line / step), abs_tol=1e-8):
                raise ValueError(f"line debe ser múltiplo de {step} para {self.market.value}.")
            if self.line == 0:
                raise ValueError("line no puede ser 0.")
        if rule.needs_line != (self.line is not None):
            raise ValueError(f"El mercado {self.market.value} requiere line={rule.needs_line}.")
        if rule.positive_line and self.line is not None and self.line < 0.5:
            raise ValueError(f"El mercado {self.market.value} requiere line >= 0.5.")
        if rule.needs_team != (self.team is not None):
            raise ValueError(f"El mercado {self.market.value} requiere team={rule.needs_team}.")
        if rule.needs_player and not (self.player_id or self.player):
            raise ValueError(f"El mercado {self.market.value} requiere player o player_id.")
        if not rule.needs_player and (self.player_id or self.player):
            raise ValueError(f"El mercado {self.market.value} no admite player.")
        if rule.selection_values:
            if self.selection not in rule.selection_values:
                raise ValueError(
                    f"selection inválida para {self.market.value}; valores: "
                    f"{', '.join(rule.selection_values)}."
                )
        elif self.selection is not None:
            raise ValueError(f"El mercado {self.market.value} no usa selection.")
        if rule.needs_score:
            if self.home_goals is None or self.away_goals is None:
                raise ValueError("exact_score requiere home_goals y away_goals.")
        elif self.home_goals is not None or self.away_goals is not None:
            raise ValueError(f"El mercado {self.market.value} no usa marcador exacto.")

        if self.estimate_status == "estimated":
            if self.probability is None or self.confidence is None:
                raise ValueError("Una fila estimada requiere probability y confidence.")
            if self.no_estimate_reason is not None:
                raise ValueError("no_estimate_reason solo aplica a una fila not_estimated.")
        elif self.probability is not None or self.confidence is not None:
            raise ValueError(
                "Una fila not_estimated no puede incluir probability ni confidence."
            )
        elif not self.no_estimate_reason:
            raise ValueError("Una fila sin estimación requiere no_estimate_reason.")

        if (self.expected_value is None) != (self.expected_value_unit is None):
            raise ValueError("expected_value y expected_value_unit deben enviarse juntos.")
        return self


class RankingCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches_considered: int | None = Field(default=None, ge=0)
    matches_with_rows: int | None = Field(default=None, ge=0)
    coverage_complete: bool
    limitations: list[str] = Field(default_factory=list, max_length=100)


class FootballRankingCreate(BaseModel):
    """An analyst-authored ranking document submitted for immutable storage."""

    model_config = ConfigDict(extra="forbid")

    ranking_id: str | None = Field(default=None, pattern=RANKING_ID_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    target_date: date
    timezone: str = Field(min_length=1, max_length=64)
    analyst: str = Field(min_length=2, max_length=80)
    scope: RankingScope
    competition: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    ranking_type: RankingType
    sort_criterion: str = Field(min_length=1, max_length=120)
    sort_direction: Literal["asc", "desc"]
    analysis_prompt_version_id: str = Field(pattern=r"^[A-Fa-f0-9]{32}$")
    method_version: str = Field(min_length=1, max_length=40)
    generated_at: datetime
    rows: list[RankingRow] = Field(min_length=1, max_length=10000)
    coverage: RankingCoverage

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone debe ser una zona IANA válida.") from exc
        return value

    @field_validator("generated_at")
    @classmethod
    def _aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at debe incluir zona horaria.")
        return value

    @model_validator(mode="after")
    def _validate_ranking(self) -> Self:
        if self.scope == RankingScope.LEAGUE and self.competition is None:
            raise ValueError("competition es obligatorio para scope=league.")
        if self.scope == RankingScope.GENERAL and self.competition is not None:
            raise ValueError("competition debe omitirse para scope=general.")
        if self.ranking_type == RankingType.OVERALL_HIGH_CONFIDENCE:
            if self.scope != RankingScope.GENERAL:
                raise ValueError("overall_high_confidence requiere scope=general.")
        elif self.scope == RankingScope.GENERAL:
            raise ValueError("scope=general requiere ranking_type=overall_high_confidence.")
        if self.ranking_type == RankingType.LEAGUE_MAIN_SELECTIONS and self.scope != RankingScope.LEAGUE:
            raise ValueError("league_main_selections requiere scope=league.")
        if self.scope == RankingScope.GENERAL and len({row.league for row in self.rows}) < 2:
            raise ValueError("Un ranking general debe incluir filas de al menos dos ligas.")

        positions = [row.position for row in self.rows]
        if positions != list(range(1, len(self.rows) + 1)):
            raise ValueError("rows debe conservar posiciones únicas, consecutivas y en orden 1..N.")
        for row in self.rows:
            if self.scope == RankingScope.LEAGUE and row.league != self.competition:
                raise ValueError("Cada fila de un ranking league debe usar su competition.")
            self._validate_row_type(row)
        return self

    def _validate_row_type(self, row: RankingRow) -> None:
        required_market: Market | None = {
            RankingType.FIRST_TEAM_TO_SCORE: Market.FIRST_TEAM_TO_SCORE,
            RankingType.WINNER: Market.ONE_X_TWO,
            RankingType.BTTS: Market.BTTS,
            RankingType.OVER_1_5_GOALS: Market.TOTAL_GOALS,
            RankingType.SHOTS_MATCH: Market.SHOTS_TOTAL,
            RankingType.SHOTS_TEAM: Market.SHOTS_TEAM,
            RankingType.SHOTS_PLAYER: Market.SHOTS_PLAYER,
            RankingType.SHOTS_ON_TARGET_MATCH: Market.SHOTS_ON_TARGET_TOTAL,
            RankingType.SHOTS_ON_TARGET_TEAM: Market.SHOTS_ON_TARGET_TEAM,
            RankingType.SHOTS_ON_TARGET_PLAYER: Market.SHOTS_ON_TARGET_PLAYER,
            RankingType.CORNERS_MATCH: Market.CORNERS_TOTAL,
            RankingType.CORNERS_TEAM: Market.CORNERS_TEAM,
            RankingType.CORNERS_HANDICAP: Market.CORNERS_HANDICAP,
            RankingType.CORNERS_MOST: Market.CORNERS_MOST,
        }.get(self.ranking_type)
        if required_market is not None and row.market != required_market:
            raise ValueError(
                f"ranking_type={self.ranking_type.value} requiere market={required_market.value}."
            )
        if self.ranking_type == RankingType.OVER_1_5_GOALS and (
            row.line != 1.5 or row.selection != "over"
        ):
            raise ValueError("over_1_5_goals requiere total_goals, line=1.5 y selection=over.")


class FootballRankingBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FootballRankingCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _unique_batch_keys(self) -> Self:
        idempotency_keys = [item.idempotency_key for item in self.items]
        if len(idempotency_keys) != len(set(idempotency_keys)):
            raise ValueError("idempotency_key debe ser única dentro del lote.")
        ranking_ids = [item.ranking_id for item in self.items if item.ranking_id]
        if len(ranking_ids) != len(set(ranking_ids)):
            raise ValueError("ranking_id debe ser único dentro del lote.")
        return self


class StoredFootballRanking(BaseModel):
    document_id: str
    ranking_id: str
    version: int
    version_id: str
    is_current: bool
    supersedes_version_id: str | None = None
    target_date: date
    timezone: str
    analyst: str
    scope: RankingScope
    competition: str | None = None
    ranking_type: RankingType
    sort_criterion: str
    sort_direction: Literal["asc", "desc"]
    analysis_prompt: PromptReference
    method_version: str
    generated_at: datetime
    received_at: datetime
    rows: list[RankingRow]
    coverage: RankingCoverage
    idempotency_key: str


class FootballRankingBatchItem(BaseModel):
    status: Literal["created", "replayed", "rejected"]
    ranking_id: str | None = None
    version: int | None = None
    version_id: str | None = None
    idempotency_key: str
    error: str | None = None
    ranking: StoredFootballRanking | None = None


class FootballRankingBatchResponse(BaseModel):
    received_at: datetime
    total: int
    created: int
    replayed: int
    rejected: int
    items: list[FootballRankingBatchItem]


class FootballRankingListResponse(BaseModel):
    date: date
    timezone: str
    page: int
    page_size: int
    total: int
    items: list[StoredFootballRanking]


class FootballRankingDetailResponse(BaseModel):
    ranking: StoredFootballRanking
    current_version: int
    total_versions: int
    history_page: int
    history_page_size: int
    versions: list[StoredFootballRanking]


__all__ = [
    "FootballRankingBatchCreate",
    "FootballRankingBatchResponse",
    "FootballRankingCreate",
    "FootballRankingDetailResponse",
    "FootballRankingListResponse",
    "FootballRankingBatchItem",
    "RankingCoverage",
    "RankingRow",
    "RankingScope",
    "RankingType",
    "StoredFootballRanking",
]
