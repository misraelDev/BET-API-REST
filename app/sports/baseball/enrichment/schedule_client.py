import logging
import re
import zlib
from datetime import UTC, datetime, timedelta, timezone as fixed_timezone
from typing import Any

from app.sports.baseball.enrichment.models import ExtractedScheduleGame
from app.sports.baseball.enrichment.sources import BaseballPublicWebSource

logger = logging.getLogger(__name__)

MLB_TEAM_ALIASES = {
    "ARI": "Arizona Diamondbacks",
    "AZ": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "ATH": "Athletics",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "CWS": "Chicago White Sox",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "OAK": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SF": "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TB": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals",
}


class PublicBaseballScheduleClient:
    def __init__(
        self,
        source: BaseballPublicWebSource,
        cache_ttl_seconds: int = 900,
    ) -> None:
        self._source = source
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}

    async def close(self) -> None:
        await self._source.close()

    async def get_games(
        self,
        target_date: str,
        timezone: str,
    ) -> list[dict[str, Any]]:
        cache_key = f"{target_date}:{timezone}"
        cached = self._cache.get(cache_key)
        if cached and datetime.now(UTC) - cached[0] < self._cache_ttl:
            logger.info(
                "public_schedule.cache_hit date=%s games=%s",
                target_date,
                len(cached[1]),
            )
            return cached[1]

        try:
            games = await self._fetch_mlb_games(target_date, timezone)
        except Exception as exc:
            logger.error(
                "public_schedule.failed league=MLB date=%s error=%s",
                target_date,
                exc,
            )
            logger.warning(
                "public_schedule.partial_result_not_cached date=%s games=0",
                target_date,
            )
            return []

        self._cache[cache_key] = (datetime.now(UTC), games)
        logger.info(
            "public_schedule.completed date=%s games=%s source=public_web cached=True",
            target_date,
            len(games),
        )
        return games

    async def get_standings(self, league, season) -> list[dict[str, Any]]:
        return []

    async def _fetch_mlb_games(
        self,
        target_date: str,
        timezone: str,
    ) -> list[dict[str, Any]]:
        _, _, text = await self._source.fetch_schedule_page("MLB", target_date)
        games = [
            self._to_internal_game(game, target_date)
            for game in self._parse_mlb_schedule(
                text,
                target_date,
                timezone,
            )
        ]
        logger.info(
            "public_schedule.parsed league=MLB date=%s games=%s",
            target_date,
            len(games),
        )
        return games

    @classmethod
    def _parse_mlb_schedule(
        cls,
        text: str,
        target_date: str,
        timezone: str,
    ) -> list[ExtractedScheduleGame]:
        aliases = "|".join(
            sorted(map(re.escape, MLB_TEAM_ALIASES), key=len, reverse=True)
        )
        pattern = re.compile(
            rf"\b({aliases})\s+\1\s+@\s+({aliases})\s+\2\s+"
            r"(\d{1,2}:\d{2}\s+[AP]M)\s+ET\b",
            re.IGNORECASE,
        )
        target = datetime.strptime(target_date, "%Y-%m-%d")
        eastern = fixed_timezone(cls._eastern_utc_offset(target))
        requested_offsets = {
            "America/Mexico_City": timedelta(hours=-6),
            "UTC": timedelta(0),
        }
        if timezone not in requested_offsets:
            raise ValueError(f"Zona horaria no soportada para MLB: {timezone}.")
        requested_zone = fixed_timezone(requested_offsets[timezone])
        games: list[ExtractedScheduleGame] = []
        for match in pattern.finditer(text):
            away_alias, home_alias, time_text = match.groups()
            parsed_time = datetime.strptime(time_text.upper(), "%I:%M %p")
            kickoff = datetime(
                target.year,
                target.month,
                target.day,
                parsed_time.hour,
                parsed_time.minute,
                tzinfo=eastern,
            ).astimezone(requested_zone)
            games.append(
                ExtractedScheduleGame(
                    league="MLB",
                    home_team=cls._canonical_team("MLB", home_alias),
                    away_team=cls._canonical_team("MLB", away_alias),
                    kickoff=kickoff,
                    status="NS",
                )
            )
        if not games:
            raise ValueError("No se pudieron extraer juegos MLB de la pagina oficial.")
        return games

    @staticmethod
    def _eastern_utc_offset(target: datetime) -> timedelta:
        # US daylight time: second Sunday in March through first Sunday in November.
        march_first = datetime(target.year, 3, 1)
        second_sunday = 8 + (6 - march_first.weekday()) % 7
        november_first = datetime(target.year, 11, 1)
        first_sunday = 1 + (6 - november_first.weekday()) % 7
        daylight_start = datetime(target.year, 3, second_sunday)
        daylight_end = datetime(target.year, 11, first_sunday)
        return timedelta(hours=-4 if daylight_start <= target < daylight_end else -5)

    @staticmethod
    def _stable_id(value: str) -> int:
        return zlib.crc32(value.casefold().encode("utf-8")) & 0x7FFFFFFF

    @classmethod
    def _to_internal_game(cls, game, target_date: str) -> dict[str, Any]:
        league = game.league.upper()
        home_team = cls._canonical_team(league, game.home_team)
        away_team = cls._canonical_team(league, game.away_team)
        home_id = cls._stable_id(f"{league}:team:{home_team}")
        away_id = cls._stable_id(f"{league}:team:{away_team}")
        game_id = cls._stable_id(
            f"{league}:game:{target_date}:{away_team}:{home_team}"
        )
        return {
            "id": game_id,
            "date": game.kickoff.isoformat(),
            "status": {"short": game.status.upper()},
            "league": {
                "id": cls._stable_id(f"{league}:league"),
                "name": league,
                "season": game.kickoff.year,
            },
            "season": game.kickoff.year,
            "teams": {
                "home": {"id": home_id, "name": home_team},
                "away": {"id": away_id, "name": away_team},
            },
            "scores": {
                "home": game.home_score,
                "away": game.away_score,
            },
            "_source": "public_web",
        }

    @staticmethod
    def _canonical_team(league: str, team_name: str) -> str:
        normalized = team_name.strip()
        if league == "MLB":
            return MLB_TEAM_ALIASES.get(normalized.upper(), normalized)
        return normalized
