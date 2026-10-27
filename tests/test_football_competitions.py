import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.sports.football.competitions.models import (
    CompetitionCreate,
    CompetitionPatch,
    CompetitionType,
)
from app.sports.football.competitions.router import router
from app.sports.football.competitions.service import (
    CompetitionNotFound,
    CompetitionService,
    CompetitionUnavailable,
)
from app.sports.football.predictions.catalog import league_catalog

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def payload(**overrides):
    value = {
        "code": "copa_del_rey",
        "name": "Copa del Rey",
        "country": "España",
        "type": "cup",
        "active": True,
        "registration_available": True,
        "capabilities": {"query": True, "automatic_settlement": False},
    }
    value.update(overrides)
    return value


class FakeCompetitionRepository:
    def __init__(self, records=None):
        self.records = {item["code"]: dict(item) for item in (records or [])}
        self.migration_updates = []

    async def create(self, document):
        if document["code"] in self.records:
            raise ValueError(f"La competición code={document['code']} ya existe.")
        self.records[document["code"]] = dict(document)
        return dict(document)

    async def get(self, code):
        record = self.records.get(code)
        return dict(record) if record is not None else None

    async def list(self, query, *, skip=0, limit=100):
        records = [
            dict(item)
            for item in self.records.values()
            if all(item.get(key) == value for key, value in query.items())
        ]
        return sorted(records, key=lambda item: item["code"])[skip : skip + limit]

    async def count(self, query):
        return len(await self.list(query))

    async def patch(self, code, update):
        record = self.records.get(code)
        if record is None:
            return None
        for key, value in update.items():
            if key.startswith("capabilities."):
                capability = key.split(".", 1)[1]
                record.setdefault("capabilities", {})[capability] = value
            else:
                record[key] = value
        return dict(record)


def make_client(repository=None):
    repository = repository or FakeCompetitionRepository()
    app = FastAPI()
    app.include_router(router)
    app.state.football_competition_service = CompetitionService(
        repository, clock=lambda: NOW
    )
    return TestClient(app), repository


def test_create_get_and_filtered_list():
    client, repository = make_client()

    created = client.post("/api/v1/football/competitions", json=payload())
    retrieved = client.get("/api/v1/football/competitions/copa_del_rey")
    listed = client.get(
        "/api/v1/football/competitions?country=España&type=cup&active=true"
    )

    assert created.status_code == 201
    record = created.json()
    assert record["code"] == "copa_del_rey"
    assert record["created_at"].endswith("Z")
    assert retrieved.status_code == 200
    assert retrieved.json()["name"] == "Copa del Rey"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["code"] == "copa_del_rey"
    assert repository.records["copa_del_rey"]["code"] == "copa_del_rey"


def test_duplicate_code_and_unknown_code_validation():
    client, _ = make_client()
    client.post("/api/v1/football/competitions", json=payload())

    duplicate = client.post("/api/v1/football/competitions", json=payload())
    malformed = client.post(
        "/api/v1/football/competitions", json=payload(code="Copa del Rey")
    )
    missing = client.get("/api/v1/football/competitions/not_registered")

    assert duplicate.status_code == 409
    assert malformed.status_code == 422
    assert missing.status_code == 404


def test_patch_omitted_values_preserve_provider_configuration_and_merge_capabilities():
    client, _ = make_client()
    client.post(
        "/api/v1/football/competitions",
        json=payload(
            providers={"espn": {"competition_id": "esp.cup"}},
            capabilities={"query": True, "automatic_settlement": True},
        ),
    )

    response = client.patch(
        "/api/v1/football/competitions/copa_del_rey",
        json={"name": "Copa del Rey · edición", "capabilities": {"query": False}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["providers"]["espn"]["competition_id"] == "esp.cup"
    assert data["capabilities"] == {"query": False, "automatic_settlement": True}
    assert data["name"] == "Copa del Rey · edición"


def test_patch_rejects_null_for_non_nullable_fields_and_code_is_immutable():
    client, _ = make_client()
    client.post("/api/v1/football/competitions", json=payload())

    null_name = client.patch(
        "/api/v1/football/competitions/copa_del_rey", json={"name": None}
    )
    code_change = client.patch(
        "/api/v1/football/competitions/copa_del_rey",
        json={"code": "copa_nueva"},
    )

    assert null_name.status_code == 422
    assert code_change.status_code == 422


def test_deactivation_blocks_new_registration_but_keeps_historical_read():
    service = CompetitionService(FakeCompetitionRepository(), clock=lambda: NOW)

    async def scenario():
        created = await service.create(CompetitionCreate.model_validate(payload()))
        deactivated = await service.patch(
            created.code, CompetitionPatch.model_validate({"active": False})
        )
        historical = await service.get(created.code)
        with pytest.raises(CompetitionUnavailable):
            await service.require_registration(created.code)
        return deactivated, historical

    deactivated, historical = asyncio.run(scenario())
    assert not deactivated.active
    assert not historical.active
    assert historical.code == "copa_del_rey"


def test_migration_seeds_all_25_legacy_competition_codes():
    class FakeMongoCollection:
        def __init__(self):
            self.documents = {}

        async def update_one(self, query, update, *, upsert):
            code = query["code"]
            if code not in self.documents:
                self.documents[code] = dict(update["$setOnInsert"])
                return type("Result", (), {"upserted_id": code})()
            return type("Result", (), {"upserted_id": None})()

    async def scenario():
        mongo = FakeMongoCollection()
        repository = FakeCompetitionRepository()
        repository._collection = mongo
        repository._db = lambda: mongo

        # Exercise the actual repository migration method without a live client.
        from app.sports.football.competitions.repository import CompetitionRepository

        migrated = await CompetitionRepository.migrate_legacy_competitions(repository)
        migrated_again = await CompetitionRepository.migrate_legacy_competitions(
            repository
        )
        return mongo.documents, migrated, migrated_again

    documents, migrated, migrated_again = asyncio.run(scenario())
    assert migrated == 25
    assert migrated_again == 0
    assert {item["code"] for item in documents.values()} == {
        item["code"] for item in league_catalog()
    }
    assert "copa_del_rey" not in documents
    assert documents["liga_mx"]["code"] == "liga_mx"
    assert documents["champions_league"]["type"] == "cup"


def test_create_examples_are_distinct_cup_codes():
    copa = CompetitionCreate.model_validate(payload())
    pokal = CompetitionCreate.model_validate(
        payload(code="dfb_pokal", name="DFB-Pokal", country="Alemania")
    )
    assert copa.type == CompetitionType.CUP
    assert pokal.code == "dfb_pokal"
