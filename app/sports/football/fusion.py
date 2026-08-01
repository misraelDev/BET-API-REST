from dataclasses import dataclass
from typing import Any

SOURCE_RELIABILITY = {
    "API-Football": 1.0,
    "football-data.org": 0.88,
    "TheSportsDB public schedule": 0.72,
}


@dataclass(frozen=True)
class FusedFootballSignals:
    probabilities: tuple[float, float, float] | None
    expected_home: float | None
    expected_away: float | None
    market_stats: dict[str, Any]
    providers: list[str]
    agreement: float


class FootballDataFusion:
    """Normalizes provider payloads and builds a reliability-weighted consensus."""

    @classmethod
    def fuse(cls, payloads: list[dict[str, Any]]) -> FusedFootballSignals:
        normalized = [
            item
            for payload in payloads
            if (item := cls._normalize(payload)) is not None
        ]
        providers = list(dict.fromkeys(item["provider"] for item in normalized))
        probabilities = cls._weighted_vector(normalized, "probabilities")
        expected_home = cls._weighted_scalar(normalized, "expected_home")
        expected_away = cls._weighted_scalar(normalized, "expected_away")
        market_stats = {
            market: cls._weighted_market(normalized, market)
            for market in ("corners", "cards")
        }
        market_stats = {
            key: value for key, value in market_stats.items() if value
        }
        return FusedFootballSignals(
            probabilities=probabilities,
            expected_home=expected_home,
            expected_away=expected_away,
            market_stats=market_stats,
            providers=providers,
            agreement=cls._agreement(normalized, probabilities),
        )

    @classmethod
    def _normalize(cls, payload: dict[str, Any]) -> dict[str, Any] | None:
        provider = str(payload.get("_provider") or "unknown")
        prediction = payload.get("predictions") or {}
        probabilities = cls._probabilities(prediction.get("percent") or {})
        goals = prediction.get("goals") or {}
        expected_home = cls._positive_float(goals.get("home"))
        expected_away = cls._positive_float(goals.get("away"))
        market_stats = payload.get("_market_stats") or {}
        if probabilities is None and expected_home is None and not market_stats:
            return None
        completeness = sum(
            (
                probabilities is not None,
                expected_home is not None and expected_away is not None,
                bool(market_stats.get("corners")),
                bool(market_stats.get("cards")),
            )
        ) / 4
        return {
            "provider": provider,
            "weight": cls._reliability(provider) * (0.7 + 0.3 * completeness),
            "probabilities": probabilities,
            "expected_home": expected_home,
            "expected_away": expected_away,
            "market_stats": market_stats,
        }

    @staticmethod
    def _reliability(provider: str) -> float:
        for name, weight in SOURCE_RELIABILITY.items():
            if name.casefold() in provider.casefold():
                return weight
        return 0.65

    @classmethod
    def _weighted_vector(
        cls,
        rows: list[dict[str, Any]],
        field: str,
    ) -> tuple[float, float, float] | None:
        available = [row for row in rows if row.get(field) is not None]
        total_weight = sum(row["weight"] for row in available)
        if total_weight <= 0:
            return None
        return tuple(
            sum(row[field][index] * row["weight"] for row in available)
            / total_weight
            for index in range(3)
        )

    @classmethod
    def _weighted_scalar(
        cls,
        rows: list[dict[str, Any]],
        field: str,
    ) -> float | None:
        available = [row for row in rows if row.get(field) is not None]
        total_weight = sum(row["weight"] for row in available)
        if total_weight <= 0:
            return None
        return (
            sum(row[field] * row["weight"] for row in available)
            / total_weight
        )

    @staticmethod
    def _weighted_market(
        rows: list[dict[str, Any]],
        market: str,
    ) -> dict[str, Any] | None:
        values = []
        for row in rows:
            details = row["market_stats"].get(market) or {}
            average = FootballDataFusion._positive_float(details.get("average"))
            if average is not None:
                values.append((row, details, average))
        total_weight = sum(row["weight"] for row, _, _ in values)
        if total_weight <= 0:
            return None
        average = sum(
            value * row["weight"] for row, _, value in values
        ) / total_weight
        samples = [
            int(details["sample_games"])
            for _, details, _ in values
            if details.get("sample_games")
        ]
        return {
            "average": round(average, 3),
            "sample_games": sum(samples) if samples else None,
            "sources": [
                {
                    "provider": row["provider"],
                    "source_url": details.get("source_url"),
                    "average": value,
                }
                for row, details, value in values
            ],
        }

    @staticmethod
    def _agreement(
        rows: list[dict[str, Any]],
        consensus: tuple[float, float, float] | None,
    ) -> float:
        vectors = [row["probabilities"] for row in rows if row["probabilities"]]
        if consensus is None or not vectors:
            return 0.0
        if len(vectors) == 1:
            return 50.0
        distances = [
            sum(abs(value - consensus[index]) for index, value in enumerate(vector))
            / 2
            for vector in vectors
        ]
        return round(max(0.0, 1 - sum(distances) / len(distances)) * 100, 1)

    @classmethod
    def _probabilities(
        cls,
        values: dict[str, Any],
    ) -> tuple[float, float, float] | None:
        parsed = [
            cls._percent(values.get(key))
            for key in ("home", "draw", "away")
        ]
        if any(value is None for value in parsed):
            return None
        total = sum(parsed)  # type: ignore[arg-type]
        if total <= 0:
            return None
        return tuple(value / total for value in parsed)  # type: ignore[misc]

    @staticmethod
    def _percent(value: Any) -> float | None:
        try:
            parsed = float(str(value).strip().rstrip("%"))
        except (TypeError, ValueError):
            return None
        return parsed / 100 if parsed > 1 else parsed

    @staticmethod
    def _positive_float(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
