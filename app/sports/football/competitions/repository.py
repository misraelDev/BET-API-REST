"""MongoDB persistence and idempotent migration for football competitions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)

CUP_CODES = frozenset(
    {
        "leagues_cup",
        "champions_league",
        "europa_league",
        "conference_league",
        "libertadores",
        "sudamericana",
        "afc_champions_league_elite",
        "afc_champions_league_two",
    }
)


def prepare_competition(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result.pop("_id", None)
    for field in ("created_at", "updated_at"):
        value = result.get(field)
        if isinstance(value, datetime):
            result[field] = (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            )
    return result


class CompetitionRepository:
    def __init__(
        self,
        uri: str,
        database: str,
        collection: str = "football_competitions",
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
            self._connection_error = "MONGODB_URI no configurado para competiciones."
            if self._required:
                raise RuntimeError(self._connection_error)
            return
        try:
            self._client = AsyncMongoClient(
                self._uri,
                serverSelectionTimeoutMS=5000,
                appname="football-competitions-api",
            )
            await self._client.admin.command("ping")
            self._collection = self._client[self._database_name][self._collection_name]
            await self._collection.create_index(
                [("code", ASCENDING)], unique=True, name="football_competition_code"
            )
            await self.migrate_legacy_competitions()
            logger.info(
                "mongodb.football_competitions_connected database=%s collection=%s",
                self._database_name,
                self._collection_name,
            )
        except PyMongoError as exc:
            self._connection_error = (
                f"MongoDB de competiciones no disponible: {exc.__class__.__name__}"
            )
            if self._client:
                await self._client.close()
            self._client = None
            self._collection = None
            if self._required:
                raise RuntimeError(self._connection_error) from exc
            logger.exception("mongodb.football_competitions_connection_error")

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    def _db(self):
        if self._collection is None:
            raise RuntimeError(
                self._connection_error or "Persistencia de competiciones deshabilitada."
            )
        return self._collection

    async def migrate_legacy_competitions(self) -> int:
        """Upsert the 25 historic codes, only setting defaults on first migration."""
        from app.sports.football.predictions.catalog import league_catalog

        now = datetime.now(UTC)
        migrated = 0
        for legacy in league_catalog():
            code = str(legacy["code"])
            source = str(legacy.get("source") or "")
            provider_id = source.removeprefix("ESPN (").removesuffix(")")
            document = {
                "code": code,
                "name": str(legacy["name"]),
                "country": str(legacy["country"]),
                "type": "cup" if code in CUP_CODES else "league",
                "active": True,
                "registration_available": bool(
                    legacy.get("registration_available", True)
                ),
                "providers": (
                    {"espn": {"competition_id": provider_id}}
                    if provider_id
                    else None
                ),
                "capabilities": {
                    "query": True,
                    "automatic_settlement": bool(
                        legacy.get("automatic_settlement_available", False)
                    ),
                },
                "created_at": now,
                "updated_at": now,
            }
            result = await self._db().update_one(
                {"code": code}, {"$setOnInsert": document}, upsert=True
            )
            if result.upserted_id is not None:
                migrated += 1
        return migrated

    async def create(self, document: dict[str, Any]) -> dict[str, Any]:
        try:
            await self._db().insert_one(document)
        except DuplicateKeyError as exc:
            raise ValueError(
                f"La competición code={document['code']} ya existe."
            ) from exc
        stored = await self._db().find_one({"code": document["code"]})
        return prepare_competition(stored)

    async def get(self, code: str) -> dict[str, Any] | None:
        document = await self._db().find_one({"code": code})
        return prepare_competition(document) if document else None

    async def list(
        self, query: dict[str, Any], *, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        cursor = (
            self._db()
            .find(query)
            .sort([("country", ASCENDING), ("name", ASCENDING)])
            .skip(skip)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [prepare_competition(item) for item in documents]

    async def count(self, query: dict[str, Any]) -> int:
        return await self._db().count_documents(query)

    async def patch(self, code: str, update: dict[str, Any]) -> dict[str, Any] | None:
        update["updated_at"] = datetime.now(UTC)
        result = await self._db().find_one_and_update(
            {"code": code}, {"$set": update}, return_document=True
        )
        return prepare_competition(result) if result else None
