"""Elasticsearch and OpenSearch as the search and vector backends (#354): what both share.

The two engines answer the same REST API for everything ExactDocs asks (index mappings, bulk
writes, delete by query, BM25 ``bool``/``match`` queries, composite aggregations), so this module
builds the requests and reads the answers once; ``elasticsearch_index`` and ``opensearch_index``
only add their client (``Engine``: one request in, the JSON answer out) and their options. Where
the engines differ (the vector field, the kNN query, the native hybrid query) the ``flavour``
decides. Nothing here imports either client.

**Indexes.** The search index is ``<prefix>-search``; each embedding space has its own
``<prefix>-vectors-<space ID>`` (its dimensions are fixed in the mapping, and dropping a space
deletes one index). Every document is one chunk of one version (``IndexEntry``), keyed by its
manifest and chunk ID, with ``manifest_id``, ``library``, ``version_id``, ``chunk_id``,
``article_path`` and ``tags`` as ``keyword`` fields: every search filters by manifest ID inside
the cluster, so another version's chunk never comes back. Vector documents carry the same text
fields as search documents, for the native hybrid query.

**Identifiers.** The heading, path and text fields use the ``exactdocs_words`` analyzer: words
of letters, digits, marks and ``-_.`` (``retry_policy``, ``v1.4.0``, ``--dry-run`` stay whole),
lower case and ASCII-folded, nothing trimmed (as FTS5's tokenizer). The ``identifiers``
field holds ``identifier_tokens`` of the heading path and text (``retryPolicy`` is
``retrypolicy retry policy``), whitespace-separated, so camelCase, snake_case and dotted names
are found by their whole and by their parts, as in the database's own indexes. The query is
never parsed: each of its terms (``TextQuery.terms``) is a ``dis_max`` of one ``match`` per
field, with the database engines' weights (``ELASTIC_FIELD_BOOSTS``), so a term counts in its
best field as FTS5 saturates it once over all columns; the terms are OR-ed and their scores add
up (#472).

**Native hybrid.** Elasticsearch fuses the BM25 and kNN halves with its RRF retriever;
OpenSearch with a ``hybrid`` query and a normalisation search pipeline (``<prefix>-hybrid``,
created at start). A cluster that refuses it (Elasticsearch's RRF needs an Enterprise or trial
licence; OpenSearch needs the neural-search plugin) gets the same two halves asked separately and
fused here with reciprocal rank fusion, as ExactDocs fuses the database's; the start logs it once.
"""

import hashlib
import json
import logging
import math
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol

from exactdocs.retrieval.constants import (
    ELASTIC_DISTANCE_DECIMALS,
    ELASTIC_ERROR_CHARS,
    ELASTIC_FIELD_BOOSTS,
    ELASTIC_INDEX_PREFIX,
    ELASTIC_MAX_CANDIDATES,
    ELASTIC_MIN_MAJOR,
    ELASTIC_NUM_CANDIDATES,
    ELASTIC_OPTIONS,
    ELASTIC_PAGE,
    ELASTIC_PREFIX_PATTERN,
    ELASTIC_REFRESH,
    ELASTIC_REQUEST_TIMEOUT,
    ELASTIC_TIE_BREAKER,
    ELASTIC_WORDS_PATTERN,
    OPENSEARCH_BACKEND,
    OPENSEARCH_COMBINATION,
    OPENSEARCH_HYBRID_WEIGHTS,
    OPENSEARCH_NORMALIZATION,
    RRF_DEPTH,
    RRF_K,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs.retrieval.models import (
    BackendHit,
    BackendNeighbour,
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    HeldVersion,
    IndexedManifest,
    IndexEntry,
    TagFilter,
    TagMatch,
    TextQuery,
    fuse_across_manifests,
    identifier_tokens,
)

logger = logging.getLogger(__name__)

type Flavour = str
"""The engine: ``elasticsearch`` or ``opensearch`` (the backend constants of the same names)."""
type Json = dict[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class Answer:
    """What the cluster answered to one request."""

    status: int
    """The HTTP status."""
    body: Json
    """The JSON answer (empty when it had none, as a ``HEAD``)."""


class Engine(Protocol):
    """One cluster's client, as both engines' modules wrap it: a request in, its JSON out."""

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: object = None,
        params: Mapping[str, str] | None = None,
        ndjson: bool = False,
        allow: Collection[int] = (),
    ) -> Answer:
        """Send one request.

        Args:
            method: ``GET``, ``PUT``, ``POST``, ``DELETE`` or ``HEAD``.
            path: The path, from ``/``.
            body: A JSON body, or newline-delimited JSON text when ``ndjson``.
            params: The query string.
            ndjson: The body is ``_bulk`` text.
            allow: Error statuses answered instead of raised (``404``...).

        Returns:
            The status and the JSON answer.

        Raises:
            IndexBackendUnavailableError: The cluster could not be reached, or answered with an
                error status not in ``allow``.
        """
        ...

    async def close(self) -> None:
        """Close the client's connections."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ElasticOptions:
    """An ``[index_backends.elasticsearch]`` or ``[index_backends.opensearch]`` table, checked."""

    urls: tuple[str, ...]
    """The cluster's nodes (``url``: one URL, or several separated by commas)."""
    index_prefix: str = ELASTIC_INDEX_PREFIX
    """What every index name starts with."""
    api_key: str | None = None
    """An Elasticsearch API key (``api_key`` from the environment, or ``api_key_file``)."""
    username: str | None = None
    """The basic-auth user."""
    password: str | None = None
    """The basic-auth password (``password`` from the environment, or ``password_file``)."""
    token: str | None = None
    """A bearer token (``token`` from the environment, or ``token_file``)."""
    ca_certs: str | None = None
    """A PEM file of the certificate authorities a ``https`` cluster's certificate is checked
    against (the system's when unset)."""
    verify_certs: bool = True
    """Whether the certificate is checked at all."""
    request_timeout: float = ELASTIC_REQUEST_TIMEOUT
    """Seconds before a request gives up."""
    number_of_shards: int = 1
    """Primary shards of each index ExactDocs creates."""
    number_of_replicas: int | None = None
    """Replicas of each index ExactDocs creates (the cluster's default when unset)."""
    num_candidates: int = ELASTIC_NUM_CANDIDATES
    """The fewest HNSW candidates a kNN search considers."""
    refresh: str = "wait_for"
    """How a write waits until it is searchable (``ELASTIC_REFRESH``)."""


def parse_options(
    backend: str, options: Mapping[str, object], secrets: Collection[str]
) -> ElasticOptions:
    """Check a backend's options table and read its secrets.

    Args:
        backend: The backend's name, for messages.
        options: The table (``[index_backends.<name>]`` or the environment's values: strings).
        secrets: The secrets the engine takes (``api_key``, ``password``, ``token``), each also
            as ``<secret>_file``.

    Returns:
        The options.

    Raises:
        ValueError: An option is unknown, missing or invalid, a secret is given twice, or a
            secret file cannot be read.
    """
    given = {str(k).lower(): v for k, v in options.items() if v is not None and str(v)}
    known = ELASTIC_OPTIONS | set(secrets) | {f"{s}_file" for s in secrets}
    unknown = sorted(set(given) - known)
    if unknown:
        message = f"unknown option(s) {', '.join(unknown)} (known: {', '.join(sorted(known))})"
        raise ValueError(message)
    urls = tuple(u.strip() for u in str(given.get("url", "")).split(",") if u.strip())
    if not urls:
        message = f"`url` is required: the {backend} cluster's URL (https://host:9200)"
        raise ValueError(message)
    for url in urls:
        if not url.startswith(("http://", "https://")):
            message = (
                "`url` must start with http:// or https://"  # never echoed: it may hold a password
            )
            raise ValueError(message)
    prefix = str(given.get("index_prefix", ELASTIC_INDEX_PREFIX))
    if not ELASTIC_PREFIX_PATTERN.fullmatch(prefix):
        message = (
            f"`index_prefix` {prefix!r} must be lower case letters, digits, `_` and `-`, starting "
            "with a letter or digit, at most 100 characters"
        )
        raise ValueError(message)
    read = {s: _secret(given, s) for s in secrets}
    refresh = str(given.get("refresh", "wait_for")).lower()
    if refresh not in ELASTIC_REFRESH:
        message = f"`refresh` must be one of {', '.join(sorted(ELASTIC_REFRESH))}"
        raise ValueError(message)
    if read.get("password") is not None and "username" not in given:
        message = "`password` needs `username`"
        raise ValueError(message)
    ca_certs = str(given["ca_certs"]) if "ca_certs" in given else None
    if ca_certs is not None and not Path(ca_certs).is_file():
        message = f"`ca_certs` {ca_certs!r} is not a readable file"
        raise ValueError(message)
    replicas = given.get("number_of_replicas")
    return ElasticOptions(
        urls=urls,
        index_prefix=prefix,
        api_key=read.get("api_key"),
        username=str(given["username"]) if "username" in given else None,
        password=read.get("password"),
        token=read.get("token"),
        ca_certs=ca_certs,
        verify_certs=_flag(given.get("verify_certs", True), "verify_certs"),
        request_timeout=_seconds(given.get("request_timeout", ELASTIC_REQUEST_TIMEOUT)),
        number_of_shards=_count(given.get("number_of_shards", 1), "number_of_shards", 1),
        number_of_replicas=None if replicas is None else _count(replicas, "number_of_replicas", 0),
        num_candidates=min(
            _count(given.get("num_candidates", ELASTIC_NUM_CANDIDATES), "num_candidates", 1),
            ELASTIC_MAX_CANDIDATES,
        ),
        refresh=refresh,
    )


def _secret(given: Mapping[str, object], name: str) -> str | None:
    """Read a secret from its option or from the file ``<name>_file`` names.

    Args:
        given: The options.
        name: The secret's option.

    Returns:
        The secret, or ``None`` when neither is set.

    Raises:
        ValueError: Both are set, or the file cannot be read or is empty.
    """
    value, path = given.get(name), given.get(f"{name}_file")
    if value is not None and path is not None:
        message = f"set `{name}` or `{name}_file`, not both"
        raise ValueError(message)
    if path is None:
        return None if value is None else str(value).strip() or None
    try:
        read = Path(str(path)).read_text("utf-8").strip()
    except OSError as error:
        message = f"`{name}_file` {str(path)!r} cannot be read ({error.strerror or error})"
        raise ValueError(message) from error
    if not read:
        message = f"`{name}_file` {str(path)!r} is empty"
        raise ValueError(message)
    return read


def _flag(value: object, name: str) -> bool:
    """Read a boolean option (``true``/``false`` from the environment).

    Args:
        value: The raw value.
        name: The option, for the message.

    Returns:
        The flag.

    Raises:
        ValueError: It is not a boolean.
    """
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    message = f"`{name}` must be true or false"
    raise ValueError(message)


def _count(value: object, name: str, least: int) -> int:
    """Read a whole-number option.

    Args:
        value: The raw value.
        name: The option, for the message.
        least: Its smallest value.

    Returns:
        The number.

    Raises:
        ValueError: It is not a whole number of at least ``least``.
    """
    try:
        number = int(str(value).strip())
    except ValueError:
        number = least - 1
    if isinstance(value, bool) or number < least:
        message = f"`{name}` must be a whole number of at least {least}"
        raise ValueError(message)
    return number


def _seconds(value: object) -> float:
    """Read ``request_timeout``: a positive number of seconds.

    Args:
        value: The raw value.

    Returns:
        The number.

    Raises:
        ValueError: It is not a positive number.
    """
    try:
        number = float(str(value).strip())
    except ValueError:
        number = 0.0
    if isinstance(value, bool) or not math.isfinite(number) or number <= 0:
        message = "`request_timeout` must be a positive number of seconds"
        raise ValueError(message)
    return number


def error_reason(status: int, body: object) -> str:
    """Say in a few words why the cluster refused a request (its error type and reason).

    Args:
        status: The HTTP status.
        body: The error answer (JSON or text).

    Returns:
        ``<status> <type>: <reason>``, cut to ``ELASTIC_ERROR_CHARS``.
    """
    error = body.get("error") if isinstance(body, Mapping) else body
    if isinstance(error, Mapping):
        causes = error.get("root_cause") or [error]
        first = causes[0] if isinstance(causes, list) and causes else error
        text = f"{first.get('type', 'error')}: {first.get('reason', '')}"
    else:
        text = str(error or "no reason given")
    return f"{status} {text}"[:ELASTIC_ERROR_CHARS]


def _doc_id(manifest_id: str, chunk_id: str) -> str:
    """Return the document ID of a chunk of a version (index IDs are limited to 512 bytes).

    Args:
        manifest_id: The version.
        chunk_id: The chunk.

    Returns:
        A hex digest of both.
    """
    return hashlib.sha256(f"{manifest_id}\x00{chunk_id}".encode()).hexdigest()


def _document(entry: IndexEntry) -> Json:
    """Return the document of an entry: its keys, its text fields and its vector, if any.

    Args:
        entry: The entry.

    Returns:
        The document.
    """
    heading_path = [unicodedata.normalize("NFC", h) for h in entry.heading_path]
    content = unicodedata.normalize("NFC", entry.content)
    document: Json = {
        "manifest_id": entry.manifest_id,
        "library": entry.library,
        "version_id": entry.version_id,
        "chunk_id": entry.chunk_id,
        "article_path": entry.article_path,
        "tags": list(entry.tags),
        "heading": heading_path[-1] if heading_path else "",
        "path": " / ".join(heading_path[:-1]),
        "body": content,
        "identifiers": identifier_tokens(f"{' / '.join(heading_path)}\n{content}"),
    }
    if entry.vector is not None:
        document["vector"] = list(entry.vector)
    return document


def _filters(manifest_ids: Sequence[str], tag_filter: TagFilter) -> list[Json]:
    """Return the filters of a search: the versions, then the tags.

    Args:
        manifest_ids: The versions searched.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        ``bool`` filter clauses.
    """
    clauses: list[Json] = [{"terms": {"manifest_id": list(dict.fromkeys(manifest_ids))}}]
    if tag_filter.tags and tag_filter.match is TagMatch.ALL:
        clauses.extend({"term": {"tags": tag}} for tag in tag_filter.tags)
    elif tag_filter.tags:
        clauses.append({"terms": {"tags": list(tag_filter.tags)}})
    return clauses


def _text_query(manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter) -> Json:
    """Return the BM25 query: any term in any text field, weighted, within the versions.

    Each term scores in its best field (``dis_max``, ``ELASTIC_TIE_BREAKER``), and the terms'
    scores add up: a term in both a section's heading and its text is not counted twice.

    Args:
        manifest_ids: The versions searched.
        query: The query's terms (alternatives); its text is never parsed.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        A ``bool`` query.
    """
    return {
        "bool": {
            "filter": _filters(manifest_ids, tag_filter),
            "should": [
                {
                    "dis_max": {
                        "queries": [
                            {"match": {name: {"query": term, "boost": boost}}}
                            for name, boost in ELASTIC_FIELD_BOOSTS.items()
                        ],
                        "tie_breaker": ELASTIC_TIE_BREAKER,
                    }
                }
                for term in query.terms
            ],
            "minimum_should_match": 1,
        }
    }


def _settings(options: ElasticOptions, flavour: Flavour) -> Json:
    """Return an index's settings: its shards and the analyzers of the text fields.

    Args:
        options: The backend's options.
        flavour: The engine.

    Returns:
        The ``settings`` of an index creation.
    """
    index: Json = {"number_of_shards": options.number_of_shards}
    if options.number_of_replicas is not None:
        index["number_of_replicas"] = options.number_of_replicas
    if flavour == OPENSEARCH_BACKEND:
        index["knn"] = True
    return {
        "index": index,
        "analysis": {
            "tokenizer": {
                "exactdocs_words": {
                    "type": "pattern",
                    "pattern": ELASTIC_WORDS_PATTERN,
                    "group": 0,
                }
            },
            "analyzer": {
                "exactdocs_words": {
                    "type": "custom",
                    "tokenizer": "exactdocs_words",
                    "filter": ["lowercase", "asciifolding"],
                },
                "exactdocs_identifiers": {"type": "custom", "tokenizer": "whitespace"},
            },
        },
    }


def _mappings(flavour: Flavour, dimensions: int | None) -> Json:
    """Return an index's mappings: keyword keys, analysed text and, for vectors, the vector.

    Args:
        flavour: The engine.
        dimensions: The space's dimensions; ``None`` for the search index.

    Returns:
        The ``mappings`` of an index creation.
    """
    words = {"type": "text", "analyzer": "exactdocs_words"}
    properties: Json = {
        "manifest_id": {"type": "keyword"},
        "library": {"type": "keyword"},
        "version_id": {"type": "keyword"},
        "chunk_id": {"type": "keyword"},
        "article_path": {"type": "keyword", "index": False},
        "tags": {"type": "keyword"},
        "heading": words,
        "path": words,
        "body": words,
        "identifiers": {"type": "text", "analyzer": "exactdocs_identifiers"},
    }
    if dimensions is not None and flavour == OPENSEARCH_BACKEND:
        properties["vector"] = {
            "type": "knn_vector",
            "dimension": dimensions,
            "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
        }
    elif dimensions is not None:
        properties["vector"] = {
            "type": "dense_vector",
            "dims": dimensions,
            "index": True,
            "similarity": "cosine",
            "index_options": {"type": "hnsw"},  # unquantised: distances as the database's
        }
    return {"dynamic": "strict", "properties": properties}


def _distance(score: float) -> float:
    """Turn a cosine kNN score, ``(1 + cos) / 2`` in both engines, into a cosine distance.

    Args:
        score: The score.

    Returns:
        ``1 - cos``, within 0 to 2.
    """
    return min(2.0, max(0.0, 2.0 - 2.0 * score))


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- opened at start
class _Cluster:
    """The connection both backends of an engine keep: opened at start, closed at stop."""

    name: str
    """The backend's registered name."""
    flavour: Flavour
    """The engine."""
    options: ElasticOptions
    """The checked options."""
    connect: Callable[[ElasticOptions], Engine]
    """Builds the client (no connection is made until the first request)."""
    engine: Engine | None = field(default=None, init=False)
    """The client, once opened."""

    async def open(self) -> None:
        """Connect and check the cluster is the engine named, in a version that works.

        ``IndexBackendUnavailableError`` when it cannot be reached, or is another engine or too
        old; the client is closed then.
        """
        if self.engine is None:
            self.engine = self.connect(self.options)
        try:
            await self._check(self.engine)
        except BaseException:
            await self.close()  # a start that failed leaves no client open
            raise

    async def _check(self, engine: Engine) -> None:
        """Check the cluster is the engine named, in a version that works.

        Args:
            engine: The client.

        Raises:
            IndexBackendUnavailableError: It is another engine, or too old.
        """
        about = (await engine.request("GET", "/")).body
        version = about.get("version", {}) if isinstance(about.get("version"), dict) else {}
        is_opensearch = version.get("distribution") == "opensearch"
        if is_opensearch != (self.flavour == OPENSEARCH_BACKEND):
            found = "OpenSearch" if is_opensearch else "Elasticsearch"
            reason = f"the cluster at the configured url is {found}, not {self.flavour}"
            raise IndexBackendUnavailableError(self.name, reason)
        number = str(version.get("number", "0"))
        first = number.partition(".")[0]
        major = int(first) if first.isdigit() else 0
        if major < ELASTIC_MIN_MAJOR[self.flavour]:
            reason = f"version {number} is too old (needs {ELASTIC_MIN_MAJOR[self.flavour]}.0+)"
            raise IndexBackendUnavailableError(self.name, reason)

    async def close(self) -> None:
        """Close the client, if opened."""
        if self.engine is not None:
            engine, self.engine = self.engine, None
            await engine.close()

    async def send(
        self,
        method: str,
        path: str,
        *,
        body: object = None,
        params: Mapping[str, str] | None = None,
        ndjson: bool = False,
        allow: Collection[int] = (),
    ) -> Answer:
        """Send a request on the opened client.

        Args:
            method: The method.
            path: The path.
            body: The body.
            params: The query string.
            ndjson: The body is ``_bulk`` text.
            allow: Error statuses answered instead of raised.

        Returns:
            The answer.

        Raises:
            IndexBackendUnavailableError: Not opened, unreachable, or an error status.
        """
        if self.engine is None:
            raise IndexBackendUnavailableError(self.name, "not opened")
        return await self.engine.request(
            method, path, body=body, params=params, ndjson=ndjson, allow=allow
        )

    async def create_index(self, index: str, dimensions: int | None) -> None:
        """Create an index with ExactDocs' settings and mappings; one that exists is kept.

        Args:
            index: Its name.
            dimensions: Its vector field's dimensions; ``None`` for the search index.

        Raises:
            IndexBackendUnavailableError: The cluster refused it.
        """
        if (
            await self.send("HEAD", f"/{index}", allow=(HTTPStatus.NOT_FOUND,))
        ).status != HTTPStatus.NOT_FOUND:
            return
        body = {
            "settings": _settings(self.options, self.flavour),
            "mappings": _mappings(self.flavour, dimensions),
        }
        answer = await self.send("PUT", f"/{index}", body=body, allow=(HTTPStatus.BAD_REQUEST,))
        if answer.status == HTTPStatus.BAD_REQUEST and not _already_exists(answer.body):
            raise IndexBackendUnavailableError(self.name, error_reason(answer.status, answer.body))

    async def bulk(self, index: str, actions: Sequence[tuple[Json, Json | None]]) -> None:
        """Write documents (index or delete actions) and wait until they are searchable.

        Args:
            index: The index.
            actions: Each action line and its document (``None`` for a delete).

        Raises:
            IndexBackendUnavailableError: The cluster refused one of them.
        """
        if not actions:
            return
        lines = []
        for action, document in actions:
            lines.append(json.dumps(action, ensure_ascii=False))
            if document is not None:
                lines.append(json.dumps(document, ensure_ascii=False))
        answer = await self.send(
            "POST",
            f"/{index}/_bulk",
            body="\n".join(lines) + "\n",
            params={"refresh": self.options.refresh},
            ndjson=True,
        )
        if not answer.body.get("errors"):
            return
        for item in answer.body.get("items", []):
            result = next(iter(item.values()), {})
            error = result.get("error")
            if error:
                reason = error_reason(int(result.get("status", 500)), {"error": error})
                raise IndexBackendUnavailableError(self.name, f"bulk: {reason}")

    async def delete_where(self, index: str, query: Json) -> None:
        """Delete the documents matching a query; a missing index has nothing to delete.

        Args:
            index: The index, or a pattern of indexes.
            query: The query.
        """
        await self.send(
            "POST",
            f"/{index}/_delete_by_query",
            body={"query": query},
            params={
                "refresh": "true",
                "conflicts": "proceed",
                "ignore_unavailable": "true",
                "allow_no_indices": "true",
            },
            allow=(HTTPStatus.NOT_FOUND,),
        )

    async def held(self, index: str, library: str | None) -> list[HeldVersion]:
        """List the versions an index holds documents of, and how many, page by page.

        Args:
            index: The index.
            library: Only this library's, if given.

        Returns:
            One per version, by manifest ID; none for a missing index.
        """
        query: Json = {"term": {"library": library}} if library is not None else {"match_all": {}}
        held: list[HeldVersion] = []
        after: Json | None = None
        while True:
            composite: Json = {
                "size": ELASTIC_PAGE,
                "sources": [
                    {"manifest_id": {"terms": {"field": "manifest_id"}}},
                    {"library": {"terms": {"field": "library"}}},
                ],
            }
            if after is not None:
                composite["after"] = after
            answer = await self.send(
                "POST",
                f"/{index}/_search",
                body={"size": 0, "query": query, "aggs": {"held": {"composite": composite}}},
                allow=(HTTPStatus.NOT_FOUND,),
            )
            if answer.status == HTTPStatus.NOT_FOUND:
                return held
            found = answer.body.get("aggregations", {}).get("held", {})
            buckets = found.get("buckets", [])
            held.extend(
                HeldVersion(
                    manifest_id=b["key"]["manifest_id"],
                    library=b["key"]["library"],
                    entries=int(b["doc_count"]),
                )
                for b in buckets
            )
            after = found.get("after_key")
            if len(buckets) < ELASTIC_PAGE or after is None:
                return held

    async def ranked(self, index: str, body: Json) -> list[BackendHit]:
        """Run a BM25 search sorted best first, then by chunk ID and manifest ID.

        Args:
            index: The index.
            body: The search, without its sort.

        Returns:
            The hits; none for a missing index.
        """
        body = {
            **body,
            "_source": False,
            "track_scores": True,
            "sort": [{"_score": "desc"}, {"chunk_id": "asc"}, {"manifest_id": "asc"}],
        }
        answer = await self.send(
            "POST", f"/{index}/_search", body=body, allow=(HTTPStatus.NOT_FOUND,)
        )
        return [
            BackendHit(manifest_id=h["sort"][2], chunk_id=ChunkId(h["sort"][1]), score=h["sort"][0])
            for h in answer.body.get("hits", {}).get("hits", [])
        ]


def _already_exists(body: Json) -> bool:
    """Tell whether an index creation failed only because another writer created it first.

    Args:
        body: The error answer.

    Returns:
        True for ``resource_already_exists_exception``.
    """
    error = body.get("error")
    return isinstance(error, Mapping) and error.get("type") == "resource_already_exists_exception"


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- opened at start
class ElasticSearchBackend:
    """Implements ``ports.driven.SearchBackend`` on an Elasticsearch or OpenSearch index."""

    cluster: _Cluster
    """The connection and options."""

    @property
    def name(self) -> str:
        """The registered name (``elasticsearch`` or ``opensearch``)."""
        return self.cluster.name

    @property
    def index(self) -> str:
        """The search index's name."""
        return f"{self.cluster.options.index_prefix}-search"

    async def open(self) -> None:
        """Connect, check the cluster and create the search index when it is missing."""
        await self.cluster.open()
        await self.cluster.create_index(self.index, None)

    async def close(self) -> None:
        """Close the client."""
        await self.cluster.close()

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries (one document per version and chunk).

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        await self.cluster.bulk(
            self.index,
            [
                ({"index": {"_id": _doc_id(manifest.manifest_id, e.chunk_id)}}, _document(e))
                for e in entries
            ],
        )

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' documents.

        Args:
            manifest_ids: The versions.
        """
        ids = list(dict.fromkeys(manifest_ids))
        for start in range(0, len(ids), ELASTIC_PAGE):
            batch = ids[start : start + ELASTIC_PAGE]
            await self.cluster.delete_where(self.index, {"terms": {"manifest_id": batch}})

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """List the versions held.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self.cluster.held(self.index, library)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' documents by BM25 over the weighted text fields.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or not query.terms or limit < 1:
            return []
        body = {"size": limit, "query": _text_query(manifest_ids, query, tag_filter)}
        return await self.cluster.ranked(self.index, body)

    async def count(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the matching documents of each version.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many documents match, by manifest ID; zeros left out.
        """
        wanted = list(dict.fromkeys(manifest_ids))
        if not wanted or not query.terms:
            return {}
        body = {
            "size": 0,
            "query": _text_query(wanted, query, tag_filter),
            "aggs": {"versions": {"terms": {"field": "manifest_id", "size": len(wanted)}}},
        }
        answer = await self.cluster.send(
            "POST", f"/{self.index}/_search", body=body, allow=(HTTPStatus.NOT_FOUND,)
        )
        buckets = answer.body.get("aggregations", {}).get("versions", {}).get("buckets", [])
        return {b["key"]: int(b["doc_count"]) for b in buckets if b["doc_count"]}


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- opened at start
class ElasticVectorBackend:
    """Implements ``ports.driven.VectorBackend`` and ``NativeHybrid``: one HNSW index per space."""

    cluster: _Cluster
    """The connection and options."""
    native: bool = True
    """Whether the cluster answers the native hybrid query; cleared (and logged) when it refuses
    it, so hybrid fuses the two halves here instead."""
    created: set[EmbeddingSpaceId] = field(default_factory=set)
    """The spaces whose index is known to exist."""

    @property
    def name(self) -> str:
        """The registered name (``elasticsearch`` or ``opensearch``)."""
        return self.cluster.name

    @property
    def pipeline(self) -> str:
        """OpenSearch's normalisation search pipeline for the hybrid query."""
        return f"{self.cluster.options.index_prefix}-hybrid"

    def index(self, space_id: EmbeddingSpaceId) -> str:
        """Name a space's index.

        Args:
            space_id: The space.

        Returns:
            ``<prefix>-vectors-<space ID>``.
        """
        return f"{self.cluster.options.index_prefix}-vectors-{space_id}"

    async def open(self) -> None:
        """Connect and check the cluster; on OpenSearch, create the hybrid search pipeline."""
        await self.cluster.open()
        if self.cluster.flavour != OPENSEARCH_BACKEND:
            return
        weights = list(OPENSEARCH_HYBRID_WEIGHTS)
        body = {
            "description": "ExactDocs hybrid search: BM25 and kNN, normalised and combined",
            "phase_results_processors": [
                {
                    "normalization-processor": {
                        "normalization": {"technique": OPENSEARCH_NORMALIZATION},
                        "combination": {
                            "technique": OPENSEARCH_COMBINATION,
                            "parameters": {"weights": weights},
                        },
                    }
                }
            ],
        }
        answer = await self.cluster.send(
            "PUT",
            f"/_search/pipeline/{self.pipeline}",
            body=body,
            allow=(HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
        )
        if answer.status >= HTTPStatus.BAD_REQUEST:
            self._fuse_here(error_reason(answer.status, answer.body))

    async def close(self) -> None:
        """Close the client."""
        await self.cluster.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries in the space's index, created on its first put.

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        actions = [
            ({"index": {"_id": _doc_id(manifest.manifest_id, e.chunk_id)}}, _document(e))
            for e in entries
            if e.vector is not None
        ]
        if not actions:
            return
        if space.id not in self.created:
            await self.cluster.create_index(self.index(space.id), space.spec.dimensions)
            self.created.add(space.id)
        await self.cluster.bulk(self.index(space.id), actions)

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        ids = list(dict.fromkeys(chunk_ids))
        for start in range(0, len(ids), ELASTIC_PAGE):
            batch = ids[start : start + ELASTIC_PAGE]
            query = {
                "bool": {
                    "filter": [
                        {"term": {"manifest_id": manifest_id}},
                        {"terms": {"chunk_id": batch}},
                    ]
                }
            }
            await self.cluster.delete_where(self.index(space_id), query)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries in every space.

        Args:
            manifest_ids: The versions.
        """
        ids = list(dict.fromkeys(manifest_ids))
        pattern = f"{self.cluster.options.index_prefix}-vectors-*"
        for start in range(0, len(ids), ELASTIC_PAGE):
            batch = ids[start : start + ELASTIC_PAGE]
            await self.cluster.delete_where(pattern, {"terms": {"manifest_id": batch}})

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Delete a space's index.

        Args:
            space_id: The space.
        """
        await self.cluster.send("DELETE", f"/{self.index(space_id)}", allow=(HTTPStatus.NOT_FOUND,))
        self.created.discard(space_id)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the space holds.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self.cluster.held(self.index(space_id), library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Find the versions' nearest entries with a filtered kNN search (HNSW).

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries, nearest first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or limit < 1:
            return []
        k = min(limit, ELASTIC_MAX_CANDIDATES)
        body: Json = {
            "size": k,
            "_source": ["manifest_id", "chunk_id"],
            **self._knn(manifest_ids, query, tag_filter, k),
        }
        answer = await self.cluster.send(
            "POST", f"/{self.index(space.id)}/_search", body=body, allow=(HTTPStatus.NOT_FOUND,)
        )
        hits = [
            BackendNeighbour(
                manifest_id=h["_source"]["manifest_id"],
                chunk_id=ChunkId(h["_source"]["chunk_id"]),
                distance=_distance(float(h["_score"])),
            )
            for h in answer.body.get("hits", {}).get("hits", [])
        ]
        hits.sort(
            key=lambda h: (round(h.distance, ELASTIC_DISTANCE_DECIMALS), h.chunk_id, h.manifest_id)
        )
        return hits

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Rank the versions' entries by BM25 and kNN together, in one native query.

        Elasticsearch fuses them with its RRF retriever, OpenSearch with its hybrid query and
        normalisation pipeline. A cluster that refuses the native query gets both halves asked
        apart and fused here (reciprocal rank fusion).

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms (none: the vector alone ranks).
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The hits, best first.
        """
        if not manifest_ids or limit < 1:
            return []
        if not query.terms:
            near = await self.nearest(space, manifest_ids, vector, tag_filter, limit)
            return [
                BackendHit(manifest_id=h.manifest_id, chunk_id=h.chunk_id, score=1 - h.distance)
                for h in near
            ]
        window = min(max(RRF_DEPTH, limit), ELASTIC_MAX_CANDIDATES)
        if self.native:
            found = await self._native(space, manifest_ids, query, vector, tag_filter, window)
            if found is not None:
                return found[:limit]
        return await self._fused(space, manifest_ids, query, vector, tag_filter, limit, window)

    async def _native(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        window: int,
    ) -> list[BackendHit] | None:
        """Ask the engine's own hybrid query.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's terms.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            window: How many of each half are fused (and returned at most).

        Returns:
            The hits, best first; ``None`` when the cluster refused the query (then it is not
            asked again).
        """
        words = _text_query(manifest_ids, query, tag_filter)
        params: dict[str, str] | None = None
        body: Json
        if self.cluster.flavour == OPENSEARCH_BACKEND:
            knn = self._knn(manifest_ids, vector, tag_filter, window)["query"]
            body = {"size": window, "query": {"hybrid": {"queries": [words, knn]}}}
            params = {"search_pipeline": self.pipeline}
        else:
            knn = self._knn(manifest_ids, vector, tag_filter, window)["knn"]
            body = {
                "size": window,
                "retriever": {
                    "rrf": {
                        "retrievers": [{"standard": {"query": words}}, {"knn": knn}],
                        "rank_window_size": window,
                        "rank_constant": RRF_K,
                    }
                },
            }
        body["_source"] = ["manifest_id", "chunk_id"]
        answer = await self.cluster.send(
            "POST",
            f"/{self.index(space.id)}/_search",
            body=body,
            params=params,
            allow=(HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
        )
        if answer.status == HTTPStatus.NOT_FOUND:
            return []
        if answer.status >= HTTPStatus.BAD_REQUEST:
            self._fuse_here(error_reason(answer.status, answer.body))
            return None
        return [
            BackendHit(
                manifest_id=h["_source"]["manifest_id"],
                chunk_id=ChunkId(h["_source"]["chunk_id"]),
                score=float(h["_score"]),
            )
            for h in answer.body.get("hits", {}).get("hits", [])
        ]

    async def _fused(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
        window: int,
    ) -> list[BackendHit]:
        """Ask the BM25 and kNN halves apart and fuse them with reciprocal rank fusion.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's terms.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.
            window: How many of each half are fused.

        Returns:
            The fused hits, best first.
        """
        body = {"size": window, "query": _text_query(manifest_ids, query, tag_filter)}
        words = await self.cluster.ranked(self.index(space.id), body)
        near = await self.nearest(space, manifest_ids, vector, tag_filter, window)
        fused = fuse_across_manifests(
            [(h.manifest_id, h.chunk_id) for h in words],
            [(h.manifest_id, h.chunk_id) for h in near],
        )
        return [
            BackendHit(manifest_id=f.manifest_id, chunk_id=f.chunk_id, score=f.score)
            for f in fused[:limit]
        ]

    def _knn(
        self, manifest_ids: Sequence[str], vector: Sequence[float], tag_filter: TagFilter, k: int
    ) -> Json:
        """Return the engine's filtered kNN search, as the part of a search body it goes in.

        Args:
            manifest_ids: The versions searched (filtered before ranking).
            vector: The query's vector.
            tag_filter: Which chunks may be returned (filtered before ranking).
            k: How many neighbours.

        Returns:
            ``{"knn": ...}`` (Elasticsearch) or ``{"query": {"knn": ...}}`` (OpenSearch).
        """
        wanted = {"bool": {"filter": _filters(manifest_ids, tag_filter)}}
        values = [float(v) for v in vector]
        if self.cluster.flavour == OPENSEARCH_BACKEND:
            return {"query": {"knn": {"vector": {"vector": values, "k": k, "filter": wanted}}}}
        candidates = min(max(k, self.cluster.options.num_candidates), ELASTIC_MAX_CANDIDATES)
        return {
            "knn": {
                "field": "vector",
                "query_vector": values,
                "k": k,
                "num_candidates": candidates,
                "filter": wanted,
            }
        }

    def _fuse_here(self, reason: str) -> None:
        """Stop asking the native hybrid query, and say why once.

        Args:
            reason: What the cluster answered.
        """
        if self.native:
            logger.warning(
                "The %s cluster refused its native hybrid query (%s): hybrid searches fuse "
                "BM25 and kNN in ExactDocs instead (reciprocal rank fusion).",
                self.cluster.name,
                reason,
            )
        self.native = False


def make_search_backend(
    name: str,
    flavour: Flavour,
    options: ElasticOptions,
    connect: Callable[[ElasticOptions], Engine],
) -> ElasticSearchBackend:
    """Build a search backend (no connection is made until ``open``).

    Args:
        name: The registered name.
        flavour: The engine.
        options: The checked options.
        connect: Builds the engine's client.

    Returns:
        The backend.
    """
    cluster = _Cluster(name=name, flavour=flavour, options=options, connect=connect)
    return ElasticSearchBackend(cluster=cluster)


def make_vector_backend(
    name: str,
    flavour: Flavour,
    options: ElasticOptions,
    connect: Callable[[ElasticOptions], Engine],
) -> ElasticVectorBackend:
    """Build a vector backend (no connection is made until ``open``).

    Args:
        name: The registered name.
        flavour: The engine.
        options: The checked options.
        connect: Builds the engine's client.

    Returns:
        The backend.
    """
    cluster = _Cluster(name=name, flavour=flavour, options=options, connect=connect)
    return ElasticVectorBackend(cluster=cluster)
