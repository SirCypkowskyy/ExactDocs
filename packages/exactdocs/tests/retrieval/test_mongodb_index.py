"""#363: MongoDB (Atlas Search and Vector Search) as the search and vector backend, beyond the
shared suites.

The shared suites (``test_index_backends.py``, ``test_search_index.py``,
``test_vector_index.py``) run the ``mongodb`` and ``mongodb_hybrid`` cases when
``EXACTDOCS_TEST_MONGODB_URL`` names a server. Here: the options (``[index_backends.mongodb]``:
connection string, credentials, names), the settings that pick the backend, and what only a
server shows: the search indexes made from the space and their filter fields, a password checked,
an index dropped behind the backend's back, another instance's index, ``$rankFusion`` and the
fusion in ExactDocs when the server has none, and exact vector search.
"""

import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.mongodb_index import (
    MongoHybridVectorBackend,
    MongoSearchBackend,
    MongoVectorBackend,
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
    TextQuery,
    search_terms,
)
from exactdocs.retrieval.ports import NativeHybrid
from mongodb_server import MONGODB_URL, admin, drop, fresh_database, options

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
URL = "mongodb://mongo.internal:27017/?replicaSet=rs0"
NO_TAGS = TagFilter()

needs_mongodb = pytest.mark.skipif(
    MONGODB_URL is None, reason="needs MongoDB with mongot: set EXACTDOCS_TEST_MONGODB_URL"
)


def manifest(manifest_id: str, library: str = LIB, ref: str = "v1") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{library}/{ref}", library=library, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str,
    *,
    tags: tuple[str, ...] = (),
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
        tags=tags,
        vector=vector,
    )


def space(space_id: int = 1, dimensions: int = 3) -> EmbeddingSpace:
    return EmbeddingSpace(
        id=EmbeddingSpaceId(space_id),
        spec=EmbeddingSpec(profile_kind="openai", model=f"m{space_id}", dimensions=dimensions),
        state=SpaceState.ACTIVE,
        created_at=T0,
    )


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


@pytest.mark.parametrize(
    ("given", "refused"),
    [
        ({}, "set url .* or url_file"),
        ({"url": URL, "url_file": "/x"}, "one of them"),
        ({"url": "http://mongo:27017"}, "must be mongodb://"),
        ({"url": "mongodb://"}, "must be mongodb://"),
        ({"url": URL, "port": 1}, "unknown options port"),
        ({"url": "mongodb://me:s3cret@mongo:27017"}, "may not hold a password"),
        ({"url": f"{URL}&tlsCertificateKeyFilePassword=x"}, "may not hold a password"),
        ({"url": URL, "database": "a.b"}, "database 'a.b'"),
        ({"url": URL, "collection": "chunks.search"}, "collection 'chunks.search'"),
        ({"url": URL, "timeout": "soon"}, "timeout must be"),
        ({"url": URL, "index_timeout": 0}, "index_timeout must be"),
        ({"url": URL, "hybrid": "maybe"}, "hybrid must be true or false"),
        ({"url": URL, "vector_search": "fuzzy"}, "vector_search must be"),
        ({"url": URL, "password": "a", "password_file": "/x"}, "cannot be read"),
        ({"url": URL, "password_file": "/nowhere/mongodb"}, "cannot be read"),
        ({"url_file": "/nowhere/mongodb-url"}, "cannot be read"),
    ],
)
def test_invalid_options_are_refused(given: dict[str, object], refused: str) -> None:
    with pytest.raises(ValueError, match=refused):
        search_backend(given)
    with pytest.raises(ValueError, match=refused):
        vector_backend(given)


def test_a_password_and_a_password_file_are_not_both_taken(tmp_path: Path) -> None:
    password = tmp_path / "password"
    password.write_text("s3cret", encoding="utf-8")

    with pytest.raises(ValueError, match="not both"):
        search_backend({"url": URL, "password": "a", "password_file": str(password)})


def test_a_refused_url_never_repeats_its_password() -> None:
    with pytest.raises(ValueError, match="password") as refused:
        search_backend({"url": "mongodb://admin:s3cret@mongo:27017"})

    assert "s3cret" not in str(refused.value)


def test_the_client_is_made_from_the_options(tmp_path: Path) -> None:
    password = tmp_path / "password"
    password.write_text("s3cret\n", encoding="utf-8")
    backend = vector_backend(
        {
            "url": URL,
            "username": "exactdocs",
            "password_file": str(password),
            "database": "docs",
            "collection": "sections",
            "timeout": "3",
            "index_timeout": 30,
            "vector_search": "EXACT",
        }
    )

    client = backend.connect()
    given = client.options

    assert (given.timeout, given.server_selection_timeout) == (3.0, 3.0)
    assert given.pool_options.connect_timeout == pytest.approx(3)
    assert given.replica_set_name == "rs0"
    assert given.pool_options.metadata["application"] == {"name": "exactdocs"}
    credentials = given.pool_options._credentials  # ruff: ignore[private-member-access] -- no API
    assert credentials is not None
    assert (credentials.username, credentials.password) == ("exactdocs", "s3cret")
    assert (backend.database, backend.collection, backend.index_timeout) == ("docs", "sections", 30)
    assert backend.exact
    assert "s3cret" not in repr(backend)


def test_a_url_file_holds_the_whole_connection_string(tmp_path: Path) -> None:
    secret = tmp_path / "url"
    secret.write_text("mongodb+srv://exactdocs:s3cret@cluster0.example.net/?w=majority\n", "utf-8")

    backend = search_backend({"url_file": str(secret)})

    assert backend.hidden == ("s3cret",)  # never repeated in a message
    credentials = backend.connect().options.pool_options._credentials  # ruff: ignore[private-member-access] -- no API
    assert credentials is not None
    assert (credentials.username, credentials.password) == ("exactdocs", "s3cret")
    assert "s3cret" not in repr(backend)


def test_hybrid_is_on_unless_turned_off() -> None:
    hybrid = vector_backend({"url": URL})
    plain = vector_backend({"url": URL, "hybrid": "off"})

    assert isinstance(hybrid, MongoHybridVectorBackend)
    assert isinstance(hybrid, NativeHybrid)
    assert type(plain) is MongoVectorBackend
    assert not isinstance(plain, NativeHybrid)
    assert not plain.exact  # approximate (HNSW) unless asked


def test_the_settings_put_both_indexes_in_mongodb() -> None:
    settings = Settings(
        search_backend="mongodb",
        vector_backend="mongodb",
        index_backends={"mongodb": {"url": URL, "database": "docs", "collection": "sections"}},
    )

    backends = build_index_backends(settings)

    assert isinstance(backends.search, MongoSearchBackend)
    assert isinstance(backends.vectors, MongoHybridVectorBackend)
    assert backends.names == ("mongodb", "mongodb")
    assert (backends.search.database, backends.search.collection) == ("docs", "sections")


async def test_a_server_that_does_not_answer_stops_the_start_naming_it() -> None:
    settings = Settings(
        vector_backend="mongodb",
        index_backends={"mongodb": {"url": "mongodb://127.0.0.1:9/", "timeout": 1}},
    )
    backends = build_index_backends(settings)

    with pytest.raises(StartupError, match=r"vector backend 'mongodb'.*unreachable"):
        await backends.open()
    await backends.close()


# ---------------------------------------------------------------- against a server


@pytest.fixture
async def database() -> object:
    name = fresh_database()
    yield name
    await drop(name)


async def _indexes(database: str, collection: str) -> dict[str, dict]:
    client = admin()
    try:
        cursor = await client[database][collection].list_search_indexes()
        return {i["name"]: dict(i) for i in await cursor.to_list()}
    finally:
        await client.close()


@needs_mongodb
async def test_the_indexes_are_made_with_filter_fields_and_the_spaces_dimensions(
    database: str,
) -> None:
    search = search_backend(options(database))
    vectors = vector_backend(options(database))
    await search.open()
    await vectors.open()
    try:
        v1 = manifest("m1")
        await search.put(v1, [entry(v1, "a", "retry policy", tags=("api",))])
        await vectors.put(space(7, 4), v1, [entry(v1, "a", "retry", vector=(1.0, 0, 0, 0))])
    finally:
        await search.close()
        await vectors.close()

    text = await _indexes(database, "chunks")
    assert set(text) == {"exactdocs_text"}
    fields = text["exactdocs_text"]["latestDefinition"]["mappings"]["fields"]
    assert {"manifest_id", "library", "version_id", "chunk_id", "tags"} <= {
        name for name, spec in fields.items() if spec["type"] == "token"
    }
    spaces = await _indexes(database, "chunks.space7")
    assert set(spaces) == {"exactdocs_text", "exactdocs_vectors"}  # hybrid: the words too
    definition = spaces["exactdocs_vectors"]["latestDefinition"]["fields"]
    vector = next(f for f in definition if f["type"] == "vector")
    assert (vector["numDimensions"], vector["similarity"]) == (4, "cosine")
    filters = {f["path"] for f in definition if f["type"] == "filter"}
    assert {"manifest_id", "library", "version_id", "tags"} <= filters
    client = admin()
    try:
        stored = await client[database]["chunks.space7"].find_one({})
    finally:
        await client.close()
    assert stored is not None
    assert (stored["library"], stored["version_id"], stored["manifest_id"]) == (
        LIB,
        f"{LIB}/v1",
        "m1",
    )


@needs_mongodb
async def test_another_instances_index_of_other_dimensions_is_never_written_to(
    database: str,
) -> None:
    first = vector_backend(options(database, hybrid=False))
    await first.open()
    v1 = manifest("m1")
    try:
        await first.put(space(1, 3), v1, [entry(v1, "a", "a", vector=(1.0, 0.0, 0.0))])
        with pytest.raises(IndexBackendUnavailableError, match="3 dimensions, not 4"):
            await first.put(space(1, 4), v1, [entry(v1, "b", "b", vector=(1.0, 0, 0, 0))])
        assert await first.held(EmbeddingSpaceId(1), None) == [
            HeldVersion(manifest_id="m1", library=LIB, entries=1)
        ]
    finally:
        await first.close()


@needs_mongodb
async def test_an_index_dropped_behind_its_back_is_made_again_on_the_next_write(
    database: str,
) -> None:
    backend = search_backend(options(database))
    await backend.open()
    v1 = manifest("m1")
    try:
        await backend.put(v1, [entry(v1, "a", "retry policy")])
        client = admin()
        try:
            await client[database]["chunks"].drop_search_index("exactdocs_text")
            await client[database].drop_collection("chunks")
        finally:
            await client.close()

        await backend.put(v1, [entry(v1, "b", "retry later")])

        found = await backend.search(["m1"], query("retry"), NO_TAGS, 10)
        assert [h.chunk_id for h in found] == ["b"]  # a was lost: a rebuild writes it again
    finally:
        await backend.close()


@needs_mongodb
async def test_hybrid_is_one_rank_fusion_stage_or_fused_in_exactdocs(database: str) -> None:
    backend = vector_backend(options(database))
    assert isinstance(backend, MongoHybridVectorBackend)
    await backend.open()
    s, v1 = space(), manifest("m1")
    try:
        assert backend.rank_fusion  # the pinned server has $rankFusion (MongoDB 8.1+)
        await backend.put(
            s,
            v1,
            [
                entry(v1, "words", "RetryPolicy decides retries", vector=(0.5, 1.0, 0.0)),
                entry(v1, "meaning", "how often calls run again", vector=(1.0, 0.0, 0.0)),
                entry(v1, "other", "unrelated", vector=(0.0, 0.0, 1.0)),
            ],
        )
        native = await backend.hybrid(s, ["m1"], query("RetryPolicy"), [1, 0, 0], NO_TAGS, 3)
        no_words = TextQuery(text="?", terms=())  # only the vector counts
        native_vector = await backend.hybrid(s, ["m1"], no_words, [0, 0, 1], NO_TAGS, 1)
        backend.rank_fusion = False  # a server without it: the same ranking, fused here
        fused = await backend.hybrid(s, ["m1"], query("RetryPolicy"), [1, 0, 0], NO_TAGS, 3)
        fused_vector = await backend.hybrid(s, ["m1"], no_words, [0, 0, 1], NO_TAGS, 1)
        unmatched = await backend.hybrid(s, ["m1"], query("zzz"), [0, 0, 1], NO_TAGS, 1)
    finally:
        await backend.close()

    assert [h.chunk_id for h in native][:2] in (["words", "meaning"], ["meaning", "words"])
    assert [h.chunk_id for h in fused] == [h.chunk_id for h in native]
    assert [h.score for h in fused] == pytest.approx([h.score for h in native])
    assert [h.chunk_id for h in native_vector] == [h.chunk_id for h in fused_vector] == ["other"]
    assert [h.chunk_id for h in unmatched] == ["other"]


@needs_mongodb
async def test_exact_vector_search_scans_every_filtered_vector(database: str) -> None:
    backend = vector_backend(options(database, hybrid=False) | {"vector_search": "exact"})
    await backend.open()
    s, v1 = space(), manifest("m1")
    try:
        await backend.put(
            s,
            v1,
            [entry(v1, f"c{n}", "x", vector=(1.0, n / 10, 0.0)) for n in range(30)],
        )
        found = await backend.nearest(s, ["m1"], [1, 0, 0], NO_TAGS, 3)
    finally:
        await backend.close()

    assert [h.chunk_id for h in found] == ["c0", "c1", "c2"]
    assert found[0].distance == pytest.approx(0, abs=1e-6)


@needs_mongodb
async def test_a_user_and_password_are_used_and_a_wrong_one_is_refused_unnamed(
    database: str,
) -> None:
    user, password = f"u{secrets.token_hex(4)}", secrets.token_urlsafe(16)
    client = admin()
    try:
        await client[database].command(
            "createUser", user, pwd=password, roles=[{"role": "readWrite", "db": database}]
        )
        given = options(database) | {"username": user}
        right = search_backend(given | {"password": password} | _auth_source(database))
        await right.open()
        await right.close()
        wrong = search_backend(given | {"password": "not-it"} | _auth_source(database))
        with pytest.raises(IndexBackendUnavailableError, match="authentication failed") as refused:
            await wrong.open()
        await wrong.close()
        assert "not-it" not in str(refused.value)
    finally:
        await client[database].command("dropUser", user)
        await client.close()


def _auth_source(database: str) -> dict[str, object]:
    """The test URL with the user's database as its ``authSource``."""
    assert MONGODB_URL is not None
    joiner = "&" if "?" in MONGODB_URL else "/?"
    return {"url": f"{MONGODB_URL}{joiner}authSource={database}"}
