"""Admin API for the persisted football competition catalog."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, status

from app.sports.football.competitions.models import (
    CompetitionCreate,
    CompetitionListResponse,
    CompetitionPatch,
    CompetitionRecord,
    CompetitionType,
)
from app.sports.football.competitions.service import (
    CompetitionNotFound,
    CompetitionService,
)

router = APIRouter(
    prefix="/api/v1/football/competitions",
    tags=["Football Competitions"],
)

_COMPETITION_EXAMPLES = {
    "copa_del_rey": {
        "summary": "Copa del Rey sin cobertura automática declarada",
        "value": {
            "code": "copa_del_rey",
            "name": "Copa del Rey",
            "country": "España",
            "type": "cup",
            "active": True,
            "registration_available": True,
            "providers": None,
            "capabilities": {"query": True, "automatic_settlement": False},
        },
    },
    "dfb_pokal": {
        "summary": "DFB-Pokal con identificador ESPN configurado",
        "value": {
            "code": "dfb_pokal",
            "name": "DFB-Pokal",
            "country": "Alemania",
            "type": "cup",
            "active": True,
            "registration_available": True,
            "providers": {"espn": {"competition_id": "ger.dfb_pokal"}},
            "capabilities": {"query": True, "automatic_settlement": False},
        },
    },
}


def _service(request: Request) -> CompetitionService:
    service = getattr(request.app.state, "football_competition_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="Catálogo de competiciones no configurado."
        )
    return service


@router.post(
    "",
    response_model=CompetitionRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Registra una competición de fútbol",
    description=(
        "Crea un código estable en el catálogo persistido. La competición se puede "
        "usar de inmediato en registros manuales aunque no tenga proveedor o "
        "liquidación automática. Configurar IDs externos no garantiza cobertura."
    ),
    responses={
        201: {"description": "Competición creada."},
        409: {"description": "Ya existe una competición con ese code."},
        422: {"description": "Code o configuración inválidos."},
        503: {"description": "MongoDB no disponible."},
    },
)
async def create_competition(
    request: Request,
    payload: Annotated[
        CompetitionCreate,
        Body(openapi_examples=_COMPETITION_EXAMPLES),
    ],
) -> CompetitionRecord:
    try:
        return await _service(request).create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "",
    response_model=CompetitionListResponse,
    summary="Lista competiciones registradas",
)
async def list_competitions(
    request: Request,
    active: bool | None = None,
    country: str | None = Query(default=None, min_length=1, max_length=100),
    competition_type: CompetitionType | None = Query(default=None, alias="type"),
    registration_available: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> CompetitionListResponse:
    try:
        return await _service(request).list(
            active=active,
            country=country,
            competition_type=competition_type.value if competition_type else None,
            registration_available=registration_available,
            page=page,
            page_size=page_size,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/{code}",
    response_model=CompetitionRecord,
    summary="Consulta una competición",
)
async def get_competition(
    request: Request,
    code: str = Path(pattern=r"^[a-z][a-z0-9_]{1,63}$"),
) -> CompetitionRecord:
    try:
        return await _service(request).get(code)
    except CompetitionNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"No existe la competición {code}."
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.patch(
    "/{code}",
    response_model=CompetitionRecord,
    summary="Actualiza configuración o estado de una competición",
    description=(
        "PATCH solo modifica campos enviados. Las capacidades anidadas se fusionan "
        "parcialmente; omitir providers/capabilities conserva la configuración. "
        "code es inmutable y no forma parte del cuerpo."
    ),
    responses={
        200: {"description": "Configuración actualizada."},
        404: {"description": "Competición inexistente."},
        422: {"description": "Campos o configuración inválidos."},
        503: {"description": "MongoDB no disponible."},
    },
)
async def patch_competition(
    request: Request,
    payload: CompetitionPatch,
    code: str = Path(pattern=r"^[a-z][a-z0-9_]{1,63}$"),
) -> CompetitionRecord:
    try:
        return await _service(request).patch(code, payload)
    except CompetitionNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"No existe la competición {code}."
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
