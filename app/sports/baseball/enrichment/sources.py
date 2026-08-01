import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.sports.baseball.enrichment.models import ExtractedTeamStats

logger = logging.getLogger(__name__)

LEAGUE_SOURCES = {
    "MLB": (
        "MLB standings",
        "https://www.mlb.com/standings",
    ),
    "KBO": (
        "KBO team ranking",
        "https://www.koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx",
    ),
}
ALLOWED_HOSTS = {
    "www.mlb.com",
    "www.koreabaseball.com",
    "eng.koreabaseball.com",
}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())


class BaseballPublicWebSource:
    def __init__(self, timeout_seconds: float = 25.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; SportsResearchBot/1.0; "
                    "+local-data-enrichment)"
                )
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_league_page(self, league: str) -> tuple[str, str, str]:
        source = LEAGUE_SOURCES.get(league.upper())
        if source is None:
            raise ValueError(f"No hay fuente web permitida para {league}.")
        source_name, url = source
        if urlparse(url).hostname not in ALLOWED_HOSTS:
            raise ValueError("La fuente no pertenece a un dominio permitido.")

        text = await self._fetch_html(url, league)
        return source_name, url, text

    async def fetch_schedule_page(
        self,
        league: str,
        target_date: str,
    ) -> tuple[str, str, str]:
        if league == "MLB":
            source_name = "MLB schedule"
            url = f"https://www.mlb.com/schedule/{target_date}"
        elif league == "KBO":
            source_name = "KBO scoreboard"
            url = (
                "https://eng.koreabaseball.com/Schedule/Scoreboard.aspx"
                f"?searchDate={target_date}"
            )
        else:
            raise ValueError(f"No hay calendario permitido para {league}.")
        text = await self._fetch_html(url, league)
        return source_name, url, text

    async def _fetch_html(self, url: str, league: str) -> str:
        if urlparse(url).hostname not in ALLOWED_HOSTS:
            raise ValueError("La fuente no pertenece a un dominio permitido.")
        logger.info("web_source.request league=%s url=%s", league, url)
        response = await self._client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise ValueError("La fuente publica no devolvio HTML.")
        if len(response.content) > 5_000_000:
            raise ValueError("La pagina publica excede el limite permitido.")

        parser = _VisibleTextParser()
        parser.feed(response.text)
        text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
        logger.info(
            "web_source.response league=%s status=%s html_bytes=%s text_chars=%s",
            league,
            response.status_code,
            len(response.content),
            len(text),
        )
        return text[:80_000]

    @staticmethod
    def parse_mlb_standings(
        text: str,
        team_names: list[str],
    ) -> list[ExtractedTeamStats]:
        extracted: list[ExtractedTeamStats] = []
        for team_name in team_names:
            pattern = (
                rf"{re.escape(team_name)}\s+(\d+)\s+(\d+)\s+\.\d{{3}}"
                rf".*?\s+\d+-\d+\s+[WL]\d+\s+(\d+)\s+(\d+)\s+[+-]\d+"
            )
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            wins, losses, runs_for, runs_against = map(int, match.groups())
            extracted.append(
                ExtractedTeamStats(
                    team_name=team_name,
                    games_played=wins + losses,
                    wins=wins,
                    losses=losses,
                    runs_for=runs_for,
                    runs_against=runs_against,
                    source_excerpt=match.group(0)[:500],
                )
            )
        return extracted
