"""Private repositories through the whole app: nothing secret is logged, echoed or stored."""

import asyncio
import logging
import stat
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from exactdocs.bootstrap.container import KNOWN_HOSTS_FILE, Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.secret_box import KEY_FILE, FernetSecretBox
from exactdocs.ingestion.adapters.driven.sqlite import SqliteCredentialVault
from exactdocs.ingestion.dtos import EnqueueJobCommand
from exactdocs.ingestion.models import REFRESH_JOB, AccessToken, RefKind
from fixture_repo import DocsRepo

pytestmark = pytest.mark.usefixtures("demo_catalog")
KEY_BODY = "QmFkZ2VyS2V5Qm9keQ0123456789"
KEY = f"-----BEGIN OPENSSH PRIVATE KEY-----\n{KEY_BODY}\n-----END OPENSSH PRIVATE KEY-----"


@pytest.fixture
async def container(demo_catalog: dict[str, str]) -> AsyncIterator[Container]:
    del demo_catalog
    built = Container.build(Settings())
    async with built.running():
        yield built


@pytest.fixture
async def client(
    container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as found,
    ):
        yield found


async def _job(client: httpx.AsyncClient, job_id: str) -> dict:
    for _ in range(3000):
        job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        if job["state"] in {"succeeded", "failed"}:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError


async def test_secrets_never_reach_logs_responses_or_the_database(
    client: httpx.AsyncClient,
    docs_repo: DocsRepo,
    isolated_data_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    token, wrong = docs_repo.token, "wrong-" + docs_repo.token
    texts: list[str] = []

    async def post(path: str, **body: object) -> httpx.Response:
        response = await client.post(path, json=body)
        texts.append(response.text)
        return response

    ok = {"kind": "token", "token": token}
    checked = await post("/api/v1/repositories/check", url=docs_repo.private_url, credential=ok)
    bad = await post(
        "/api/v1/repositories/check",
        url=docs_repo.private_url,
        credential={"kind": "token", "token": wrong},
    )
    not_a_token = await post(  # a malformed body is a 422 that must not echo the secret
        "/api/v1/repositories/check",
        url=docs_repo.private_url,
        credential={"kind": "token", "token": [token], "extra": token},
    )
    insecure = await post(  # over plain http to a non-local host: refused before any contact
        "/api/v1/repositories/check", url="http://git.example.com/a/b.git", credential=ok
    )
    wrong_kind = await post(
        "/api/v1/repositories/check",
        url=docs_repo.private_url,
        credential={"kind": "ssh_key", "private_key": KEY},
    )
    added = await post(
        "/api/v1/libraries",
        url=docs_repo.private_url,
        ref="v1.3.0",
        include_paths=["docs/"],
        credential=ok,
    )
    job = await _job(client, added.json()["job_id"])
    texts += [
        str(job),
        (await client.get("/api/v1/libraries/fixture/docs-repo")).text,
        (await client.get("/api/v1/openapi.json")).text,
    ]

    assert (checked.status_code, bad.status_code) == (200, 422)
    assert bad.json()["error"] == "repository_auth_required"
    assert not_a_token.status_code == 422
    assert (insecure.status_code, insecure.json()["error"]) == (422, "invalid_credential")
    assert (wrong_kind.status_code, wrong_kind.json()["error"]) == (422, "invalid_credential")
    assert (added.status_code, job["state"]) == (201, "succeeded")
    secrets = (token, wrong, KEY_BODY)
    for secret in secrets:
        assert not any(secret in text for text in texts), secret
        assert secret not in caplog.text
        assert secret not in "".join(str(record.__dict__) for record in caplog.records)
        for file in isolated_data_dir.rglob("*"):  # ruff: ignore[blocking-path-method-in-async-function]
            if file.is_file():  # the database, its WAL, the key file's neighbours
                assert secret.encode() not in file.read_bytes(), file


async def test_a_key_file_is_generated_once_and_the_known_hosts_file_is_seeded(
    isolated_data_dir: Path,
) -> None:
    async with Container.build(Settings()).running():
        pass
    key = isolated_data_dir / "secret.key"
    first = key.read_text()

    async with Container.build(Settings()).running():
        pass

    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert key.read_text() == first
    known = isolated_data_dir / KNOWN_HOSTS_FILE
    assert {line.split()[0] for line in known.read_text().splitlines()} >= {
        "github.com",
        "gitlab.com",
        "bitbucket.org",
    }


async def test_with_a_secret_key_in_the_environment_no_key_file_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = tmp_path / "fresh"  # the demo catalog fixture already ran the app on the other one
    monkeypatch.setenv("EXACTDOCS_DATA_DIR", str(fresh))
    monkeypatch.setenv("EXACTDOCS_SECRET_KEY", "e" * 40)

    async with Container.build(Settings()).running():
        pass

    assert fresh.is_dir()
    assert not (fresh / "secret.key").exists()


async def test_removing_a_private_library_deletes_its_stored_credential(
    client: httpx.AsyncClient, container: Container, docs_repo: DocsRepo
) -> None:
    body = {
        "url": docs_repo.private_url,
        "ref": "v1.3.0",
        "include_paths": ["docs/"],
        "credential": {"kind": "token", "token": docs_repo.token},
    }
    added = await client.post("/api/v1/libraries", json=body)
    assert (await _job(client, added.json()["job_id"]))["state"] == "succeeded"
    assert await _stored(container) == 1

    removed = await client.delete("/api/v1/libraries/fixture/docs-repo")

    assert removed.status_code == 200, removed.text
    assert await _stored(container) == 0


async def _stored(container: Container) -> int:
    async with container.engine.connect() as connection:
        statement = text("SELECT count(*) FROM ingestion_library_credentials")
        return (await connection.execute(statement)).scalar_one()


async def test_an_api_token_cannot_send_a_credential_but_may_add_public_docs(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    created = await client.post("/api/v1/tokens", json={"name": "mcp client"})
    bearer = {"Authorization": f"Bearer {created.json()['token']}"}
    credential = {"kind": "token", "token": docs_repo.token}
    url = docs_repo.private_url

    async with httpx.AsyncClient(
        transport=client._transport,  # ruff: ignore[private-member-access]
        base_url="http://localhost",
        headers=bearer,
    ) as api:
        check = await api.post(
            "/api/v1/repositories/check", json={"url": url, "credential": credential}
        )
        add = await api.post("/api/v1/libraries", json={"url": url, "credential": credential})
        version = await api.post(
            "/api/v1/libraries/acme/payments/versions", json={"ref": "v1", "credential": credential}
        )
        public = await api.post("/api/v1/repositories/check", json={"url": docs_repo.http_url})

    assert (check.status_code, add.status_code, version.status_code) == (401, 401, 401)
    assert public.status_code == 200  # no credential: an API token is enough
    assert docs_repo.token not in check.text + add.text + version.text
    assert (await client.get("/api/v1/libraries/fixture/docs-repo")).status_code == 404


async def test_a_session_may_send_a_credential(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    check = await client.post(
        "/api/v1/repositories/check",
        json={
            "url": docs_repo.private_url,
            "credential": {"kind": "token", "token": docs_repo.token},
        },
    )

    assert check.status_code == 200


async def test_a_library_added_again_from_another_host_does_not_inherit_the_old_token(
    client: httpx.AsyncClient, container: Container, docs_repo: DocsRepo
) -> None:
    body = {"ref": "v1.3.0", "include_paths": ["docs/"]}
    first = await client.post(
        "/api/v1/libraries",
        json={
            **body,
            "url": docs_repo.private_url,
            "credential": {"kind": "token", "token": docs_repo.token},
        },
    )
    assert (await _job(client, first.json()["job_id"]))["state"] == "succeeded"
    assert await _stored(container) == 1
    # the library disappears without the removal use case (a restore, a rolled-back add...)
    async with container.engine.begin() as connection:
        await connection.execute(text("DELETE FROM catalog_libraries"))
    before = len(docs_repo.private_seen or [])

    again = await client.post("/api/v1/libraries", json={**body, "url": docs_repo.http_url})

    assert again.status_code == 201, again.text
    assert await _stored(container) == 0
    assert (await _job(client, again.json()["job_id"]))["state"] == "succeeded"
    assert not (docs_repo.private_seen or [])[before:]  # the token's server was never asked


async def test_a_credential_row_of_another_host_makes_the_import_fail_closed(
    client: httpx.AsyncClient, container: Container, docs_repo: DocsRepo
) -> None:
    body = {"ref": "v1.3.0", "include_paths": ["docs/"], "url": docs_repo.http_url}
    added = await client.post("/api/v1/libraries", json=body)
    assert (await _job(client, added.json()["job_id"]))["state"] == "succeeded"
    # a row from before the library moved: sealed for another host
    vault = SqliteCredentialVault(
        container.engine, FernetSecretBox.from_file(container.settings.data_dir / KEY_FILE)
    )
    await vault.save(
        "/fixture/docs-repo", "https://elsewhere.example.com", AccessToken(token="t0ken")
    )

    version = await client.post(
        "/api/v1/libraries/fixture/docs-repo/versions", json={"ref": "v1.4.0"}
    )

    assert (version.status_code, version.json()["error"]) == (422, "credentials_required")


async def test_syncing_and_refreshing_a_private_library_use_its_stored_token(
    client: httpx.AsyncClient, container: Container, docs_repo: DocsRepo
) -> None:
    body = {
        "url": docs_repo.private_url,
        "ref": "main",
        "include_paths": ["docs/"],
        "credential": {"kind": "token", "token": docs_repo.token},
    }
    added = (await client.post("/api/v1/libraries", json=body)).json()
    assert (await _job(client, added["job_id"]))["state"] == "succeeded"
    before = len(docs_repo.private_seen or [])

    synced = await client.post("/api/v1/libraries/fixture/docs-repo/sync")

    assert synced.status_code == 200, synced.text
    assert [v["status"] for v in synced.json()["versions"]] == ["up_to_date"]
    asked = (docs_repo.private_seen or [])[before:]
    assert asked
    assert all(auth and auth.startswith("Basic ") for _, auth in asked[-1:])  # `list_refs` got in
    # a refresh job (what a moved branch queues) fetches with the same stored credential
    job = await container.ingestion.enqueue_job(
        EnqueueJobCommand(
            kind=REFRESH_JOB,
            library=added["library_id"],
            version="main",
            commit_sha=added["commit_sha"],
            ref_kind=RefKind.BRANCH,
        )
    )
    assert (await _job(client, job.id))["state"] == "succeeded"


async def test_previewing_a_private_repository_needs_a_session_and_the_token(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    created = await client.post("/api/v1/tokens", json={"name": "mcp client"})
    bearer = {"Authorization": f"Bearer {created.json()['token']}"}
    credential = {"kind": "token", "token": docs_repo.token}
    body = {"url": docs_repo.private_url, "ref": "v1.4.0", "include_paths": ["docs/"]}

    anonymous = await client.post("/api/v1/repositories/preview", json=body)
    allowed = await client.post(
        "/api/v1/repositories/preview", json={**body, "credential": credential}
    )
    async with httpx.AsyncClient(
        transport=client._transport,  # ruff: ignore[private-member-access]
        base_url="http://localhost",
        headers=bearer,
    ) as api:
        by_token = await api.post(
            "/api/v1/repositories/preview", json={**body, "credential": credential}
        )

    assert anonymous.status_code == 422
    assert anonymous.json()["error"] == "repository_auth_required"
    assert allowed.status_code == 200
    assert "docs/guide/install.md" in allowed.json()["files"]
    assert by_token.status_code == 401
    assert docs_repo.token not in anonymous.text + allowed.text + by_token.text
