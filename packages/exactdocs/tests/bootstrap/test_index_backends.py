"""#352: choosing, opening and reporting the external search and vector backends.

The default keeps every index in the database. A backend is named by
``EXACTDOCS_SEARCH_BACKEND`` / ``EXACTDOCS_VECTOR_BACKEND`` and configured under
``[index_backends.<name>]``; an unknown one, a missing extra, invalid options, or one that does
not answer at start stop the instance with a message naming it. ``/healthz`` names the backends
and how many versions the last comparison with the database found drifted.
"""

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsError

from exactdocs.bootstrap.constants import INDEX_BACKENDS, LIVENESS_PATH, LOCAL_COMMANDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.index_backends import IndexBackends, build_index_backends
from exactdocs.bootstrap.index_kinds import IndexBackendKind
from exactdocs.bootstrap.settings import Settings, read_config_file
from exactdocs.retrieval.adapters.driven.memory_index import (
    InMemorySearchBackend,
    InMemoryVectorBackend,
)

FAKE_MODULE = "exactdocs_test_fake_backend"


@pytest.fixture
def fake_adapter() -> Iterator[types.ModuleType]:
    """An importable adapter module whose factory refuses an option, as a real one validates."""
    module = types.ModuleType(FAKE_MODULE)

    def build(options: dict[str, object]) -> InMemorySearchBackend:
        if "url" not in options:
            message = "url is required"
            raise ValueError(message)
        return InMemorySearchBackend(name="fake")

    vars(module)["build"] = build
    sys.modules[FAKE_MODULE] = module
    yield module
    del sys.modules[FAKE_MODULE]


# ---------------------------------------------------------------- settings


def test_every_index_lives_in_the_database_by_default() -> None:
    settings = Settings()

    assert (settings.search_backend, settings.vector_backend) == ("database", "database")
    assert build_index_backends(settings) == IndexBackends()


def test_a_registered_backend_is_named_in_any_letter_case() -> None:
    settings = Settings(search_backend=" Memory ", vector_backend="MEMORY")

    backends = build_index_backends(settings)

    assert isinstance(backends.search, InMemorySearchBackend)
    assert isinstance(backends.vectors, InMemoryVectorBackend)
    assert backends.names == ("memory", "memory")


def test_an_unknown_backend_is_refused_naming_the_known_ones() -> None:
    with pytest.raises(
        ValidationError, match=r"EXACTDOCS_SEARCH_BACKEND='qdrnt'.*database, (.*, )?memory"
    ):
        Settings(search_backend="qdrnt")


def test_the_environment_names_the_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_SEARCH_BACKEND", "memory")
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__MEMORY__COLLECTION", "docs")

    settings = Settings()

    assert settings.search_backend == "memory"
    assert settings.index_backends == {"memory": {"collection": "docs"}}


def test_the_configuration_file_may_not_hold_a_backend_secret(tmp_path: Path) -> None:
    config = tmp_path / "exactdocs.toml"
    config.write_text(
        '[index_backends.qdrant]\nurl = "http://qdrant:6333"\napi_key = "s3cret"\n'
        'api_key_file = "/run/secrets/qdrant"\n',
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match=r"index_backends\.qdrant\.api_key\b") as refused:
        read_config_file(config)

    assert "api_key_file" not in str(refused.value).split("(")[1].split(")")[0]


def test_the_registry_names_a_module_and_a_factory_per_index() -> None:
    for name, kind in INDEX_BACKENDS.items():
        assert kind.name == name
        assert kind.search or kind.vectors
        assert kind.module.startswith("exactdocs.retrieval.adapters.driven.")


# ---------------------------------------------------------------- building and opening


def test_a_backend_whose_extra_is_missing_says_which_extra_to_install() -> None:
    kinds = {
        "qdrant": IndexBackendKind(
            name="qdrant",
            module="exactdocs.retrieval.adapters.driven.not_installed_here",
            search="search_backend",
            vectors=None,
            extra="qdrant",
            packages=("qdrant_client",),
        )
    }
    settings = Settings.model_construct(
        search_backend="qdrant", vector_backend="database", index_backends={}
    )

    with pytest.raises(StartupError, match=r"pip install 'exactdocs\[qdrant\]'"):
        build_index_backends(settings, kinds)


def test_invalid_options_stop_the_start_naming_the_table(fake_adapter: types.ModuleType) -> None:
    del fake_adapter
    kinds = {
        "fake": IndexBackendKind(name="fake", module=FAKE_MODULE, search="build", vectors=None)
    }
    settings = Settings.model_construct(
        search_backend="fake", vector_backend="database", index_backends={}
    )

    with pytest.raises(StartupError, match=r"\[index_backends\.fake\].*url is required"):
        build_index_backends(settings, kinds)
    with pytest.raises(StartupError, match="no backend that can hold the vectors index"):
        build_index_backends(
            Settings.model_construct(
                search_backend="database", vector_backend="fake", index_backends={}
            ),
            kinds,
        )
    good = Settings.model_construct(
        search_backend="fake", vector_backend="database", index_backends={"fake": {"url": "x"}}
    )
    assert build_index_backends(good, kinds).names == ("fake", "database")


async def test_a_backend_that_does_not_answer_stops_the_start_naming_it(tmp_path: Path) -> None:
    container = Container.build(
        Settings(data_dir=tmp_path),
        index_backends=IndexBackends(vectors=InMemoryVectorBackend(unavailable=True)),
    )

    with pytest.raises(StartupError, match=r"vector backend 'memory'.*unreachable") as stopped:
        async with container.running(jobs=False):
            pytest.fail("the instance started")

    assert "EXACTDOCS_VECTOR_BACKEND=database" in str(stopped.value)


# ---------------------------------------------------------------- liveness


async def _health(container: Container, *, check: bool) -> dict[str, object]:
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        if check:
            assert container.drift is not None
            await container.drift.once()
        return (await client.get(LIVENESS_PATH)).json()


async def test_liveness_names_the_backends_and_the_versions_that_drifted(tmp_path: Path) -> None:
    container = Container.build(Settings(data_dir=tmp_path, search_backend="memory"))

    before = await _health(container, check=False)
    assert (before["search_backend"], before["vector_backend"]) == ("memory", "database")
    assert before["index_versions_missing"] is None  # no comparison has ended yet

    again = Container.build(Settings(data_dir=tmp_path, search_backend="memory"))
    assert (await _health(again, check=True))["index_versions_missing"] == 0


async def test_liveness_without_external_backends(tmp_path: Path) -> None:
    body = await _health(Container.build(Settings(data_dir=tmp_path)), check=False)

    assert (body["search_backend"], body["vector_backend"]) == ("database", "database")
    assert body["index_versions_missing"] is None


def test_the_index_commands_are_local() -> None:
    assert {"index check", "index rebuild"} <= LOCAL_COMMANDS
