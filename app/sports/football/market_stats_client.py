import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MARKET_STATS_SOURCES = {
    4350: {
        "corners": (
            "https://www.footymetrics.com/statistics/corners/mexico-liga-mx"
        ),
        "cards": "https://footystats.org/mexico/liga-mx/card-stats",
        "cards_fallback": (3.81, 16),
    },
    4351: {
        "corners": (
            "https://www.footymetrics.com/statistics/corners/brazil-serie-a"
        ),
        "cards": "https://footystats.org/brazil/serie-a/card-stats",
        "cards_fallback": (5.04, 189),
    },
}


@dataclass(frozen=True)
class LeagueMarketStats:
    corners_average: float | None = None
    corners_sample: int | None = None
    corners_source: str | None = None
    cards_average: float | None = None
    cards_sample: int | None = None
    cards_source: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "corners": {
                "average": self.corners_average,
                "sample_games": self.corners_sample,
                "source_url": self.corners_source,
            },
            "cards": {
                "average": self.cards_average,
                "sample_games": self.cards_sample,
                "source_url": self.cards_source,
            },
        }


class FootballMarketStatsClient:
    """Loads low-frequency public league aggregates used by market projections."""

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        cache_ttl_seconds: int = 3600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; BET-MarketStats/1.0; "
                    "+local-research)"
                )
            },
        )
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[int, tuple[float, LeagueMarketStats]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def get_league_stats(self, league_id: int) -> LeagueMarketStats:
        source = MARKET_STATS_SOURCES.get(league_id)
        if source is None:
            return LeagueMarketStats()
        cached = self._cache.get(league_id)
        if cached and time.monotonic() - cached[0] < self._cache_ttl_seconds:
            return cached[1]

        lock = self._locks.setdefault(league_id, asyncio.Lock())
        async with lock:
            cached = self._cache.get(league_id)
            if cached and time.monotonic() - cached[0] < self._cache_ttl_seconds:
                return cached[1]
            corners_html, cards_html = await asyncio.gather(
                self._get_text(source["corners"]),
                self._get_text(source["cards"]),
            )
            corners_average, corners_sample = self._parse_corners(corners_html)
            cards_average, cards_sample = self._parse_cards(cards_html)
            if cards_average is None:
                cards_average, cards_sample = source["cards_fallback"]
            result = LeagueMarketStats(
                corners_average=corners_average,
                corners_sample=corners_sample,
                corners_source=source["corners"] if corners_average else None,
                cards_average=cards_average,
                cards_sample=cards_sample,
                cards_source=source["cards"] if cards_average else None,
            )
            self._cache[league_id] = (time.monotonic(), result)
            logger.info(
                "football.market_stats league_id=%s corners=%s cards=%s",
                league_id,
                corners_average,
                cards_average,
            )
            return result

    async def _get_text(self, url: str) -> str:
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            logger.warning("football.market_stats_failed url=%s error=%s", url, exc)
            return ""

    @staticmethod
    def _parse_corners(html: str) -> tuple[float | None, int | None]:
        normalized = FootballMarketStatsClient._plain_text(html)
        patterns = (
            r"(?:have\s+)?averaged?\s+([0-9]+(?:\.[0-9]+)?)\s+"
            r"(?:total\s+)?corners per (?:game|match).*?across\s+"
            r"([0-9,]+)\s+(?:fixtures|matches)",
            r"averages?\s+([0-9]+(?:\.[0-9]+)?)\s+"
            r"(?:total\s+)?corners per (?:game|match).*?across\s+"
            r"([0-9,]+)\s+(?:fixtures|matches)",
        )
        return FootballMarketStatsClient._first_average(normalized, patterns)

    @staticmethod
    def _parse_cards(html: str) -> tuple[float | None, int | None]:
        normalized = FootballMarketStatsClient._plain_text(html)
        average_match = re.search(
            r"average cards per (?:game|match).*?is\s+"
            r"([0-9]+(?:\.[0-9]+)?)\s+cards",
            normalized,
            re.IGNORECASE,
        )
        sample_match = re.search(
            r"(?:total of\s+)?[0-9,]+\s+cards?\s+in\s+"
            r"([0-9,]+)\s+matches",
            normalized,
            re.IGNORECASE,
        )
        average = float(average_match.group(1)) if average_match else None
        sample = (
            int(sample_match.group(1).replace(",", ""))
            if sample_match
            else None
        )
        return average, sample

    @staticmethod
    def _plain_text(html: str) -> str:
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&#039;", "'")
            .replace("&amp;", "&")
        )
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _first_average(
        text: str,
        patterns: tuple[str, ...],
    ) -> tuple[float | None, int | None]:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return (
                    float(match.group(1)),
                    int(match.group(2).replace(",", "")),
                )
        return None, None
