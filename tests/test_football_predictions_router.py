import asyncio
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.sports.football.predictions.router import router
from app.sports.football.predictions.service import FootballPredictionService
from test_football_predictions_service import (
    ANALYSIS_PROMPT_VERSION_ID,
    EVALUATION_PROMPT_VERSION_ID,
    FakeObservationProvider,
    FakeRepository,
    observation,
    service,
)

PREDICTION_PATH = "/api/v1/football/predictions"


def body(**overrides):
    data = {
        "idempotency_key": "http-key-0001",
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
        "sources": [{"name": "ESPN"}],
        "analyst": "ana.garcia",
        "method_version": "analista-v1",
    }
    data.update(overrides)
    return data


def make_client(repository=None, **service_overrides):
    repository = repository or FakeRepository()
    app = FastAPI()
    app.include_router(router)
    app.state.football_prediction_service = service(
        repository, **service_overrides
    )
    return TestClient(app), repository


def register(client, *items):
    return client.post(
        PREDICTION_PATH,
        json={
            "analysis_prompt_version_id": ANALYSIS_PROMPT_VERSION_ID,
            "items": list(items),
        },
    )


def test_post_batch_returns_created_items():
    client, _ = make_client()

    response = register(client, body(), body(
        idempotency_key="http-key-0002",
        market="total_goals",
        selection="over",
        line=2.5,
    ))

    assert response.status_code == 201
    data = response.json()
    assert data["total"] == 2
    assert data["created"] == 2
    assert data["replayed"] == 0
    assert data["rejected"] == 0
    assert data["received_at"].startswith("2026-10-24T17:00:00")
    assert all(item["status"] == "created" for item in data["items"])
    assert data["items"][0]["received_before_kickoff"] is True


def test_post_replay_returns_200():
    client, repository = make_client()
    register(client, body())

    response = register(client, body())

    assert response.status_code == 200
    data = response.json()
    assert data["replayed"] == 1
    assert len(repository.documents) == 1
    assert data["items"][0]["record"]["probability"] == 58.0
    assert data["items"][0]["record"]["market"] == "1x2"


def test_post_mixed_replay_and_item_conflict_returns_200_with_both_results():
    client, repository = make_client()
    register(
        client,
        body(),
        body(idempotency_key="http-key-0002", market="btts", selection="yes"),
    )
    replay = repository.documents[0]
    conflict = repository.documents[1]
    response = register(
        client,
        body(),
        body(
            idempotency_key=conflict["idempotency_key"],
            market="btts",
            selection="yes",
            probability=88,
        ),
    )
    assert response.status_code == 200
    assert response.json()["replayed"] == 1
    assert response.json()["rejected"] == 1


def test_post_conflict_returns_409():
    client, _ = make_client()
    register(client, body())

    response = register(client, body(probability=75.0))

    assert response.status_code == 409
    data = response.json()
    assert data["rejected"] == 1
    assert "cuerpo distinto" in data["items"][0]["error"]


def test_post_mixed_batch_returns_201():
    client, _ = make_client()
    register(client, body())

    response = register(
        client,
        body(),
        body(
            idempotency_key="http-key-0002",
            market="btts",
            selection="yes",
        ),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 1
    assert data["replayed"] == 1
    assert data["total"] == 2


def test_post_corner_half_is_accepted_for_registration():
    client, _ = make_client()

    response = register(
        client,
        body(
            market="corners_total",
            period="first_half",
            selection="over",
            line=8.5,
        ),
    )

    assert response.status_code == 201
    assert response.json()["created"] == 1


def test_post_missing_sources_is_422():
    client, _ = make_client()

    response = register(client, body(sources=[]))

    assert response.status_code == 422


def test_get_list_returns_envelope_and_headers():
    client, _ = make_client()
    register(client, body())

    response = client.get(
        PREDICTION_PATH,
        params={"match_date": "2026-10-24", "analyst": "ana.garcia"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["market"] == "1x2"
    assert item["settlement_status"] == "pendiente"
    assert item["timing"]["status"] == "pre_match"
    assert item["match"]["date"] == "2026-10-24"
    assert item["match"]["declared_date"] == "2026-10-24"
    assert response.headers["X-Total-Count"] == "1"
    assert response.headers["X-Page"] == "1"
    assert response.headers["X-Page-Size"] == "50"
    assert response.headers["X-Total-Pages"] == "1"


def test_get_list_accepts_filters_and_pagination():
    client, _ = make_client()
    register(
        client,
        body(prediction_id="pred0001"),
        body(
            idempotency_key="http-key-0002",
            prediction_id="pred0002",
            market="btts",
            selection="yes",
        ),
        body(
            idempotency_key="http-key-0003",
            prediction_id="pred0003",
            market="cards_total",
            selection="under",
            line=3.5,
        ),
    )

    response = client.get(
        PREDICTION_PATH,
        params={"page": 1, "page_size": 2, "timing": "pre_match"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert response.headers["X-Total-Pages"] == "2"


def test_get_list_rejects_invalid_date_range():
    client, _ = make_client()

    response = client.get(
        PREDICTION_PATH,
        params={
            "match_date_from": "2026-10-26",
            "match_date_to": "2026-10-24",
        },
    )

    assert response.status_code == 422


def test_get_list_rejects_unknown_market():
    client, _ = make_client()

    response = client.get(PREDICTION_PATH, params={"market": "assists"})

    assert response.status_code == 422


def test_get_detail_returns_versions():
    client, _ = make_client()
    register(client, body(prediction_id="abcdefgh"))

    response = client.get(f"{PREDICTION_PATH}/abcdefgh")

    assert response.status_code == 200
    data = response.json()
    assert data["prediction_id"] == "abcdefgh"
    assert data["total_versions"] == 1
    assert data["current_version"] == 1
    assert data["versions"][0]["probability"] == 58.0


def test_get_detail_unknown_returns_404():
    client, _ = make_client()

    response = client.get(f"{PREDICTION_PATH}/zzzzzzzz")

    assert response.status_code == 404


def test_get_markets_catalog():
    client, _ = make_client()

    response = client.get(f"{PREDICTION_PATH}/markets")

    assert response.status_code == 200
    data = response.json()
    assert data["rule_version"] == "football-settlement-v2"
    assert set(data["periods"]) == {"full_time", "first_half", "second_half"}
    assert set(data["settlement_statuses"]) == {
        "pendiente",
        "acertado",
        "fallado",
        "reembolso",
        "media_ganancia",
        "media_perdida",
        "anulado",
        "no_evaluable",
    }
    markets = {item["market"]: item for item in data["markets"]}
    assert len(markets) == 22
    assert markets["1x2"]["periods"] == [
        "full_time",
        "first_half",
        "second_half",
    ]
    assert markets["corners_total"]["periods"] == [
        "full_time", "first_half", "second_half"
    ]
    assert markets["asian_handicap"]["allowed_line_steps"] == [0.25]
    assert len(data["leagues"]) == 25
    saudi = next(item for item in data["leagues"] if item["code"] == "saudi_pro_league")
    assert saudi["registration_available"] is True
    assert saudi["automatic_settlement_available"] is False
    assert markets["corners_total"]["requires_line"] is True
    assert "reembolso" in markets["asian_handicap"]["settlement_rule"]
    assert any(item["code"] == "liga_mx" for item in data["leagues"])


def test_register_and_list_evaluations():
    client, _ = make_client()
    registered = register(client, body(prediction_id="abcdefgh"))
    payload = {
        "version_id": registered.json()["items"][0]["version_id"],
        "evaluation_prompt_version_id": EVALUATION_PROMPT_VERSION_ID,
        "analyst": "ana.garcia",
        "diagnosis": "El local dominó y sentenció en el segundo tiempo.",
        "learnings": ["La ventaja de localía pesó más que la forma reciente."],
        "sources": [{"name": "ESPN"}],
        "tags": ["1x2"],
    }

    created = client.post(
        f"{PREDICTION_PATH}/abcdefgh/evaluations", json=payload
    )
    duplicate = client.post(
        f"{PREDICTION_PATH}/abcdefgh/evaluations", json=payload
    )
    listed = client.get(f"{PREDICTION_PATH}/abcdefgh/evaluations")

    assert created.status_code == 201
    assert created.json()["version"] == 1
    assert duplicate.status_code == 409
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_evaluation_for_unknown_prediction_returns_404():
    client, _ = make_client()

    response = client.post(
        f"{PREDICTION_PATH}/zzzzzzzz/evaluations",
        json={
            "version_id": "0" * 32,
            "evaluation_prompt_version_id": EVALUATION_PROMPT_VERSION_ID,
            "analyst": "ana.garcia",
            "diagnosis": "No existe el pronóstico que se intenta evaluar.",
            "learnings": ["Verificar el identificador antes de evaluar."],
            "sources": [{"name": "ESPN"}],
        },
    )

    assert response.status_code == 404


def test_schema_level_validation_lists_item_index():
    client, _ = make_client()

    response = register(
        client,
        body(),
        body(idempotency_key="http-key-0002", confidence=9),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"][:3] == ["body", "items", 1]


def test_service_unavailable_returns_503():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get(PREDICTION_PATH)

    assert response.status_code == 503


def test_settlement_status_filter_and_settle_flow():
    repository = FakeRepository()
    client, _ = make_client(
        repository,
        observation_provider=FakeObservationProvider({736644: observation()}),
    )
    register(client, body(prediction_id="abcdefgh"))

    subject = FootballPredictionService(
        repository,
        observation_provider=FakeObservationProvider({736644: observation()}),
    )
    summary = asyncio.run(subject.settle_date(date(2026, 10, 24)))
    assert summary["predictions_updated"] == 1

    settled = client.get(
        PREDICTION_PATH, params={"settlement_status": "acertado"}
    )
    assert settled.status_code == 200
    assert settled.json()["total"] == 1
    assert settled.json()["items"][0]["settlement"]["status"] == "acertado"
