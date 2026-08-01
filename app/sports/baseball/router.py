import logging
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from app.shared.pagination import set_pagination_headers
from app.shared.prediction_filters import kickoff_hour_filter

from app.shared.exceptions import ApiSportsError
from app.sports.baseball.models import (
    BaseballLeague,
    BaseballPredictionRequest,
    BaseballResultsUpdateRequest,
    BaseballResultsUpdateResponse,
    OfficialBaseballGame,
    SportDailyPredictionResponse,
    StoredBaseballPrediction,
)

router = APIRouter(prefix="/api/v1/baseball", tags=["Baseball"])
logger = logging.getLogger(__name__)


@router.get("/stats")
async def baseball_stats(
    request: Request,
    league: BaseballLeague = Query(default=BaseballLeague.ALL),
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    try:
        date_from = (date.today() - timedelta(days=days - 1)).isoformat()
        return await request.app.state.prediction_repository.baseball_dashboard_stats(
            league=league.value,
            date_from=date_from,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/official-results", response_model=list[OfficialBaseballGame])
async def official_results(
    request: Request,
    target_date: date = Query(alias="date"),
    league: BaseballLeague = Query(default=BaseballLeague.MLB),
) -> list[OfficialBaseballGame]:
    try:
        if league == BaseballLeague.ALL:
            raise HTTPException(
                status_code=422,
                detail="Selecciona MLB o KBO.",
            )
        client = (
            request.app.state.mlb_official_results
            if league == BaseballLeague.MLB
            else request.app.state.kbo_official_results
        )
        return await client.get_results(target_date)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.exception(
            "baseball.official_results_failed date=%s league=%s",
            target_date,
            league.value,
        )
        raise HTTPException(
            status_code=502,
            detail=f"No fue posible consultar los resultados oficiales MLB: {exc}",
        ) from exc


@router.post("/results/update", response_model=BaseballResultsUpdateResponse)
async def update_market_results(
    payload: BaseballResultsUpdateRequest,
    request: Request,
) -> BaseballResultsUpdateResponse:
    if payload.league == BaseballLeague.ALL:
        raise HTTPException(
            status_code=422,
            detail="Selecciona MLB o KBO.",
        )
    try:
        return await request.app.state.baseball_results_update.update(
            payload.date,
            payload.league.value.upper(),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No fue posible consultar resultados oficiales: {exc}",
        ) from exc


async def _generate_predictions(
    request: Request,
    target_date: date,
    timezone: str,
    limit: int,
    league: BaseballLeague,
) -> SportDailyPredictionResponse:
    logger.info(
        "baseball.generate date=%s timezone=%s limit=%s league=%s",
        target_date,
        timezone,
        limit,
        league.value,
    )
    try:
        response = await request.app.state.baseball_service.predict_league_date(
            target_date, timezone, limit, league
        )
        response.persistence = await request.app.state.prediction_repository.save_response(
            "baseball", response
        )
        logger.info(
            "baseball.generate_completed date=%s found=%s returned=%s inserted=%s updated=%s",
            target_date,
            response.games_found,
            response.games_returned,
            response.persistence.inserted,
            response.persistence.updated,
        )
        return response
    except ApiSportsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Respuesta incompatible del proveedor: {exc}",
        ) from exc


@router.get("/predictions", response_model=SportDailyPredictionResponse)
async def daily_predictions(
    request: Request,
    target_date: date = Query(alias="date"),
    timezone: str = Query(default="America/Mexico_City"),
    limit: int = Query(default=20, ge=1, le=20),
    league: BaseballLeague = Query(default=BaseballLeague.ALL),
) -> SportDailyPredictionResponse:
    return await _generate_predictions(
        request, target_date, timezone, limit, league
    )


@router.post("/predictions", response_model=SportDailyPredictionResponse)
async def create_predictions(
    payload: BaseballPredictionRequest,
    request: Request,
) -> SportDailyPredictionResponse:
    return await _generate_predictions(
        request,
        payload.date,
        payload.timezone,
        payload.limit,
        payload.league,
    )


@router.get("/results", response_model=list[StoredBaseballPrediction])
async def stored_results(
    request: Request,
    response: Response,
    target_date: date | None = Query(default=None, alias="date"),
    league: BaseballLeague = Query(default=BaseballLeague.ALL),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    limit: int | None = Query(default=None, ge=1, le=200, deprecated=True),
    hour: int | None = Query(default=None, ge=0, le=23),
) -> list[StoredBaseballPrediction]:
    logger.info(
        "baseball.results date=%s league=%s limit=%s source=mongodb",
        target_date or "all",
        league.value,
        limit,
    )
    try:
        size = limit or page_size
        repository = request.app.state.prediction_repository
        query_date = target_date.isoformat() if target_date else None
        filters = kickoff_hour_filter(target_date, hour) if target_date is not None and hour is not None else None
        if hour is not None and target_date is None:
            raise HTTPException(status_code=422, detail="La fecha es obligatoria para filtrar por hora.")
        total = await repository.count_predictions(
            sport="baseball", requested_date=query_date, league=league.value,
            filters=filters,
        )
        results = await repository.list_predictions(
            sport="baseball",
            requested_date=query_date,
            league=league.value,
            limit=size,
            offset=(page - 1) * size,
            filters=filters,
        )
        set_pagination_headers(response, total=total, page=page, page_size=size)
        logger.info("baseball.results_completed count=%s source=mongodb", len(results))
        return results
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/results/settle")
async def settle_results(
    request: Request,
    target_date: date = Query(alias="date"),
    timezone: str = Query(default="America/Mexico_City"),
    league: BaseballLeague = Query(default=BaseballLeague.ALL),
) -> dict[str, int]:
    try:
        return await request.app.state.baseball_settlement_service.settle_date(
            target_date=target_date,
            timezone=timezone,
            league=league.value,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
