from datetime import date

import httpx
import pytest

from app.sports.baseball.official_results import (
    KboOfficialResultsClient,
    MlbOfficialResultsClient,
)


@pytest.mark.asyncio
async def test_mlb_official_results_maps_final_score():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["sportId"] == "1"
        assert request.url.params["date"] == "2026-07-25"
        return httpx.Response(
            200,
            json={
                "dates": [
                    {
                        "games": [
                            {
                                "gamePk": 824244,
                                "gameDate": "2026-07-25T17:10:00Z",
                                "status": {
                                    "abstractGameState": "Final",
                                    "detailedState": "Final",
                                },
                                "teams": {
                                    "away": {
                                        "team": {"name": "Kansas City Royals"},
                                        "score": 3,
                                    },
                                    "home": {
                                        "team": {"name": "Detroit Tigers"},
                                        "score": 2,
                                    },
                                },
                            }
                        ]
                    }
                ]
            },
        )

    client = MlbOfficialResultsClient(
        transport=httpx.MockTransport(handler)
    )
    try:
        games = await client.get_results(date(2026, 7, 25))
    finally:
        await client.close()

    assert len(games) == 1
    assert games[0].official_id == 824244
    assert games[0].away_team == "Kansas City Royals"
    assert games[0].home_score == 2
    assert games[0].away_score == 3
    assert games[0].is_final is True


def test_kbo_official_results_parse_final_and_live_games():
    text = (
        "SAMSUNG 4 FINAL 1 DOOSAN JAMSIL 18:00 "
        "KT 0 BOT 6 13 LOTTE SAJIK 18:00"
    )

    games = KboOfficialResultsClient._parse_games(
        text,
        date(2026, 7, 25),
    )

    assert len(games) == 2
    assert games[0].away_team == "SAMSUNG"
    assert games[0].home_team == "DOOSAN"
    assert games[0].away_score == 4
    assert games[0].home_score == 1
    assert games[0].is_final is True
    assert games[1].status == "Live"
    assert games[1].detailed_status == "BOT 6"
    assert games[1].is_final is False
