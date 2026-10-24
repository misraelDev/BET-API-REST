import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from app.sports.football.predictions.catalog import SettlementStatus
from app.sports.football.predictions.models import (
    FootballPredictionBatchRequest,
    FootballPredictionEvaluationCreate,
    FootballPredictionCreate,
    PredictionSource,
)
from app.sports.football.predictions.observation import (
    FootballObservation,
    ObservationSource,
    PeriodScore,
)
from app.sports.football.predictions.repository import RepositoryConflict
from app.sports.football.predictions.service import (
    FootballPredictionService,
    PredictionNotFound,
    PromptVersionNotFound,
    VersionNotFound,
)

RECEIVED_AT = datetime(2026, 10, 24, 17, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 10, 25, 2, 0, tzinfo=UTC)  # 2026-10-24 20:00 CDMX
ANALYSIS_PROMPT_VERSION_ID = "a" * 32
EVALUATION_PROMPT_VERSION_ID = "b" * 32


class FakePromptRepository:
    def __init__(self):
        self.versions = {
            ("football", "analysis", ANALYSIS_PROMPT_VERSION_ID): 1,
            ("football", "analysis", "c" * 32): 2,
            ("football", "evaluation", EVALUATION_PROMPT_VERSION_ID): 1,
            ("nba", "analysis", ANALYSIS_PROMPT_VERSION_ID): 1,
            ("baseball", "analysis", ANALYSIS_PROMPT_VERSION_ID): 1,
            ("tennis", "analysis", ANALYSIS_PROMPT_VERSION_ID): 1,
        }

    async def get_version_by_id(self, sport, prompt_type, version_id):
        version = self.versions.get((sport, prompt_type, version_id))
        if version is None:
            return None
        return {
            "prompt_id": f"{sport}.{prompt_type}",
            "sport": sport,
            "prompt_type": prompt_type,
            "version": version,
            "version_id": version_id,
        }


def _get(document, path):
    current = document
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


class FakeRepository:
    """Repositorio en memoria con la misma semántica que usa el servicio."""

    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.evaluations: list[dict] = []
        self._sequence = 0
        self.updated_settlements: list[tuple[str, dict]] = []

    def _next_id(self) -> str:
        self._sequence += 1
        return f"id-{self._sequence}"

    def _public(self, document: dict) -> dict:
        return {**document, "document_id": document["_id"]}

    async def find_by_idempotency_key(self, key):
        for document in self.documents:
            if document["idempotency_key"] == key:
                return self._public(document)
        return None

    async def get_current(self, prediction_id):
        for document in self.documents:
            if document["prediction_id"] == prediction_id and document["is_current"]:
                return self._public(document)
        return None

    async def list_versions(self, prediction_id):
        return [
            self._public(document)
            for document in sorted(
                (
                    item
                    for item in self.documents
                    if item["prediction_id"] == prediction_id
                ),
                key=lambda item: item["version"],
            )
        ]

    async def insert_version(self, document, previous):
        if any(
            item["idempotency_key"] == document["idempotency_key"]
            for item in self.documents
        ):
            raise RepositoryConflict("idempotency_key duplicada.")
        if any(
            item["prediction_id"] == document["prediction_id"]
            and item["version"] == document["version"]
            for item in self.documents
        ):
            raise RepositoryConflict("versión duplicada.")
        if previous is not None:
            for item in self.documents:
                if item["version_id"] == previous.get("version_id"):
                    item["is_current"] = False
        stored = {**document, "_id": self._next_id()}
        self.documents.append(stored)
        return self._public(stored)

    async def find_predictions(self, query, *, skip=0, limit=50, sort=None):
        matches = [doc for doc in self.documents if self._matches(doc, query)]
        matches.sort(
            key=lambda doc: (doc["received_at"], doc["prediction_id"]),
            reverse=True,
        )
        return [self._public(doc) for doc in matches[skip : skip + limit]]

    async def count_predictions(self, query):
        return sum(1 for doc in self.documents if self._matches(doc, query))

    async def update_settlement(self, version_id, settlement):
        self.updated_settlements.append((version_id, settlement))
        for document in self.documents:
            if document["version_id"] == version_id:
                document["settlement"] = settlement
                document["settlement_status"] = settlement["status"]
                return 1
        return 0

    async def insert_evaluation(self, document):
        for item in self.evaluations:
            if (
                item["prediction_id"] == document["prediction_id"]
                and item["version"] == document["version"]
                and item["analyst"] == document["analyst"]
            ):
                raise RepositoryConflict(
                    "Ya existe una evaluación de este analista para esa versión."
                )
        stored = {**document, "_id": self._next_id()}
        self.evaluations.append(stored)
        return {**stored, "evaluation_id": stored["_id"]}

    async def find_evaluations(self, query, *, skip=0, limit=50):
        matches = [
            item
            for item in self.evaluations
            if item["prediction_id"] == query["prediction_id"]
        ]
        return [
            {**item, "evaluation_id": item["_id"]}
            for item in matches[skip : skip + limit]
        ]

    async def count_evaluations(self, query):
        return sum(
            1
            for item in self.evaluations
            if item["prediction_id"] == query["prediction_id"]
        )

    @staticmethod
    def _matches(document, query):
        for key, expected in query.items():
            value = _get(document, key)
            if isinstance(expected, dict):
                if "$gte" in expected and value < expected["$gte"]:
                    return False
                if "$lte" in expected and value > expected["$lte"]:
                    return False
                if "$lt" in expected and value >= expected["$lt"]:
                    return False
            elif value != expected:
                return False
        return True


class FakeKickoffResolver:
    def __init__(self, kickoffs):
        self.kickoffs = kickoffs
        self.calls = []

    async def resolve_many(self, requests):
        self.calls.append(list(requests))
        return dict(self.kickoffs)


class FailingKickoffResolver:
    async def resolve_many(self, requests):
        raise RuntimeError("fuente caída")


class FakeObservationProvider:
    def __init__(self, observations):
        self.observations = observations

    async def get_observation(self, event_id, league_slug=None):
        value = self.observations.get(event_id)
        if isinstance(value, Exception):
            raise value
        return value


def payload(**overrides):
    data = {
        "idempotency_key": "test-key-0001",
        "event_id": 736644,
        "match_date": date(2026, 10, 24),
        "league": "liga_mx",
        "home_team": "Pumas UNAM",
        "away_team": "Necaxa",
        "kickoff": "2026-10-24T20:00:00-06:00",
        "market": "1x2",
        "period": "full_time",
        "selection": "home",
        "probability": 58.0,
        "confidence": 4,
        "rationale": "Local con mejor forma y ventaja de localía.",
        "sources": [{"name": "ESPN"}],
        "analyst": "ana.garcia",
        "method_version": "analista-v1",
    }
    data.update(overrides)
    return FootballPredictionCreate(**data)


def batch(*items, analysis_prompt_version_id=ANALYSIS_PROMPT_VERSION_ID):
    return FootballPredictionBatchRequest(
        items=list(items),
        analysis_prompt_version_id=analysis_prompt_version_id,
    )


def service(repository, **overrides):
    options = {
        "kickoff_resolver": FakeKickoffResolver({736644: KICKOFF}),
        "prompt_repository": FakePromptRepository(),
        "clock": lambda: RECEIVED_AT,
    }
    options.update(overrides)
    return FootballPredictionService(repository, **options)


def observation(**overrides):
    data = {
        "event_id": 736644,
        "league": "mex.1",
        "status_name": "STATUS_FULL_TIME",
        "phase": "finished",
        "home_team": "Pumas UNAM",
        "away_team": "Necaxa",
        "regulation": PeriodScore(home=2, away=1),
        "first_half": PeriodScore(home=1, away=0),
        "second_half": PeriodScore(home=1, away=1),
        "source": ObservationSource(
            retrieved_at=datetime(2026, 10, 25, 5, 0, tzinfo=UTC),
            url="https://example.test/summary",
        ),
    }
    data.update(overrides)
    return FootballObservation(**data)


@pytest.mark.asyncio
async def test_registers_each_selection_of_the_batch():
    repository = FakeRepository()
    result = await service(repository).register_batch(
        batch(
            payload(),
            payload(
                idempotency_key="test-key-0002",
                market="total_goals",
                selection="over",
                line=2.5,
            ),
        )
    )

    assert result.created == 2
    assert result.total == 2
    assert all(item.status == "created" for item in result.items)
    assert len({item.prediction_id for item in result.items}) == 2
    assert all(item.version == 1 for item in result.items)
    assert len(repository.documents) == 2
    assert repository.documents[0]["analysis_prompt"] == {
        "prompt_id": "football.analysis",
        "version": 1,
        "version_id": ANALYSIS_PROMPT_VERSION_ID,
    }
    assert repository.documents[0]["method_version"] == "analista-v1"


@pytest.mark.asyncio
async def test_registration_rejects_unknown_analysis_prompt_reference():
    repository = FakeRepository()
    with pytest.raises(PromptVersionNotFound):
        await service(repository).register_batch(
            FootballPredictionBatchRequest(
                analysis_prompt_version_id="f" * 32,
                items=[payload()],
            )
        )
    assert repository.documents == []


@pytest.mark.asyncio
async def test_new_prompt_revision_does_not_change_old_prediction_reference():
    repository = FakeRepository()
    prompts = FakePromptRepository()
    subject = service(repository, prompt_repository=prompts)
    await subject.register_batch(batch(payload(prediction_id="pred00001")))
    prompts.versions[("football", "analysis", "d" * 32)] = 3
    await subject.register_batch(
        batch(
            payload(
                prediction_id="pred00002",
                idempotency_key="test-key-0002",
            ),
            analysis_prompt_version_id="d" * 32,
        )
    )
    assert repository.documents[0]["analysis_prompt"]["version_id"] == ANALYSIS_PROMPT_VERSION_ID
    assert repository.documents[0]["analysis_prompt"]["version"] == 1
    assert repository.documents[1]["analysis_prompt"]["version"] == 3


@pytest.mark.asyncio
async def test_derives_match_date_from_verified_kickoff_in_cdmx():
    repository = FakeRepository()
    await service(repository).register_batch(
        batch(payload(match_date=date(2026, 10, 25)))
    )

    match = repository.documents[0]["match"]
    assert match["date"] == "2026-10-24"
    assert match["declared_date"] == "2026-10-25"
    assert match["kickoff_source"] == "provider"
    assert match["kickoff_verified"] is True
    assert repository.documents[0]["timing"]["status"] == "pre_match"


@pytest.mark.asyncio
async def test_idempotent_retry_replays_existing_version():
    repository = FakeRepository()
    subject = service(repository)
    first = await subject.register_batch(batch(payload()))
    second = await subject.register_batch(batch(payload()))

    assert first.created == 1
    assert second.replayed == 1
    assert second.created == 0
    assert second.items[0].version_id == first.items[0].version_id
    assert len(repository.documents) == 1


@pytest.mark.asyncio
async def test_same_key_with_different_body_is_rejected():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload()))
    result = await subject.register_batch(batch(payload(probability=70.0)))

    assert result.rejected == 1
    assert "cuerpo distinto" in result.items[0].error
    assert repository.documents[0]["probability"] == 58.0


@pytest.mark.asyncio
async def test_concurrent_same_key_replays_single_insert():
    repository = FakeRepository()
    subject = service(repository)
    first, second = await asyncio.gather(
        subject.register_batch(batch(payload())),
        subject.register_batch(batch(payload())),
    )
    assert first.created + second.created == 1
    assert first.replayed + second.replayed == 1
    assert len(repository.documents) == 1


@pytest.mark.asyncio
async def test_concurrent_version_attempts_keep_one_current_version():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))
    results = await asyncio.gather(
        subject.register_batch(batch(payload(
            prediction_id="abcdefgh",
            idempotency_key="test-key-0002",
            probability=60,
        ))),
        subject.register_batch(batch(payload(
            prediction_id="abcdefgh",
            idempotency_key="test-key-0003",
            probability=70,
        ))),
    )
    current = [item for item in repository.documents if item["is_current"]]
    assert len(current) == 1
    assert sum(result.created for result in results) == 2
    assert sorted(item["version"] for item in repository.documents) == [1, 2, 3]


@pytest.mark.asyncio
async def test_new_version_never_overwrites_the_previous_one():
    repository = FakeRepository()
    subject = service(repository)
    first = await subject.register_batch(
        batch(payload(prediction_id="abcdefgh"))
    )
    second = await subject.register_batch(
        batch(
            payload(
                prediction_id="abcdefgh",
                idempotency_key="test-key-0002",
                probability=66.0,
                confidence=5,
            )
        )
    )

    assert first.items[0].version == 1
    assert second.created == 1
    assert second.items[0].version == 2
    assert len(repository.documents) == 2
    assert [doc["is_current"] for doc in repository.documents] == [False, True]
    assert repository.documents[0]["probability"] == 58.0
    assert repository.documents[1]["probability"] == 66.0
    assert (
        repository.documents[1]["supersedes_version_id"]
        == repository.documents[0]["version_id"]
    )
    assert repository.documents[1]["prediction_id"] == first.items[0].prediction_id


@pytest.mark.asyncio
async def test_version_must_keep_market_identity():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))
    result = await subject.register_batch(
        batch(
            payload(
                prediction_id="abcdefgh",
                idempotency_key="test-key-0002",
                selection="draw",
            )
        )
    )

    assert result.rejected == 1
    assert "identidad de la selección" in result.items[0].error
    assert len(repository.documents) == 1


@pytest.mark.asyncio
async def test_late_registration_is_flagged_not_rejected():
    repository = FakeRepository()
    late = KICKOFF + timedelta(hours=1)
    result = await service(
        repository, clock=lambda: late
    ).register_batch(batch(payload()))

    assert result.created == 1
    document = repository.documents[0]
    assert document["timing"] == {
        "status": "late",
        "received_before_kickoff": False,
    }
    assert result.items[0].received_before_kickoff is False


@pytest.mark.asyncio
async def test_missing_kickoff_marks_timing_unverified():
    repository = FakeRepository()
    result = await service(
        repository, kickoff_resolver=None
    ).register_batch(batch(payload(kickoff=None)))

    assert result.created == 1
    document = repository.documents[0]
    assert document["timing"] == {
        "status": "unverified",
        "received_before_kickoff": None,
    }
    assert document["match"]["kickoff_source"] == "unknown"
    assert document["match"]["date"] == "2026-10-24"


@pytest.mark.asyncio
async def test_declared_kickoff_is_used_when_source_says_unknown():
    repository = FakeRepository()
    await service(
        repository, kickoff_resolver=FakeKickoffResolver({})
    ).register_batch(batch(payload()))

    document = repository.documents[0]
    assert document["match"]["kickoff_source"] == "request"
    assert document["match"]["kickoff_verified"] is False
    assert document["timing"] == {
        "status": "unverified",
        "received_before_kickoff": None,
    }


@pytest.mark.asyncio
async def test_kickoff_lookup_failure_does_not_block_registration():
    repository = FakeRepository()
    result = await service(
        repository, kickoff_resolver=FailingKickoffResolver()
    ).register_batch(batch(payload()))

    assert result.created == 1
    assert repository.documents[0]["match"]["kickoff_source"] == "request"


@pytest.mark.asyncio
async def test_generated_at_is_stored_separately_from_received_at():
    repository = FakeRepository()
    await service(repository).register_batch(
        batch(payload(generated_at="2026-10-24T09:00:00-06:00"))
    )

    document = repository.documents[0]
    assert document["received_at"] == RECEIVED_AT
    assert document["generated_at"] == datetime(
        2026, 10, 24, 15, 0, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_list_filters_and_pagination():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(
        batch(
            payload(prediction_id="pred0001"),
            payload(
                idempotency_key="test-key-0002",
                prediction_id="pred0002",
                market="btts",
                selection="yes",
                analyst="luis.perez",
            ),
            payload(
                idempotency_key="test-key-0003",
                prediction_id="pred0003",
                event_id=999,
                market="total_goals",
                selection="over",
                line=2.5,
            ),
        )
    )

    by_analyst = await subject.list_predictions(analyst="ana.garcia")
    assert by_analyst.total == 2
    by_market = await subject.list_predictions(market="total_goals")
    assert by_market.total == 1
    assert by_market.items[0].prediction_id == "pred0003"
    by_event = await subject.list_predictions(event_id=736644)
    assert by_event.total == 2
    by_date = await subject.list_predictions(match_date=date(2026, 10, 24))
    assert by_date.total == 3
    by_range = await subject.list_predictions(
        match_date_from=date(2026, 10, 25),
        match_date_to=date(2026, 10, 26),
    )
    assert by_range.total == 0
    pending = await subject.list_predictions(
        settlement_status=SettlementStatus.PENDIENTE
    )
    assert pending.total == 3
    pre_match = await subject.list_predictions(timing="pre_match")
    assert pre_match.total == 2
    page = await subject.list_predictions(page=2, page_size=2)
    assert page.total == 3
    assert len(page.items) == 1
    assert page.page == 2
    assert page.page_size == 2


@pytest.mark.asyncio
async def test_list_hides_old_versions_unless_requested():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))
    await subject.register_batch(
        batch(
            payload(
                prediction_id="abcdefgh",
                idempotency_key="test-key-0002",
                probability=70.0,
            )
        )
    )

    current = await subject.list_predictions()
    assert current.total == 1
    assert current.items[0].version == 2
    assert current.items[0].probability == 70.0

    history = await subject.list_predictions(include_versions=True)
    assert history.total == 2
    assert {item.version for item in history.items} == {1, 2}
    probabilities = {item.version: item.probability for item in history.items}
    assert probabilities == {1: 58.0, 2: 70.0}


@pytest.mark.asyncio
async def test_detail_returns_all_versions():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))
    await subject.register_batch(
        batch(
            payload(
                prediction_id="abcdefgh",
                idempotency_key="test-key-0002",
                probability=70.0,
            )
        )
    )

    detail = await subject.get_prediction("abcdefgh")
    assert detail.total_versions == 2
    assert detail.current_version == 2
    assert [item.version for item in detail.versions] == [1, 2]
    assert detail.versions[0].probability == 58.0
    assert detail.versions[1].probability == 70.0


@pytest.mark.asyncio
async def test_detail_keeps_latest_verified_pre_match_after_late_update():
    repository = FakeRepository()
    first = await service(repository).register_batch(
        batch(payload(prediction_id="abcdefgh"))
    )
    later_clock = KICKOFF + timedelta(minutes=5)
    second = await service(repository, clock=lambda: later_clock).register_batch(
        batch(
            payload(
                prediction_id="abcdefgh",
                idempotency_key="test-key-0002",
                probability=71.0,
            )
        )
    )

    detail = await service(repository).get_prediction("abcdefgh")
    assert second.items[0].version == 2
    assert detail.current_version == 2
    assert detail.latest_verified_pre_match_version == 1
    assert detail.latest_verified_pre_match.version_id == first.items[0].version_id


@pytest.mark.asyncio
async def test_detail_unknown_id_raises():
    with pytest.raises(PredictionNotFound):
        await service(FakeRepository()).get_prediction("desconocido")


def evaluation(**overrides):
    data = {
        "analyst": "ana.garcia",
        "evaluation_prompt_version_id": EVALUATION_PROMPT_VERSION_ID,
        "diagnosis": "El local dominó el primer tiempo y lo liquidó al final.",
        "learnings": ["El descanso no cambió el guion del partido."],
        "sources": [PredictionSource(name="ESPN")],
    }
    data.update(overrides)
    return FootballPredictionEvaluationCreate(**data)


@pytest.mark.asyncio
async def test_evaluation_is_linked_to_current_version_and_is_unique():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))

    version_id = repository.documents[0]["version_id"]
    stored = await subject.add_evaluation(
        "abcdefgh", evaluation(version_id=version_id)
    )
    assert stored.version == 1
    assert stored.prediction_id == "abcdefgh"
    assert stored.evaluation_prompt.prompt_id == "football.evaluation"
    assert stored.evaluation_prompt.version == 1
    assert stored.evaluation_prompt.version_id == EVALUATION_PROMPT_VERSION_ID

    with pytest.raises(RepositoryConflict):
        await subject.add_evaluation(
            "abcdefgh", evaluation(version_id=version_id)
        )

    listed = await subject.list_evaluations("abcdefgh")
    assert listed.total == 1
    assert listed.items[0].diagnosis.startswith("El local dominó")


@pytest.mark.asyncio
async def test_evaluation_can_target_an_explicit_version():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))
    await subject.register_batch(
        batch(
            payload(
                prediction_id="abcdefgh",
                idempotency_key="test-key-0002",
                probability=70.0,
            )
        )
    )

    stored = await subject.add_evaluation(
        "abcdefgh",
        evaluation(version_id=repository.documents[0]["version_id"]),
    )
    assert stored.version == 1
    assert stored.version_id == repository.documents[0]["version_id"]

    with pytest.raises(VersionNotFound):
        await subject.add_evaluation(
            "abcdefgh", evaluation(version_id="0" * 32)
        )


@pytest.mark.asyncio
async def test_evaluation_rejects_unknown_prompt_version():
    repository = FakeRepository()
    subject = service(repository)
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))
    with pytest.raises(PromptVersionNotFound):
        await subject.add_evaluation(
            "abcdefgh",
            evaluation(
                version_id=repository.documents[0]["version_id"],
                evaluation_prompt_version_id="f" * 32,
            ),
        )
    assert repository.evaluations == []


@pytest.mark.asyncio
async def test_settle_date_updates_current_versions():
    repository = FakeRepository()
    subject = service(
        repository,
        observation_provider=FakeObservationProvider({736644: observation()}),
    )
    await subject.register_batch(batch(payload(prediction_id="abcdefgh")))

    summary = await subject.settle_date(date(2026, 10, 24))

    assert summary["predictions_matched"] == 1
    assert summary["predictions_settled"] == 1
    assert summary["predictions_updated"] == 1
    assert summary["predictions_pending"] == 0
    document = repository.documents[0]
    assert document["settlement_status"] == "acertado"
    assert document["settlement"]["observed"]["home_goals"] == 2
    assert document["settlement"]["source"]["name"] == "ESPN public summary"
    assert document["settlement"]["rule_version"] == "football-settlement-v2"


@pytest.mark.asyncio
async def test_settle_date_is_idempotent():
    repository = FakeRepository()
    subject = service(
        repository,
        observation_provider=FakeObservationProvider({736644: observation()}),
    )
    await subject.register_batch(batch(payload()))
    await subject.settle_date(date(2026, 10, 24))
    second = await subject.settle_date(date(2026, 10, 24))

    assert second["predictions_updated"] == 0
    assert second["predictions_settled"] == 1


@pytest.mark.asyncio
async def test_registration_only_competition_is_not_auto_settled():
    repository = FakeRepository()
    provider = FakeObservationProvider({736644: observation()})
    subject = service(repository, observation_provider=provider)
    await subject.register_batch(
        batch(payload(league="saudi_pro_league", prediction_id="abcdefgh"))
    )
    summary = await subject.settle_date(date(2026, 10, 24))
    assert summary["predictions_pending"] == 1
    assert summary["predictions_updated"] == 0
    assert summary["errors"][0].stage == "coverage"
    assert repository.documents[0]["settlement_status"] == "pendiente"


@pytest.mark.asyncio
async def test_settle_date_keeps_pending_when_match_is_not_finished():
    repository = FakeRepository()
    subject = service(
        repository,
        observation_provider=FakeObservationProvider(
            {736644: observation(phase="in_play", regulation=None)}
        ),
    )
    await subject.register_batch(batch(payload()))
    summary = await subject.settle_date(date(2026, 10, 24))

    assert summary["predictions_pending"] == 1
    assert repository.documents[0]["settlement_status"] == "pendiente"


@pytest.mark.asyncio
async def test_settle_date_reports_unmatched_and_errors():
    repository = FakeRepository()
    subject = service(
        repository,
        observation_provider=FakeObservationProvider(
            {736644: None, 999: RuntimeError("boom")}
        ),
    )
    await subject.register_batch(
        batch(
            payload(prediction_id="pred0001"),
            payload(
                prediction_id="pred0002",
                idempotency_key="test-key-0002",
                event_id=999,
            ),
        )
    )
    summary = await subject.settle_date(date(2026, 10, 24))

    assert summary["unmatched_event_ids"] == ["736644"]
    assert len(summary["errors"]) == 2
    stages = {error.stage for error in summary["errors"]}
    assert stages == {"observation"}


@pytest.mark.asyncio
async def test_settle_date_requires_observation_provider():
    with pytest.raises(RuntimeError, match="observaciones"):
        await service(FakeRepository(), observation_provider=None).settle_date(
            date(2026, 10, 24)
        )
