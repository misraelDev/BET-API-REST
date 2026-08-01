from app.sports.tennis.client import PublicTennisClient
from app.sports.tennis.models import TennisTour


def test_flatten_keeps_only_the_requested_tour_grouping():
    events = [{
        "name": "Combined tournament",
        "season": {"year": 2026},
        "groupings": [
            {
                "grouping": {"slug": "mens-singles"},
                "competitions": [{"id": "atp-1", "competitors": [{}, {}]}],
            },
            {
                "grouping": {"slug": "womens-singles"},
                "competitions": [{"id": "wta-1", "competitors": [{}, {}]}],
            },
        ],
    }]

    atp = PublicTennisClient._flatten(events, TennisTour.ATP)
    wta = PublicTennisClient._flatten(events, TennisTour.WTA)

    assert [row["match"]["id"] for row in atp] == ["atp-1"]
    assert [row["match"]["id"] for row in wta] == ["wta-1"]
    assert atp[0]["tour"] == "ATP"
    assert wta[0]["tour"] == "WTA"
