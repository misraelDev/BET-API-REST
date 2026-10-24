from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.shared.exceptions import ApiSportsError
from app.shared.pagination import set_pagination_headers
from app.shared.prediction_filters import kickoff_hour_filter
from app.sports.nba.models import (
    BasketballLeague, NbaResultsUpdateRequest, NbaResultsUpdateResponse,
    StoredNbaPrediction,
)

router = APIRouter(prefix="/api/v1/nba", tags=["NBA"])
LEAGUE_NAMES = {
    BasketballLeague.NBA: ("NBA",),
    BasketballLeague.WNBA: ("WNBA",),
    BasketballLeague.SUMMER_LEAGUE: (
        "NBA - Summer League", "NBA Summer League", "Summer League",
    ),
}


def _league_name(game: dict) -> str:
    league = game.get("league") or {}
    return str(league.get("name") or "") if isinstance(league, dict) else str(league)


def _matches_league(game: dict, league: BasketballLeague) -> bool:
    return league == BasketballLeague.ALL or _league_name(game) in LEAGUE_NAMES[league]


@router.get("/results", response_model=list[StoredNbaPrediction])
async def stored_results(
    request: Request, response: Response,
    target_date: date | None = Query(None, alias="date"),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    hour: int | None = Query(None, ge=0, le=23),
    league: BasketballLeague = Query(BasketballLeague.NBA),
    market: str = Query("winner"),
    min_probability: float | None = Query(None, ge=0, le=100),
):
    if hour is not None and target_date is None:
        raise HTTPException(status_code=422, detail="La fecha es obligatoria para filtrar por hora.")
    repository = request.app.state.prediction_repository
    query_date = target_date.isoformat() if target_date else None
    market_fields = {
        "handicap": "prediction.markets.handicap_confidence",
        "total": "prediction.markets.total_confidence",
    }
    if market not in {"winner", *market_fields}:
        raise HTTPException(status_code=422, detail="Mercado de básquetbol no válido.")
    filters = kickoff_hour_filter(target_date, hour) if target_date is not None and hour is not None else {}
    if min_probability is not None:
        if market == "winner":
            filters["$or"] = [
                {"prediction.predicted_result": "home", "prediction.probabilities.home": {"$gte": min_probability}},
                {"prediction.predicted_result": "away", "prediction.probabilities.away": {"$gte": min_probability}},
            ]
        else:
            filters[market_fields[market]] = {"$gte": min_probability}
    stored_league = None if league == BasketballLeague.ALL else next(iter(LEAGUE_NAMES[league]))
    try:
        total = await repository.count_predictions("nba", query_date, league=stored_league, filters=filters or None)
        rows = await repository.list_predictions(
            "nba", query_date, league=stored_league, limit=page_size,
            offset=(page - 1) * page_size, filters=filters or None,
        )
        set_pagination_headers(
            response, total=total, page=page, page_size=page_size
        )
        return rows
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/results/update", response_model=NbaResultsUpdateResponse)
async def update_results(payload: NbaResultsUpdateRequest, request: Request):
    try:
        games = await request.app.state.nba_service.client.get_games(
            payload.date.isoformat(), "America/Mexico_City"
        )
        finals = [game for game in games if _matches_league(game, payload.league) and (game.get("status") or {}).get("short") in {"FT", "AOT"}]
        summary = await request.app.state.prediction_repository.update_nba_market_results(
            payload.date.isoformat(), finals
        )
        return NbaResultsUpdateResponse(
            date=payload.date, league=payload.league.value,
            official_games=sum(_matches_league(game, payload.league) for game in games),
            final_games=len(finals), **summary
        )
    except (ApiSportsError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
