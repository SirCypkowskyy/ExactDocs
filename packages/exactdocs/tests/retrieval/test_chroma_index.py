"""#361: Chroma as the vector backend, beyond the shared contract suites.

The shared suites (``test_index_backends.py``, ``test_vector_index.py``) run the ``chroma_local``
case (the embedded client on a temporary directory) everywhere and the ``chroma`` case (HTTP)
when ``EXACTDOCS_TEST_CHROMA_URL`` names a server. Here: the options (``[index_backends.chroma]``),
the token and what a refusal says, no model of Chroma's ever loaded, the metadata a record
carries, and what a collection of the same name that is not this space's does.
"""

import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import textwrap
import threading
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chromadb
import pytest
from chromadb.api.client import Client

from chroma_server import CHROMA_URL, chroma_vectors, place
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.chroma_index import (
    ChromaVectorBackend,
    close_client,
    record_metadata,
    search_filter,
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
    TagMatch,
)

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
TOKEN = "s3cr3t-chroma-token"  # a test value, sent to a loopback stub only
MODES = ["local", *(["http"] if CHROMA_URL else [])]


def manifest(manifest_id: str, ref: str = "v1") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{LIB}/{ref}", library=LIB, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    vector: tuple[float, ...],
    tags: tuple[str, ...] = ("api",),
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", "Retry policy"),
        content="RetryPolicy decides how often a call is retried.",
        tags=tags,
        vector=vector,
    )


def space(space_id: int = 1, dimensions: int = 3) -> EmbeddingSpace:
    return EmbeddingSpace(
        id=EmbeddingSpaceId(space_id),
        spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=dimensions),
        state=SpaceState.ACTIVE,
        created_at=T0,
    )


@pytest.fixture(params=MODES)
async def fresh(request: pytest.FixtureRequest) -> AsyncIterator[tuple[ChromaVectorBackend, dict]]:
    """An opened backend and its options (to look into Chroma with a client of the test's own)."""
    async with place(request.param) as options:
        backend = vector_backend(options)
        await backend.open()
        try:
            yield backend, options
        finally:
            await backend.close()


@contextmanager
def peer(options: dict) -> Generator[Client]:
    """A client of the same Chroma, as an operator (or another instance) would use it."""
    client = vector_backend(options).connect()
    try:
        yield client
    finally:
        close_client(client)


# ---------------------------------------------------------------- options


def test_the_options_are_checked_before_any_connection(tmp_path: Path) -> None:
    def refused(options: dict[str, object], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            vector_backend(options)

    refused({}, "give url .* or path")
    refused({"url": "http://chroma:8000", "path": str(tmp_path)}, "one of the two")
    refused({"url": "http://chroma:8000", "colection": "x"}, r"unknown options colection \(known")
    refused({"url": "ftp://chroma"}, "must be http")
    refused({"url": "https://chroma.example.com/api"}, "no path")
    refused({"url": "https://user:pw@chroma.example.com"}, "no credentials")
    refused({"url": "http://chroma:0"}, "must be http")
    refused({"url": "http://chroma", "collection": "_x"}, "collection '_x'")
    refused({"url": "http://chroma", "collection": "a b"}, "collection 'a b'")
    refused({"url": "http://chroma", "timeout": "soon"}, "timeout must be")
    refused({"url": "http://chroma", "timeout": 0}, "timeout must be")
    refused({"url": "http://chroma", "token_header": "x-api-key"}, "token_header must be")
    refused({"url": "http://chroma", "token": TOKEN, "token_file": "t"}, "not both")
    refused({"path": str(tmp_path), "token": TOKEN}, "the embedded client .* takes none")

    backend = vector_backend({"url": "https://api.trychroma.com", "collection": "docs.v2"})
    assert (backend.collection, backend.timeout, backend.secret) == ("docs.v2", 30, None)


def test_the_token_comes_from_the_environment_or_a_file(tmp_path: Path) -> None:
    secret = tmp_path / "token"
    secret.write_text(f"{TOKEN}\n", "utf-8")
    assert vector_backend({"url": "http://c", "token_file": str(secret)}).secret == TOKEN
    secret.write_text("  ", "utf-8")
    with pytest.raises(ValueError, match="is empty"):
        vector_backend({"url": "http://c", "token_file": str(secret)})
    with pytest.raises(ValueError, match="cannot be read"):
        vector_backend({"url": "http://c", "token_file": str(tmp_path / "missing")})
    assert TOKEN not in repr(vector_backend({"url": "http://c", "token": TOKEN}))


def test_the_http_only_client_refuses_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromadb, "is_client", True)  # chromadb-client, the `chroma` extra
    with pytest.raises(ValueError, match=r"install exactdocs\[chroma-local\]"):
        vector_backend({"path": str(tmp_path)})


async def test_the_settings_name_the_backend_and_its_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXACTDOCS_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__CHROMA__PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__CHROMA__COLLECTION", "docs")

    backends = build_index_backends(Settings())

    assert isinstance(backends.vectors, ChromaVectorBackend)
    assert backends.names == ("database", "chroma")
    await backends.open()
    await backends.close()
    assert (tmp_path / "chroma").is_dir()  # the embedded client's directory, made at start


def test_the_token_is_refused_in_the_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "exactdocs.toml"
    file.write_text(f'[index_backends.chroma]\nurl = "http://c"\ntoken = "{TOKEN}"\n', "utf-8")
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(file))
    with pytest.raises(ValueError, match=r"index_backends\.chroma\.token") as refused:
        Settings()
    assert TOKEN not in str(refused.value)


# ---------------------------------------------------------------- the token, over HTTP


@contextmanager
def stub(status: int, hold: threading.Event | None = None) -> Generator[tuple[str, list[dict]]]:
    """A loopback server that answers every request with ``status`` (a proxy refusing it), or
    holds it until ``hold`` is set; yields its URL and the headers it saw."""
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append({k.lower(): v for k, v in self.headers.items()})
            if hold is not None:
                hold.wait(10)
            body = b"401 Unauthorized: no or bad token"
            self.send_response(status)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            del code, size

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        if hold is not None:
            hold.set()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(
    ("header", "sent"),
    [("x-chroma-token", TOKEN), ("authorization", f"Bearer {TOKEN}")],
)
async def test_the_token_is_sent_and_a_refusal_never_names_it(header: str, sent: str) -> None:
    with stub(401) as (url, seen):
        backend = vector_backend({"url": url, "token": TOKEN, "token_header": header})
        with pytest.raises(IndexBackendUnavailableError, match="401 Unauthorized") as refused:
            await backend.open()

    assert seen
    assert seen[0][header] == sent
    assert TOKEN not in str(refused.value)
    assert TOKEN not in refused.value.reason


async def test_a_server_that_does_not_answer_in_time_is_unavailable() -> None:
    with stub(200, hold=threading.Event()) as (url, _):
        backend = vector_backend({"url": url, "timeout": 1})
        with pytest.raises(IndexBackendUnavailableError, match="no answer within 1 s"):
            await backend.open()


async def test_a_server_that_is_not_there_is_unavailable() -> None:
    with stub(200) as (url, _):
        pass  # the port is free again
    backend = vector_backend({"url": url})
    with pytest.raises(IndexBackendUnavailableError, match="Could not connect"):
        await backend.open()


# ---------------------------------------------------------------- no model of Chroma's


def test_no_model_of_chromas_is_loaded_or_downloaded(tmp_path: Path) -> None:
    """In a process of its own (with an empty home), a put and a search import no ONNX runtime
    and no tokenizer, and download nothing: ExactDocs passes its vectors in."""
    script = textwrap.dedent(
        f"""
        import asyncio, sys, warnings
        warnings.simplefilter("ignore", DeprecationWarning)
        from datetime import UTC, datetime
        from exactdocs.retrieval.adapters.driven.chroma_index import vector_backend
        from exactdocs.retrieval.models import (
            ChunkId, EmbeddingSpace, EmbeddingSpaceId, EmbeddingSpec, IndexedManifest,
            IndexEntry, SpaceState, TagFilter,
        )

        async def main():
            t0 = datetime(2026, 11, 22, tzinfo=UTC)
            s = EmbeddingSpace(
                id=EmbeddingSpaceId(1), spec=EmbeddingSpec(profile_kind="o", model="m",
                dimensions=3), state=SpaceState.ACTIVE, created_at=t0,
            )
            m = IndexedManifest(manifest_id="m1", version_id="/a/b/v1", library="/a/b",
                                indexed_at=t0)
            e = IndexEntry(manifest_id="m1", library="/a/b", version_id="/a/b/v1",
                           chunk_id=ChunkId("c"), article_path="a.md", heading_path=("A",),
                           content="text Chroma could embed", tags=(), vector=(1.0, 0.0, 0.0))
            b = vector_backend({{"path": {str(tmp_path / "chroma")!r}}})
            await b.open()
            await b.put(s, m, [e])
            hits = await b.nearest(s, ["m1"], [1.0, 0.0, 0.0], TagFilter(), 1)
            await b.held(s.id, None)
            await b.delete(["m1"])
            await b.close()
            assert [h.chunk_id for h in hits] == ["c"], hits

        asyncio.run(main())
        heavy = {{"onnxruntime", "tokenizers"}}
        loaded = sorted(m for m in sys.modules if m.split(".")[0] in heavy)
        assert not loaded, loaded
        """
    )
    home = tmp_path / "home"
    home.mkdir()
    done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- this interpreter, the test script
        [sys.executable, "-c", script],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert not any(home.rglob("*")), sorted(home.rglob("*"))  # no model cache, no download


# ---------------------------------------------------------------- records and collections


def test_a_record_holds_scalars_only_and_one_key_per_tag() -> None:
    v1 = manifest("m1")
    found = record_metadata(entry(v1, "a", (1.0, 0.0, 0.0), tags=("api", "http")))

    assert found == {
        "manifest_id": "m1",
        "library": LIB,
        "version_id": f"{LIB}/v1",
        "chunk_id": "a",
        "article_path": "docs/a.md",
        "headings": "Docs > Retry policy",
        "tag:api": True,
        "tag:http": True,
    }
    assert search_filter(["m2", "m1"], TagFilter()) == {"manifest_id": {"$in": ["m1", "m2"]}}
    assert search_filter(["m1"], TagFilter(tags=("api", "http"))) == {
        "$and": [
            {"manifest_id": {"$in": ["m1"]}},
            {"$or": [{"tag:api": True}, {"tag:http": True}]},
        ]
    }
    assert search_filter(["m1"], TagFilter(tags=("api", "http"), match=TagMatch.ALL)) == {
        "$and": [{"manifest_id": {"$in": ["m1"]}}, {"tag:api": True}, {"tag:http": True}]
    }


async def test_a_space_is_a_collection_without_an_embedding_function(
    fresh: tuple[ChromaVectorBackend, dict],
) -> None:
    backend, options = fresh
    s, v1 = space(7, 3), manifest("m1")
    await backend.put(s, v1, [entry(v1, "a", (1.0, 0.0, 0.0), tags=("api", "http"))])

    with peer(options) as client:
        collection = client.get_collection(f"{backend.collection}_space7", embedding_function=None)
        records = collection.get(include=["metadatas", "embeddings", "documents"])

    assert collection.metadata["exactdocs_dimensions"] == 3
    assert collection.configuration_json["hnsw"]["space"] == "cosine"
    assert collection.configuration_json.get("embedding_function") in (None, {"type": "legacy"})
    assert records["documents"] == [None]  # no text: nothing Chroma could embed
    embeddings = records["embeddings"]
    assert embeddings is not None
    assert [list(v) for v in embeddings] == [[1.0, 0.0, 0.0]]
    metadata = (records["metadatas"] or [{}])[0]
    assert (metadata["manifest_id"], metadata["tag:api"], metadata["tag:http"]) == ("m1", 1, 1)
    hits = await backend.nearest(
        s, ["m1"], [1, 0, 0], TagFilter(tags=("api", "rest"), match=TagMatch.ALL), 5
    )
    assert hits == []


async def test_vectors_persist_in_the_embedded_clients_directory(tmp_path: Path) -> None:
    s, v1 = space(), manifest("m1")
    first = vector_backend({"path": str(tmp_path)})
    await first.open()
    await first.put(s, v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
    await first.close()

    again = vector_backend({"path": str(tmp_path)})
    await again.open()
    try:
        assert await again.held(s.id, None) == [
            HeldVersion(manifest_id="m1", library=LIB, entries=1)
        ]
    finally:
        await again.close()


async def test_a_collection_dropped_behind_its_back_is_made_again(
    fresh: tuple[ChromaVectorBackend, dict],
) -> None:
    backend, options = fresh
    s, v1 = space(), manifest("m1")
    await backend.put(s, v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
    with peer(options) as client:
        client.delete_collection(f"{backend.collection}_space1")

    assert await backend.nearest(s, ["m1"], [1, 0, 0], TagFilter(), 5) == []
    assert await backend.held(s.id, None) == []
    await backend.remove(s.id, "m1", [ChunkId("a")])  # nothing there: nothing to do
    await backend.put(s, v1, [entry(v1, "b", (0.0, 1.0, 0.0))])
    assert [h.chunk_id for h in await backend.nearest(s, ["m1"], [0, 1, 0], TagFilter(), 5)] == [
        "b"
    ]


async def test_another_instances_collection_is_never_written_to(
    fresh: tuple[ChromaVectorBackend, dict],
) -> None:
    backend, options = fresh
    v1 = manifest("m1")
    await backend.put(space(1, 3), v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
    other = vector_backend(options)  # the same prefix, another embedding model's dimensions
    await other.open()
    try:
        with pytest.raises(IndexBackendUnavailableError, match=r"3 dimensions .*not 4"):
            await other.put(space(1, 4), v1, [entry(v1, "a", (1.0, 0.0, 0.0, 0.0))])
        with pytest.raises(IndexBackendUnavailableError, match="another `collection` prefix"):
            await other.nearest(space(1, 4), ["m1"], [1, 0, 0, 0], TagFilter(), 5)
    finally:
        await other.close()


async def test_a_collection_not_made_by_exactdocs_is_left_alone(
    fresh: tuple[ChromaVectorBackend, dict],
) -> None:
    backend, options = fresh
    with peer(options) as client:  # someone else's collection, of the name of space 2
        theirs = client.create_collection(f"{backend.collection}_space2", embedding_function=None)
        theirs.add(ids=["x"], embeddings=[[1.0, 0.0, 0.0]], metadatas=[{"manifest_id": "m1"}])

    v1 = manifest("m1")
    with pytest.raises(IndexBackendUnavailableError, match="not made by ExactDocs"):
        await backend.put(space(2), v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
    with pytest.raises(IndexBackendUnavailableError, match="not made by ExactDocs"):
        await backend.held(EmbeddingSpaceId(2), None)
    await backend.delete(["m1"])  # not one of its own spaces' names: never touched

    with peer(options) as client:
        assert client.get_collection(f"{backend.collection}_space2").count() == 1


async def test_only_this_prefixs_collections_are_touched(
    fresh: tuple[ChromaVectorBackend, dict],
) -> None:
    backend, options = fresh
    s, v1 = space(), manifest("m1")
    neighbour = vector_backend({**options, "collection": f"{backend.collection}x"})
    await neighbour.open()
    try:
        await backend.put(s, v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
        await neighbour.put(s, v1, [entry(v1, "a", (1.0, 0.0, 0.0))])

        await backend.delete(["m1"])
        await backend.drop_space(s.id)

        assert await neighbour.held(s.id, None) == [
            HeldVersion(manifest_id="m1", library=LIB, entries=1)
        ]
    finally:
        await neighbour.close()


async def test_held_reads_every_page(
    fresh: tuple[ChromaVectorBackend, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    backend, _ = fresh
    monkeypatch.setattr("exactdocs.retrieval.adapters.driven.chroma_index.CHROMA_READ_PAGE", 2)
    s, v1, v2 = space(), manifest("m1"), manifest("m2", ref="v2")
    await backend.put(s, v1, [entry(v1, c, (1.0, 0.0, 0.0)) for c in "abc"])
    await backend.put(s, v2, [entry(v2, c, (0.0, 1.0, 0.0)) for c in "ab"])

    assert await backend.held(s.id, LIB) == [
        HeldVersion(manifest_id="m1", library=LIB, entries=3),
        HeldVersion(manifest_id="m2", library=LIB, entries=2),
    ]


async def test_a_closed_backend_is_unavailable() -> None:
    async with chroma_vectors("local") as backend:
        pass
    with pytest.raises(IndexBackendUnavailableError, match="not connected"):
        await backend.held(EmbeddingSpaceId(1), None)
