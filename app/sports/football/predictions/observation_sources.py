"""Resolución de resultados en varias fuentes públicas.

La liquidación no depende de que el ``event_id`` sea de ESPN. Primero se
consulta la fuente declarada en ``event_source`` y, si esa fuente no responde
o no reconoce el partido, se busca el mismo encuentro por equipos y fecha en
las demás fuentes configuradas.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Protocol

from app.sports.football.predictions.observation import FootballObservation

logger = logging.getLogger(__name__)


class SourceObservationProvider(Protocol):
    """Adaptador de una fuente que puede verificar un partido."""

    async def get_observation(
        self, event_id: int, league_slug: str | None = None
    ) -> FootballObservation | None: ...

    async def find_observation(
        self,
        home_team: str,
        away_team: str,
        target_date: date,
        league_slug: str | None = None,
    ) -> FootballObservation | None: ...


class MultiSourceObservationResolver:
    """Consulta la fuente declarada y cae a las demás si no hay resultado."""

    def __init__(
        self,
        providers: dict[str, SourceObservationProvider],
        fallback_order: tuple[str, ...] = (
            "thesportsdb",
            "365scores",
            "espn",
        ),
    ) -> None:
        self._providers = dict(providers)
        self._fallback_order = tuple(fallback_order)

    async def resolve(
        self,
        *,
        event_source: str,
        event_id: int,
        league_slug: str | None,
        home_team: str,
        away_team: str,
        match_date: date,
    ) -> FootballObservation | None:
        declared = self._providers.get(event_source)
        if declared is not None:
            try:
                observation = await declared.get_observation(
                    event_id, league_slug
                )
            except Exception as exc:  # noqa: BLE001 - se intenta el respaldo
                logger.warning(
                    "football.predictions.source_failed provider=%s "
                    "event_id=%s type=%s",
                    event_source,
                    event_id,
                    exc.__class__.__name__,
                )
                observation = None
            if observation is not None:
                return observation

        for name in self._fallback_order:
            if name == event_source:
                continue
            provider = self._providers.get(name)
            if provider is None:
                continue
            try:
                observation = await provider.find_observation(
                    home_team,
                    away_team,
                    match_date,
                    league_slug,
                )
            except Exception as exc:  # noqa: BLE001 - se prueba la siguiente
                logger.warning(
                    "football.predictions.fallback_failed provider=%s "
                    "event_id=%s type=%s",
                    name,
                    event_id,
                    exc.__class__.__name__,
                )
                continue
            if observation is not None:
                logger.info(
                    "football.predictions.settled_by_fallback "
                    "declared=%s used=%s event_id=%s",
                    event_source,
                    name,
                    event_id,
                )
                return observation
        return None


__all__ = ["MultiSourceObservationResolver", "SourceObservationProvider"]
