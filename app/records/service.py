"""Construcción y guardado de registros manuales."""

from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

from app.database.repository import PredictionRepository
from app.prompts.models import PromptReference, PromptType
from app.prompts.repository import PromptRepository
from app.records.models import (
    MANUAL_MODEL_VERSION,
    RecordCreateRequest,
    StoredRecord,
)
from app.sports.baseball.enrichment.schedule_client import (
    PublicBaseballScheduleClient,
)

PROVIDER = "manual"
WARNING = "Registro manual: sin cálculo de modelo."
DEFAULT_KICKOFF_TIMEZONE = timezone(timedelta(hours=-6))

LEAGUE_ALIASES: dict[str, dict[str, str]] = {
    "football": {
        "all": "all",
        "liga mx": "Liga MX",
        "liga_mx": "Liga MX",
        "brasileirao betano": "Brasileirão Betano",
        "brasileirao": "Brasileirão Betano",
        "brasileirão betano": "Brasileirão Betano",
        "leagues cup": "Leagues Cup",
        "leagues_cup": "Leagues Cup",
    },
    "nba": {
        "nba": "NBA",
        "wnba": "WNBA",
        "nba - summer league": "NBA - Summer League",
        "nba summer league": "NBA - Summer League",
        "summer league": "NBA - Summer League",
        "summer_league": "NBA - Summer League",
    },
    "baseball": {
        "mlb": "MLB",
        "kbo": "KBO",
    },
    "tennis": {
        "atp": "ATP",
        "wta": "WTA",
    },
}


def canonical_league(sport: str, value: str) -> str:
    """Normaliza la competición al texto que usan los filtros de /results."""
    key = " ".join(value.strip().split()).casefold()
    aliases = LEAGUE_ALIASES[sport]
    try:
        return aliases[key]
    except KeyError as exc:
        allowed = ", ".join(sorted(set(aliases.values())))
        raise ValueError(
            f"Competición no válida para {sport}: {value!r}. Usa: {allowed}."
        ) from exc


def resolve_event_id(payload: RecordCreateRequest, league: str) -> int:
    """Devuelve el id del partido; en béisbol lo deriva de liga, fecha y equipos."""
    if payload.event_id is not None:
        return payload.event_id
    home = PublicBaseballScheduleClient._canonical_team(league, payload.home_team)
    away = PublicBaseballScheduleClient._canonical_team(league, payload.away_team)
    return PublicBaseballScheduleClient._stable_id(
        f"{league}:game:{payload.date.isoformat()}:{away}:{home}"
    )


def resolve_kickoff(payload: RecordCreateRequest) -> str:
    if payload.kickoff is not None:
        return payload.kickoff.isoformat()
    start = datetime.combine(
        payload.date,
        time.min,
        tzinfo=DEFAULT_KICKOFF_TIMEZONE,
    )
    return start.isoformat()


def _probabilities(payload: RecordCreateRequest) -> dict[str, float]:
    if payload.sport == "football":
        values = {"home": 0.0, "draw": 0.0, "away": 0.0}
    elif payload.sport == "tennis":
        values = {"player_one": 0.0, "player_two": 0.0}
    else:
        values = {"home": 0.0, "away": 0.0}

    if payload.probability is not None:
        key = payload.pick
        if payload.sport == "tennis":
            key = "player_one" if payload.pick == "home" else "player_two"
        values[key] = float(payload.probability)
    return values


def _common_fields(payload: RecordCreateRequest) -> dict[str, Any]:
    return {
        "odds": payload.odds,
        "stake": payload.stake,
        "notes": payload.notes,
        "source": "manual",
        "warnings": [WARNING],
    }


def _football_prediction(
    payload: RecordCreateRequest,
    event_id: int,
    league: str,
    kickoff: str,
) -> dict[str, Any]:
    return {
        "fixture_id": event_id,
        "kickoff": kickoff,
        "timezone": payload.timezone,
        "league_id": 0,
        "league": league,
        "country": None,
        "home_team_id": payload.home_team_id or 0,
        "home_team": payload.home_team,
        "away_team_id": payload.away_team_id or 0,
        "away_team": payload.away_team,
        "data_quality_score": 0.0,
        "confidence": float(payload.probability or 0.0),
        "probabilities": _probabilities(payload),
        "predicted_result": payload.pick,
        "expected_goals_home": None,
        "expected_goals_away": None,
        "advice": None,
        "markets": payload.markets,
        "fusion": None,
        "weights": [],
        **_common_fields(payload),
    }


def _team_sport_prediction(
    payload: RecordCreateRequest,
    event_id: int,
    league: str,
    kickoff: str,
) -> dict[str, Any]:
    return {
        "game_id": event_id,
        "kickoff": kickoff,
        "league": league,
        "season": "",
        "home_team_id": payload.home_team_id or 0,
        "home_team": payload.home_team,
        "away_team_id": payload.away_team_id or 0,
        "away_team": payload.away_team,
        "data_quality_score": 0.0,
        "confidence": float(payload.probability or 0.0),
        "probabilities": _probabilities(payload),
        "predicted_result": payload.pick,
        "expected_score_home": None,
        "expected_score_away": None,
        "markets": payload.markets,
        "available_components": [],
        **_common_fields(payload),
    }


def _tennis_prediction(
    payload: RecordCreateRequest,
    event_id: int,
    league: str,
    kickoff: str,
) -> dict[str, Any]:
    winner = payload.home_team if payload.pick == "home" else payload.away_team
    markets = payload.markets or {
        "winner": {
            "available": True,
            "selection": winner,
            "probability": payload.probability,
        }
    }
    return {
        "match_id": event_id,
        "kickoff": kickoff,
        "league": league,
        "tour": league,
        "tournament": payload.tournament or league,
        "season": "",
        "round": None,
        "player_one_id": str(payload.home_team_id or 0),
        "player_one": payload.home_team,
        "player_two_id": str(payload.away_team_id or 0),
        "player_two": payload.away_team,
        "data_quality_score": 0.0,
        "confidence": float(payload.probability or 0.0),
        "probabilities": _probabilities(payload),
        "predicted_winner": winner,
        "markets": markets,
        "available_components": [],
        **_common_fields(payload),
    }


_BUILDERS = {
    "football": _football_prediction,
    "nba": _team_sport_prediction,
    "baseball": _team_sport_prediction,
    "tennis": _tennis_prediction,
}


def build_document(
    payload: RecordCreateRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Devuelve ``(identidad, documento)`` listos para el upsert."""
    league = canonical_league(payload.sport, payload.league)
    event_id = resolve_event_id(payload, league)
    kickoff = resolve_kickoff(payload)
    now = datetime.now(UTC)

    identity: dict[str, Any] = {
        "sport": payload.sport,
        "event_id": event_id,
        "requested_date": payload.date.isoformat(),
    }
    if payload.sport != "tennis":
        identity["model_version"] = MANUAL_MODEL_VERSION

    document: dict[str, Any] = {
        **identity,
        "sport": payload.sport,
        "event_id": event_id,
        "requested_date": payload.date.isoformat(),
        "model_version": MANUAL_MODEL_VERSION,
        "provider": PROVIDER,
        "timezone": payload.timezone,
        "prediction": _BUILDERS[payload.sport](
            payload,
            event_id,
            league,
            kickoff,
        ),
        "generated_at": now,
    }
    return identity, document


class ManualRecordService:
    def __init__(
        self,
        repository: PredictionRepository,
        prompt_repository: PromptRepository | None = None,
    ) -> None:
        self._repository = repository
        self._prompt_repository = prompt_repository

    async def register(self, payload: RecordCreateRequest) -> StoredRecord:
        if self._prompt_repository is None:
            raise RuntimeError("Repositorio de prompts no configurado.")
        prompt = await self._prompt_repository.get_version_by_id(
            payload.sport,
            PromptType.ANALYSIS.value,
            payload.analysis_prompt_version_id,
        )
        if prompt is None:
            raise ValueError(
                "analysis_prompt_version_id no existe para el deporte y tipo analysis."
            )
        identity, document = build_document(payload)
        document["analysis_prompt"] = PromptReference(
            prompt_id=prompt.get("prompt_id", f"{payload.sport}.analysis"),
            version=int(prompt["version"]),
            version_id=prompt["version_id"],
        ).model_dump(mode="json")
        stored = await self._repository.upsert_record(identity, document)
        return StoredRecord(**stored)
