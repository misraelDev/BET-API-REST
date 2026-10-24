from types import SimpleNamespace

import pytest

from app.prompts.repository import PromptRepository
from app.sports.football.predictions.repository import RepositoryConflict


class Cursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, key, direction):
        self.documents.sort(key=lambda item: item[key], reverse=direction < 0)
        return self

    async def to_list(self, length):
        return self.documents[:length]


class FakeCollection:
    def __init__(self):
        self.documents = []
        self.indexes = []

    async def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))

    async def find_one(self, query):
        return next(
            (
                item for item in self.documents
                if all(item.get(key) == value for key, value in query.items())
            ),
            None,
        )

    def find(self, query):
        documents = [
            item for item in self.documents
            if all(item.get(key) == value for key, value in query.items())
        ]
        return Cursor(documents)

    async def update_one(self, query, update):
        item = await self.find_one(query)
        if item is None:
            return SimpleNamespace(modified_count=0)
        item.update(update["$set"])
        return SimpleNamespace(modified_count=1)

    async def insert_one(self, document):
        item = {**document, "_id": f"id-{len(self.documents) + 1}"}
        self.documents.append(item)
        return SimpleNamespace(inserted_id=item["_id"])

    async def count_documents(self, query):
        return sum(
            all(item.get(key) == value for key, value in query.items())
            for item in self.documents
        )


def make_repository(collection):
    repo = PromptRepository.__new__(PromptRepository)
    repo._collection = collection
    return repo


@pytest.mark.asyncio
async def test_prompt_repository_preserves_versions_and_compare_and_set():
    collection = FakeCollection()
    repo = make_repository(collection)
    first = await repo.publish(
        {
            "sport": "football",
            "prompt_type": "analysis",
            "version": 1,
            "version_id": "a" * 32,
            "is_current": True,
            "prompt": "v1",
        },
        None,
    )
    previous = await repo.get_current("football", "analysis")
    second = await repo.publish(
        {
            "sport": "football",
            "prompt_type": "analysis",
            "version": 2,
            "version_id": "b" * 32,
            "is_current": True,
            "prompt": "v2",
        },
        previous,
    )

    history = await repo.list_versions("football", "analysis")
    assert first["version_id"] == "a" * 32
    assert second["version_id"] == "b" * 32
    assert [item["version"] for item in history] == [1, 2]
    assert [item["is_current"] for item in history] == [False, True]


@pytest.mark.asyncio
async def test_prompt_repository_rejects_stale_cas():
    collection = FakeCollection()
    repo = make_repository(collection)
    await repo.publish(
        {
            "sport": "nba",
            "prompt_type": "evaluation",
            "version": 1,
            "version_id": "a" * 32,
            "is_current": True,
        },
        None,
    )
    stale = {
        "_id": "wrong-id",
        "version_id": "a" * 32,
        "is_current": True,
    }
    with pytest.raises(RepositoryConflict, match="base dejó de ser vigente"):
        await repo.publish(
            {
                "sport": "nba",
                "prompt_type": "evaluation",
                "version": 2,
                "version_id": "b" * 32,
                "is_current": True,
            },
            stale,
        )
    assert len(collection.documents) == 1


@pytest.mark.asyncio
async def test_prompt_repository_defines_unique_version_and_current_indexes():
    collection = FakeCollection()
    repo = make_repository(collection)
    await repo._ensure_indexes()
    indexes = {options["name"]: options for _, options in collection.indexes}
    assert indexes["prompt_identity_version"]["unique"] is True
    assert indexes["prompt_version_id"]["unique"] is True
    assert indexes["prompt_single_current"]["unique"] is True
    assert indexes["prompt_single_current"]["partialFilterExpression"] == {
        "is_current": True
    }
