"""A sources entry's title and description on every SQL backend (#444): stored like an edit."""

from collections.abc import AsyncIterator

import httpx
import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ApplyReadmeCommand

LIBRARY = "/acme/payments"  # a demo library: it has versions, so a README can be applied
URL = "https://github.com/acme/payments"
TITLE, DESCRIPTION = "Azure Functions", "Microsoft Azure Functions documentation."


@pytest.fixture(params=SQL_BACKENDS)
def backend(request: pytest.FixtureRequest) -> str:
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    return request.param


@pytest.fixture
async def container(backend: str, demo_catalog: dict[str, str]) -> AsyncIterator[Container]:
    del backend, demo_catalog  # the database is chosen before the demo data goes into it
    built = Container.build(Settings())
    async with built.running(jobs=False):
        yield built


@pytest.fixture
def client(container: Container, demo_catalog: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)),
        base_url="http://localhost",
        cookies=demo_catalog,
    )


def _file(**entry: object) -> dict:
    declared = {"url": URL, "refs": ["v1.3.0", "v1.4.0", "main", "next"]}
    return {"sources": {"version": 1, "libraries": [declared | entry]}}


async def test_a_declared_title_and_description_are_stored_and_survive_a_readme_import(
    client: httpx.AsyncClient, container: Container
) -> None:
    body = _file(title=TITLE, description=DESCRIPTION)

    applied = (await client.post("/api/v1/sources/apply", json=body)).json()
    stored = (await client.get(f"/api/v1/libraries{LIBRARY}")).json()
    await container.catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="v1.4.0", title="From README", description="Other.")
    )
    after_import = (await client.get(f"/api/v1/libraries{LIBRARY}")).json()
    again = (await client.post("/api/v1/sources/plan", json=body)).json()

    assert [r["action"] for r in applied["results"] if r["library_id"] == LIBRARY] == ["updated"]
    assert (stored["title"], stored["description"]) == (TITLE, DESCRIPTION)
    assert (after_import["title"], after_import["description"]) == (TITLE, DESCRIPTION)
    assert LIBRARY in again["unchanged"]


async def test_plan_shows_a_changed_title_and_apply_makes_it(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/sources/apply", json=_file(title="Old", description="D."))
    changed = _file(title=TITLE, description="D.")

    plan = (await client.post("/api/v1/sources/plan", json=changed)).json()
    before = (await client.get(f"/api/v1/libraries{LIBRARY}")).json()
    applied = (await client.post("/api/v1/sources/apply", json=changed)).json()
    after = (await client.get(f"/api/v1/libraries{LIBRARY}")).json()

    (update,) = [u for u in plan["update"] if u["library_id"] == LIBRARY]
    assert update["title"] == {"before": "Old", "after": TITLE}
    assert update["description"] is None
    assert before["title"] == "Old"
    assert [(r["action"], r["jobs"]) for r in applied["results"] if r["library_id"] == LIBRARY] == [
        ("updated", [])
    ]
    assert (after["title"], after["description"]) == (TITLE, "D.")


async def test_an_entry_without_them_leaves_the_readme_text_and_an_edit_alone(
    client: httpx.AsyncClient, container: Container
) -> None:
    body = _file()
    await client.post("/api/v1/sources/apply", json=body)
    await client.patch(f"/api/v1/libraries{LIBRARY}", json={"title": "By hand"})
    await container.catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="v1.4.0", title="From README", description="Text.")
    )

    plan = (await client.post("/api/v1/sources/plan", json=body)).json()
    await client.post("/api/v1/sources/apply", json=body)

    stored = (await client.get(f"/api/v1/libraries{LIBRARY}")).json()
    assert LIBRARY in plan["unchanged"]
    assert (stored["title"], stored["description"]) == ("By hand", "Text.")
