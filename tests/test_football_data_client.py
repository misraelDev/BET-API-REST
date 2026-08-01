import json

import httpx
import pytest

from app.shared.exceptions import ApiSportsDailyLimitError, ApiSportsUnavailableError
from app.sports.football.football_data_client import FootballDataClient
from app.sports.football.resilient_client import ResilientFootballClient


MATCH = {
    "id": 100,
    "utcDate": "2026-07-26T18:00:00Z",
    "status": "TIMED",
    "competition": {
        "id": 2021,
        "name": "Premier League",
        "area": {"name": "England"},
    },
    "season": {"startDate": "2026-08-01"},
    "homeTeam": {"id": 1, "name": "Home"},
    "awayTeam": {"id": 2, "name": "Away"},
    "score": {"fullTime": {"home": None, "away": None}},
}


def football_data_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/matches"):
        return httpx.Response(200, json={"matches": [MATCH]})
    if request.url.path.endswith("/competitions"):
        return httpx.Response(
            200,
            json={"competitions": [{"id": 2021, "name": "Premier League"}]},
        )
    if request.url.path.endswith("/competitions/2021/standings"):
        table = [
            {
                "team": {"id": 1, "name": "Home"},
                "playedGames": 20,
                "won": 14,
                "draw": 3,
                "lost": 3,
                "goalsFor": 42,
                "goalsAgainst": 18,
                "form": "W,W,D,W,W",
            },
            {
                "team": {"id": 2, "name": "Away"},
                "playedGames": 20,
                "won": 6,
                "draw": 4,
                "lost": 10,
                "goalsFor": 22,
                "goalsAgainst": 35,
                "form": "L,D,L,W,L",
            },
        ]
        return httpx.Response(
            200,
            json={"standings": [{"type": "TOTAL", "table": table}]},
        )
    return httpx.Response(404, content=json.dumps({"message": "not found"}))


@pytest.mark.asyncio
async def test_football_data_adapts_matches_and_builds_statistical_prediction():
    client = FootballDataClient(
        api_key="test",
        base_url="https://api.football-data.test/v4",
        transport=httpx.MockTransport(football_data_transport),
    )

    fixtures = await client.get_fixtures("2026-07-26", "America/Mexico_City")
    prediction = await client.get_prediction(100)

    assert fixtures[0]["fixture"]["status"]["short"] == "NS"
    assert fixtures[0]["teams"]["home"]["name"] == "Home"
    assert prediction is not None
    assert float(prediction["predictions"]["percent"]["home"].rstrip("%")) > 50
    assert float(prediction["predictions"]["goals"]["home"]) > 0
    await client.close()


class ExhaustedPrimary:
    async def get_fixtures(self, target_date, timezone):
        raise ApiSportsDailyLimitError("daily quota")

    async def get_current_leagues(self):
        raise ApiSportsDailyLimitError("daily quota")

    async def get_prediction(self, fixture_id):
        raise AssertionError("fallback fixture must not use primary")

    async def close(self):
        return None


class SuspendedPrimary(ExhaustedPrimary):
    async def get_fixtures(self, target_date, timezone):
        raise ApiSportsUnavailableError("account suspended")

    async def get_current_leagues(self):
        raise ApiSportsUnavailableError("account suspended")


class EmptyPublicWeb:
    async def get_fixtures(self, target_date, timezone):
        return []

    async def get_current_leagues(self):
        return []

    async def get_prediction(self, fixture_id):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_resilient_client_switches_to_football_data_after_daily_limit():
    fallback = FootballDataClient(
        api_key="test",
        base_url="https://api.football-data.test/v4",
        transport=httpx.MockTransport(football_data_transport),
    )
    client = ResilientFootballClient(
        ExhaustedPrimary(),
        fallback,
        EmptyPublicWeb(),
    )

    fixtures = await client.get_fixtures("2026-07-26", "America/Mexico_City")
    leagues = await client.get_current_leagues()
    prediction = await client.get_prediction(100)

    assert fixtures[0]["fixture"]["source"] == "football-data.org"
    assert leagues[0]["league"]["id"] == 2021
    assert prediction is not None
    await client.close()


@pytest.mark.asyncio
async def test_resilient_client_switches_provider_when_primary_is_suspended():
    fallback = FootballDataClient(
        api_key="test",
        base_url="https://api.football-data.test/v4",
        transport=httpx.MockTransport(football_data_transport),
    )
    client = ResilientFootballClient(
        SuspendedPrimary(),
        fallback,
        EmptyPublicWeb(),
    )

    fixtures = await client.get_fixtures("2026-07-26", "America/Mexico_City")

    assert fixtures[0]["fixture"]["source"] == "football-data.org"
    await client.close()
