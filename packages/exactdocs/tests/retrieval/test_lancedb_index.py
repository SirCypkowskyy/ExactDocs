"""LanceDB as the search and vector backend (#356): what the shared contract suites do not cover.

The contract suites (``test_search_index.py``, ``test_vector_index.py``,
``test_index_backends.py``) run the ``lancedb`` case on a temporary directory. These tests cover
the adapter's own promises: its options (an object-store URI is refused unless the operator
states one process writes it; credentials never come from the options), writers in several
processes taking turns on a local directory, a write that waits too long failing for its job to
retry, other processes' writes being read at once, the data surviving a restart, and the wiring
from the settings an operator writes.
"""

import asyncio
import fcntl
import os
import tomllib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import lancedb
import pytest

from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.lancedb_index import (
    LanceDBSearchBackend,
    LanceDBVectorBackend,
    lancedb_settings,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.constants import LANCEDB_LOCK_FILE
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
    TextQuery,
    search_terms,
)

ROOT = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
V1 = IndexedManifest(manifest_id="m1", version_id=f"{LIB}/v1", library=LIB, indexed_at=T0)
SPACE = EmbeddingSpace(
    id=EmbeddingSpaceId(1),
    spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=3),
    state=SpaceState.ACTIVE,
    created_at=T0,
)


def entry(chunk: str, content: str, vector: tuple[float, ...] | None = None) -> IndexEntry:
    return IndexEntry(
        manifest_id=V1.manifest_id,
        library=LIB,
        version_id=V1.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", "Retries"),
        content=content,
        tags=(),
        vector=vector,
    )


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


@pytest.fixture
async def search(tmp_path: Path) -> AsyncIterator[LanceDBSearchBackend]:
    backend = search_backend({"uri": str(tmp_path)})
    await backend.open()
    yield backend
    await backend.close()


# ---------------------------------------------------------------- options


def test_a_local_directory_is_the_whole_configuration(tmp_path: Path) -> None:
    settings = lancedb_settings({"uri": str(tmp_path / "lance")})

    assert (settings.local, settings.prefix, settings.single_writer) == (
        tmp_path / "lance",
        "exactdocs",
        False,
    )
    assert settings.search_table == "exactdocs_chunks"
    assert settings.space_table(EmbeddingSpaceId(7)) == "exactdocs_space_7"
    assert lancedb_settings({"uri": f"file://{tmp_path}"}).local == tmp_path


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({}, "uri is required"),
        ({"uri": "relative/dir"}, "absolute directory"),
        ({"uri": "/x", "url": "/y"}, r"unknown option\(s\) url"),
        ({"uri": "/x", "table_prefix": "Bad-Name"}, "table_prefix"),
        ({"uri": "/x", "single_writer": "maybe"}, "single_writer must be true or false"),
        ({"uri": "/x", "lock_timeout_seconds": "0"}, "more than 0"),
        ({"uri": "/x", "read_consistency_seconds": "-1"}, "0 or more"),
        ({"uri": "az://docs/x?sv=2024&sig=abc"}, "may not carry credentials"),
        ({"uri": "s3://key:secret@bucket/x", "single_writer": True}, "may not carry"),
        (
            {"uri": "/x", "storage_options": {"aws_secret_access_key": "s"}},
            "may not hold credentials.*AWS_SECRET_ACCESS_KEY",
        ),
    ],
)
def test_invalid_options_are_refused(options: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        lancedb_settings(options)


def test_storage_options_must_be_a_table() -> None:
    with pytest.raises(TypeError, match="storage_options"):
        lancedb_settings({"uri": "/x", "storage_options": "region=eu"})


def test_an_object_store_needs_the_operator_to_state_one_writer() -> None:
    with pytest.raises(ValueError, match=r"s3://\.\.\. is an object store.*single_writer = true"):
        vector_backend({"uri": "s3://bucket/exactdocs"})

    settings = lancedb_settings(
        {
            "uri": "s3://bucket/exactdocs",
            "single_writer": "true",  # from the environment: a string
            "storage_options": {"region": "eu-central-1", "endpoint": "http://minio:9000"},
        }
    )
    assert (settings.local, settings.single_writer) == (None, True)
    assert settings.storage_options == {"region": "eu-central-1", "endpoint": "http://minio:9000"}


def test_the_settings_an_operator_writes_build_both_backends(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        search_backend="LanceDB",
        vector_backend="lancedb",
        index_backends={"lancedb": {"uri": str(tmp_path / "lance"), "table_prefix": "docs"}},
    )

    backends = build_index_backends(settings)

    assert backends.names == ("lancedb", "lancedb")
    assert isinstance(backends.search, LanceDBSearchBackend)
    assert isinstance(backends.vectors, LanceDBVectorBackend)
    assert backends.vectors.store.settings.prefix == "docs"


# ---------------------------------------------------------------- opening


async def test_a_directory_that_cannot_be_used_does_not_answer(tmp_path: Path) -> None:
    taken = tmp_path / "a-file"
    taken.write_text("not a directory")
    backend = search_backend({"uri": str(taken)})

    with pytest.raises(IndexBackendUnavailableError, match=f"opening {taken}"):
        await backend.open()
    await backend.close()


async def test_a_write_before_open_does_not_answer(tmp_path: Path) -> None:
    backend = search_backend({"uri": str(tmp_path)})

    with pytest.raises(IndexBackendUnavailableError, match="not opened"):
        await backend.put(V1, [entry("a", "retry")])


# ---------------------------------------------------------------- writers


async def test_writers_in_several_processes_take_turns(tmp_path: Path) -> None:
    # Each backend has its own connection and lock file descriptor, as a process has: without
    # the lock, concurrent merge-inserts of the same rows leave duplicates.
    writers = [search_backend({"uri": str(tmp_path)}) for _ in range(3)]
    for writer in writers:
        await writer.open()
    entries = [entry(f"c{n:03d}", f"retry number {n}") for n in range(60)]
    try:
        await asyncio.gather(*(w.put(V1, entries) for w in writers for _ in range(3)))

        assert await writers[0].held(None) == [
            HeldVersion(manifest_id="m1", library=LIB, entries=60)
        ]
    finally:
        for writer in writers:
            await writer.close()


async def test_a_write_waits_for_another_process_then_fails_for_its_job_to_retry(
    tmp_path: Path,
) -> None:
    backend = search_backend({"uri": str(tmp_path), "lock_timeout_seconds": "0.2"})
    await backend.open()
    await backend.put(V1, [entry("a", "retry")])
    other = os.open(tmp_path / LANCEDB_LOCK_FILE, os.O_RDWR)
    fcntl.flock(other, fcntl.LOCK_EX)  # another process is writing
    try:
        with pytest.raises(IndexBackendUnavailableError, match="another process kept the write"):
            await backend.put(V1, [entry("b", "retry")])
        # Reads never wait for the lock.
        assert len(await backend.search(["m1"], query("retry"), TagFilter(), 10)) == 1
    finally:
        os.close(other)
        await backend.close()


async def test_another_processs_writes_are_read_at_once(
    tmp_path: Path, search: LanceDBSearchBackend
) -> None:
    assert await search.held(None) == []  # opened (and the table looked for) before the write
    writer = search_backend({"uri": str(tmp_path)})
    await writer.open()
    await writer.put(V1, [entry("a", "retry once"), entry("b", "retry twice")])
    await writer.close()

    assert await search.held(LIB) == [HeldVersion(manifest_id="m1", library=LIB, entries=2)]
    assert len(await search.search(["m1"], query("retry"), TagFilter(), 10)) == 2


async def test_what_was_written_is_there_after_a_restart_and_indexed(tmp_path: Path) -> None:
    first = search_backend({"uri": str(tmp_path)})
    await first.open()
    await first.put(V1, [entry(f"c{n:03d}", f"retry {n}") for n in range(25)])
    await first.close()  # adds the pending rows to the indexes

    again = search_backend({"uri": str(tmp_path)})
    await again.open()
    try:
        assert await again.held(None) == [HeldVersion(manifest_id="m1", library=LIB, entries=25)]
        assert await again.count(["m1"], query("retry"), TagFilter()) == {"m1": 25}
    finally:
        await again.close()
    db = await lancedb.connect_async(tmp_path)
    table = await db.open_table("exactdocs_chunks")
    indices = await table.list_indices()
    table.close()
    db.close()
    stats = {i.name: (i.num_indexed_rows, i.num_unindexed_rows) for i in indices}
    assert stats["body_words_idx"] == (25, 0), stats


async def test_a_space_table_of_other_dimensions_is_refused(tmp_path: Path) -> None:
    mine = vector_backend({"uri": str(tmp_path)})
    await mine.open()
    await mine.put(SPACE, V1, [entry("a", "a", vector=(1.0, 0.0, 0.0))])
    await mine.close()
    other_spec = EmbeddingSpec(profile_kind="openai", model="other", dimensions=4)
    other = EmbeddingSpace(id=SPACE.id, spec=other_spec, state=SpaceState.ACTIVE, created_at=T0)
    theirs = vector_backend({"uri": str(tmp_path)})
    await theirs.open()
    try:
        with pytest.raises(IndexBackendUnavailableError, match=r"3 dimensions.*table prefix"):
            await theirs.put(other, V1, [entry("a", "a", vector=(1.0, 0.0, 0.0, 0.0))])
    finally:
        await theirs.close()


async def test_table_prefixes_keep_instances_apart(tmp_path: Path) -> None:
    one = search_backend({"uri": str(tmp_path), "table_prefix": "one"})
    two = search_backend({"uri": str(tmp_path), "table_prefix": "two"})
    for backend in (one, two):
        await backend.open()
    try:
        await one.put(V1, [entry("a", "retry")])

        assert await two.held(None) == []
        assert await two.search(["m1"], query("retry"), TagFilter(), 10) == []
    finally:
        for backend in (one, two):
            await backend.close()


async def test_held_counts_every_row_of_a_large_version(search: LanceDBSearchBackend) -> None:
    await search.put(V1, [entry(f"c{n:04d}", "words") for n in range(1200)])

    assert await search.held(None) == [HeldVersion(manifest_id="m1", library=LIB, entries=1200)]


async def test_a_quote_in_a_value_is_data(search: LanceDBSearchBackend) -> None:
    await search.put(V1, [entry("a", "retry")])

    assert await search.search(["m1' OR '1'='1"], query("retry"), TagFilter(), 10) == []
    assert await search.search(["m1"], query("retry"), TagFilter(tags=("it's",)), 10) == []
    await search.delete(["x') OR (manifest_id = 'm1"])
    assert len(await search.search(["m1"], query("retry"), TagFilter(), 10)) == 1


@pytest.mark.parametrize("package", ["lancedb", "pyarrow"])
def test_the_pinned_extra_has_wheels_for_both_image_architectures(package: str) -> None:
    # CI and the images run on ARM64 and x86_64: a pin without a manylinux wheel for one of
    # them would build from source (Rust, C++) or not install at all.
    locked = tomllib.loads((ROOT / "uv.lock").read_text("utf-8"))["package"]
    (found,) = [p for p in locked if p["name"] == package]
    wheels = [w["url"].rsplit("/", 1)[1] for w in found["wheels"]]
    for arch in ("aarch64", "x86_64"):
        assert [
            w
            for w in wheels
            if f"manylinux_2_28_{arch}" in w and ("abi3" in w or "cp314-cp314-" in w)
        ], (package, arch, wheels)


async def test_indexes_lost_after_the_table_was_made_are_made_again(tmp_path: Path) -> None:
    first = search_backend({"uri": str(tmp_path)})
    await first.open()
    await first.put(V1, [entry("a", "retry once")])
    await first.close()
    db = await lancedb.connect_async(tmp_path)
    table = await db.open_table("exactdocs_chunks")
    for index in await table.list_indices():  # as if a stop came between table and indexes
        await table.drop_index(index.name)
    table.close()
    db.close()

    again = search_backend({"uri": str(tmp_path)})
    await again.open()
    try:
        await again.put(V1, [entry("b", "retry twice")])

        assert len(await again.search(["m1"], query("retry"), TagFilter(), 10)) == 2
    finally:
        await again.close()
    db = await lancedb.connect_async(tmp_path)
    table = await db.open_table("exactdocs_chunks")
    columns = {c for index in await table.list_indices() for c in index.columns}
    table.close()
    db.close()
    assert columns == {"manifest_id", "heading_words", "path_words", "body_words"}
