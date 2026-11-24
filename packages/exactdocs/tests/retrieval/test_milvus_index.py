"""Milvus as the vector backend (#360): what the shared contract suites do not cover.

The options an operator writes (and the ones refused at start), the token kept out of the file and
the logs, native hybrid switched off, a query without terms, filter values that need quoting, the
BM25 text cut to Milvus' field size, and a Milvus Lite directory found again after a restart. The
behaviour cases run on Milvus Lite everywhere and, as integration tests (#507), on the server
``EXACTDOCS_TEST_MILVUS_URL`` names (``tests/fixtures/milvus_server.py``).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

import integration
import milvus_server
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.milvus_index import (
    MilvusHybridVectorBackend,
    MilvusVectorBackend,
    _words,
    vector_backend,
)
from exactdocs.retrieval.constants import MILVUS_TEXT_LENGTH
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
    TagMatch,
    TextQuery,
    search_terms,
)
from exactdocs.retrieval.ports import NativeHybrid

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
SPACE = EmbeddingSpace(
    id=EmbeddingSpaceId(1),
    spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=3),
    state=SpaceState.ACTIVE,
    created_at=T0,
)
MODES = ["lite", pytest.param("server", marks=integration.MILVUS)]
"""Milvus Lite everywhere; the server (``EXACTDOCS_TEST_MILVUS_URL``): integration (#507)."""


def manifest(manifest_id: str, library: str = LIB) -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{library}/v1", library=library, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str,
    vector: tuple[float, ...],
    tags: tuple[str, ...] = (),
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs",),
        content=content,
        tags=tags,
        vector=vector,
    )


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


@pytest.fixture(params=MODES)
def mode(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
async def hybrid(mode: str) -> AsyncIterator[MilvusVectorBackend]:
    async with milvus_server.milvus_vectors(mode) as backend:
        yield backend


# ---------------------------------------------------------------- options


def test_a_server_uri_gives_a_hybrid_backend_with_the_defaults() -> None:
    backend = vector_backend({"uri": "http://milvus:19530/"})

    assert isinstance(backend, MilvusHybridVectorBackend)
    assert isinstance(backend, NativeHybrid)
    assert (backend.uri, backend.collection, backend.timeout) == (
        "http://milvus:19530",
        "exactdocs",
        30.0,
    )
    assert (backend.consistency_level, backend.local, backend.token) == ("Strong", False, None)


def test_hybrid_false_from_the_environment_gives_a_plain_vector_backend() -> None:
    backend = vector_backend({"uri": "http://milvus:19530", "hybrid": "false"})

    assert type(backend) is MilvusVectorBackend
    assert not isinstance(backend, NativeHybrid)


def test_a_milvus_lite_path_is_made_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    backend = vector_backend({"uri": "data/exactdocs.db", "consistency_level": "bounded"})

    assert backend.uri == str(tmp_path / "data" / "exactdocs.db")
    assert backend.local
    assert backend.consistency_level == "Bounded"


def test_the_token_is_read_from_its_file_and_kept_out_of_the_repr(tmp_path: Path) -> None:
    secret = tmp_path / "token"
    secret.write_text("root:s3cret\n", "utf-8")

    backend = vector_backend({"uri": "https://x.zillizcloud.com", "token_file": str(secret)})

    assert backend.token == "root:s3cret"
    assert "s3cret" not in repr(backend)


@pytest.mark.parametrize(
    ("options", "refusal"),
    [
        ({}, "uri is required"),
        ({"uri": "http://m:19530", "url": "x"}, "unknown option.*url"),
        ({"uri": "/data/milvus"}, "neither a server.*nor a Milvus Lite path ending in .db"),
        ({"uri": "/data/milvus.db", "token": "root:Milvus"}, "Milvus Lite .* has none"),
        ({"uri": "http://m:19530", "token": "a", "token_file": "/t"}, "token or token_file"),
        ({"uri": "http://m:19530", "token_file": "/nowhere/token"}, "cannot be read"),
        ({"uri": "http://m:19530", "collection": "9lives"}, "collection '9lives'"),
        ({"uri": "http://m:19530", "collection": "a-b"}, "collection 'a-b'"),
        ({"uri": "http://m:19530", "timeout": "soon"}, "timeout must be a number"),
        ({"uri": "http://m:19530", "timeout": 0}, "more than 0"),
        ({"uri": "http://m:19530", "consistency_level": "eventual"}, "consistency_level"),
        ({"uri": "http://m:19530", "hybrid": "maybe"}, "hybrid must be true or false"),
    ],
)
def test_invalid_options_are_refused(options: dict[str, object], refusal: str) -> None:
    with pytest.raises(ValueError, match=refusal):
        vector_backend(options)


def test_an_empty_token_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("\n", "utf-8")

    with pytest.raises(ValueError, match="is empty"):
        vector_backend({"uri": "http://m:19530", "token_file": str(tmp_path / "token")})


def test_the_settings_build_it_and_name_it_in_a_refusal() -> None:
    settings = Settings(
        vector_backend="milvus", index_backends={"milvus": {"uri": "http://milvus:19530"}}
    )

    assert isinstance(build_index_backends(settings).vectors, MilvusHybridVectorBackend)
    broken = settings.model_copy(update={"index_backends": {"milvus": {}}})
    with pytest.raises(StartupError, match=r"\[index_backends\.milvus\].*uri is required"):
        build_index_backends(broken)


def test_it_cannot_hold_the_search_index() -> None:
    with pytest.raises(ValueError, match="the milvus backend cannot hold the search index"):
        Settings(search_backend="milvus")


async def test_an_unreachable_server_is_unavailable_naming_the_backend() -> None:
    backend = vector_backend({"uri": "http://127.0.0.1:1", "timeout": 1})

    with pytest.raises(IndexBackendUnavailableError, match="'milvus' is unavailable"):
        await backend.open()
    with pytest.raises(IndexBackendUnavailableError, match="not open"):
        await backend.held(SPACE.id, None)


def test_the_bm25_text_is_cut_at_a_word_to_fit_the_field() -> None:
    long = entry(manifest("m1"), "a", "retry " * 20_000, (1.0, 0.0, 0.0))

    words = _words(long)

    assert len(words.encode()) <= MILVUS_TEXT_LENGTH
    assert set(words.split()) == {"docs", "retry"}


# ---------------------------------------------------------------- behaviour


async def test_filter_values_that_need_quoting_match_exactly(
    hybrid: MilvusVectorBackend,
) -> None:
    quoted, plain = manifest('m"1\\'), manifest("m1")
    odd = ('it\'s "api"', "zażółć")
    await hybrid.put(SPACE, quoted, [entry(quoted, "a", "retry", (1.0, 0.0, 0.0), odd)])
    await hybrid.put(SPACE, plain, [entry(plain, "a", "retry", (1.0, 0.0, 0.0), ("api",))])

    found = await hybrid.nearest(
        SPACE, [quoted.manifest_id], [1, 0, 0], TagFilter(tags=odd, match=TagMatch.ALL), 5
    )

    assert [(h.manifest_id, h.chunk_id) for h in found] == [(quoted.manifest_id, "a")]
    assert (
        await hybrid.nearest(SPACE, [quoted.manifest_id], [1, 0, 0], TagFilter(tags=("api",)), 5)
        == []
    )
    assert [h.manifest_id for h in await hybrid.held(SPACE.id, LIB)] == ['m"1\\', "m1"]


async def test_a_hybrid_query_without_terms_ranks_by_its_vector(
    hybrid: MilvusVectorBackend,
) -> None:
    assert isinstance(hybrid, MilvusHybridVectorBackend)
    v1 = manifest("m1")
    await hybrid.put(
        SPACE,
        v1,
        [entry(v1, "far", "far", (0.0, 1.0, 0.0)), entry(v1, "near", "near", (1.0, 0.1, 0.0))],
    )

    found = await hybrid.hybrid(
        SPACE, ["m1"], TextQuery(text="--", terms=()), [1, 0, 0], TagFilter(), 5
    )

    assert [h.chunk_id for h in found] == ["near", "far"]
    assert found[0].score > found[1].score


async def test_without_hybrid_no_words_are_kept_and_hybrid_says_how_to_fix_it(mode: str) -> None:
    v1 = manifest("m1")
    async with milvus_server.place(mode) as options:
        plain = vector_backend({**options, "hybrid": False})
        await plain.open()
        try:
            await plain.put(SPACE, v1, [entry(v1, "a", "retry", (1.0, 0.0, 0.0))])
            assert [
                h.chunk_id for h in await plain.nearest(SPACE, ["m1"], [1, 0, 0], TagFilter(), 5)
            ] == ["a"]
        finally:
            await plain.close()
        later = vector_backend(options)
        assert isinstance(later, MilvusHybridVectorBackend)
        await later.open()
        try:
            with pytest.raises(IndexBackendUnavailableError, match="no BM25 field"):
                await later.hybrid(SPACE, ["m1"], query("retry"), [1, 0, 0], TagFilter(), 5)
            await later.put(
                SPACE, v1, [entry(v1, "b", "again", (0.0, 1.0, 0.0))]
            )  # still takes rows
            assert await later.held(SPACE.id, None) == [
                HeldVersion(manifest_id="m1", library=LIB, entries=2)
            ]
        finally:
            await later.close()


async def test_milvus_lite_finds_its_collections_again_after_a_restart() -> None:
    v1 = manifest("m1")
    async with milvus_server.place("lite") as options:
        first = vector_backend(options)
        await first.open()
        await first.put(SPACE, v1, [entry(v1, "a", "retry policy", (1.0, 0.0, 0.0))])
        await first.close()

        again = vector_backend(options)
        await again.open()
        try:
            assert await again.held(SPACE.id, None) == [
                HeldVersion(manifest_id="m1", library=LIB, entries=1)
            ]
            assert isinstance(again, MilvusHybridVectorBackend)
            found = await again.hybrid(SPACE, ["m1"], query("policy"), [1, 0, 0], TagFilter(), 5)
            assert [h.chunk_id for h in found] == ["a"]
        finally:
            await again.close()
