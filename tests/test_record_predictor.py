from datetime import date

import pytest

from app.shared.record_service import (
    BASEBALL_CONFIG,
    NBA_CONFIG,
    RecordBasedPredictionService,
)


class FakeRecordClient:
    def __init__(self, sport: str):
        self.sport = sport

    async def get_games(self, target_date: str, timezone: str):
        teams = (
            {
                "home": {"id": 1, "name": "Home"},
                "visitors": {"id": 2, "name": "Away"},
            }
            if self.sport == "nba"
            else {
                "home": {"id": 1, "name": "Home"},
                "away": {"id": 2, "name": "Away"},
            }
        )
        game_date = (
            {"start": f"{target_date}T20:00:00-06:00"}
            if self.sport == "nba"
            else f"{target_date}T20:00:00-06:00"
        )
        return [
            {
                "id": 50,
                "date": game_date,
                "status": {"short": "NS"},
                "league": {"id": 12, "name": "Test League", "season": 2026},
                "season": 2026,
                "teams": teams,
            }
        ]

    async def get_standings(self, league, season):
        return [
            {
                "team": {"id": 1, "name": "Home"},
                "games": {"played": 20},
                "win": {"total": 14, "home": 8, "lastTen": 7},
                "loss": {"total": 6, "home": 2, "lastTen": 3},
                "points": {"for": 2200, "against": 2100},
            },
            {
                "team": {"id": 2, "name": "Away"},
                "games": {"played": 20},
                "win": {"total": 8, "away": 3, "lastTen": 4},
                "loss": {"total": 12, "away": 7, "lastTen": 6},
                "points": {"for": 2050, "against": 2150},
            },
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sport", "config"),
    [("nba", NBA_CONFIG), ("baseball", BASEBALL_CONFIG)],
)
async def test_record_models_filter_date_and_return_two_way_probabilities(
    sport,
    config,
):
    result = await RecordBasedPredictionService(
        FakeRecordClient(sport),
        config,
    ).predict_date(
        target_date=date(2026, 7, 26),
        timezone="America/Mexico_City",
        limit=20,
    )

    assert result.sport == sport
    assert result.games_found == 1
    assert result.games_returned == 1
    prediction = result.predictions[0]
    assert prediction.home_team == "Home"
    assert prediction.away_team == "Away"
    assert prediction.predicted_result == "home"
    assert prediction.probabilities.home + prediction.probabilities.away == pytest.approx(
        100, abs=0.01
    )
    assert prediction.confidence > 70


def test_nested_standings_are_indexed():
    index = RecordBasedPredictionService._standings_index(
        [[{"team": {"id": 7}, "games": {"played": 10}}]]
    )
    assert index[7]["games"]["played"] == 10


def test_baseball_league_filter_matches_exact_provider_name():
    game = {"league": {"name": "KBO"}}

    assert RecordBasedPredictionService._matches_league(game, {"KBO"}) is True
    assert RecordBasedPredictionService._matches_league(game, {"MLB"}) is False
    assert RecordBasedPredictionService._matches_league(game, None) is True


def test_baseball_markets_use_reference_total_and_run_line():
    markets = RecordBasedPredictionService._baseball_markets(
        home_team="Home",
        away_team="Away",
        home_probability=0.65,
        expected_home=5.8,
        expected_away=3.1,
        data_quality=80,
        league="MLB",
    )

    assert markets.handicap_team == "Home"
    assert markets.handicap_line == -1.5
    assert markets.total_line == 8.5
    assert markets.total_pick == "over"
    assert markets.projected_total == 8.9


def test_baseball_markets_return_no_signal_without_run_data():
    markets = RecordBasedPredictionService._baseball_markets(
        home_team="Home",
        away_team="Away",
        home_probability=0.53,
        expected_home=None,
        expected_away=None,
        data_quality=56,
        league="KBO",
    )

    assert markets.handicap_team is None
    assert markets.total_pick is None


@pytest.mark.asyncio
async def test_empty_standings_use_validated_fallback_rows():
    client = FakeRecordClient("baseball")

    async def empty_standings(league, season):
        return []

    async def fallback(games):
        return (
            {
                1: {
                    "team": {"id": 1, "name": "Home"},
                    "games": {"played": 20},
                    "win": {"total": 15},
                    "loss": {"total": 5},
                    "points": {"for": 120, "against": 70},
                },
                2: {
                    "team": {"id": 2, "name": "Away"},
                    "games": {"played": 20},
                    "win": {"total": 5},
                    "loss": {"total": 15},
                    "points": {"for": 70, "against": 120},
                },
            },
            ["Datos web validados."],
        )

    client.get_standings = empty_standings
    result = await RecordBasedPredictionService(
        client,
        BASEBALL_CONFIG,
        standings_fallback=fallback,
    ).predict_date(
        target_date=date(2026, 7, 26),
        timezone="America/Mexico_City",
        limit=20,
    )

    prediction = result.predictions[0]
    assert "season_win_rate" in prediction.available_components
    assert "run_differential" in prediction.available_components
    assert prediction.data_quality_score > 70
    assert "Datos web validados." in result.warnings
