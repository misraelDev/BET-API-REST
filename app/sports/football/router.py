from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.shared.exceptions import ApiSportsError
from app.shared.pagination import set_pagination_headers
from app.shared.prediction_filters import kickoff_hour_filter
from app.sports.football.models import (
    DailyPredictionResponse,
    FootballResultsUpdateRequest,
    FootballResultsUpdateResponse,
    StoredFootballPrediction,
)

router = APIRouter(prefix="/api/v1/football", tags=["Football"])
FootballLeague = Literal["all", "liga_mx", "brasileirao"]
STORED_LEAGUE_NAMES = {
    "liga_mx": "Liga MX",
    "brasileirao": "Brasileirão Betano",
}


@router.get("/results", response_model=list[StoredFootballPrediction])
async def stored_results(
    request: Request,
    response: Response,
    target_date: date | None = Query(default=None, alias="date"),
    league: FootballLeague = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    limit: int | None = Query(default=None, ge=1, le=200, deprecated=True),
    hour: int | None = Query(default=None, ge=0, le=23),
) -> list[StoredFootballPrediction]:
    try:
        size = limit or page_size
        repository = request.app.state.prediction_repository
        query_date = target_date.isoformat() if target_date else None
        stored_league = STORED_LEAGUE_NAMES.get(league)
        filters = kickoff_hour_filter(target_date, hour) if target_date is not None and hour is not None else None
        if hour is not None and target_date is None:
            raise HTTPException(status_code=422, detail="La fecha es obligatoria para filtrar por hora.")
        total = await repository.count_predictions(
            sport="football", requested_date=query_date, league=stored_league,
            filters=filters,
        )
        results = await repository.list_predictions(
            sport="football",
            requested_date=query_date,
            league=stored_league,
            limit=size,
            offset=(page - 1) * size,
            filters=filters,
        )
        set_pagination_headers(response, total=total, page=page, page_size=size)
        return results
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/results/update", response_model=FootballResultsUpdateResponse)
async def update_results(
    payload: FootballResultsUpdateRequest,
    request: Request,
) -> FootballResultsUpdateResponse:
    try:
        fixtures = await request.app.state.football_service.client.get_fixtures(
            payload.date.isoformat(),
            "America/Mexico_City",
        )
        finals = [
            fixture for fixture in fixtures
            if fixture.get("fixture", {}).get("status", {}).get("short")
            in {"FT", "AET", "PEN"}
            and fixture.get("goals", {}).get("home") is not None
            and fixture.get("goals", {}).get("away") is not None
        ]
        summary = await request.app.state.prediction_repository.update_football_market_results(
            payload.date.isoformat(),
            finals,
        )
        return FootballResultsUpdateResponse(
            date=payload.date,
            official_fixtures=len(fixtures),
            final_fixtures=len(finals),
            **summary,
        )
    except ApiSportsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/predictions", response_model=DailyPredictionResponse)
async def daily_predictions(
    request: Request,
    target_date: date = Query(alias="date"),
    timezone: str = Query(default="America/Mexico_City"),
    league: FootballLeague = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=20),
) -> DailyPredictionResponse:
    try:
        response = await request.app.state.football_service.predict_date(
            target_date=target_date,
            timezone=timezone,
            limit=limit,
            league=league,
        )
        response.persistence = await request.app.state.prediction_repository.save_response(
            "football", response
        )
        return response
    except ApiSportsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
