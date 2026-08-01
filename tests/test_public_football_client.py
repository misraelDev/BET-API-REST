import httpx
import pytest
from datetime import date

from app.sports.football.public_web_client import PublicWebFootballClient


EVENTS = [
    {
        "idEvent": "10",
        "strTimestamp": "2026-07-18T02:00:00",
        "dateEvent": "2026-07-18",
        "dateEventLocal": "2026-07-17",
        "strStatus": "FT",
        "strSeason": "2026-2027",
        "idHomeTeam": "1",
        "strHomeTeam": "Home",
        "idAwayTeam": "3",
        "strAwayTeam": "Past Rival",
        "intHomeScore": "3",
        "intAwayScore": "0",
    },
    {
        "idEvent": "11",
        "strTimestamp": "2026-07-20T02:00:00",
        "dateEvent": "2026-07-20",
        "dateEventLocal": "2026-07-19",
        "strStatus": "FT",
        "strSeason": "2026-2027",
        "idHomeTeam": "4",
        "strHomeTeam": "Past Rival 2",
        "idAwayTeam": "2",
        "strAwayTeam": "Away",
        "intHomeScore": "2",
        "intAwayScore": "0",
    },
    {
        "idEvent": "12",
        "strTimestamp": "2026-07-26T20:00:00",
        "dateEvent": "2026-07-26",
        "dateEventLocal": "2026-07-26",
        "strTimeLocal": "14:00:00",
        "strStatus": "NS",
        "strSeason": "2026-2027",
        "idHomeTeam": "1",
        "strHomeTeam": "Home",
        "idAwayTeam": "2",
        "strAwayTeam": "Away",
        "intHomeScore": None,
        "intAwayScore": None,
    },
]


def public_transport(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("id") == "4351":
        return httpx.Response(200, json={"events": []})
    return httpx.Response(200, json={"events": EVENTS})


@pytest.mark.asyncio
async def test_liga_mx_public_source_builds_fixture_and_recent_form_prediction():
    client = PublicWebFootballClient(
        transport=httpx.MockTransport(public_transport),
    )

    fixtures = await client.get_fixtures(
        "2026-07-26",
        "America/Mexico_City",
    )
    prediction = await client.get_prediction(12)

    assert len(fixtures) == 1
    assert fixtures[0]["league"]["name"] == "Liga MX"
    assert fixtures[0]["fixture"]["source"] == "TheSportsDB public schedule"
    assert fixtures[0]["fixture"]["date"].endswith("-06:00")
    assert prediction is not None
    assert prediction["_provider"] == "TheSportsDB public schedule"
    assert "partidos recientes" in prediction["_warnings"][0]
    assert (
        float(prediction["predictions"]["percent"]["home"].rstrip("%"))
        > float(prediction["predictions"]["percent"]["away"].rstrip("%"))
    )
    assert float(prediction["predictions"]["goals"]["home"]) > 0
    await client.close()


def test_public_leagues_use_their_correct_season_format():
    assert PublicWebFootballClient._season_name(
        date(2026, 7, 26),
        "split_year",
    ) == "2026-2027"
    assert PublicWebFootballClient._season_name(
        date(2026, 7, 26),
        "calendar_year",
    ) == "2026"


def brazil_round_transport(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("id") == "4350":
        return httpx.Response(200, json={"events": []})
    if request.url.path.endswith("/eventsseason.php"):
        return httpx.Response(200, json={"events": []})
    seed = {
        **EVENTS[2],
        "idEvent": "20",
        "intRound": "20",
        "strHomeTeam": "Bahia",
        "strAwayTeam": "Corinthians",
    }
    if request.url.path.endswith("/eventsnextleague.php"):
        return httpx.Response(200, json={"events": [seed]})
    second = {
        **seed,
        "idEvent": "21",
        "strHomeTeam": "Flamengo",
        "strAwayTeam": "Palmeiras",
    }
    return httpx.Response(200, json={"events": [seed, second]})


@pytest.mark.asyncio
async def test_next_event_round_expands_truncated_brazil_schedule():
    client = PublicWebFootballClient(
        transport=httpx.MockTransport(brazil_round_transport),
    )

    fixtures = await client.get_fixtures(
        "2026-07-26",
        "America/Mexico_City",
    )

    assert {fixture["fixture"]["id"] for fixture in fixtures} == {20, 21}
    assert all(
        fixture["league"]["name"] == "Brasileirão Betano"
        for fixture in fixtures
    )
    await client.close()
