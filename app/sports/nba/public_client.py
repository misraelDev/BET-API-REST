import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


class PublicBasketballClient:
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball"
    STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball"
    LEAGUES = (
        "nba", "wnba", "nba-summer-california", "nba-summer-golden-state",
        "nba-summer-las-vegas", "nba-summer-orlando",
        "nba-summer-sacramento", "nba-summer-utah",
    )

    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_games(self, target_date: str, timezone: str) -> list[dict[str, Any]]:
        del timezone
        date_value = target_date.replace("-", "")
        responses = await asyncio.gather(*(
            self._client.get(
                f"{self.BASE_URL}/{league}/scoreboard",
                params={"dates": date_value, "limit": 100},
            )
            for league in self.LEAGUES
        ))
        games: dict[int, dict[str, Any]] = {}
        for league, response in zip(self.LEAGUES, responses, strict=True):
            response.raise_for_status()
            for event in response.json().get("events") or []:
                mapped = self._map_event(event, league)
                if mapped:
                    games[mapped["id"]] = mapped
        return list(games.values())

    async def get_standings(self, league: str | int, season: str | int) -> list[dict[str, Any]]:
        slug = str(league)
        response = await self._client.get(
            f"{self.STANDINGS_URL}/{slug}/standings", params={"season": season}
        )
        response.raise_for_status()
        rows: list[dict[str, Any]] = []
        for group in response.json().get("children") or []:
            for entry in (group.get("standings") or {}).get("entries") or []:
                row = self._map_standing(entry)
                if row:
                    rows.append(row)
        return rows

    @staticmethod
    def _map_event(event: dict[str, Any], league: str) -> dict[str, Any] | None:
        competition = next(iter(event.get("competitions") or []), None)
        if not competition:
            return None
        teams: dict[str, dict[str, Any]] = {}
        scores: dict[str, dict[str, float | None]] = {}
        for competitor in competition.get("competitors") or []:
            side = competitor.get("homeAway")
            team = competitor.get("team") or {}
            if side not in {"home", "away"} or team.get("id") is None:
                continue
            teams[side] = {
                "id": int(team["id"]),
                "name": team.get("displayName") or team.get("shortDisplayName") or team["id"],
            }
            try:
                total = float(competitor.get("score"))
            except (TypeError, ValueError):
                total = None
            scores[side] = {"total": total}
        if set(teams) != {"home", "away"}:
            return None
        status = (competition.get("status") or {}).get("type") or {}
        completed = bool(status.get("completed"))
        raw_date = str(event.get("date") or "")
        try:
            local_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(
                timezone(timedelta(hours=-6))
            ).isoformat()
        except ValueError:
            local_date = raw_date
        return {
            "id": int(event["id"]), "date": local_date,
            "status": {"short": "FT" if completed else status.get("state", "NS").upper()},
            "league": {
                "id": league,
                "name": "NBA - Summer League" if league.startswith("nba-summer-") else league.upper(),
            },
            "season": (event.get("season") or {}).get("year"),
            "teams": teams, "scores": scores,
        }

    @staticmethod
    def _record(value: str | None) -> tuple[float, float]:
        try:
            wins, losses = (value or "0-0").split("-", 1)
            return float(wins), float(losses)
        except (TypeError, ValueError):
            return 0.0, 0.0

    @classmethod
    def _map_standing(cls, entry: dict[str, Any]) -> dict[str, Any] | None:
        team = entry.get("team") or {}
        if team.get("id") is None:
            return None
        stats = {item.get("name"): item for item in entry.get("stats") or []}
        wins = float((stats.get("wins") or {}).get("value") or 0)
        losses = float((stats.get("losses") or {}).get("value") or 0)
        played = wins + losses
        avg_for = float((stats.get("avgPointsFor") or {}).get("value") or 0)
        avg_against = float((stats.get("avgPointsAgainst") or {}).get("value") or 0)
        home_wins, home_losses = cls._record((stats.get("Home") or {}).get("displayValue"))
        away_wins, away_losses = cls._record((stats.get("Road") or {}).get("displayValue"))
        last_wins, last_losses = cls._record((stats.get("Last Ten Games") or {}).get("displayValue"))
        return {
            "team": {"id": int(team["id"]), "name": team.get("displayName")},
            "games": {"played": played},
            "win": {"total": wins, "home": home_wins, "away": away_wins, "lastTen": last_wins},
            "loss": {"total": losses, "home": home_losses, "away": away_losses, "lastTen": last_losses},
            "points": {"for": avg_for * played, "against": avg_against * played},
        }
