"""Adaptador de TheSportsDB para verificar y liquidar partidos."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.sports.football.predictions.observation import (
    FootballObservation,
    GoalEvent,
    ObservationSource,
    PeriodScore,
)
from app.sports.football.predictions.source_matching import same_match, same_team

THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/123"


class TheSportsDbResultsClient:
    """Lee resultados y goles de la API pública de TheSportsDB.

    ``event_id`` es el ``idEvent`` de TheSportsDB. Para IDs de otras fuentes
    se usa ``find_observation`` con los equipos y la fecha.
    """

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=THESPORTSDB_BASE,
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "BET-API-REST/1.0",
            },
        )
        self._day_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._timeline_cache: dict[int, list[dict[str, Any]]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def get_observation(
        self,
        event_id: int,
        league_slug: str | None = None,
    ) -> FootballObservation | None:
        payload = await self._get("/lookupevent.php", {"id": str(event_id)})
        events = payload.get("events") or []
        if not events:
            return None
        return await self._build(events[0], league_slug)

    async def find_observation(
        self,
        home_team: str,
        away_team: str,
        target_date: date,
        league_slug: str | None = None,
    ) -> FootballObservation | None:
        for offset in (0, -1, 1):
            payload = await self._day(target_date + timedelta(days=offset))
            for event in payload.get("events") or []:
                if not isinstance(event, dict):
                    continue
                if not same_match(
                    home_team,
                    away_team,
                    event.get("strHomeTeam"),
                    event.get("strAwayTeam"),
                ):
                    continue
                observation = await self._build(event, league_slug)
                if observation is not None:
                    return observation
        return None

    async def _day(self, day: date) -> dict[str, Any]:
        key = day.isoformat()
        cached = self._day_cache.get(key)
        now = datetime.now(UTC)
        if cached is not None and (now - cached[0]).total_seconds() < 120:
            return cached[1]
        payload = await self._get(
            "/eventsday.php", {"d": key, "s": "Soccer"}
        )
        self._day_cache[key] = (now, payload)
        return payload

    async def _timeline(self, event_id: int) -> list[dict[str, Any]]:
        cached = self._timeline_cache.get(event_id)
        if cached is not None:
            return cached
        payload = await self._get(
            "/lookuptimeline.php", {"id": str(event_id)}
        )
        timeline = [
            item
            for item in payload.get("timeline") or []
            if isinstance(item, dict)
        ]
        self._timeline_cache[event_id] = timeline
        return timeline

    async def _build(
        self,
        event: dict[str, Any],
        league_slug: str | None,
    ) -> FootballObservation | None:
        raw_id = event.get("idEvent")
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            return None

        home_team = str(event.get("strHomeTeam") or "Local")
        away_team = str(event.get("strAwayTeam") or "Visitante")
        status = str(event.get("strStatus") or "").upper()
        postponed = str(event.get("strPostponed") or "").lower() == "yes"
        phase = _phase(status, postponed)
        home_score = _number(event.get("intHomeScore"))
        away_score = _number(event.get("intAwayScore"))
        went_to_extra_time = status in {"AET", "PEN", "AP"}
        regulation = None
        if (
            not went_to_extra_time
            and home_score is not None
            and away_score is not None
        ):
            regulation = PeriodScore(home=home_score, away=away_score)

        timeline = await self._timeline(event_id) if phase == "finished" else []
        goals = _goals(timeline, home_team, away_team)
        retrieved_at = datetime.now(UTC)
        return FootballObservation(
            event_id=event_id,
            league=str(event.get("strLeague") or league_slug or "unknown"),
            status_name=status or "UNKNOWN",
            phase=phase,
            status_detail=event.get("strStatus"),
            home_team=home_team,
            away_team=away_team,
            home_team_id=(
                str(event["idHomeTeam"])
                if event.get("idHomeTeam")
                else None
            ),
            away_team_id=(
                str(event["idAwayTeam"])
                if event.get("idAwayTeam")
                else None
            ),
            kickoff=_kickoff(event),
            regulation=regulation,
            went_to_extra_time=went_to_extra_time,
            goals=goals,
            events_complete=bool(goals)
            or (
                phase == "finished"
                and home_score == 0
                and away_score == 0
            ),
            stats_reliable=False,
            source=ObservationSource(
                name="TheSportsDB public event",
                provider="thesportsdb",
                event_id=event_id,
                url=f"https://www.thesportsdb.com/event/{event_id}",
                retrieved_at=retrieved_at,
            ),
        )

    async def _get(
        self, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _number(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _phase(status: str, postponed: bool) -> str:
    blob = status.upper()
    if postponed or "POSTPON" in blob or blob in {"PST", "TBD"}:
        return "postponed"
    if "CANCEL" in blob or blob == "CANC":
        return "cancelled"
    if "ABANDON" in blob or "SUSPEND" in blob or blob in {"ABD", "SUSP"}:
        return "abandoned"
    if blob in {"FT", "AET", "PEN", "AP", "AWD", "WO"} or "FINAL" in blob:
        return "finished"
    if blob in {"NS", "SCHEDULED"} or "SCHEDULED" in blob:
        return "scheduled"
    if blob in {"1H", "2H", "HT", "ET", "BT", "P", "LIVE", "INT"}:
        return "in_play"
    return "unknown"


def _period(minute: int) -> int:
    if minute <= 45:
        return 1
    if minute <= 90:
        return 2
    if minute <= 105:
        return 3
    return 4


def _side(
    item: dict[str, Any],
    home_team: str,
    away_team: str,
) -> str | None:
    flag = str(item.get("strHome") or "").casefold()
    if flag in {"yes", "true", "1"}:
        return "home"
    if flag in {"no", "false", "0"}:
        return "away"
    team = item.get("strTeam")
    if same_team(team, home_team):
        return "home"
    if same_team(team, away_team):
        return "away"
    return None


def _goals(
    timeline: list[dict[str, Any]],
    home_team: str,
    away_team: str,
) -> list[GoalEvent]:
    goals: list[GoalEvent] = []
    for index, item in enumerate(timeline):
        timeline_type = str(item.get("strTimeline") or "").casefold()
        detail = str(item.get("strTimelineDetail") or "").casefold()
        if timeline_type == "var" or "cancel" in detail or "missed" in detail:
            continue
        is_goal = timeline_type == "goal" or (
            "goal" in detail and "goal kick" not in detail
        )
        if not is_goal:
            continue
        minute = _number(item.get("intTime"))
        if minute is None:
            continue
        reported = _side(item, home_team, away_team)
        if reported is None:
            continue
        own_goal = "own goal" in detail or "autogol" in detail
        credited = (
            ("away" if reported == "home" else "home")
            if own_goal
            else reported
        )
        period = _period(minute)
        goals.append(
            GoalEvent(
                period=period,
                clock=f"{minute}'",
                minute=minute,
                team=credited,
                reported_team=reported,
                own_goal=own_goal,
                penalty="penalty" in detail,
                player=item.get("strPlayer") or None,
                order=float(period) * 10000
                + float(minute) * 60
                + float(index),
            )
        )
    return goals


def _kickoff(event: dict[str, Any]) -> datetime | None:
    raw = event.get("strTimestamp")
    if raw:
        try:
            value = datetime.fromisoformat(
                str(raw).replace("Z", "+00:00")
            )
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        except ValueError:
            pass
    day = event.get("dateEvent")
    clock = event.get("strTime")
    if day and clock:
        try:
            value = datetime.fromisoformat(f"{day}T{clock}")
            return value.replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


__all__ = ["TheSportsDbResultsClient"]
