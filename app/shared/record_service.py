import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date
from collections.abc import Awaitable, Callable
from typing import Any

from app.shared.api_sports_client import ApiSportsClient
from app.shared.models import (
    BaseballMarketProjection,
    SportDailyPredictionResponse,
    SportGamePrediction,
    TwoWayProbabilitySet,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordModelConfig:
    sport: str
    version: str
    weights: dict[str, float]
    home_advantage_logit: float
    point_scale: float


NBA_CONFIG = RecordModelConfig(
    sport="nba",
    version="nba-record-v1",
    weights={
        "season_win_rate": 0.35,
        "scoring_margin": 0.30,
        "home_away_record": 0.20,
        "recent_form": 0.15,
    },
    home_advantage_logit=0.16,
    point_scale=12.0,
)

BASEBALL_CONFIG = RecordModelConfig(
    sport="baseball",
    version="baseball-public-web-v2",
    weights={
        "season_win_rate": 0.45,
        "run_differential": 0.30,
        "home_away_record": 0.15,
        "recent_form": 0.10,
    },
    home_advantage_logit=0.12,
    point_scale=1.8,
)

FINAL_STATUSES = {"FT", "AET", "AOT", "AP", "CANC", "ABD", "AW", "POST"}
StandingsFallback = Callable[
    [list[dict[str, Any]]],
    Awaitable[tuple[dict[int, dict[str, Any]], list[str]]],
]


class RecordBasedPredictionService:
    def __init__(
        self,
        client: ApiSportsClient,
        config: RecordModelConfig,
        standings_fallback: StandingsFallback | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.standings_fallback = standings_fallback

    async def predict_date(
        self,
        target_date: date,
        timezone: str,
        limit: int,
        league_names: set[str] | None = None,
    ) -> SportDailyPredictionResponse:
        provider_games = await self.client.get_games(target_date.isoformat(), timezone)
        logger.info(
            "prediction.games_received sport=%s date=%s count=%s league_filter=%s",
            self.config.sport,
            target_date,
            len(provider_games),
            sorted(league_names) if league_names else "all",
        )
        games = [
            game
            for game in provider_games
            if self._game_date(game) == target_date
            and self._status(game) not in FINAL_STATUSES
            and self._matches_league(game, league_names)
        ]

        competition_keys = {
            self._competition_key(game)
            for game in games
            if self._competition_key(game) is not None
        }
        keys = list(competition_keys)[:12]
        standings_results = await asyncio.gather(
            *(self.client.get_standings(league, season) for league, season in keys),
            return_exceptions=True,
        )
        standings_by_competition: dict[tuple[str | int, str | int], dict[int, dict]] = {}
        global_warnings: list[str] = []
        for key, result in zip(keys, standings_results, strict=True):
            if isinstance(result, Exception):
                global_warnings.append(
                    f"No se pudieron obtener standings para {key[0]} {key[1]}: {result}"
                )
                standings_by_competition[key] = {}
            else:
                standings_by_competition[key] = self._standings_index(result)

        if self.standings_fallback and any(
            not standings_by_competition.get(key) for key in keys
        ):
            fallback_rows, fallback_warnings = await self.standings_fallback(games)
            global_warnings.extend(fallback_warnings)
            if fallback_rows:
                for key in keys:
                    current = standings_by_competition.setdefault(key, {})
                    for team_id, row in fallback_rows.items():
                        current.setdefault(team_id, row)

        predictions = [
            self._predict_game(
                game,
                standings_by_competition.get(self._competition_key(game), {}),
            )
            for game in games
        ]
        predictions.sort(
            key=lambda item: (item.data_quality_score, item.confidence),
            reverse=True,
        )
        predictions = predictions[:limit]
        logger.info(
            "prediction.completed sport=%s date=%s eligible=%s competitions=%s "
            "returned=%s warnings=%s",
            self.config.sport,
            target_date,
            len(games),
            len(keys),
            len(predictions),
            len(global_warnings),
        )

        return SportDailyPredictionResponse(
            sport=self.config.sport,
            requested_date=target_date,
            timezone=timezone,
            games_found=len(games),
            games_returned=len(predictions),
            model_version=self.config.version,
            weights=self.config.weights,
            filters={
                "league": (
                    ",".join(sorted(league_names)) if league_names else "all"
                )
            },
            predictions=predictions,
            warnings=global_warnings,
        )

    def _predict_game(
        self,
        game: dict[str, Any],
        standings: dict[int, dict[str, Any]],
    ) -> SportGamePrediction:
        home = self._team(game, "home")
        away = self._team(game, "away")
        home_stats = standings.get(home["id"], {})
        away_stats = standings.get(away["id"], {})

        components: dict[str, float | None] = {
            "season_win_rate": self._difference(
                self._win_rate(home_stats),
                self._win_rate(away_stats),
            ),
            self._margin_component_name(): self._scaled_difference(
                self._margin_per_game(home_stats),
                self._margin_per_game(away_stats),
                self.config.point_scale,
            ),
            "home_away_record": self._difference(
                self._split_win_rate(home_stats, "home"),
                self._split_win_rate(away_stats, "away"),
            ),
            "recent_form": self._difference(
                self._recent_win_rate(home_stats),
                self._recent_win_rate(away_stats),
            ),
        }

        available_weight = sum(
            self.config.weights[name]
            for name, value in components.items()
            if value is not None
        )
        logit = self.config.home_advantage_logit
        if available_weight:
            for name, value in components.items():
                if value is not None:
                    logit += (self.config.weights[name] / available_weight) * value * 2.2
        home_probability = 1 / (1 + math.exp(-logit))
        away_probability = 1 - home_probability

        available = [name for name, value in components.items() if value is not None]
        completeness = available_weight
        confidence = min(
            92.0,
            25 + 50 * completeness + 17 * min(abs(home_probability - 0.5) / 0.25, 1),
        )
        quality = min(100.0, 20 + 80 * completeness)

        expected_home, expected_away = self._expected_score(home_stats, away_stats)
        markets = (
            self._baseball_markets(
                home["name"],
                away["name"],
                home_probability,
                expected_home,
                expected_away,
                quality,
                self._league_name(game, "unknown"),
            )
            if self.config.sport == "baseball"
            else self._basketball_markets(
                home["name"], away["name"], home_probability,
                expected_home, expected_away, quality,
            )
        )
        warnings: list[str] = []
        if completeness < 0.70:
            warnings.append("Standings incompletos; confianza reducida.")
        if self.config.sport == "baseball":
            warnings.append(
                "Este modelo v1 no incorpora abridores confirmados ni uso del bullpen."
            )

        league, season = self._competition_key(game) or ("unknown", "unknown")
        return SportGamePrediction(
            game_id=self._game_id(game),
            kickoff=self._game_datetime(game),
            league=self._league_name(game, league),
            season=str(season),
            home_team_id=home["id"],
            home_team=home["name"],
            away_team_id=away["id"],
            away_team=away["name"],
            data_quality_score=round(quality, 1),
            confidence=round(confidence, 1),
            probabilities=TwoWayProbabilitySet(
                home=round(home_probability * 100, 2),
                away=round(away_probability * 100, 2),
            ),
            predicted_result="home" if home_probability >= 0.5 else "away",
            expected_score_home=expected_home,
            expected_score_away=expected_away,
            markets=markets,
            available_components=available,
            warnings=warnings,
        )

    @staticmethod
    def _baseball_markets(
        home_team: str,
        away_team: str,
        home_probability: float,
        expected_home: float | None,
        expected_away: float | None,
        data_quality: float,
        league: str,
    ) -> BaseballMarketProjection:
        if expected_home is None or expected_away is None:
            return BaseballMarketProjection()

        favorite = home_team if home_probability >= 0.5 else away_team
        underdog = away_team if favorite == home_team else home_team
        expected_margin = abs(expected_home - expected_away)
        handicap_team = favorite if expected_margin >= 1.5 else underdog
        handicap_line = -1.5 if handicap_team == favorite else 1.5
        handicap_confidence = min(
            90.0,
            data_quality * 0.55 + abs(expected_margin - 1.5) * 10,
        )

        projected_total = round(expected_home + expected_away, 1)
        total_line = 9.5 if league.upper() == "KBO" else 8.5
        total_pick = "over" if projected_total > total_line else "under"
        total_confidence = min(
            90.0,
            data_quality * 0.55 + abs(projected_total - total_line) * 12,
        )
        return BaseballMarketProjection(
            handicap_team=handicap_team,
            handicap_line=handicap_line,
            handicap_confidence=round(handicap_confidence, 1),
            total_line=total_line,
            total_pick=total_pick,
            projected_total=projected_total,
            total_confidence=round(total_confidence, 1),
        )

    @staticmethod
    def _basketball_markets(
        home_team: str,
        away_team: str,
        home_probability: float,
        expected_home: float | None,
        expected_away: float | None,
        data_quality: float,
    ) -> BaseballMarketProjection:
        if expected_home is None or expected_away is None:
            return BaseballMarketProjection()
        favorite = home_team if home_probability >= 0.5 else away_team
        margin = abs(expected_home - expected_away)
        handicap_line = -(math.floor(margin) + 0.5)
        projected_total = round(expected_home + expected_away, 1)
        total_line = math.floor(projected_total) + 0.5
        return BaseballMarketProjection(
            handicap_team=favorite,
            handicap_line=handicap_line,
            handicap_confidence=round(min(90.0, data_quality * 0.6 + margin * 2), 1),
            total_line=total_line,
            total_pick="over" if projected_total >= total_line else "under",
            projected_total=projected_total,
            total_confidence=round(min(90.0, data_quality * 0.55 + 4), 1),
        )

    def _margin_component_name(self) -> str:
        return "run_differential" if self.config.sport == "baseball" else "scoring_margin"

    @staticmethod
    def _standings_index(raw: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                if RecordBasedPredictionService._team_id(value) is not None:
                    rows.append(value)
                else:
                    for child in value.values():
                        if isinstance(child, (list, dict)):
                            visit(child)

        visit(raw)
        return {
            team_id: row
            for row in rows
            if (team_id := RecordBasedPredictionService._team_id(row)) is not None
        }

    @staticmethod
    def _team_id(row: dict[str, Any]) -> int | None:
        team = row.get("team")
        if isinstance(team, dict) and isinstance(team.get("id"), int):
            return team["id"]
        return None

    @staticmethod
    def _win_rate(row: dict[str, Any]) -> float | None:
        wins = RecordBasedPredictionService._number(
            row, ("win", "total"), ("games", "win", "total"), ("games", "wins")
        )
        losses = RecordBasedPredictionService._number(
            row, ("loss", "total"), ("games", "lose", "total"), ("games", "losses")
        )
        played = RecordBasedPredictionService._number(row, ("games", "played"))
        total = played or ((wins or 0) + (losses or 0))
        return wins / total if wins is not None and total else None

    @staticmethod
    def _split_win_rate(row: dict[str, Any], side: str) -> float | None:
        wins = RecordBasedPredictionService._number(
            row, ("win", side), ("games", "win", side)
        )
        losses = RecordBasedPredictionService._number(
            row, ("loss", side), ("games", "lose", side)
        )
        total = (wins or 0) + (losses or 0)
        return wins / total if wins is not None and total else None

    @staticmethod
    def _recent_win_rate(row: dict[str, Any]) -> float | None:
        wins = RecordBasedPredictionService._number(row, ("win", "lastTen"))
        losses = RecordBasedPredictionService._number(row, ("loss", "lastTen"))
        if wins is not None and losses is not None and wins + losses:
            return wins / (wins + losses)
        form = row.get("form")
        if isinstance(form, str):
            results = [char for char in form.upper() if char in {"W", "L"}][-10:]
            return results.count("W") / len(results) if results else None
        return None

    @staticmethod
    def _margin_per_game(row: dict[str, Any]) -> float | None:
        played = RecordBasedPredictionService._number(row, ("games", "played"))
        points_for = RecordBasedPredictionService._number(
            row, ("points", "for"), ("scores", "for")
        )
        points_against = RecordBasedPredictionService._number(
            row, ("points", "against"), ("scores", "against")
        )
        if played and points_for is not None and points_against is not None:
            return (points_for - points_against) / played
        return None

    @staticmethod
    def _expected_score(
        home: dict[str, Any],
        away: dict[str, Any],
    ) -> tuple[float | None, float | None]:
        home_played = RecordBasedPredictionService._number(home, ("games", "played"))
        away_played = RecordBasedPredictionService._number(away, ("games", "played"))
        home_for = RecordBasedPredictionService._number(home, ("points", "for"), ("scores", "for"))
        home_against = RecordBasedPredictionService._number(
            home, ("points", "against"), ("scores", "against")
        )
        away_for = RecordBasedPredictionService._number(away, ("points", "for"), ("scores", "for"))
        away_against = RecordBasedPredictionService._number(
            away, ("points", "against"), ("scores", "against")
        )
        if not home_played or not away_played:
            return None, None
        if None in {home_for, home_against, away_for, away_against}:
            return None, None
        expected_home = ((home_for / home_played) + (away_against / away_played)) / 2
        expected_away = ((away_for / away_played) + (home_against / home_played)) / 2
        return round(expected_home, 1), round(expected_away, 1)

    @staticmethod
    def _difference(home: float | None, away: float | None) -> float | None:
        return home - away if home is not None and away is not None else None

    @staticmethod
    def _scaled_difference(
        home: float | None,
        away: float | None,
        scale: float,
    ) -> float | None:
        if home is None or away is None:
            return None
        return max(-1.0, min(1.0, (home - away) / scale))

    @staticmethod
    def _number(row: dict[str, Any], *paths: tuple[str, ...]) -> float | None:
        for path in paths:
            value: Any = row
            for part in path:
                if not isinstance(value, dict) or part not in value:
                    value = None
                    break
                value = value[part]
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _game_date(game: dict[str, Any]) -> date | None:
        value = RecordBasedPredictionService._date_value(game)
        try:
            return date.fromisoformat(value[:10]) if value else None
        except ValueError:
            return None

    @staticmethod
    def _date_value(game: dict[str, Any]) -> str | None:
        value = game.get("date")
        if isinstance(value, dict):
            return value.get("start")
        return value if isinstance(value, str) else None

    @staticmethod
    def _game_datetime(game: dict[str, Any]) -> str:
        return RecordBasedPredictionService._date_value(game) or "1970-01-01T00:00:00Z"

    @staticmethod
    def _game_id(game: dict[str, Any]) -> int:
        return int(game.get("id") or game.get("game", {}).get("id"))

    @staticmethod
    def _status(game: dict[str, Any]) -> str | None:
        status = game.get("status", {})
        return status.get("short") if isinstance(status, dict) else str(status)

    @staticmethod
    def _team(game: dict[str, Any], side: str) -> dict[str, Any]:
        teams = game.get("teams", {})
        aliases = ("home",) if side == "home" else ("away", "visitors")
        for alias in aliases:
            team = teams.get(alias)
            if isinstance(team, dict) and team.get("id") is not None:
                return {"id": int(team["id"]), "name": team.get("name", str(team["id"]))}
        raise ValueError(f"Equipo {side} ausente en la respuesta.")

    @staticmethod
    def _competition_key(game: dict[str, Any]) -> tuple[str | int, str | int] | None:
        league = game.get("league", {})
        league_id = league.get("id") or league.get("name")
        season = game.get("season") or league.get("season")
        if league_id is None or season is None:
            return None
        return league_id, season

    @staticmethod
    def _league_name(game: dict[str, Any], fallback: str | int) -> str:
        league = game.get("league", {})
        return str(league.get("name") or fallback)

    @staticmethod
    def _matches_league(
        game: dict[str, Any],
        league_names: set[str] | None,
    ) -> bool:
        if not league_names:
            return True
        league = game.get("league", {})
        name = str(league.get("name", "")).strip().casefold()
        return name in {candidate.casefold() for candidate in league_names}
