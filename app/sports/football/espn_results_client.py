import asyncio
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

import httpx

from app.sports.football.predictions.catalog import ESPN_SLUGS
from app.sports.football.predictions.observation import (
    FootballObservation,
    build_observation,
)


ESPN_LEAGUES = ("mex.1", "bra.1", "concacaf.leagues.cup")
ESPN_SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


class EspnFootballResultsClient:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://site.api.espn.com/apis/site/v2/sports/soccer",
            timeout=timeout_seconds,
            headers={"Accept": "application/json", "User-Agent": "BET-API-REST/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def enrich_fixtures(
        self,
        target_date: str,
        fixtures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        events = await self._events(target_date)
        by_teams = {
            self._identity(event): event
            for event in events
            if self._identity(event)
        }
        enriched: list[dict[str, Any]] = []
        for fixture in fixtures:
            identity = self._fixture_identity(fixture)
            event = by_teams.get(identity)
            if not event:
                enriched.append(fixture)
                continue
            statistics = await self._statistics(event["league"], event["id"])
            enriched.append({**fixture, "statistics": statistics} if statistics else fixture)
        return enriched

    async def _events(self, target_date: str) -> list[dict[str, Any]]:
        date_value = target_date.replace("-", "")
        payloads = await asyncio.gather(
            *(self._get(f"/{league}/scoreboard", {"dates": date_value, "limit": 100}) for league in ESPN_LEAGUES),
            return_exceptions=True,
        )
        events: list[dict[str, Any]] = []
        for league, payload in zip(ESPN_LEAGUES, payloads, strict=True):
            if not isinstance(payload, dict):
                continue
            for event in payload.get("events") or []:
                competitors = (((event.get("competitions") or [{}])[0]).get("competitors") or [])
                home = next((item for item in competitors if item.get("homeAway") == "home"), None)
                away = next((item for item in competitors if item.get("homeAway") == "away"), None)
                if home and away:
                    events.append({
                        "id": event.get("id"),
                        "league": league,
                        "home": (home.get("team") or {}).get("displayName"),
                        "away": (away.get("team") or {}).get("displayName"),
                    })
        return events

    async def _statistics(self, league: str, event_id: str) -> dict[str, int] | None:
        payload = await self._get(f"/{league}/summary", {"event": event_id})
        teams = ((payload.get("boxscore") or {}).get("teams") or [])
        totals = {"corners": 0, "cards": 0}
        found = {"corners": 0, "cards": 0}
        for row in teams:
            values = {
                item.get("name"): item.get("displayValue")
                for item in row.get("statistics") or []
            }
            corner_value = self._number(values.get("wonCorners"))
            yellow = self._number(values.get("yellowCards"))
            red = self._number(values.get("redCards"))
            if corner_value is not None:
                totals["corners"] += corner_value
                found["corners"] += 1
            if yellow is not None and red is not None:
                totals["cards"] += yellow + red
                found["cards"] += 1
        return {
            key: value
            for key, value in totals.items()
            if found[key] == 2
        } or None

    async def get_observation(
        self,
        event_id: int,
        league_slug: str | None = None,
    ) -> FootballObservation | None:
        """Devuelve la observación verificable del partido.

        Si se conoce el ``slug`` de ESPN se consulta primero esa liga. Como
        respaldo se prueban todos los slugs soportados (útil para datos
        heredados donde solo se guardó el ``event_id``).
        """
        candidates = [league_slug] if league_slug else []
        candidates.extend(slug for slug in ESPN_SLUGS if slug not in candidates)
        payloads = await asyncio.gather(
            *(self._get(f"/{slug}/summary", {"event": event_id}) for slug in candidates),
            return_exceptions=True,
        )
        retrieved_at = datetime.now(UTC)
        for slug, payload in zip(candidates, payloads, strict=True):
            if not isinstance(payload, dict):
                continue
            observation = build_observation(
                payload,
                event_id=event_id,
                league_slug=slug,
                source_url=f"{ESPN_SITE_BASE}/{slug}/summary?event={event_id}",
                retrieved_at=retrieved_at,
            )
            if observation is not None:
                return observation
        return None

    async def get_kickoff(
        self,
        event_id: int,
        league_slug: str | None = None,
    ) -> datetime | None:
        observation = await self.get_observation(event_id, league_slug)
        return observation.kickoff if observation else None

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _identity(cls, event: dict[str, Any]) -> str:
        return f"{cls._normalize(event.get('home'))}|{cls._normalize(event.get('away'))}"

    @classmethod
    def _fixture_identity(cls, fixture: dict[str, Any]) -> str:
        teams = fixture.get("teams") or {}
        return f"{cls._normalize((teams.get('home') or {}).get('name'))}|{cls._normalize((teams.get('away') or {}).get('name'))}"

    @staticmethod
    def _normalize(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(char for char in text if not unicodedata.combining(char))
        ignored = {"fc", "cf", "ac", "club", "de", "do", "da"}
        return " ".join(token for token in re.findall(r"[a-z0-9]+", text.casefold()) if token not in ignored)

    @staticmethod
    def _number(value: Any) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
