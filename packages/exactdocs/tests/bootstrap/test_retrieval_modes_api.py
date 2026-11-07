"""RET-06 over REST: a library's retrieval mode, the search `mode`, and the instance setting."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import SecretStr
from pydantic import ValidationError as SettingsError

from app_lifespan import serving
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, VersionRef
from exactdocs.identity.dtos import CreateFirstAdminCommand
from exactdocs.retrieval.adapters.driven.memory import StaticModelRoles
from exactdocs.retrieval.models import ModelRole, PipelineAnswer, PipelineRequest, RetrievalMode

HORSE = "correct horse battery staple"
SETTING = "/api/v1/libraries/acme/payments/retrieval"


class NothingFound:
    """A stand-in hybrid pipeline: the real one is #92."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        del request
        return PipelineAnswer(
            mode=RetrievalMode.HYBRID, hits=(), candidates=0, reranked=0, complete=True
        )


async def _add_payments(container: Container) -> None:
    await SqliteLibraryRepository(engine=container.engine).save(
        Library(
            id=LibraryId("/acme/payments"),
            title="Payments",
            source_url="https://github.com/acme/payments",
            host=HostKind.GITHUB,
            default_branch=VersionRef("main"),
        )
    )


@asynccontextmanager
async def _client(container: Container) -> AsyncGenerator[httpx.AsyncClient]:
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        await _add_payments(container)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            login = {"username": "ada", "password": HORSE}
            assert (await client.post("/api/v1/session", json=login)).status_code == 201
            yield client


@pytest.fixture
async def plain() -> AsyncIterator[httpx.AsyncClient]:
    async with _client(Container.build(Settings())) as client:
        yield client


@pytest.fixture
def embedding_container() -> Container:
    return Container.build(
        Settings(ai=AiSettings(mode=RetrievalMode.BM25)),
        model_roles=StaticModelRoles(roles=frozenset({ModelRole.EMBEDDING})),
        pipelines={RetrievalMode.HYBRID: NothingFound()},
    )


@pytest.fixture
async def with_embeddings() -> AsyncIterator[httpx.AsyncClient]:
    container = Container.build(
        Settings(ai=AiSettings(mode=RetrievalMode.BM25)),
        model_roles=StaticModelRoles(roles=frozenset({ModelRole.EMBEDDING})),
        pipelines={RetrievalMode.HYBRID: NothingFound()},
    )
    async with _client(container) as client:
        yield client


async def test_a_library_without_a_setting_uses_the_best_mode(plain: httpx.AsyncClient) -> None:
    response = await plain.get(SETTING)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "library": "/acme/payments",
        "mode": None,
        "instance_mode": None,
        "effective_mode": "bm25",
        "fallback_reason": None,
        "available_modes": ["bm25"],
        "configured_roles": [],
    }


async def test_setting_a_mode_whose_model_is_not_configured_is_refused(
    plain: httpx.AsyncClient,
) -> None:
    response = await plain.put(SETTING, json={"mode": "hybrid"})

    assert response.status_code == 422, response.text
    assert response.json()["error"] == "mode_unavailable"
    assert "embedding" in response.json()["detail"]
    assert (await plain.get(SETTING)).json()["mode"] is None


async def test_a_library_that_does_not_exist_has_no_setting(plain: httpx.AsyncClient) -> None:
    response = await plain.put("/api/v1/libraries/acme/nothing/retrieval", json={"mode": "bm25"})

    assert response.status_code == 404, response.text
    assert response.json()["error"] == "not_found"


async def test_searching_with_an_unavailable_mode_names_the_missing_role(
    plain: httpx.AsyncClient,
) -> None:
    response = await plain.get(
        "/api/v1/libraries/acme/payments/search", params={"q": "token", "mode": "hybrid"}
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == "mode_unavailable"
    assert "needs the embedding role" in body["detail"]


async def test_a_stored_mode_is_kept_and_shown_with_the_instance_mode(
    with_embeddings: httpx.AsyncClient,
) -> None:
    response = await with_embeddings.put(SETTING, json={"mode": "hybrid"})

    assert response.status_code == 200, response.text
    shown = (await with_embeddings.get(SETTING)).json()
    assert (shown["mode"], shown["instance_mode"], shown["effective_mode"]) == (
        "hybrid",
        "bm25",
        "hybrid",
    )
    assert shown["available_modes"] == ["bm25", "hybrid"]

    cleared = await with_embeddings.put(SETTING, json={"mode": None})
    assert (cleared.json()["mode"], cleared.json()["effective_mode"]) == (None, "bm25")


@pytest.mark.parametrize(
    ("raw", "mode"), [("hybrid", "hybrid"), (" Agentic ", "agentic"), ("", None), ("AUTO", None)]
)
def test_the_instance_mode_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str, mode: str | None
) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__MODE", raw)

    assert Settings().ai.mode == mode


def test_an_unknown_instance_mode_is_refused_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__MODE", "semantic")

    with pytest.raises(SettingsError, match=r"ai\.mode"):
        Settings()


async def test_a_removed_library_added_again_starts_without_its_old_mode(
    embedding_container: Container,
) -> None:
    async with _client(embedding_container) as client:
        assert (await client.put(SETTING, json={"mode": "hybrid"})).status_code == 200

        removed = await client.delete("/api/v1/libraries/acme/payments")
        assert removed.status_code == 200, removed.text
        assert (await client.get(SETTING)).status_code == 404
        await _add_payments(embedding_container)

        shown = (await client.get(SETTING)).json()
        assert (shown["mode"], shown["effective_mode"]) == (None, "bm25")
