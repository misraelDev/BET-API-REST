from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ExtractedTeamStats(BaseModel):
    team_name: str = Field(min_length=1, max_length=120)
    games_played: int | None = Field(default=None, ge=0, le=250)
    wins: int | None = Field(default=None, ge=0, le=250)
    losses: int | None = Field(default=None, ge=0, le=250)
    runs_for: float | None = Field(default=None, ge=0, le=3000)
    runs_against: float | None = Field(default=None, ge=0, le=3000)
    source_excerpt: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_record(self):
        if (
            self.games_played is not None
            and self.wins is not None
            and self.losses is not None
            and self.wins + self.losses > self.games_played
        ):
            raise ValueError("Las victorias y derrotas exceden los juegos disputados.")
        return self


class ExtractedScheduleGame(BaseModel):
    league: str
    home_team: str = Field(min_length=1, max_length=120)
    away_team: str = Field(min_length=1, max_length=120)
    kickoff: datetime
    status: str = Field(default="NS", max_length=20)
    home_score: int | None = Field(default=None, ge=0, le=100)
    away_score: int | None = Field(default=None, ge=0, le=100)


class EnrichmentEvidence(BaseModel):
    league: str
    source_name: str
    source_url: str
    fetched_at: datetime
    extraction_method: str = "html+parser"
    teams_requested: list[str]
    teams_mapped: list[str]
