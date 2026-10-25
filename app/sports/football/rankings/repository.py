"""Mongo persistence for analyst-authored football ranking versions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)


class RankingRepositoryConflict(RuntimeError):
    """Idempotency or compare-and-set conflict while versioning a ranking."""


def prepare_ranking(document: dict[str, Any]) -> dict[str, Any]:
    def normalize_utc(value: Any) -> Any:
        if isinstance(value, datetime):
            # BSON dates are UTC instants. PyMongo's default tz_aware=False
            # drops tzinfo on read, so restore UTC rather than guessing a
            # display/local timezone.
            return (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            )
        if isinstance(value, dict):
            return {key: normalize_utc(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize_utc(item) for item in value]
        if isinstance(value, tuple):
            return tuple(normalize_utc(item) for item in value)
        return value

    result = normalize_utc(document)
    result["document_id"] = str(result.pop("_id"))
    return result


class FootballRankingRepository:
    def __init__(
        self,
        uri: str,
        database: str,
        collection: str = "football_rankings",
        required: bool = False,
    ) -> None:
        self._uri = uri.strip()
        self._database_name = database
        self._collection_name = collection
        self._required = required
        self._client: AsyncMongoClient | None = None
        self._collection = None
        self._connection_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._collection is not None

    async def connect(self) -> None:
        if not self._uri:
            self._connection_error = "MONGODB_URI no configurado para rankings."
            if self._required:
                raise RuntimeError(self._connection_error)
            return
        try:
            self._client = AsyncMongoClient(
                self._uri,
                serverSelectionTimeoutMS=5000,
                appname="football-analyst-rankings-api",
            )
            await self._client.admin.command("ping")
            self._collection = self._client[self._database_name][self._collection_name]
            await self._ensure_indexes()
            logger.info(
                "mongodb.football_rankings_connected database=%s collection=%s",
                self._database_name,
                self._collection_name,
            )
        except PyMongoError as exc:
            self._connection_error = (
                f"MongoDB de rankings no disponible: {exc.__class__.__name__}"
            )
            if self._client:
                await self._client.close()
            self._client = None
            self._collection = None
            if self._required:
                raise RuntimeError(self._connection_error) from exc
            logger.exception("mongodb.football_rankings_connection_error")

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def _ensure_indexes(self) -> None:
        assert self._collection is not None
        await self._collection.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="football_ranking_idempotency",
        )
        await self._collection.create_index(
            [("ranking_id", ASCENDING), ("version", ASCENDING)],
            unique=True,
            name="football_ranking_version",
        )
        await self._collection.create_index(
            [("ranking_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"is_current": True},
            name="football_ranking_single_current",
        )
        await self._collection.create_index(
            [
                ("target_date", ASCENDING),
                ("scope", ASCENDING),
                ("competition", ASCENDING),
                ("analyst", ASCENDING),
                ("ranking_type", ASCENDING),
                ("is_current", ASCENDING),
            ],
            name="football_ranking_filters",
        )

    def _db(self):
        if self._collection is None:
            raise RuntimeError(
                self._connection_error or "Persistencia de rankings deshabilitada."
            )
        return self._collection

    async def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        document = await self._db().find_one({"idempotency_key": key})
        return prepare_ranking(document) if document else None

    async def get_current(self, ranking_id: str) -> dict[str, Any] | None:
        document = await self._db().find_one(
            {"ranking_id": ranking_id, "is_current": True}
        )
        if document is None:
            return None
        result = prepare_ranking(document)
        result["_id"] = document["_id"]
        return result

    async def get_version(self, ranking_id: str, version: int) -> dict[str, Any] | None:
        document = await self._db().find_one(
            {"ranking_id": ranking_id, "version": version}
        )
        return prepare_ranking(document) if document else None

    async def get_version_by_id(
        self, ranking_id: str, version_id: str
    ) -> dict[str, Any] | None:
        document = await self._db().find_one(
            {"ranking_id": ranking_id, "version_id": version_id}
        )
        return prepare_ranking(document) if document else None

    async def list_versions(
        self, ranking_id: str, *, skip: int = 0, limit: int = 50
    ) -> list[dict[str, Any]]:
        cursor = (
            self._db()
            .find({"ranking_id": ranking_id})
            .sort("version", ASCENDING)
            .skip(skip)
            .limit(limit)
        )
        return [prepare_ranking(item) for item in await cursor.to_list(length=limit)]

    async def find_rankings(
        self,
        query: dict[str, Any],
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        cursor = (
            self._db()
            .find(query)
            .sort([("received_at", DESCENDING), ("ranking_id", ASCENDING), ("version", DESCENDING)])
            .skip(skip)
            .limit(limit)
        )
        return [prepare_ranking(item) for item in await cursor.to_list(length=limit)]

    async def count_rankings(self, query: dict[str, Any]) -> int:
        return await self._db().count_documents(query)

    async def publish(
        self,
        document: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if previous is not None:
            updated = await self._db().update_one(
                {
                    "_id": previous["_id"],
                    "ranking_id": previous["ranking_id"],
                    "version_id": previous["version_id"],
                    "is_current": True,
                },
                {"$set": {"is_current": False}},
            )
            if updated.modified_count != 1:
                raise RankingRepositoryConflict(
                    "La versión base del ranking dejó de ser vigente."
                )
        try:
            inserted = await self._db().insert_one(document)
        except DuplicateKeyError:
            if previous is not None and await self._db().count_documents(
                {"ranking_id": document["ranking_id"], "is_current": True}
            ) == 0:
                await self._db().update_one(
                    {"_id": previous["_id"], "is_current": False},
                    {"$set": {"is_current": True}},
                )
            raise RankingRepositoryConflict(
                "Conflicto de idempotencia o de versión del ranking."
            ) from None
        except Exception:
            if previous is not None and await self._db().count_documents(
                {"ranking_id": document["ranking_id"], "is_current": True}
            ) == 0:
                await self._db().update_one(
                    {"_id": previous["_id"], "is_current": False},
                    {"$set": {"is_current": True}},
                )
            raise
        return prepare_ranking({**document, "_id": inserted.inserted_id})
