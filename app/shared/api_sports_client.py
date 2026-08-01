import json
import logging
from time import perf_counter
from typing import Any

import httpx

from app.shared.exceptions import ApiSportsError

logger = logging.getLogger(__name__)


class ApiSportsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        service_name: str = "api-sports",
        log_response_payload: bool = True,
        log_preview_chars: int = 2000,
    ) -> None:
        self._api_key = api_key
        self._service_name = service_name
        self._log_response_payload = log_response_payload
        self._log_preview_chars = log_preview_chars
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-apisports-key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_games(self, target_date: str, timezone: str) -> list[dict[str, Any]]:
        return await self._get(
            "/games",
            {"date": target_date, "timezone": timezone},
        )

    async def get_standings(
        self,
        league: str | int,
        season: str | int,
    ) -> list[dict[str, Any]]:
        return await self._get(
            "/standings",
            {"league": league, "season": season},
        )

    async def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._api_key:
            raise ApiSportsError(
                "Falta API_FOOTBALL_KEY. La misma clave del dashboard API-Sports "
                "debe tener habilitado este producto."
            )
        started_at = perf_counter()
        logger.info(
            "api_sports.request service=%s path=%s params=%s",
            self._service_name,
            path,
            params,
        )
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception(
                "api_sports.error service=%s path=%s duration_ms=%.0f",
                self._service_name,
                path,
                (perf_counter() - started_at) * 1000,
            )
            raise ApiSportsError(f"Error consultando API-Sports: {exc}") from exc

        payload = response.json()
        result = payload.get("response", [])
        result_count = len(result) if isinstance(result, list) else -1
        logger.info(
            "api_sports.response service=%s path=%s status=%s results=%s "
            "duration_ms=%.0f remaining=%s",
            self._service_name,
            path,
            response.status_code,
            result_count,
            (perf_counter() - started_at) * 1000,
            response.headers.get("x-ratelimit-requests-remaining", "unknown"),
        )
        if self._log_response_payload:
            preview_source = result[:1] if isinstance(result, list) else payload
            preview = json.dumps(preview_source, ensure_ascii=True, default=str)
            logger.info(
                "api_sports.payload service=%s path=%s preview=%s",
                self._service_name,
                path,
                preview[: self._log_preview_chars],
            )
        if payload.get("errors"):
            logger.error(
                "api_sports.provider_error service=%s path=%s errors=%s",
                self._service_name,
                path,
                payload["errors"],
            )
            raise ApiSportsError(f"API-Sports devolvio errores: {payload['errors']}")
        if not isinstance(result, list):
            raise ApiSportsError("Respuesta inesperada de API-Sports.")
        return result
