from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.shared.exceptions import ApiSportsError
from app.shared.pagination import set_pagination_headers
from app.shared.prediction_filters import kickoff_hour_filter
from app.sports.football.espn_results_client import EspnFootballResultsClient
from app.sports.football.models import (
    FootballResultsUpdateError,
    FootballResultsUpdateRequest,
    FootballResultsUpdateResponse,
    StoredFootballPrediction,
)

router = APIRouter(prefix="/api/v1/football", tags=["Football"])
FootballLeague = Literal["all", "liga_mx", "brasileirao", "leagues_cup"]
STORED_LEAGUE_NAMES = {
    "liga_mx": "Liga MX",
    "brasileirao": "Brasileirão Betano",
    "leagues_cup": "Leagues Cup",
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
    market: str = Query(default="winner"),
    min_probability: float | None = Query(default=None, ge=0, le=100),
) -> list[StoredFootballPrediction]:
    try:
        size = limit or page_size
        repository = request.app.state.prediction_repository
        query_date = target_date.isoformat() if target_date else None
        stored_league = STORED_LEAGUE_NAMES.get(league)
        market_fields = {
            "handicap": "prediction.markets.handicap.probability",
            "double_chance": "prediction.markets.double_chance.probability",
            "goals": "prediction.markets.goals.probability",
            "corners": "prediction.markets.corners.probability",
            "cards": "prediction.markets.cards.probability",
        }
        if market not in {"winner", *market_fields}:
            raise HTTPException(status_code=422, detail="Mercado de fútbol no válido.")
        filters = kickoff_hour_filter(target_date, hour) if target_date is not None and hour is not None else {}
        if min_probability is not None:
            if market == "winner":
                filters["$or"] = [
                    {"prediction.predicted_result": result, f"prediction.probabilities.{result}": {"$gte": min_probability}}
                    for result in ("home", "draw", "away")
                ]
            else:
                filters[market_fields[market]] = {"$gte": min_probability}
        if hour is not None and target_date is None:
            raise HTTPException(status_code=422, detail="La fecha es obligatoria para filtrar por hora.")
        total = await repository.count_predictions(
            sport="football", requested_date=query_date, league=stored_league,
            filters=filters or None,
        )
        results = await repository.list_predictions(
            sport="football",
            requested_date=query_date,
            league=stored_league,
            limit=size,
            offset=(page - 1) * size,
            filters=filters or None,
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
    errors: list[FootballResultsUpdateError] = []
    new_summary: dict = {
        "predictions_matched": 0,
        "predictions_settled": 0,
        "predictions_updated": 0,
        "predictions_pending": 0,
        "unmatched_event_ids": [],
        "errors": [],
    }
    prediction_service = getattr(
        request.app.state, "football_prediction_service", None
    )
    if prediction_service is None:
        errors.append(
            FootballResultsUpdateError(
                stage="football_predictions",
                message="Servicio de pronósticos no configurado.",
            )
        )
    else:
        try:
            new_summary = await prediction_service.settle_date(payload.date)
            errors.extend(new_summary.get("errors") or [])
        except RuntimeError as exc:
            errors.append(
                FootballResultsUpdateError(
                    stage="football_predictions",
                    message=str(exc),
                )
            )
    try:
        repository = request.app.state.prediction_repository
        documents = await repository.list_predictions(
            sport="football",
            requested_date=payload.date.isoformat(),
            limit=200,
        )
        fixture_ids = list({int(item["event_id"]) for item in documents})
        fixtures = await request.app.state.football_service.client.get_fixtures_by_ids(
            fixture_ids,
            "America/Mexico_City",
        )
        espn = getattr(request.app.state, "espn_football_results", None)
        close_espn = espn is None
        if espn is None:
            espn = EspnFootballResultsClient()
        try:
            fixtures = await espn.enrich_fixtures(payload.date.isoformat(), fixtures)
        finally:
            if close_espn:
                await espn.close()
        finals = [
            fixture for fixture in fixtures
            if fixture.get("fixture", {}).get("status", {}).get("short")
            in {"FT", "AET", "PEN"}
            and fixture.get("goals", {}).get("home") is not None
            and fixture.get("goals", {}).get("away") is not None
        ]
        summary = await repository.update_football_market_results(
            payload.date.isoformat(),
            finals,
        )
        final_ids = {int(fixture["fixture"]["id"]) for fixture in finals}
        predicted_ids = {int(item["event_id"]) for item in documents}
        unmatched = list(new_summary.get("unmatched_event_ids") or [])
        for event_id in sorted(predicted_ids - final_ids):
            value = str(event_id)
            if value not in unmatched:
                unmatched.append(value)
        return FootballResultsUpdateResponse(
            date=payload.date,
            source=(
                "ESPN public summary (site.api.espn.com) + "
                "TheSportsDB public schedule"
            ),
            official_fixtures=len(fixtures),
            final_fixtures=len(finals),
            predictions_matched=summary["predictions_matched"],
            predictions_updated=summary["predictions_updated"],
            football_predictions_matched=new_summary["predictions_matched"],
            football_predictions_settled=new_summary["predictions_settled"],
            football_predictions_updated=new_summary["predictions_updated"],
            football_predictions_pending=new_summary["predictions_pending"],
            unmatched_event_ids=unmatched,
            fixtures_without_predictions=sorted(final_ids - predicted_ids),
            errors=errors,
        )
    except ApiSportsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
