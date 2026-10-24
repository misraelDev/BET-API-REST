from datetime import UTC, datetime

import pytest

from app.sports.football.predictions.catalog import SettlementStatus
from app.sports.football.predictions.observation import (
    CardEvent,
    CardTotals,
    FootballObservation,
    GoalEvent,
    ObservationSource,
    PeriodScore,
    PlayerObservation,
)
from app.sports.football.predictions.settlement import settle_prediction


def observation(**overrides):
    data = {
        "event_id": 1,
        "league": "mex.1",
        "status_name": "STATUS_FULL_TIME",
        "phase": "finished",
        "home_team": "Pumas UNAM",
        "away_team": "Necaxa",
        "regulation": PeriodScore(home=2, away=1),
        "first_half": PeriodScore(home=1, away=0),
        "second_half": PeriodScore(home=1, away=1),
        "goals": [
            GoalEvent(
                period=1,
                clock="20'",
                team="home",
                player="Guillermo Martínez",
                order=1200,
            ),
            GoalEvent(
                period=2,
                clock="60'",
                team="away",
                player="Diego de Buen",
                order=3600,
            ),
            GoalEvent(
                period=2,
                clock="80'",
                team="home",
                player="Jorge Ruvalcaba",
                order=4800,
            ),
        ],
        "corners": PeriodScore(home=7, away=4),
        "cards": {
            "home": CardTotals(yellow=2, red=1, total=3),
            "away": CardTotals(yellow=2, red=0, total=2),
        },
        "card_events": [
            CardEvent(
                period=1,
                clock="30'",
                team="home",
                player="Jorge Ruvalcaba",
                yellow=1,
            ),
            CardEvent(
                period=2,
                clock="65'",
                team="away",
                player="Diego de Buen",
                yellow=1,
            ),
            CardEvent(
                period=2,
                clock="75'",
                team="home",
                player="Otro Defensa",
                yellow=1,
            ),
            CardEvent(
                period=2,
                clock="85'",
                team="away",
                player="Otro Visitante",
                yellow=1,
            ),
            CardEvent(
                period=2,
                clock="88'",
                team="home",
                player="Jorge Ruvalcaba",
                red=1,
            ),
        ],
        "shots": PeriodScore(home=21, away=12),
        "shots_on_target": PeriodScore(home=5, away=5),
        "players": [
            PlayerObservation(
                name="Guillermo Martínez",
                player_id="10",
                team="home",
                appeared=True,
                shots=5,
                shots_on_target=2,
                yellow_cards=0,
                red_cards=0,
            ),
            PlayerObservation(
                name="Jorge Ruvalcaba",
                player_id="11",
                team="home",
                appeared=True,
                shots=3,
                shots_on_target=1,
                yellow_cards=1,
                red_cards=1,
            ),
            PlayerObservation(
                name="Diego de Buen",
                player_id="20",
                team="away",
                appeared=True,
                shots=2,
                shots_on_target=1,
                yellow_cards=1,
                red_cards=0,
            ),
            PlayerObservation(
                name="Suplente",
                player_id="30",
                team="home",
                appeared=False,
                shots=0,
                shots_on_target=0,
                yellow_cards=0,
                red_cards=0,
            ),
        ],
        "rosters_complete": True,
        "events_complete": True,
        "source": ObservationSource(retrieved_at=datetime.now(UTC)),
    }
    data.update(overrides)
    return FootballObservation(**data)


def prediction(market, period="full_time", **overrides):
    data = {
        "market": market,
        "period": period,
        "selection": None,
        "line": None,
        "team": None,
        "player": None,
        "player_id": None,
        "home_goals": None,
        "away_goals": None,
        "match": {"home_team": "Pumas UNAM", "away_team": "Necaxa"},
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("market", "selection", "expected"),
    [
        ("1x2", "home", SettlementStatus.ACERTADO),
        ("1x2", "draw", SettlementStatus.FALLADO),
        ("double_chance", "home_or_draw", SettlementStatus.ACERTADO),
        ("double_chance", "draw_or_away", SettlementStatus.FALLADO),
        ("btts", "yes", SettlementStatus.ACERTADO),
        ("btts", "no", SettlementStatus.FALLADO),
    ],
)
def test_result_markets(market, selection, expected):
    result = settle_prediction(
        prediction(market, selection=selection), observation()
    )
    assert result.status == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (-0.5, SettlementStatus.ACERTADO),
        (-1.0, SettlementStatus.REEMBOLSO),
        (-1.5, SettlementStatus.FALLADO),
        (1.5, SettlementStatus.ACERTADO),
    ],
)
def test_asian_handicap(line, expected):
    result = settle_prediction(
        prediction("asian_handicap", selection="home", line=line),
        observation(),
    )
    assert result.status == expected


def test_asian_handicap_away_with_positive_line():
    result = settle_prediction(
        prediction("asian_handicap", selection="away", line=1.5),
        observation(),
    )
    assert result.status == SettlementStatus.ACERTADO


def test_european_handicap_draw_loses():
    result = settle_prediction(
        prediction("european_handicap", selection="home", line=-1.0),
        observation(),
    )
    assert result.status == SettlementStatus.FALLADO


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (-0.25, SettlementStatus.MEDIA_PERDIDA),
        (0.25, SettlementStatus.MEDIA_GANANCIA),
    ],
)
def test_asian_quarter_handicap_half_results(line, expected):
    tied = observation(
        regulation=PeriodScore(home=1, away=1),
        first_half=PeriodScore(home=0, away=0),
        second_half=PeriodScore(home=1, away=1),
    )
    result = settle_prediction(
        prediction("asian_handicap", selection="home", line=line), tied
    )
    assert result.status == expected


def test_european_handicap_draw_is_local_adjusted_draw():
    result = settle_prediction(
        prediction("european_handicap", selection="draw", line=-1),
        observation(),
    )
    assert result.status == SettlementStatus.ACERTADO
    assert result.observed["adjusted_result"] == "draw"


@pytest.mark.parametrize(
    ("line", "selection", "expected"),
    [
        (2.5, "over", SettlementStatus.ACERTADO),
        (3.0, "over", SettlementStatus.REEMBOLSO),
        (3.5, "under", SettlementStatus.ACERTADO),
        (1.5, "under", SettlementStatus.FALLADO),
    ],
)
def test_total_goals(line, selection, expected):
    result = settle_prediction(
        prediction("total_goals", selection=selection, line=line),
        observation(),
    )
    assert result.status == expected


def test_team_total_goals():
    result = settle_prediction(
        prediction(
            "team_total_goals",
            selection="over",
            line=1.5,
            team="home",
        ),
        observation(),
    )
    assert result.status == SettlementStatus.ACERTADO


def test_exact_score():
    won = settle_prediction(
        prediction("exact_score", home_goals=2, away_goals=1),
        observation(),
    )
    lost = settle_prediction(
        prediction("exact_score", home_goals=1, away_goals=1),
        observation(),
    )
    assert won.status == SettlementStatus.ACERTADO
    assert lost.status == SettlementStatus.FALLADO


def test_first_team_to_score_and_none():
    first = settle_prediction(
        prediction("first_team_to_score", selection="home"),
        observation(),
    )
    assert first.status == SettlementStatus.ACERTADO

    no_goals = observation(
        regulation=PeriodScore(home=0, away=0),
        first_half=PeriodScore(home=0, away=0),
        second_half=PeriodScore(home=0, away=0),
        goals=[],
    )
    none = settle_prediction(
        prediction("first_team_to_score", selection="none"),
        no_goals,
    )
    assert none.status == SettlementStatus.ACERTADO


def test_first_team_unverifiable_when_events_do_not_match():
    incomplete = observation(
        goals=[
            GoalEvent(
                period=1,
                clock="20'",
                team="home",
                order=1200,
            )
        ]
    )
    result = settle_prediction(
        prediction("first_team_to_score", selection="home"),
        incomplete,
    )
    assert result.status == SettlementStatus.NO_EVALUABLE


def test_first_half_markets():
    result = settle_prediction(
        prediction("1x2", period="first_half", selection="home"),
        observation(),
    )
    assert result.status == SettlementStatus.ACERTADO


def test_second_half_does_not_accumulate():
    result = settle_prediction(
        prediction("total_goals", period="second_half", selection="over", line=1.5),
        observation(),
    )
    assert result.status == SettlementStatus.ACERTADO


def test_corner_markets():
    total = settle_prediction(
        prediction("corners_total", selection="over", line=10.5),
        observation(),
    )
    handicap = settle_prediction(
        prediction("corners_handicap", selection="home", line=-2.5),
        observation(),
    )
    most = settle_prediction(
        prediction("corners_most", selection="home"),
        observation(),
    )
    assert total.status == SettlementStatus.ACERTADO
    assert handicap.status == SettlementStatus.ACERTADO
    assert most.status == SettlementStatus.ACERTADO


def test_corner_half_never_falls_back_to_match_total():
    result = settle_prediction(
        prediction("corners_total", "first_half", selection="over", line=2.5),
        observation(),
    )
    assert result.status == SettlementStatus.NO_EVALUABLE
    assert "no se usa el total del partido" in result.reason


def test_corner_and_shot_half_data_can_settle_when_explicitly_observed():
    by_half = observation(
        corners_by_period={"first_half": PeriodScore(home=2, away=1)},
        shots_by_period={"second_half": PeriodScore(home=10, away=5)},
        shots_on_target_by_period={"second_half": PeriodScore(home=3, away=2)},
    )
    corners = settle_prediction(
        prediction("corners_total", "first_half", selection="over", line=2.5),
        by_half,
    )
    shots = settle_prediction(
        prediction("shots_total", "second_half", selection="over", line=14.5),
        by_half,
    )
    sot = settle_prediction(
        prediction("shots_on_target_total", "second_half", selection="over", line=4.5),
        by_half,
    )
    assert corners.status == SettlementStatus.ACERTADO
    assert shots.status == SettlementStatus.ACERTADO
    assert sot.status == SettlementStatus.ACERTADO


def test_corner_most_tie_is_refund():
    tied = observation(corners=PeriodScore(home=5, away=5))
    result = settle_prediction(
        prediction("corners_most", selection="home"), tied
    )
    assert result.status == SettlementStatus.REEMBOLSO


def test_card_markets_total_team_and_player():
    total = settle_prediction(
        prediction("cards_total", selection="over", line=4.5),
        observation(),
    )
    team = settle_prediction(
        prediction("cards_team", selection="over", line=2.5, team="home"),
        observation(),
    )
    player = settle_prediction(
        prediction(
            "cards_player",
            selection="over",
            line=1.5,
            player="Jorge Ruvalcaba",
        ),
        observation(),
    )
    assert total.status == SettlementStatus.ACERTADO
    assert team.status == SettlementStatus.ACERTADO
    assert player.status == SettlementStatus.ACERTADO


def test_cards_first_half_uses_events():
    result = settle_prediction(
        prediction("cards_total", period="first_half", selection="over", line=0.5),
        observation(),
    )
    assert result.status == SettlementStatus.ACERTADO

    under = settle_prediction(
        prediction("cards_total", period="first_half", selection="under", line=1.5),
        observation(),
    )
    assert under.status == SettlementStatus.ACERTADO


def test_second_yellow_counts_as_two_cards():
    second_yellow = observation(
        cards={
            "home": CardTotals(yellow=1, red=1, total=2),
            "away": CardTotals(),
        },
        card_events=[
            CardEvent(
                period=1,
                team="home",
                player="Jugador",
                yellow=1,
                red=1,
            )
        ],
    )
    result = settle_prediction(
        prediction("cards_total", selection="over", line=1.5),
        second_yellow,
    )
    assert result.status == SettlementStatus.ACERTADO


def test_card_events_take_precedence_over_boxscore_stats():
    # ESPN reporta la segunda amarilla como un evento rojo y no la suma a
    # yellowCards, por eso los eventos mandan cuando existen.
    espn_style = observation(
        cards={
            "home": CardTotals(yellow=0, red=1, total=1),
            "away": CardTotals(),
        },
        card_events=[
            CardEvent(
                period=1,
                team="home",
                player="Jugador",
                yellow=1,
            ),
            CardEvent(
                period=2,
                team="home",
                player="Jugador",
                yellow=1,
                red=1,
            ),
        ],
    )

    result = settle_prediction(
        prediction("cards_team", selection="over", line=2.5, team="home"),
        espn_style,
    )

    assert result.status == SettlementStatus.ACERTADO
    assert result.observed["cards"] == 3


def test_cards_fall_back_to_stats_without_card_events():
    only_stats = observation(
        cards={
            "home": CardTotals(yellow=2, red=0, total=2),
            "away": CardTotals(yellow=1, red=0, total=1),
        },
        card_events=[],
        events_complete=False,
    )
    result = settle_prediction(
        prediction("cards_total", selection="over", line=2.5),
        only_stats,
    )

    assert result.status == SettlementStatus.ACERTADO
    assert result.observed["total"] == 3


def test_player_not_in_roster_counts_zero():
    result = settle_prediction(
        prediction(
            "shots_player",
            selection="under",
            line=0.5,
            player="Suplente",
        ),
        observation(),
    )
    assert result.status == SettlementStatus.ACERTADO


def test_player_without_roster_data_is_not_evaluable():
    no_rosters = observation(players=[], rosters_complete=False)
    result = settle_prediction(
        prediction(
            "shots_player",
            selection="over",
            line=0.5,
            player="Desconocido",
        ),
        no_rosters,
    )
    assert result.status == SettlementStatus.NO_EVALUABLE


def test_shots_and_shots_on_target():
    total = settle_prediction(
        prediction("shots_total", selection="over", line=32.5),
        observation(),
    )
    on_target = settle_prediction(
        prediction("shots_on_target_total", selection="under", line=10.5),
        observation(),
    )
    player = settle_prediction(
        prediction(
            "shots_on_target_player",
            selection="over",
            line=0.5,
            player="Guillermo Martínez",
        ),
        observation(),
    )
    assert total.status == SettlementStatus.ACERTADO
    assert on_target.status == SettlementStatus.ACERTADO
    assert player.status == SettlementStatus.ACERTADO


def test_corners_unavailable_is_not_evaluable():
    result = settle_prediction(
        prediction("corners_total", selection="over", line=8.5),
        observation(corners=None),
    )
    assert result.status == SettlementStatus.NO_EVALUABLE


def test_extra_time_invalidates_full_time_corners():
    result = settle_prediction(
        prediction("corners_total", selection="over", line=8.5),
        observation(went_to_extra_time=True),
    )
    assert result.status == SettlementStatus.NO_EVALUABLE


def test_pending_and_cancelled():
    pending = settle_prediction(
        prediction("1x2", selection="home"),
        observation(phase="scheduled"),
    )
    cancelled = settle_prediction(
        prediction("1x2", selection="home"),
        observation(phase="cancelled"),
    )
    assert pending.status == SettlementStatus.PENDIENTE
    assert cancelled.status == SettlementStatus.ANULADO


def test_missing_period_score_is_not_evaluable():
    result = settle_prediction(
        prediction("1x2", period="first_half", selection="home"),
        observation(first_half=None),
    )
    assert result.status == SettlementStatus.NO_EVALUABLE
