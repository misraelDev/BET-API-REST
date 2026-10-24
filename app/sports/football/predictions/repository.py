"""Persistencia del histórico versionado de pronósticos y evaluaciones."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)


class RepositoryConflict(RuntimeError):
    """La escritura choca con una clave única (idempotencia o versión)."""


def ensure_utc(value: Any) -> Any:
    """Mongo devuelve datetimes naive en UTC; los modelos exigen offset."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return value


def prepare_document(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["document_id"] = str(result.pop("_id"))
    for key in ("received_at", "created_at", "updated_at", "generated_at"):
        if result.get(key) is not None:
            result[key] = ensure_utc(result[key])
    match = result.get("match")
    if isinstance(match, dict) and match.get("kickoff"):
        match["kickoff"] = ensure_utc(match["kickoff"])
    settlement = result.get("settlement")
    if isinstance(settlement, dict):
        if settlement.get("settled_at"):
            settlement["settled_at"] = ensure_utc(settlement["settled_at"])
        source = settlement.get("source")
        if isinstance(source, dict) and source.get("retrieved_at"):
            source["retrieved_at"] = ensure_utc(source["retrieved_at"])
    return result


def prepare_evaluation(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["evaluation_id"] = str(result.pop("_id"))
    if result.get("created_at") is not None:
        result["created_at"] = ensure_utc(result["created_at"])
    return result


class FootballPredictionRepository:
    """Colecciones ``football_predictions`` y ``football_prediction_evaluations``."""

    def __init__(
        self,
        uri: str,
        database: str,
        predictions_collection: str,
        evaluations_collection: str,
        required: bool = False,
    ) -> None:
        self._uri = uri.strip()
        self._database_name = database
        self._predictions_collection_name = predictions_collection
        self._evaluations_collection_name = evaluations_collection
        self._required = required
        self._client: AsyncMongoClient | None = None
        self._predictions = None
        self._evaluations = None
        self._connection_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._predictions is not None

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
                appname="sports-predictions-api",
            )
            await self._client.admin.command("ping")
            database = self._client[self._database_name]
            self._predictions = database[self._predictions_collection_name]
            self._evaluations = database[self._evaluations_collection_name]
            await self._ensure_indexes()
            logger.info(
                "mongodb.football_predictions_connected database=%s predictions=%s evaluations=%s",
                self._database_name,
                self._predictions_collection_name,
                self._evaluations_collection_name,
            )
        except PyMongoError as exc:
            self._connection_error = (
                f"MongoDB no disponible: {exc.__class__.__name__}"
            )
            if self._client:
                await self._client.close()
            self._client = None
            self._predictions = None
            self._evaluations = None
            logger.exception(
                "mongodb.football_predictions_connection_error type=%s",
                exc.__class__.__name__,
            )
            if self._required:
                raise RuntimeError(self._connection_error) from exc

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def _ensure_indexes(self) -> None:
        assert self._predictions is not None
        assert self._evaluations is not None
        await self._predictions.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="prediction_idempotency",
        )
        await self._predictions.create_index(
            [("prediction_id", ASCENDING), ("version", ASCENDING)],
            unique=True,
            name="prediction_version",
        )
        await self._predictions.create_index(
            [("prediction_id", ASCENDING), ("is_current", ASCENDING)],
            name="prediction_current",
        )
        await self._predictions.create_index(
            [("match.date", ASCENDING), ("is_current", ASCENDING)],
            name="prediction_match_date",
        )
        await self._predictions.create_index(
            [("event_id", ASCENDING), ("is_current", ASCENDING)],
            name="prediction_event",
        )
        await self._predictions.create_index(
            [("analyst", ASCENDING), ("is_current", ASCENDING)],
            name="prediction_analyst",
        )
        await self._predictions.create_index(
            [("market", ASCENDING), ("is_current", ASCENDING)],
            name="prediction_market",
        )
        await self._predictions.create_index(
            [("settlement_status", ASCENDING)],
            name="prediction_settlement_status",
        )
        await self._predictions.create_index(
            [("timing.status", ASCENDING)],
            name="prediction_timing",
        )
        await self._evaluations.create_index(
            [
                ("prediction_id", ASCENDING),
                ("version", ASCENDING),
                ("analyst", ASCENDING),
            ],
            unique=True,
            name="evaluation_identity",
        )
        await self._evaluations.create_index(
            [("prediction_id", ASCENDING), ("created_at", DESCENDING)],
            name="evaluation_prediction",
        )

    def _collection(self):
        if self._predictions is None:
            raise RuntimeError(
                self._connection_error or "Persistencia deshabilitada."
            )
        return self._predictions

    def _evaluation_collection(self):
        if self._evaluations is None:
            raise RuntimeError(
                self._connection_error or "Persistencia deshabilitada."
            )
        return self._evaluations

    async def find_by_idempotency_key(
        self, key: str
    ) -> dict[str, Any] | None:
        document = await self._collection().find_one({"idempotency_key": key})
        return prepare_document(document) if document else None

    async def get_current(self, prediction_id: str) -> dict[str, Any] | None:
        document = await self._collection().find_one(
            {"prediction_id": prediction_id, "is_current": True}
        )
        return prepare_document(document) if document else None

    async def get_version(
        self, prediction_id: str, version: int
    ) -> dict[str, Any] | None:
        document = await self._collection().find_one(
            {"prediction_id": prediction_id, "version": version}
        )
        return prepare_document(document) if document else None

    async def max_version(self, prediction_id: str) -> int:
        document = await self._collection().find_one(
            {"prediction_id": prediction_id},
            sort=[("version", DESCENDING)],
            projection={"version": 1},
        )
        return int((document or {}).get("version") or 0)

    async def list_versions(self, prediction_id: str) -> list[dict[str, Any]]:
        cursor = self._collection().find(
            {"prediction_id": prediction_id}
        ).sort("version", ASCENDING)
        documents = await cursor.to_list(length=500)
        return [prepare_document(document) for document in documents]

    async def insert_version(
        self,
        document: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        if previous is not None:
            await self._collection().update_one(
                {"_id": previous["_id"]},
                {"$set": {"is_current": False, "updated_at": now}},
            )
        try:
            result = await self._collection().insert_one(document)
        except DuplicateKeyError:
            if previous is not None:
                await self._collection().update_one(
                    {"_id": previous["_id"]},
                    {"$set": {"is_current": True}},
                )
            raise RepositoryConflict(
                "Ya existe una versión con ese prediction_id y version."
            ) from None
        stored = {**document, "_id": result.inserted_id}
        return prepare_document(stored)

    async def find_predictions(
        self,
        query: dict[str, Any],
        *,
        skip: int = 0,
        limit: int = 50,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        cursor = (
            self._collection()
            .find(query)
            .sort(sort or [("received_at", DESCENDING), ("prediction_id", ASCENDING)])
            .skip(skip)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [prepare_document(document) for document in documents]

    async def count_predictions(self, query: dict[str, Any]) -> int:
        return await self._collection().count_documents(query)

    async def update_settlement(
        self,
        version_id: str,
        settlement: dict[str, Any],
    ) -> int:
        result = await self._collection().update_one(
            {"version_id": version_id},
            {
                "$set": {
                    "settlement": settlement,
                    "settlement_status": settlement["status"],
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        return result.modified_count

    async def insert_evaluation(
        self, document: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            result = await self._evaluation_collection().insert_one(document)
        except DuplicateKeyError:
            raise RepositoryConflict(
                "Ya existe una evaluación de este analista para esa versión."
            ) from None
        stored = {**document, "_id": result.inserted_id}
        return prepare_evaluation(stored)

    async def find_evaluations(
        self,
        query: dict[str, Any],
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        cursor = (
            self._evaluation_collection()
            .find(query)
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [prepare_evaluation(document) for document in documents]

    async def count_evaluations(self, query: dict[str, Any]) -> int:
        return await self._evaluation_collection().count_documents(query)


__all__ = [
    "FootballPredictionRepository",
    "RepositoryConflict",
    "ensure_utc",
    "prepare_document",
    "prepare_evaluation",
]
