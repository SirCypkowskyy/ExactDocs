"""#364: Redis (Query Engine) as the search and vector backend, beyond the shared suites.

The shared suites (``test_index_backends.py``, ``test_search_index.py``,
``test_vector_index.py``) run the ``redis`` and ``redis_hybrid`` cases when
``EXACTDOCS_TEST_REDIS_URL`` names a server. Here: the options (``[index_backends.redis]``:
URL, credentials, TLS), the settings that pick the backend, and what only a server shows: the
indexes made with ``FT.CREATE`` from the space, a password checked, values the query syntax
would read as syntax, an index dropped behind the backend's back, another instance's index.
"""

import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest
from redis.asyncio import Redis

import integration
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.redis_index import (
    RedisHybridVectorBackend,
    RedisSearchBackend,
    RedisVectorBackend,
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
    TagMatch,
    TextQuery,
    search_terms,
)
from exactdocs.retrieval.ports import NativeHybrid
from redis_server import admin, drop, options, redis_search, redis_vectors

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
URL = "redis://127.0.0.1:6379"
NO_TAGS = TagFilter()

needs_redis = integration.REDIS


def manifest(manifest_id: str, library: str = LIB, ref: str = "v1") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{library}/{ref}", library=library, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str = "RetryPolicy decides how often a call is retried.",
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
        heading_path=("Docs", "Retry policy"),
        content=content,
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


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


# ---------------------------------------------------------------- options


@pytest.mark.parametrize(
    ("given", "refused"),
    [
        ({}, "url is required"),
        ({"url": "http://redis:6379"}, "url is required"),
        ({"url": URL, "collection": "x"}, "unknown options collection"),
        ({"url": "redis://:s3cret@redis:6379"}, "may not hold credentials"),
        ({"url": "redis://me@redis:6379"}, "may not hold credentials"),
        ({"url": "redis://redis:6379/2"}, "database other than 0"),
        ({"url": "redis://redis:99999"}, "invalid port"),
        ({"url": URL, "prefix": "a:b"}, "prefix 'a:b'"),
        ({"url": URL, "timeout": "soon"}, "timeout must be"),
        ({"url": URL, "timeout": 0}, "timeout must be"),
        ({"url": URL, "hybrid": "maybe"}, "hybrid must be true or false"),
        ({"url": URL, "vector_algorithm": "ivf"}, "vector_algorithm must be"),
        ({"url": URL, "password": "a", "password_file": "/x"}, "not both"),
        ({"url": URL, "password_file": "/nowhere/redis"}, "cannot be read"),
        ({"url": URL, "tls_ca_file": "/nowhere/ca.pem"}, "is not a file"),
    ],
)
def test_invalid_options_are_refused(given: dict[str, object], refused: str) -> None:
    with pytest.raises(ValueError, match=refused):
        search_backend(given)
    with pytest.raises(ValueError, match=refused):
        vector_backend(given)


def test_a_refused_url_never_repeats_its_password() -> None:
    with pytest.raises(ValueError, match="credentials") as refused:
        search_backend({"url": "redis://admin:s3cret@redis:6379"})

    assert "s3cret" not in str(refused.value)


def test_tls_options_need_rediss_and_a_client_certificate_needs_its_key(tmp_path: Path) -> None:
    ca, cert = tmp_path / "ca.pem", tmp_path / "client.pem"
    ca.write_text("ca", encoding="utf-8")
    cert.write_text("cert", encoding="utf-8")

    with pytest.raises(ValueError, match="need a rediss:// url"):
        search_backend({"url": URL, "tls_ca_file": str(ca)})
    with pytest.raises(ValueError, match="together"):
        search_backend({"url": "rediss://redis:6380", "tls_cert_file": str(cert)})


def test_the_client_is_made_from_the_options(tmp_path: Path) -> None:
    ca, cert, key, password = (tmp_path / n for n in ("ca.pem", "c.pem", "c.key", "password"))
    for path in (ca, cert, key):
        path.write_text("x", encoding="utf-8")
    password.write_text("s3cret\n", encoding="utf-8")
    backend = vector_backend(
        {
            "url": "rediss://redis.internal:6380",
            "prefix": "docs",
            "username": "exactdocs",
            "password_file": str(password),
            "tls_ca_file": str(ca),
            "tls_cert_file": str(cert),
            "tls_key_file": str(key),
            "timeout": "3",
        }
    )

    client = backend.connect()
    given = client.connection_pool.connection_kwargs

    assert (given["host"], given["port"], given["db"]) == ("redis.internal", 6380, 0)
    assert (given["username"], given["password"]) == ("exactdocs", "s3cret")
    assert (given["ssl_ca_certs"], given["ssl_certfile"], given["ssl_keyfile"]) == (
        str(ca),
        str(cert),
        str(key),
    )
    assert given["ssl_cert_reqs"] == "required"  # the server's certificate is always checked
    assert (given["socket_timeout"], backend.timeout_ms) == (3, 3000)
    assert (backend.prefix, backend.algorithm) == ("docs", "hnsw")
    assert "s3cret" not in repr(backend)


def test_hybrid_gives_the_native_hybrid_backend() -> None:
    plain = vector_backend({"url": URL})
    hybrid = vector_backend({"url": URL, "hybrid": "yes", "vector_algorithm": "FLAT"})

    assert type(plain) is RedisVectorBackend
    assert not isinstance(plain, NativeHybrid)
    assert isinstance(hybrid, RedisHybridVectorBackend)
    assert isinstance(hybrid, NativeHybrid)
    assert hybrid.algorithm == "flat"


def test_the_settings_put_both_indexes_in_redis() -> None:
    settings = Settings(
        search_backend="redis",
        vector_backend="redis",
        index_backends={"redis": {"url": URL, "prefix": "docs", "hybrid": True}},
    )

    backends = build_index_backends(settings)

    assert isinstance(backends.search, RedisSearchBackend)
    assert isinstance(backends.vectors, RedisHybridVectorBackend)
    assert backends.names == ("redis", "redis")
    assert backends.search.index == "docs:search"


async def test_a_server_that_does_not_answer_stops_the_start_naming_it() -> None:
    settings = Settings(
        search_backend="redis",
        index_backends={"redis": {"url": "redis://127.0.0.1:9", "timeout": 1}},
    )
    backends = build_index_backends(settings)

    with pytest.raises(StartupError, match=r"search backend 'redis'.*unreachable"):
        await backends.open()
    await backends.close()


# ---------------------------------------------------------------- against a server


@needs_redis
async def test_the_indexes_are_created_with_tag_fields_and_the_spaces_dimensions() -> None:
    async with redis_search() as search, redis_vectors() as vectors:
        v1 = manifest("m1")
        await search.put(v1, [entry(v1, "a")])
        await vectors.put(space(7, 5), v1, [entry(v1, "a", vector=(1.0, 0.0, 0.0, 0.0, 0.0))])
        assert isinstance(search, RedisSearchBackend)
        assert isinstance(vectors, RedisVectorBackend)

        client = admin()
        try:
            words = await client.execute_command("FT.INFO", search.index)
            near = await client.execute_command("FT.INFO", f"{vectors.prefix}:space7")
        finally:
            await client.aclose()

    def fields(info: dict) -> dict[str, dict]:
        return {a[b"attribute"].decode(): a for a in info[b"attributes"]}

    tagged = {"manifest_id", "library", "version_id", "chunk_id", "tags"}
    assert {n for n, a in fields(words).items() if a[b"type"] == b"TAG"} == tagged
    assert {n for n, a in fields(words).items() if a[b"type"] == b"TEXT"} == {
        "heading",
        "path",
        "text",
    }
    vector = fields(near)["vector"]
    assert (vector[b"dim"], vector[b"distance_metric"], vector[b"algorithm"]) == (
        5,
        b"COSINE",
        b"HNSW",
    )
    assert {n for n, a in fields(near).items() if a[b"type"] == b"TAG"} == tagged


@needs_redis
async def test_values_the_query_syntax_would_read_are_matched_as_they_are() -> None:
    async with redis_search() as search:
        odd, plain = manifest("m:1/x y", library="/acme/pay-ments"), manifest("m1")
        tags = ("v 2", "c++", "a|b", "日本")
        await search.put(odd, [entry(odd, "a/1", "Use --dry-run with v1.2", tags=tags)])
        await search.put(plain, [entry(plain, "a/1", "Use --dry-run with v1.2")])

        for tag in tags:
            for match in TagMatch:
                found = await search.search(
                    [odd.manifest_id, "m1"],
                    query("dry-run"),
                    TagFilter(tags=(tag,), match=match),
                    5,
                )
                assert [(h.manifest_id, h.chunk_id) for h in found] == [("m:1/x y", "a/1")], tag
        assert len(await search.search(["m:1/x y"], query("--dry-run v1.2"), NO_TAGS, 5)) == 1
        assert await search.held("/acme/pay-ments") == [
            HeldVersion(manifest_id="m:1/x y", library="/acme/pay-ments", entries=1)
        ]
        await search.delete(["m:1/x y"])
        assert [h.manifest_id for h in await search.held(None)] == ["m1"]


@needs_redis
async def test_an_index_dropped_behind_its_back_is_made_again_on_the_next_write() -> None:
    async with redis_search() as search, redis_vectors() as vectors:
        assert isinstance(search, RedisSearchBackend)
        assert isinstance(vectors, RedisVectorBackend)
        v1, s = manifest("m1"), space()
        await search.put(v1, [entry(v1, "a")])
        await vectors.put(s, v1, [entry(v1, "a", vector=(1.0, 0.0, 0.0))])
        await drop(search.prefix)
        await drop(vectors.prefix)

        assert await search.search(["m1"], query("retry"), NO_TAGS, 5) == []
        assert await vectors.nearest(s, ["m1"], [1, 0, 0], NO_TAGS, 5) == []
        assert await search.held(None) == []
        await search.put(v1, [entry(v1, "a")])
        await vectors.put(s, v1, [entry(v1, "a", vector=(1.0, 0.0, 0.0))])

        assert len(await search.search(["m1"], query("retry"), NO_TAGS, 5)) == 1
        assert len(await vectors.nearest(s, ["m1"], [1, 0, 0], NO_TAGS, 5)) == 1


@needs_redis
async def test_another_instances_index_of_other_dimensions_is_never_written_to() -> None:
    prefix = f"test_{secrets.token_hex(6)}"
    try:
        first, second = (vector_backend(options(prefix)) for _ in range(2))
        await first.open()
        await second.open()
        v1 = manifest("m1")
        await first.put(space(1, 3), v1, [entry(v1, "a", vector=(1.0, 0.0, 0.0))])

        with pytest.raises(IndexBackendUnavailableError, match="own `prefix`"):
            await second.put(space(1, 4), v1, [entry(v1, "a", vector=(1.0, 0.0, 0.0, 0.0))])
        await first.close()
        await second.close()
    finally:
        await drop(prefix)


@needs_redis
async def test_a_user_and_password_are_used_and_a_wrong_one_is_refused_unnamed() -> None:
    user, password = f"exactdocs_{secrets.token_hex(4)}", secrets.token_hex(16)
    prefix = f"test_{secrets.token_hex(6)}"
    client: Redis = admin()
    rules = ["+@read", "+@write", "+@search", "+@transaction", "+ping", "+info"]  # the docs'
    await client.execute_command(
        "ACL", "SETUSER", user, "on", f">{password}", f"~{prefix}:*", *rules
    )
    try:
        given = options(prefix) | {"username": user, "password": password}
        backend, vectors = search_backend(given), vector_backend(given | {"hybrid": True})
        await backend.open()
        await vectors.open()
        v1, s = manifest("m1"), space()
        await backend.put(v1, [entry(v1, "a")])
        await vectors.put(s, v1, [entry(v1, "a", vector=(1.0, 0.0, 0.0))])
        assert len(await backend.search(["m1"], query("retry"), NO_TAGS, 5)) == 1
        assert await backend.count(["m1"], query("retry"), NO_TAGS) == {"m1": 1}
        assert len(await vectors.nearest(s, ["m1"], [1, 0, 0], NO_TAGS, 5)) == 1
        assert isinstance(vectors, RedisHybridVectorBackend)
        assert len(await vectors.hybrid(s, ["m1"], query("retry"), [1, 0, 0], NO_TAGS, 5)) == 1
        assert len(await vectors.held(s.id, None)) == 1
        await backend.delete(["m1"])
        await vectors.delete(["m1"])
        await vectors.drop_space(s.id)
        await backend.close()
        await vectors.close()

        wrong = search_backend(given | {"password": "not-" + password})
        with pytest.raises(IndexBackendUnavailableError, match="authentication failed") as refused:
            await wrong.open()
        await wrong.close()
        assert password not in str(refused.value)
    finally:
        await client.execute_command("ACL", "DELUSER", user)
        await client.aclose()
        await drop(prefix)
