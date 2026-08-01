import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OmniRouteClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 90.0,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def map_json(self, system_prompt: str, content: str) -> dict[str, Any]:
        logger.info(
            "omniroute.request model=%s input_chars=%s",
            self._model,
            len(content),
        )
        last_error: Exception | None = None
        for attempt in range(1, 3):
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0,
                    "max_tokens": 4000,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            payload = response.json()
            answer = payload["choices"][0]["message"]["content"]
            try:
                parsed = self._parse_json_object(answer)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.error(
                    "omniroute.invalid_json model=%s attempt=%s preview=%s",
                    payload.get("model", "unknown"),
                    attempt,
                    answer[:1000],
                )
                continue
            logger.info(
                "omniroute.response requested_model=%s actual_model=%s "
                "output_chars=%s attempt=%s",
                self._model,
                payload.get("model", "unknown"),
                len(answer),
                attempt,
            )
            return parsed
        raise ValueError("OmniRoute no devolvio JSON valido tras 2 intentos.") from last_error

    @staticmethod
    def _parse_json_object(value: str) -> dict[str, Any]:
        stripped = value.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
        candidate = fenced.group(1) if fenced else stripped
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("OmniRoute no devolvio un objeto JSON.")
            candidate = candidate[start : end + 1]
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("OmniRoute devolvio JSON con una raiz no valida.")
        return parsed
