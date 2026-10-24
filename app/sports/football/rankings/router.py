"""API for rankings authored and submitted by football analysts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, Response, status

from app.shared.pagination import set_pagination_headers
from app.sports.football.predictions.catalog import FootballLeague
from app.sports.football.rankings.models import (
    FootballRankingBatchCreate,
    FootballRankingBatchResponse,
    FootballRankingDetailResponse,
    FootballRankingListResponse,
    RankingScope,
    RankingType,
)
from app.sports.football.rankings.service import (
    RankingNotFound,
    RankingReferenceNotFound,
    RankingService,
)

router = APIRouter(
    prefix="/api/v1/football/rankings",
    tags=["Football Rankings"],
)
CDMX = ZoneInfo("America/Mexico_City")

_LEAGUE_REQUEST = {
    "items": [
        {
            "ranking_id": "rank-liga-mx-winner-20261024",
            "idempotency_key": "rank-liga-mx-winner-20261024-v1",
            "target_date": "2026-10-24",
            "timezone": "America/Mexico_City",
            "analyst": "ana.garcia",
            "scope": "league",
            "competition": "liga_mx",
            "ranking_type": "winner",
            "sort_criterion": "probabilidad_descendente",
            "sort_direction": "desc",
            "analysis_prompt_version_id": "3be3ffee060a4f01b01057c32f5ae197",
            "method_version": "analista-v2",
            "generated_at": "2026-10-24T10:30:00-06:00",
            "coverage": {
                "matches_considered": 4,
                "matches_with_rows": 3,
                "coverage_complete": False,
                "limitations": ["Un partido sin estimación confiable."],
            },
            "rows": [
                {
                    "position": 1,
                    "league": "liga_mx",
                    "event_id": 736644,
                    "home_team": "Pumas UNAM",
                    "away_team": "Necaxa",
                    "kickoff": "2026-10-24T20:00:00-06:00",
                    "match_status": "scheduled",
                    "market": "1x2",
                    "period": "full_time",
                    "selection": "home",
                    "estimate_status": "estimated",
                    "probability": 58,
                    "confidence": 4,
                    "rationale": "La estimación del analista favorece al local.",
                    "risk": "Alineaciones aún no confirmadas.",
                    "prediction_id": "pred-liga-mx-736644-home",
                    "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
                },
                {
                    "position": 2,
                    "league": "liga_mx",
                    "event_id": 736645,
                    "home_team": "Atlas",
                    "away_team": "Puebla",
                    "match_status": "scheduled",
                    "market": "1x2",
                    "period": "full_time",
                    "selection": "away",
                    "estimate_status": "not_estimated",
                    "no_estimate_reason": "Datos insuficientes para estimar.",
                },
            ],
        }
    ]
}
_GENERAL_REQUEST = {
    "items": [
        {
            "idempotency_key": "rank-general-confidence-20261024-v1",
            "target_date": "2026-10-24",
            "timezone": "America/Mexico_City",
            "analyst": "ana.garcia",
            "scope": "general",
            "competition": None,
            "ranking_type": "overall_high_confidence",
            "sort_criterion": "confidence_desc_then_probability_desc",
            "sort_direction": "desc",
            "analysis_prompt_version_id": "3be3ffee060a4f01b01057c32f5ae197",
            "method_version": "analista-v2",
            "generated_at": "2026-10-24T10:30:00-06:00",
            "coverage": {
                "matches_considered": 12,
                "matches_with_rows": 2,
                "coverage_complete": False,
                "limitations": ["Solo se incluyen selecciones sustentadas."],
            },
            "rows": [
                {
                    "position": 1,
                    "league": "mls",
                    "event_id": 123456,
                    "home_team": "Seattle Sounders",
                    "away_team": "Portland Timbers",
                    "match_status": "scheduled",
                    "market": "corners_total",
                    "period": "full_time",
                    "selection": "over",
                    "line": 8.5,
                    "estimate_status": "estimated",
                    "probability": 70,
                    "confidence": 5,
                    "rationale": "Selección principal publicada por el analista.",
                    "expected_value": 10.2,
                    "expected_value_unit": "corners",
                },
                {
                    "position": 2,
                    "league": "liga_mx",
                    "event_id": 654321,
                    "home_team": "Toluca",
                    "away_team": "Monterrey",
                    "match_status": "scheduled",
                    "market": "1x2",
                    "period": "full_time",
                    "selection": "home",
                    "estimate_status": "estimated",
                    "probability": 66,
                    "confidence": 4,
                    "rationale": "Segunda selección de otra liga.",
                },
            ],
        }
    ]
}


def _service(request: Request) -> RankingService:
    service = getattr(request.app.state, "football_ranking_service", None)
    if service is None:
        raise RuntimeError("Servicio de rankings no configurado.")
    return service


@router.post(
    "",
    response_model=FootballRankingBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registra uno o varios rankings elaborados por analistas",
    description=(
        "La API valida, almacena y versiona el contenido enviado. No calcula, "
        "completa, reordena ni evalúa la calidad deportiva del ranking. GET no "
        "genera ni modifica rankings. Un prediction_id/version_id es opcional; "
        "si se envía, se valida y debe ser compatible con su fila."
    ),
    responses={
        201: {"description": "Al menos un ranking se registró como versión nueva."},
        200: {"description": "Reintento idempotente sin creaciones nuevas."},
        409: {"description": "Conflicto de idempotencia o de versión."},
        422: {"description": "Estructura o referencia inválida; el lote no se inserta."},
        503: {"description": "MongoDB o una dependencia de validación no disponible."},
    },
)
async def create_rankings(
    request: Request,
    response: Response,
    payload: Annotated[
        FootballRankingBatchCreate,
        Body(
            openapi_examples={
                "ranking_por_liga": {"value": _LEAGUE_REQUEST},
                "ranking_general": {"value": _GENERAL_REQUEST},
            }
        ),
    ],
) -> FootballRankingBatchResponse:
    try:
        result = await _service(request).register_batch(payload)
    except RankingReferenceNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.created:
        response.status_code = status.HTTP_201_CREATED
    elif result.replayed:
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_409_CONFLICT
    return result


@router.get(
    "",
    response_model=FootballRankingListResponse,
    summary="Consulta rankings almacenados",
    description=(
        "Devuelve exactamente las filas y el orden enviados por los analistas. "
        "Si se omite date, usa hoy en America/Mexico_City. La consulta es de "
        "solo lectura y una ausencia devuelve items vacío, nunca un ranking generado."
    ),
    responses={
        200: {"description": "Página de rankings almacenados."},
        503: {"description": "MongoDB no disponible."},
    },
)
async def list_rankings(
    request: Request,
    response: Response,
    target_date: date | None = Query(default=None, alias="date"),
    league: FootballLeague | None = None,
    analyst: str | None = Query(default=None, min_length=1, max_length=80),
    scope: RankingScope | None = None,
    ranking_type: RankingType | None = None,
    include_versions: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FootballRankingListResponse:
    resolved_date = target_date or datetime.now(CDMX).date()
    try:
        result = await _service(request).list_rankings(
            target_date=resolved_date,
            league=league,
            analyst=analyst,
            scope=scope,
            ranking_type=ranking_type,
            include_versions=include_versions,
            page=page,
            page_size=page_size,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    set_pagination_headers(
        response,
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
    return result


@router.get(
    "/{ranking_id}",
    response_model=FootballRankingDetailResponse,
    summary="Consulta un ranking y su historial de versiones",
    responses={
        200: {"description": "Ranking actual o versión exacta, más historial paginado."},
        404: {"description": "Ranking o revisión inexistente."},
        422: {"description": "Parámetros de versión incompatibles."},
        503: {"description": "MongoDB no disponible."},
    },
)
async def get_ranking(
    request: Request,
    ranking_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"),
    version: int | None = Query(default=None, ge=1),
    version_id: str | None = Query(default=None, pattern=r"^[A-Fa-f0-9]{32}$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FootballRankingDetailResponse:
    try:
        return await _service(request).get_ranking(
            ranking_id,
            version=version,
            version_id=version_id,
            history_page=page,
            history_page_size=page_size,
        )
    except RankingNotFound as exc:
        raise HTTPException(status_code=404, detail="Ranking o versión no encontrados.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
