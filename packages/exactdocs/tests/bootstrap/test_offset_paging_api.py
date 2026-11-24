"""Every paged list over HTTP jumps to any page with `offset` (#509), on both databases.

A page at an offset is the slice of the cursor walk with the same sort and filters, `total` does
not change, its `next_cursor` goes on from it, and `offset` with `cursor` is refused.
"""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, Version, VersionRef
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
)
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.models import Account, AccountId, Role, Session, Username, hash_token
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.models import Job, JobId
from exactdocs_kernel import MAX_OFFSET

START = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)
PAYMENTS = "/api/v1/libraries/acme/payments"
COOKIE = "offset-paging-session"
NOT_A_HASH = "not-a-hash"  # nobody signs in with a password: the session is planted

# (path, key of the items, the sort and filters of the walk)
LISTS = [
    pytest.param("/api/v1/libraries", "libraries", {"sort": "-version_count"}, id="libraries"),
    pytest.param(
        f"{PAYMENTS}/versions", "versions", {"kind": "tag", "sort": "-imported_at"}, id="versions"
    ),
    pytest.param("/api/v1/jobs", "jobs", {"sort": "kind"}, id="jobs"),
    pytest.param(f"{PAYMENTS}/jobs", "jobs", {"state": "succeeded"}, id="library jobs"),
    pytest.param(
        f"{PAYMENTS}/articles",
        "articles",
        {"ref": "main", "q": "guide", "sort": "-size"},
        id="articles",
    ),
    pytest.param("/api/v1/users", "users", {"sort": "-role"}, id="users"),
    pytest.param("/api/v1/tokens", "tokens", {"q": "-", "sort": "name"}, id="tokens"),
    pytest.param(f"{PAYMENTS}/grants", "grants", {"sort": "subject"}, id="grants"),
    pytest.param("/api/v1/access-log", "events", {"change": "granted"}, id="access log"),
    pytest.param(f"{PAYMENTS}/access-log", "events", {}, id="library access log"),
]


def version(ref: str, hour: int) -> Version:
    return Version(
        ref=VersionRef(ref),
        kind=RefKind.TAG if ref.startswith("v") else RefKind.BRANCH,
        commit_sha=hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest(),
        imported_at=START + timedelta(hours=hour),
    )


def library(name: str, *refs: str) -> Library:
    return Library(
        id=LibraryId(f"/acme/{name}"),
        title=name.title(),
        source_url=f"https://git.example.com/acme/{name}.git",
        host=HostKind.GIT,
        default_branch=VersionRef("main"),
        versions=frozenset(version(ref, n % 3) for n, ref in enumerate(refs)),
    )


def account(n: int, name: str, role: Role) -> Account:
    return Account(
        id=AccountId(f"{n + 1:032d}"),
        username=Username(name),
        password_hash=NOT_A_HASH,
        role=role,
        created_at=START + timedelta(minutes=n),
    )


async def seed_catalog_and_jobs(container: Container) -> None:
    """Libraries, versions, jobs and articles, with ties in every sort."""
    libraries = SqliteLibraryRepository(engine=container.engine)
    for lib in [
        library("payments", "main", "next", *(f"v1.{n}.0" for n in range(7))),
        library("ledger", "main"),
        library("audit", "main"),
        library("billing", "main", "v2.0.0"),
        library("empty"),
        library("notes"),
    ]:
        await libraries.save(lib)
    jobs = SqliteJobRepository(engine=container.engine)
    for n in range(12):
        job = Job.queued(
            job_id=JobId(f"job-{n:02d}"),
            kind=JobKind(("import", "embed", "rechunk")[n % 3]),
            library=("/acme/payments", "/acme/ledger")[n % 2 if n < 6 else 0],
            version=None,
            now=START + timedelta(minutes=n),
        )
        await jobs.add(job.started(job.created_at).succeeded(job.created_at) if n % 4 else job)
    paths = ["guide/a.md", "guide/b.md", "api/c.md", "guide/d.md", "guide/e.md", "guide/f.md"]
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library="/acme/payments",
            ref="main",
            kind=RefKind.BRANCH,
            commit_sha="c" * 40,
            articles=[
                ArticleIn(
                    path=path,
                    blob_sha=hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest(),
                    content_version=1,
                    title=path,
                    content="x" * (n % 3 + 1),
                )
                for n, path in enumerate(paths)
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def seed_identity(container: Container, client: httpx.AsyncClient) -> None:
    """The operator `ada` signed in, five more accounts, their grants and `ada`'s tokens."""
    accounts = SqliteAccountRepository(engine=container.engine)
    ada = account(0, "ada", Role.ADMIN)
    assert await accounts.add_first(ada)
    now = datetime.now(UTC)
    session = Session(
        token_hash=hash_token(COOKIE), account_id=ada.id, created_at=now, last_used_at=now
    )
    await SqliteSessionRepository(engine=container.engine).add(session)
    client.cookies.set(SESSION_COOKIE, COOKIE)
    for n, name in enumerate(("dave", "carol", "bob", "erin", "frank"), start=1):
        assert await accounts.add(account(n, name, Role.ADMIN if n % 2 else Role.USER))
        grant = {"kind": "user", "subject": name, "role": ("viewer", "contributor")[n % 2]}
        assert (await client.put(f"{PAYMENTS}/grants", json=grant)).status_code == 200
    group = {"kind": "group", "subject": "writers", "role": "viewer"}
    assert (await client.put(f"{PAYMENTS}/grants", json=group)).status_code == 200
    for name in ("ci-main", "ci-nightly", "desk-2", "laptop-1", "laptop-2", "phone"):
        assert (await client.post("/api/v1/tokens", json={"name": name})).status_code == 201


@pytest.fixture(params=SQL_BACKENDS)
async def client(request: pytest.FixtureRequest) -> AsyncIterator[httpx.AsyncClient]:
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    transport = httpx.ASGITransport(app=create_app(container))
    # ASGITransport does not run the app's lifespan, which migrates the database. No worker:
    # the queued jobs must stay queued.
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        await seed_catalog_and_jobs(container)
        await seed_identity(container, client)
        yield client


async def page(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def cursor_walk(
    client: httpx.AsyncClient, path: str, key: str, params: dict[str, str]
) -> list[dict[str, Any]]:
    found, totals, cursor = [], set(), None
    while True:
        body = await page(client, path, **params, limit=2, **({"cursor": cursor} if cursor else {}))
        found += body[key]
        totals.add(body["total"])
        if (cursor := body["next_cursor"]) is None:
            break
    assert totals == {len(found)}, totals
    return found


@pytest.mark.parametrize(("path", "key", "params"), LISTS)
async def test_a_page_at_an_offset_is_the_slice_of_the_cursor_walk(
    client: httpx.AsyncClient, path: str, key: str, params: dict[str, str]
) -> None:
    walked = await cursor_walk(client, path, key, params)
    assert len(walked) > 3

    for offset in range(len(walked) + 2):
        body = await page(client, path, **params, limit=3, offset=offset)

        assert body[key] == walked[offset : offset + 3], offset
        assert body["total"] == len(walked)
        assert (body["next_cursor"] is None) == (offset + 3 >= len(walked))
    after = await page(client, path, **params, limit=2, offset=1)
    rest = await page(client, path, **params, limit=2, cursor=after["next_cursor"])
    assert rest[key] == walked[3:5]
    deepest = await page(client, path, **params, offset=MAX_OFFSET)
    assert (deepest[key], deepest["next_cursor"], deepest["total"]) == ([], None, len(walked))


@pytest.mark.parametrize(("path", "key", "params"), LISTS)
async def test_an_offset_with_a_cursor_or_out_of_bounds_is_a_422(
    client: httpx.AsyncClient, path: str, key: str, params: dict[str, str]
) -> None:
    first = await page(client, path, **params, limit=1)
    assert first[key]

    both = await client.get(
        path, params={**params, "limit": 1, "cursor": first["next_cursor"], "offset": 0}
    )

    assert (both.status_code, both.json()["error"]) == (422, "cursor_with_offset")
    for offset in (-1, MAX_OFFSET + 1, "two"):
        refused = await client.get(path, params={**params, "offset": offset})
        assert (refused.status_code, refused.json()["error"]) == (422, "validation_error")
        assert [field["loc"] for field in refused.json()["fields"]] == [["query", "offset"]]
