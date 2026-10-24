import asyncio
import re
import unicodedata
from datetime import date
from typing import Any

from app.shared.exceptions import (
    ApiSportsDailyLimitError,
    ApiSportsError,
    ApiSportsUnavailableError,
)
from app.sports.football.client import ApiFootballClient
from app.sports.football.football_data_client import FootballDataClient
from app.sports.football.public_web_client import PublicWebFootballClient


class ResilientFootballClient:
    def __init__(
        self,
        primary: ApiFootballClient,
        fallback: FootballDataClient,
        public_web: PublicWebFootballClient,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._public_web = public_web
        self._fallback_fixture_ids: set[int] = set()
        self._public_fixture_ids: set[int] = set()
        self._daily_limit_date: date | None = None
        self._prediction_sources: dict[
            int,
            list[tuple[Any, int]],
        ] = {}

    async def close(self) -> None:
        await self._primary.close()
        await self._fallback.close()
        await self._public_web.close()

    async def get_fixtures(self, target_date: str, timezone: str) -> list[dict[str, Any]]:
        clients = [self._fallback, self._public_web]
        if self._daily_limit_date != date.today():
            clients.insert(0, self._primary)
        results = await asyncio.gather(
            *(self._safe_fixtures(client, target_date, timezone) for client in clients)
        )
        source_rows = [
            (client, fixtures)
            for client, fixtures in zip(clients, results, strict=True)
            if fixtures
        ]
        if not source_rows:
            return []

        preferred: list[dict[str, Any]] = []
        seen_identities: set[str] = set()
        for _, fixtures in source_rows:
            for fixture in fixtures:
                identity = self._identity(fixture)
                if identity not in seen_identities:
                    preferred.append(fixture)
                    seen_identities.add(identity)
        self._fallback_fixture_ids = {
            fixture["fixture"]["id"]
            for client, fixtures in source_rows
            if client is self._fallback
            for fixture in fixtures
        }
        self._public_fixture_ids = {
            fixture["fixture"]["id"]
            for client, fixtures in source_rows
            if client is self._public_web
            for fixture in fixtures
        }
        by_identity: dict[str, list[tuple[Any, int]]] = {}
        for client, fixtures in source_rows:
            for fixture in fixtures:
                by_identity.setdefault(self._identity(fixture), []).append(
                    (client, fixture["fixture"]["id"])
                )
        self._prediction_sources = {
            fixture["fixture"]["id"]: by_identity.get(self._identity(fixture), [])
            for fixture in preferred
        }
        return preferred

    async def get_current_leagues(self) -> list[dict[str, Any]]:
        if self._daily_limit_date == date.today():
            try:
                return await self._fallback.get_current_leagues()
            except ApiSportsError:
                return await self._public_web.get_current_leagues()

    async def get_fixtures_by_ids(
        self,
        fixture_ids: list[int],
        timezone: str,
    ) -> list[dict[str, Any]]:
        return await self._public_web.get_fixtures_by_ids(fixture_ids, timezone)
        try:
            return await self._primary.get_current_leagues()
        except (ApiSportsDailyLimitError, ApiSportsUnavailableError):
            self._daily_limit_date = date.today()
            try:
                return await self._fallback.get_current_leagues()
            except ApiSportsError:
                return await self._public_web.get_current_leagues()

    async def get_prediction(self, fixture_id: int) -> dict[str, Any] | None:
        sources = self._prediction_sources.get(fixture_id)
        if sources:
            results = await asyncio.gather(
                *(client.get_prediction(source_id) for client, source_id in sources),
                return_exceptions=True,
            )
            payloads = [
                item
                for item in results
                if isinstance(item, dict) and item
            ]
            if payloads:
                payload = dict(payloads[0])
                payload["_source_payloads"] = payloads
                return payload
        if fixture_id in self._fallback_fixture_ids:
            return await self._fallback.get_prediction(fixture_id)
        if fixture_id in self._public_fixture_ids:
            return await self._public_web.get_prediction(fixture_id)
        try:
            return await self._primary.get_prediction(fixture_id)
        except (ApiSportsDailyLimitError, ApiSportsUnavailableError):
            self._daily_limit_date = date.today()
            raise ApiSportsError(
                "API-Football dejo de estar disponible durante la generacion. "
                "Repite la solicitud para usar football-data.org."
            )

    async def _fallback_fixtures(
        self,
        target_date: str,
        timezone: str,
    ) -> list[dict[str, Any]]:
        try:
            fixtures = await self._fallback.get_fixtures(target_date, timezone)
        except ApiSportsError:
            fixtures = []
        self._fallback_fixture_ids = {
            fixture["fixture"]["id"]
            for fixture in fixtures
        }
        if fixtures:
            return fixtures
        fixtures = await self._public_web.get_fixtures(target_date, timezone)
        self._public_fixture_ids = {
            fixture["fixture"]["id"]
            for fixture in fixtures
        }
        return fixtures

    async def _safe_fixtures(
        self,
        client: Any,
        target_date: str,
        timezone: str,
    ) -> list[dict[str, Any]]:
        try:
            return await client.get_fixtures(target_date, timezone)
        except (ApiSportsDailyLimitError, ApiSportsUnavailableError):
            if client is self._primary:
                self._daily_limit_date = date.today()
            return []
        except ApiSportsError:
            return []

    @classmethod
    def _identity(cls, fixture: dict[str, Any]) -> str:
        teams = fixture.get("teams", {})
        return "|".join(
            (
                cls._normalize_team(teams.get("home", {}).get("name")),
                cls._normalize_team(teams.get("away", {}).get("name")),
            )
        )

    @staticmethod
    def _normalize_team(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(char for char in text if not unicodedata.combining(char))
        tokens = re.findall(r"[a-z0-9]+", text.casefold())
        ignored = {"fc", "cf", "ac", "club", "de", "do", "da"}
        return " ".join(token for token in tokens if token not in ignored)
