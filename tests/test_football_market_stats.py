from app.sports.football.market_stats_client import FootballMarketStatsClient
from app.sports.football.service import FootballPredictionService


def test_parses_public_corner_and_card_averages():
    corners = """
    <p>Liga matches have averaged 10.1 corners per game in 2026
    across 192 fixtures.</p>
    """
    cards = """
    <p>The average cards per game in the Serie A is 5.02 cards.</p>
    <p>There have been 964 cards in 192 matches.</p>
    """

    assert FootballMarketStatsClient._parse_corners(corners) == (10.1, 192)
    assert FootballMarketStatsClient._parse_cards(cards) == (5.02, 192)


def test_builds_corner_and_card_markets_from_league_averages():
    markets = FootballPredictionService._build_markets(
        "Home",
        "Away",
        (0.5, 0.3, 0.2),
        1.8,
        0.9,
        {
            "corners": {"average": 10.1, "sample_games": 192},
            "cards": {"average": 5.02, "sample_games": 192},
        },
    )

    assert markets.corners.available is True
    assert markets.corners.line == 10.5
    assert markets.corners.projected_total == 10.1
    assert markets.cards.available is True
    assert markets.cards.line == 5.5
    assert markets.cards.projected_total == 5.02
