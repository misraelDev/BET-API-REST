from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from app.sports.football.predictions.repository import (
    FootballPredictionRepository,
    RepositoryConflict,
)


class FakeCollection:
    def __init__(self, documents=None, *, insert_error=None):
        self.documents = list(documents or [])
        self.insert_error = insert_error
        self.indexes = []

    async def update_one(self, query, update):
        item = next(
            (doc for doc in self.documents if all(doc.get(k) == v for k, v in query.items())),
            None,
        )
        if item is None:
            return SimpleNamespace(modified_count=0)
        item.update(update["$set"])
        return SimpleNamespace(modified_count=1)

    async def insert_one(self, document):
        if self.insert_error:
            raise self.insert_error
        item = {**document, "_id": f"inserted-{len(self.documents)}"}
        self.documents.append(item)
        return SimpleNamespace(inserted_id=item["_id"])

    async def count_documents(self, query):
        return sum(
            1 for doc in self.documents
            if all(doc.get(key) == value for key, value in query.items())
        )

    async def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))


def repository(collection):
    value = FootballPredictionRepository.__new__(FootballPredictionRepository)
    value._predictions = collection
    value._evaluations = FakeCollection()
    return value


@pytest.mark.asyncio
async def test_version_insert_uses_compare_and_set_and_preserves_history():
    previous = {
        "_id": "old",
        "prediction_id": "abcdefgh",
        "version": 1,
        "version_id": "a" * 32,
        "is_current": True,
    }
    collection = FakeCollection([dict(previous)])
    stored = await repository(collection).insert_version(
        {
            "prediction_id": "abcdefgh",
            "version": 2,
            "version_id": "b" * 32,
            "is_current": True,
        },
        previous,
    )
    assert collection.documents[0]["is_current"] is False
    assert collection.documents[1]["is_current"] is True
    assert stored["version_id"] == "b" * 32


@pytest.mark.asyncio
async def test_stale_current_version_cannot_be_promoted_or_overwritten():
    previous = {
        "_id": "old",
        "prediction_id": "abcdefgh",
        "version": 1,
        "version_id": "a" * 32,
        "is_current": False,
    }
    collection = FakeCollection([dict(previous)])
    with pytest.raises(RepositoryConflict, match="cambió en paralelo"):
        await repository(collection).insert_version(
            {"prediction_id": "abcdefgh", "version": 2}, previous
        )
    assert len(collection.documents) == 1


@pytest.mark.asyncio
async def test_failed_insert_restores_previous_current_version():
    previous = {
        "_id": "old",
        "prediction_id": "abcdefgh",
        "version": 1,
        "version_id": "a" * 32,
        "is_current": True,
    }
    collection = FakeCollection(
        [dict(previous)], insert_error=DuplicateKeyError("duplicate")
    )
    with pytest.raises(RepositoryConflict):
        await repository(collection).insert_version(
            {"prediction_id": "abcdefgh", "version": 2}, previous
        )
    assert collection.documents[0]["is_current"] is True


@pytest.mark.asyncio
async def test_indexes_enforce_one_current_prediction_and_exact_evaluation_identity():
    value = FootballPredictionRepository.__new__(FootballPredictionRepository)
    value._predictions = FakeCollection()
    value._evaluations = FakeCollection()
    await value._ensure_indexes()

    prediction_indexes = {kwargs["name"]: kwargs for _, kwargs in value._predictions.indexes}
    evaluation_indexes = {kwargs["name"]: kwargs for _, kwargs in value._evaluations.indexes}
    assert prediction_indexes["prediction_idempotency"]["unique"] is True
    assert prediction_indexes["prediction_single_current"]["unique"] is True
    assert prediction_indexes["prediction_single_current"]["partialFilterExpression"] == {
        "is_current": True
    }
    assert evaluation_indexes["evaluation_version_identity"]["unique"] is True
