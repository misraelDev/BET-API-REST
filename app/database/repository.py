import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.errors import PyMongoError

from app.shared.models import (
    DailyPredictionResponse,
    PersistenceSummary,
    SportDailyPredictionResponse,
)
from app.sports.baseball.enrichment.models import EnrichmentEvidence

PredictionResponse = DailyPredictionResponse | SportDailyPredictionResponse
logger = logging.getLogger(__name__)


class PredictionRepository:
    def __init__(
        self,
        uri: str,
        database: str,
        collection: str,
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
            self._collection = self._client[self._database_name][
                self._collection_name
            ]
            await self._collection.create_index(
                [
                    ("sport", ASCENDING),
                    ("event_id", ASCENDING),
                    ("requested_date", ASCENDING),
                    ("model_version", ASCENDING),
                ],
                unique=True,
                name="prediction_identity",
            )
            await self._collection.create_index(
                [
                    ("sport", ASCENDING),
                    ("event_id", ASCENDING),
                    ("requested_date", ASCENDING),
                ],
                unique=True,
                name="tennis_prediction_identity",
                partialFilterExpression={"sport": "tennis"},
            )
            logger.info(
                "mongodb.connected database=%s collection=%s",
                self._database_name,
                self._collection_name,
            )
        except PyMongoError as exc:
            self._connection_error = f"MongoDB no disponible: {exc.__class__.__name__}"
            if self._client:
                await self._client.close()
            self._client = None
            self._collection = None
            logger.exception("mongodb.connection_error type=%s", exc.__class__.__name__)
            if self._required:
                raise RuntimeError(self._connection_error) from exc

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def save_response(
        self,
        sport: str,
        response: PredictionResponse,
    ) -> PersistenceSummary:
        if self._collection is None:
            logger.warning("mongodb.save_skipped sport=%s reason=disabled", sport)
            return PersistenceSummary(
                enabled=False,
                error=self._connection_error or "Persistencia deshabilitada.",
            )

        inserted = 0
        updated = 0
        generated_at = datetime.now(UTC)

        try:
            for prediction in response.predictions:
                raw_prediction = prediction.model_dump(mode="json")
                event_id = (
                    raw_prediction.get("fixture_id")
                    or raw_prediction.get("game_id")
                    or raw_prediction.get("match_id")
                )
                identity = {
                    "sport": sport,
                    "event_id": event_id,
                    "requested_date": response.requested_date.isoformat(),
                }
                if sport != "tennis":
                    identity["model_version"] = response.model_version
                document: dict[str, Any] = {
                    **identity,
                    "model_version": response.model_version,
                    "provider": {
                        "baseball": "MLB/KBO public web + OmniRoute",
                        "tennis": "ESPN public scoreboard",
                        "nba": "ESPN public scoreboard + standings",
                    }.get(sport, "API-Sports"),
                    "timezone": response.timezone,
                    "prediction": raw_prediction,
                    "generated_at": generated_at,
                    "updated_at": generated_at,
                }
                result = await self._collection.update_one(
                    identity,
                    {
                        "$set": document,
                        "$setOnInsert": {"created_at": generated_at},
                    },
                    upsert=True,
                )
                if result.upserted_id is not None:
                    inserted += 1
                elif result.matched_count:
                    updated += 1
        except PyMongoError as exc:
            logger.exception(
                "mongodb.save_error sport=%s inserted=%s updated=%s",
                sport,
                inserted,
                updated,
            )
            return PersistenceSummary(
                enabled=True,
                inserted=inserted,
                updated=updated,
                collection=self._collection_name,
                error=f"Error guardando predicciones: {exc.__class__.__name__}",
            )

        logger.info(
            "mongodb.save_completed sport=%s requested=%s inserted=%s updated=%s",
            sport,
            len(response.predictions),
            inserted,
            updated,
        )
        if sport == "tennis":
            await self.deduplicate_predictions("tennis")
        return PersistenceSummary(
            enabled=True,
            inserted=inserted,
            updated=updated,
            collection=self._collection_name,
        )

    async def deduplicate_predictions(self, sport: str) -> int:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")
        pipeline = [
            {"$match": {"sport": sport}},
            {"$sort": {"updated_at": -1}},
            {"$group": {
                "_id": {"event_id": "$event_id", "requested_date": "$requested_date"},
                "document_ids": {"$push": "$_id"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
        ]
        cursor = await self._collection.aggregate(pipeline)
        groups = await cursor.to_list(length=10000)
        duplicate_ids = [document_id for group in groups for document_id in group["document_ids"][1:]]
        if not duplicate_ids:
            return 0
        result = await self._collection.delete_many({"_id": {"$in": duplicate_ids}})
        logger.info("mongodb.deduplicated sport=%s deleted=%s", sport, result.deleted_count)
        return result.deleted_count

    async def save_enrichment_evidence(
        self,
        evidence: EnrichmentEvidence,
        mapped_rows: dict[int, dict[str, Any]],
    ) -> None:
        if self._client is None:
            logger.warning(
                "mongodb.enrichment_save_skipped league=%s reason=disabled",
                evidence.league,
            )
            return
        collection_name = f"{self._collection_name}_enrichment"
        collection = self._client[self._database_name][collection_name]
        identity = {
            "sport": "baseball",
            "league": evidence.league,
            "source_url": evidence.source_url,
            "fetched_at": evidence.fetched_at,
        }
        document = {
            **identity,
            "source_name": evidence.source_name,
            "extraction_method": evidence.extraction_method,
            "teams_requested": evidence.teams_requested,
            "teams_mapped": evidence.teams_mapped,
            "mapped_rows": {str(key): value for key, value in mapped_rows.items()},
            "created_at": datetime.now(UTC),
        }
        try:
            await collection.insert_one(document)
            logger.info(
                "mongodb.enrichment_saved league=%s teams=%s collection=%s",
                evidence.league,
                len(mapped_rows),
                collection_name,
            )
        except PyMongoError:
            logger.exception(
                "mongodb.enrichment_save_error league=%s",
                evidence.league,
            )

    async def settle_baseball_predictions(
        self,
        requested_date: str,
        final_games: dict[int, dict[str, Any]],
    ) -> dict[str, int]:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")

        summary = {
            "final_games": len(final_games),
            "matched": 0,
            "settled": 0,
        }
        if not final_games:
            return summary

        query = {
            "sport": "baseball",
            "requested_date": requested_date,
            "event_id": {"$in": list(final_games)},
        }
        documents = await self._collection.find(query).to_list(length=500)
        summary["matched"] = len(documents)
        settled_at = datetime.now(UTC)
        for document in documents:
            game = final_games.get(int(document["event_id"]))
            if game is None:
                continue
            settlement = self._build_baseball_settlement(
                document["prediction"],
                game,
                settled_at,
            )
            await self._collection.update_one(
                {"_id": document["_id"]},
                {
                    "$set": {
                        "settlement": settlement,
                        "status": settlement["outcome"],
                        "updated_at": settled_at,
                    }
                },
            )
            summary["settled"] += 1
        logger.info(
            "mongodb.settlement_completed date=%s matched=%s settled=%s",
            requested_date,
            summary["matched"],
            summary["settled"],
        )
        return summary

    async def update_baseball_market_results(
        self,
        requested_date: str,
        league: str,
        final_games: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")

        query = {
            "sport": "baseball",
            "requested_date": requested_date,
            "prediction.league": {"$regex": f"^{re.escape(league)}$", "$options": "i"},
        }
        documents = await self._collection.find(query).to_list(length=100)
        document_index = {
            (
                self._normalize_team(document["prediction"].get("home_team", "")),
                self._normalize_team(document["prediction"].get("away_team", "")),
            ): document
            for document in documents
        }
        matched = 0
        updated = 0
        not_found: list[str] = []
        settled_at = datetime.now(UTC)
        for game in final_games:
            key = (
                self._normalize_team(game["home_team"]),
                self._normalize_team(game["away_team"]),
            )
            document = document_index.get(key)
            if document is None:
                not_found.append(f'{game["away_team"]} vs {game["home_team"]}')
                continue
            matched += 1
            settlement = self._build_baseball_settlement(
                document["prediction"],
                {
                    "scores": {
                        "home": game["home_score"],
                        "away": game["away_score"],
                    }
                },
                settled_at,
            )
            result = await self._collection.update_one(
                {"_id": document["_id"]},
                {
                    "$set": {
                        "settlement": settlement,
                        "updated_at": settled_at,
                    }
                },
            )
            updated += result.modified_count
        logger.info(
            "mongodb.market_results_updated date=%s league=%s matched=%s updated=%s missing=%s",
            requested_date,
            league,
            matched,
            updated,
            len(not_found),
        )
        return {
            "predictions_matched": matched,
            "predictions_updated": updated,
            "not_found": not_found,
        }

    @staticmethod
    def _normalize_team(value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value).encode(
            "ascii", "ignore"
        ).decode()
        normalized = re.sub(r"[^a-z0-9]", "", ascii_value.casefold())
        aliases = {
            "samsunglions": "samsung",
            "doosanbears": "doosan",
            "ktwiz": "kt",
            "ktwizsuwon": "kt",
            "lottegiants": "lotte",
            "ncdinos": "nc",
            "ssglanders": "ssg",
            "kiwoomheroes": "kiwoom",
            "kiatigers": "kia",
            "lgtwins": "lg",
            "hanwhaeagles": "hanwha",
        }
        return aliases.get(normalized, normalized)

    @staticmethod
    def _build_baseball_settlement(
        prediction: dict[str, Any],
        game: dict[str, Any],
        settled_at: datetime,
    ) -> dict[str, Any]:
        home_score = int(game["scores"]["home"])
        away_score = int(game["scores"]["away"])
        if home_score == away_score:
            actual_winner = "push"
        else:
            actual_winner = "home" if home_score > away_score else "away"
        winner_outcome = (
            "push"
            if actual_winner == "push"
            else (
                "won"
                if prediction.get("predicted_result") == actual_winner
                else "lost"
            )
        )

        markets = prediction.get("markets") or {}
        handicap_outcome = PredictionRepository._settle_handicap(
            prediction,
            markets,
            home_score,
            away_score,
        )
        total_outcome = PredictionRepository._settle_total(
            markets,
            home_score + away_score,
        )
        moneyline_units = PredictionRepository._outcome_units(winner_outcome)
        handicap_units = PredictionRepository._outcome_units(handicap_outcome)
        total_units = PredictionRepository._outcome_units(total_outcome)
        return {
            "game_status": "FT",
            "outcome": winner_outcome,
            "actual_winner": actual_winner,
            "home_score": home_score,
            "away_score": away_score,
            "handicap_outcome": handicap_outcome,
            "total_outcome": total_outcome,
            "moneyline_units": moneyline_units,
            "handicap_units": handicap_units,
            "total_units": total_units,
            "net_units": sum(
                value
                for value in (moneyline_units, handicap_units, total_units)
                if value is not None
            ),
            "settled_at": settled_at,
        }

    @staticmethod
    def _outcome_units(outcome: str | None, stake: int = 100) -> int | None:
        if outcome == "won":
            return stake
        if outcome == "lost":
            return -stake
        if outcome == "push":
            return 0
        return None

    @staticmethod
    def _settle_handicap(
        prediction: dict[str, Any],
        markets: dict[str, Any],
        home_score: int,
        away_score: int,
    ) -> str | None:
        team = markets.get("handicap_team")
        line = markets.get("handicap_line")
        if team is None or line is None:
            return None
        if team == prediction.get("home_team"):
            adjusted = home_score + float(line) - away_score
        elif team == prediction.get("away_team"):
            adjusted = away_score + float(line) - home_score
        else:
            return None
        return "won" if adjusted > 0 else "lost" if adjusted < 0 else "push"

    @staticmethod
    def _settle_total(
        markets: dict[str, Any],
        actual_total: int,
    ) -> str | None:
        pick = markets.get("total_pick")
        line = markets.get("total_line")
        if pick is None or line is None:
            return None
        difference = actual_total - float(line)
        if difference == 0:
            return "push"
        won = (pick == "over" and difference > 0) or (
            pick == "under" and difference < 0
        )
        return "won" if won else "lost"

    async def list_predictions(
        self,
        sport: str,
        requested_date: str | None = None,
        league: str | None = None,
        limit: int = 50,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")

        query: dict[str, Any] = {"sport": sport}
        if requested_date:
            query["requested_date"] = requested_date
        if league and league != "all":
            query["prediction.league"] = {
                "$regex": f"^{league}$",
                "$options": "i",
            }
        if filters:
            query.update(filters)

        logger.info(
            "mongodb.query sport=%s date=%s league=%s limit=%s",
            sport,
            requested_date or "all",
            league or "all",
            limit,
        )
        cursor = self._collection.find(query).sort("updated_at", -1)
        if offset:
            cursor = cursor.skip(offset)
        cursor = cursor.limit(limit)
        documents = await cursor.to_list(length=limit)
        for document in documents:
            document["document_id"] = str(document.pop("_id"))
        logger.info(
            "mongodb.query_completed sport=%s count=%s",
            sport,
            len(documents),
        )
        preview = json.dumps(
            documents[:1],
            ensure_ascii=True,
            default=str,
        )
        logger.info(
            "mongodb.query_payload sport=%s preview=%s",
            sport,
            preview[:2000],
        )
        return documents

    async def count_predictions(
        self,
        sport: str,
        requested_date: str | None = None,
        league: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> int:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")
        query: dict[str, Any] = {"sport": sport}
        if requested_date:
            query["requested_date"] = requested_date
        if league and league != "all":
            query["prediction.league"] = {
                "$regex": f"^{league}$",
                "$options": "i",
            }
        if filters:
            query.update(filters)
        return await self._collection.count_documents(query)

    async def baseball_dashboard_stats(
        self,
        league: str | None = None,
        date_from: str | None = None,
    ) -> dict[str, Any]:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")
        query: dict[str, Any] = {
            "sport": "baseball",
            "settlement": {"$ne": None},
        }
        if league and league != "all":
            query["prediction.league"] = {
                "$regex": f"^{re.escape(league)}$",
                "$options": "i",
            }
        if date_from:
            query["requested_date"] = {"$gte": date_from}
        documents = await self._collection.find(query).to_list(length=5000)
        return self._aggregate_baseball_stats(documents)

    async def update_football_market_results(
        self,
        requested_date: str,
        final_fixtures: list[dict[str, Any]],
    ) -> dict[str, int]:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")
        fixtures = {
            int(item["fixture"]["id"]): item
            for item in final_fixtures
        }
        documents = await self._collection.find(
            {
                "sport": "football",
                "requested_date": requested_date,
                "event_id": {"$in": list(fixtures)},
            }
        ).to_list(length=100)
        updated = 0
        settled_at = datetime.now(UTC)
        for document in documents:
            fixture = fixtures[int(document["event_id"])]
            settlement = self._build_football_settlement(
                document["prediction"],
                fixture,
                settled_at,
            )
            result = await self._collection.update_one(
                {"_id": document["_id"]},
                {"$set": {"settlement": settlement, "updated_at": settled_at}},
            )
            updated += result.modified_count
        return {
            "predictions_matched": len(documents),
            "predictions_updated": updated,
        }

    async def update_tennis_market_results(
        self, requested_date: str, final_matches: list[dict[str, Any]]
    ) -> dict[str, int]:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")
        matches = {int(match["id"]): match for match in final_matches}
        documents = await self._collection.find({
            "sport": "tennis", "requested_date": requested_date,
            "event_id": {"$in": list(matches)},
        }).to_list(length=500)
        updated = 0
        settled_at = datetime.now(UTC)
        for document in documents:
            settlement = self._build_tennis_settlement(
                document["prediction"], matches[int(document["event_id"])], settled_at
            )
            result = await self._collection.update_one(
                {"_id": document["_id"]},
                {"$set": {"settlement": settlement, "updated_at": settled_at}},
            )
            updated += result.modified_count
        return {"predictions_matched": len(documents), "predictions_updated": updated}

    async def update_nba_market_results(
        self, requested_date: str, games: list[dict[str, Any]]
    ) -> dict[str, int]:
        if self._collection is None:
            raise RuntimeError(self._connection_error or "Persistencia deshabilitada.")
        finals = {int(game["id"]): game for game in games if game.get("id") is not None}
        documents = await self._collection.find({
            "sport": "nba", "requested_date": requested_date,
            "event_id": {"$in": list(finals)},
        }).to_list(length=500)
        updated = 0
        settled_at = datetime.now(UTC)
        for document in documents:
            game = finals[int(document["event_id"])]
            scores = game.get("scores") or {}
            home_score = self._nba_score(scores.get("home"))
            away_score = self._nba_score(scores.get("away") or scores.get("visitors"))
            if home_score is None or away_score is None:
                continue
            settlement = self._build_nba_settlement(
                document["prediction"], home_score, away_score, settled_at
            )
            result = await self._collection.update_one(
                {"_id": document["_id"]},
                {"$set": {"settlement": settlement, "updated_at": settled_at}},
            )
            updated += result.modified_count
        return {"predictions_matched": len(documents), "predictions_updated": updated}

    @staticmethod
    def _nba_score(value: Any) -> float | None:
        if isinstance(value, dict):
            value = value.get("total") or value.get("points")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_nba_settlement(
        prediction: dict[str, Any], home_score: float, away_score: float,
        settled_at: datetime,
    ) -> dict[str, Any]:
        home_won = home_score > away_score
        predicted_home = prediction.get("predicted_result") == "home"
        winner_outcome = "won" if home_won == predicted_home else "lost"
        markets = prediction.get("markets") or {}
        handicap_team = markets.get("handicap_team")
        handicap_line = markets.get("handicap_line")
        handicap_outcome = None
        if handicap_team and handicap_line is not None:
            team_score = home_score if handicap_team == prediction.get("home_team") else away_score
            opponent_score = away_score if handicap_team == prediction.get("home_team") else home_score
            adjusted = team_score + float(handicap_line) - opponent_score
            handicap_outcome = "push" if adjusted == 0 else ("won" if adjusted > 0 else "lost")
        total_line = markets.get("total_line")
        total_pick = markets.get("total_pick")
        total_outcome = None
        if total_line is not None and total_pick:
            difference = home_score + away_score - float(total_line)
            total_outcome = "push" if difference == 0 else (
                "won" if (total_pick == "over" and difference > 0) or (total_pick == "under" and difference < 0) else "lost"
            )
        outcomes = {
            "winner": {"outcome": winner_outcome, "units": PredictionRepository._outcome_units(winner_outcome)},
            "handicap": {"outcome": handicap_outcome, "units": PredictionRepository._outcome_units(handicap_outcome)},
            "total": {"outcome": total_outcome, "units": PredictionRepository._outcome_units(total_outcome)},
        }
        return {
            "settled_at": settled_at, "home_score": home_score, "away_score": away_score,
            "markets": outcomes,
            "net_units": sum(item["units"] for item in outcomes.values() if item["units"] is not None),
        }

    @staticmethod
    def _build_tennis_settlement(
        prediction: dict[str, Any], match: dict[str, Any], settled_at: datetime
    ) -> dict[str, Any]:
        competitors = match.get("competitors") or []
        by_id = {str(item.get("id")): item for item in competitors}
        winner = next((item for item in competitors if item.get("winner")), None)
        winner_name = ((winner or {}).get("athlete") or {}).get("displayName", "")
        markets = prediction.get("markets") or {}
        results: dict[str, dict[str, Any]] = {}
        winner_market = markets.get("winner") or {}
        winner_outcome = None
        if winner_market.get("available") and winner_market.get("selection"):
            winner_outcome = "won" if winner_market["selection"] == winner_name else "lost"
        results["winner"] = {"outcome": winner_outcome, "units": PredictionRepository._outcome_units(winner_outcome)}

        handicap = markets.get("set_handicap") or {}
        handicap_outcome = None
        if handicap.get("available") and handicap.get("selection") and handicap.get("line") is not None:
            selected_id = prediction.get("player_one_id") if handicap["selection"] == prediction.get("player_one") else prediction.get("player_two_id")
            selected = by_id.get(str(selected_id), {})
            opponent = next((item for item in competitors if item is not selected), {})
            selected_sets = sum(int(bool(row.get("winner"))) for row in selected.get("linescores") or [])
            opponent_sets = sum(int(bool(row.get("winner"))) for row in opponent.get("linescores") or [])
            adjusted = selected_sets + float(handicap["line"])
            handicap_outcome = "won" if adjusted > opponent_sets else "lost" if adjusted < opponent_sets else "push"
        results["set_handicap"] = {"outcome": handicap_outcome, "units": PredictionRepository._outcome_units(handicap_outcome)}

        total_market = markets.get("total_games") or {}
        total_outcome = None
        actual_games = sum(float(row.get("value") or 0) for item in competitors for row in item.get("linescores") or [])
        if total_market.get("available") and total_market.get("line") is not None:
            difference = actual_games - float(total_market["line"])
            selection = total_market.get("selection")
            total_outcome = "push" if difference == 0 else "won" if ((selection == "Más" and difference > 0) or (selection == "Menos" and difference < 0)) else "lost"
        results["total_games"] = {"outcome": total_outcome, "units": PredictionRepository._outcome_units(total_outcome)}

        exact = markets.get("exact_sets") or {}
        exact_outcome = None
        actual_score = ""
        if winner:
            loser = next((item for item in competitors if item is not winner), {})
            winner_sets = sum(int(bool(row.get("winner"))) for row in winner.get("linescores") or [])
            loser_sets = sum(int(bool(row.get("winner"))) for row in loser.get("linescores") or [])
            actual_score = f"{winner_name} {winner_sets}-{loser_sets}"
        if exact.get("available") and exact.get("selection"):
            exact_outcome = "won" if exact["selection"] == actual_score else "lost"
        results["exact_sets"] = {"outcome": exact_outcome, "units": PredictionRepository._outcome_units(exact_outcome)}
        return {
            "game_status": "FT", "winner": winner_name, "actual_games": actual_games,
            "actual_sets": actual_score, "markets": results,
            "net_units": sum(item["units"] for item in results.values() if item["units"] is not None),
            "settled_at": settled_at,
        }

    @staticmethod
    def _build_football_settlement(
        prediction: dict[str, Any],
        fixture: dict[str, Any],
        settled_at: datetime,
    ) -> dict[str, Any]:
        home_score = int(fixture["goals"]["home"])
        away_score = int(fixture["goals"]["away"])
        actual = "draw" if home_score == away_score else (
            "home" if home_score > away_score else "away"
        )
        winner_outcome = (
            "won" if prediction.get("predicted_result") == actual else "lost"
        )
        markets = prediction.get("markets") or {}
        results: dict[str, dict[str, Any]] = {
            "winner": {
                "outcome": winner_outcome,
                "units": PredictionRepository._outcome_units(winner_outcome),
            }
        }
        handicap = markets.get("handicap") or {}
        handicap_outcome = None
        if handicap.get("available") and handicap.get("selection"):
            selected_score = (
                home_score
                if handicap["selection"] == prediction.get("home_team")
                else away_score
            )
            opponent_score = (
                away_score
                if handicap["selection"] == prediction.get("home_team")
                else home_score
            )
            adjusted = selected_score + float(handicap.get("line") or 0)
            handicap_outcome = (
                "won" if adjusted > opponent_score
                else "lost" if adjusted < opponent_score
                else "push"
            )
        double = markets.get("double_chance") or {}
        double_outcome = None
        if double.get("available"):
            selection = str(double.get("selection", ""))
            accepted = (
                (actual == "home" and prediction.get("home_team") in selection)
                or (actual == "away" and prediction.get("away_team") in selection)
                or (actual == "draw" and "empate" in selection.casefold())
            )
            double_outcome = "won" if accepted else "lost"
        goals = markets.get("goals") or {}
        goals_outcome = None
        if goals.get("available") and goals.get("line") is not None:
            difference = home_score + away_score - float(goals["line"])
            goals_outcome = "push" if difference == 0 else (
                "won"
                if (
                    (goals.get("selection") == "Más" and difference > 0)
                    or (goals.get("selection") == "Menos" and difference < 0)
                )
                else "lost"
            )
        for key, outcome in (
            ("handicap", handicap_outcome),
            ("double_chance", double_outcome),
            ("goals", goals_outcome),
            ("corners", None),
            ("cards", None),
        ):
            results[key] = {
                "outcome": outcome,
                "units": PredictionRepository._outcome_units(outcome),
            }
        return {
            "game_status": "FT",
            "home_score": home_score,
            "away_score": away_score,
            "markets": results,
            "net_units": sum(
                item["units"]
                for item in results.values()
                if item["units"] is not None
            ),
            "settled_at": settled_at,
        }

    @staticmethod
    def _aggregate_baseball_stats(
        documents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        markets = {
            "moneyline": {"label": "Moneyline", "won": 0, "lost": 0, "push": 0, "net_units": 0},
            "handicap": {"label": "Run line", "won": 0, "lost": 0, "push": 0, "net_units": 0},
            "total": {"label": "Más / menos", "won": 0, "lost": 0, "push": 0, "net_units": 0},
        }
        daily: dict[str, dict[str, int]] = {}
        league_totals: dict[str, dict[str, int]] = {}
        recent: list[dict[str, Any]] = []
        for document in documents:
            settlement = document.get("settlement") or {}
            prediction = document.get("prediction") or {}
            requested_date = str(document.get("requested_date", ""))
            league = str(prediction.get("league", "Unknown")).upper()
            day = daily.setdefault(
                requested_date,
                {"net_units": 0, "won": 0, "lost": 0, "push": 0, "bets": 0, "predictions": 0},
            )
            league_row = league_totals.setdefault(
                league,
                {"net_units": 0, "bets": 0, "predictions": 0},
            )
            day["predictions"] += 1
            league_row["predictions"] += 1
            for key, outcome_field, units_field in (
                ("moneyline", "outcome", "moneyline_units"),
                ("handicap", "handicap_outcome", "handicap_units"),
                ("total", "total_outcome", "total_units"),
            ):
                outcome = settlement.get(outcome_field)
                units = settlement.get(units_field)
                if outcome not in {"won", "lost", "push"}:
                    continue
                markets[key][outcome] += 1
                markets[key]["net_units"] += int(units or 0)
                league_row["bets"] += 1
                league_row["net_units"] += int(units or 0)
                day["net_units"] += int(units or 0)
                day["bets"] += 1
                day[outcome] += 1
            recent.append(
                {
                    "date": requested_date,
                    "league": league,
                    "away_team": prediction.get("away_team", ""),
                    "home_team": prediction.get("home_team", ""),
                    "net_units": int(settlement.get("net_units", 0)),
                }
            )
        market_rows = []
        for key, row in markets.items():
            decisive = row["won"] + row["lost"]
            market_rows.append(
                {
                    "market": key,
                    **row,
                    "hit_rate": round(row["won"] / decisive * 100, 1)
                    if decisive
                    else 0.0,
                }
            )
        won = sum(row["won"] for row in markets.values())
        lost = sum(row["lost"] for row in markets.values())
        push = sum(row["push"] for row in markets.values())
        decisive = won + lost
        return {
            "summary": {
                "settled_predictions": len(documents),
                "evaluated_bets": won + lost + push,
                "won": won,
                "lost": lost,
                "push": push,
                "hit_rate": round(won / decisive * 100, 1) if decisive else 0.0,
                "net_units": sum(row["net_units"] for row in markets.values()),
            },
            "markets": market_rows,
            "daily": [
                {"date": key, **value}
                for key, value in sorted(daily.items())
            ],
            "leagues": [
                {"league": key, **value}
                for key, value in sorted(league_totals.items())
            ],
            "recent": sorted(
                recent,
                key=lambda row: row["date"],
                reverse=True,
            )[:10],
        }
