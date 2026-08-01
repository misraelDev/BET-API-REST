from app.shared.record_service import (
    BASEBALL_CONFIG,
    RecordBasedPredictionService,
)
from app.sports.baseball.models import BaseballLeague

LEAGUE_NAMES = {
    BaseballLeague.MLB: {"MLB"},
    BaseballLeague.KBO: {"KBO"},
}


class BaseballPredictionService(RecordBasedPredictionService):
    def __init__(self, client, standings_fallback=None) -> None:
        super().__init__(client, BASEBALL_CONFIG, standings_fallback)

    async def predict_league_date(
        self,
        target_date,
        timezone: str,
        limit: int,
        league: BaseballLeague,
    ):
        league_names = LEAGUE_NAMES.get(league)
        response = await self.predict_date(
            target_date,
            timezone,
            limit,
            league_names=league_names,
        )
        response.filters["league"] = league.value
        return response
