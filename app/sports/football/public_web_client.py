import asyncio
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, timezone as fixed_timezone
from typing import Any

import httpx

from app.shared.exceptions import ApiSportsError
from app.sports.football.market_stats_client import FootballMarketStatsClient

PUBLIC_FOOTBALL_LEAGUES = {
    "liga_mx": {
        "id": 4350,
        "name": "Liga MX",
        "provider_name": "Mexican Primera League",
        "country": "Mexico",
        "season_type": "split_year",
    },
    "brasileirao": {
        "id": 4351,
        "name": "Brasileirão Betano",
        "provider_name": "Brazilian Serie A",
        "country": "Brazil",
        "season_type": "calendar_year",
    },
}


class PublicWebFootballClient:
    """Keyless football source backed by documented public league schedules."""

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        market_stats: FootballMarketStatsClient | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://www.thesportsdb.com/api/v1/json/123",
            timeout=timeout_seconds,
            transport=transport,
        )
        self._fixtures: dict[int, dict[str, Any]] = {}
        self._metrics: dict[int, dict[str, float]] = {}
        self._market_stats = market_stats
        self._fixture_market_stats: dict[int, dict[str, Any]] = {}

    async def close(self) -> None:
        await self._client.aclose()
        if self._market_stats:
            await self._market_stats.close()

    async def get_fixtures(self, target_date: str, timezone: str) -> list[dict[str, Any]]:
        requested = date.fromisoformat(target_date)
        fixtures: list[dict[str, Any]] = []
        completed_events: list[dict[str, Any]] = []
        for league in PUBLIC_FOOTBALL_LEAGUES.values():
            season = self._season_name(requested, league["season_type"])
            season_payload = await self._get(
                "/eventsseason.php",
                {"id": league["id"], "s": season},
            )
            season_events = season_payload.get("events") or []
            events_by_id = {
                event["idEvent"]: event
                for event in season_events
                if event.get("idEvent")
            }
            next_payload = await self._get(
                "/eventsnextleague.php",
                {"id": league["id"]},
            )
            for event in next_payload.get("events") or []:
                if event.get("idEvent"):
                    events_by_id[event["idEvent"]] = event

            target_rounds = {
                str(event.get("intRound"))
                for event in events_by_id.values()
                if (
                    self._event_local_date(event, timezone) == target_date
                    or event.get("dateEvent") == target_date
                    or event.get("dateEventLocal") == target_date
                )
                and event.get("intRound") is not None
            }
            for round_number in sorted(target_rounds):
                round_payload = await self._get(
                    "/eventsround.php",
                    {
                        "id": league["id"],
                        "r": round_number,
                        "s": season,
                    },
                )
                for event in round_payload.get("events") or []:
                    if event.get("idEvent"):
                        events_by_id[event["idEvent"]] = event

            events = list(events_by_id.values())
            completed_events.extend(
                event for event in events if self._is_completed(event)
            )
            fixtures.extend(
                self._adapt_event(event, league, timezone)
                for event in events
                if self._event_local_date(event, timezone) == target_date
            )
        self._metrics = self._build_metrics(completed_events)
        self._fixtures = {
            fixture["fixture"]["id"]: fixture
            for fixture in fixtures
        }
        self._fixture_market_stats = {}
        if self._market_stats:
            league_ids = {fixture["league"]["id"] for fixture in fixtures}
            stats = await asyncio.gather(
                *(self._market_stats.get_league_stats(item) for item in league_ids)
            )
            by_league = {
                league_id: item.as_payload()
                for league_id, item in zip(league_ids, stats, strict=True)
            }
            self._fixture_market_stats = {
                fixture["fixture"]["id"]: by_league[fixture["league"]["id"]]
                for fixture in fixtures
            }
        return fixtures

    async def get_current_leagues(self) -> list[dict[str, Any]]:
        return [
            {
                "league": {"id": league["id"], "name": league["name"]},
                "seasons": [
                    {
                        "year": datetime.now().year,
                        "coverage": {
                            "predictions": False,
                            "injuries": False,
                            "standings": True,
                            "fixtures": {"statistics_fixtures": True},
                        },
                    }
                ],
            }
            for league in PUBLIC_FOOTBALL_LEAGUES.values()
        ]

    async def get_prediction(self, fixture_id: int) -> dict[str, Any] | None:
        fixture = self._fixtures.get(fixture_id)
        if not fixture:
            return None
        home = self._metrics.get(fixture["teams"]["home"]["id"])
        away = self._metrics.get(fixture["teams"]["away"]["id"])
        if not home or not away:
            return None

        draw = min(0.34, max(0.22, (home["draw_rate"] + away["draw_rate"]) / 2))
        difference = self._strength(home, 0.08) - self._strength(away, 0)
        home_share = 1 / (1 + math.exp(-difference))
        home_probability = (1 - draw) * home_share
        away_probability = (1 - draw) * (1 - home_share)
        expected_home = self._expected_goals(home, away, 0.12)
        expected_away = self._expected_goals(away, home, -0.05)
        sample_size = int(min(home["played"], away["played"]))
        market_stats = self._fixture_market_stats.get(fixture_id, {})
        market_warnings = []
        for label, key in (("Córners", "corners"), ("Tarjetas", "cards")):
            details = market_stats.get(key) or {}
            if details.get("average") is not None:
                sample = details.get("sample_games")
                market_warnings.append(
                    f"{label}: promedio de competición"
                    + (f" sobre {sample} partidos." if sample else ".")
                )
        return {
            "_provider": "TheSportsDB public schedule",
            "_warnings": [
                (
                    "Fuente publica Liga MX: modelo calculado con "
                    f"{sample_size} partidos recientes por equipo como minimo."
                ),
                (
                    "Córners y tarjetas usan promedios públicos de la competición; "
                    "no sustituyen estadísticas específicas del enfrentamiento."
                ),
                *market_warnings,
            ],
            "_market_stats": market_stats,
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
                "advice": (
                    "Modelo propio con resultados públicos recientes de Liga MX."
                ),
            },
            "comparison": {
                "form": self._comparison(home, away, "form_score"),
                "att": self._comparison(home, away, "goals_for_rate"),
                "def": self._comparison(home, away, "defense_score"),
            },
        }

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ApiSportsError(
                f"Error consultando la fuente publica de futbol: {exc}"
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ApiSportsError("Respuesta inesperada de la fuente publica de futbol.")
        return payload

    @staticmethod
    def _season_name(target: date, season_type: str) -> str:
        if season_type == "calendar_year":
            return str(target.year)
        start = target.year if target.month >= 7 else target.year - 1
        return f"{start}-{start + 1}"

    @classmethod
    def _event_local_date(
        cls,
        event: dict[str, Any],
        timezone: str,
    ) -> str | None:
        kickoff = cls._kickoff(event, timezone)
        return kickoff.date().isoformat() if kickoff else None

    @staticmethod
    def _is_completed(event: dict[str, Any]) -> bool:
        return (
            str(event.get("strStatus") or "").upper() in {"FT", "AET", "PEN"}
            and PublicWebFootballClient._score(event.get("intHomeScore")) is not None
            and PublicWebFootballClient._score(event.get("intAwayScore")) is not None
        )

    @staticmethod
    def _adapt_event(
        event: dict[str, Any],
        league: dict[str, Any],
        timezone: str,
    ) -> dict[str, Any]:
        status = str(event.get("strStatus") or "NS").upper()
        if status in {"NOT STARTED", "SCHEDULED", ""}:
            status = "NS"
        kickoff_value = PublicWebFootballClient._kickoff(event, timezone)
        kickoff = kickoff_value.isoformat() if kickoff_value else None
        if kickoff is None:
            kickoff = (
                f"{event.get('dateEventLocal') or event.get('dateEvent')}"
                f"T{event.get('strTimeLocal') or event.get('strTime') or '00:00:00'}"
                "-06:00"
            )
        return {
            "fixture": {
                "id": int(event["idEvent"]),
                "date": kickoff,
                "status": {"short": status},
                "source": "TheSportsDB public schedule",
                "source_url": (
                    "https://www.thesportsdb.com/api/v1/json/123/"
                    f"eventsseason.php?id={league['id']}"
                ),
            },
            "league": {
                "id": league["id"],
                "name": league["name"],
                "country": league["country"],
                "season": int(str(event.get("strSeason") or "0")[:4]),
            },
            "teams": {
                "home": {
                    "id": int(event["idHomeTeam"]),
                    "name": event["strHomeTeam"],
                },
                "away": {
                    "id": int(event["idAwayTeam"]),
                    "name": event["strAwayTeam"],
                },
            },
            "goals": {
                "home": PublicWebFootballClient._score(event.get("intHomeScore")),
                "away": PublicWebFootballClient._score(event.get("intAwayScore")),
            },
            "_requested_timezone": timezone,
        }

    @staticmethod
    def _kickoff(
        event: dict[str, Any],
        timezone: str,
    ) -> datetime | None:
        value = str(event.get("strTimestamp") or "").strip()
        if not value:
            return None
        parsed: datetime | None = None
        for candidate in (value.replace("Z", "+00:00"), value):
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        offsets = {
            "America/Mexico_City": timedelta(hours=-6),
            "UTC": timedelta(0),
        }
        offset = offsets.get(timezone)
        if offset is None:
            return parsed
        return parsed.astimezone(fixed_timezone(offset))

    @classmethod
    def _build_metrics(
        cls,
        events: list[dict[str, Any]],
    ) -> dict[int, dict[str, float]]:
        rows: dict[int, dict[str, float]] = defaultdict(
            lambda: {
                "played": 0,
                "wins": 0,
                "draws": 0,
                "goals_for": 0,
                "goals_against": 0,
                "form_points": 0,
            }
        )
        for event in events:
            home_id = int(event["idHomeTeam"])
            away_id = int(event["idAwayTeam"])
            home_goals = cls._score(event.get("intHomeScore"))
            away_goals = cls._score(event.get("intAwayScore"))
            if home_goals is None or away_goals is None:
                continue
            for team_id, scored, allowed in (
                (home_id, home_goals, away_goals),
                (away_id, away_goals, home_goals),
            ):
                row = rows[team_id]
                row["played"] += 1
                row["goals_for"] += scored
                row["goals_against"] += allowed
                if scored > allowed:
                    row["wins"] += 1
                    row["form_points"] += 3
                elif scored == allowed:
                    row["draws"] += 1
                    row["form_points"] += 1
        metrics: dict[int, dict[str, float]] = {}
        for team_id, row in rows.items():
            played = max(row["played"], 1)
            goals_against_rate = row["goals_against"] / played
            metrics[team_id] = {
                "played": row["played"],
                "win_rate": row["wins"] / played,
                "draw_rate": row["draws"] / played,
                "goals_for_rate": row["goals_for"] / played,
                "goals_against_rate": goals_against_rate,
                "goal_difference_rate": (
                    row["goals_for"] - row["goals_against"]
                ) / played,
                "form_score": row["form_points"] / (3 * played),
                "defense_score": 1 / (1 + goals_against_rate),
            }
        return metrics

    @staticmethod
    def _strength(metrics: dict[str, float], home_advantage: float) -> float:
        sample_factor = min(1.0, metrics["played"] / 5)
        return sample_factor * (
            1.5 * metrics["win_rate"]
            + 0.8 * metrics["form_score"]
            + 0.25 * metrics["goal_difference_rate"]
        ) + home_advantage

    @staticmethod
    def _expected_goals(
        team: dict[str, float],
        opponent: dict[str, float],
        adjustment: float,
    ) -> float:
        value = (team["goals_for_rate"] + opponent["goals_against_rate"]) / 2
        return min(5.0, max(0.2, value + adjustment))

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

    @staticmethod
    def _score(value: Any) -> int | None:
        try:
            return int(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            return None
