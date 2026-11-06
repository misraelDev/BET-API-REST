"""Adaptador de 365Scores para verificar y liquidar partidos."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.sports.football.predictions.observation import (
    CardEvent,
    CardTotals,
    FootballObservation,
    GoalEvent,
    ObservationSource,
    PeriodScore,
)
from app.sports.football.predictions.source_matching import same_match

SCORES365_BASE = "https://webws.365scores.com"
SCORES365_PARAMS = {
    "appTypeId": 5,
    "langId": 29,
    "timezoneName": "America/Mexico_City",
    "userCountryId": 52,
}


class Scores365ResultsClient:
    """Lee resultados, goles y tarjetas de la API pública de 365Scores."""

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=SCORES365_BASE,
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "BET-API-REST/1.0",
            },
        )
        self._day_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def get_observation(
        self,
        event_id: int,
        league_slug: str | None = None,
    ) -> FootballObservation | None:
        payload = await self._get(
            "/web/game/",
            {**SCORES365_PARAMS, "gameId": str(event_id)},
        )
        game = payload.get("game")
        if not isinstance(game, dict):
            return None
        return self._build(game, league_slug)

    async def find_observation(
        self,
        home_team: str,
        away_team: str,
        target_date: date,
        league_slug: str | None = None,
    ) -> FootballObservation | None:
        for offset in (0, -1, 1):
            payload = await self._allscores(
                target_date + timedelta(days=offset)
            )
            for game in payload.get("games") or []:
                if not isinstance(game, dict):
                    continue
                home = (game.get("homeCompetitor") or {}).get("name")
                away = (game.get("awayCompetitor") or {}).get("name")
                if not same_match(home_team, away_team, home, away):
                    continue
                raw_id = game.get("id")
                if raw_id in (None, ""):
                    continue
                observation = await self.get_observation(
                    int(raw_id), league_slug
                )
                if observation is not None:
                    return observation
        return None

    async def _allscores(self, day: date) -> dict[str, Any]:
        key = day.isoformat()
        cached = self._day_cache.get(key)
        now = datetime.now(UTC)
        if cached is not None and (now - cached[0]).total_seconds() < 120:
            return cached[1]
        payload = await self._get(
            "/web/games/allscores/",
            {
                **SCORES365_PARAMS,
                "sports": 1,
                "startDate": key,
                "endDate": key,
            },
        )
        self._day_cache[key] = (now, payload)
        return payload

    def _build(
        self,
        game: dict[str, Any],
        league_slug: str | None,
    ) -> FootballObservation | None:
        raw_id = game.get("id")
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            return None

        home = game.get("homeCompetitor") or {}
        away = game.get("awayCompetitor") or {}
        home_team = str(home.get("name") or "Local")
        away_team = str(away.get("name") or "Visitante")
        status_group = _number(game.get("statusGroup")) or 0
        status_text = str(game.get("statusText") or "")
        phase = _phase(status_group, status_text)

        stages = [
            stage
            for stage in game.get("stages") or []
            if isinstance(stage, dict)
        ]
        first_half = _stage_score(_find_stage(stages, 7, "entretiempo"))
        regulation_stage = _find_stage(stages, 9, "90")
        regulation = _stage_score(regulation_stage)
        went_to_extra_time = _went_to_extra_time(status_text, stages)
        if regulation is None and phase == "finished" and not went_to_extra_time:
            regulation = PeriodScore(
                home=_number(home.get("score")) or 0,
                away=_number(away.get("score")) or 0,
            )
        second_half = None
        if first_half is not None and regulation is not None:
            second_half = PeriodScore(
                home=regulation.home - first_half.home,
                away=regulation.away - first_half.away,
            )

        events = [
            event
            for event in game.get("events") or []
            if isinstance(event, dict)
        ]
        home_id = home.get("id")
        away_id = away.get("id")
        members = {
            str(member["id"]): member.get("name")
            for member in game.get("members") or []
            if isinstance(member, dict) and member.get("id") is not None
        }
        goals = _goals(events, home_id, away_id, members)
        card_events, card_totals = _cards(
            events, home_id, away_id, members
        )
        retrieved_at = datetime.now(UTC)
        return FootballObservation(
            event_id=event_id,
            league=str(
                game.get("competitionDisplayName")
                or league_slug
                or "unknown"
            ),
            status_name=status_text or "UNKNOWN",
            phase=phase,
            status_detail=game.get("shortStatusText"),
            home_team=home_team,
            away_team=away_team,
            home_team_id=str(home_id) if home_id is not None else None,
            away_team_id=str(away_id) if away_id is not None else None,
            kickoff=_kickoff(game),
            regulation=regulation,
            first_half=first_half,
            second_half=second_half,
            went_to_extra_time=went_to_extra_time,
            goals=goals,
            cards=card_totals or None,
            card_events=card_events,
            events_complete=bool(events),
            stats_reliable=False,
            source=ObservationSource(
                name="365Scores public game",
                provider="365scores",
                event_id=event_id,
                url=(
                    "https://webws.365scores.com/web/game/"
                    f"?gameId={event_id}"
                ),
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
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _phase(status_group: int, status_text: str) -> str:
    blob = status_text.casefold()
    if any(token in blob for token in ("cancel", "anulad")):
        return "cancelled"
    if any(
        token in blob
        for token in ("abandon", "suspend", "interrump", "susp")
    ):
        return "abandoned"
    if any(
        token in blob
        for token in ("aplaz", "postpon", "retras", "delay")
    ):
        return "postponed"
    if any(token in blob for token in ("final", "terminado", "full time")):
        return "finished"
    if any(
        token in blob
        for token in ("program", "scheduled", "por jugar", "no iniciado")
    ):
        return "scheduled"
    if any(
        token in blob
        for token in (
            "entretiempo",
            "medio tiempo",
            "descanso",
            "half",
            "vivo",
            "live",
            "1t",
            "2t",
        )
    ):
        return "in_play"
    return {
        1: "scheduled",
        2: "in_play",
        3: "in_play",
        4: "finished",
        5: "postponed",
        6: "cancelled",
        7: "postponed",
    }.get(status_group, "unknown")


def _find_stage(
    stages: list[dict[str, Any]],
    stage_id: int,
    name_fragment: str,
) -> dict[str, Any] | None:
    for stage in stages:
        if _number(stage.get("id")) == stage_id:
            return stage
    for stage in stages:
        name = str(stage.get("name") or "").casefold()
        if name_fragment in name:
            return stage
    return None


def _stage_score(stage: dict[str, Any] | None) -> PeriodScore | None:
    if stage is None:
        return None
    home = _number(stage.get("homeCompetitorScore"))
    away = _number(stage.get("awayCompetitorScore"))
    if home is None or away is None:
        return None
    return PeriodScore(home=home, away=away)


def _went_to_extra_time(
    status_text: str,
    stages: list[dict[str, Any]],
) -> bool:
    blob = status_text.casefold()
    if any(
        token in blob
        for token in ("prórroga", "prorroga", "penales", "penalty", "aet")
    ):
        return True
    for stage in stages:
        name = str(stage.get("name") or "").casefold()
        if "prórroga" in name or "prorroga" in name or "penal" in name:
            return True
    return False


def _period(minute: int) -> int:
    if minute <= 45:
        return 1
    if minute <= 90:
        return 2
    if minute <= 105:
        return 3
    return 4


def _side(
    competitor_id: Any,
    home_id: Any,
    away_id: Any,
) -> str | None:
    if competitor_id is None:
        return None
    if home_id is not None and str(competitor_id) == str(home_id):
        return "home"
    if away_id is not None and str(competitor_id) == str(away_id):
        return "away"
    return None


def _goal_type(event: dict[str, Any]) -> tuple[bool, bool]:
    event_type = event.get("eventType") or {}
    type_id = _number(event_type.get("id"))
    type_name = str(event_type.get("name") or "").casefold()
    subtype = str(event_type.get("subTypeName") or "").casefold()
    blob = f"{type_name} {subtype}"
    if "cancel" in blob or "anulad" in blob or "var" in type_name:
        return False, False
    is_goal = type_id == 1 or "gol" in type_name or "goal" in type_name
    own_goal = "autogol" in subtype or "own goal" in subtype
    return is_goal, own_goal


def _goals(
    events: list[dict[str, Any]],
    home_id: Any,
    away_id: Any,
    members: dict[str, str | None],
) -> list[GoalEvent]:
    goals: list[GoalEvent] = []
    for index, event in enumerate(events):
        is_goal, own_goal = _goal_type(event)
        if not is_goal:
            continue
        minute = _number(event.get("gameTime"))
        if minute is None:
            continue
        reported = _side(event.get("competitorId"), home_id, away_id)
        if reported is None:
            continue
        credited = (
            ("away" if reported == "home" else "home")
            if own_goal
            else reported
        )
        period = _period(minute)
        player_id = event.get("playerId")
        goals.append(
            GoalEvent(
                period=period,
                clock=event.get("gameTimeDisplay") or f"{minute}'",
                minute=minute,
                team=credited,
                reported_team=reported,
                own_goal=own_goal,
                penalty="penal" in str(
                    (event.get("eventType") or {}).get("subTypeName") or ""
                ).casefold(),
                player=members.get(str(player_id)) if player_id else None,
                order=float(period) * 10000
                + float(minute) * 60
                + float(index),
            )
        )
    return goals


def _cards(
    events: list[dict[str, Any]],
    home_id: Any,
    away_id: Any,
    members: dict[str, str | None],
) -> tuple[list[CardEvent], dict[str, CardTotals]]:
    cards: list[CardEvent] = []
    totals = {
        "home": CardTotals(),
        "away": CardTotals(),
    }
    for event in events:
        event_type = event.get("eventType") or {}
        type_id = _number(event_type.get("id"))
        type_name = str(event_type.get("name") or "").casefold()
        subtype = str(event_type.get("subTypeName") or "").casefold()
        blob = f"{type_name} {subtype}"
        if "cancel" in blob or "anulad" in blob:
            continue
        yellow = 0
        red = 0
        if "segunda" in blob or "second yellow" in blob or (
            "amarilla" in blob and "roja" in blob
        ):
            yellow, red = 1, 1
        elif type_id == 2 or "amarilla" in blob or "yellow" in blob:
            yellow = 1
        elif type_id == 3 or "roja" in blob or "red card" in blob:
            red = 1
        if not (yellow or red):
            continue
        side = _side(event.get("competitorId"), home_id, away_id)
        if side is None:
            continue
        minute = _number(event.get("gameTime")) or 0
        player_id = event.get("playerId")
        cards.append(
            CardEvent(
                period=_period(minute),
                clock=event.get("gameTimeDisplay") or f"{minute}'",
                team=side,
                player=(
                    members.get(str(player_id)) if player_id else None
                ),
                yellow=yellow,
                red=red,
            )
        )
        totals[side] = CardTotals(
            yellow=totals[side].yellow + yellow,
            red=totals[side].red + red,
            total=totals[side].total + yellow + red,
        )
    return cards, totals


def _kickoff(game: dict[str, Any]) -> datetime | None:
    raw = game.get("startTime")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["Scores365ResultsClient"]
