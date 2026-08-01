from app.database.repository import PredictionRepository
from app.sports.baseball.models import (
    BaseballResultsUpdateResponse,
)
from app.sports.baseball.official_results import (
    KboOfficialResultsClient,
    MlbOfficialResultsClient,
)


class BaseballResultsUpdateService:
    def __init__(
        self,
        mlb_results: MlbOfficialResultsClient,
        kbo_results: KboOfficialResultsClient,
        repository: PredictionRepository,
    ) -> None:
        self._clients = {
            "MLB": mlb_results,
            "KBO": kbo_results,
        }
        self._repository = repository

    async def update(
        self,
        target_date,
        league: str,
    ) -> BaseballResultsUpdateResponse:
        official_games = await self._clients[league].get_results(target_date)
        final_games = [
            game.model_dump(mode="python")
            for game in official_games
            if game.is_final
            and game.home_score is not None
            and game.away_score is not None
        ]
        summary = await self._repository.update_baseball_market_results(
            requested_date=target_date.isoformat(),
            league=league,
            final_games=final_games,
        )
        return BaseballResultsUpdateResponse(
            date=target_date,
            league=league,
            official_games=len(official_games),
            final_games=len(final_games),
            **summary,
        )
