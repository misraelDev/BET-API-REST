from datetime import date

import pytest

from app.sports.tennis.models import TennisTour
from app.sports.tennis.service import TennisPredictionService


class FakeClient:
    async def scoreboard(self, tour, target_date, start_date=None):
        return [
            {
                "tour": "ATP",
                "tournament": "Test Open",
                "season": "2026",
                "match": {
                    "id": "10",
                    "date": "2026-08-01T18:00Z",
                    "status": {"type": {"state": "pre", "completed": False}},
                    "round": {"displayName": "Round 1"},
                    "competitors": [
                        {"id": "1", "order": 1, "athlete": {"displayName": "Player One"}},
                        {"id": "2", "order": 2, "athlete": {"displayName": "Player Two"}},
                    ],
                },
            }
        ]


@pytest.mark.asyncio
async def test_returns_atp_match_without_inventing_markets():
    result = await TennisPredictionService(FakeClient()).predict_date(
        date(2026, 8, 1), "America/Mexico_City", 20, TennisTour.ATP
    )

    assert result.matches_found == 1
    assert result.filters == {"tour": "atp"}
    prediction = result.predictions[0]
    assert prediction.tour == "ATP"
    assert prediction.predicted_winner == "insufficient_data"
    assert prediction.markets.winner.available is False
    assert prediction.markets.total_games.available is False
