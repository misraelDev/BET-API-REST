"""Pruebas de los adaptadores multi-fuente de liquidación."""

from __future__ import annotations

from datetime import date, datetime

import httpx
import pytest

from app.sports.football.predictions.observation import (
    FootballObservation,
    ObservationSource,
    PeriodScore,
)
from app.sports.football.predictions.observation_sources import (
    MultiSourceObservationResolver,
)
from app.sports.football.scores365_results_client import (
    Scores365ResultsClient,
)
from app.sports.football.thesportsdb_results_client import (
    TheSportsDbResultsClient,
)

MATCH_DATE = date(2026, 11, 5)


def _observation(provider: str, event_id: int) -> FootballObservation:
    return FootballObservation(
        event_id=event_id,
        league="test",
        status_name="FT",
        phase="finished",
        home_team="Home",
        away_team="Away",
        regulation=PeriodScore(home=1, away=0),
        source=ObservationSource(
            name=provider,
            provider=provider,
            event_id=event_id,
            retrieved_at=datetime(2026, 11, 6, tzinfo=None),
        ),
    )


class FakeSource:
    def __init__(self, name, observation=None, found=None, error=None):
        self.name = name
        self.observation = observation
        self.found = found
        self.error = error
        self.get_calls = []
        self.find_calls = []

    async def get_observation(self, event_id, league_slug=None):
        self.get_calls.append((event_id, league_slug))
        if self.error:
            raise self.error
        return self.observation

    async def find_observation(
        self, home_team, away_team, target_date, league_slug=None
    ):
        self.find_calls.append(
            (home_team, away_team, target_date, league_slug)
        )
        if self.error:
            raise self.error
        return self.found


@pytest.mark.asyncio
async def test_resolver_uses_declared_source_first():
    declared = FakeSource("sofascore", observation=_observation("sofascore", 10))
    fallback = FakeSource("thesportsdb", found=_observation("thesportsdb", 20))
    resolver = MultiSourceObservationResolver(
        {"sofascore": declared, "thesportsdb": fallback}
    )

    result = await resolver.resolve(
        event_source="sofascore",
        event_id=10,
        league_slug="mex.1",
        home_team="Home",
        away_team="Away",
        match_date=MATCH_DATE,
    )

    assert result is not None
    assert result.source.provider == "sofascore"
    assert declared.get_calls == [(10, "mex.1")]
    assert fallback.find_calls == []


@pytest.mark.asyncio
async def test_resolver_falls_back_by_teams_and_date():
    declared = FakeSource("sofascore", observation=None)
    fallback = FakeSource("thesportsdb", found=_observation("thesportsdb", 20))
    resolver = MultiSourceObservationResolver(
        {"sofascore": declared, "thesportsdb": fallback}
    )

    result = await resolver.resolve(
        event_source="sofascore",
        event_id=10,
        league_slug=None,
        home_team="Home",
        away_team="Away",
        match_date=MATCH_DATE,
    )

    assert result is not None
    assert result.source.provider == "thesportsdb"
    assert fallback.find_calls == [
        ("Home", "Away", MATCH_DATE, None)
    ]


@pytest.mark.asyncio
async def test_resolver_falls_back_when_declared_source_fails():
    declared = FakeSource("sofascore", error=RuntimeError("caída"))
    fallback = FakeSource("365scores", found=_observation("365scores", 30))
    resolver = MultiSourceObservationResolver(
        {"sofascore": declared, "365scores": fallback}
    )

    result = await resolver.resolve(
        event_source="sofascore",
        event_id=10,
        league_slug=None,
        home_team="Home",
        away_team="Away",
        match_date=MATCH_DATE,
    )

    assert result is not None
    assert result.source.provider == "365scores"


@pytest.mark.asyncio
async def test_resolver_returns_none_when_no_source_matches():
    resolver = MultiSourceObservationResolver(
        {
            "sofascore": FakeSource("sofascore"),
            "thesportsdb": FakeSource("thesportsdb"),
        }
    )

    result = await resolver.resolve(
        event_source="sofascore",
        event_id=10,
        league_slug=None,
        home_team="Home",
        away_team="Away",
        match_date=MATCH_DATE,
    )

    assert result is None


THESPORTSDB_EVENT = {
    "idEvent": "2398176",
    "strHomeTeam": "Aldosivi",
    "strAwayTeam": "River Plate",
    "intHomeScore": "0",
    "intAwayScore": "2",
    "strStatus": "FT",
    "strLeague": "Argentinian Primera Division",
    "strTimestamp": "2026-11-05T18:00:00",
    "idHomeTeam": "135150",
    "idAwayTeam": "135171",
}

THESPORTSDB_TIMELINE = {
    "timeline": [
        {
            "strTimeline": "Goal",
            "strTimelineDetail": "Goal",
            "strHome": "No",
            "intTime": "12",
            "strPlayer": "Player Away",
            "strTeam": "River Plate",
        },
        {
            "strTimeline": "Goal",
            "strTimelineDetail": "Penalty",
            "strHome": "No",
            "intTime": "70",
            "strPlayer": "Player Away 2",
            "strTeam": "River Plate",
        },
    ]
}


def _thesportsdb_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lookupevent.php"):
            return httpx.Response(200, json={"events": [THESPORTSDB_EVENT]})
        if request.url.path.endswith("/eventsday.php"):
            return httpx.Response(200, json={"events": [THESPORTSDB_EVENT]})
        if request.url.path.endswith("/lookuptimeline.php"):
            return httpx.Response(200, json=THESPORTSDB_TIMELINE)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_thesportsdb_reads_score_and_goal_timeline():
    client = TheSportsDbResultsClient(transport=_thesportsdb_transport())

    observation = await client.get_observation(2398176)

    assert observation is not None
    assert observation.regulation == PeriodScore(home=0, away=2)
    assert observation.phase == "finished"
    assert [goal.team for goal in observation.goals] == ["away", "away"]
    assert observation.goals[0].minute == 12
    assert observation.source.provider == "thesportsdb"
    assert observation.source.event_id == 2398176
    await client.close()


@pytest.mark.asyncio
async def test_thesportsdb_finds_match_by_teams_and_date():
    client = TheSportsDbResultsClient(transport=_thesportsdb_transport())

    observation = await client.find_observation(
        "Aldosivi", "River Plate", MATCH_DATE
    )

    assert observation is not None
    assert observation.event_id == 2398176
    await client.close()


SCORES365_GAME = {
    "id": 4808721,
    "statusGroup": 4,
    "statusText": "Finalizado",
    "shortStatusText": "Final",
    "competitionDisplayName": "Liga Indonesia",
    "startTime": "2026-11-06T02:30:00-06:00",
    "homeCompetitor": {
        "id": 89689,
        "name": "PSIM Yogyakarta",
        "score": 1.0,
    },
    "awayCompetitor": {
        "id": 70869,
        "name": "Dewa United",
        "score": 2.0,
    },
    "stages": [
        {
            "id": 7,
            "name": "Entretiempo",
            "homeCompetitorScore": 0.0,
            "awayCompetitorScore": 1.0,
        },
        {
            "id": 9,
            "name": "Fin de los 90 minutos",
            "homeCompetitorScore": 1.0,
            "awayCompetitorScore": 2.0,
        },
    ],
    "events": [
        {
            "competitorId": 70869,
            "eventType": {
                "id": 1,
                "name": "Gol",
                "subTypeName": "Gol de campo",
            },
            "gameTime": 11.0,
            "gameTimeDisplay": "11'",
            "playerId": 3163110,
        },
        {
            "competitorId": 89689,
            "eventType": {
                "id": 1,
                "name": "Gol",
                "subTypeName": "Gol de campo",
            },
            "gameTime": 66.0,
            "gameTimeDisplay": "66'",
            "playerId": 400723,
        },
    ],
    "members": [
        {"id": 3163110, "name": "Player Away"},
        {"id": 400723, "name": "Player Home"},
    ],
}


def _scores365_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/web/game/"):
            return httpx.Response(200, json={"game": SCORES365_GAME})
        if request.url.path.endswith("/web/games/allscores/"):
            return httpx.Response(200, json={"games": [SCORES365_GAME]})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_scores365_reads_score_periods_and_first_goal():
    client = Scores365ResultsClient(transport=_scores365_transport())

    observation = await client.get_observation(4808721)

    assert observation is not None
    assert observation.regulation == PeriodScore(home=1, away=2)
    assert observation.first_half == PeriodScore(home=0, away=1)
    assert observation.second_half == PeriodScore(home=1, away=1)
    assert observation.goals[0].team == "away"
    assert observation.goals[0].player == "Player Away"
    assert observation.source.provider == "365scores"
    assert observation.source.event_id == 4808721
    await client.close()


@pytest.mark.asyncio
async def test_scores365_finds_match_by_teams_and_date():
    client = Scores365ResultsClient(transport=_scores365_transport())

    observation = await client.find_observation(
        "PSIM Yogyakarta", "Dewa United", date(2026, 11, 6)
    )

    assert observation is not None
    assert observation.event_id == 4808721
    await client.close()
