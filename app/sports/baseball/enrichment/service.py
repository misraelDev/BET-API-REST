import logging
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from app.database.repository import PredictionRepository
from app.integrations.omniroute import OmniRouteClient
from app.sports.baseball.enrichment.models import (
    EnrichmentEvidence,
    ExtractedLeagueStats,
)
from app.sports.baseball.enrichment.sources import BaseballPublicWebSource

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract baseball team statistics from public webpage text.
Return one JSON object only, with this exact shape:
{"teams":[{"team_name":"string","games_played":null,"wins":null,"losses":null,
"runs_for":null,"runs_against":null,"source_excerpt":"short exact evidence"}]}
Only include requested teams found in the supplied text. Use null when a value is not
explicitly supported. Never estimate, calculate, complete, or invent a statistic.
Numbers must describe the current season table shown in the supplied content."""


class BaseballWebEnrichmentService:
    def __init__(
        self,
        source: BaseballPublicWebSource,
        mapper: OmniRouteClient,
        repository: PredictionRepository,
        enabled: bool = True,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._repository = repository
        self._enabled = enabled

    async def close(self) -> None:
        await self._source.close()
        await self._mapper.close()

    async def build_fallback(
        self,
        games: list[dict[str, Any]],
    ) -> tuple[dict[int, dict[str, Any]], list[str]]:
        if not self._enabled or not games:
            return {}, []

        league_groups: dict[str, list[dict[str, Any]]] = {}
        for game in games:
            league = str(game.get("league", {}).get("name", "")).upper()
            if league in {"MLB", "KBO"}:
                league_groups.setdefault(league, []).append(game)

        combined: dict[int, dict[str, Any]] = {}
        warnings: list[str] = []
        for league, league_games in league_groups.items():
            try:
                mapped, evidence = await self._enrich_league(league, league_games)
                combined.update(mapped)
                await self._repository.save_enrichment_evidence(evidence, mapped)
                warnings.append(
                    f"Standings completados desde {evidence.source_name}: "
                    f"{len(mapped)} equipos mapeados."
                )
            except Exception as exc:
                logger.exception("web_enrichment.failed league=%s", league)
                detail = str(exc).strip()[:180] or exc.__class__.__name__
                warnings.append(
                    f"No se pudo enriquecer {league} desde su pagina publica: "
                    f"{exc.__class__.__name__}: {detail}."
                )
        return combined, warnings

    async def _enrich_league(
        self,
        league: str,
        games: list[dict[str, Any]],
    ) -> tuple[dict[int, dict[str, Any]], EnrichmentEvidence]:
        teams = self._game_teams(games)
        source_name, source_url, page_text = await self._source.fetch_league_page(league)
        requested_names = [team["name"] for team in teams.values()]
        if league == "MLB":
            extracted_teams = self._source.parse_mlb_standings(
                page_text,
                requested_names,
            )
            extraction_method = "html+parser"
            if not extracted_teams:
                raise ValueError("El parser MLB no encontro equipos solicitados.")
        else:
            extracted_teams = []
            extraction_method = "html+llm"
            for start in range(0, len(requested_names), 10):
                batch = requested_names[start : start + 10]
                mapped_payload = await self._mapper.map_json(
                    SYSTEM_PROMPT,
                    (
                        f"League: {league}\nRequested teams: "
                        f"{', '.join(batch)}\n\nPublic page text:\n{page_text}"
                    ),
                )
                extracted_teams.extend(
                    ExtractedLeagueStats.model_validate(mapped_payload).teams
                )
        rows: dict[int, dict[str, Any]] = {}
        mapped_names: list[str] = []
        for item in extracted_teams:
            match = self._match_team(item.team_name, teams)
            if match is None:
                continue
            team_id, canonical_name = match
            rows[team_id] = {
                "team": {"id": team_id, "name": canonical_name},
                "games": {"played": item.games_played},
                "win": {"total": item.wins},
                "loss": {"total": item.losses},
                "points": {
                    "for": item.runs_for,
                    "against": item.runs_against,
                },
                "_enrichment": {
                    "source_url": source_url,
                    "source_excerpt": item.source_excerpt,
                    "estimated": False,
                },
            }
            mapped_names.append(canonical_name)

        evidence = EnrichmentEvidence(
            league=league,
            source_name=source_name,
            source_url=source_url,
            fetched_at=datetime.now(UTC),
            teams_requested=requested_names,
            teams_mapped=mapped_names,
            extraction_method=extraction_method,
        )
        logger.info(
            "web_enrichment.completed league=%s requested=%s mapped=%s",
            league,
            len(requested_names),
            len(rows),
        )
        return rows, evidence

    @staticmethod
    def _game_teams(games: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        teams: dict[int, dict[str, Any]] = {}
        for game in games:
            for team in game.get("teams", {}).values():
                if isinstance(team, dict) and team.get("id") is not None:
                    teams[int(team["id"])] = {
                        "id": int(team["id"]),
                        "name": str(team.get("name", team["id"])),
                    }
        return teams

    @staticmethod
    def _match_team(
        extracted_name: str,
        teams: dict[int, dict[str, Any]],
    ) -> tuple[int, str] | None:
        normalized = extracted_name.casefold().strip()
        candidates = [
            (
                SequenceMatcher(
                    None,
                    normalized,
                    team["name"].casefold().strip(),
                ).ratio(),
                team_id,
                team["name"],
            )
            for team_id, team in teams.items()
        ]
        if not candidates:
            return None
        score, team_id, name = max(candidates)
        return (team_id, name) if score >= 0.72 else None
