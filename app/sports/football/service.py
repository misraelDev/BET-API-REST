import asyncio
import math
from datetime import date
from typing import Any

from app.shared.models import (
    DailyPredictionResponse,
    FixturePrediction,
    FootballFusionSummary,
    FootballMarketProjection,
    FootballMarkets,
    ProbabilitySet,
    WeightContribution,
)
from app.shared.exceptions import ApiSportsRateLimitError
from app.sports.football.client import ApiFootballClient
from app.sports.football.fusion import FootballDataFusion

MODEL_VERSION = "football-fusion-v2"

MODEL_WEIGHTS = {
    "api_base": 0.35,
    "form": 0.20,
    "attack": 0.15,
    "defense": 0.15,
    "poisson": 0.10,
    "h2h": 0.05,
}

# Competitions with stronger and more stable public data receive a modest prior.
# Coverage flags remain the dominant factor in fixture selection.
COMPETITION_PRIORITIES = {
    2: 100,   # UEFA Champions League
    3: 95,    # UEFA Europa League
    39: 100,  # Premier League
    61: 95,   # Ligue 1
    78: 95,   # Bundesliga
    88: 92,   # Eredivisie
    94: 90,   # Primeira Liga
    135: 98,  # Serie A
    140: 100, # La Liga
    262: 88,  # Liga MX
    253: 90,  # MLS
}

FINISHED_STATUSES = {"FT", "AET", "PEN", "CANC", "ABD", "AWD", "WO"}
PREDICTION_BATCH_SIZE = 4
PREDICTION_BATCH_DELAY_SECONDS = 30.0


class FootballPredictionService:
    def __init__(self, client: ApiFootballClient) -> None:
        self.client = client

    async def predict_date(
        self,
        target_date: date,
        timezone: str,
        limit: int,
        league: str = "all",
    ) -> DailyPredictionResponse:
        fixtures, leagues = await asyncio.gather(
            self.client.get_fixtures(target_date.isoformat(), timezone),
            self.client.get_current_leagues(),
        )
        coverage = self._coverage_index(leagues)

        exact_date_fixtures = [
            fixture
            for fixture in fixtures
            if self._fixture_local_date(fixture) == target_date
            and self._matches_league(fixture, league)
        ]
        eligible = [
            fixture
            for fixture in exact_date_fixtures
            if fixture.get("fixture", {}).get("status", {}).get("short")
            not in FINISHED_STATUSES
            and fixture.get("teams", {}).get("home", {}).get("id")
            and fixture.get("teams", {}).get("away", {}).get("id")
        ]

        ranked = sorted(
            eligible,
            key=lambda fixture: self._selection_score(fixture, coverage),
            reverse=True,
        )
        predictions: list[FixturePrediction] = []
        warnings: list[str] = []
        max_attempts = min(len(ranked), limit * 3)
        candidates = ranked[:max_attempts]
        cursor = 0
        failed_attempts = 0
        rate_limit_reached = False
        while len(predictions) < limit and cursor < len(candidates):
            missing = limit - len(predictions)
            batch_size = min(PREDICTION_BATCH_SIZE, missing)
            batch = candidates[cursor : cursor + batch_size]
            cursor += len(batch)
            prediction_payloads = await asyncio.gather(
                *(
                    self.client.get_prediction(item["fixture"]["id"])
                    for item in batch
                ),
                return_exceptions=True,
            )
            for fixture, payload in zip(batch, prediction_payloads, strict=True):
                if isinstance(payload, ApiSportsRateLimitError):
                    if not rate_limit_reached:
                        warnings.append(
                            "API-Football alcanzo su limite temporal. "
                            "La generacion se detuvo para evitar mas solicitudes."
                        )
                    rate_limit_reached = True
                    continue
                if isinstance(payload, Exception):
                    failed_attempts += 1
                    warnings.append(
                        f"Fixture {fixture['fixture']['id']}: no se pudo consultar "
                        f"la prediccion ({payload})."
                    )
                    continue
                predictions.append(
                    self._build_prediction(
                        fixture,
                        payload,
                        coverage,
                        timezone,
                    )
                )
            if rate_limit_reached:
                break
            if len(predictions) < limit and cursor < len(candidates):
                await asyncio.sleep(PREDICTION_BATCH_DELAY_SECONDS)
        if failed_attempts:
            warnings.insert(
                0,
                f"Fallback aplicado: {cursor} candidatos revisados, "
                f"{failed_attempts} fallidos y {len(predictions)} predicciones generadas.",
            )

        predictions.sort(
            key=lambda item: (item.confidence, item.data_quality_score),
            reverse=True,
        )
        return DailyPredictionResponse(
            requested_date=target_date,
            timezone=timezone,
            fixtures_found=len(exact_date_fixtures),
            fixtures_eligible=len(eligible),
            fixtures_returned=len(predictions),
            model_version=MODEL_VERSION,
            weights=MODEL_WEIGHTS,
            predictions=predictions,
            warnings=warnings,
        )

    @staticmethod
    def _fixture_local_date(fixture: dict[str, Any]) -> date | None:
        value = fixture.get("fixture", {}).get("date")
        if not value:
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None

    @staticmethod
    def _coverage_index(
        leagues: list[dict[str, Any]],
    ) -> dict[tuple[int, int], dict[str, Any]]:
        index: dict[tuple[int, int], dict[str, Any]] = {}
        for item in leagues:
            league_id = item.get("league", {}).get("id")
            for season in item.get("seasons", []):
                if league_id and season.get("year") is not None:
                    index[(league_id, season["year"])] = season.get("coverage", {})
        return index

    def _selection_score(
        self,
        fixture: dict[str, Any],
        coverage: dict[tuple[int, int], dict[str, Any]],
    ) -> float:
        league = fixture.get("league", {})
        flags = coverage.get((league.get("id"), league.get("season")), {})
        fixture_flags = flags.get("fixtures", {})
        coverage_score = (
            30 * bool(flags.get("predictions"))
            + 20 * bool(flags.get("injuries"))
            + 15 * bool(flags.get("standings"))
            + 15 * bool(fixture_flags.get("statistics_fixtures"))
            + 10 * bool(fixture_flags.get("statistics_players"))
            + 10 * bool(fixture_flags.get("lineups"))
        )
        priority = COMPETITION_PRIORITIES.get(league.get("id"), 60)
        return 0.8 * coverage_score + 0.2 * priority

    def _build_prediction(
        self,
        fixture: dict[str, Any],
        payload: dict[str, Any] | None,
        coverage: dict[tuple[int, int], dict[str, Any]],
        timezone: str,
    ) -> FixturePrediction:
        payload = payload or {}
        source_payloads = payload.get("_source_payloads") or [payload]
        fused = FootballDataFusion.fuse(source_payloads)
        raw_prediction = payload.get("predictions", {})
        comparison = payload.get("comparison", {})

        base = (
            fused.probabilities
            or self._three_way_percent(raw_prediction.get("percent", {}))
        )
        draw_anchor = base[1] if base else 0.27

        components = {
            "api_base": base,
            "form": self._comparison_vector(comparison.get("form"), draw_anchor),
            "attack": self._comparison_vector(comparison.get("att"), draw_anchor),
            "defense": self._comparison_vector(comparison.get("def"), draw_anchor),
            "poisson": self._comparison_vector(
                comparison.get("poisson"), draw_anchor
            ),
            "h2h": self._comparison_vector(comparison.get("h2h"), draw_anchor),
        }
        probabilities, contributions = self._weighted_probabilities(components)

        league = fixture["league"]
        league_name = self._canonical_league_name(league)
        data_quality = self._selection_score(fixture, coverage)
        completeness = sum(
            MODEL_WEIGHTS[name]
            for name, value in components.items()
            if value is not None
        )
        confidence = self._confidence(
            probabilities,
            [value for value in components.values() if value],
            completeness,
            data_quality,
        )
        if len(fused.providers) > 1:
            confidence *= 0.85 + 0.15 * fused.agreement / 100
        elif len(fused.providers) == 1:
            confidence *= 0.9

        warnings: list[str] = []
        for source_payload in source_payloads:
            warnings.extend(
                str(item)
                for item in source_payload.get("_warnings", [])
                if item and str(item) not in warnings
            )
        if len(fused.providers) < 2:
            warnings.append(
                "Consenso limitado: solo una fuente independiente aportó señales."
            )
        if payload == {}:
            warnings.append("API-Football no devolvio una prediccion para el partido.")
        if completeness < 0.70:
            warnings.append("La prediccion tiene componentes estadisticos faltantes.")
        if fixture["fixture"]["status"]["short"] == "TBD":
            warnings.append("La hora o fecha del partido figura como no confirmada.")

        expected = raw_prediction.get("goals", {})
        expected_home = (
            fused.expected_home
            if fused.expected_home is not None
            else self._expected_goal_value(expected.get("home"))
        )
        expected_away = (
            fused.expected_away
            if fused.expected_away is not None
            else self._expected_goal_value(expected.get("away"))
        )
        return FixturePrediction(
            fixture_id=fixture["fixture"]["id"],
            kickoff=fixture["fixture"]["date"],
            timezone=timezone,
            league_id=league["id"],
            league=league_name,
            country=league.get("country"),
            home_team_id=fixture["teams"]["home"]["id"],
            home_team=fixture["teams"]["home"]["name"],
            away_team_id=fixture["teams"]["away"]["id"],
            away_team=fixture["teams"]["away"]["name"],
            data_quality_score=round(data_quality, 1),
            confidence=round(confidence, 1),
            probabilities=ProbabilitySet(
                home=round(probabilities[0] * 100, 2),
                draw=round(probabilities[1] * 100, 2),
                away=round(probabilities[2] * 100, 2),
            ),
            predicted_result=self._predicted_result(probabilities),
            expected_goals_home=expected_home,
            expected_goals_away=expected_away,
            advice=raw_prediction.get("advice"),
            markets=self._build_markets(
                fixture["teams"]["home"]["name"],
                fixture["teams"]["away"]["name"],
                probabilities,
                expected_home,
                expected_away,
                fused.market_stats or payload.get("_market_stats"),
            ),
            fusion=FootballFusionSummary(
                source_count=len(fused.providers),
                providers=fused.providers,
                agreement=fused.agreement,
            ),
            weights=contributions,
            warnings=warnings,
        )

    @staticmethod
    def _matches_league(fixture: dict[str, Any], league: str) -> bool:
        if league == "all":
            return True
        details = fixture.get("league", {})
        league_id = details.get("id")
        name = str(details.get("name") or "").casefold()
        country = str(details.get("country") or "").casefold()
        if league == "liga_mx":
            return league_id in {262, 4350} or "liga mx" in name
        if league == "brasileirao":
            return (
                league_id in {71, 4351}
                or "brasileir" in name
                or (
                    country == "brazil"
                    and name in {"serie a", "brazilian serie a"}
                )
            )
        if league == "leagues_cup":
            return league_id == 9003 or "leagues cup" in name
        return False

    @staticmethod
    def _canonical_league_name(league: dict[str, Any]) -> str:
        fixture = {"league": league}
        if FootballPredictionService._matches_league(fixture, "liga_mx"):
            return "Liga MX"
        if FootballPredictionService._matches_league(fixture, "brasileirao"):
            return "Brasileirão Betano"
        if FootballPredictionService._matches_league(fixture, "leagues_cup"):
            return "Leagues Cup"
        return str(league.get("name") or "Unknown")

    @staticmethod
    def _build_markets(
        home_team: str,
        away_team: str,
        probabilities: tuple[float, float, float],
        expected_home: float | None,
        expected_away: float | None,
        market_stats: dict[str, Any] | None = None,
    ) -> FootballMarkets:
        home, draw, away = probabilities
        double_chances = {
            f"{home_team} o empate": home + draw,
            f"Empate o {away_team}": draw + away,
            f"{home_team} o {away_team}": home + away,
        }
        double_pick, double_probability = max(
            double_chances.items(),
            key=lambda item: item[1],
        )
        if home + draw >= away + draw:
            handicap_team = home_team
            handicap_probability = home + draw
        else:
            handicap_team = away_team
            handicap_probability = away + draw

        goals = FootballMarketProjection(
            available=False,
            reason="Goles esperados no disponibles.",
        )
        if expected_home is not None and expected_away is not None:
            projected_total = expected_home + expected_away
            under_probability = math.exp(-projected_total) * (
                1 + projected_total + projected_total**2 / 2
            )
            over_probability = 1 - under_probability
            goals = FootballMarketProjection(
                selection="Más" if over_probability >= under_probability else "Menos",
                line=2.5,
                probability=round(
                    max(over_probability, under_probability) * 100,
                    1,
                ),
                projected_total=round(projected_total, 2),
                available=True,
            )
        corners = FootballPredictionService._total_market(
            (market_stats or {}).get("corners"),
            "No hay promedio público de córners para esta competición.",
        )
        cards = FootballPredictionService._total_market(
            (market_stats or {}).get("cards"),
            "No hay promedio público de tarjetas para esta competición.",
        )
        return FootballMarkets(
            handicap=FootballMarketProjection(
                selection=handicap_team,
                line=0.5,
                probability=round(handicap_probability * 100, 1),
                available=True,
            ),
            double_chance=FootballMarketProjection(
                selection=double_pick,
                probability=round(double_probability * 100, 1),
                available=True,
            ),
            goals=goals,
            corners=corners,
            cards=cards,
        )

    @staticmethod
    def _total_market(
        stats: dict[str, Any] | None,
        missing_reason: str,
    ) -> FootballMarketProjection:
        if not stats:
            return FootballMarketProjection(available=False, reason=missing_reason)
        try:
            projected_total = float(stats.get("average"))
        except (TypeError, ValueError):
            return FootballMarketProjection(available=False, reason=missing_reason)
        if projected_total <= 0:
            return FootballMarketProjection(available=False, reason=missing_reason)

        line = math.floor(projected_total) + 0.5
        threshold = math.floor(line)
        under_probability = sum(
            math.exp(-projected_total) * projected_total**value / math.factorial(value)
            for value in range(threshold + 1)
        )
        over_probability = 1 - under_probability
        return FootballMarketProjection(
            selection="Más" if over_probability >= under_probability else "Menos",
            line=line,
            probability=round(max(over_probability, under_probability) * 100, 1),
            projected_total=round(projected_total, 2),
            available=True,
        )

    @staticmethod
    def _three_way_percent(values: dict[str, Any]) -> tuple[float, float, float] | None:
        parsed = [
            FootballPredictionService._percent(values.get("home")),
            FootballPredictionService._percent(values.get("draw")),
            FootballPredictionService._percent(values.get("away")),
        ]
        if any(value is None for value in parsed):
            return None
        total = sum(parsed)  # type: ignore[arg-type]
        if total <= 0:
            return None
        return tuple(value / total for value in parsed)  # type: ignore[misc]

    @staticmethod
    def _comparison_vector(
        values: dict[str, Any] | None,
        draw_anchor: float,
    ) -> tuple[float, float, float] | None:
        if not values:
            return None
        home = FootballPredictionService._percent(values.get("home"))
        away = FootballPredictionService._percent(values.get("away"))
        if home is None or away is None or home + away <= 0:
            return None
        draw = min(max(draw_anchor, 0.15), 0.35)
        non_draw = 1 - draw
        return (
            non_draw * home / (home + away),
            draw,
            non_draw * away / (home + away),
        )

    @staticmethod
    def _weighted_probabilities(
        components: dict[str, tuple[float, float, float] | None],
    ) -> tuple[tuple[float, float, float], list[WeightContribution]]:
        available_weight = sum(
            MODEL_WEIGHTS[name]
            for name, value in components.items()
            if value is not None
        )
        if available_weight == 0:
            fallback = (0.365, 0.27, 0.365)
            return fallback, [
                WeightContribution(
                    component=name,
                    configured_weight=weight,
                    effective_weight=0,
                    available=False,
                )
                for name, weight in MODEL_WEIGHTS.items()
            ]

        result = [0.0, 0.0, 0.0]
        contributions: list[WeightContribution] = []
        for name, configured_weight in MODEL_WEIGHTS.items():
            value = components[name]
            effective_weight = (
                configured_weight / available_weight if value is not None else 0
            )
            if value is not None:
                for index in range(3):
                    result[index] += effective_weight * value[index]
            contributions.append(
                WeightContribution(
                    component=name,
                    configured_weight=configured_weight,
                    effective_weight=round(effective_weight, 4),
                    available=value is not None,
                    probabilities=(
                        ProbabilitySet(
                            home=round(value[0] * 100, 2),
                            draw=round(value[1] * 100, 2),
                            away=round(value[2] * 100, 2),
                        )
                        if value is not None
                        else None
                    ),
                )
            )
        return (result[0], result[1], result[2]), contributions

    @staticmethod
    def _confidence(
        final: tuple[float, float, float],
        components: list[tuple[float, float, float]],
        completeness: float,
        data_quality: float,
    ) -> float:
        if not components:
            return 10.0

        disagreement = sum(
            sum(abs(component[index] - final[index]) for index in range(3)) / 2
            for component in components
        ) / len(components)
        agreement = max(0.0, 1.0 - disagreement / 0.35)
        decisiveness = min(1.0, max(final) / 0.70)
        score = (
            45 * completeness
            + 25 * agreement
            + 20 * (data_quality / 100)
            + 10 * decisiveness
        )
        return min(95.0, max(10.0, score))

    @staticmethod
    def _predicted_result(probabilities: tuple[float, float, float]) -> str:
        labels = ("home", "draw", "away")
        return labels[max(range(3), key=lambda index: probabilities[index])]

    @staticmethod
    def _percent(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).replace("%", "").strip()) / 100
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _expected_goal_value(value: Any) -> float | None:
        parsed = FootballPredictionService._to_float(value)
        if parsed is None or parsed < 0 or parsed > 10:
            return None
        return parsed
