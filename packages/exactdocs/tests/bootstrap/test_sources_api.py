"""``/api/v1/sources``: plan writes nothing, apply is idempotent, prune, errors, the schema."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from fixture_repo import DocsRepo

pytestmark = pytest.mark.usefixtures("demo_catalog")

LIBRARY = "/fixture/docs-repo"
DEMO = ["/acme/ledger", "/acme/payments"]
SCHEMA = Path(__file__).parents[4] / "docs" / "schemas" / "exactdocs.sources.schema.json"


@pytest.fixture
async def client(demo_catalog: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    """The app without its job worker: queued imports stay queued, as right after an apply.

    Yields:
        A client signed in as the admin.
    """
    container = Container.build(Settings())  # the real system git
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as found,
    ):
        yield found


def _sources(docs_repo: DocsRepo, **entry: object) -> dict:
    declared = {
        "url": docs_repo.file_url,
        "refs": ["main", "v1.3.0"],
        "include_paths": ["docs"],
        "chunking": {"split_level": 2},
        "auto_sync": {"tag_pattern": "v*", "keep_last": 3},
    }
    return {"version": 1, "libraries": [declared | entry]}


async def _state(client: httpx.AsyncClient) -> tuple[object, ...]:
    """Everything an apply could write: libraries, jobs, schedules."""
    libraries = (await client.get("/api/v1/libraries")).json()["libraries"]
    ids = [lib["id"] for lib in libraries]
    details = [(await client.get(f"/api/v1/libraries{i}")).json() for i in ids]
    schedules = [(await client.get(f"/api/v1/libraries{i}/auto-sync")).json() for i in ids]
    jobs = [(await client.get(f"/api/v1/libraries{i}/jobs")).json() for i in ids]
    return details, schedules, jobs


async def test_it_needs_a_caller(client: httpx.AsyncClient) -> None:
    client.cookies.clear()

    for path in ("/api/v1/sources/plan", "/api/v1/sources/apply"):
        assert (await client.post(path, json={})).status_code == 401
    assert (await client.get("/api/v1/sources/schema")).status_code == 401


async def test_plan_shows_the_diff_and_writes_nothing(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    before = await _state(client)

    response = await client.post(
        "/api/v1/sources/plan", json={"sources": _sources(docs_repo), "prune": True}
    )

    body = response.json()
    assert response.status_code == 200, body
    assert [(c["id"], c["refs"], c["include_paths"]) for c in body["create"]] == [
        (LIBRARY, ["main", "v1.3.0"], ["docs"])
    ]
    assert [(u["library_id"], u["will_be_removed"]) for u in body["undeclared"]] == [
        (i, True) for i in DEMO
    ]
    assert (body["changes"], body["errors"]) == (True, [])
    assert await _state(client) == before


async def test_apply_creates_and_a_second_apply_writes_nothing(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    body = {"sources": _sources(docs_repo)}

    first = (await client.post("/api/v1/sources/apply", json=body)).json()
    after_first = await _state(client)
    second = (await client.post("/api/v1/sources/apply", json=body)).json()

    (created,) = [r for r in first["results"] if r["library_id"] == LIBRARY]
    assert (created["action"], len(created["jobs"]), created["error"]) == ("created", 2, None)
    detail = (await client.get(f"/api/v1/libraries{LIBRARY}")).json()
    assert (detail["settings"]["include_paths"], detail["settings"]["chunking"]["split_level"]) == (
        ["docs"],
        2,
    )
    schedule = (await client.get(f"/api/v1/libraries{LIBRARY}/auto-sync")).json()
    assert (schedule["enabled"], schedule["tag_pattern"], schedule["keep_last"]) == (True, "v*", 3)
    jobs = (await client.get(f"/api/v1/libraries{LIBRARY}/jobs")).json()["jobs"]
    assert sorted((j["kind"], j["version"], j["state"]) for j in jobs) == [
        ("import", "main", "queued"),
        ("import", "v1.3.0", "queued"),
    ]
    assert second["plan"]["changes"] is False
    assert {r["action"] for r in second["results"]} == {"unchanged"}
    assert second["plan"]["unchanged"] == [LIBRARY]
    assert await _state(client) == after_first


async def test_without_prune_nothing_is_removed_and_with_prune_undeclared_libraries_are(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    body = {"sources": _sources(docs_repo)}

    kept = (await client.post("/api/v1/sources/apply", json=body)).json()
    assert [u["library_id"] for u in kept["plan"]["undeclared"]] == DEMO
    listed = (await client.get("/api/v1/libraries")).json()["libraries"]
    assert sorted(lib["id"] for lib in listed) == [*DEMO, LIBRARY]

    pruned = (await client.post("/api/v1/sources/apply", json=body | {"prune": True})).json()

    assert [(r["library_id"], r["action"]) for r in pruned["results"]] == [
        (LIBRARY, "unchanged"),
        *[(i, "removed") for i in DEMO],
    ]
    listed = (await client.get("/api/v1/libraries")).json()["libraries"]
    assert [lib["id"] for lib in listed] == [LIBRARY]


async def test_one_failing_library_does_not_stop_the_others(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    sources = {
        "version": 1,
        "libraries": [
            {"url": docs_repo.file_url, "id": "/fixture/broken", "refs": ["no-such-ref"]},
            {"url": docs_repo.file_url, "refs": ["v1.4.0"]},
        ],
    }

    applied = (await client.post("/api/v1/sources/apply", json={"sources": sources})).json()

    assert [(r["library_id"], r["action"], r["error_code"]) for r in applied["results"]] == [
        ("/fixture/broken", "failed", "unknown_ref"),
        (LIBRARY, "created", None),
    ]
    assert applied["failed"] == 1


async def test_an_id_that_exists_with_another_url_is_a_source_mismatch(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    sources = {
        "version": 1,
        "libraries": [{"url": docs_repo.file_url, "id": "/acme/payments", "refs": ["main"]}],
    }

    plan = (await client.post("/api/v1/sources/plan", json={"sources": sources})).json()

    assert [(e["library_id"], e["error"]) for e in plan["errors"]] == [
        ("/acme/payments", "source_mismatch")
    ]


@pytest.mark.parametrize(
    ("entry", "field"),
    [({"include_path": ["docs"]}, "include_path"), ({"refs": ["abc1234"]}, "refs")],
)
async def test_an_invalid_file_is_a_422_naming_the_field(
    client: httpx.AsyncClient, docs_repo: DocsRepo, entry: dict, field: str
) -> None:
    response = await client.post(
        "/api/v1/sources/plan", json={"sources": _sources(docs_repo, **entry)}
    )

    assert response.status_code == 422
    assert field in response.text


async def test_a_setting_the_server_cannot_store_is_a_422_naming_the_entry(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    response = await client.post(
        "/api/v1/sources/plan", json={"sources": _sources(docs_repo, include_paths=["../x"])}
    )

    assert (response.status_code, response.json()["error"]) == (422, "invalid_sources")
    assert "libraries[0] (/fixture/docs-repo)" in response.json()["detail"]


async def test_the_served_schema_is_the_committed_one(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/sources/schema")

    assert response.status_code == 200
    assert response.json() == json.loads(SCHEMA.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("entry", "include"),
    [({"include_paths": []}, []), ({}, ["docs/"])],  # declared "every file"; not managed
)
async def test_context7_fills_in_only_paths_the_file_does_not_manage(
    client: httpx.AsyncClient, docs_repo: DocsRepo, entry: dict, include: list[str]
) -> None:
    declared = {"url": docs_repo.file_url, "refs": ["next"], **entry}  # `next` has context7.json
    body = {"sources": {"version": 1, "libraries": [declared]}}

    await client.post("/api/v1/sources/apply", json=body)
    plan = (await client.post("/api/v1/sources/plan", json=body)).json()

    detail = (await client.get(f"/api/v1/libraries{LIBRARY}")).json()
    assert detail["settings"]["include_paths"] == include
    assert (plan["unchanged"], plan["changes"]) == ([LIBRARY], False)


async def test_an_admin_token_may_plan_and_a_user_token_gets_403(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    bob = {"username": "bob", "password": "bob's long passphrase"}
    assert (await client.post("/api/v1/users", json=bob)).status_code == 201
    admin = (await client.post("/api/v1/tokens", json={"name": "ci"})).json()["token"]
    user = (await client.post("/api/v1/tokens/login", json=bob | {"name": "bob"})).json()["token"]
    client.cookies.clear()  # tokens only, as the CLI and CI call
    body = {"sources": _sources(docs_repo)}

    as_admin = await client.post(
        "/api/v1/sources/plan", json=body, headers={"authorization": f"Bearer {admin}"}
    )
    for method, path in [
        ("POST", "/api/v1/sources/plan"),
        ("POST", "/api/v1/sources/apply"),
        ("GET", "/api/v1/sources/schema"),
    ]:
        refused = await client.request(
            method, path, json=body, headers={"authorization": f"Bearer {user}"}
        )
        assert (refused.status_code, refused.json()["error"]) == (403, "forbidden"), path

    assert as_admin.status_code == 200, as_admin.text
