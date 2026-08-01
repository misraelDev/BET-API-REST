import pytest

from app.sports.football.fusion import FootballDataFusion


def payload(provider, home, draw, away, goals, corners=None):
    result = {
        "_provider": provider,
        "predictions": {
            "percent": {
                "home": f"{home}%",
                "draw": f"{draw}%",
                "away": f"{away}%",
            },
            "goals": {"home": str(goals[0]), "away": str(goals[1])},
        },
    }
    if corners:
        result["_market_stats"] = {
            "corners": {
                "average": corners,
                "sample_games": 100,
                "source_url": provider,
            }
        }
    return result


def test_fuses_independent_probabilities_goals_and_market_totals():
    fused = FootballDataFusion.fuse(
        [
            payload("API-Football", 60, 25, 15, (1.8, 0.8), 10.0),
            payload("football-data.org", 50, 30, 20, (1.5, 1.0), 11.0),
        ]
    )

    assert fused.providers == ["API-Football", "football-data.org"]
    assert fused.probabilities is not None
    assert 0.5 < fused.probabilities[0] < 0.6
    assert 1.5 < fused.expected_home < 1.8
    assert 10 < fused.market_stats["corners"]["average"] < 11
    assert fused.agreement > 80


def test_single_source_is_reported_as_limited_agreement():
    fused = FootballDataFusion.fuse(
        [payload("TheSportsDB public schedule", 45, 30, 25, (1.3, 0.9))]
    )

    assert fused.agreement == 50
    assert fused.providers == ["TheSportsDB public schedule"]
