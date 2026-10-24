import pytest
from pydantic import ValidationError

from app.sports.football.rankings.models import (
    FootballRankingBatchCreate,
    RankingScope,
    RankingType,
)


def _item(**overrides):
    value = {
        "idempotency_key": "ranking-test-20261024-v1",
        "target_date": "2026-10-24",
        "timezone": "America/Mexico_City",
        "analyst": "analista",
        "scope": "league",
        "competition": "liga_mx",
        "ranking_type": "winner",
        "sort_criterion": "probabilidad",
        "sort_direction": "desc",
        "analysis_prompt_version_id": "a" * 32,
        "method_version": "v1",
        "generated_at": "2026-10-24T10:00:00-06:00",
        "coverage": {"coverage_complete": False, "limitations": ["parcial"]},
        "rows": [
            {
                "position": 1,
                "league": "liga_mx",
                "event_id": 1,
                "home_team": "Local",
                "away_team": "Visitante",
                "market": "1x2",
                "period": "full_time",
                "selection": "home",
                "estimate_status": "estimated",
                "probability": 61,
                "confidence": 4,
                "rationale": "Selección enviada por analista.",
            },
            {
                "position": 2,
                "league": "liga_mx",
                "event_id": 2,
                "home_team": "Equipo A",
                "away_team": "Equipo B",
                "market": "1x2",
                "period": "full_time",
                "selection": "away",
                "estimate_status": "not_estimated",
                "no_estimate_reason": "Sin datos suficientes.",
            },
        ],
    }
    value.update(overrides)
    return value


def test_batch_keeps_row_order_and_explicit_no_estimate():
    batch = FootballRankingBatchCreate.model_validate({"items": [_item()]})
    ranking = batch.items[0]
    assert [row.position for row in ranking.rows] == [1, 2]
    assert ranking.rows[1].estimate_status == "not_estimated"
    assert ranking.rows[1].probability is None


def test_rejects_positions_that_disagree_with_submitted_order():
    item = _item()
    item["rows"][1]["position"] = 3
    with pytest.raises(ValidationError, match="posiciones únicas"):
        FootballRankingBatchCreate.model_validate({"items": [item]})


def test_rejects_probability_outside_percent_range():
    item = _item()
    item["rows"][0]["probability"] = 101
    with pytest.raises(ValidationError):
        FootballRankingBatchCreate.model_validate({"items": [item]})


def test_general_ranking_does_not_require_competition():
    item = _item(
        scope="general",
        competition=None,
        ranking_type="overall_high_confidence",
        rows=[
            {
                "position": 1,
                "league": "mls",
                "event_id": 9,
                "home_team": "Local",
                "away_team": "Visitante",
                "market": "corners_total",
                "period": "full_time",
                "line": 8.5,
                "selection": "over",
                "estimate_status": "estimated",
                "probability": 70,
                "confidence": 5,
                "rationale": "Incluido por su confianza.",
            },
            {
                "position": 2,
                "league": "liga_mx",
                "event_id": 10,
                "home_team": "Equipo C",
                "away_team": "Equipo D",
                "market": "1x2",
                "period": "full_time",
                "selection": "home",
                "estimate_status": "estimated",
                "probability": 65,
                "confidence": 4,
                "rationale": "Incluido desde otra liga.",
            },
        ],
    )
    ranking = FootballRankingBatchCreate.model_validate({"items": [item]}).items[0]
    assert ranking.scope == RankingScope.GENERAL
    assert ranking.ranking_type == RankingType.OVERALL_HIGH_CONFIDENCE
