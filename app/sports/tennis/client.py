import httpx

from app.sports.tennis.models import TennisTour


class PublicTennisClient:
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis"

    def __init__(self, timeout_seconds: float = 20) -> None:
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def scoreboard(
        self, tour: TennisTour, target_date: str, start_date: str | None = None
    ) -> list[dict]:
        tours = [TennisTour.ATP, TennisTour.WTA] if tour == TennisTour.ALL else [tour]
        rows_by_id: dict[str, dict] = {}
        for selected in tours:
            response = await self._client.get(
                f"{self.BASE_URL}/{selected.value}/scoreboard",
                params={
                    "dates": (
                        f"{start_date.replace('-', '')}-{target_date.replace('-', '')}"
                        if start_date
                        else target_date.replace("-", "")
                    )
                },
            )
            response.raise_for_status()
            payload = response.json()
            for row in self._flatten(payload.get("events") or [], selected):
                match_id = str(row["match"].get("id") or "")
                if match_id:
                    rows_by_id[match_id] = row
        return list(rows_by_id.values())

    @staticmethod
    def _flatten(events: list[dict], tour: TennisTour) -> list[dict]:
        rows: list[dict] = []
        expected_slug = {
            TennisTour.ATP: "mens-singles",
            TennisTour.WTA: "womens-singles",
        }[tour]
        for event in events:
            for grouping in event.get("groupings") or []:
                slug = (grouping.get("grouping") or {}).get("slug", "")
                if slug != expected_slug:
                    continue
                for match in grouping.get("competitions") or []:
                    competitors = match.get("competitors") or []
                    if len(competitors) != 2:
                        continue
                    rows.append({
                        "tour": tour.value.upper(),
                        "tournament": event.get("name") or "Torneo sin nombre",
                        "season": str((event.get("season") or {}).get("year") or ""),
                        "match": match,
                    })
        return rows

    async def close(self) -> None:
        await self._client.aclose()
