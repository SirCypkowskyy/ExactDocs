"""#428 with #111: a library-scoped token is refused other libraries on `/search`, `/answer`."""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from app_lifespan import serving
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, VersionRef
from exactdocs.identity.dtos import CreateFirstAdminCommand, CreateTokenCommand
from scripted_explorer import ScriptedModels, answering, scripted_ai

ALLOWED = "/acme/payments"
HIDDEN = "/acme/ledger"
MISSING = "/acme/absent"


@pytest.fixture
async def scoped() -> AsyncIterator[httpx.AsyncClient]:
    """A client whose token is limited to ``ALLOWED``, on an instance with an ``llm`` role."""
    settings = Settings(ai=AiSettings.model_validate(scripted_ai(None)))
    container = Container.build(settings, model_factory=ScriptedModels(model=answering()))
    async with serving(create_app(container)) as app:
        admin = await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr("correct horse battery"))
        )
        repository = SqliteLibraryRepository(engine=container.engine)
        for library in (ALLOWED, HIDDEN):
            await repository.save(
                Library(
                    id=LibraryId(library),
                    title=library,
                    source_url=f"https://git.example.com{library}.git",
                    host=HostKind.GIT,
                    default_branch=VersionRef("main"),
                )
            )
        grant = await container.identity.create_token(
            admin, CreateTokenCommand(name="scoped", library_ids={ALLOWED})
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
            headers={"authorization": f"Bearer {grant.token}"},
        ) as client:
            yield client


async def test_search_of_a_library_outside_the_token_is_a_404_like_a_missing_one(
    scoped: httpx.AsyncClient,
) -> None:
    refused = [
        await scoped.get("/api/v1/search", params={"q": "retry", "library": library})
        for library in (HIDDEN, MISSING)
    ]

    assert [r.status_code for r in refused] == [404, 404]
    assert refused[0].text.replace(HIDDEN, MISSING) == refused[1].text


async def test_an_answer_over_a_library_outside_the_token_is_a_404_like_a_missing_one(
    scoped: httpx.AsyncClient,
) -> None:
    refused = [
        await scoped.post("/api/v1/answer", json={"question": "retry?", "libraries": [library]})
        for library in (HIDDEN, MISSING)
    ]

    assert [r.status_code for r in refused] == [404, 404]
    assert refused[0].text.replace(HIDDEN, MISSING) == refused[1].text
