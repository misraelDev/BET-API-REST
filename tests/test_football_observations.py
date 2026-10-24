from datetime import UTC, datetime

import pytest

from app.sports.football.predictions.observation import build_observation

RETRIEVED_AT = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)


def summary_payload(**overrides):
    payload = {
        "header": {
            "competitions": [
                {
                    "id": "736644",
                    "date": "2026-10-25T02:00:00Z",
                    "status": {
                        "type": {
                            "name": "STATUS_FULL_TIME",
                            "state": "post",
                            "completed": True,
                            "detail": "FT",
                        }
                    },
                    "competitors": [
                        {
                            "homeAway": "home",
                            "score": "2",
                            "team": {
                                "id": "1",
                                "displayName": "Pumas UNAM",
                            },
                            "linescores": [
                                {"displayValue": "1"},
                                {"displayValue": "1"},
                            ],
                        },
                        {
                            "homeAway": "away",
                            "score": "1",
                            "team": {"id": "2", "displayName": "Necaxa"},
                            "linescores": [
                                {"displayValue": "0"},
                                {"displayValue": "1"},
                            ],
                        },
                    ],
                }
            ]
        },
        "boxscore": {
            "teams": [
                {
                    "homeAway": "home",
                    "statistics": [
                        {"name": "wonCorners", "displayValue": "7"},
                        {"name": "yellowCards", "displayValue": "3"},
                        {"name": "redCards", "displayValue": "1"},
                        {"name": "totalShots", "displayValue": "21"},
                        {"name": "shotsOnTarget", "displayValue": "5"},
                    ],
                },
                {
                    "homeAway": "away",
                    "statistics": [
                        {"name": "wonCorners", "displayValue": "4"},
                        {"name": "yellowCards", "displayValue": "2"},
                        {"name": "redCards", "displayValue": "0"},
                        {"name": "totalShots", "displayValue": "12"},
                        {"name": "shotsOnTarget", "displayValue": "5"},
                    ],
                },
            ]
        },
        "keyEvents": [
            {
                "type": {"text": "Kickoff"},
                "period": {"number": 1},
                "clock": {"displayValue": "0'"},
            },
            {
                "type": {"text": "Goal"},
                "period": {"number": 1},
                "clock": {"displayValue": "20'", "value": 1200},
                "team": {"id": "1", "displayName": "Pumas UNAM"},
                "scoringPlay": True,
                "athletesInvolved": [{"displayName": "Guillermo Martínez"}],
            },
            {
                "type": {"text": "Yellow Card"},
                "period": {"number": 1},
                "clock": {"displayValue": "30'"},
                "team": {"id": "1", "displayName": "Pumas UNAM"},
                "athletesInvolved": [{"displayName": "Jorge Ruvalcaba"}],
            },
            {
                "type": {"text": "Halftime"},
                "period": {"number": 1},
                "clock": {"displayValue": "45'+2'"},
            },
            {
                "type": {"text": "Goal"},
                "period": {"number": 2},
                "clock": {"displayValue": "60'", "value": 3600},
                "team": {"id": "2", "displayName": "Necaxa"},
                "scoringPlay": True,
                "athletesInvolved": [{"displayName": "Diego de Buen"}],
            },
            {
                "type": {"text": "Yellow Card"},
                "period": {"number": 2},
                "clock": {"displayValue": "65'"},
                "team": {"id": "2", "displayName": "Necaxa"},
                "athletesInvolved": [{"displayName": "Diego de Buen"}],
            },
            {
                "type": {"text": "Goal - Header"},
                "period": {"number": 2},
                "clock": {"displayValue": "80'", "value": 4800},
                "team": {"id": "1", "displayName": "Pumas UNAM"},
                "scoringPlay": True,
                "ownGoal": True,
                "athletesInvolved": [{"displayName": "Defensor"}],
            },
            {
                "type": {"text": "Red Card"},
                "period": {"number": 2},
                "clock": {"displayValue": "88'"},
                "team": {"id": "1", "displayName": "Pumas UNAM"},
                "athletesInvolved": [{"displayName": "Jorge Ruvalcaba"}],
            },
            {
                "type": {"text": "End Regular Time"},
                "period": {"number": 2},
                "clock": {"displayValue": "90'+4'"},
            },
        ],
        "rosters": [
            {
                "homeAway": "home",
                "team": {"id": "1", "displayName": "Pumas UNAM"},
                "roster": [
                    {
                        "starter": True,
                        "athlete": {"id": "10", "displayName": "Guillermo Martínez"},
                        "stats": [
                            {"name": "appearances", "value": 1},
                            {"name": "totalShots", "value": 5},
                            {"name": "shotsOnTarget", "value": 2},
                            {"name": "yellowCards", "value": 0},
                            {"name": "redCards", "value": 0},
                        ],
                    },
                    {
                        "starter": True,
                        "athlete": {"id": "11", "displayName": "Jorge Ruvalcaba"},
                        "stats": [
                            {"name": "appearances", "value": 1},
                            {"name": "totalShots", "value": 3},
                            {"name": "shotsOnTarget", "value": 1},
                            {"name": "yellowCards", "value": 1},
                            {"name": "redCards", "value": 1},
                        ],
                    },
                    {
                        "starter": False,
                        "athlete": {"id": "12", "displayName": "Suplente"},
                        "stats": [
                            {"name": "appearances", "value": 0},
                            {"name": "totalShots", "value": 0},
                            {"name": "shotsOnTarget", "value": 0},
                            {"name": "yellowCards", "value": 0},
                            {"name": "redCards", "value": 0},
                        ],
                    },
                ],
            },
            {
                "homeAway": "away",
                "team": {"id": "2", "displayName": "Necaxa"},
                "roster": [
                    {
                        "starter": True,
                        "athlete": {"id": "20", "displayName": "Diego de Buen"},
                        "stats": [
                            {"name": "appearances", "value": 1},
                            {"name": "totalShots", "value": 2},
                            {"name": "shotsOnTarget", "value": 1},
                            {"name": "yellowCards", "value": 1},
                            {"name": "redCards", "value": 0},
                        ],
                    }
                ],
            },
        ],
    }
    payload.update(overrides)
    return payload


def observation(payload=None):
    return build_observation(
        payload or summary_payload(),
        event_id=736644,
        league_slug="mex.1",
        source_url="https://example.test/summary",
        retrieved_at=RETRIEVED_AT,
    )


def test_builds_scores_and_halves():
    result = observation()

    assert result is not None
    assert result.regulation.home == 2
    assert result.regulation.away == 1
    assert result.first_half.home == 1
    assert result.first_half.away == 0
    assert result.second_half.home == 1
    assert result.second_half.away == 1
    assert result.kickoff.isoformat() == "2026-10-25T02:00:00+00:00"
    assert result.phase == "finished"


def test_own_goal_is_credited_to_the_opponent():
    result = observation()

    own_goal = next(goal for goal in result.goals if goal.own_goal)
    assert own_goal.reported_team == "home"
    assert own_goal.team == "away"


def test_corners_cards_and_shots():
    result = observation()

    assert result.corners.home == 7
    assert result.corners.away == 4
    assert result.cards["home"].total == 4
    assert result.cards["away"].total == 2
    assert result.shots.home == 21
    assert result.shots_on_target.away == 5
    assert result.stats_reliable is True


def test_card_events_and_player_stats():
    result = observation()

    assert len(result.card_events) == 3
    ruvalcaba = next(
        player for player in result.players if player.name == "Jorge Ruvalcaba"
    )
    assert ruvalcaba.yellow_cards == 1
    assert ruvalcaba.red_cards == 1
    assert ruvalcaba.shots == 3
    assert result.rosters_complete is False


def test_rosters_complete_requires_both_sides():
    payload = summary_payload()
    payload["rosters"][0]["roster"].extend(
        {
            "starter": False,
            "athlete": {"id": f"h{i}", "displayName": f"Suplente local {i}"},
            "stats": [],
        }
        for i in range(11)
    )
    payload["rosters"][1]["roster"].extend(
        {
            "starter": False,
            "athlete": {"id": f"a{i}", "displayName": f"Suplente visita {i}"},
            "stats": [],
        }
        for i in range(11)
    )

    result = observation(payload)

    assert result.rosters_complete is True


def test_extra_time_uses_only_first_two_linescores():
    payload = summary_payload()
    competition = payload["header"]["competitions"][0]
    competition["status"]["type"]["name"] = "STATUS_FINAL_AET"
    competition["status"]["type"]["detail"] = "AET"
    competition["competitors"][0]["linescores"] = [
        {"displayValue": "1"},
        {"displayValue": "0"},
        {"displayValue": "1"},
        {"displayValue": "0"},
    ]
    competition["competitors"][1]["linescores"] = [
        {"displayValue": "0"},
        {"displayValue": "1"},
        {"displayValue": "0"},
        {"displayValue": "2"},
    ]

    result = observation(payload)

    assert result.went_to_extra_time is True
    assert result.regulation.home == 1
    assert result.regulation.away == 1
    assert result.first_half.home == 1
    assert result.second_half.away == 1


def test_zero_statistics_with_goals_are_flagged_unreliable():
    payload = summary_payload()
    for team in payload["boxscore"]["teams"]:
        team["statistics"] = [
            {"name": "wonCorners", "displayValue": "0"},
            {"name": "yellowCards", "displayValue": "0"},
            {"name": "redCards", "displayValue": "0"},
            {"name": "totalShots", "displayValue": "0"},
            {"name": "shotsOnTarget", "displayValue": "0"},
        ]

    result = observation(payload)

    assert result.stats_reliable is False
    assert result.corners is None
    assert result.shots is None
    assert result.cards is not None  # se recuperan de los eventos


def test_missing_statistics_are_unreliable():
    payload = summary_payload()
    payload["boxscore"] = {"teams": []}

    result = observation(payload)

    assert result.stats_reliable is False
    assert result.corners is None
    assert result.shots is None
    assert result.cards is not None


def test_espn_participants_and_second_yellow():
    payload = summary_payload()
    payload["keyEvents"].append(
        {
            "type": {"text": "Red Card"},
            "text": (
                "Second yellow card to Jorge Ruvalcaba (Pumas UNAM) for a "
                "bad foul."
            ),
            "period": {"number": 2},
            "clock": {"displayValue": "90'"},
            "team": {"id": "1", "displayName": "Pumas UNAM"},
            "participants": [
                {"athlete": {"id": "11", "displayName": "Jorge Ruvalcaba"}}
            ],
        }
    )

    result = observation(payload)

    second_yellow = result.card_events[-1]
    assert second_yellow.player == "Jorge Ruvalcaba"
    assert second_yellow.yellow == 1
    assert second_yellow.red == 1


def test_goal_uses_espn_participants():
    payload = summary_payload()
    for event in payload["keyEvents"]:
        if event.get("scoringPlay"):
            event.pop("athletesInvolved", None)
            event["participants"] = [
                {"athlete": {"id": "270578", "displayName": "André Silva"}}
            ]
            break

    result = observation(payload)

    assert result.goals[0].player == "André Silva"


def test_cancelled_match_phase():
    payload = summary_payload()
    payload["header"]["competitions"][0]["status"]["type"] = {
        "name": "STATUS_CANCELED",
        "state": "post",
        "completed": True,
        "detail": "Canceled",
    }

    result = observation(payload)

    assert result.phase == "cancelled"


def test_missing_competition_returns_none():
    assert (
        build_observation(
            {"header": {"competitions": []}},
            event_id=1,
            league_slug="mex.1",
            source_url="https://example.test",
            retrieved_at=RETRIEVED_AT,
        )
        is None
    )
