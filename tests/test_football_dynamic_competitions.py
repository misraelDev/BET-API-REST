import asyncio

import pytest

from app.sports.football.competitions.service import CompetitionNotFound
from test_football_predictions_service import (
    FakeRepository,
    batch,
    payload,
    service,
)


class DynamicCompetitionRepository:
    def __init__(self):
        self.competitions = {
            "copa_del_rey": {
                "code": "copa_del_rey",
                "name": "Copa del Rey",
                "country": "España",
                "active": True,
                "registration_available": True,
                "providers": None,
                "capabilities": {"query": True, "automatic_settlement": False},
            }
        }

    async def get(self, code):
        item = self.competitions.get(code)
        return dict(item) if item else None


def test_new_catalog_code_can_be_registered_and_filtered_without_enum_change():
    predictions = FakeRepository()
    competitions = DynamicCompetitionRepository()
    prediction_service = service(
        predictions,
        competition_repository=competitions,
        kickoff_resolver=None,
    )

    async def scenario():
        response = await prediction_service.register_batch(
            batch(
                payload(
                    prediction_id="copa-del-rey-pick-1",
                    idempotency_key="copa-del-rey-key-1",
                    league="copa_del_rey",
                    kickoff=None,
                )
            )
        )
        stored = response.items[0].record
        filtered = await prediction_service.list_predictions(league="copa_del_rey")
        return response, stored, filtered

    response, stored, filtered = asyncio.run(scenario())
    assert response.created == 1
    assert stored.match.league == "copa_del_rey"
    assert stored.match.league_name == "Copa del Rey"
    assert stored.timing.status.value == "unverified"
    assert filtered.total == 1


def test_unknown_dynamic_code_is_rejected_instead_of_treated_as_arbitrary_text():
    prediction_service = service(
        FakeRepository(),
        competition_repository=DynamicCompetitionRepository(),
        kickoff_resolver=None,
    )

    with pytest.raises(CompetitionNotFound):
        asyncio.run(
            prediction_service.register_batch(
                batch(payload(league="arbitrary_competition"))
            )
        )


def test_deactivated_competition_blocks_new_prediction_but_keeps_history_queryable():
    predictions = FakeRepository()
    competitions = DynamicCompetitionRepository()
    prediction_service = service(
        predictions,
        competition_repository=competitions,
        kickoff_resolver=None,
    )

    async def scenario():
        first = await prediction_service.register_batch(
            batch(
                payload(
                    prediction_id="copa-del-rey-pick-2",
                    idempotency_key="copa-del-rey-key-2",
                    league="copa_del_rey",
                    kickoff=None,
                )
            )
        )
        competitions.competitions["copa_del_rey"]["active"] = False
        rejected = await prediction_service.register_batch(
            batch(
                payload(
                    prediction_id="copa-del-rey-pick-3",
                    idempotency_key="copa-del-rey-key-3",
                    league="copa_del_rey",
                    kickoff=None,
                )
            )
        )
        historic = await prediction_service.list_predictions(league="copa_del_rey")
        return first, rejected, historic

    first, rejected, historic = asyncio.run(scenario())
    assert first.created == 1
    assert rejected.rejected == 1
    assert "inactiva" in rejected.items[0].error
    assert historic.total == 1


def test_dynamic_catalog_code_is_usable_in_rankings_without_static_enum():
    from test_football_rankings_service import build as build_ranking_service
    from test_football_rankings_service import item as ranking_item
    from test_football_rankings_service import register as register_ranking
    from test_football_rankings_service import row as ranking_row

    competitions = DynamicCompetitionRepository()
    ranking_service, _ = build_ranking_service(
        competition_repository=competitions
    )

    result = register_ranking(
        ranking_service,
        ranking_item(
            ranking_id="copa-del-rey-ranking",
            idempotency_key="copa-del-rey-ranking-key",
            scope="league",
            competition="copa_del_rey",
            rows=[ranking_row(league="copa_del_rey")],
        ),
    )

    assert result.created == 1
    assert result.items[0].ranking.rows[0].league == "copa_del_rey"
    assert result.items[0].ranking.competition == "copa_del_rey"
