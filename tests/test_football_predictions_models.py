from datetime import date

import pytest
from pydantic import ValidationError

from app.sports.football.predictions.models import (
    FootballPredictionBatchRequest,
    FootballPredictionCreate,
)
from app.sports.football.predictions.catalog import league_catalog, market_catalog


def payload(**overrides):
    data = {
        "idempotency_key": "test-key-0001",
        "event_id": 736644,
        "match_date": date(2026, 10, 24),
        "league": "liga_mx",
        "home_team": "Pumas UNAM",
        "away_team": "Necaxa",
        "kickoff": "2026-10-24T20:00:00-06:00",
        "market": "1x2",
        "period": "full_time",
        "selection": "home",
        "probability": 58.0,
        "confidence": 4,
        "rationale": "Local con mejor forma y ventaja de localía.",
        "sources": [{"name": "ESPN"}],
        "analyst": "ana.garcia",
        "method_version": "analista-v1",
    }
    data.update(overrides)
    return data


def test_valid_one_x_two():
    item = FootballPredictionCreate(**payload())

    assert item.market.value == "1x2"
    assert item.period.value == "full_time"
    assert item.selection == "home"
    assert item.selection_summary == "home"


@pytest.mark.parametrize(
    ("market", "period"),
    [("corners_total", "first_half"), ("shots_total", "second_half")],
)
def test_corners_and_shots_accept_halves(market, period):
    item = FootballPredictionCreate(
        **payload(
            market=market,
            period=period,
            selection="over",
            line=9.5,
        )
    )
    assert item.period.value == period


def test_cards_support_halves():
    item = FootballPredictionCreate(
        **payload(
            market="cards_total",
            period="first_half",
            selection="over",
            line=1.5,
        )
    )

    assert item.period.value == "first_half"


def test_total_goals_requires_line():
    with pytest.raises(ValidationError, match="requiere line"):
        FootballPredictionCreate(
            **payload(market="total_goals", selection="over", line=None)
        )


def test_line_must_be_half_step():
    with pytest.raises(ValidationError, match="múltiplo de 0.25"):
        FootballPredictionCreate(
            **payload(market="total_goals", selection="over", line=2.25)
        )


def test_asian_handicap_accepts_quarter_line():
    item = FootballPredictionCreate(
        **payload(market="asian_handicap", selection="home", line=-0.25)
    )
    assert item.line == -0.25


def test_european_handicap_accepts_draw_selection():
    item = FootballPredictionCreate(
        **payload(market="european_handicap", selection="draw", line=-1)
    )
    assert item.selection == "draw"


def test_added_competitions_are_registerable_without_claiming_auto_coverage():
    leagues = {item["code"]: item for item in league_catalog()}
    for code in (
        "saudi_pro_league",
        "qatar_stars_league",
        "afc_champions_league_elite",
        "afc_champions_league_two",
        "conference_league",
    ):
        assert leagues[code]["registration_available"] is True
        assert leagues[code]["automatic_settlement_available"] is False


def test_catalog_does_not_add_markets_and_exposes_steps_and_periods():
    markets = {item["market"]: item for item in market_catalog()}
    assert len(markets) == 22
    assert markets["asian_handicap"]["allowed_line_steps"] == [0.25]
    assert {"full_time", "first_half", "second_half"} <= set(
        markets["shots_total"]["periods"]
    )


def test_team_market_requires_team():
    with pytest.raises(ValidationError, match="requiere team"):
        FootballPredictionCreate(
            **payload(market="team_total_goals", selection="over", line=1.5)
        )


def test_player_market_requires_player():
    with pytest.raises(ValidationError, match="requiere player"):
        FootballPredictionCreate(
            **payload(market="cards_player", selection="over", line=0.5)
        )


def test_player_market_accepts_player():
    item = FootballPredictionCreate(
        **payload(
            market="shots_on_target_player",
            selection="over",
            line=0.5,
            player="Guillermo Martínez",
        )
    )

    assert item.player == "Guillermo Martínez"


def test_exact_score_requires_both_scores_and_no_selection():
    item = FootballPredictionCreate(
        **payload(
            market="exact_score",
            selection=None,
            home_goals=2,
            away_goals=1,
        )
    )
    assert item.home_goals == 2

    with pytest.raises(ValidationError, match="requiere home_goals"):
        FootballPredictionCreate(
            **payload(market="exact_score", selection=None, home_goals=2)
        )

    with pytest.raises(ValidationError, match="no usa selection"):
        FootballPredictionCreate(
            **payload(
                market="exact_score",
                selection="home",
                home_goals=2,
                away_goals=1,
            )
        )


def test_invalid_selection_for_market():
    with pytest.raises(ValidationError, match="selection inválida"):
        FootballPredictionCreate(**payload(market="1x2", selection="over"))


def test_kickoff_requires_offset():
    with pytest.raises(ValidationError, match="debe incluir zona horaria"):
        FootballPredictionCreate(**payload(kickoff="2026-10-24T20:00:00"))


def test_probability_and_confidence_bounds():
    with pytest.raises(ValidationError):
        FootballPredictionCreate(**payload(probability=101))
    with pytest.raises(ValidationError):
        FootballPredictionCreate(**payload(confidence=6))


def test_sources_are_required():
    with pytest.raises(ValidationError):
        FootballPredictionCreate(**payload(sources=[]))


def test_teams_must_differ():
    with pytest.raises(ValidationError, match="deben ser distintos"):
        FootballPredictionCreate(**payload(home_team="Pumas", away_team="Pumas"))


def test_handicap_uses_team_as_selection_and_signed_line():
    item = FootballPredictionCreate(
        **payload(market="asian_handicap", selection="home", line=-1.5)
    )
    assert item.selection == "home"
    assert item.line == -1.5


def test_market_does_not_use_line():
    with pytest.raises(ValidationError, match="no usa line"):
        FootballPredictionCreate(**payload(market="1x2", selection="home", line=1.5))


def test_batch_rejects_duplicate_idempotency_keys():
    item = FootballPredictionCreate(**payload())
    with pytest.raises(ValidationError, match="idempotency_key debe ser única"):
        FootballPredictionBatchRequest(items=[item, item])


def test_batch_rejects_duplicate_prediction_ids():
    first = FootballPredictionCreate(**payload(prediction_id="abcdefgh"))
    second = FootballPredictionCreate(
        **payload(idempotency_key="test-key-0002", prediction_id="abcdefgh")
    )
    with pytest.raises(ValidationError, match="prediction_id debe ser único"):
        FootballPredictionBatchRequest(items=[first, second])


def test_unknown_market_is_rejected():
    with pytest.raises(ValidationError):
        FootballPredictionCreate(**payload(market="assists"))
