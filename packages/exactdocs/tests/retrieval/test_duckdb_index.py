"""#357: DuckDB as the search and vector backend, beyond the shared contract suites.

The contract (put, delete, held, version isolation, ranking, spaces) runs in
``test_index_backends.py``, ``test_search_index.py`` and ``test_vector_index.py`` on a temporary
database file. Here: what is DuckDB's own: the ``fts`` extension is loaded from the installed
wheel and never downloaded (a tampered file is refused, a missing one stops the start), one
process writes a file and a second is refused with a message saying so, the ``fts`` index
survives a restart and follows writes, both backends share one file, and the options.
"""

import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from exactdocs.bootstrap.constants import INDEX_BACKENDS
from exactdocs.retrieval.adapters.driven import duckdb_index
from exactdocs.retrieval.adapters.driven.duckdb_index import (
    DuckDBSearchBackend,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs.retrieval.models import (
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    IndexedManifest,
    IndexEntry,
    SpaceState,
    TagFilter,
    TextQuery,
    search_terms,
)

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
NO_TAGS = TagFilter()
HOLD = "import duckdb, sys; c = duckdb.connect(sys.argv[1]); print('held', flush=True); input()"


def manifest(manifest_id: str, ref: str = "v1") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{LIB}/{ref}", library=LIB, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str,
    vector: tuple[float, ...] | None = None,
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", "Guide"),
        content=content,
        tags=(),
        vector=vector,
    )


def duckdb_version() -> str:
    with duckdb.connect() as connection:
        row = connection.execute("PRAGMA version").fetchone()
    assert row is not None
    return str(row[0])


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


SPACE = EmbeddingSpace(
    id=EmbeddingSpaceId(7),
    spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=3),
    state=SpaceState.ACTIVE,
    created_at=T0,
)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "index.duckdb"


@pytest.fixture
async def search(path: Path) -> AsyncIterator[DuckDBSearchBackend]:
    backend = search_backend({"path": str(path)})
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()


@pytest.fixture
def holder(path: Path) -> Iterator[subprocess.Popen[str]]:
    """Another process with the file open, as a second server worker would have."""
    with subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter
        [sys.executable, "-c", HOLD, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "held"
        try:
            yield process
        finally:
            process.communicate("\n", timeout=30)


def test_the_backend_is_registered_behind_its_extra() -> None:
    kind = INDEX_BACKENDS["duckdb"]
    assert (kind.extra, kind.search, kind.vectors) == ("duckdb", "search_backend", "vector_backend")
    assert kind.production


# ---------------------------------------------------------------- offline extensions


async def test_fts_is_loaded_from_the_installed_wheel_and_nothing_installs_itself(
    search: DuckDBSearchBackend,
) -> None:
    connection = search.file.connection
    assert connection is not None
    settings = dict(
        connection.execute(
            "SELECT name, value FROM duckdb_settings() WHERE name IN ("
            "'autoinstall_known_extensions', 'autoload_known_extensions', "
            "'allow_community_extensions', 'allow_unsigned_extensions')"
        ).fetchall()
    )
    assert set(settings.values()) == {"false"}, settings
    loaded = dict(
        connection.execute(
            "SELECT extension_name, installed FROM duckdb_extensions() WHERE loaded"
        ).fetchall()
    )
    assert "fts" in loaded
    assert not loaded["fts"]  # loaded from the wheel's file, never installed from a repository
    assert "vss" not in loaded  # vectors use core functions only


async def test_a_tampered_extension_is_refused(path: Path, tmp_path: Path, monkeypatch) -> None:
    version = duckdb_version()
    tampered = tmp_path / "fts.duckdb_extension"
    shutil.copy(duckdb_index.fts_extension(version), tampered)
    data = bytearray(tampered.read_bytes())
    data[len(data) // 2] ^= 0xFF
    tampered.write_bytes(bytes(data))
    monkeypatch.setattr(duckdb_index, "fts_extension", lambda _: tampered)
    backend = search_backend({"path": str(path)})

    with pytest.raises(IndexBackendUnavailableError, match="fts extension did not load"):
        await backend.open()
    await backend.close()


async def test_a_missing_extension_stops_the_start_instead_of_a_download(
    path: Path, monkeypatch
) -> None:
    def missing(version: str) -> Path:
        message = f"duckdb-extension-fts has no fts extension for DuckDB {version}"
        raise FileNotFoundError(message)

    monkeypatch.setattr(duckdb_index, "fts_extension", missing)
    backend = search_backend({"path": str(path)})

    with pytest.raises(IndexBackendUnavailableError, match=r"exactdocs\[duckdb\]"):
        await backend.open()
    await backend.close()


def test_the_wheel_has_the_extension_of_the_installed_duckdb() -> None:
    version = duckdb_version()
    assert duckdb_index.fts_extension(version).is_file()


# ---------------------------------------------------------------- one writer process


async def test_a_second_process_is_refused_with_a_clear_message(
    path: Path, holder: subprocess.Popen[str]
) -> None:
    for backend in (search_backend({"path": str(path)}), vector_backend({"path": str(path)})):
        with pytest.raises(IndexBackendUnavailableError) as raised:
            await backend.open()
        await backend.close()
        reason = raised.value.reason
        assert f"PID {holder.pid}" in reason, reason
        assert "DuckDB lets one process write a database file" in reason, reason
        assert "WEB_CONCURRENCY=1" in reason, reason


async def test_both_backends_share_one_file_in_one_process(path: Path) -> None:
    search, vectors = search_backend({"path": str(path)}), vector_backend({"path": str(path)})
    await search.open()
    await vectors.open()
    try:
        v1 = manifest("m1")
        await search.put(v1, [entry(v1, "a", "retry policy")])
        await vectors.put(SPACE, v1, [entry(v1, "a", "a", vector=(1.0, 0.0, 0.0))])
        assert [h.chunk_id for h in await search.search(["m1"], query("retry"), NO_TAGS, 5)] == [
            "a"
        ]
        assert [
            h.chunk_id for h in await vectors.nearest(SPACE, ["m1"], [1, 0, 0], NO_TAGS, 5)
        ] == ["a"]
    finally:
        await search.close()
        await vectors.close()


# ---------------------------------------------------------------- the fts index


async def test_the_fts_index_survives_a_restart_and_follows_later_writes(path: Path) -> None:
    v1 = manifest("m1")
    first = search_backend({"path": str(path)})
    await first.open()
    await first.put(v1, [entry(v1, "a", "retry policy"), entry(v1, "b", "unrelated")])
    found = await first.search(["m1"], query("retry"), NO_TAGS, 5)
    await first.close()

    again = search_backend({"path": str(path)})
    await again.open()
    try:
        connection = again.file.connection
        assert connection is not None
        assert connection.execute("SELECT stale FROM exactdocs_search_state").fetchall() == [
            (False,)
        ]  # built before the restart: no rebuild at the first search
        assert await again.search(["m1"], query("retry"), NO_TAGS, 5) == found
        await again.put(v1, [entry(v1, "c", "retry again")])
        await again.delete(["never-held"])
        assert {h.chunk_id for h in await again.search(["m1"], query("retry"), NO_TAGS, 5)} == {
            "a",
            "c",
        }
        await again.delete(["m1"])
        assert await again.search(["m1"], query("retry"), NO_TAGS, 5) == []
    finally:
        await again.close()


async def test_the_tables_carry_library_and_version(search: DuckDBSearchBackend) -> None:
    v1 = manifest("m1", ref="v1.4.0")
    await search.put(v1, [entry(v1, "a", "retry policy")])
    connection = search.file.connection
    assert connection is not None

    rows = connection.execute(
        "SELECT library, version_id, manifest_id, chunk_id, content FROM exactdocs_search"
    ).fetchall()

    assert rows == [(LIB, f"{LIB}/v1.4.0", "m1", "a", "retry policy")]


async def test_a_closed_backend_does_not_answer(path: Path) -> None:
    backend = search_backend({"path": str(path)})
    with pytest.raises(IndexBackendUnavailableError, match="not open"):
        await backend.held(None)


async def test_a_missing_folder_stops_the_start(tmp_path: Path) -> None:
    backend = vector_backend({"path": str(tmp_path / "nowhere" / "index.duckdb")})
    with pytest.raises(IndexBackendUnavailableError, match="does not exist"):
        await backend.open()
    await backend.close()


# ---------------------------------------------------------------- options


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({}, "needs `path`"),
        ({"path": ":memory:"}, "needs `path`"),
        ({"path": "x.duckdb", "url": "y"}, "takes memory_limit, path, threads"),
        ({"path": "x.duckdb", "threads": "0"}, "at least 1"),
        ({"path": "x.duckdb", "threads": "many"}, "invalid literal"),
    ],
)
def test_invalid_options_are_refused(options: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        search_backend(options)


def test_options_reach_duckdb(tmp_path: Path) -> None:
    backend = vector_backend(
        {"path": str(tmp_path / "i.duckdb"), "threads": "2", "memory_limit": "1GB"}
    )
    assert backend.file.config["threads"] == 2
    assert backend.file.config["memory_limit"] == "1GB"
    assert backend.file.config["autoinstall_known_extensions"] is False
