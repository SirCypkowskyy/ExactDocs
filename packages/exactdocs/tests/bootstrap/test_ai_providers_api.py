"""RET-01..03, RET-06 over REST and configuration: AI provider profiles, roles, overrides (#241)."""

import logging
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsError

from app_lifespan import serving
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, VersionRef
from exactdocs.identity.dtos import CreateFirstAdminCommand
from fake_llm import FakeGateway, gateway

HORSE = "correct horse battery staple"
PROVIDERS = "/api/v1/ai/providers"
SETTING = "/api/v1/libraries/acme/payments/retrieval"
SECRET = "sk-very-secret-123"


@pytest.fixture
def fake() -> Iterator[FakeGateway]:
    with gateway() as running:
        yield running


@asynccontextmanager
async def _client(
    container: Container, *, sign_in: bool = True
) -> AsyncGenerator[httpx.AsyncClient]:
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        await SqliteLibraryRepository(engine=container.engine).save(
            Library(
                id=LibraryId("/acme/payments"),
                title="Payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                default_branch=VersionRef("main"),
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            if sign_in:
                login = {"username": "ada", "password": HORSE}
                assert (await client.post("/api/v1/session", json=login)).status_code == 201
            yield client


def _settings(fake: FakeGateway, **roles: str) -> Settings:
    return Settings(
        ai=AiSettings.model_validate(
            {
                "providers": {"corp": {"kind": "openai-compatible", "base_url": fake.v1}},
                **{role: {"model": model} for role, model in roles.items()},
            }
        )
    )


async def test_the_provider_routes_need_a_signed_in_admin() -> None:
    async with _client(Container.build(Settings()), sign_in=False) as client:
        assert (await client.get(PROVIDERS)).status_code == 401
        thinking = {"thinking": "low"}
        assert (await client.put("/api/v1/ai/roles/llm", json=thinking)).status_code == 401
        assert (
            await client.post(PROVIDERS, json={"name": "x", "kind": "openai"})
        ).status_code == 401


async def test_a_key_sent_over_rest_is_never_returned_nor_logged(
    fake: FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)  # the SDK and app logs (aiosqlite DEBUG echoes all SQL)
    async with _client(Container.build(Settings())) as client:
        created = await client.post(
            PROVIDERS,
            json={
                "name": "gw",
                "kind": "openai-compatible",
                "base_url": fake.v1,
                "api_key": SECRET,
                "headers": {"X-Team": "header-secret"},
            },
        )
        listed = await client.get(PROVIDERS)
        shown = await client.get(f"{PROVIDERS}/gw")
        checked = await client.post(
            f"{PROVIDERS}/gw/check", json={"role": "embedding", "model": "e5"}
        )

    assert created.status_code == 201, created.text
    for response in (created, listed, shown, checked):
        assert SECRET not in response.text
        assert "header-secret" not in response.text
    assert shown.json()["key"] == "sealed"
    assert shown.json()["header_names"] == ["X-Team"]
    assert checked.json()["checks"][0]["status"] == "ok", checked.text
    assert checked.json()["checks"][0]["dimensions"] == 3
    assert fake.seen[0].headers["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in caplog.text
    assert "header-secret" not in caplog.text


async def test_the_key_is_sealed_in_the_database(fake: FakeGateway) -> None:
    container = Container.build(Settings())
    async with _client(container) as client:
        body = {"name": "gw", "kind": "openai-compatible", "base_url": fake.v1, "api_key": SECRET}
        assert (await client.post(PROVIDERS, json=body)).status_code == 201
        raw = await client.get(PROVIDERS)  # the database is still open here
        database = (container.settings.data_dir / "exactdocs.db").read_bytes()

    assert raw.status_code == 200
    assert SECRET.encode() not in database


async def test_a_configured_profile_is_listed_read_only_and_cannot_be_changed(
    fake: FakeGateway,
) -> None:
    async with _client(Container.build(_settings(fake, llm="corp:gpt-4.1-mini"))) as client:
        listed = (await client.get(PROVIDERS)).json()["providers"]
        changed = await client.put(f"{PROVIDERS}/corp", json={"kind": "openai", "api_key": "x"})
        deleted = await client.delete(f"{PROVIDERS}/corp")
        roles = (await client.get("/api/v1/ai/roles")).json()["roles"]

    assert [(p["name"], p["origin"], p["read_only"], p["roles"]) for p in listed] == [
        ("corp", "configuration", True, ["llm", "judge"])
    ]
    assert (changed.status_code, changed.json()["error"]) == (409, "provider_read_only")
    assert (deleted.status_code, deleted.json()["error"]) == (409, "provider_read_only")
    assert {r["role"]: (r["model"], r["source"]) for r in roles} == {
        "embedding": (None, None),
        "reranker": (None, None),
        "llm": ("corp:gpt-4.1-mini", "instance"),
        "judge": ("corp:gpt-4.1-mini", "llm"),
    }


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "google-vertex", "project": "p", "location": "l", "credentials": "adc"},
        {
            "kind": "google-vertex",
            "project": "p",
            "location": "l",
            "credentials_file": "/etc/passwd",
        },
        {"kind": "azure", "resource": "acme", "api_version": "v", "auth": "entra"},
        {"kind": "anthropic", "platform": "foundry", "resource": "acme", "auth": "entra"},
        {
            "kind": "anthropic",
            "platform": "vertex",
            "project": "p",
            "location": "l",
            "credentials": "adc",
        },
        {"kind": "anthropic", "platform": "bedrock", "location": "eu-central-1"},
    ],
    ids=["adc", "credentials file", "azure entra", "foundry entra", "claude on vertex", "bedrock"],
)
async def test_the_servers_cloud_identity_cannot_be_used_over_rest(
    body: dict, fake: FakeGateway
) -> None:
    async with _client(Container.build(Settings())) as client:
        created = await client.post(PROVIDERS, json={"name": "cloud", **body})
        with_url = await client.post(
            PROVIDERS, json={"name": "cloud", **body, "base_url": fake.url}
        )
        listed = await client.get(PROVIDERS)

    for response in (created, with_url):
        assert response.status_code == 422, response.text
        assert response.json()["error"] == "invalid_provider"
        assert "environment or the configuration file" in response.json()["detail"]
    assert listed.json()["providers"] == []
    assert fake.seen == []  # no token, nor any call, reached a host of the caller's choosing


async def test_a_credential_header_is_refused_over_rest_and_in_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _client(Container.build(Settings())) as client:
        response = await client.post(
            PROVIDERS,
            json={
                "name": "gw",
                "kind": "openai-compatible",
                "base_url": "https://gw.example.com/v1",
                "headers": {"X-Portkey-Api-Key": "sk-in-a-header"},
            },
        )
    assert response.status_code == 422
    assert "use the key field" in response.json()["detail"]
    assert "sk-in-a-header" not in response.text

    config = tmp_path / "exactdocs.toml"
    config.write_text(
        '[ai.providers.gw]\nkind = "openai-compatible"\nbase_url = "https://gw.example.com/v1"\n'
        'headers = { "Authorization" = "Bearer sk-in-the-file" }\n'
    )
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(config))
    with pytest.raises(StartupError, match="use the key field") as error:
        Container.build(Settings())
    assert "sk-in-the-file" not in str(error.value)


@pytest.mark.parametrize("injection", ["evil.example/x?", "a.evil.com", "x@evil", "x%2Fevil"])
async def test_a_resource_that_would_change_the_host_is_refused_over_rest(injection: str) -> None:
    body = {
        "name": "az",
        "kind": "azure",
        "resource": injection,
        "api_version": "v",
        "api_key": "k",
    }
    async with _client(Container.build(Settings())) as client:
        response = await client.post(PROVIDERS, json=body)

    assert response.status_code == 422, response.text
    assert "resource must be a single name" in response.json()["detail"]


async def test_an_invalid_profile_is_refused_with_its_reason() -> None:
    async with _client(Container.build(Settings())) as client:
        response = await client.post(PROVIDERS, json={"name": "gw", "kind": "openai-compatible"})
        groq = await client.post(PROVIDERS, json={"name": "g", "kind": "groq", "api_key": "k"})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_provider"
    assert "base_url" in response.json()["detail"]
    assert "openai-compatible" in groq.json()["detail"]


async def test_a_profile_edited_over_rest_counts_at_the_next_check(fake: FakeGateway) -> None:
    async with _client(Container.build(Settings())) as client:
        body = {"name": "gw", "kind": "openai-compatible", "base_url": fake.url + "/broken/v1"}
        await client.post(PROVIDERS, json=body)
        check = {"role": "llm", "model": "m"}
        before = (await client.post(f"{PROVIDERS}/gw/check", json=check)).json()["checks"][0]

        fixed = await client.put(
            f"{PROVIDERS}/gw", json={"kind": "openai-compatible", "base_url": fake.v1}
        )
        after = (await client.post(f"{PROVIDERS}/gw/check", json=check)).json()["checks"][0]
        deleted = await client.delete(f"{PROVIDERS}/gw")
        gone = await client.get(f"{PROVIDERS}/gw")

    assert before["status"] == "error"
    assert fixed.status_code == 200, fixed.text
    assert after["status"] == "ok", after
    assert deleted.status_code == 204
    assert (gone.status_code, gone.json()["error"]) == (404, "unknown_provider")


async def test_a_library_can_turn_ai_off_and_choose_its_own_llm(fake: FakeGateway) -> None:
    container = Container.build(_settings(fake, embedding="corp:e5", llm="corp:gpt"))
    async with _client(container) as client:
        own = await client.put(SETTING, json={"llm": "corp:small", "judge": "corp:o3"})
        off = await client.put(SETTING, json={"ai_enabled": False})
        embedding = await client.put(SETTING, json={"embedding": "corp:other"})
        unknown = await client.put(SETTING, json={"llm": "ghost:gpt"})

    assert own.status_code == 200, own.text
    assert (own.json()["llm"], own.json()["judge"]) == ("corp:small", "corp:o3")
    assert own.json()["configured_roles"] == ["embedding", "llm", "judge"]
    assert (off.json()["ai_enabled"], off.json()["configured_roles"]) == (False, [])
    assert off.json()["effective_mode"] == "bm25"
    assert embedding.status_code == 422  # instance-wide only: not a field here
    assert (unknown.status_code, unknown.json()["error"]) == (404, "unknown_provider")


async def test_an_instance_roles_thinking_level_is_set_over_rest_and_used_by_the_check(
    fake: FakeGateway,
) -> None:
    container = Container.build(_settings(fake, llm="corp:writer"))
    async with _client(container) as client:
        reranker = await client.put("/api/v1/ai/roles/reranker", json={"thinking": "low"})
        bogus = await client.put("/api/v1/ai/roles/llm", json={"thinking": "max"})
        saved = await client.put("/api/v1/ai/roles/llm", json={"thinking": "low"})
        shown = (await client.get("/api/v1/ai/roles")).json()["roles"]
        await client.post(f"{PROVIDERS}/corp/check")
        cleared = await client.put("/api/v1/ai/roles/llm", json={"thinking": None})

    assert (reranker.status_code, reranker.json()["error"]) == (422, "role_takes_no_thinking")
    assert bogus.status_code == 422
    assert saved.status_code == 200, saved.text
    assert (saved.json()["thinking"], saved.json()["thinking_configured"]) == ("low", False)
    llm, judge = (next(r for r in shown if r["role"] == name) for name in ("llm", "judge"))
    assert (llm["thinking"], judge["thinking"]) == ("low", "low")  # the judge is the LLM
    calls = [s.body for s in fake.seen if s.path.endswith("/chat/completions")]
    assert [c["reasoning_effort"] for c in calls] == ["low", "low"], calls
    assert cleared.json()["thinking"] is None


# ---------------------------------------------------------------- configuration


def test_the_toml_file_configures_providers_and_the_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "exactdocs.toml"
    config.write_text(
        """
[ai.providers.corp]
kind = "openai-compatible"
base_url = "https://llm.example.com/v1"
api_key_file = "/run/secrets/corp"
headers = { "X-Team" = "docs" }
request_timeout = 30

[ai.llm]
model = "corp:gpt-4.1-mini"

[ai.embedding]
model = "corp:text-embedding-3-small"
dimensions = 1024
"""
    )
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(config))
    monkeypatch.setenv("EXACTDOCS_AI__LLM__MODEL", "corp:o3")
    monkeypatch.setenv("EXACTDOCS_AI__PROVIDERS__CORP__REQUEST_TIMEOUT", "12")

    ai = Settings().ai

    corp = ai.providers["corp"]
    assert (corp.base_url, corp.headers, corp.request_timeout) == (
        "https://llm.example.com/v1",
        {"X-Team": "docs"},
        12,
    )
    assert (ai.llm.model, ai.embedding.model) == ("corp:o3", "corp:text-embedding-3-small")


@pytest.mark.parametrize(
    "content",
    [
        '[ai.providers.corp]\nkind = "openai"\napi_key = "sk-in-the-file"\n',
        'secret_key = "a-secret-key-of-at-least-32-characters"\n',
    ],
    ids=["provider key", "secret key"],
)
def test_the_toml_file_refuses_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    config = tmp_path / "exactdocs.toml"
    config.write_text(content)
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(config))

    with pytest.raises(SettingsError, match="secrets") as error:
        Settings()

    assert "sk-in-the-file" not in str(error.value)


def test_a_missing_toml_file_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(tmp_path / "none.toml"))

    with pytest.raises(SettingsError, match="cannot be read"):
        Settings()


def test_an_invalid_configured_profile_stops_the_start() -> None:
    settings = Settings(
        ai=AiSettings.model_validate({"providers": {"corp": {"kind": "openai-compatible"}}})
    )

    with pytest.raises(StartupError, match="needs base_url"):
        Container.build(settings)


def test_a_role_not_written_profile_colon_model_stops_the_start() -> None:
    settings = Settings(ai=AiSettings.model_validate({"llm": {"model": "gpt-4.1"}}))

    with pytest.raises(StartupError, match="<profile>:<model>"):
        Container.build(settings)
