from datetime import date

import pytest

from app.shared.exceptions import ApiSportsRateLimitError
from app.sports.football.service import FootballPredictionService


class FakeClient:
    async def get_fixtures(self, target_date: str, timezone: str):
        return [
            {
                "fixture": {
                    "id": 10,
                    "date": f"{target_date}T20:00:00-06:00",
                    "status": {"short": "NS"},
                },
                "league": {
                    "id": 39,
                    "name": "Premier League",
                    "country": "England",
                    "season": 2026,
                },
                "teams": {
                    "home": {"id": 1, "name": "Home"},
                    "away": {"id": 2, "name": "Away"},
                },
            },
            {
                "fixture": {
                    "id": 11,
                    "date": "2026-07-27T00:00:00-06:00",
                    "status": {"short": "NS"},
                },
                "league": {
                    "id": 39,
                    "name": "Premier League",
                    "country": "England",
                    "season": 2026,
                },
                "teams": {
                    "home": {"id": 3, "name": "Wrong day"},
                    "away": {"id": 4, "name": "Ignored"},
                },
            },
        ]

    async def get_current_leagues(self):
        return [
            {
                "league": {"id": 39},
                "seasons": [
                    {
                        "year": 2026,
                        "coverage": {
                            "predictions": True,
                            "injuries": True,
                            "standings": True,
                            "fixtures": {
                                "statistics_fixtures": True,
                                "statistics_players": True,
                                "lineups": True,
                            },
                        },
                    }
                ],
            }
        ]

    async def get_prediction(self, fixture_id: int):
        return {
            "predictions": {
                "percent": {"home": "50%", "draw": "30%", "away": "20%"},
                "goals": {"home": "1.8", "away": "0.9"},
                "advice": "Home or draw",
            },
            "comparison": {
                "form": {"home": "60%", "away": "40%"},
                "att": {"home": "65%", "away": "35%"},
                "def": {"home": "55%", "away": "45%"},
                "poisson": {"home": "62%", "away": "38%"},
                "h2h": {"home": "58%", "away": "42%"},
            },
        }


class FallbackClient(FakeClient):
    async def get_fixtures(self, target_date: str, timezone: str):
        return [
            {
                "fixture": {
                    "id": fixture_id,
                    "date": f"{target_date}T20:00:00-06:00",
                    "status": {"short": "NS"},
                },
                "league": {
                    "id": 39,
                    "name": "Premier League",
                    "country": "England",
                    "season": 2026,
                },
                "teams": {
                    "home": {
                        "id": fixture_id * 2,
                        "name": f"Home {fixture_id}",
                    },
                    "away": {
                        "id": fixture_id * 2 + 1,
                        "name": f"Away {fixture_id}",
                    },
                },
            }
            for fixture_id in range(1, 6)
        ]

    async def get_prediction(self, fixture_id: int):
        if fixture_id in {1, 2}:
            raise RuntimeError("prediction unavailable")
        return await super().get_prediction(fixture_id)


class RateLimitedClient(FallbackClient):
    def __init__(self):
        self.requested_fixture_ids = []

    async def get_prediction(self, fixture_id: int):
        self.requested_fixture_ids.append(fixture_id)
        if fixture_id == 1:
            raise ApiSportsRateLimitError("rate limit")
        return await FakeClient.get_prediction(self, fixture_id)


@pytest.mark.asyncio
async def test_filters_exact_date_and_probabilities_sum_to_100():
    result = await FootballPredictionService(FakeClient()).predict_date(
        target_date=date(2026, 7, 26),
        timezone="America/Mexico_City",
        limit=20,
    )

    assert result.fixtures_found == 1
    assert result.fixtures_returned == 1
    prediction = result.predictions[0]
    total = (
        prediction.probabilities.home
        + prediction.probabilities.draw
        + prediction.probabilities.away
    )
    assert total == pytest.approx(100, abs=0.02)
    assert prediction.predicted_result == "home"
    assert prediction.confidence > 70


@pytest.mark.asyncio
async def test_uses_next_ranked_candidates_after_provider_failures():
    result = await FootballPredictionService(FallbackClient()).predict_date(
        target_date=date(2026, 7, 26),
        timezone="America/Mexico_City",
        limit=3,
    )

    assert result.fixtures_returned == 3
    assert {prediction.fixture_id for prediction in result.predictions} == {3, 4, 5}
    assert "Fallback aplicado" in result.warnings[0]
    assert "2 fallidos" in result.warnings[0]


@pytest.mark.asyncio
async def test_stops_before_next_batch_when_provider_rate_limit_is_reached():
    client = RateLimitedClient()

    result = await FootballPredictionService(client).predict_date(
        target_date=date(2026, 7, 26),
        timezone="America/Mexico_City",
        limit=3,
    )

    assert client.requested_fixture_ids == [1, 2, 3]
    assert result.fixtures_returned == 2
    assert any("limite temporal" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_filters_predictions_by_configured_football_league():
    client = FallbackClient()
    fixtures = await client.get_fixtures("2026-07-26", "America/Mexico_City")
    fixtures[2]["league"] = {
        "id": 4351,
        "name": "Brazilian Serie A",
        "country": "Brazil",
        "season": 2026,
    }
    client.get_fixtures = lambda target_date, timezone: _async_value(fixtures)

    result = await FootballPredictionService(client).predict_date(
        target_date=date(2026, 7, 26),
        timezone="America/Mexico_City",
        limit=3,
        league="brasileirao",
    )

    assert result.fixtures_found == 1
    assert result.predictions[0].league == "Brasileirão Betano"


async def _async_value(value):
    return value


def test_missing_components_renormalize_weights():
    final, contributions = FootballPredictionService._weighted_probabilities(
        {
            "api_base": (0.5, 0.3, 0.2),
            "form": None,
            "attack": None,
            "defense": None,
            "poisson": None,
            "h2h": None,
        }
    )

    assert final == pytest.approx((0.5, 0.3, 0.2))
    assert contributions[0].effective_weight == 1
    assert all(item.effective_weight == 0 for item in contributions[1:])


def test_football_markets_include_handicap_double_chance_and_goals():
    markets = FootballPredictionService._build_markets(
        "Home",
        "Away",
        (0.5, 0.3, 0.2),
        1.8,
        0.9,
    )

    assert markets.handicap.selection == "Home"
    assert markets.handicap.line == 0.5
    assert markets.double_chance.selection == "Home o empate"
    assert markets.goals.line == 2.5
    assert markets.goals.projected_total == 2.7
    assert markets.corners.available is False
    assert markets.cards.available is False


def test_api_goal_lines_are_not_treated_as_expected_goals():
    assert FootballPredictionService._expected_goal_value("-5") is None
    assert FootballPredictionService._expected_goal_value("-2.5") is None
    assert FootballPredictionService._expected_goal_value("1.8") == 1.8
