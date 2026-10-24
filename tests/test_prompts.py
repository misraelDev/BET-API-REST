import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.prompts.models import PromptCreate, PromptSport, PromptType
from app.prompts.router import router
from app.prompts.service import PromptService
from app.sports.football.predictions.repository import RepositoryConflict


class FakePromptRepository:
    def __init__(self):
        self.documents = []
        self.lock = asyncio.Lock()

    async def get_current(self, sport, prompt_type):
        item = next(
            (
                x for x in self.documents
                if x["sport"] == sport
                and x["prompt_type"] == prompt_type
                and x["is_current"]
            ),
            None,
        )
        return deepcopy(item) if item else None

    async def get_version(self, sport, prompt_type, version):
        item = next(
            (
                x for x in self.documents
                if x["sport"] == sport
                and x["prompt_type"] == prompt_type
                and x["version"] == version
            ),
            None,
        )
        return deepcopy(item) if item else None

    async def get_version_by_id(self, sport, prompt_type, version_id):
        item = next(
            (
                x for x in self.documents
                if x["sport"] == sport
                and x["prompt_type"] == prompt_type
                and x["version_id"] == version_id
            ),
            None,
        )
        return deepcopy(item) if item else None

    async def list_versions(self, sport, prompt_type):
        return [
            deepcopy(x)
            for x in sorted(self.documents, key=lambda x: x["version"])
            if x["sport"] == sport and x["prompt_type"] == prompt_type
        ]

    async def publish(self, document, previous):
        async with self.lock:
            current = next(
                (
                    x for x in self.documents
                    if x["sport"] == document["sport"]
                    and x["prompt_type"] == document["prompt_type"]
                    and x["is_current"]
                ),
                None,
            )
            expected_id = previous.get("version_id") if previous else None
            actual_id = current.get("version_id") if current else None
            if expected_id != actual_id:
                raise RepositoryConflict("La versión base cambió en paralelo.")
            if current:
                current["is_current"] = False
            stored = {
                **deepcopy(document),
                "document_id": f"prompt-{len(self.documents) + 1}",
                "_id": f"prompt-{len(self.documents) + 1}",
            }
            self.documents.append(stored)
            return deepcopy(stored)


def payload(base_version_id=None, *, prompt="Analiza con evidencia."):
    return PromptCreate(
        base_version_id=base_version_id,
        prompt=prompt,
        author="analista",
        change_summary="Ajuste de criterios y trazabilidad.",
    )


@pytest.mark.asyncio
async def test_prompt_publication_creates_immutable_versions_and_retrieves_latest_or_exact():
    repository = FakePromptRepository()
    service = PromptService(repository)
    first = await service.publish(
        PromptSport.FOOTBALL, PromptType.ANALYSIS, payload()
    )
    second = await service.publish(
        PromptSport.FOOTBALL,
        PromptType.ANALYSIS,
        payload(first.version_id, prompt="Analiza con fuentes contrastadas."),
    )

    latest = await service.get(PromptSport.FOOTBALL, PromptType.ANALYSIS)
    exact = await service.get(
        PromptSport.FOOTBALL,
        PromptType.ANALYSIS,
        version_id=first.version_id,
    )
    history = await service.history(PromptSport.FOOTBALL, PromptType.ANALYSIS)

    assert first.version == 1
    assert second.version == 2
    assert second.supersedes_version_id == first.version_id
    assert latest.version_id == second.version_id
    assert latest.prompt_id == "football.analysis"
    assert exact.prompt == "Analiza con evidencia."
    assert exact.is_current is False
    assert [item.version for item in history] == [1, 2]


@pytest.mark.asyncio
async def test_prompt_publication_rejects_stale_base_and_concurrent_loser():
    repository = FakePromptRepository()
    service = PromptService(repository)
    first = await service.publish(
        PromptSport.NBA, PromptType.EVALUATION, payload()
    )

    with pytest.raises(RepositoryConflict, match="no coincide"):
        await service.publish(
            PromptSport.NBA, PromptType.EVALUATION, payload(None)
        )

    async def create_revision(text):
        try:
            result = await service.publish(
                PromptSport.NBA,
                PromptType.EVALUATION,
                payload(first.version_id, prompt=text),
            )
            return result
        except RepositoryConflict:
            return None

    revisions = await asyncio.gather(
        create_revision("Candidato A"), create_revision("Candidato B")
    )
    created = [item for item in revisions if item is not None]
    history = await service.history(PromptSport.NBA, PromptType.EVALUATION)
    assert len(created) == 1
    assert [item.version for item in history] == [1, 2]
    assert sum(item.is_current for item in history) == 1


def test_prompt_api_gets_latest_exact_history_and_publishes_new_revision():
    repository = FakePromptRepository()
    app = FastAPI()
    app.include_router(router)
    app.state.prompt_repository = repository
    client = TestClient(app)

    first = client.post(
        "/api/v1/prompts/football/analysis",
        json={
            "base_version_id": None,
            "prompt": "Prompt inicial.",
            "author": "ana",
            "change_summary": "Primera publicación.",
        },
    )
    assert first.status_code == 201
    first_data = first.json()

    current = client.get("/api/v1/prompts/football/analysis")
    exact = client.get(
        "/api/v1/prompts/football/analysis",
        params={"version_id": first_data["version_id"]},
    )
    history = client.get("/api/v1/prompts/football/analysis/versions")
    second = client.post(
        "/api/v1/prompts/football/analysis",
        json={
            "base_version_id": first_data["version_id"],
            "prompt": "Prompt mejorado.",
            "author": "ana",
            "change_summary": "Aclarar manejo de incertidumbre.",
        },
    )
    stale = client.post(
        "/api/v1/prompts/football/analysis",
        json={
            "base_version_id": first_data["version_id"],
            "prompt": "Versión basada en una revisión vieja.",
            "author": "otra",
            "change_summary": "Debe entrar en conflicto.",
        },
    )

    assert current.status_code == 200
    assert current.json()["version"] == 1
    assert exact.json()["prompt"] == "Prompt inicial."
    assert history.json()["total"] == 1
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert stale.status_code == 409
