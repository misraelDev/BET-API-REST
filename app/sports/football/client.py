from typing import Any

import httpx

from app.shared.exceptions import (
    ApiSportsDailyLimitError,
    ApiSportsError,
    ApiSportsRateLimitError,
    ApiSportsUnavailableError,
)


class ApiFootballClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-apisports-key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_fixtures(self, target_date: str, timezone: str) -> list[dict[str, Any]]:
        return await self._get(
            "/fixtures",
            {"date": target_date, "timezone": timezone},
        )

    async def get_current_leagues(self) -> list[dict[str, Any]]:
        return await self._get("/leagues", {"current": "true"})

    async def get_prediction(self, fixture_id: int) -> dict[str, Any] | None:
        response = await self._get("/predictions", {"fixture": fixture_id})
        if not response:
            return None
        result = dict(response[0])
        result["_provider"] = "API-Football"
        return result

    async def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._api_key:
            raise ApiSportsError(
                "Falta API_FOOTBALL_KEY. Configurala en football_api/.env."
            )

        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = exc.response.headers.get("retry-after")
                detail = f" Reintentar despues de {retry_after}s." if retry_after else ""
                raise ApiSportsRateLimitError(
                    f"API-Football alcanzo el limite de solicitudes.{detail}"
                ) from exc
            raise ApiSportsError(f"Error consultando API-Football: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ApiSportsError(f"Error consultando API-Football: {exc}") from exc

        payload = response.json()
        errors = payload.get("errors")
        if errors:
            if isinstance(errors, dict) and errors.get("access"):
                raise ApiSportsUnavailableError(
                    f"API-Football no esta disponible: {errors['access']}"
                )
            if isinstance(errors, dict) and errors.get("requests"):
                raise ApiSportsDailyLimitError(
                    f"API-Football agoto su cuota diaria: {errors['requests']}"
                )
            if isinstance(errors, dict) and errors.get("rateLimit"):
                raise ApiSportsRateLimitError(
                    f"API-Football alcanzo su limite temporal: {errors['rateLimit']}"
                )
            raise ApiSportsError(f"API-Football devolvio errores: {errors}")

        result = payload.get("response", [])
        if not isinstance(result, list):
            raise ApiSportsError("Respuesta inesperada de API-Football.")
        return result
