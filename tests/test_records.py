from datetime import date

import pytest

from app.records.models import RecordCreateRequest
from app.records.service import (
    ManualRecordService,
    build_document,
    canonical_league,
    resolve_event_id,
    resolve_kickoff,
)
from app.sports.baseball.enrichment.schedule_client import (
    PublicBaseballScheduleClient,
)


def football_payload(**overrides):
    data = {
        "sport": "football",
        "date": date(2026, 8, 1),
        "league": "liga mx",
        "event_id": 123456,
        "home_team": "América",
        "away_team": "Cruz Azul",
        "pick": "home",
        "probability": 54.0,
        "odds": 1.85,
        "stake": 2.0,
    }
    data.update(overrides)
    return RecordCreateRequest(**data)


def test_football_document_keeps_legacy_shape():
    identity, document = build_document(football_payload())

    assert identity == {
        "sport": "football",
        "event_id": 123456,
        "requested_date": "2026-08-01",
        "model_version": "manual-v1",
    }
    assert document["provider"] == "manual"
    assert document["model_version"] == "manual-v1"
    prediction = document["prediction"]
    assert prediction["fixture_id"] == 123456
    assert prediction["league"] == "Liga MX"
    assert prediction["predicted_result"] == "home"
    assert prediction["probabilities"] == {"home": 54.0, "draw": 0.0, "away": 0.0}
    assert prediction["source"] == "manual"
    assert prediction["markets"] is None


def test_tennis_document_uses_tour_as_league():
    payload = RecordCreateRequest(
        sport="tennis",
        date=date(2026, 8, 2),
        league="atp",
        event_id=9001,
        home_team="Sinner",
        away_team="Alcaraz",
        pick="away",
        tournament="Wimbledon",
    )

    identity, document = build_document(payload)

    assert "model_version" not in identity
    prediction = document["prediction"]
    assert prediction["league"] == "ATP"
    assert prediction["tour"] == "ATP"
    assert prediction["tournament"] == "Wimbledon"
    assert prediction["predicted_winner"] == "Alcaraz"
    assert prediction["markets"]["winner"]["selection"] == "Alcaraz"
    assert prediction["probabilities"]["player_two"] == 0.0


@pytest.mark.parametrize(
    ("sport", "value", "expected"),
    [
        ("football", "Liga MX", "Liga MX"),
        ("football", "  brasileirao   betano ", "Brasileirão Betano"),
        ("football", "leagues_cup", "Leagues Cup"),
        ("nba", "summer_league", "NBA - Summer League"),
        ("baseball", "mlb", "MLB"),
        ("tennis", "wta", "WTA"),
    ],
)
def test_canonical_league(sport, value, expected):
    assert canonical_league(sport, value) == expected


def test_canonical_league_rejects_unknown():
    with pytest.raises(ValueError, match="Competición no válida"):
        canonical_league("football", "Champions League")


def test_draw_is_football_only():
    with pytest.raises(ValueError, match="El empate"):
        RecordCreateRequest(
            sport="nba",
            date=date(2026, 8, 1),
            league="NBA",
            event_id=1,
            home_team="Lakers",
            away_team="Celtics",
            pick="draw",
        )


def test_event_id_required_outside_baseball():
    with pytest.raises(ValueError, match="event_id es obligatorio"):
        RecordCreateRequest(
            sport="tennis",
            date=date(2026, 8, 1),
            league="ATP",
            home_team="A",
            away_team="B",
            pick="home",
        )


def test_baseball_derives_event_id_from_teams():
    payload = RecordCreateRequest(
        sport="baseball",
        date=date(2026, 8, 1),
        league="MLB",
        home_team="Yankees",
        away_team="Red Sox",
        pick="home",
    )

    identity, document = build_document(payload)

    expected = PublicBaseballScheduleClient._stable_id(
        "MLB:game:2026-08-01:Red Sox:Yankees"
    )
    assert identity["event_id"] == expected
    assert document["event_id"] == expected


def test_kickoff_defaults_to_mexico_city_offset():
    payload = football_payload(kickoff=None)

    assert resolve_kickoff(payload) == "2026-08-01T00:00:00-06:00"


def test_explicit_event_id_wins_for_baseball():
    payload = RecordCreateRequest(
        sport="baseball",
        date=date(2026, 8, 1),
        league="KBO",
        event_id=777,
        home_team="Doosan Bears",
        away_team="LG Twins",
        pick="away",
    )

    assert resolve_event_id(payload, "KBO") == 777


class FakeCollection:
    def __init__(self):
        self.arguments = None

    async def find_one_and_update(self, identity, update, upsert, return_document):
        self.arguments = (identity, update, upsert, return_document)
        stored = {**identity, **update["$set"], **update["$setOnInsert"], "_id": "abc"}
        stored.setdefault("created_at", update["$set"]["generated_at"])
        stored["updated_at"] = update["$set"]["generated_at"]
        return stored


class FakeRepository:
    def __init__(self):
        self.collection = FakeCollection()

    async def upsert_record(self, identity, document):
        stored = await self.collection.find_one_and_update(
            identity,
            {"$set": document, "$setOnInsert": {"created_at": document["generated_at"]}},
            upsert=True,
            return_document=True,
        )
        stored["document_id"] = str(stored.pop("_id"))
        return stored


@pytest.mark.asyncio
async def test_service_returns_stored_record():
    stored = await ManualRecordService(FakeRepository()).register(football_payload())

    assert stored.document_id == "abc"
    assert stored.event_id == 123456
    assert stored.model_version == "manual-v1"
    assert stored.provider == "manual"
    assert stored.requested_date == "2026-08-01"
