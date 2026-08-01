import asyncio
import math
from datetime import datetime
from typing import Any

import httpx

from app.shared.exceptions import ApiSportsError


class FootballDataClient:
    """Adapts football-data.org resources to the internal API-Football shape."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Auth-Token": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )
        self._fixtures: dict[int, dict[str, Any]] = {}
        self._standings: dict[int, dict[int, dict[str, Any]]] = {}
        self._standings_locks: dict[int, asyncio.Lock] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def get_fixtures(self, target_date: str, timezone: str) -> list[dict[str, Any]]:
        payload = await self._get(
            "/matches",
            {"dateFrom": target_date, "dateTo": target_date},
        )
        fixtures = [self._adapt_match(match, timezone) for match in payload.get("matches", [])]
        self._fixtures = {
            fixture["fixture"]["id"]: fixture
            for fixture in fixtures
        }
        return fixtures

    async def get_current_leagues(self) -> list[dict[str, Any]]:
        payload = await self._get("/competitions")
        return [
            {
                "league": {
                    "id": item["id"],
                    "name": item.get("name"),
                },
                "seasons": [
                    {
                        "year": datetime.now().year,
                        "coverage": {
                            "predictions": False,
                            "injuries": False,
                            "standings": True,
                            "fixtures": {},
                        },
                    }
                ],
            }
            for item in payload.get("competitions", [])
            if item.get("id")
        ]

    async def get_prediction(self, fixture_id: int) -> dict[str, Any] | None:
        fixture = self._fixtures.get(fixture_id)
        if not fixture:
            return None
        competition_id = fixture["league"]["id"]
        standings = await self._competition_standings(competition_id)
        home = standings.get(fixture["teams"]["home"]["id"])
        away = standings.get(fixture["teams"]["away"]["id"])
        if not home or not away:
            return None

        home_strength = self._team_strength(home, home_advantage=0.08)
        away_strength = self._team_strength(away, home_advantage=0)
        draw = 0.27
        home_share = 1 / (1 + math.exp(-(home_strength - away_strength)))
        home_probability = (1 - draw) * home_share
        away_probability = (1 - draw) * (1 - home_share)
        expected_home = self._expected_goals(home, away, home_team=True)
        expected_away = self._expected_goals(away, home, home_team=False)

        return {
            "_provider": "football-data.org",
            "_warnings": [
                "Fuente alternativa: tabla, forma y resultados de football-data.org."
            ],
            "predictions": {
                "percent": {
                    "home": f"{home_probability * 100:.2f}%",
                    "draw": f"{draw * 100:.2f}%",
                    "away": f"{away_probability * 100:.2f}%",
                },
                "goals": {
                    "home": f"{expected_home:.2f}",
                    "away": f"{expected_away:.2f}",
                },
                "advice": "Modelo propio basado en tabla, forma y diferencia de goles.",
            },
            "comparison": {
                "form": self._comparison(home, away, "form_score"),
                "att": self._comparison(home, away, "goals_for_rate"),
                "def": self._comparison(home, away, "defense_score"),
            },
        }

    async def _competition_standings(
        self,
        competition_id: int,
    ) -> dict[int, dict[str, Any]]:
        if competition_id in self._standings:
            return self._standings[competition_id]
        lock = self._standings_locks.setdefault(competition_id, asyncio.Lock())
        async with lock:
            if competition_id in self._standings:
                return self._standings[competition_id]
            payload = await self._get(f"/competitions/{competition_id}/standings")
            table = next(
                (
                    item.get("table", [])
                    for item in payload.get("standings", [])
                    if item.get("type") == "TOTAL"
                ),
                [],
            )
            index = {
                row["team"]["id"]: self._standing_metrics(row)
                for row in table
                if row.get("team", {}).get("id")
            }
            self._standings[competition_id] = index
            return index

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise ApiSportsError("Falta FOOTBALL_DATA_API_KEY en football_api/.env.")
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ApiSportsError(f"Error consultando football-data.org: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ApiSportsError("Respuesta inesperada de football-data.org.")
        return payload

    @staticmethod
    def _adapt_match(match: dict[str, Any], timezone: str) -> dict[str, Any]:
        status_map = {
            "SCHEDULED": "NS",
            "TIMED": "NS",
            "IN_PLAY": "LIVE",
            "PAUSED": "HT",
            "FINISHED": "FT",
            "POSTPONED": "PST",
            "CANCELLED": "CANC",
            "SUSPENDED": "SUSP",
        }
        competition = match.get("competition", {})
        season = match.get("season", {})
        score = match.get("score", {}).get("fullTime", {})
        return {
            "fixture": {
                "id": match["id"],
                "date": match["utcDate"],
                "status": {"short": status_map.get(match.get("status"), "TBD")},
                "source": "football-data.org",
            },
            "league": {
                "id": competition.get("id"),
                "name": competition.get("name", "Unknown"),
                "country": competition.get("area", {}).get("name"),
                "season": FootballDataClient._season_year(season),
            },
            "teams": {
                "home": {
                    "id": match.get("homeTeam", {}).get("id"),
                    "name": match.get("homeTeam", {}).get("name"),
                },
                "away": {
                    "id": match.get("awayTeam", {}).get("id"),
                    "name": match.get("awayTeam", {}).get("name"),
                },
            },
            "goals": {
                "home": score.get("home"),
                "away": score.get("away"),
            },
            "_requested_timezone": timezone,
        }

    @staticmethod
    def _season_year(season: dict[str, Any]) -> int:
        value = season.get("startDate") or ""
        try:
            return int(value[:4])
        except (TypeError, ValueError):
            return datetime.now().year

    @staticmethod
    def _standing_metrics(row: dict[str, Any]) -> dict[str, float]:
        played = max(int(row.get("playedGames") or 0), 1)
        goals_for = float(row.get("goalsFor") or 0)
        goals_against = float(row.get("goalsAgainst") or 0)
        form = str(row.get("form") or "").split(",")
        form_points = sum({"W": 3, "D": 1}.get(item, 0) for item in form if item)
        form_games = max(sum(1 for item in form if item), 1)
        return {
            "played": played,
            "win_rate": float(row.get("won") or 0) / played,
            "draw_rate": float(row.get("draw") or 0) / played,
            "goals_for_rate": goals_for / played,
            "goals_against_rate": goals_against / played,
            "goal_difference_rate": (goals_for - goals_against) / played,
            "form_score": form_points / (3 * form_games),
            "defense_score": 1 / (1 + goals_against / played),
        }

    @staticmethod
    def _team_strength(metrics: dict[str, float], home_advantage: float) -> float:
        return (
            1.5 * metrics["win_rate"]
            + 0.8 * metrics["form_score"]
            + 0.25 * metrics["goal_difference_rate"]
            + home_advantage
        )

    @staticmethod
    def _expected_goals(
        team: dict[str, float],
        opponent: dict[str, float],
        home_team: bool,
    ) -> float:
        value = (team["goals_for_rate"] + opponent["goals_against_rate"]) / 2
        return min(5.0, max(0.2, value + (0.12 if home_team else -0.05)))

    @staticmethod
    def _comparison(
        home: dict[str, float],
        away: dict[str, float],
        field: str,
    ) -> dict[str, str]:
        total = home[field] + away[field]
        if total <= 0:
            return {"home": "50%", "away": "50%"}
        return {
            "home": f"{home[field] / total * 100:.2f}%",
            "away": f"{away[field] / total * 100:.2f}%",
        }
