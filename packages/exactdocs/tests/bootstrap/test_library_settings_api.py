"""``PUT /api/v1/libraries/{owner}/{repo}/settings``: status codes, the job, what is stored."""

from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings

PATH = "/api/v1/libraries/acme/payments"
pytestmark = pytest.mark.usefixtures("demo_catalog")


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    built = Container.build(Settings())
    async with built.running(jobs=False):  # jobs run by hand: no worker races them
        yield built


@pytest.fixture
def client(container: Container, demo_catalog: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)),
        base_url="http://localhost",
        cookies=demo_catalog,
    )


async def test_it_needs_a_caller(container: Container) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    ) as anonymous:
        response = await anonymous.put(f"{PATH}/settings", json={})

    assert (response.status_code, response.json()["error"]) == (401, "unauthenticated")


async def test_changed_paths_are_stored_and_a_reprocess_job_is_queued(
    client: httpx.AsyncClient,
) -> None:
    response = await client.put(
        f"{PATH}/settings",
        json={"include_paths": ["docs/"], "exclude_paths": ["docs/archive/**"]},
    )

    body = response.json()
    assert response.status_code == 202, body
    assert response.headers["Location"] == f"/api/v1/jobs/{body['job_id']}"
    assert (body["reprocess"], sorted(body["versions"])) == (
        "paths",
        ["main", "next", "v1.3.0", "v1.4.0"],
    )
    job = (await client.get(response.headers["Location"])).json()
    assert (job["kind"], job["library"], job["version"], job["state"]) == (
        "reprocess",
        "/acme/payments",
        None,
        "queued",
    )
    settings = (await client.get(PATH)).json()["settings"]
    assert (settings["include_paths"], settings["exclude_paths"]) == (
        ["docs/"],
        ["docs/archive/**"],
    )


async def test_a_tag_rule_change_runs_a_retag_job_to_its_end(
    client: httpx.AsyncClient, container: Container
) -> None:
    response = await client.put(
        f"{PATH}/settings", json={"tag_rules": [{"pattern": "docs/api/**", "tag": "API"}]}
    )
    assert response.status_code == 202, response.text
    assert response.json()["tag_rules"] == [{"pattern": "docs/api/**", "tag": "api"}]

    assert await container.ingestion.run_next_job()

    job = (await client.get(response.headers["Location"])).json()
    assert (job["kind"], job["state"], job["done"], job["total"]) == ("retag", "succeeded", 4, 4)


async def test_unchanged_settings_answer_200_without_a_job(client: httpx.AsyncClient) -> None:
    response = await client.put(f"{PATH}/settings", json={})

    body = response.json()
    assert response.status_code == 200, body
    assert (body["reprocess"], body["job_id"]) == (None, None)
    assert "Location" not in response.headers


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"exclude_paths": ["../up"]}, "invalid_path_pattern"),
        ({"tag_rules": [{"pattern": "docs/**", "tag": "!!"}]}, "invalid_tag"),
        ({"include_paths": "docs/"}, "validation_error"),
        ({"chunking": {"min_chars": 50, "max_chars": 10}}, "invalid_chunking_config"),
        ({"chunking": {"split_level": 7}}, "validation_error"),
    ],
)
async def test_invalid_settings_are_422_and_nothing_changes(
    client: httpx.AsyncClient, body: dict, error: str
) -> None:
    response = await client.put(f"{PATH}/settings", json=body)

    assert (response.status_code, response.json()["error"]) == (422, error)
    assert (await client.get(PATH)).json()["settings"]["exclude_paths"] == []


async def test_an_unknown_library_is_404(client: httpx.AsyncClient) -> None:
    response = await client.put("/api/v1/libraries/acme/nope/settings", json={})

    assert (response.status_code, response.json()["error"]) == (404, "not_found")


async def test_a_chunking_change_queues_a_rechunk_and_leaving_it_out_keeps_it(
    client: httpx.AsyncClient,
) -> None:
    chunking = {"split_level": 2, "min_chars": 0, "max_chars": 4000, "chunker": "markdown"}
    changed = await client.put(f"{PATH}/settings", json={"chunking": chunking})
    assert changed.status_code == 202, changed.text
    assert (changed.json()["reprocess"], changed.json()["chunking"]) == ("chunking", chunking)
    assert (await client.get(changed.headers["Location"])).json()["kind"] == "rechunk"

    # What a client that edits only paths and tag rules sends (the web UI does).
    tags = await client.put(
        f"{PATH}/settings", json={"tag_rules": [{"pattern": "docs/**", "tag": "d"}]}
    )

    assert tags.status_code == 202, tags.text
    assert (tags.json()["reprocess"], tags.json()["chunking"]) == ("tags", chunking)
    assert tags.json()["job_id"] == changed.json()["job_id"]  # the queued rechunk re-tags too
    assert (await client.get(PATH)).json()["settings"]["chunking"] == chunking
