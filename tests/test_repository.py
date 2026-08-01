from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.database.repository import PredictionRepository
from app.shared.models import (
    DailyPredictionResponse,
    FixturePrediction,
    ProbabilitySet,
)


class FakeCollection:
    def __init__(self):
        self.calls = 0

    async def update_one(self, identity, update, upsert):
        self.calls += 1
        assert upsert is True
        assert identity["sport"] == "football"
        assert update["$set"]["prediction"]["fixture_id"] == 99
        return SimpleNamespace(
            upserted_id="new-id" if self.calls == 1 else None,
            matched_count=0 if self.calls == 1 else 1,
        )


def make_response():
    return DailyPredictionResponse(
        requested_date=date(2026, 7, 26),
        timezone="America/Mexico_City",
        fixtures_found=1,
        fixtures_eligible=1,
        fixtures_returned=1,
        model_version="test-v1",
        weights={"form": 1.0},
        predictions=[
            FixturePrediction(
                fixture_id=99,
                kickoff=datetime.fromisoformat("2026-07-26T20:00:00-06:00"),
                timezone="America/Mexico_City",
                league_id=1,
                league="Test League",
                home_team_id=10,
                home_team="Home",
                away_team_id=20,
                away_team="Away",
                data_quality_score=80,
                confidence=75,
                probabilities=ProbabilitySet(home=50, draw=30, away=20),
                predicted_result="home",
                weights=[],
            )
        ],
    )


@pytest.mark.asyncio
async def test_repository_upserts_instead_of_duplicating():
    repository = PredictionRepository("", "sports_db", "predictions")
    repository._collection = FakeCollection()

    first = await repository.save_response("football", make_response())
    second = await repository.save_response("football", make_response())

    assert first.inserted == 1
    assert first.updated == 0
    assert second.inserted == 0
    assert second.updated == 1


@pytest.mark.asyncio
async def test_repository_reports_disabled_without_uri():
    repository = PredictionRepository("", "sports_db", "predictions")
    await repository.connect()

    result = await repository.save_response("football", make_response())

    assert result.enabled is False
    assert "MONGODB_URI" in result.error


def test_baseball_settlement_scores_each_market_independently():
    prediction = {
        "home_team": "Home",
        "away_team": "Away",
        "predicted_result": "home",
        "markets": {
            "handicap_team": "Home",
            "handicap_line": -1.5,
            "total_pick": "over",
            "total_line": 8.5,
        },
    }
    game = {"scores": {"home": 5, "away": 4}}

    settlement = PredictionRepository._build_baseball_settlement(
        prediction,
        game,
        datetime.fromisoformat("2026-07-26T12:00:00+00:00"),
    )

    assert settlement["outcome"] == "won"
    assert settlement["handicap_outcome"] == "lost"
    assert settlement["total_outcome"] == "won"
    assert settlement["moneyline_units"] == 100
    assert settlement["handicap_units"] == -100
    assert settlement["total_units"] == 100
    assert settlement["net_units"] == 100


def test_baseball_settlement_marks_wrong_winner_lost():
    prediction = {
        "home_team": "Home",
        "away_team": "Away",
        "predicted_result": "away",
        "markets": {},
    }
    game = {"scores": {"home": 6, "away": 2}}

    settlement = PredictionRepository._build_baseball_settlement(
        prediction,
        game,
        datetime.fromisoformat("2026-07-26T12:00:00+00:00"),
    )

    assert settlement["outcome"] == "lost"
    assert settlement["handicap_outcome"] is None
    assert settlement["total_outcome"] is None
    assert settlement["moneyline_units"] == -100
    assert settlement["handicap_units"] is None
    assert settlement["total_units"] is None
    assert settlement["net_units"] == -100


def test_market_units_handle_push_and_missing_market():
    assert PredictionRepository._outcome_units("won") == 100
    assert PredictionRepository._outcome_units("lost") == -100
    assert PredictionRepository._outcome_units("push") == 0
    assert PredictionRepository._outcome_units(None) is None


def test_tennis_settlement_scores_markets_and_units():
    prediction = {
        "player_one_id": "1", "player_one": "Player A",
        "player_two_id": "2", "player_two": "Player B",
        "markets": {
            "winner": {"available": True, "selection": "Player A"},
            "set_handicap": {"available": True, "selection": "Player A", "line": 1.5},
            "total_games": {"available": True, "selection": "Más", "line": 20.5},
            "exact_sets": {"available": True, "selection": "Player A 2-0"},
        },
    }
    match = {
        "competitors": [
            {"id": "1", "winner": True, "athlete": {"displayName": "Player A"},
             "linescores": [{"value": 6, "winner": True}, {"value": 6, "winner": True}]},
            {"id": "2", "winner": False, "athlete": {"displayName": "Player B"},
             "linescores": [{"value": 4, "winner": False}, {"value": 3, "winner": False}]},
        ]
    }

    settlement = PredictionRepository._build_tennis_settlement(
        prediction, match, datetime.fromisoformat("2026-08-01T12:00:00+00:00")
    )

    assert settlement["markets"]["winner"]["outcome"] == "won"
    assert settlement["markets"]["set_handicap"]["outcome"] == "won"
    assert settlement["markets"]["total_games"]["outcome"] == "lost"
    assert settlement["markets"]["exact_sets"]["outcome"] == "won"
    assert settlement["net_units"] == 200


class FakeMarketCursor:
    async def to_list(self, length):
        return [
            {
                "_id": "prediction-id",
                "prediction": {
                    "home_team": "Detroit Tigers",
                    "away_team": "Kansas City Royals",
                    "predicted_result": "away",
                    "markets": {
                        "handicap_team": "Kansas City Royals",
                        "handicap_line": 1.5,
                        "total_pick": "under",
                        "total_line": 8.5,
                    },
                },
            }
        ]


class FakeMarketCollection:
    def __init__(self):
        self.update = None

    def find(self, query):
        assert query["requested_date"] == "2026-07-25"
        assert query["prediction.league"]["$regex"] == "^MLB$"
        return FakeMarketCursor()

    async def update_one(self, identity, update):
        assert identity == {"_id": "prediction-id"}
        self.update = update
        return SimpleNamespace(modified_count=1)


@pytest.mark.asyncio
async def test_market_result_update_only_writes_settlement_metadata():
    repository = PredictionRepository("", "sports_db", "predictions")
    collection = FakeMarketCollection()
    repository._collection = collection

    summary = await repository.update_baseball_market_results(
        requested_date="2026-07-25",
        league="MLB",
        final_games=[
            {
                "home_team": "Detroit Tigers",
                "away_team": "Kansas City Royals",
                "home_score": 2,
                "away_score": 3,
            }
        ],
    )

    assert summary["predictions_updated"] == 1
    assert set(collection.update["$set"]) == {"settlement", "updated_at"}
    settlement = collection.update["$set"]["settlement"]
    assert settlement["outcome"] == "won"
    assert settlement["handicap_outcome"] == "won"
    assert settlement["total_outcome"] == "won"


def test_kbo_team_names_are_normalized_to_official_codes():
    assert PredictionRepository._normalize_team("Lotte Giants") == "lotte"
    assert PredictionRepository._normalize_team("KT Wiz Suwon") == "kt"
    assert PredictionRepository._normalize_team("Hanwha Eagles") == "hanwha"


class FakeFilteredCursor:
    def __init__(self):
        self.skipped = 0
        self.limited = 0

    def sort(self, field, direction):
        return self

    def limit(self, limit):
        self.limited = limit
        return self

    def skip(self, offset):
        self.skipped = offset
        return self

    async def to_list(self, length):
        return []


class FakeFilteredCollection:
    def __init__(self):
        self.query = None
        self.cursor = FakeFilteredCursor()

    def find(self, query):
        self.query = query
        return self.cursor

    async def count_documents(self, query):
        self.query = query
        return 73


@pytest.mark.asyncio
async def test_results_query_filters_exact_baseball_league():
    repository = PredictionRepository("", "sports_db", "predictions")
    collection = FakeFilteredCollection()
    repository._collection = collection

    await repository.list_predictions(
        sport="baseball",
        requested_date="2026-07-26",
        league="kbo",
    )

    assert collection.query["requested_date"] == "2026-07-26"
    assert collection.query["prediction.league"] == {
        "$regex": "^kbo$",
        "$options": "i",
    }


@pytest.mark.asyncio
async def test_results_query_applies_offset_limit_and_matching_count_filter():
    repository = PredictionRepository("", "sports_db", "predictions")
    collection = FakeFilteredCollection()
    repository._collection = collection

    total = await repository.count_predictions(
        sport="tennis", requested_date="2026-08-01", league="atp"
    )
    await repository.list_predictions(
        sport="tennis", requested_date="2026-08-01", league="atp",
        limit=20, offset=40,
    )

    assert total == 73
    assert collection.cursor.skipped == 40
    assert collection.cursor.limited == 20
    assert collection.query["prediction.league"]["$regex"] == "^atp$"


def test_dashboard_stats_aggregate_markets_and_units():
    stats = PredictionRepository._aggregate_baseball_stats(
        [
            {
                "requested_date": "2026-07-25",
                "prediction": {
                    "league": "MLB",
                    "home_team": "Home",
                    "away_team": "Away",
                },
                "settlement": {
                    "outcome": "won",
                    "handicap_outcome": "lost",
                    "total_outcome": "push",
                    "moneyline_units": 100,
                    "handicap_units": -100,
                    "total_units": 0,
                    "net_units": 0,
                },
            }
        ]
    )

    assert stats["summary"]["settled_predictions"] == 1
    assert stats["summary"]["evaluated_bets"] == 3
    assert stats["summary"]["hit_rate"] == 50.0
    assert stats["summary"]["net_units"] == 0
    assert stats["markets"][0]["hit_rate"] == 100.0
    assert stats["daily"][0]["won"] == 1


def test_football_settlement_scores_dynamic_markets():
    settlement = PredictionRepository._build_football_settlement(
        {
            "home_team": "Home",
            "away_team": "Away",
            "predicted_result": "home",
            "markets": {
                "handicap": {"available": True, "selection": "Home", "line": 0.5},
                "double_chance": {"available": True, "selection": "Home o empate"},
                "goals": {"available": True, "selection": "Más", "line": 2.5},
            },
        },
        {"goals": {"home": 2, "away": 1}},
        datetime.fromisoformat("2026-07-26T12:00:00+00:00"),
    )

    assert settlement["markets"]["winner"]["outcome"] == "won"
    assert settlement["markets"]["handicap"]["outcome"] == "won"
    assert settlement["markets"]["double_chance"]["outcome"] == "won"
    assert settlement["markets"]["goals"]["outcome"] == "won"
    assert settlement["markets"]["corners"]["outcome"] is None
    assert settlement["net_units"] == 400
