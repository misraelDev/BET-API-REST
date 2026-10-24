from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_football_key: str = Field(default="", validation_alias="API_FOOTBALL_KEY")
    api_football_base_url: str = "https://v3.football.api-sports.io"
    football_data_api_key: str = Field(
        default="",
        validation_alias="FOOTBALL_DATA_API_KEY",
    )
    football_data_base_url: str = "https://api.football-data.org/v4"
    api_nba_base_url: str = "https://v2.nba.api-sports.io"
    mongodb_uri: str = ""
    mongodb_database: str = "sports_db"
    mongodb_collection: str = "predictions"
    mongodb_football_predictions_collection: str = "football_predictions"
    mongodb_football_evaluations_collection: str = (
        "football_prediction_evaluations"
    )
    mongodb_required: bool = False
    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"
    cors_origin_regex: str = r"^http://(localhost|127\.0\.0\.1):\d+$"
    request_timeout_seconds: float = 20.0
    cache_ttl_seconds: int = 900
    log_level: str = "INFO"
    log_api_responses: bool = True
    api_log_preview_chars: int = 2000
    web_enrichment_enabled: bool = True
    web_enrichment_timeout_seconds: float = 25.0
    baseball_settlement_enabled: bool = True
    baseball_settlement_interval_seconds: int = 600
    football_kickoff_lookup_enabled: bool = True
    football_kickoff_timeout_seconds: float = 8.0
    public_base_url: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
