"""Rutas de pronósticos de fútbol: registro por lotes, consulta y evaluación."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)

from app.shared.pagination import set_pagination_headers
from app.sports.football.predictions.catalog import (
    FootballLeague,
    Market,
    PERIOD_LABELS,
    Period,
    RULE_VERSION,
    SETTLEMENT_STATUS_LABELS,
    SettlementStatus,
    TimingStatus,
    league_catalog,
    market_catalog,
)
from app.sports.football.predictions.models import (
    FootballEvaluationListResponse,
    FootballLeagueCatalogItem,
    FootballMarketCatalogResponse,
    FootballMarketRuleResponse,
    FootballPredictionBatchRequest,
    FootballPredictionBatchResponse,
    FootballPredictionDetailResponse,
    FootballPredictionEvaluationCreate,
    FootballPredictionListResponse,
    PREDICTION_ID_PATTERN,
    StoredEvaluation,
)
from app.sports.football.predictions.repository import RepositoryConflict
from app.sports.football.predictions.service import (
    FootballPredictionService,
    PredictionNotFound,
    VersionNotFound,
)

router = APIRouter(prefix="/api/v1/football", tags=["Football Predictions"])

_BATCH_REQUEST_EXAMPLE: dict[str, Any] = {
    "items": [
        {
            "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
            "idempotency_key": "2026-10-24-liga-mx-736644-1x2-home",
            "event_id": 736644,
            "match_date": "2026-10-24",
            "league": "liga_mx",
            "home_team": "Pumas UNAM",
            "away_team": "Necaxa",
            "kickoff": "2026-10-24T20:00:00-06:00",
            "market": "1x2",
            "period": "full_time",
            "selection": "home",
            "probability": 58.0,
            "confidence": 4,
            "rationale": "Local con mejor forma y ventaja de localía.",
            "sources": [
                {
                    "name": "ESPN",
                    "url": "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/summary?event=736644",
                }
            ],
            "analyst": "ana.garcia",
            "method_version": "analista-v1",
            "generated_at": "2026-10-24T10:30:00-06:00",
        },
        {
            "idempotency_key": "2026-10-24-liga-mx-736644-total-goals-over-2.5",
            "event_id": 736644,
            "match_date": "2026-10-24",
            "league": "liga_mx",
            "home_team": "Pumas UNAM",
            "away_team": "Necaxa",
            "market": "total_goals",
            "period": "full_time",
            "selection": "over",
            "line": 2.5,
            "probability": 61.0,
            "confidence": 3,
            "rationale": "Ambos equipos generan más de dos goles por partido.",
            "sources": [{"name": "ESPN"}],
            "analyst": "ana.garcia",
            "method_version": "analista-v1",
        },
    ]
}

_BATCH_RESPONSE_EXAMPLE: dict[str, Any] = {
    "received_at": "2026-10-24T17:05:12.345678Z",
    "total": 2,
    "created": 2,
    "replayed": 0,
    "rejected": 0,
    "items": [
        {
            "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
            "version": 1,
            "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
            "idempotency_key": "2026-10-24-liga-mx-736644-1x2-home",
            "status": "created",
            "error": None,
            "analyst": "ana.garcia",
            "probability": 58.0,
            "received_before_kickoff": True,
        },
        {
            "prediction_id": "6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e",
            "version": 1,
            "version_id": "1f2e3d4c5b6a79880716253443526170",
            "idempotency_key": "2026-10-24-liga-mx-736644-total-goals-over-2.5",
            "status": "created",
            "error": None,
            "analyst": "ana.garcia",
            "probability": 61.0,
            "received_before_kickoff": True,
        },
    ],
}

_VALIDATION_EXAMPLE: dict[str, Any] = {
    "detail": [
        {
            "type": "value_error",
            "loc": ["body", "items", 0],
            "msg": "Value error, line debe ser múltiplo de 0.25 para asian_handicap y de 0.5 para los demás mercados.",
            "input": {"market": "total_goals", "line": 2.25},
        }
    ]
}

_REPLAY_RESPONSE_EXAMPLE: dict[str, Any] = {
    "received_at": "2026-10-24T17:12:00Z",
    "total": 1,
    "created": 0,
    "replayed": 1,
    "rejected": 0,
    "items": [
        {
            "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
            "version": 1,
            "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
            "idempotency_key": "2026-10-24-liga-mx-736644-1x2-home",
            "status": "replayed",
            "error": None,
            "analyst": "ana.garcia",
            "probability": 58.0,
            "received_before_kickoff": True,
        }
    ],
}

_CONFLICT_EXAMPLE: dict[str, Any] = {
    "received_at": "2026-10-24T17:10:00Z",
    "total": 1,
    "created": 0,
    "replayed": 0,
    "rejected": 1,
    "items": [
        {
            "prediction_id": "6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e",
            "version": None,
            "version_id": None,
            "idempotency_key": "2026-10-24-liga-mx-736644-total-goals-over-2.5",
            "status": "rejected",
            "error": "idempotency_key ya existe con un cuerpo distinto.",
            "analyst": "ana.garcia",
            "probability": 58.0,
            "received_before_kickoff": None,
        }
    ],
}

_MIXED_RESPONSE_EXAMPLE: dict[str, Any] = {
    "received_at": "2026-10-24T17:12:00Z",
    "total": 2,
    "created": 0,
    "replayed": 1,
    "rejected": 1,
    "items": [
        _REPLAY_RESPONSE_EXAMPLE["items"][0],
        _CONFLICT_EXAMPLE["items"][0],
    ],
}

_STORED_PREDICTION_EXAMPLE: dict[str, Any] = {
    "document_id": "671b2c3d4e5f60718293a4b5",
    "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
    "version": 1,
    "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
    "is_current": True,
    "supersedes_version_id": None,
    "event_id": 736644,
    "match": {
        "event_id": 736644,
        "date": "2026-10-24",
        "declared_date": "2026-10-24",
        "league": "liga_mx",
        "league_name": "Liga MX",
        "country": "México",
        "home_team": "Pumas UNAM",
        "away_team": "Necaxa",
        "kickoff": "2026-10-25T02:00:00Z",
        "kickoff_source": "provider",
        "kickoff_verified": True,
    },
    "market": "1x2",
    "period": "full_time",
    "selection": "home",
    "line": None,
    "team": None,
    "player": None,
    "player_id": None,
    "home_goals": None,
    "away_goals": None,
    "probability": 58.0,
    "confidence": 4,
    "rationale": "Local con mejor forma y ventaja de localía.",
    "sources": [
        {
            "name": "ESPN",
            "url": (
                "https://site.api.espn.com/apis/site/v2/sports/soccer/"
                "mex.1/summary?event=736644"
            ),
            "note": "Forma reciente y estadísticas del partido.",
        }
    ],
    "analyst": "ana.garcia",
    "method_version": "analista-v1",
    "generated_at": "2026-10-24T16:30:00Z",
    "received_at": "2026-10-24T17:05:12.345678Z",
    "timing": {"status": "pre_match", "received_before_kickoff": True},
    "settlement_status": "pendiente",
    "settlement": None,
    "notes": None,
    "created_at": "2026-10-24T17:05:12.345678Z",
    "updated_at": "2026-10-24T17:05:12.345678Z",
}

_BATCH_RESPONSE_EXAMPLE["items"][0]["record"] = _STORED_PREDICTION_EXAMPLE
_REPLAY_RESPONSE_EXAMPLE["items"][0]["record"] = _STORED_PREDICTION_EXAMPLE

_LIST_RESPONSE_EXAMPLE: dict[str, Any] = {
    "items": [_STORED_PREDICTION_EXAMPLE],
    "page": 1,
    "page_size": 50,
    "total": 1,
}

_DETAIL_RESPONSE_EXAMPLE: dict[str, Any] = {
    "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
    "total_versions": 1,
    "current_version": 1,
    "latest_verified_pre_match_version": 1,
    "latest_verified_pre_match": _STORED_PREDICTION_EXAMPLE,
    "versions": [_STORED_PREDICTION_EXAMPLE],
}

_EVALUATION_EXAMPLE: dict[str, Any] = {
    "evaluation_id": "671c3d4e5f60718293a4b5c6",
    "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
    "version": 1,
    "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
    "analyst": "ana.garcia",
    "diagnosis": (
        "El local dominó el primer tiempo, pero el gol visitante al 60' "
        "cambió el guion; el 1X2 se resolvió por un gol tardío."
    ),
    "learnings": [
        "La ventaja de localía pesó más que la forma reciente.",
        "No dar por cerrado un 1X2 con un solo gol de diferencia.",
    ],
    "sources": [{"name": "ESPN", "url": None, "note": "Resumen del partido."}],
    "outcome_comment": "Se cumplió la lectura del primer tiempo.",
    "tags": ["1x2", "lectura-de-partido"],
    "created_at": "2026-10-25T05:10:00Z",
}

_EVALUATION_LIST_EXAMPLE: dict[str, Any] = {
    "items": [_EVALUATION_EXAMPLE],
    "page": 1,
    "page_size": 50,
    "total": 1,
}

_COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    422: {
        "description": "Cuerpo o parámetros inválidos.",
        "content": {"application/json": {"example": _VALIDATION_EXAMPLE}},
    },
    503: {
        "description": "MongoDB o la fuente no están disponibles.",
        "content": {
            "application/json": {
                "example": {"detail": "Persistencia deshabilitada."}
            }
        },
    },
}


def _service(request: Request) -> FootballPredictionService:
    service = getattr(
        request.app.state, "football_prediction_service", None
    )
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de pronósticos no configurado.",
        )
    return service


@router.get(
    "/predictions/markets",
    response_model=FootballMarketCatalogResponse,
    summary="Catálogo de ligas, mercados, periodos y reglas",
)
async def prediction_catalog() -> FootballMarketCatalogResponse:
    return FootballMarketCatalogResponse(
        rule_version=RULE_VERSION,
        periods={
            period.value: label for period, label in PERIOD_LABELS.items()
        },
        settlement_statuses={
            key.value: label
            for key, label in SETTLEMENT_STATUS_LABELS.items()
        },
        leagues=[
            FootballLeagueCatalogItem(**league)
            for league in league_catalog()
        ],
        markets=[
            FootballMarketRuleResponse(**market)
            for market in market_catalog()
        ],
    )


@router.post(
    "/predictions",
    response_model=FootballPredictionBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registra un lote de selecciones",
    description=(
        "Cada elemento del lote se guarda por separado. Errores de esquema o "
        "validación Pydantic invalidan el lote completo con 422; conflictos de "
        "negocio se devuelven en el elemento afectado. received_at siempre lo "
        "genera el servidor. Solo un inicio verificado permite declarar "
        "pre_match/late; el kickoff declarado sin verificación queda como "
        "referencia y timing=unverified. Reenviar la misma idempotency_key con el "
        "mismo cuerpo devuelve la versión existente; con otro cuerpo se "
        "rechaza ese elemento. Responder 201 si hubo creaciones; 200 si no "
        "hubo creaciones y existe al menos "
        "un reintento válido (puede incluir rechazos); 409 si todos los elementos "
        "fueron rechazados."
    ),
    responses={
        201: {
            "description": "Al menos una selección se registró como versión nueva.",
            "content": {
                "application/json": {"example": _BATCH_RESPONSE_EXAMPLE}
            },
        },
        200: {
            "model": FootballPredictionBatchResponse,
            "description": "No hubo creaciones y al menos un reintento válido; puede incluir rechazos por elemento.",
            "content": {
                "application/json": {"example": _MIXED_RESPONSE_EXAMPLE}
            },
        },
        409: {
            "model": FootballPredictionBatchResponse,
            "description": "Ninguna selección se pudo aceptar.",
            "content": {"application/json": {"example": _CONFLICT_EXAMPLE}},
        },
        **_COMMON_ERRORS,
    },
)
async def register_predictions(
    request: Request,
    response: Response,
    payload: Annotated[
        FootballPredictionBatchRequest,
        Body(openapi_examples={"lote_liga_mx": {"value": _BATCH_REQUEST_EXAMPLE}}),
    ],
) -> FootballPredictionBatchResponse:
    service = _service(request)
    try:
        result = await service.register_batch(payload)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if result.created:
        response.status_code = status.HTTP_201_CREATED
    elif result.replayed:
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_409_CONFLICT
    return result


@router.get(
    "/predictions",
    response_model=FootballPredictionListResponse,
    summary="Consulta el historial de selecciones",
    description=(
        "Por defecto devuelve solo la versión vigente de cada selección. Usa "
        "include_versions=true para ver también las versiones anteriores. "
        "match_date se interpreta como jornada en Ciudad de México (UTC-6); "
        "received_date filtra por el día en que el servidor recibió el "
        "registro, también en CDMX."
    ),
    responses={
        200: {
            "description": "Página de selecciones registradas.",
            "content": {
                "application/json": {"example": _LIST_RESPONSE_EXAMPLE}
            },
        },
        **_COMMON_ERRORS,
    },
)
async def list_predictions(
    request: Request,
    response: Response,
    match_date: date | None = Query(default=None),
    match_date_from: date | None = Query(default=None),
    match_date_to: date | None = Query(default=None),
    received_date: date | None = Query(default=None),
    league: FootballLeague | None = Query(default=None),
    event_id: int | None = Query(default=None, gt=0),
    analyst: str | None = Query(default=None, min_length=1),
    market: Market | None = Query(default=None),
    settlement_status: SettlementStatus | None = Query(default=None),
    period: Period | None = Query(default=None),
    timing: TimingStatus | None = Query(default=None),
    include_versions: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FootballPredictionListResponse:
    if match_date is not None and (
        match_date_from is not None or match_date_to is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Usa match_date o el rango match_date_from/match_date_to, no ambos.",
        )
    if (
        match_date_from is not None
        and match_date_to is not None
        and match_date_from > match_date_to
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="match_date_from no puede ser posterior a match_date_to.",
        )
    try:
        result = await _service(request).list_predictions(
            match_date=match_date,
            match_date_from=match_date_from,
            match_date_to=match_date_to,
            received_date=received_date,
            league=league,
            event_id=event_id,
            analyst=analyst,
            market=market.value if market else None,
            settlement_status=settlement_status,
            period=period,
            timing=timing,
            include_versions=include_versions,
            page=page,
            page_size=page_size,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    set_pagination_headers(
        response, total=result.total, page=page, page_size=page_size
    )
    return result


@router.get(
    "/predictions/{prediction_id}",
    response_model=FootballPredictionDetailResponse,
    summary="Recupera una selección con todas sus versiones",
    responses={
        200: {
            "description": "Selección con su historial de versiones.",
            "content": {
                "application/json": {"example": _DETAIL_RESPONSE_EXAMPLE}
            },
        },
        404: {
            "description": "No existe ese prediction_id.",
            "content": {
                "application/json": {"example": {"detail": "No encontrado."}}
            },
        },
        **_COMMON_ERRORS,
    },
)
async def get_prediction(
    request: Request,
    prediction_id: str = Path(pattern=PREDICTION_ID_PATTERN),
) -> FootballPredictionDetailResponse:
    try:
        return await _service(request).get_prediction(prediction_id)
    except PredictionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró el prediction_id.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/predictions/{prediction_id}/evaluations",
    response_model=StoredEvaluation,
    status_code=status.HTTP_201_CREATED,
    summary="Registra la evaluación posterior del analista",
    description=(
        "La evaluación se guarda en una colección aparte y queda ligada al "
        "prediction_id, versión y version_id. No modifica la selección, "
        "probabilidad, confianza ni fecha originales. La liquidación oficial "
        "sigue siendo responsabilidad del servicio autorizado."
    ),
    responses={
        201: {
            "description": "Evaluación posterior registrada.",
            "content": {
                "application/json": {"example": _EVALUATION_EXAMPLE}
            },
        },
        404: {
            "description": "No existe el pronóstico o la versión indicada.",
            "content": {
                "application/json": {"example": {"detail": "No encontrado."}}
            },
        },
        409: {
            "description": "Ese analista ya evaluó esa versión.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Ya existe una evaluación de este analista "
                        "para esa versión."
                    }
                }
            },
        },
        **_COMMON_ERRORS,
    },
)
async def create_evaluation(
    request: Request,
    payload: FootballPredictionEvaluationCreate,
    prediction_id: str = Path(pattern=PREDICTION_ID_PATTERN),
) -> StoredEvaluation:
    try:
        return await _service(request).add_evaluation(prediction_id, payload)
    except (PredictionNotFound, VersionNotFound) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró el pronóstico o la versión indicada.",
        ) from exc
    except RepositoryConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get(
    "/predictions/{prediction_id}/evaluations",
    response_model=FootballEvaluationListResponse,
    summary="Consulta las evaluaciones posteriores",
    responses={
        200: {
            "description": "Evaluaciones posteriores de la selección.",
            "content": {
                "application/json": {"example": _EVALUATION_LIST_EXAMPLE}
            },
        },
        404: {
            "description": "No existe ese prediction_id.",
            "content": {
                "application/json": {"example": {"detail": "No encontrado."}}
            },
        },
        **_COMMON_ERRORS,
    },
)
async def list_evaluations(
    request: Request,
    response: Response,
    prediction_id: str = Path(pattern=PREDICTION_ID_PATTERN),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FootballEvaluationListResponse:
    try:
        result = await _service(request).list_evaluations(
            prediction_id, page=page, page_size=page_size
        )
    except PredictionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró el prediction_id.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    set_pagination_headers(
        response, total=result.total, page=page, page_size=page_size
    )
    return result


__all__ = ["router"]
