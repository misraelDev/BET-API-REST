"""Observación verificable de un partido a partir del resumen de ESPN.

El módulo convierte el JSON público de ESPN en un objeto estable que usa el
motor de liquidación. No hace peticiones HTTP: eso corresponde al cliente.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Side = Literal["home", "away"]
Phase = Literal[
    "scheduled",
    "in_play",
    "finished",
    "postponed",
    "cancelled",
    "abandoned",
    "unknown",
]


class PeriodScore(BaseModel):
    home: int
    away: int


class GoalEvent(BaseModel):
    period: int
    clock: str | None = None
    minute: int | None = None
    team: Side | None = Field(
        default=None,
        description="Equipo al que se acredita el gol (autogol incluido).",
    )
    reported_team: Side | None = None
    own_goal: bool = False
    penalty: bool = False
    player: str | None = None
    order: float = 0.0


class CardEvent(BaseModel):
    period: int
    clock: str | None = None
    team: Side | None = None
    player: str | None = None
    yellow: int = 0
    red: int = 0


class CardTotals(BaseModel):
    yellow: int = 0
    red: int = 0
    total: int = 0


class PlayerObservation(BaseModel):
    name: str
    player_id: str | None = None
    team: Side | None = None
    starter: bool | None = None
    appeared: bool | None = None
    shots: int | None = None
    shots_on_target: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None


class ObservationSource(BaseModel):
    name: str = "ESPN public summary"
    url: str | None = None
    retrieved_at: datetime


class FootballObservation(BaseModel):
    event_id: int
    league: str
    status_name: str
    phase: Phase
    status_detail: str | None = None
    home_team: str
    away_team: str
    home_team_id: str | None = None
    away_team_id: str | None = None
    kickoff: datetime | None = None
    regulation: PeriodScore | None = None
    first_half: PeriodScore | None = None
    second_half: PeriodScore | None = None
    went_to_extra_time: bool = False
    goals: list[GoalEvent] = Field(default_factory=list)
    cards: dict[str, CardTotals] | None = None
    card_events: list[CardEvent] = Field(default_factory=list)
    corners: PeriodScore | None = None
    shots: PeriodScore | None = None
    shots_on_target: PeriodScore | None = None
    players: list[PlayerObservation] = Field(default_factory=list)
    rosters_complete: bool = False
    events_complete: bool = False
    stats_reliable: bool = True
    source: ObservationSource

    @property
    def finished(self) -> bool:
        return self.phase == "finished"

    @property
    def total_goals(self) -> int | None:
        if self.regulation is None:
            return None
        return self.regulation.home + self.regulation.away


def normalize_name(value: str | None) -> str:
    """Normaliza nombres para comparar jugadores entre fuentes."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _number(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"-?\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group())
    except ValueError:
        return None


def _minute(value: Any) -> int | None:
    text = str(value or "")
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def _display(item: Any) -> Any:
    if isinstance(item, dict):
        if item.get("displayValue") is not None:
            return item.get("displayValue")
        if item.get("value") is not None:
            return item.get("value")
    return item


def _line_scores(competitor: dict[str, Any]) -> list[int]:
    scores: list[int] = []
    for item in competitor.get("linescores") or []:
        value = _number(_display(item))
        if value is not None:
            scores.append(value)
    return scores


def _phase(status_type: dict[str, Any]) -> Phase:
    name = str(status_type.get("name") or "").upper()
    detail = str(status_type.get("detail") or "").upper()
    short = str(status_type.get("shortDetail") or "").upper()
    blob = f"{name} {detail} {short}"
    if "CANCEL" in blob:
        return "cancelled"
    if "ABANDON" in blob or "SUSPEND" in blob:
        return "abandoned"
    if "POSTPON" in blob or "DELAY" in blob:
        return "postponed"
    if status_type.get("completed") or "FULL_TIME" in blob or "FINAL" in blob:
        return "finished"
    if status_type.get("state") == "in":
        return "in_play"
    if status_type.get("state") == "pre":
        return "scheduled"
    return "unknown"


def _team_maps(
    competitors: list[dict[str, Any]],
) -> tuple[dict[str, Side], dict[str, Side]]:
    by_id: dict[str, Side] = {}
    by_name: dict[str, Side] = {}
    for competitor in competitors:
        side = competitor.get("homeAway")
        if side not in ("home", "away"):
            continue
        team = competitor.get("team") or {}
        if team.get("id") is not None:
            by_id[str(team["id"])] = side
        for key in ("displayName", "name", "shortDisplayName", "abbreviation"):
            if team.get(key):
                by_name[normalize_name(team[key])] = side
    return by_id, by_name


def _event_side(
    event: dict[str, Any],
    by_id: dict[str, Side],
    by_name: dict[str, Side],
) -> Side | None:
    team = event.get("team")
    if isinstance(team, dict):
        if team.get("id") is not None and str(team["id"]) in by_id:
            return by_id[str(team["id"])]
        for key in ("displayName", "name", "shortDisplayName", "abbreviation"):
            if team.get(key):
                side = by_name.get(normalize_name(team[key]))
                if side:
                    return side
    team_id = event.get("teamId")
    if team_id is not None and str(team_id) in by_id:
        return by_id[str(team_id)]
    return None


def _player_name(event: dict[str, Any]) -> str | None:
    for key in ("participants", "athletesInvolved"):
        for item in event.get(key) or []:
            if not isinstance(item, dict):
                continue
            athlete = item.get("athlete")
            if isinstance(athlete, dict) and athlete.get("displayName"):
                return str(athlete["displayName"])
            if item.get("displayName"):
                return str(item["displayName"])
    athlete = event.get("athlete")
    if isinstance(athlete, dict) and athlete.get("displayName"):
        return str(athlete["displayName"])
    return None


def _is_goal(event: dict[str, Any]) -> bool:
    text = str(((event.get("type") or {}).get("text")) or "").casefold()
    if event.get("scoringPlay"):
        return True
    if "disallow" in text or "cancel" in text or "no goal" in text:
        return False
    if "goal kick" in text:
        return False
    if "goal" in text or "own goal" in text:
        return True
    return "penalty" in text and "scored" in text


def _goal_events(
    events: list[dict[str, Any]],
    by_id: dict[str, Side],
    by_name: dict[str, Side],
) -> tuple[list[GoalEvent], bool]:
    goals: list[GoalEvent] = []
    saw_extra = False
    for event in events:
        period = _number((event.get("period") or {}).get("number")) or 0
        if period >= 3:
            saw_extra = True
        if not _is_goal(event) or event.get("shootout"):
            continue
        reported = _event_side(event, by_id, by_name)
        own_goal = bool(event.get("ownGoal"))
        credited = reported
        if own_goal and reported is not None:
            credited = "away" if reported == "home" else "home"
        clock = event.get("clock") or {}
        display = clock.get("displayValue")
        seconds = _number(clock.get("value"))
        minute = _minute(display)
        order = float(period) * 10000 + (
            float(seconds) if seconds is not None else float(minute or 0) * 60
        )
        goals.append(
            GoalEvent(
                period=period,
                clock=str(display) if display else None,
                minute=minute,
                team=credited,
                reported_team=reported,
                own_goal=own_goal,
                penalty=bool(event.get("penaltyKick"))
                or "penalty" in str(((event.get("type") or {}).get("text")) or "").casefold(),
                player=_player_name(event),
                order=order,
            )
        )
    # Pydantic convierte minute a str en el constructor si el tipo es str.
    return goals, saw_extra


def _card_events(
    events: list[dict[str, Any]],
    by_id: dict[str, Side],
    by_name: dict[str, Side],
) -> tuple[list[CardEvent], dict[str, CardTotals]]:
    cards: list[CardEvent] = []
    totals: dict[str, CardTotals] = {
        "home": CardTotals(),
        "away": CardTotals(),
    }
    for event in events:
        type_text = str(((event.get("type") or {}).get("text")) or "").casefold()
        description = " ".join(
            str(event.get(key) or "")
            for key in ("text", "shortText")
        ).casefold()
        if event.get("shootout"):
            continue
        yellow = 0
        red = 0
        if (
            "second yellow" in description
            or "yellow/red" in description
            or ("yellow" in type_text and "red" in type_text)
        ):
            # La segunda amarilla se reporta de dos formas: un solo evento
            # "yellow/red" o un evento rojo cuya descripción la menciona.
            # En ambos casos se muestran dos tarjetas: amarilla + roja.
            yellow, red = 1, 1
        elif "yellow" in type_text or "yellow" in description:
            yellow = 1
        elif "red" in type_text or "red card" in description:
            red = 1
        if not (yellow or red):
            continue
        side = _event_side(event, by_id, by_name)
        period = _number((event.get("period") or {}).get("number")) or 0
        clock = (event.get("clock") or {}).get("displayValue")
        cards.append(
            CardEvent(
                period=period,
                clock=str(clock) if clock else None,
                team=side,
                player=_player_name(event),
                yellow=yellow,
                red=red,
            )
        )
        if side is not None:
            totals[side] = CardTotals(
                yellow=totals[side].yellow + yellow,
                red=totals[side].red + red,
                total=totals[side].total + yellow + red,
            )
    return cards, totals


def _team_statistics(
    boxscore_teams: list[dict[str, Any]],
) -> dict[str, dict[str, int | None]]:
    stats: dict[str, dict[str, int | None]] = {}
    for row in boxscore_teams:
        side = row.get("homeAway")
        if side not in ("home", "away"):
            continue
        values: dict[str, int | None] = {}
        for item in row.get("statistics") or []:
            values[str(item.get("name"))] = _number(
                item.get("displayValue")
                if item.get("displayValue") is not None
                else item.get("value")
            )
        stats[side] = values
    return stats


def _players(
    rosters: list[dict[str, Any]],
) -> list[PlayerObservation]:
    players: list[PlayerObservation] = []
    for roster in rosters:
        side = roster.get("homeAway")
        if side not in ("home", "away"):
            side = None
        for entry in roster.get("roster") or []:
            athlete = entry.get("athlete") or {}
            name = athlete.get("displayName") or athlete.get("fullName")
            if not name:
                continue
            values: dict[str, int | None] = {}
            for stat in entry.get("stats") or []:
                key = str(stat.get("name"))
                raw = stat.get("value")
                if raw is None:
                    raw = stat.get("displayValue")
                values[key] = _number(raw)
            appearances = values.get("appearances") or 0
            appeared = bool(
                entry.get("starter")
                or entry.get("subbedIn")
                or appearances > 0
            )
            players.append(
                PlayerObservation(
                    name=str(name),
                    player_id=str(athlete["id"]) if athlete.get("id") else None,
                    team=side,
                    starter=bool(entry.get("starter")),
                    appeared=appeared,
                    shots=values.get("totalShots"),
                    shots_on_target=values.get("shotsOnTarget"),
                    yellow_cards=values.get("yellowCards"),
                    red_cards=values.get("redCards"),
                )
            )
    return players


def _rosters_complete(rosters: list[dict[str, Any]]) -> bool:
    """Considera completa la plantilla solo si ambos equipos están listados.

    Se exigen al menos 11 jugadores por lado para no deducir un cero cuando la
    fuente publica una lista parcial.
    """
    counts: dict[str, int] = {}
    for roster in rosters:
        side = roster.get("homeAway")
        if side not in ("home", "away"):
            continue
        entries = [
            entry
            for entry in roster.get("roster") or []
            if isinstance(entry, dict)
            and ((entry.get("athlete") or {}).get("displayName"))
        ]
        counts[side] = len(entries)
    return counts.get("home", 0) >= 11 and counts.get("away", 0) >= 11


def build_observation(
    payload: dict[str, Any],
    *,
    event_id: int,
    league_slug: str,
    source_url: str,
    retrieved_at: datetime,
) -> FootballObservation | None:
    """Convierte el resumen de ESPN en ``FootballObservation``.

    Devuelve ``None`` si el payload no contiene la competición del partido.
    """
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    competition = next(
        (
            item
            for item in competitions
            if str(item.get("id")) == str(event_id)
        ),
        competitions[0] if competitions else None,
    )
    if not competition:
        return None

    competitors = competition.get("competitors") or []
    home = next(
        (item for item in competitors if item.get("homeAway") == "home"), None
    )
    away = next(
        (item for item in competitors if item.get("homeAway") == "away"), None
    )
    if not home or not away:
        return None

    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    home_name = home_team.get("displayName") or home_team.get("name") or "Local"
    away_name = away_team.get("displayName") or away_team.get("name") or "Visitante"

    status_type = (competition.get("status") or {}).get("type") or {}
    phase = _phase(status_type)
    home_lines = _line_scores(home)
    away_lines = _line_scores(away)
    home_final = _number(home.get("score"))
    away_final = _number(away.get("score"))

    label = " ".join(
        str(status_type.get(key) or "")
        for key in ("name", "detail", "shortDetail")
    ).upper()
    went_to_extra_time = (
        "AET" in label
        or "PEN" in label
        or "PENAL" in label
        or len(home_lines) > 2
        or len(away_lines) > 2
    )

    regulation: PeriodScore | None = None
    first_half: PeriodScore | None = None
    second_half: PeriodScore | None = None
    if len(home_lines) >= 2 and len(away_lines) >= 2:
        first_half = PeriodScore(home=home_lines[0], away=away_lines[0])
        second_half = PeriodScore(home=home_lines[1], away=away_lines[1])
        regulation = PeriodScore(
            home=home_lines[0] + home_lines[1],
            away=away_lines[0] + away_lines[1],
        )
    elif (
        phase == "finished"
        and not went_to_extra_time
        and home_final is not None
        and away_final is not None
    ):
        regulation = PeriodScore(home=home_final, away=away_final)

    events = payload.get("keyEvents")
    if not events:
        events = competition.get("details") or []
    events = [event for event in events if isinstance(event, dict)]
    by_id, by_name = _team_maps(competitors)
    goals, saw_extra_period = _goal_events(events, by_id, by_name)
    card_events, card_totals_from_events = _card_events(events, by_id, by_name)
    went_to_extra_time = went_to_extra_time or saw_extra_period

    statistics = _team_statistics(
        ((payload.get("boxscore") or {}).get("teams") or [])
    )
    home_stats = statistics.get("home") or {}
    away_stats = statistics.get("away") or {}

    goals_total = (
        regulation.home + regulation.away if regulation is not None else None
    )
    observed_values = [
        home_stats.get("wonCorners"),
        away_stats.get("wonCorners"),
        home_stats.get("totalShots"),
        away_stats.get("totalShots"),
        home_stats.get("shotsOnTarget"),
        away_stats.get("shotsOnTarget"),
        home_stats.get("yellowCards"),
        away_stats.get("yellowCards"),
        home_stats.get("redCards"),
        away_stats.get("redCards"),
    ]
    all_zero = all((value or 0) == 0 for value in observed_values)
    has_stats = bool(home_stats) or bool(away_stats)
    stats_reliable = has_stats and not (
        goals_total is not None
        and goals_total > 0
        and all_zero
        and home_stats
        and away_stats
    )

    def _period(home_key: str, away_key: str) -> PeriodScore | None:
        home_value = home_stats.get(home_key)
        away_value = away_stats.get(away_key)
        if home_value is None or away_value is None:
            return None
        return PeriodScore(home=home_value, away=away_value)

    cards: dict[str, CardTotals] | None = None
    if stats_reliable and (
        home_stats.get("yellowCards") is not None
        or away_stats.get("yellowCards") is not None
    ):
        home_yellow = home_stats.get("yellowCards") or 0
        home_red = home_stats.get("redCards") or 0
        away_yellow = away_stats.get("yellowCards") or 0
        away_red = away_stats.get("redCards") or 0
        cards = {
            "home": CardTotals(
                yellow=home_yellow,
                red=home_red,
                total=home_yellow + home_red,
            ),
            "away": CardTotals(
                yellow=away_yellow,
                red=away_red,
                total=away_yellow + away_red,
            ),
        }
    elif card_events:
        cards = card_totals_from_events

    kickoff = None
    raw_date = competition.get("date") or header.get("date")
    if raw_date:
        try:
            kickoff = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=UTC)
            kickoff = kickoff.astimezone(UTC)
        except ValueError:
            kickoff = None

    players = _players(payload.get("rosters") or [])

    return FootballObservation(        event_id=event_id,
        league=league_slug,
        status_name=str(status_type.get("name") or ""),
        phase=phase,
        status_detail=status_type.get("detail"),
        home_team=str(home_name),
        away_team=str(away_name),
        home_team_id=str(home_team["id"]) if home_team.get("id") else None,
        away_team_id=str(away_team["id"]) if away_team.get("id") else None,
        kickoff=kickoff,
        regulation=regulation,
        first_half=first_half,
        second_half=second_half,
        went_to_extra_time=went_to_extra_time,
        goals=goals,
        cards=cards,
        card_events=card_events,
        corners=(
            _period("wonCorners", "wonCorners") if stats_reliable else None
        ),
        shots=(
            _period("totalShots", "totalShots") if stats_reliable else None
        ),
        shots_on_target=(
            _period("shotsOnTarget", "shotsOnTarget")
            if stats_reliable
            else None
        ),
        players=players,
        rosters_complete=_rosters_complete(payload.get("rosters") or []),
        events_complete=bool(events),
        stats_reliable=stats_reliable,
        source=ObservationSource(
            url=source_url,
            retrieved_at=retrieved_at,
        ),
    )


__all__ = [
    "CardEvent",
    "CardTotals",
    "FootballObservation",
    "GoalEvent",
    "ObservationSource",
    "PeriodScore",
    "PlayerObservation",
    "build_observation",
    "normalize_name",
]
