from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from app.shared.pagination import set_pagination_headers
from app.shared.prediction_filters import kickoff_hour_filter

from app.sports.tennis.models import (
    StoredTennisPrediction,
    TennisMatchCountResponse,
    TennisResultsUpdateRequest,
    TennisResultsUpdateResponse,
    TennisTour,
)

router = APIRouter(prefix="/api/v1/tennis", tags=["Tennis"])


@router.get("/matches/count", response_model=TennisMatchCountResponse)
async def match_count(
    request: Request,
    target_date: date = Query(alias="date"),
    timezone: str = "America/Mexico_City",
    tour: TennisTour = TennisTour.ALL,
):
    try:
        total = await request.app.state.tennis_service.count_matches(
            target_date, timezone, tour
        )
        return TennisMatchCountResponse(
            date=target_date, tour=tour.value, matches_found=total
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No fue posible consultar la cartelera de tenis: {exc}",
        ) from exc


@router.get("/results", response_model=list[StoredTennisPrediction])
async def results(
    request: Request,
    response: Response,
    target_date: date | None = Query(None, alias="date"),
    tour: TennisTour = TennisTour.ALL,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200, deprecated=True),
    hour: int | None = Query(None, ge=0, le=23),
    market: str | None = Query(None),
    min_probability: float | None = Query(None, ge=0, le=100),
):
    try:
        size = limit or page_size
        repository = request.app.state.prediction_repository
        query_date = target_date.isoformat() if target_date else None
        filters: dict = {}
        market_fields = {
            "winner": "winner",
            "set_handicap": "set_handicap",
            "total_games": "total_games",
            "exact_sets": "exact_sets",
        }
        if market and market not in market_fields:
            raise HTTPException(status_code=422, detail="Mercado de tenis no válido.")
        if min_probability is not None:
            selected_market = market or "winner"
            filters[
                f"prediction.markets.{market_fields[selected_market]}.probability"
            ] = {"$gte": min_probability}
        if hour is not None:
            if target_date is None:
                raise HTTPException(
                    status_code=422,
                    detail="La fecha es obligatoria para filtrar por hora.",
                )
            filters.update(kickoff_hour_filter(target_date, hour))
        total = await repository.count_predictions(
            sport="tennis", requested_date=query_date, league=tour.value,
            filters=filters,
        )
        rows = await repository.list_predictions(
            sport="tennis", requested_date=query_date, league=tour.value,
            limit=size, offset=(page - 1) * size, filters=filters,
        )
        set_pagination_headers(response, total=total, page=page, page_size=size)
        return rows
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/results/update", response_model=TennisResultsUpdateResponse)
async def update_results(payload: TennisResultsUpdateRequest, request: Request):
    try:
        finals = await request.app.state.tennis_service.final_results(
            payload.date, "America/Mexico_City", payload.tour
        )
        summary = await request.app.state.prediction_repository.update_tennis_market_results(
            payload.date.isoformat(), finals
        )
        return TennisResultsUpdateResponse(
            date=payload.date, tour=payload.tour.value,
            official_matches=len(finals), final_matches=len(finals), **summary,
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"No fue posible actualizar tenis: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
