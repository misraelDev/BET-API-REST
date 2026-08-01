import logging
from datetime import date
from typing import Any

from app.database.repository import PredictionRepository
from app.sports.baseball.enrichment.schedule_client import (
    PublicBaseballScheduleClient,
)

logger = logging.getLogger(__name__)
FINAL_STATUSES = {"FT", "FINAL"}


class BaseballSettlementService:
    def __init__(
        self,
        schedule_client: PublicBaseballScheduleClient,
        repository: PredictionRepository,
    ) -> None:
        self._schedule_client = schedule_client
        self._repository = repository

    async def settle_date(
        self,
        target_date: date,
        timezone: str,
        league: str = "all",
    ) -> dict[str, int]:
        games = await self._schedule_client.get_games(
            target_date.isoformat(),
            timezone,
        )
        final_games: dict[int, dict[str, Any]] = {}
        for game in games:
            game_league = str(game.get("league", {}).get("name", "")).casefold()
            status = str(game.get("status", {}).get("short", "")).upper()
            scores = game.get("scores", {})
            if (
                status in FINAL_STATUSES
                and scores.get("home") is not None
                and scores.get("away") is not None
                and (league == "all" or game_league == league.casefold())
            ):
                final_games[int(game["id"])] = game

        summary = await self._repository.settle_baseball_predictions(
            requested_date=target_date.isoformat(),
            final_games=final_games,
        )
        logger.info(
            "baseball.settlement date=%s final_games=%s settled=%s",
            target_date,
            len(final_games),
            summary["settled"],
        )
        return summary
