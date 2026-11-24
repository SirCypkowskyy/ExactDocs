"""#358: libSQL as the search and vector backend, beyond the shared contract suites.

The shared suites (``test_search_index.py``, ``test_vector_index.py``, ``test_index_backends.py``)
run on a libSQL server (``EXACTDOCS_TEST_LIBSQL_URL``) and on a local file (with the ``libsql``
package). Here: the options and URLs it takes, that the vectors sit in libSQL's own vector type and
index, that a small version of a big space still finds its nearest chunks, the server's auth, and
what happens when another process changed the tables.
"""

import importlib.util
import secrets
import sqlite3
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _pytest.mark import ParameterSet
from pydantic_settings import SettingsError

import integration
import libsql_backends
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.index_backends import IndexBackends, build_index_backends
from exactdocs.bootstrap.settings import Settings, read_config_file
from exactdocs.retrieval.adapters.driven.libsql_index import (
    LibsqlSearchBackend,
    LibsqlVectorBackend,
    _FileEngine,
    _HttpEngine,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs.retrieval.models import (
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    HeldVersion,
    IndexedManifest,
    IndexEntry,
    SpaceState,
    TagFilter,
)

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
NO_TAGS = TagFilter()


def manifest(manifest_id: str) -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{LIB}/{manifest_id}", library=LIB, indexed_at=T0
    )


def entry(version: IndexedManifest, chunk: str, vector: tuple[float, ...]) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", chunk),
        content=f"about {chunk}",
        tags=(),
        vector=vector,
    )


def space(dimensions: int = 3, space_id: int = 1) -> EmbeddingSpace:
    return EmbeddingSpace(
        id=EmbeddingSpaceId(space_id),
        spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=dimensions),
        state=SpaceState.ACTIVE,
        created_at=T0,
    )


# ---------------------------------------------------------------- options


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({}, "url is required"),
        ({"url": "http://h", "colection": "x"}, "unknown option.*colection"),
        ({"url": "ws://h"}, "url must be libsql://"),
        ({"url": "postgres://h/db"}, "url must be libsql://"),
        ({"url": "https://h/db"}, "server only"),
        ({"url": "https://u:p@h"}, "server only"),
        ({"url": "http://h", "prefix": "1x"}, "prefix must start with a letter"),
        ({"url": "http://h", "prefix": "a;DROP"}, "prefix must start with a letter"),
        ({"url": "http://h", "compress_neighbors": "float7"}, "compress_neighbors must be"),
        ({"url": "http://h", "max_neighbors": "2.5"}, "whole number"),
        ({"url": "http://h", "timeout": "0"}, "timeout must be a positive number"),
        ({"url": "http://h", "timeout": True}, "timeout must be a positive number"),
        ({"url": "http://h", "auth_token": "t", "auth_token_file": "/f"}, "not both"),
    ],
)
def test_invalid_options_are_refused(options: dict[str, object], message: str) -> None:
    for factory in (search_backend, vector_backend):
        with pytest.raises(ValueError, match=message):
            factory(options)


def test_a_url_is_text() -> None:
    with pytest.raises(TypeError, match="url must be text"):
        vector_backend({"url": 8080})


@pytest.mark.parametrize(
    ("url", "reached"),
    [
        ("libsql://db-acme.turso.io", "https://db-acme.turso.io"),
        ("libsql://sqld:8080?tls=0", "http://sqld:8080"),
        ("https://db.example.com/", "https://db.example.com"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
    ],
)
def test_a_server_is_reached_over_http(url: str, reached: str) -> None:
    backend = vector_backend({"url": url, "auth_token": "tok", "timeout": "3"})

    assert isinstance(backend.engine, _HttpEngine)
    assert (backend.engine.url, backend.engine.token, backend.engine.timeout) == (reached, "tok", 3)
    assert "tok" not in repr(backend)


def test_the_token_can_come_from_a_file(tmp_path: Path) -> None:
    secret = tmp_path / "token"
    secret.write_text("from-file\n", encoding="utf-8")

    backend = search_backend({"url": "libsql://db", "auth_token_file": str(secret)})

    assert isinstance(backend.engine, _HttpEngine)
    assert backend.engine.token == "from-file"


def test_an_unreadable_token_file_is_refused_without_its_content(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"auth_token_file cannot be read \(FileNotFoundError\)"):
        search_backend({"url": "libsql://db", "auth_token_file": str(tmp_path / "none")})


@pytest.mark.skipif(not libsql_backends.HAS_DRIVER, reason="needs the libsql package")
@pytest.mark.parametrize("url", ["file:{path}", "file://{path}", "{path}"])
def test_a_file_is_libsql_embedded(url: str, tmp_path: Path) -> None:
    path = tmp_path / "index.db"

    backend = vector_backend({"url": url.format(path=path)})

    assert isinstance(backend.engine, _FileEngine)
    assert backend.engine.path == str(path)


def test_a_file_takes_no_token() -> None:
    with pytest.raises(ValueError, match="auth_token is for a libSQL server"):
        vector_backend({"url": "file:index.db", "auth_token": "t"})


def test_a_file_without_the_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    found = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "libsql" else found(name, *a)
    )

    with pytest.raises(ValueError, match=r"pip install 'exactdocs\[libsql\]'"):
        search_backend({"url": "file:index.db"})


def test_the_settings_name_it_and_bad_options_stop_the_start() -> None:
    good = Settings(
        search_backend="libsql",
        vector_backend="LibSQL",
        index_backends={"libsql": {"url": "libsql://db", "prefix": "docs"}},
    )
    bad = Settings(vector_backend="libsql", index_backends={"libsql": {"url": "ws://db"}})

    backends = build_index_backends(good)

    assert isinstance(backends.search, LibsqlSearchBackend)
    assert isinstance(backends.vectors, LibsqlVectorBackend)
    assert backends.names == ("libsql", "libsql")
    assert backends.vectors.prefix == "docs"
    with pytest.raises(StartupError, match=r"\[index_backends.libsql\].*url must be libsql://"):
        build_index_backends(bad)


def test_the_toml_file_refuses_the_token_but_takes_its_file(tmp_path: Path) -> None:
    refused, taken = tmp_path / "refused.toml", tmp_path / "taken.toml"
    refused.write_text('[index_backends.libsql]\nauth_token = "s3cr3t"\n', encoding="utf-8")
    taken.write_text('[index_backends.libsql]\nauth_token_file = "/run/t"\n', encoding="utf-8")

    with pytest.raises(SettingsError, match=r"index_backends\.libsql\.auth_token\b") as raised:
        read_config_file(refused)

    assert "s3cr3t" not in str(raised.value)
    assert read_config_file(taken)["index_backends"]["libsql"] == {"auth_token_file": "/run/t"}


async def test_a_server_that_does_not_answer_stops_the_start() -> None:
    backends = IndexBackends(vectors=vector_backend({"url": "http://127.0.0.1:9", "timeout": 2}))

    with pytest.raises(StartupError, match=r"'libsql'.*unreachable: ConnectError"):
        await backends.open()
    await backends.close()


# ---------------------------------------------------------------- against libSQL

type Build = Callable[[dict[str, object]], dict[str, object]]


def _locations() -> list[str | ParameterSet]:
    """The server, an integration case (#507); a local file, where the ``libsql`` package is."""
    found: list[str | ParameterSet] = [pytest.param("server", marks=integration.LIBSQL)]
    if libsql_backends.HAS_DRIVER:
        found.append("file")
    return found


@pytest.fixture(params=_locations())
async def where(request: pytest.FixtureRequest) -> AsyncIterator[Build]:
    """Options of one fresh place (server tables of their own, or a new file), any extras."""
    if request.param == "server":
        prefix = f"test_{secrets.token_hex(6)}"
        yield lambda extra: {**libsql_backends.server_options(prefix), **extra}
        await libsql_backends.drop_tables(prefix)
        return
    with tempfile.TemporaryDirectory(prefix="exactdocs-libsql-") as folder:
        url = f"file:{Path(folder) / 'index.db'}"
        yield lambda extra: {"url": url, **extra}


async def _opened(backend: LibsqlVectorBackend) -> LibsqlVectorBackend:
    await backend.open()
    return backend


async def test_vectors_are_libsql_vectors_in_a_libsql_vector_index(where: Build) -> None:
    backend = await _opened(vector_backend(where({"compress_neighbors": "float8"})))
    v1 = manifest("m1")
    try:
        await backend.put(space(), v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
        table_name = f"{backend.prefix}_space_1"
        ((table,), (index,)) = await backend.engine.run(
            [
                ("SELECT sql FROM sqlite_master WHERE name = ?", [table_name]),
                ("SELECT sql FROM sqlite_master WHERE name = ?", [f"{table_name}_ann"]),
            ],
            atomic=False,
        )
    finally:
        await backend.close()

    assert "embedding F32_BLOB(3) NOT NULL" in table[0]
    assert (
        "libsql_vector_idx(embedding, 'metric=cosine', 'compress_neighbors=float8')" in (index[0])
    )


async def test_a_small_version_of_a_big_space_finds_its_nearest(where: Build) -> None:
    # Three dimensions are three bits with the default compression: float8 tells them apart.
    backend = await _opened(vector_backend(where({"compress_neighbors": "float8"})))
    big, small = manifest("big"), manifest("small")
    try:
        await backend.put(
            space(),
            big,
            [entry(big, f"b{i:03}", (1.0, i / 300, 0.5)) for i in range(300)],
        )
        await backend.put(
            space(),
            small,
            [
                entry(small, "far", (0.0, 0.0, 1.0)),
                entry(small, "near", (1.0, 0.0, 0.1)),
                entry(small, "mid", (1.0, 1.0, 0.0)),
            ],
        )

        mine = await backend.nearest(space(), ["small"], (1.0, 0.0, 0.0), NO_TAGS, 2)
        theirs = await backend.nearest(space(), ["big"], (1.0, 0.0, 0.5), NO_TAGS, 3)
    finally:
        await backend.close()

    assert [(h.manifest_id, h.chunk_id) for h in mine] == [("small", "near"), ("small", "mid")]
    assert [h.chunk_id for h in theirs] == ["b000", "b001", "b002"]
    assert theirs[0].distance == pytest.approx(0.0, abs=1e-6)


async def test_another_instance_with_the_same_prefix_and_other_dimensions_is_refused(
    where: Build,
) -> None:
    first = await _opened(vector_backend(where({})))
    second = await _opened(vector_backend(where({})))
    v1 = manifest("m1")
    try:
        await first.put(space(dimensions=3), v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
        with pytest.raises(IndexBackendUnavailableError, match="holds vectors of 3 dimensions"):
            await second.put(space(dimensions=2), v1, [entry(v1, "a", (1.0, 0.0))])
    finally:
        await first.close()
        await second.close()


async def test_a_space_dropped_by_another_process_is_made_again_on_the_next_put(
    where: Build,
) -> None:
    writer = await _opened(vector_backend(where({})))
    other = await _opened(vector_backend(where({})))
    v1 = manifest("m1")
    try:
        await writer.put(space(), v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
        await other.drop_space(EmbeddingSpaceId(1))

        gone = await writer.held(EmbeddingSpaceId(1), None)
        nothing = await writer.nearest(space(), ["m1"], (1.0, 0.0, 0.0), NO_TAGS, 5)
        await writer.remove(EmbeddingSpaceId(1), "m1", [ChunkId("a")])
        await writer.put(space(), v1, [entry(v1, "b", (0.0, 1.0, 0.0))])
        held = await other.held(EmbeddingSpaceId(1), None)
    finally:
        await writer.close()
        await other.close()

    assert (gone, nothing) == ([], [])
    assert held == [HeldVersion(manifest_id="m1", library=LIB, entries=1)]


@integration.needs("EXACTDOCS_TEST_LIBSQL_URL", "EXACTDOCS_TEST_LIBSQL_AUTH_TOKEN")
@pytest.mark.parametrize("token", [None, "not-a-jwt"])
async def test_a_server_refuses_a_missing_or_wrong_token(token: str | None) -> None:
    assert libsql_backends.LIBSQL_URL is not None
    options = {"url": libsql_backends.LIBSQL_URL, "prefix": "never"}
    backend = search_backend(options if token is None else {**options, "auth_token": token})

    with pytest.raises(IndexBackendUnavailableError, match="HTTP 401") as raised:
        await backend.open()
    await backend.close()

    assert "not-a-jwt" not in str(raised.value)


@pytest.mark.skipif(not libsql_backends.HAS_DRIVER, reason="needs the libsql package")
async def test_a_local_file_is_an_sqlite_file_other_tools_can_read(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    backend = vector_backend({"url": f"file:{path}"})
    await backend.open()
    v1 = manifest("m1")
    try:
        await backend.put(space(), v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
    finally:
        await backend.close()

    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute("SELECT manifest_id, chunk_id FROM exactdocs_space_1")
        assert rows.fetchall() == [("m1", "a")]
