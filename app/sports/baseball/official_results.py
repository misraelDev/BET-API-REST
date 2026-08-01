import logging
import re
import zlib
from datetime import date, datetime, timedelta, timezone

import httpx

from app.sports.baseball.enrichment.sources import BaseballPublicWebSource
from app.sports.baseball.models import OfficialBaseballGame

logger = logging.getLogger(__name__)


class MlbOfficialResultsClient:
    BASE_URL = "https://statsapi.mlb.com/api/v1"

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": "BET baseball results service/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_results(self, target_date: date) -> list[OfficialBaseballGame]:
        logger.info("mlb.official_results.request date=%s", target_date)
        response = await self._client.get(
            "/schedule",
            params={"sportId": 1, "date": target_date.isoformat()},
        )
        response.raise_for_status()
        games = self._parse_games(response.json())
        logger.info(
            "mlb.official_results.completed date=%s games=%s finals=%s",
            target_date,
            len(games),
            sum(game.is_final for game in games),
        )
        return games

    @staticmethod
    def _parse_games(payload: dict) -> list[OfficialBaseballGame]:
        games: list[OfficialBaseballGame] = []
        for date_entry in payload.get("dates", []):
            for game in date_entry.get("games", []):
                teams = game.get("teams", {})
                home = teams.get("home", {})
                away = teams.get("away", {})
                status = game.get("status", {})
                games.append(
                    OfficialBaseballGame(
                        official_id=int(game["gamePk"]),
                        league="MLB",
                        game_date=datetime.fromisoformat(
                            str(game["gameDate"]).replace("Z", "+00:00")
                        ),
                        status=str(status.get("abstractGameState", "Preview")),
                        detailed_status=str(status.get("detailedState", "Unknown")),
                        home_team=str(home.get("team", {}).get("name", "")),
                        away_team=str(away.get("team", {}).get("name", "")),
                        home_score=home.get("score"),
                        away_score=away.get("score"),
                        is_final=str(status.get("abstractGameState", "")).casefold()
                        == "final",
                    )
                )
        return games


class KboOfficialResultsClient:
    TEAM_CODES = (
        "SAMSUNG",
        "DOOSAN",
        "KT",
        "LOTTE",
        "NC",
        "SSG",
        "KIWOOM",
        "KIA",
        "LG",
        "HANWHA",
    )

    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._source = BaseballPublicWebSource(timeout_seconds=timeout_seconds)

    async def close(self) -> None:
        await self._source.close()

    async def get_results(self, target_date: date) -> list[OfficialBaseballGame]:
        logger.info("kbo.official_results.request date=%s", target_date)
        _, _, text = await self._source.fetch_schedule_page(
            "KBO",
            target_date.isoformat(),
        )
        games = self._parse_games(text, target_date)
        logger.info(
            "kbo.official_results.completed date=%s games=%s finals=%s",
            target_date,
            len(games),
            sum(game.is_final for game in games),
        )
        return games

    @classmethod
    def _parse_games(
        cls,
        text: str,
        target_date: date,
    ) -> list[OfficialBaseballGame]:
        teams = "|".join(cls.TEAM_CODES)
        pattern = re.compile(
            rf"\b({teams})\s+(\d+)\s+"
            rf"(FINAL|CANCELLED|POSTPONED|TOP\s+\d+|BOT\s+\d+)\s+"
            rf"(\d+)\s+({teams})\s+[A-Z]+\s+(\d{{1,2}}:\d{{2}})\b",
            re.IGNORECASE,
        )
        kst = timezone(timedelta(hours=9))
        games: list[OfficialBaseballGame] = []
        for match in pattern.finditer(text):
            away, away_score, raw_status, home_score, home, start_time = (
                match.groups()
            )
            parsed_time = datetime.strptime(start_time, "%H:%M")
            game_date = datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                parsed_time.hour,
                parsed_time.minute,
                tzinfo=kst,
            )
            normalized_status = raw_status.upper()
            is_final = normalized_status == "FINAL"
            status = (
                "Final"
                if is_final
                else (
                    "Live"
                    if normalized_status.startswith(("TOP", "BOT"))
                    else normalized_status.title()
                )
            )
            official_id = zlib.crc32(
                f"KBO:{target_date}:{away.upper()}:{home.upper()}".encode()
            ) & 0x7FFFFFFF
            games.append(
                OfficialBaseballGame(
                    official_id=official_id,
                    league="KBO",
                    game_date=game_date,
                    status=status,
                    detailed_status=normalized_status,
                    home_team=home.upper(),
                    away_team=away.upper(),
                    home_score=int(home_score),
                    away_score=int(away_score),
                    is_final=is_final,
                )
            )
        return games
