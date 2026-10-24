import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.database.repository import PredictionRepository
from app.records.models import MANUAL_MODEL_VERSION
from app.records.router import router as records_router
from app.records.service import ManualRecordService
from app.shared.models import SportCapability
from app.sports.baseball.router import router as baseball_router
from app.sports.baseball.enrichment.schedule_client import (
    PublicBaseballScheduleClient,
)
from app.sports.baseball.enrichment.sources import BaseballPublicWebSource
from app.sports.baseball.settlement import BaseballSettlementService
from app.sports.baseball.official_results import (
    KboOfficialResultsClient,
    MlbOfficialResultsClient,
)
from app.sports.baseball.results_update import BaseballResultsUpdateService
from app.sports.football.client import ApiFootballClient
from app.sports.football.espn_results_client import EspnFootballResultsClient
from app.sports.football.football_data_client import FootballDataClient
from app.sports.football.resilient_client import ResilientFootballClient
from app.sports.football.public_web_client import PublicWebFootballClient
from app.sports.football.market_stats_client import FootballMarketStatsClient
from app.sports.football.predictions.repository import (
    FootballPredictionRepository,
)
from app.sports.football.predictions.router import (
    router as football_predictions_router,
)
from app.sports.football.predictions.service import (
    EspnKickoffResolver,
    FootballPredictionService as VersionedFootballPredictionService,
)
from app.sports.football.router import router as football_router
from app.sports.football.service import (
    FootballPredictionService as LegacyFootballPredictionService,
)
from app.sports.nba.router import router as nba_router
from app.sports.nba.service import NbaPredictionService
from app.sports.nba.public_client import PublicBasketballClient
from app.sports.tennis.router import router as tennis_router
from app.sports.tennis.client import PublicTennisClient
from app.sports.tennis.service import TennisPredictionService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("✅ api.starting name=%s version=%s", app.title, app.version)
    settings = get_settings()
    api_football_client = ApiFootballClient(
        api_key=settings.api_football_key,
        base_url=settings.api_football_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )
    football_client = ResilientFootballClient(
        primary=api_football_client,
        fallback=FootballDataClient(
            api_key=settings.football_data_api_key,
            base_url=settings.football_data_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        ),
        public_web=PublicWebFootballClient(
            timeout_seconds=settings.request_timeout_seconds,
            market_stats=FootballMarketStatsClient(
                timeout_seconds=settings.request_timeout_seconds,
                cache_ttl_seconds=max(settings.cache_ttl_seconds, 3600),
            ),
        ),
    )
    nba_client = PublicBasketballClient(
        timeout_seconds=settings.request_timeout_seconds
    )
    baseball_schedule_client = PublicBaseballScheduleClient(
        source=BaseballPublicWebSource(
            timeout_seconds=settings.web_enrichment_timeout_seconds
        ),
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )
    mlb_official_results = MlbOfficialResultsClient(
        timeout_seconds=settings.request_timeout_seconds
    )
    kbo_official_results = KboOfficialResultsClient(
        timeout_seconds=settings.request_timeout_seconds
    )

    repository = PredictionRepository(
        uri=settings.mongodb_uri,
        database=settings.mongodb_database,
        collection=settings.mongodb_collection,
        required=settings.mongodb_required,
    )
    await repository.connect()
    football_predictions_repository = FootballPredictionRepository(
        uri=settings.mongodb_uri,
        database=settings.mongodb_database,
        predictions_collection=settings.mongodb_football_predictions_collection,
        evaluations_collection=(
            settings.mongodb_football_evaluations_collection
        ),
        required=settings.mongodb_required,
    )
    await football_predictions_repository.connect()
    espn_football_results = EspnFootballResultsClient(
        timeout_seconds=settings.request_timeout_seconds
    )
    football_prediction_service = VersionedFootballPredictionService(
        football_predictions_repository,
        kickoff_resolver=(
            EspnKickoffResolver(espn_football_results)
            if settings.football_kickoff_lookup_enabled
            else None
        ),
        observation_provider=espn_football_results,
        kickoff_timeout_seconds=settings.football_kickoff_timeout_seconds,
    )
    baseball_settlement = BaseballSettlementService(
        schedule_client=baseball_schedule_client,
        repository=repository,
    )

    app.state.football_service = LegacyFootballPredictionService(football_client)
    app.state.nba_service = NbaPredictionService(nba_client)
    app.state.mlb_official_results = mlb_official_results
    app.state.kbo_official_results = kbo_official_results
    app.state.baseball_results_update = BaseballResultsUpdateService(
        mlb_results=mlb_official_results,
        kbo_results=kbo_official_results,
        repository=repository,
    )
    app.state.baseball_settlement_service = baseball_settlement
    tennis_client = PublicTennisClient(
        timeout_seconds=settings.request_timeout_seconds
    )
    app.state.tennis_service = TennisPredictionService(tennis_client)
    app.state.prediction_repository = repository
    app.state.football_prediction_repository = football_predictions_repository
    app.state.football_prediction_service = football_prediction_service
    app.state.espn_football_results = espn_football_results
    app.state.record_service = ManualRecordService(repository)
    settlement_task = None
    if settings.baseball_settlement_enabled:
        settlement_task = asyncio.create_task(
            _run_baseball_settlement_loop(
                baseball_settlement,
                settings.baseball_settlement_interval_seconds,
            )
        )

    yield

    if settlement_task:
        settlement_task.cancel()
        with suppress(asyncio.CancelledError):
            await settlement_task
    await football_client.close()
    await nba_client.close()
    await baseball_schedule_client.close()
    await mlb_official_results.close()
    await kbo_official_results.close()
    await tennis_client.close()
    await app.state.prediction_repository.close()
    await app.state.football_prediction_repository.close()
    await app.state.espn_football_results.close()


async def _run_baseball_settlement_loop(
    service: BaseballSettlementService,
    interval_seconds: int,
) -> None:
    while True:
        await asyncio.sleep(max(60, interval_seconds))
        try:
            await service.settle_date(
                target_date=date.today(),
                timezone="America/Mexico_City",
            )
        except Exception:
            logger.exception("baseball.settlement_background_failed")


app = FastAPI(
    title="BET Analytics API",
    version="1.3.1",
    description=(
        "Registro, consulta y liquidación de predicciones deportivas. "
        "El registro es manual: la API ya no calcula probabilidades."
    ),
    lifespan=lifespan,
)

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Page", "X-Page-Size", "X-Total-Pages"],
)

app.include_router(records_router)
app.include_router(football_router)
app.include_router(football_predictions_router)
app.include_router(nba_router)
app.include_router(baseball_router)
app.include_router(tennis_router)


@app.get("/health", tags=["System"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "database": (
            "connected"
            if app.state.prediction_repository.enabled
            else "disabled"
        ),
    }


@app.get(
    "/api/v1/sports",
    response_model=list[SportCapability],
    tags=["System"],
)
async def sports_catalog() -> list[SportCapability]:
    limitation = "Registro manual: la API ya no calcula probabilidades."
    return [
        SportCapability(
            sport="football",
            provider_product=(
                "API-Football + football-data.org + Liga MX public web"
            ),
            supported=True,
            endpoint="/api/v1/records",
            model_version=MANUAL_MODEL_VERSION,
            limitation=limitation,
        ),
        SportCapability(
            sport="nba",
            provider_product="ESPN public web",
            supported=True,
            endpoint="/api/v1/records",
            model_version=MANUAL_MODEL_VERSION,
            limitation=limitation,
        ),
        SportCapability(
            sport="baseball",
            provider_product="MLB public web + KBO official results",
            supported=True,
            endpoint="/api/v1/records",
            model_version=MANUAL_MODEL_VERSION,
            limitation=limitation,
        ),
        SportCapability(
            sport="tennis",
            provider_product="ESPN public scoreboard (ATP/WTA)",
            supported=True,
            endpoint="/api/v1/records",
            model_version=MANUAL_MODEL_VERSION,
            limitation=limitation,
        ),
    ]
