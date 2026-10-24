"""Mongo persistence for immutable prompt revisions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.prompts.models import make_prompt_id
from app.sports.football.predictions.repository import RepositoryConflict

logger = logging.getLogger(__name__)


def prepare_prompt(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["document_id"] = str(result.pop("_id"))
    result.setdefault(
        "prompt_id", make_prompt_id(result["sport"], result["prompt_type"])
    )
    for field in ("created_at", "updated_at"):
        value = result.get(field)
        if isinstance(value, datetime):
            result[field] = (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            )
    return result


class PromptRepository:
    """Repository for the dedicated Mongo collection named ``prompts``."""

    def __init__(
        self,
        uri: str,
        database: str,
        collection: str = "prompts",
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

    @property
    def error(self) -> str | None:
        return self._connection_error

    async def connect(self) -> None:
        if not self._uri:
            self._connection_error = "MONGODB_URI no configurado."
            if self._required:
                raise RuntimeError(self._connection_error)
            return
        try:
            self._client = AsyncMongoClient(
                self._uri,
                serverSelectionTimeoutMS=5000,
                appname="sports-analyst-prompts-api",
            )
            await self._client.admin.command("ping")
            self._collection = self._client[self._database_name][
                self._collection_name
            ]
            await self._ensure_indexes()
            logger.info(
                "mongodb.prompts_connected database=%s collection=%s",
                self._database_name,
                self._collection_name,
            )
        except PyMongoError as exc:
            self._connection_error = (
                f"MongoDB no disponible para prompts: {exc.__class__.__name__}"
            )
            if self._client:
                await self._client.close()
            self._client = None
            self._collection = None
            logger.exception(
                "mongodb.prompts_connection_error type=%s",
                exc.__class__.__name__,
            )
            if self._required:
                raise RuntimeError(self._connection_error) from exc

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def _ensure_indexes(self) -> None:
        assert self._collection is not None
        await self._collection.create_index(
            [
                ("sport", ASCENDING),
                ("prompt_type", ASCENDING),
                ("version", ASCENDING),
            ],
            unique=True,
            name="prompt_identity_version",
        )
        await self._collection.create_index(
            [("sport", ASCENDING), ("prompt_type", ASCENDING)],
            unique=True,
            partialFilterExpression={"is_current": True},
            name="prompt_single_current",
        )
        await self._collection.create_index(
            [("sport", ASCENDING), ("prompt_type", ASCENDING), ("created_at", DESCENDING)],
            name="prompt_history",
        )
        await self._collection.create_index(
            [("version_id", ASCENDING)],
            unique=True,
            name="prompt_version_id",
        )

    def _db(self):
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia de prompts deshabilitada.")
        return self._collection

    async def get_current(
        self, sport: str, prompt_type: str
    ) -> dict[str, Any] | None:
        document = await self._db().find_one(
            {"sport": sport, "prompt_type": prompt_type, "is_current": True}
        )
        if document is None:
            return None
        result = prepare_prompt(document)
        # Keep Mongo's native id only for the internal compare-and-set.
        result["_id"] = document["_id"]
        return result

    async def get_version(
        self, sport: str, prompt_type: str, version: int
    ) -> dict[str, Any] | None:
        document = await self._db().find_one(
            {"sport": sport, "prompt_type": prompt_type, "version": version}
        )
        return prepare_prompt(document) if document else None

    async def get_version_by_id(
        self, sport: str, prompt_type: str, version_id: str
    ) -> dict[str, Any] | None:
        document = await self._db().find_one(
            {"sport": sport, "prompt_type": prompt_type, "version_id": version_id}
        )
        return prepare_prompt(document) if document else None

    async def list_versions(
        self, sport: str, prompt_type: str
    ) -> list[dict[str, Any]]:
        cursor = self._db().find(
            {"sport": sport, "prompt_type": prompt_type}
        ).sort("version", ASCENDING)
        return [prepare_prompt(document) for document in await cursor.to_list(length=500)]

    async def publish(
        self,
        document: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if previous is not None:
            changed = await self._db().update_one(
                {
                    "_id": previous["_id"],
                    "version_id": previous["version_id"],
                    "is_current": True,
                },
                {"$set": {"is_current": False, "updated_at": datetime.now(UTC)}},
            )
            if changed.modified_count != 1:
                raise RepositoryConflict(
                    "La versión base dejó de ser vigente; vuelve a consultar el prompt."
                )
        try:
            inserted = await self._db().insert_one(document)
        except DuplicateKeyError:
            if previous is not None and await self._db().count_documents(
                {
                    "sport": document["sport"],
                    "prompt_type": document["prompt_type"],
                    "is_current": True,
                }
            ) == 0:
                await self._db().update_one(
                    {"_id": previous["_id"], "is_current": False},
                    {"$set": {"is_current": True}},
                )
            raise RepositoryConflict(
                "Ya existe esa versión; consulta el historial y reintenta con la base vigente."
            ) from None
        except Exception:
            if previous is not None and await self._db().count_documents(
                {
                    "sport": document["sport"],
                    "prompt_type": document["prompt_type"],
                    "is_current": True,
                }
            ) == 0:
                await self._db().update_one(
                    {"_id": previous["_id"], "is_current": False},
                    {"$set": {"is_current": True}},
                )
            raise
        return prepare_prompt({**document, "_id": inserted.inserted_id})
