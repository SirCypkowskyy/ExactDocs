"""Push webhooks over HTTP: the secret routes, the route forges push to, and refusals."""

import hashlib
import hmac
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.ingestion.constants import MAX_WEBHOOK_BYTES

pytestmark = pytest.mark.usefixtures("demo_catalog")

SETTINGS = "/api/v1/libraries/acme/payments/webhook"
HOOK = "/api/v1/webhooks/acme/payments"
PUSH = json.dumps({"ref": "refs/heads/main", "deleted": False}).encode()


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running(jobs=False):  # the push jobs stay queued: no git is asked
        yield container


@pytest.fixture
async def client(
    container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)),
        base_url="http://localhost",
        cookies=demo_catalog,
    ) as client:
        yield client


@pytest.fixture
async def forge(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """A forge: no session, no token."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    ) as forge:
        yield forge


def github(secret: str | None, *, delivery: str = "d-1", body: bytes = PUSH) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery,
    }
    if secret is not None:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={digest}"
    return headers


async def push_jobs(client: httpx.AsyncClient) -> list[dict]:
    jobs = (await client.get("/api/v1/libraries/acme/payments/jobs")).json()["jobs"]
    return [j for j in jobs if j["kind"] == "push"]


async def test_the_secret_is_shown_once_and_rotating_replaces_it(
    client: httpx.AsyncClient, forge: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    off = await client.get(SETTINGS)
    assert (off.status_code, off.json()) == (
        200,
        {"library": "/acme/payments", "enabled": False, "url": None, "created_at": None},
    )

    created = await client.put(SETTINGS)

    assert created.status_code == 200, created.text
    body = created.json()
    secret = body["secret"]
    assert len(secret) == 43
    assert body["url"] == f"http://localhost{HOOK}"
    read = (await client.get(SETTINGS)).json()
    assert read == {k: body[k] for k in ("library", "enabled", "url", "created_at")}
    assert secret not in (await client.get(SETTINGS)).text

    rotated = (await client.put(SETTINGS)).json()["secret"]
    old = await forge.post(HOOK, content=PUSH, headers=github(secret))
    new = await forge.post(HOOK, content=PUSH, headers=github(rotated))

    assert (old.status_code, new.status_code) == (401, 202)
    assert new.json() == {"status": "queued", "job_ids": [new.json()["job_ids"][0]]}
    assert secret not in caplog.text
    assert rotated not in caplog.text

    gone = await client.delete(SETTINGS)
    assert gone.json()["enabled"] is False
    assert (
        await forge.post(HOOK, content=PUSH, headers=github(rotated, delivery="d-2"))
    ).status_code == 401


async def test_the_secret_routes_need_a_session_not_a_token(
    client: httpx.AsyncClient, forge: httpx.AsyncClient
) -> None:
    token = (await client.post("/api/v1/tokens", json={"name": "ci"})).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}

    anonymous = [await forge.request(m, SETTINGS) for m in ("GET", "PUT", "DELETE")]
    with_token = [
        await forge.request(m, SETTINGS, headers=bearer) for m in ("GET", "PUT", "DELETE")
    ]

    assert [a.status_code for a in anonymous + with_token] == [401] * 6
    assert (await client.get(SETTINGS)).json()["enabled"] is False


async def test_a_signed_in_user_who_is_not_an_operator_gets_403(
    client: httpx.AsyncClient, forge: httpx.AsyncClient
) -> None:
    bob = {"username": "bob", "password": "bob's long passphrase"}
    assert (await client.post("/api/v1/users", json=bob)).status_code == 201
    signed_in = await forge.post("/api/v1/session", json=bob)
    assert signed_in.status_code == 201, signed_in.text
    cookie = {"cookie": f"{SESSION_COOKIE}={signed_in.cookies[SESSION_COOKIE]}"}
    forge.cookies.clear()

    answers = [await forge.request(m, SETTINGS, headers=cookie) for m in ("GET", "PUT", "DELETE")]

    assert [(a.status_code, a.json()["error"]) for a in answers] == [(403, "forbidden")] * 3
    assert (await client.get(SETTINGS)).json()["enabled"] is False


async def test_an_unknown_library_has_no_webhook_settings(client: httpx.AsyncClient) -> None:
    assert (await client.put("/api/v1/libraries/acme/unknown/webhook")).status_code == 404


async def test_every_refusal_is_the_same_401(
    client: httpx.AsyncClient, forge: httpx.AsyncClient
) -> None:
    secret = (await client.put(SETTINGS)).json()["secret"]

    answers = [
        await forge.post(HOOK, content=PUSH, headers=github(None)),
        await forge.post(HOOK, content=PUSH, headers=github(secret[::-1])),
        # /acme/ledger exists but has no webhook secret.
        await forge.post("/api/v1/webhooks/acme/ledger", content=PUSH, headers=github(secret)),
        await forge.post("/api/v1/webhooks/acme/unknown", content=PUSH, headers=github(secret)),
        await forge.post(HOOK, content=PUSH, headers=github(secret, delivery="d-ok")),
    ]
    no_forge = await forge.post(
        HOOK, content=PUSH, headers={"X-Hub-Signature-256": github(secret)["X-Hub-Signature-256"]}
    )

    refused = [*answers[:4], no_forge]
    assert {a.status_code for a in refused} == {401}
    assert len({a.content for a in refused}) == 1
    assert refused[0].json()["error"] == "invalid_signature"
    assert answers[4].status_code == 202  # the signed one, for contrast
    assert len(await push_jobs(client)) == 1


async def test_a_body_above_the_cap_is_413_before_any_lookup(forge: httpx.AsyncClient) -> None:
    big = b"x" * (MAX_WEBHOOK_BYTES + 1)

    known = await forge.post(HOOK, content=big, headers=github(None))
    unknown = await forge.post("/api/v1/webhooks/acme/unknown", content=big, headers=github(None))

    assert (known.status_code, unknown.status_code) == (413, 413)
    assert known.content == unknown.content


async def test_a_redelivery_is_a_duplicate_and_queues_one_job(
    client: httpx.AsyncClient, forge: httpx.AsyncClient
) -> None:
    secret = (await client.put(SETTINGS)).json()["secret"]

    first = await forge.post(HOOK, content=PUSH, headers=github(secret))
    again = await forge.post(HOOK, content=PUSH, headers=github(secret))

    assert (first.status_code, first.json()["status"]) == (202, "queued")
    assert (again.status_code, again.json()) == (202, {"status": "duplicate", "job_ids": []})
    (job,) = await push_jobs(client)
    assert (job["version"], job["state"]) == ("main", "queued")


async def test_a_burst_of_pushes_queues_one_push_job(
    client: httpx.AsyncClient, forge: httpx.AsyncClient
) -> None:
    secret = (await client.put(SETTINGS)).json()["secret"]

    answers = [
        await forge.post(HOOK, content=PUSH, headers=github(secret, delivery=f"d-{i}"))
        for i in range(4)
    ]

    assert {(a.status_code, a.json()["status"]) for a in answers} == {(202, "queued")}
    assert len(await push_jobs(client)) == 1


async def test_an_untracked_ref_is_ignored_and_a_signed_delivery_needs_an_id(
    client: httpx.AsyncClient, forge: httpx.AsyncClient
) -> None:
    secret = (await client.put(SETTINGS)).json()["secret"]
    feature = json.dumps({"ref": "refs/heads/feature"}).encode()
    no_id = {k: v for k, v in github(secret).items() if k != "X-GitHub-Delivery"}

    ignored = await forge.post(HOOK, content=feature, headers=github(secret, body=feature))
    missing = await forge.post(HOOK, content=PUSH, headers=no_id)

    assert (ignored.status_code, ignored.json()["status"]) == (202, "ignored")
    assert (missing.status_code, missing.json()["error"]) == (400, "missing_delivery_id")
    assert await push_jobs(client) == []


async def test_removing_the_library_removes_its_secret(
    client: httpx.AsyncClient, container: Container
) -> None:
    await client.put(SETTINGS)

    removed = await client.delete("/api/v1/libraries/acme/payments")

    assert removed.status_code == 200, removed.text
    async with container.engine.connect() as connection:
        left = await connection.execute(text("SELECT count(*) FROM ingestion_webhooks"))
        assert left.scalar() == 0
