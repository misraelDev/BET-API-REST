"""HTTP API for versioned analyst prompts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.prompts.models import (
    Prompt,
    PromptCreate,
    PromptSport,
    PromptType,
    PromptVersionListResponse,
    VERSION_ID_PATTERN,
)
from app.prompts.repository import PromptRepository
from app.prompts.service import PromptNotFound, PromptService
from app.sports.football.predictions.repository import RepositoryConflict

router = APIRouter(
    prefix="/api/v1/prompts",
    tags=["Prompts"],
    responses={
        503: {"description": "Persistencia de prompts no disponible."},
    },
)


def _service(request: Request) -> PromptService:
    repository: PromptRepository = request.app.state.prompt_repository
    return PromptService(repository)


@router.get(
    "/{sport}/{prompt_type}",
    response_model=Prompt,
    summary="Consulta el prompt vigente o una versión exacta",
    description=(
        "Sin version ni version_id devuelve la versión vigente. Usa uno de esos "
        "parámetros para recuperar una revisión histórica exacta. Las versiones "
        "son inmutables."
    ),
    responses={
        200: {
            "description": "Prompt y metadatos de su versión.",
            "content": {
                "application/json": {
                    "example": {
                        "document_id": "665b9c6ab78c014ef4d1ab22",
                        "sport": "football",
                        "prompt_type": "analysis",
                        "version": 2,
                        "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
                        "is_current": True,
                        "supersedes_version_id": "1f2e3d4c5b6a79880716253443526170",
                        "prompt": "Analiza la jornada con evidencia verificable...",
                        "author": "ana.garcia",
                        "change_summary": "Agregar consulta de pronósticos previos.",
                        "created_at": "2026-10-24T20:00:00Z",
                    }
                }
            },
        },
        404: {"description": "No existe ese prompt o versión."},
        422: {"description": "Parámetros incompatibles o inválidos."},
    },
)
async def get_prompt(
    request: Request,
    sport: PromptSport,
    prompt_type: PromptType,
    version: Annotated[int | None, Query(ge=1)] = None,
    version_id: Annotated[
        str | None, Query(pattern=VERSION_ID_PATTERN)
    ] = None,
) -> Prompt:
    try:
        return await _service(request).get(
            sport,
            prompt_type,
            version=version,
            version_id=version_id,
        )
    except PromptNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/{sport}/{prompt_type}/versions",
    response_model=PromptVersionListResponse,
    summary="Consulta el historial inmutable del prompt",
    responses={200: {"description": "Historial ascendente de versiones."}},
)
async def list_prompt_versions(
    request: Request,
    sport: PromptSport,
    prompt_type: PromptType,
) -> PromptVersionListResponse:
    try:
        items = await _service(request).history(sport, prompt_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    current = next((item.version for item in items if item.is_current), None)
    return PromptVersionListResponse(
        sport=sport,
        prompt_type=prompt_type,
        total=len(items),
        current_version=current,
        items=items,
    )


@router.post(
    "/{sport}/{prompt_type}",
    response_model=Prompt,
    status_code=status.HTTP_201_CREATED,
    summary="Publica una nueva versión inmutable del prompt",
    description=(
        "Cada publicación crea una versión nueva; no hay edición in-place. "
        "base_version_id debe coincidir con la versión vigente; usa null solo "
        "para el primer registro. Este endpoint no tiene autenticación: protégelo "
        "con controles de acceso del proxy/red antes de habilitar escrituras públicas."
    ),
    responses={
        201: {"description": "Nueva versión registrada."},
        409: {"description": "La versión base está desactualizada o hubo una carrera."},
        422: {"description": "Prompt o base_version_id inválido."},
        503: {"description": "Persistencia de prompts no disponible."},
    },
)
async def publish_prompt(
    request: Request,
    payload: PromptCreate,
    sport: PromptSport,
    prompt_type: PromptType,
) -> Prompt:
    try:
        return await _service(request).publish(sport, prompt_type, payload)
    except RepositoryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
