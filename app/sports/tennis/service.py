from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone as fixed_timezone
from math import floor

from app.sports.tennis.client import PublicTennisClient
from app.sports.tennis.models import (
    TennisDailyPredictionResponse,
    TennisMarketProjection,
    TennisMarkets,
    TennisMatchPrediction,
    TennisProbabilities,
    TennisTour,
)


@dataclass
class PlayerProfile:
    rating: float = 1500.0
    matches: list[dict] = field(default_factory=list)


class TennisPredictionService:
    HISTORY_DAYS = 60
    MIN_MATCHES = 3
    MARKET_MIN_MATCHES = 5

    def __init__(self, client: PublicTennisClient) -> None:
        self.client = client

    async def count_matches(
        self, target_date: date, timezone: str, tour: TennisTour
    ) -> int:
        self._timezone(timezone)
        rows = await self.client.scoreboard(tour, target_date.isoformat())
        return sum(
            1
            for row in rows
            if self._is_target(row, target_date, timezone) and self._has_players(row)
        )

    async def predict_date(
        self, target_date: date, timezone: str, limit: int, tour: TennisTour,
        page: int = 1,
    ) -> TennisDailyPredictionResponse:
        self._timezone(timezone)
        start_date = target_date - timedelta(days=self.HISTORY_DAYS)
        rows = await self.client.scoreboard(
            tour, target_date.isoformat(), start_date.isoformat()
        )
        profiles, h2h = self._build_profiles(rows, target_date, timezone)
        pending = sorted([
            row for row in rows
            if self._is_target(row, target_date, timezone) and self._has_players(row)
        ], key=lambda row: (self._kickoff(row["match"]), int(row["match"]["id"])))
        start = (page - 1) * limit
        selected = pending[start:start + limit]
        predictions = [self._predict(row, profiles, h2h) for row in selected]
        warnings = []
        if not predictions:
            warnings.append("No se encontraron partidos individuales programados para la fecha.")
        return TennisDailyPredictionResponse(
            requested_date=target_date,
            timezone=timezone,
            matches_found=len(pending),
            matches_returned=len(predictions),
            page=page,
            page_size=limit,
            total_pages=(len(pending) + limit - 1) // limit if pending else 0,
            model_version="tennis-elo-form-v2",
            filters={"tour": tour.value},
            predictions=predictions,
            warnings=warnings,
        )

    async def final_results(self, target_date: date, timezone: str, tour: TennisTour) -> list[dict]:
        rows = await self.client.scoreboard(tour, target_date.isoformat())
        finals = []
        for row in rows:
            match = row["match"]
            status = (match.get("status") or {}).get("type") or {}
            kickoff = self._kickoff(match).astimezone(self._timezone(timezone))
            if kickoff.date() != target_date or not status.get("completed"):
                continue
            if status.get("name") == "STATUS_WALKOVER" or not self._has_players(row):
                continue
            finals.append(match)
        return finals

    @staticmethod
    def _name(competitor: dict) -> str:
        return (competitor.get("athlete") or competitor.get("roster") or {}).get(
            "displayName", "Jugador desconocido"
        )

    @classmethod
    def _build_profiles(
        cls, rows: list[dict], target_date: date, timezone: str
    ) -> tuple[dict[str, PlayerProfile], dict[tuple[str, str], list[str]]]:
        profiles: dict[str, PlayerProfile] = defaultdict(PlayerProfile)
        h2h: dict[tuple[str, str], list[str]] = defaultdict(list)
        completed = []
        for row in rows:
            match = row["match"]
            status = (match.get("status") or {}).get("type") or {}
            if not status.get("completed") or status.get("name") == "STATUS_WALKOVER":
                continue
            kickoff = cls._kickoff(match)
            if kickoff.astimezone(cls._timezone(timezone)).date() >= target_date:
                continue
            if len(match.get("competitors") or []) == 2:
                completed.append(match)

        for match in sorted(completed, key=cls._kickoff):
            competitors = match["competitors"]
            first, second = competitors
            first_id, second_id = str(first.get("id")), str(second.get("id"))
            first_profile, second_profile = profiles[first_id], profiles[second_id]
            expected_first = 1 / (1 + 10 ** ((second_profile.rating - first_profile.rating) / 400))
            first_won = bool(first.get("winner"))
            score = 1.0 if first_won else 0.0
            change = 24 * (score - expected_first)
            first_profile.rating += change
            second_profile.rating -= change
            cls._append_match(first_profile, first, second, match, first_won)
            cls._append_match(second_profile, second, first, match, not first_won)
            key = tuple(sorted((first_id, second_id)))
            h2h[key].append(first_id if first_won else second_id)
        return profiles, h2h

    @classmethod
    def _append_match(
        cls, profile: PlayerProfile, player: dict, opponent: dict, match: dict, won: bool
    ) -> None:
        player_sets = player.get("linescores") or []
        opponent_sets = opponent.get("linescores") or []
        set_pairs = list(zip(player_sets, opponent_sets))
        sets_won = sum(int(bool(item.get("winner"))) for item in player_sets)
        games_won = sum(float(item.get("value") or 0) for item, _ in set_pairs)
        games_lost = sum(float(item.get("value") or 0) for _, item in set_pairs)
        profile.matches.append({
            "won": won,
            "sets_won": sets_won,
            "sets_lost": max(0, len(set_pairs) - sets_won),
            "games_won": games_won,
            "games_lost": games_lost,
            "date": cls._kickoff(match),
        })
        profile.matches = profile.matches[-10:]

    @classmethod
    def _predict(
        cls,
        row: dict,
        profiles: dict[str, PlayerProfile],
        h2h: dict[tuple[str, str], list[str]],
    ) -> TennisMatchPrediction:
        match = row["match"]
        competitors = sorted(match["competitors"], key=lambda item: item.get("order", 99))
        one, two = competitors
        one_id, two_id = str(one.get("id")), str(two.get("id"))
        one_profile = profiles.get(one_id, PlayerProfile())
        two_profile = profiles.get(two_id, PlayerProfile())
        one_count, two_count = len(one_profile.matches), len(two_profile.matches)
        components: list[tuple[str, float, float]] = []

        elo_probability = 1 / (1 + 10 ** ((two_profile.rating - one_profile.rating) / 400))
        components.append(("elo", 0.30, elo_probability))
        if one_count and two_count:
            components.extend([
                ("recent_form", 0.30, cls._ratio(cls._wins(one_profile), one_count, cls._wins(two_profile), two_count)),
                ("sets", 0.15, cls._metric_ratio(one_profile, two_profile, "sets_won", "sets_lost")),
                ("games", 0.15, cls._metric_ratio(one_profile, two_profile, "games_won", "games_lost")),
            ])
        meetings = h2h.get(tuple(sorted((one_id, two_id))), [])[-5:]
        if meetings:
            components.append(("head_to_head", 0.10, (meetings.count(one_id) + 1) / (len(meetings) + 2)))

        total_weight = sum(weight for _, weight, _ in components)
        p_one = sum(weight * value for _, weight, value in components) / total_weight
        probability_one = round(100 * p_one, 2)
        probability_two = round(100 - probability_one, 2)
        favorite_is_one = probability_one >= probability_two
        favorite = cls._name(one if favorite_is_one else two)
        favorite_probability = max(probability_one, probability_two)
        enough = one_count >= cls.MIN_MATCHES and two_count >= cls.MIN_MATCHES
        decisive = abs(probability_one - probability_two) >= 3
        winner_available = enough and decisive
        sample_quality = min(1.0, min(one_count, two_count) / 10)
        component_quality = min(1.0, len(components) / 5)
        quality = round(100 * (0.65 * sample_quality + 0.35 * component_quality), 1)
        confidence = round(50 + (favorite_probability - 50) * quality / 100, 2)
        reason = cls._unavailable_reason(one_count, two_count, decisive)
        winner = TennisMarketProjection(
            selection=favorite if winner_available else None,
            probability=favorite_probability if winner_available else None,
            available=winner_available,
            reason=None if winner_available else reason,
        )
        markets = cls._markets(
            favorite, favorite_probability, one_profile, two_profile,
            min(one_count, two_count), winner_available,
        )
        markets.winner = winner
        return TennisMatchPrediction(
            match_id=int(match["id"]), kickoff=cls._kickoff(match),
            league=row["tour"], tour=row["tour"], tournament=row["tournament"],
            season=row["season"], round=(match.get("round") or {}).get("displayName"),
            player_one_id=one_id, player_one=cls._name(one),
            player_two_id=two_id, player_two=cls._name(two),
            data_quality_score=quality, confidence=confidence,
            probabilities=TennisProbabilities(player_one=probability_one, player_two=probability_two),
            predicted_winner=favorite if winner_available else "insufficient_data",
            markets=markets, available_components=[name for name, _, _ in components],
            warnings=[] if winner_available else [reason],
        )

    @classmethod
    def _markets(
        cls, favorite: str, favorite_probability: float,
        one: PlayerProfile, two: PlayerProfile, minimum: int, winner_available: bool,
    ) -> TennisMarkets:
        unavailable = "Requiere al menos cinco partidos previos por jugador con parciales completos."
        detailed = winner_available and minimum >= cls.MARKET_MIN_MATCHES
        totals = [m["games_won"] + m["games_lost"] for m in one.matches + two.matches]
        projected_total = round(sum(totals) / len(totals), 1) if totals else None
        line = floor(projected_total) + 0.5 if projected_total is not None else None
        total_probability = min(72.0, 52.0 + abs((projected_total or 0) - (line or 0)) * 8)
        straight_probability = round(max(0.0, min(100.0, favorite_probability * 0.72)), 1)
        cover_probability = round(min(92.0, favorite_probability + (100 - favorite_probability) * 0.55), 1)
        return TennisMarkets(
            winner=TennisMarketProjection(),
            set_handicap=TennisMarketProjection(
                selection=favorite if detailed else None, line=1.5 if detailed else None,
                probability=cover_probability if detailed else None,
                available=detailed, reason=None if detailed else unavailable,
            ),
            total_games=TennisMarketProjection(
                selection=("Más" if projected_total and line and projected_total >= line else "Menos") if detailed else None,
                line=line if detailed else None, probability=round(total_probability, 1) if detailed else None,
                projected_total=projected_total if detailed else None,
                available=detailed, reason=None if detailed else unavailable,
            ),
            exact_sets=TennisMarketProjection(
                selection=(f"{favorite} 2-0" if favorite_probability >= 62 else f"{favorite} 2-1") if detailed else None,
                probability=straight_probability if detailed else None,
                available=detailed, reason=None if detailed else unavailable,
            ),
        )

    @staticmethod
    def _wins(profile: PlayerProfile) -> int:
        return sum(int(match["won"]) for match in profile.matches)

    @staticmethod
    def _ratio(one_wins: float, one_total: float, two_wins: float, two_total: float) -> float:
        one_rate = (one_wins + 1) / (one_total + 2)
        two_rate = (two_wins + 1) / (two_total + 2)
        return one_rate / (one_rate + two_rate)

    @classmethod
    def _metric_ratio(cls, one: PlayerProfile, two: PlayerProfile, won: str, lost: str) -> float:
        one_won, one_lost = sum(m[won] for m in one.matches), sum(m[lost] for m in one.matches)
        two_won, two_lost = sum(m[won] for m in two.matches), sum(m[lost] for m in two.matches)
        return cls._ratio(one_won, one_won + one_lost, two_won, two_won + two_lost)

    @classmethod
    def _unavailable_reason(cls, one_count: int, two_count: int, decisive: bool) -> str:
        if one_count < cls.MIN_MATCHES or two_count < cls.MIN_MATCHES:
            return f"Historial insuficiente: {one_count} y {two_count} partidos; se requieren {cls.MIN_MATCHES} por jugador."
        if not decisive:
            return "La diferencia estimada es menor a tres puntos porcentuales."
        return "Datos insuficientes."

    @staticmethod
    def _kickoff(match: dict) -> datetime:
        return datetime.fromisoformat(match["date"].replace("Z", "+00:00"))

    @classmethod
    def _is_target(cls, row: dict, target_date: date, timezone: str) -> bool:
        state = (((row["match"].get("status") or {}).get("type") or {}).get("state"))
        kickoff = cls._kickoff(row["match"]).astimezone(cls._timezone(timezone))
        return kickoff.date() == target_date and state == "pre"

    @classmethod
    def _has_players(cls, row: dict) -> bool:
        names = [cls._name(item).strip().upper() for item in row["match"].get("competitors") or []]
        return len(names) == 2 and all(name not in {"TBD", "TBA", "JUGADOR DESCONOCIDO"} for name in names)

    @staticmethod
    def _timezone(name: str):
        offsets = {"UTC": 0, "America/Mexico_City": -6, "America/New_York": -5, "America/Los_Angeles": -8}
        if name not in offsets:
            raise ValueError(f"Zona horaria no soportada: {name}")
        return fixed_timezone(timedelta(hours=offsets[name]))
