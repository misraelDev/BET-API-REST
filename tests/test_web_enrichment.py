import pytest
from pydantic import ValidationError

from app.sports.baseball.enrichment.models import (
    ExtractedScheduleGame,
    ExtractedTeamStats,
)
from app.sports.baseball.enrichment.schedule_client import (
    PublicBaseballScheduleClient,
)
from app.sports.baseball.enrichment.service import BaseballWebEnrichmentService
from app.sports.baseball.enrichment.sources import BaseballPublicWebSource


def test_extracted_stats_reject_impossible_record():
    with pytest.raises(ValidationError):
        ExtractedTeamStats(
            team_name="Invalid",
            games_played=10,
            wins=8,
            losses=5,
        )


def test_team_matching_requires_a_close_name():
    teams = {
        1: {"id": 1, "name": "New York Yankees"},
        2: {"id": 2, "name": "Boston Red Sox"},
    }

    assert BaseballWebEnrichmentService._match_team(
        "New York Yankees", teams
    ) == (1, "New York Yankees")
    assert BaseballWebEnrichmentService._match_team("Unknown Club", teams) is None


def test_mlb_standings_parser_maps_explicit_values():
    text = (
        "AL East W L PCT GB WCGB L10 STRK RS RA DIFF "
        "New York Yankees 59 45 .567 2.0 +6.0 7-3 W3 484 393 +91"
    )

    rows = BaseballPublicWebSource.parse_mlb_standings(
        text,
        ["New York Yankees"],
    )

    assert rows[0].games_played == 104
    assert rows[0].wins == 59
    assert rows[0].runs_for == 484
    assert rows[0].runs_against == 393


def test_public_schedule_generates_stable_internal_ids():
    game = ExtractedScheduleGame(
        league="MLB",
        home_team="New York Yankees",
        away_team="Boston Red Sox",
        kickoff="2026-07-26T18:00:00-06:00",
    )

    first = PublicBaseballScheduleClient._to_internal_game(game, "2026-07-26")
    second = PublicBaseballScheduleClient._to_internal_game(game, "2026-07-26")

    assert first["id"] == second["id"]
    assert first["teams"]["home"]["id"] == second["teams"]["home"]["id"]
    assert first["_source"] == "public_web"


def test_public_schedule_expands_mlb_abbreviations():
    game = ExtractedScheduleGame(
        league="MLB",
        home_team="TB",
        away_team="CLE",
        kickoff="2026-07-26T18:00:00-06:00",
    )

    internal = PublicBaseballScheduleClient._to_internal_game(
        game,
        "2026-07-26",
    )

    assert internal["teams"]["home"]["name"] == "Tampa Bay Rays"
    assert internal["teams"]["away"]["name"] == "Cleveland Guardians"


def test_public_schedule_preserves_explicit_final_score():
    game = ExtractedScheduleGame(
        league="KBO",
        home_team="KT",
        away_team="LG",
        kickoff="2026-07-26T04:00:00-06:00",
        status="FT",
        home_score=3,
        away_score=5,
    )

    internal = PublicBaseballScheduleClient._to_internal_game(
        game,
        "2026-07-26",
    )

    assert internal["status"]["short"] == "FT"
    assert internal["scores"] == {"home": 3, "away": 5}


def test_public_schedule_parses_official_mlb_schedule_text():
    text = (
        "Sunday Jul 26 CLE CLE @ TB TB 12:15 PM ET Peacock "
        "AZ AZ @ WSH WSH 1:35 PM ET NATS "
        "NYY NYY @ PHI PHI 7:20 PM ET NBC"
    )

    games = PublicBaseballScheduleClient._parse_mlb_schedule(
        text,
        "2026-07-26",
        "America/Mexico_City",
    )

    assert len(games) == 3
    assert games[0].away_team == "Cleveland Guardians"
    assert games[0].home_team == "Tampa Bay Rays"
    assert games[0].kickoff.isoformat() == "2026-07-26T10:15:00-06:00"
    assert games[1].away_team == "Arizona Diamondbacks"
    assert games[1].home_team == "Washington Nationals"
    assert games[2].away_team == "New York Yankees"
    assert games[2].home_team == "Philadelphia Phillies"
