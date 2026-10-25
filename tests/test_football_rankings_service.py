import asyncio
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.sports.football.rankings.models import FootballRankingBatchCreate
from app.sports.football.rankings.router import router
from app.sports.football.rankings.service import (
    RankingNotFound,
    RankingReferenceNotFound,
    RankingService,
)

RECEIVED_AT = datetime(2026, 10, 24, 17, 0, tzinfo=UTC)
PROMPT_VERSION_ID = "3be3ffee060a4f01b01057c32f5ae197"
PREDICTION_ID = "pred-liga-mx-736644-home"
PREDICTION_VERSION_ID = "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f"
RANKINGS_PATH = "/api/v1/football/rankings"


class FakePromptRepository:
    def __init__(self, known=None):
        self.known = known or {PROMPT_VERSION_ID: 2}

    async def get_version_by_id(self, sport, prompt_type, version_id):
        version = self.known.get(version_id) if sport == "football" and prompt_type == "analysis" else None
        if version is None:
            return None
        return {
            "prompt_id": "football.analysis",
            "sport": sport,
            "prompt_type": prompt_type,
            "version": version,
            "version_id": version_id,
        }


class FakePredictionRepository:
    def __init__(self):
        self.versions = {
            (PREDICTION_ID, PREDICTION_VERSION_ID): {
                "prediction_id": PREDICTION_ID,
                "version_id": PREDICTION_VERSION_ID,
                "event_id": 736644,
                "match": {"league": "liga_mx"},
                "market": "1x2",
                "period": "full_time",
                "selection": "home",
                "line": None,
                "team": None,
                "player_id": None,
            }
        }

    async def get_version_by_id(self, prediction_id, version_id):
        return self.versions.get((prediction_id, version_id))


def _matches(document, query):
    for key, expected in query.items():
        if document.get(key) != expected:
            return False
    return True


class FakeRankingRepository:
    """In-memory repository with the same semantics the service relies on."""

    def __init__(self):
        self.documents = []
        self.writes = 0

    @staticmethod
    def _prepare(document):
        return dict(document)

    async def find_by_idempotency_key(self, key):
        for document in self.documents:
            if document["idempotency_key"] == key:
                return self._prepare(document)
        return None

    async def get_current(self, ranking_id):
        for document in self.documents:
            if document["ranking_id"] == ranking_id and document["is_current"]:
                return self._prepare(document)
        return None

    async def get_version(self, ranking_id, version):
        for document in self.documents:
            if document["ranking_id"] == ranking_id and document["version"] == version:
                return self._prepare(document)
        return None

    async def get_version_by_id(self, ranking_id, version_id):
        for document in self.documents:
            if (
                document["ranking_id"] == ranking_id
                and document["version_id"] == version_id
            ):
                return self._prepare(document)
        return None

    async def list_versions(self, ranking_id, *, skip=0, limit=50):
        versions = sorted(
            (
                document
                for document in self.documents
                if document["ranking_id"] == ranking_id
            ),
            key=lambda document: document["version"],
        )
        return [self._prepare(item) for item in versions[skip : skip + limit]]

    async def find_rankings(self, query, *, skip=0, limit=50):
        matched = [
            document for document in self.documents if _matches(document, query)
        ]
        matched.sort(key=lambda document: document["ranking_id"])
        matched.sort(key=lambda document: document["version"], reverse=True)
        matched.sort(key=lambda document: document["received_at"], reverse=True)
        return [self._prepare(item) for item in matched[skip : skip + limit]]

    async def count_rankings(self, query):
        return sum(1 for document in self.documents if _matches(document, query))

    async def publish(self, document, previous):
        if previous is not None:
            for stored in self.documents:
                if (
                    stored["ranking_id"] == previous["ranking_id"]
                    and stored["version_id"] == previous["version_id"]
                ):
                    stored["is_current"] = False
        stored = dict(document)
        stored["_id"] = f"doc-{len(self.documents) + 1}"
        stored["document_id"] = stored["_id"]
        stored.pop("_id", None)
        self.documents.append(stored)
        self.writes += 1
        return dict(stored)


def row(**overrides):
    value = {
        "position": 1,
        "league": "liga_mx",
        "event_id": 736644,
        "home_team": "Pumas UNAM",
        "away_team": "Necaxa",
        "market": "1x2",
        "period": "full_time",
        "selection": "home",
        "estimate_status": "estimated",
        "probability": 58,
        "confidence": 4,
        "rationale": "Selección enviada por el analista.",
    }
    value.update(overrides)
    return value


def item(**overrides):
    value = {
        "idempotency_key": "ranking-key-0001",
        "target_date": "2026-10-24",
        "timezone": "America/Mexico_City",
        "analyst": "ana.garcia",
        "scope": "league",
        "competition": "liga_mx",
        "ranking_type": "winner",
        "sort_criterion": "probabilidad_descendente",
        "sort_direction": "desc",
        "analysis_prompt_version_id": PROMPT_VERSION_ID,
        "method_version": "analista-v2",
        "generated_at": "2026-10-24T10:30:00-06:00",
        "coverage": {
            "matches_considered": 4,
            "matches_with_rows": 1,
            "coverage_complete": False,
            "limitations": ["Cobertura parcial."],
        },
        "rows": [row()],
    }
    value.update(overrides)
    return value


def build(repository=None, **overrides):
    repository = repository or FakeRankingRepository()
    service = RankingService(
        repository,
        prompt_repository=overrides.pop("prompt_repository", FakePromptRepository()),
        prediction_repository=overrides.pop(
            "prediction_repository", FakePredictionRepository()
        ),
        clock=lambda: RECEIVED_AT,
        **overrides,
    )
    return service, repository


def register(service, *items):
    return asyncio.run(
        service.register_batch(
            FootballRankingBatchCreate.model_validate({"items": list(items)})
        )
    )


def make_client(repository=None):
    service, repository = build(repository)
    app = FastAPI()
    app.include_router(router)
    app.state.football_ranking_service = service
    return TestClient(app), repository


def test_batch_creates_rankings_and_preserves_submitted_order():
    service, repository = build()
    result = register(
        service,
        item(
            rows=[
                row(position=1, selection="home"),
                row(
                    position=2,
                    event_id=736645,
                    home_team="Atlas",
                    away_team="Puebla",
                    selection="away",
                    estimate_status="not_estimated",
                    probability=None,
                    confidence=None,
                    no_estimate_reason="Datos insuficientes.",
                ),
            ]
        ),
    )

    assert (result.created, result.replayed, result.rejected) == (1, 0, 0)
    stored = result.items[0].ranking
    assert [entry.selection for entry in stored.rows] == ["home", "away"]
    assert stored.rows[1].probability is None
    assert stored.received_at == RECEIVED_AT
    assert stored.version == 1
    assert repository.writes == 1


def test_replayed_idempotency_key_does_not_write_again():
    service, repository = build()
    first = register(service, item())
    second = register(service, item())

    assert first.items[0].status == "created"
    assert second.items[0].status == "replayed"
    assert second.items[0].version == first.items[0].version
    assert repository.writes == 1


def test_same_idempotency_key_with_other_content_is_rejected():
    service, _ = build()
    register(service, item())
    result = register(service, item(analyst="otro.analista"))

    assert result.items[0].status == "rejected"
    assert "contenido distinto" in result.items[0].error


def test_new_revision_supersedes_previous_without_rewriting_rows():
    service, repository = build()
    first = register(service, item(ranking_id="rank-liga-mx-winner"))
    second = register(
        service,
        item(
            ranking_id="rank-liga-mx-winner",
            idempotency_key="ranking-key-0002",
            rows=[row(position=1, probability=64, confidence=5)],
        ),
    )

    assert second.items[0].status == "created"
    assert second.items[0].version == 2
    assert second.items[0].ranking.supersedes_version_id == first.items[0].version_id
    assert [doc["is_current"] for doc in repository.documents] == [False, True]
    assert repository.documents[0]["rows"][0]["probability"] == 58


def test_new_revision_must_keep_ranking_identity():
    service, _ = build()
    register(service, item(ranking_id="rank-liga-mx-winner"))
    result = register(
        service,
        item(
            ranking_id="rank-liga-mx-winner",
            idempotency_key="ranking-key-0002",
            analyst="otro.analista",
        ),
    )

    assert result.items[0].status == "rejected"
    assert "identidad del ranking" in result.items[0].error


def test_unknown_prompt_reference_rejects_whole_batch_before_writing():
    service, repository = build(prompt_repository=FakePromptRepository(known={}))
    with pytest.raises(RankingReferenceNotFound):
        register(service, item(analysis_prompt_version_id="f" * 32))
    assert repository.writes == 0


def test_mismatched_prediction_reference_is_rejected():
    service, repository = build()
    with pytest.raises(RankingReferenceNotFound, match="no coincide"):
        register(
            service,
            item(
                rows=[
                    row(
                        selection="away",
                        prediction_id=PREDICTION_ID,
                        version_id=PREDICTION_VERSION_ID,
                    )
                ]
            ),
        )
    assert repository.writes == 0


def test_matching_prediction_reference_is_stored_without_altering_rows():
    service, _ = build()
    result = register(
        service,
        item(
            rows=[
                row(
                    prediction_id=PREDICTION_ID,
                    version_id=PREDICTION_VERSION_ID,
                )
            ]
        ),
    )

    stored = result.items[0].ranking
    assert stored.rows[0].prediction_id == PREDICTION_ID
    assert stored.rows[0].version_id == PREDICTION_VERSION_ID
    assert stored.rows[0].probability == 58


def test_list_applies_filters_and_pagination_without_writing():
    service, repository = build()
    register(
        service,
        item(),
        item(
            idempotency_key="ranking-key-0002",
            scope="general",
            competition=None,
            ranking_type="overall_high_confidence",
            rows=[
                row(position=1, league="mls", event_id=1),
                row(position=2, league="liga_mx", event_id=2, selection="away"),
            ],
        ),
        item(
            idempotency_key="ranking-key-0003",
            target_date="2026-10-25",
        ),
    )
    before = repository.writes

    page = asyncio.run(
        service.list_rankings(
            target_date=date(2026, 10, 24),
            scope="general",
            page=1,
            page_size=1,
        )
    )

    assert page.total == 1
    assert page.timezone == "America/Mexico_City"
    assert page.items[0].ranking_type == "overall_high_confidence"
    assert repository.writes == before


def test_get_returns_exact_revision_and_history_without_writing():
    service, repository = build()
    register(service, item(ranking_id="rank-liga-mx-winner"))
    second = register(
        service,
        item(
            ranking_id="rank-liga-mx-winner",
            idempotency_key="ranking-key-0002",
            rows=[row(position=1, probability=70, confidence=5)],
        ),
    )
    before = repository.writes

    detail = asyncio.run(
        service.get_ranking(
            "rank-liga-mx-winner",
            version=1,
            history_page_size=1,
        )
    )

    assert detail.ranking.version == 1
    assert detail.ranking.rows[0].probability == 58
    assert detail.current_version == 2
    assert detail.total_versions == 2
    assert [entry.version for entry in detail.versions] == [1]
    assert detail.ranking.version_id != second.items[0].version_id
    assert repository.writes == before


def test_missing_ranking_is_not_generated():
    service, repository = build()
    with pytest.raises(RankingNotFound):
        asyncio.run(service.get_ranking("rank-inexistente"))
    assert repository.writes == 0


def test_post_returns_201_then_200_for_replay():
    client, _ = make_client()
    first = client.post(RANKINGS_PATH, json={"items": [item()]})
    second = client.post(RANKINGS_PATH, json={"items": [item()]})

    assert first.status_code == 201
    assert first.json()["created"] == 1
    assert second.status_code == 200
    assert second.json()["replayed"] == 1


def test_post_invalid_order_returns_422_and_writes_nothing():
    client, repository = make_client()
    invalid = item(rows=[row(position=2)])

    response = client.post(RANKINGS_PATH, json={"items": [invalid]})

    assert response.status_code == 422
    assert repository.writes == 0


def test_get_without_date_uses_today_in_mexico_city():
    client, _ = make_client()
    response = client.get(RANKINGS_PATH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == "America/Mexico_City"
    assert payload["total"] == 0
    assert payload["items"] == []
    assert payload["date"] == datetime.now(
        __import__("zoneinfo").ZoneInfo("America/Mexico_City")
    ).date().isoformat()


def test_get_detail_returns_404_for_unknown_ranking():
    client, _ = make_client()
    response = client.get(f"{RANKINGS_PATH}/rank-inexistente")
    assert response.status_code == 404


def test_get_detail_rejects_version_and_version_id_together():
    client, _ = make_client()
    register_via_client = client.post(
        RANKINGS_PATH, json={"items": [item(ranking_id="rank-liga-mx-winner")]}
    )
    assert register_via_client.status_code == 201

    response = client.get(
        f"{RANKINGS_PATH}/rank-liga-mx-winner",
        params={"version": 1, "version_id": PREDICTION_VERSION_ID},
    )

    assert response.status_code == 422
