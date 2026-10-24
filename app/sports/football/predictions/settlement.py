"""Motor puro de liquidación de pronósticos de fútbol.

No consulta fuentes ni escribe en MongoDB: recibe la selección registrada y una
``FootballObservation`` y devuelve el estado y la evidencia observada.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.sports.football.predictions.catalog import (
    RULE_VERSION,
    Market,
    Period,
    SettlementStatus,
)
from app.sports.football.predictions.observation import (
    CardTotals,
    FootballObservation,
    PeriodScore,
    PlayerObservation,
    normalize_name,
)


class SettlementResult(BaseModel):
    status: SettlementStatus
    observed: dict[str, Any] = Field(default_factory=dict)
    summary: str
    reason: str | None = None
    rule_version: str = RULE_VERSION


WON = SettlementStatus.ACERTADO
LOST = SettlementStatus.FALLADO
PUSH = SettlementStatus.REEMBOLSO
PENDING = SettlementStatus.PENDIENTE
VOID = SettlementStatus.ANULADO
NOT_EVALUABLE = SettlementStatus.NO_EVALUABLE

_GOAL_PERIODS: dict[Period, tuple[int, ...]] = {
    Period.FULL_TIME: (1, 2),
    Period.FIRST_HALF: (1,),
    Period.SECOND_HALF: (2,),
}


def _won(condition: bool) -> SettlementStatus:
    return WON if condition else LOST


def _period_score(
    observation: FootballObservation,
    period: Period,
) -> tuple[PeriodScore | None, str]:
    if period == Period.FULL_TIME:
        return observation.regulation, "tiempo completo (regulación)"
    if period == Period.FIRST_HALF:
        return observation.first_half, "primer tiempo"
    return observation.second_half, "segundo tiempo"


def _score_payload(score: PeriodScore, period: Period) -> dict[str, Any]:
    return {
        "period": period.value,
        "home_goals": score.home,
        "away_goals": score.away,
        "total_goals": score.home + score.away,
        "score": f"{score.home}-{score.away}",
    }


def _winner(score: PeriodScore) -> str:
    if score.home == score.away:
        return "draw"
    return "home" if score.home > score.away else "away"


def _over_under(
    value: float,
    line: float,
    selection: str,
) -> SettlementStatus:
    if abs(value - line) < 1e-9:
        return PUSH
    if selection == "over":
        return _won(value > line)
    return _won(value < line)


def _handicap(
    selected: float,
    opponent: float,
    line: float,
    *,
    european: bool,
) -> SettlementStatus:
    adjusted = selected + line - opponent
    if abs(adjusted) < 1e-9:
        return LOST if european else PUSH
    return _won(adjusted > 0)


def _asian_handicap(selected: int, opponent: int, line: float) -> SettlementStatus:
    adjusted = selected + line - opponent
    if abs(adjusted) < 1e-9:
        return PUSH
    return _won(adjusted > 0)


def _asian_quarter_handicap(
    selected: int, opponent: int, line: float
) -> SettlementStatus:
    lower = int(line * 2 // 1) / 2
    upper = lower + 0.5
    outcomes = [
        _asian_handicap(selected, opponent, half_line)
        for half_line in (lower, upper)
    ]
    wins = outcomes.count(WON)
    losses = outcomes.count(LOST)
    pushes = outcomes.count(PUSH)
    if wins == 2:
        return WON
    if losses == 2:
        return LOST
    if wins and losses:
        return PUSH
    if wins and pushes:
        return SettlementStatus.MEDIA_GANANCIA
    if losses and pushes:
        return SettlementStatus.MEDIA_PERDIDA
    return PUSH


def _european_handicap(
    score: PeriodScore, line: float, selection: str
) -> tuple[SettlementStatus, float, float, str]:
    adjusted_home = score.home + line
    adjusted_away = float(score.away)
    actual = (
        "home" if adjusted_home > adjusted_away
        else "away" if adjusted_home < adjusted_away
        else "draw"
    )
    return _won(actual == selection), adjusted_home, adjusted_away, actual


def _period_stat(
    observation: FootballObservation,
    field: str,
    period: Period,
) -> PeriodScore | None:
    if period == Period.FULL_TIME:
        return getattr(observation, field)
    period_field = getattr(observation, f"{field}_by_period")
    return period_field.get(period.value)


def _team_score(score: PeriodScore, team: str) -> int:
    return score.home if team == "home" else score.away


def _side_name(observation: FootballObservation, side: str | None) -> str:
    if side == "home":
        return observation.home_team
    if side == "away":
        return observation.away_team
    return "equipo no identificado"


def _player_matches(
    player: PlayerObservation,
    *,
    name: str,
    player_id: str | None,
    team: str | None,
) -> bool:
    if player_id and player.player_id:
        if player_id != player.player_id:
            return False
        return not (team and player.team and player.team != team)
    if normalize_name(player.name) != normalize_name(name):
        return False
    if team and player.team and player.team != team:
        return False
    return True


def _find_player(
    observation: FootballObservation,
    *,
    name: str,
    player_id: str | None,
    team: str | None,
) -> PlayerObservation | None:
    matches = [
        player
        for player in observation.players
        if _player_matches(
            player,
            name=name,
            player_id=player_id,
            team=team,
        )
    ]
    if not matches:
        return None
    return matches[0]


def _cards_total(card: CardTotals | None) -> int | None:
    if card is None:
        return None
    return card.yellow + card.red


def _cards_from_events(
    observation: FootballObservation,
    *,
    period: Period,
    team: str | None = None,
    player_name: str | None = None,
) -> int | None:
    if not observation.events_complete:
        return None
    periods = _GOAL_PERIODS[period]
    total = 0
    for event in observation.card_events:
        if event.period not in periods:
            continue
        if event.team is None:
            if player_name is None:
                continue
            if team is not None:
                continue
        if team is not None and event.team != team:
            continue
        if player_name is not None and normalize_name(
            event.player
        ) != normalize_name(player_name):
            continue
        total += event.yellow + event.red
    return total


def _team_cards(
    observation: FootballObservation,
    *,
    period: Period,
    team: str,
) -> int | None:
    # Los eventos son la fuente preferida porque incluyen la segunda amarilla
    # (que el boxscore de ESPN no suma a yellowCards). Las estadísticas solo
    # actúan de respaldo cuando no hay eventos de tarjetas.
    events_total = _cards_from_events(observation, period=period, team=team)
    if events_total:
        return events_total
    if period == Period.FULL_TIME and not observation.went_to_extra_time:
        total = _cards_total((observation.cards or {}).get(team))
        if total is not None:
            return total
    return events_total


def _player_cards(
    observation: FootballObservation,
    *,
    period: Period,
    name: str,
    player_id: str | None,
    team: str | None,
) -> tuple[int | None, str]:
    player = _find_player(
        observation, name=name, player_id=player_id, team=team
    )
    events_total = _cards_from_events(
        observation,
        period=period,
        team=team,
        player_name=name,
    )
    if events_total:
        return events_total, "tarjetas del jugador en los eventos del periodo"
    if period == Period.FULL_TIME and not observation.went_to_extra_time:
        if player is not None and (
            player.yellow_cards is not None or player.red_cards is not None
        ):
            total = (player.yellow_cards or 0) + (player.red_cards or 0)
            if total:
                return total, "tarjetas del jugador en el resumen del partido"
    if events_total is not None and (
        player is not None or observation.rosters_complete
    ):
        return 0, "sin tarjetas en los eventos del periodo"
    if observation.rosters_complete:
        if player is None:
            return 0, "el jugador no aparece en la plantilla disponible"
        if player.appeared is False:
            return 0, "el jugador no participó"
    return None, "sin datos verificables del jugador"


def _player_count(
    observation: FootballObservation,
    *,
    name: str,
    player_id: str | None,
    team: str | None,
    attribute: str,
    period: Period,
) -> tuple[int | None, str]:
    player = _find_player(
        observation, name=name, player_id=player_id, team=team
    )
    if player is None:
        if observation.rosters_complete:
            return 0, "el jugador no aparece en la plantilla disponible"
        return None, "sin datos verificables del jugador"
    value = (
        getattr(player, attribute)
        if period == Period.FULL_TIME
        else (player.period_stats.get(period.value) or {}).get(attribute)
    )
    if value is not None:
        return value, "estadística del jugador en el resumen del partido"
    if player.appeared is False:
        return 0, "el jugador no participó"
    return None, "la fuente no reporta la estadística del jugador"


def _scores_note(
    observation: FootballObservation,
    period: Period,
) -> str:
    score, label = _period_score(observation, period)
    if score is None:
        return "sin marcador verificable"
    return f"marcador {score.home}-{score.away} ({label})"


def settle_prediction(
    prediction: dict[str, Any],
    observation: FootballObservation,
) -> SettlementResult:
    """Liquida una selección contra la observación del partido."""
    market = Market(str(prediction["market"]))
    period = Period(str(prediction.get("period") or Period.FULL_TIME))
    selection = prediction.get("selection")
    line = prediction.get("line")
    team = prediction.get("team")

    if observation.phase in ("cancelled", "abandoned"):
        return SettlementResult(
            status=VOID,
            observed={
                "phase": observation.phase,
                "status": observation.status_name,
            },
            summary="El partido se canceló o abandonó.",
            reason="La fuente reporta el partido como cancelado o abandonado.",
        )
    if observation.phase in ("postponed", "scheduled", "in_play", "unknown"):
        return SettlementResult(
            status=PENDING,
            observed={
                "phase": observation.phase,
                "status": observation.status_name,
            },
            summary="El partido aún no termina o fue reprogramado.",
            reason="La liquidación se reintentará cuando haya resultado final.",
        )

    score, period_label = _period_score(observation, period)
    if score is None:
        return SettlementResult(
            status=NOT_EVALUABLE,
            observed={
                "period": period.value,
                "phase": observation.phase,
                "status": observation.status_name,
            },
            summary=(
                "No hay marcador verificable para el periodo solicitado."
            ),
            reason=(
                "La fuente no publica el marcador del periodo o el partido "
                "requirió alargue y no se puede aislar la regulación."
            ),
        )

    base = _score_payload(score, period)
    total = score.home + score.away

    if market == Market.ONE_X_TWO:
        actual = _winner(score)
        return SettlementResult(
            status=_won(selection == actual),
            observed={**base, "winner": actual},
            summary=(
                f"{_scores_note(observation, period)}; ganador: "
                f"{'empate' if actual == 'draw' else _side_name(observation, actual)}."
            ),
        )

    if market == Market.DOUBLE_CHANCE:
        actual = _winner(score)
        accepted = {
            "home_or_draw": {"home", "draw"},
            "home_or_away": {"home", "away"},
            "draw_or_away": {"draw", "away"},
        }.get(str(selection), set())
        return SettlementResult(
            status=_won(actual in accepted),
            observed={**base, "winner": actual},
            summary=(
                f"{_scores_note(observation, period)}; doble oportunidad "
                f"{selection}: {'acertada' if actual in accepted else 'fallada'}."
            ),
        )

    if market in (Market.ASIAN_HANDICAP, Market.EUROPEAN_HANDICAP):
        if market == Market.EUROPEAN_HANDICAP:
            status, adjusted_home, adjusted_away, actual = _european_handicap(
                score, float(line), str(selection)
            )
            return SettlementResult(
                status=status,
                observed={
                    **base,
                    "home_handicap": line,
                    "adjusted_home": adjusted_home,
                    "adjusted_away": adjusted_away,
                    "adjusted_result": actual,
                },
                summary=(
                    f"{_scores_note(observation, period)}; resultado con "
                    f"hándicap local {float(line):+g}: {actual}."
                ),
            )
        selected = _team_score(score, str(selection))
        opponent = score.away if selection == "home" else score.home
        status = (
            _asian_quarter_handicap(selected, opponent, float(line))
            if abs(float(line) * 2 - round(float(line) * 2)) > 1e-9
            else _asian_handicap(selected, opponent, float(line))
        )
        adjusted = selected + float(line) - opponent
        return SettlementResult(
            status=status,
            observed={
                **base,
                "selected_team": selection,
                "line": line,
                "adjusted_margin": adjusted,
            },
            summary=(
                f"{_scores_note(observation, period)}; {_side_name(observation, str(selection))} "
                f"con línea {float(line):+g} queda {adjusted:+g}."
            ),
        )

    if market == Market.TOTAL_GOALS:
        status = _over_under(total, float(line), str(selection))
        return SettlementResult(
            status=status,
            observed={**base, "line": line},
            summary=(
                f"{_scores_note(observation, period)}; total {total} vs línea "
                f"{float(line):g}: {status.value}."
            ),
        )

    if market == Market.TEAM_TOTAL_GOALS:
        value = _team_score(score, str(team))
        status = _over_under(value, float(line), str(selection))
        return SettlementResult(
            status=status,
            observed={
                **base,
                "team": team,
                "team_goals": value,
                "line": line,
            },
            summary=(
                f"{_scores_note(observation, period)}; {_side_name(observation, str(team))} "
                f"anotó {value} vs línea {float(line):g}: {status.value}."
            ),
        )

    if market == Market.BTTS:
        both = score.home > 0 and score.away > 0
        status = _won(both if selection == "yes" else not both)
        return SettlementResult(
            status=status,
            observed={**base, "both_scored": both},
            summary=(
                f"{_scores_note(observation, period)}; ambos anotaron: "
                f"{'sí' if both else 'no'}."
            ),
        )

    if market == Market.EXACT_SCORE:
        exact = (
            score.home == prediction.get("home_goals")
            and score.away == prediction.get("away_goals")
        )
        return SettlementResult(
            status=_won(exact),
            observed=base,
            summary=(
                f"{_scores_note(observation, period)}; marcador esperado "
                f"{prediction.get('home_goals')}-{prediction.get('away_goals')}."
            ),
        )

    if market == Market.FIRST_TEAM_TO_SCORE:
        status, observed, summary = _settle_first_team(
            observation, period, score, str(selection)
        )
        return SettlementResult(
            status=status,
            observed={**base, **observed},
            summary=f"{_scores_note(observation, period)}; {summary}",
        )

    if market in (
        Market.CORNERS_TOTAL,
        Market.CORNERS_TEAM,
        Market.CORNERS_HANDICAP,
        Market.CORNERS_MOST,
    ):
        return _settle_corners(
            observation,
            market,
            period,
            selection,
            line,
            team,
        )

    if market in (
        Market.CARDS_TOTAL,
        Market.CARDS_TEAM,
        Market.CARDS_PLAYER,
    ):
        return _settle_cards(observation, prediction, market, period)

    if market in (
        Market.SHOTS_TOTAL,
        Market.SHOTS_TEAM,
        Market.SHOTS_PLAYER,
        Market.SHOTS_ON_TARGET_TOTAL,
        Market.SHOTS_ON_TARGET_TEAM,
        Market.SHOTS_ON_TARGET_PLAYER,
    ):
        return _settle_shots(observation, prediction, market, period)

    return SettlementResult(
        status=NOT_EVALUABLE,
        observed=base,
        summary="Mercado sin regla de liquidación implementada.",
        reason=f"El mercado {market.value} no tiene regla registrada.",
    )


def _settle_first_team(
    observation: FootballObservation,
    period: Period,
    score: PeriodScore,
    selection: str,
) -> tuple[SettlementStatus, dict[str, Any], str]:
    periods = _GOAL_PERIODS[period]
    goals = [
        goal
        for goal in observation.goals
        if goal.period in periods
    ]
    total = score.home + score.away
    if total == 0 and not goals:
        actual = "none"
        return (
            _won(selection == actual),
            {"first_team": actual, "goal_count": 0},
            "no hubo goles; gana «none».",
        )
    if len(goals) != total or any(goal.team is None for goal in goals):
        return (
            NOT_EVALUABLE,
            {"goal_count": len(goals), "expected_goals": total},
            "los eventos de gol no coinciden con el marcador.",
        )
    ordered = sorted(goals, key=lambda goal: goal.order)
    first = ordered[0]
    actual = first.team or "none"
    return (
        _won(selection == actual),
        {
            "first_team": actual,
            "first_goal_clock": first.clock,
            "first_goal_player": first.player,
            "goal_count": len(goals),
        },
        f"el primer gol fue de {_side_name(observation, actual)}"
        if actual != "none"
        else "no hubo goles.",
    )


def _settle_corners(
    observation: FootballObservation,
    market: Market,
    period: Period,
    selection: str | None,
    line: float | None,
    team: str | None,
) -> SettlementResult:
    if observation.went_to_extra_time and period == Period.FULL_TIME:
        return SettlementResult(
            status=NOT_EVALUABLE,
            observed={"period": period.value, "extra_time": True},
            summary="No se pueden aislar los córners de la regulación.",
            reason=(
                "La fuente reporta córners del partido completo (incluido "
                "alargue) y el periodo solicitado es tiempo completo."
            ),
        )
    corners = _period_stat(observation, "corners", period)
    if corners is None:
        return SettlementResult(
            status=NOT_EVALUABLE,
            observed={"period": period.value},
            summary=f"La fuente no reporta córners verificables para {period.value}.",
            reason=(
                "No hay datos desglosados para este periodo; no se usa el "
                "total del partido para inferir una mitad."
            ),
        )
    total = corners.home + corners.away
    observed = {
        "period": period.value,
        "home": corners.home,
        "away": corners.away,
        "total": total,
    }
    if market == Market.CORNERS_TOTAL:
        status = _over_under(total, float(line), str(selection))
        return SettlementResult(
            status=status,
            observed={**observed, "line": line},
            summary=f"Córners {corners.home}-{corners.away} (total {total}) vs línea {float(line):g}.",
        )
    if market == Market.CORNERS_TEAM:
        value = _team_score(corners, str(team))
        status = _over_under(value, float(line), str(selection))
        return SettlementResult(
            status=status,
            observed={**observed, "team": team, "team_corners": value, "line": line},
            summary=(
                f"Córners de {_side_name(observation, team)}: {value} vs "
                f"línea {float(line):g}."
            ),
        )
    if market == Market.CORNERS_HANDICAP:
        selected = _team_score(corners, str(selection))
        opponent = corners.away if selection == "home" else corners.home
        status = _handicap(selected, opponent, float(line), european=False)
        return SettlementResult(
            status=status,
            observed={
                **observed,
                "selected_team": selection,
                "line": line,
                "adjusted_margin": selected + float(line) - opponent,
            },
            summary=(
                f"Córners {corners.home}-{corners.away}; "
                f"{_side_name(observation, str(selection))} con línea "
                f"{float(line):+g}."
            ),
        )
    if corners.home == corners.away:
        status = PUSH
        actual = "draw"
    else:
        actual = "home" if corners.home > corners.away else "away"
        status = _won(selection == actual)
    return SettlementResult(
        status=status,
        observed={**observed, "most": actual},
        summary=(
            f"Córners {corners.home}-{corners.away}; más córners: "
            f"{'empate' if actual == 'draw' else _side_name(observation, actual)}."
        ),
    )


def _settle_cards(
    observation: FootballObservation,
    prediction: dict[str, Any],
    market: Market,
    period: Period,
) -> SettlementResult:
    line = prediction.get("line")
    selection = str(prediction.get("selection"))
    if market == Market.CARDS_PLAYER:
        name = str(prediction.get("player") or "")
        total, note = _player_cards(
            observation,
            period=period,
            name=name,
            player_id=prediction.get("player_id"),
            team=prediction.get("team"),
        )
        if total is None:
            return SettlementResult(
                status=NOT_EVALUABLE,
                observed={
                    "period": period.value,
                    "player": name,
                    "line": line,
                },
                summary=f"Sin datos verificables de tarjetas para {name}.",
                reason=note,
            )
        status = _over_under(total, float(line), selection)
        return SettlementResult(
            status=status,
            observed={
                "period": period.value,
                "player": name,
                "cards": total,
                "line": line,
            },
            summary=f"{name}: {total} tarjeta(s) vs línea {float(line):g} ({note}).",
        )

    if market == Market.CARDS_TEAM:
        team = str(prediction.get("team"))
        total = _team_cards(observation, period=period, team=team)
        if total is None:
            return SettlementResult(
                status=NOT_EVALUABLE,
                observed={"period": period.value, "team": team, "line": line},
                summary="Sin datos verificables de tarjetas por equipo.",
                reason="La fuente no separa las tarjetas del periodo solicitado.",
            )
        status = _over_under(total, float(line), selection)
        return SettlementResult(
            status=status,
            observed={
                "period": period.value,
                "team": team,
                "cards": total,
                "line": line,
            },
            summary=(
                f"Tarjetas de {_side_name(observation, team)}: {total} vs "
                f"línea {float(line):g}."
            ),
        )

    home = _team_cards(observation, period=period, team="home")
    away = _team_cards(observation, period=period, team="away")
    if home is None or away is None:
        return SettlementResult(
            status=NOT_EVALUABLE,
            observed={"period": period.value, "line": line},
            summary="Sin datos verificables de tarjetas totales.",
            reason="La fuente no permite contar las tarjetas del periodo.",
        )
    total = home + away
    status = _over_under(total, float(line), selection)
    return SettlementResult(
        status=status,
        observed={
            "period": period.value,
            "home": home,
            "away": away,
            "total": total,
            "line": line,
        },
        summary=f"Tarjetas {home}-{away} (total {total}) vs línea {float(line):g}.",
    )


def _settle_shots(
    observation: FootballObservation,
    prediction: dict[str, Any],
    market: Market,
    period: Period,
) -> SettlementResult:
    on_target = market in (
        Market.SHOTS_ON_TARGET_TOTAL,
        Market.SHOTS_ON_TARGET_TEAM,
        Market.SHOTS_ON_TARGET_PLAYER,
    )
    label = "remates a puerta" if on_target else "remates"
    attr = "shots_on_target" if on_target else "shots"
    data: PeriodScore | None = _period_stat(observation, attr, period)
    line = prediction.get("line")
    selection = str(prediction.get("selection"))

    if observation.went_to_extra_time and period == Period.FULL_TIME:
        return SettlementResult(
            status=NOT_EVALUABLE,
            observed={"period": period.value, "extra_time": True},
            summary=f"No se pueden aislar los {label} de {period.value}.",
            reason=(
                "La fuente reporta estadísticas del partido completo (incluido "
                "alargue) y el periodo solicitado no puede aislarse."
            ),
        )

    if market in (Market.SHOTS_TOTAL, Market.SHOTS_ON_TARGET_TOTAL):
        if data is None:
            return SettlementResult(
                status=NOT_EVALUABLE,
                observed={"period": period.value},
                summary=f"La fuente no reporta {label} verificables para {period.value}.",
                reason=(
                    "No hay datos desglosados para este periodo; no se usa el "
                    "total del partido para inferir una mitad."
                ),
            )
        total = data.home + data.away
        status = _over_under(total, float(line), selection)
        return SettlementResult(
            status=status,
            observed={"period": period.value, "home": data.home, "away": data.away, "total": total, "line": line},
            summary=f"{label.capitalize()} {data.home}-{data.away} (total {total}) vs línea {float(line):g}.",
        )

    if market in (Market.SHOTS_TEAM, Market.SHOTS_ON_TARGET_TEAM):
        team = str(prediction.get("team"))
        if data is None:
            return SettlementResult(
                status=NOT_EVALUABLE,
                observed={"period": period.value, "team": team},
                summary=f"La fuente no reporta {label} por equipo.",
                reason=(
                    "No hay datos desglosados para este periodo; no se usa el "
                    "total del partido para inferir una mitad."
                ),
            )
        value = _team_score(data, team)
        status = _over_under(value, float(line), selection)
        return SettlementResult(
            status=status,
            observed={
                "period": period.value,
                "home": data.home,
                "away": data.away,
                "team": team,
                "value": value,
                "line": line,
            },
            summary=(
                f"{label.capitalize()} de {_side_name(observation, team)}: "
                f"{value} vs línea {float(line):g}."
            ),
        )

    name = str(prediction.get("player") or "")
    value, note = _player_count(
        observation,
        name=name,
        player_id=prediction.get("player_id"),
        team=prediction.get("team"),
        attribute=attr,
        period=period,
    )
    if value is None:
        return SettlementResult(
            status=NOT_EVALUABLE,
            observed={"period": period.value, "player": name, "line": line},
            summary=f"Sin datos verificables de {label} para {name}.",
            reason=note,
        )
    status = _over_under(value, float(line), selection)
    return SettlementResult(
        status=status,
        observed={"period": period.value, "player": name, "value": value, "line": line},
        summary=f"{name}: {value} {label} vs línea {float(line):g} ({note}).",
    )


__all__ = ["SettlementResult", "settle_prediction"]
