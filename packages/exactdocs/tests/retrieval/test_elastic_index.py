"""#354: Elasticsearch and OpenSearch as the search and vector backends.

The shared contract suites (``test_search_index.py``, ``test_vector_index.py``,
``test_index_backends.py``) run on both engines when ``EXACTDOCS_TEST_ELASTICSEARCH_URL`` /
``EXACTDOCS_TEST_OPENSEARCH_URL`` name a cluster (``tests/fixtures/index_backends.py``). This
file adds what only these adapters have: their options and secrets, the start-up checks, the
analyzer that keeps identifiers searchable, the keyword fields every search filters by, and the
native hybrid query with its fallback.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven import elasticsearch_index, opensearch_index
from exactdocs.retrieval.adapters.driven.elastic_index import (
    ElasticSearchBackend,
    ElasticVectorBackend,
    parse_options,
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
from exactdocs.retrieval.ports import NativeHybrid
from index_backends import cluster_options, drop_indexes

ENGINES = {"elasticsearch": elasticsearch_index, "opensearch": opensearch_index}
CLUSTERS = [name for name in ENGINES if cluster_options(name) is not None]
T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
NO_TAGS = TagFilter()
UNREACHABLE = "http://127.0.0.1:9"  # the discard port: nothing answers


# ---------------------------------------------------------------- options


@pytest.mark.parametrize("name", list(ENGINES))
def test_the_url_is_required_and_must_be_http(name: str) -> None:
    with pytest.raises(ValueError, match="`url` is required"):
        ENGINES[name].search_backend({})
    with pytest.raises(ValueError, match="must start with http"):
        ENGINES[name].vector_backend({"url": "localhost:9200"})


@pytest.mark.parametrize("name", list(ENGINES))
def test_options_from_the_environment_are_strings(name: str) -> None:
    backend = ENGINES[name].search_backend(
        {
            "URL": "https://a:9200, https://b:9200",
            "index_prefix": "docs-prod",
            "verify_certs": "false",
            "request_timeout": "12.5",
            "number_of_shards": "3",
            "number_of_replicas": "0",
            "num_candidates": "50000",
            "refresh": "TRUE",
        }
    )

    options = backend.cluster.options
    assert options.urls == ("https://a:9200", "https://b:9200")
    assert (options.index_prefix, backend.index) == ("docs-prod", "docs-prod-search")
    assert (options.verify_certs, options.request_timeout) == (False, 12.5)
    assert (options.number_of_shards, options.number_of_replicas) == (3, 0)
    assert options.num_candidates == 10_000  # both engines' cap
    assert options.refresh == "true"


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("index_prefix", "Docs", "index_prefix"),
        ("index_prefix", "logs-*", "index_prefix"),
        ("index_prefix", ".hidden", "index_prefix"),
        ("verify_certs", "maybe", "verify_certs"),
        ("request_timeout", "0", "request_timeout"),
        ("number_of_shards", "0", "number_of_shards"),
        ("number_of_replicas", "-1", "number_of_replicas"),
        ("refresh", "false", "refresh"),
        ("ca_certs", "/nowhere/ca.pem", "ca_certs"),
        ("shards", "1", "unknown option"),
    ],
)
def test_invalid_options_are_refused_naming_the_option(
    option: str, value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_options("elasticsearch", {"url": "http://es:9200", option: value}, ("api_key",))


def test_a_secret_comes_from_the_environment_or_a_file_never_both(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("s3cr3t-key\n", "utf-8")
    url = {"url": "http://es:9200"}

    from_file = elasticsearch_index.search_backend({**url, "api_key_file": str(key_file)})
    from_env = elasticsearch_index.search_backend({**url, "api_key": "s3cr3t-key"})

    assert from_file.cluster.options.api_key == from_env.cluster.options.api_key == "s3cr3t-key"
    with pytest.raises(ValueError, match="not both"):
        elasticsearch_index.search_backend({**url, "api_key": "x", "api_key_file": str(key_file)})
    with pytest.raises(ValueError, match="cannot be read"):
        elasticsearch_index.search_backend({**url, "api_key_file": str(tmp_path / "missing")})
    (tmp_path / "empty").write_text("", "utf-8")
    with pytest.raises(ValueError, match="is empty"):
        opensearch_index.search_backend({**url, "password_file": str(tmp_path / "empty")})


def test_one_way_to_sign_in() -> None:
    url = {"url": "https://es:9200"}

    with pytest.raises(ValueError, match="sign in one way"):
        elasticsearch_index.search_backend({**url, "api_key": "k", "username": "u"})
    with pytest.raises(ValueError, match="sign in one way"):
        opensearch_index.search_backend({**url, "token": "t", "username": "u"})
    with pytest.raises(ValueError, match="needs `username`"):
        opensearch_index.search_backend({**url, "password": "p"})
    with pytest.raises(ValueError, match="unknown option"):  # OpenSearch has no API keys
        opensearch_index.search_backend({**url, "api_key": "k"})
    signed_in = opensearch_index.vector_backend({**url, "username": "u", "password": "p"})
    assert (signed_in.cluster.options.username, signed_in.cluster.options.password) == ("u", "p")


@pytest.mark.parametrize("name", list(ENGINES))
def test_the_settings_build_the_backend_and_refuse_bad_options(name: str) -> None:
    settings = Settings(
        search_backend=name,
        vector_backend=name,
        index_backends={name: {"url": "http://cluster:9200"}},
    )

    built = build_index_backends(settings)

    assert built.names == (name, name)
    assert isinstance(built.search, ElasticSearchBackend)
    assert isinstance(built.vectors, ElasticVectorBackend)
    assert isinstance(built.vectors, NativeHybrid)
    with pytest.raises(StartupError, match=rf"\[index_backends\.{name}\].*`url` is required"):
        build_index_backends(Settings(search_backend=name))


@pytest.mark.parametrize("name", list(ENGINES))
async def test_a_cluster_that_does_not_answer_is_unavailable_at_open(name: str) -> None:
    backend = ENGINES[name].search_backend({"url": UNREACHABLE, "request_timeout": "2"})

    with pytest.raises(IndexBackendUnavailableError) as raised:
        await backend.open()
    await backend.close()

    assert raised.value.backend == name


# ---------------------------------------------------------------- against a cluster


def manifest(manifest_id: str, library: str = "/acme/payments", ref: str = "v1") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{library}/{ref}", library=library, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str,
    *,
    heading: str = "Guide",
    vector: tuple[float, ...] | None = None,
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", heading),
        content=content,
        tags=(),
        vector=vector,
    )


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


SPACE = EmbeddingSpace(
    id=EmbeddingSpaceId(7),
    spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=3),
    state=SpaceState.ACTIVE,
    created_at=T0,
)


@pytest.fixture(params=CLUSTERS)
async def search(request: pytest.FixtureRequest) -> AsyncIterator[ElasticSearchBackend]:
    options = cluster_options(request.param)
    assert options is not None
    backend = ENGINES[request.param].search_backend(options)
    await backend.open()
    try:
        yield backend
    finally:
        await drop_indexes(backend)
        await backend.close()


@pytest.fixture(params=CLUSTERS)
async def vectors(request: pytest.FixtureRequest) -> AsyncIterator[ElasticVectorBackend]:
    options = cluster_options(request.param)
    assert options is not None
    backend = ENGINES[request.param].vector_backend(options)
    await backend.open()
    try:
        yield backend
    finally:
        await drop_indexes(backend)
        await backend.close()


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("max_retries", "snake"),  # snake_case, whole
        ("MAX_RETRIES", "snake"),
        ("retries", "snake"),  # and by its parts
        ("retryPolicy", "camel"),  # camelCase, whole
        ("policy", "camel"),
        ("client.retry.timeout", "dotted"),  # dotted, whole
        ("timeout", "dotted"),
        ("--dry-run", "flag"),
        ("v1.4.0", "version"),
        ("crème", "accent"),
        ("creme", "accent"),  # folded, as FTS5's unicode61
    ],
)
async def test_identifiers_are_found_whole_and_by_their_parts(
    search: ElasticSearchBackend, text: str, found: str
) -> None:
    v1 = manifest("m1")
    await search.put(
        v1,
        [
            entry(v1, "snake", "Set `max_retries` on the client."),
            entry(v1, "camel", "The retryPolicy object decides."),
            entry(v1, "dotted", "Configure client.retry.timeout first."),
            entry(v1, "flag", "Run it with --dry-run to see."),
            entry(v1, "version", "Released in v1.4.0 last spring."),
            entry(v1, "accent", "La crème brûlée."),
            entry(v1, "other", "Nothing to see here."),
        ],
    )

    hits = await search.search(["m1"], query(text), NO_TAGS, 3)

    assert hits, text
    assert hits[0].chunk_id == found, (text, hits)


async def test_the_keys_are_keyword_fields_filtered_inside_the_cluster(
    search: ElasticSearchBackend,
) -> None:
    mapping = await search.cluster.send("GET", f"/{search.index}/_mapping")

    fields = mapping.body[search.index]["mappings"]["properties"]
    assert {fields[k]["type"] for k in ("manifest_id", "library", "version_id", "tags")} == {
        "keyword"
    }
    assert fields["body"]["analyzer"] == "exactdocs_words"


async def test_a_vector_index_per_space_holds_a_dense_vector_field(
    vectors: ElasticVectorBackend,
) -> None:
    v1 = manifest("m1")
    await vectors.put(SPACE, v1, [entry(v1, "a", "a", vector=(1.0, 0.0, 0.0))])

    index = vectors.index(SPACE.id)
    mapping = await vectors.cluster.send("GET", f"/{index}/_mapping")

    vector = mapping.body[index]["mappings"]["properties"]["vector"]
    assert vector["type"] in {"dense_vector", "knn_vector"}
    assert vector.get("dims", vector.get("dimension")) == 3


async def test_hybrid_is_native_and_falls_back_to_fusing_here(
    vectors: ElasticVectorBackend,
) -> None:
    v1, v2 = manifest("m1"), manifest("m2", ref="v2")
    await vectors.put(
        SPACE,
        v1,
        [
            entry(v1, "words", "RetryPolicy decides retries", vector=(0.0, 1.0, 0.0)),
            entry(v1, "meaning", "how often calls run again", vector=(1.0, 0.0, 0.0)),
            entry(v1, "other", "unrelated", vector=(0.0, 0.0, 1.0)),
        ],
    )
    await vectors.put(SPACE, v2, [entry(v2, "words", "RetryPolicy", vector=(1.0, 0.0, 0.0))])

    native = await vectors.hybrid(SPACE, ["m1"], query("RetryPolicy"), [1, 0, 0], NO_TAGS, 2)
    assert vectors.native, "the test cluster answers the native hybrid query (a trial licence)"
    vectors.native = False  # as when the cluster refuses it
    fused = await vectors.hybrid(SPACE, ["m1"], query("RetryPolicy"), [1, 0, 0], NO_TAGS, 2)

    for found in (native, fused):
        assert {h.manifest_id for h in found} == {"m1"}
        assert {h.chunk_id for h in found} == {"words", "meaning"}


async def test_the_other_engine_is_refused_at_open() -> None:
    if len(CLUSTERS) < len(ENGINES):
        pytest.skip("needs both test clusters")
    es, os_ = cluster_options("elasticsearch"), cluster_options("opensearch")
    assert es is not None
    assert os_ is not None
    for module, options, other in [
        (elasticsearch_index, os_, "OpenSearch|not Elasticsearch"),  # or the client's own check
        (opensearch_index, es, "Elasticsearch"),
    ]:
        backend = module.search_backend(options)
        with pytest.raises(IndexBackendUnavailableError, match=other):
            await backend.open()
        await backend.close()
