"""Azure AI Search as the search and vector backend (#353).

``EXACTDOCS_SEARCH_BACKEND=azure_search`` / ``EXACTDOCS_VECTOR_BACKEND=azure_search``. Every entry
is one document, keyed by its manifest and chunk IDs: in the ``index`` option's index for the
full-text search, and in ``<index>-space<id>`` for an embedding space. Each document carries
``manifest_id``, ``library``, ``version_id``, ``chunk_id`` and ``tags`` as filterable fields, and
the chunk's words as ``identifier_tokens`` (whole identifiers and their parts) in three fields
analysed by whitespace only and weighted by a scoring profile as the database's indexes weigh
them (the section's heading, its ancestors, its text). A space's documents carry the vector too
(``Collection(Edm.Single)``, HNSW, cosine, the embedding model's dimensions).

An index is created when it is missing (the search index when the backend opens, a space's on
its first write); one that exists with another schema (another field type, analyzer or vector
dimensions) is never written to: the error names the index and what differs. Every query
filters on the asked versions' ``manifest_id`` (and the tags) with an OData filter, inside Azure
and before ranking (vectors are pre-filtered), so another version's chunks are never returned.
Azure AI Search indexes in near real time, so every write marks its documents (``write_id``) and
returns once the index counts them all (a delete: once it counts none of them).

With the ``hybrid`` option (on by default) a space's documents carry the words too, and
``hybrid`` is one Azure hybrid query (BM25 and the vector query, fused by Azure with reciprocal
rank fusion). With the ``semantic_configuration`` option too (#473), the backend is a
``NativeRerank`` one: a space's documents also carry their headings and text as plain text
(``title``, ``content``), its index has a semantic configuration of that name over them (added to
an existing index when missing; one of that name over other fields is refused), and a search that
asks for reranking is one hybrid query reranked by Azure's semantic ranker (``semanticQuery``, the
query's text; the BM25 half keeps its escaped full Lucene query). When the ranker cannot rerank
(over capacity), Azure answers in the hybrid order and the hits say they were not reranked.

Requests go through azure-core's ``AsyncioRequestsTransport`` (no aiohttp); the tests inject an
in-process fake of the REST API as the transport. Credentials are an admin API key (from the
environment or a file, never logged: azure-core redacts the ``api-key`` header, and no message
here repeats it) or Entra ID (``DefaultAzureCredential`` or a managed identity, through the sync
``azure-identity`` credentials run in a thread).

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Its client, ``azure-search-documents``, is the ``azure-search`` extra; only this module imports it.
"""

import asyncio
import base64
import functools
import json
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

from azure.core import MatchConditions
from azure.core.credentials import AccessToken, AzureKeyCredential, TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.core.pipeline.transport import AsyncHttpTransport, AsyncioRequestsTransport
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.models import VectorizedQuery

from exactdocs.retrieval.constants import (
    AZURE_SEARCH_ANALYZER,
    AZURE_SEARCH_AUTH,
    AZURE_SEARCH_BACKEND,
    AZURE_SEARCH_BM25,
    AZURE_SEARCH_DEFAULT_INDEX,
    AZURE_SEARCH_DEFAULT_INDEX_TIMEOUT_SECONDS,
    AZURE_SEARCH_DEFAULT_TIMEOUT_SECONDS,
    AZURE_SEARCH_DELIMITERS,
    AZURE_SEARCH_FACETED_FIELDS,
    AZURE_SEARCH_FACETS,
    AZURE_SEARCH_FALSE,
    AZURE_SEARCH_FIELD_ATTRIBUTES,
    AZURE_SEARCH_FILTER_FIELDS,
    AZURE_SEARCH_HNSW,
    AZURE_SEARCH_INDEX_NAME,
    AZURE_SEARCH_KEY_FIELD,
    AZURE_SEARCH_LUCENE_SPECIAL,
    AZURE_SEARCH_OPTIONS,
    AZURE_SEARCH_PAGE,
    AZURE_SEARCH_POLL_SECONDS,
    AZURE_SEARCH_RETRIES,
    AZURE_SEARCH_SCORING_PROFILE,
    AZURE_SEARCH_SEMANTIC_DEPTH,
    AZURE_SEARCH_SEMANTIC_ERRORS,
    AZURE_SEARCH_SEMANTIC_FIELDS,
    AZURE_SEARCH_SEMANTIC_NAME,
    AZURE_SEARCH_SORTED_FIELDS,
    AZURE_SEARCH_SPACE,
    AZURE_SEARCH_TEXT_FIELDS,
    AZURE_SEARCH_TIE_MARGIN,
    AZURE_SEARCH_TRUE,
    AZURE_SEARCH_VECTOR_FIELD,
    AZURE_SEARCH_VECTOR_PROFILE,
    AZURE_SEARCH_VECTOR_SEARCH,
    AZURE_SEARCH_WRITE_BATCH,
    HEADING_WEIGHT,
    PATH_WEIGHT,
    RRF_DEPTH,
    TEXT_WEIGHT,
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
    NativeRanking,
    TagFilter,
    TagMatch,
    TextQuery,
    VectorMetric,
    as_float32,
    identifier_tokens,
)

type Document = dict[str, Any]
type Credential = AzureKeyCredential | AsyncTokenCredential
type Transport = Callable[[], AsyncHttpTransport]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- documents and queries


def _key(manifest_id: str, chunk_id: str) -> str:
    """Return the document key of a chunk of a version.

    Args:
        manifest_id: The version's manifest.
        chunk_id: The chunk.

    Returns:
        URL-safe base64 of both (keys may hold letters, digits, ``_``, ``-`` and ``=`` only).
    """
    return base64.urlsafe_b64encode(f"{manifest_id}\n{chunk_id}".encode()).decode("ascii")


def _text_fields(entry: IndexEntry) -> Document:
    """Return an entry's three word fields: its heading, the headings above, its text.

    Args:
        entry: The entry.

    Returns:
        The fields, each the text's ``identifier_tokens``.
    """
    heading = entry.heading_path[-1] if entry.heading_path else ""
    return dict(
        zip(
            AZURE_SEARCH_TEXT_FIELDS,
            (
                identifier_tokens(heading),
                identifier_tokens(" / ".join(entry.heading_path[:-1])),
                identifier_tokens(entry.content),
            ),
            strict=True,
        )
    )


def _document(entry: IndexEntry, write_id: str, *, words: bool, semantic: bool = False) -> Document:
    """Return the document of an entry, without its vector.

    Args:
        entry: The entry.
        write_id: The mark of the write that puts it.
        words: Whether it carries the words (the search index, a hybrid space).
        semantic: Whether it carries its headings and text as plain text, for the semantic
            ranker (a space with a semantic configuration).

    Returns:
        The document.
    """
    document: Document = {
        AZURE_SEARCH_KEY_FIELD: _key(entry.manifest_id, entry.chunk_id),
        "manifest_id": entry.manifest_id,
        "library": entry.library,
        "version_id": entry.version_id,
        "chunk_id": entry.chunk_id,
        "article_path": entry.article_path,
        "tags": list(entry.tags),
        "write_id": write_id,
    }
    if semantic:
        title, content = AZURE_SEARCH_SEMANTIC_FIELDS
        document |= {title: " / ".join(entry.heading_path), content: entry.content}
    return document | _text_fields(entry) if words else document


def _semantic_configuration(name: str) -> Document:
    """Return ExactDocs' semantic configuration of a space's index (REST shape).

    Args:
        name: The ``semantic_configuration`` option.

    Returns:
        The configuration: the headings as its title field, the text as its content field.
    """
    title, content = AZURE_SEARCH_SEMANTIC_FIELDS
    return {
        "name": name,
        "prioritizedFields": {
            "titleField": {"fieldName": title},
            "prioritizedContentFields": [{"fieldName": content}],
        },
    }


def _semantic_fields() -> list[Document]:
    """Return the plain-text fields the semantic ranker reads (REST shape).

    Returns:
        ``title`` and ``content``: searchable and retrievable strings (what a semantic
        configuration's fields must be), with the default analyzer; never filtered on.
    """
    return [
        {
            "name": name,
            "type": "Edm.String",
            "searchable": True,
            "retrievable": True,
            "filterable": False,
            "sortable": False,
            "facetable": False,
        }
        for name in AZURE_SEARCH_SEMANTIC_FIELDS
    ]


def _definition(name: str, dimensions: int | None, semantic: str | None = None) -> Document:
    """Return the definition of an ExactDocs index (REST shape).

    Args:
        name: The index.
        dimensions: A space's dimensions; ``None`` for the search index (no vector field).
        semantic: A space's semantic configuration (``semantic_configuration``), if any.

    Returns:
        The definition: the key, the filter fields, the words (whitespace analyzer, BM25, the
        scoring profile) and, for a space, the vector field and its HNSW profile (cosine); with
        ``semantic``, the plain-text fields and the semantic configuration over them.
    """
    plain = {"searchable": False, "filterable": False, "sortable": False, "facetable": False}
    fields: list[Document] = [
        {"name": AZURE_SEARCH_KEY_FIELD, "type": "Edm.String", "key": True}
        | plain
        | {"filterable": True},
        *(
            {"name": name, "type": "Edm.String"}
            | plain
            | {
                "filterable": True,
                "sortable": name in AZURE_SEARCH_SORTED_FIELDS,
                "facetable": name in AZURE_SEARCH_FACETED_FIELDS,
            }
            for name in AZURE_SEARCH_FILTER_FIELDS
        ),
        {"name": "article_path", "type": "Edm.String"} | plain,
        {"name": "tags", "type": "Collection(Edm.String)"} | plain | {"filterable": True},
        *(
            {"name": name, "type": "Edm.String"}
            | plain
            | {"searchable": True, "retrievable": False, "analyzer": AZURE_SEARCH_ANALYZER}
            for name in AZURE_SEARCH_TEXT_FIELDS
        ),
    ]
    weights = (HEADING_WEIGHT, PATH_WEIGHT, TEXT_WEIGHT)
    definition: Document = {
        "name": name,
        "fields": fields,
        "similarity": {"@odata.type": AZURE_SEARCH_BM25},
        "scoringProfiles": [
            {
                "name": AZURE_SEARCH_SCORING_PROFILE,
                "text": {"weights": dict(zip(AZURE_SEARCH_TEXT_FIELDS, weights, strict=True))},
            }
        ],
        "defaultScoringProfile": AZURE_SEARCH_SCORING_PROFILE,
    }
    if dimensions is None:
        return definition
    if semantic is not None:
        fields.extend(_semantic_fields())
        definition["semantic"] = {"configurations": [_semantic_configuration(semantic)]}
    fields.append(
        {
            "name": AZURE_SEARCH_VECTOR_FIELD,
            "type": "Collection(Edm.Single)",
            "searchable": True,
            "retrievable": False,
            "stored": False,
            "dimensions": dimensions,
            "vectorSearchProfile": AZURE_SEARCH_VECTOR_PROFILE,
        }
    )
    return definition | {
        "vectorSearch": {
            "algorithms": [
                {"name": AZURE_SEARCH_HNSW, "kind": "hnsw", "hnswParameters": {"metric": "cosine"}}
            ],
            "profiles": [{"name": AZURE_SEARCH_VECTOR_PROFILE, "algorithm": AZURE_SEARCH_HNSW}],
        }
    }


def _field_mismatch(wanted: Document, found: Document | None) -> str | None:
    """Say how an existing field differs from what ExactDocs needs.

    Args:
        wanted: The field ExactDocs defines.
        found: The index's field of that name, if any.

    Returns:
        What differs, or ``None`` when the field serves.
    """
    name = wanted["name"]
    if found is None:
        return f"it has no field {name!r}"
    if found.get("type") != wanted["type"]:
        return f"the field {name!r} is {found.get('type')}, not {wanted['type']}"
    missing = [a for a in AZURE_SEARCH_FIELD_ATTRIBUTES if wanted.get(a) and not found.get(a)]
    if missing:
        return f"the field {name!r} is not {' or '.join(missing)}"
    if wanted.get("analyzer") and found.get("analyzer") != wanted["analyzer"]:
        analyzer = found.get("analyzer")
        return f"the field {name!r} is analysed by {analyzer!r}, not {wanted['analyzer']!r}"
    if wanted.get("dimensions") and found.get("dimensions") != wanted["dimensions"]:
        return (
            f"the field {name!r} holds vectors of {found.get('dimensions')} dimensions, not "
            f"{wanted['dimensions']} (the embedding model's)"
        )
    return None


def _mismatch(wanted: Document, found: Document) -> str | None:
    """Say how an existing index differs from what ExactDocs needs (``None``: it serves).

    Extra fields are fine; a missing or different one, another similarity, a missing scoring
    profile or a vector profile that does not compare by cosine are not.

    Args:
        wanted: ExactDocs' definition.
        found: The index's definition.

    Returns:
        The first difference, or ``None``.
    """
    fields = {f.get("name"): f for f in found.get("fields") or []}
    for spec in wanted["fields"]:
        problem = _field_mismatch(spec, fields.get(spec["name"]))
        if problem:
            return problem
    similarity = (found.get("similarity") or {}).get("@odata.type", AZURE_SEARCH_BM25)
    if similarity != AZURE_SEARCH_BM25:
        return f"it ranks with {similarity}, not BM25"
    profiles = {p.get("name"): p for p in found.get("scoringProfiles") or []}
    weights = ((profiles.get(AZURE_SEARCH_SCORING_PROFILE) or {}).get("text") or {}).get("weights")
    wanted_weights = wanted["scoringProfiles"][0]["text"]["weights"]
    if not weights or {k: float(v) for k, v in weights.items()} != wanted_weights:
        return (
            f"its scoring profile {AZURE_SEARCH_SCORING_PROFILE!r} is missing or weighs otherwise"
        )
    if "vectorSearch" not in wanted:
        return None
    search = found.get("vectorSearch") or {}
    profile = next(
        (p for p in search.get("profiles") or [] if p.get("name") == AZURE_SEARCH_VECTOR_PROFILE),
        {},
    )
    algorithm = next(
        (a for a in search.get("algorithms") or [] if a.get("name") == profile.get("algorithm")),
        {},
    )
    parameters = algorithm.get("hnswParameters") or algorithm.get("exhaustiveKnnParameters") or {}
    if parameters.get("metric", "cosine") != "cosine" or not algorithm:
        return f"its vector profile {AZURE_SEARCH_VECTOR_PROFILE!r} is missing or not cosine"
    return None


def _prioritized(configuration: Document) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    """Return the fields a semantic configuration ranks by.

    Args:
        configuration: The configuration (REST shape).

    Returns:
        Its title field, its content fields and its keyword fields, in their order.
    """
    fields = configuration.get("prioritizedFields") or {}
    title = (fields.get("titleField") or {}).get("fieldName")
    content = tuple(f.get("fieldName") for f in fields.get("prioritizedContentFields") or [])
    keywords = tuple(f.get("fieldName") for f in fields.get("prioritizedKeywordsFields") or [])
    return title, content, keywords


def _semantic_mismatch(name: str, found: Document) -> str | None:
    """Say how an index's semantic parts differ from ExactDocs' (``None``: they serve, or are none).

    Missing parts (the plain-text fields, the configuration) can be added to the index; a field
    of that name of another kind, or a configuration of that name over other fields, cannot.

    Args:
        name: The ``semantic_configuration`` option.
        found: The index's definition.

    Returns:
        The first difference, or ``None``.
    """
    fields = {f.get("name"): f for f in found.get("fields") or []}
    for spec in _semantic_fields():
        existing = fields.get(spec["name"])
        problem = None if existing is None else _field_mismatch(spec, existing)
        if problem:
            return problem
    configurations = (found.get("semantic") or {}).get("configurations") or []
    existing = next((c for c in configurations if c.get("name") == name), None)
    if existing is not None and _prioritized(existing) != _prioritized(
        _semantic_configuration(name)
    ):
        title, content = AZURE_SEARCH_SEMANTIC_FIELDS
        return (
            f"its semantic configuration {name!r} ranks other fields than {title!r} (title) and "
            f"{content!r} (content)"
        )
    return None


def _with_semantic(name: str, found: Document) -> Document | None:
    """Return the index's definition with the missing semantic parts added.

    Args:
        name: The ``semantic_configuration`` option.
        found: The index's definition, which ``_semantic_mismatch`` accepted.

    Returns:
        The definition to update the index with (its etag kept, so a concurrent change is not
        overwritten), or ``None`` when nothing is missing.
    """
    names = {f.get("name") for f in found.get("fields") or []}
    missing = [spec for spec in _semantic_fields() if spec["name"] not in names]
    semantic = dict(found.get("semantic") or {})
    configurations = list(semantic.get("configurations") or [])
    has_configuration = any(c.get("name") == name for c in configurations)
    if not missing and has_configuration:
        return None
    if not has_configuration:
        configurations.append(_semantic_configuration(name))
    semantic["configurations"] = configurations
    kept = {k: v for k, v in found.items() if not k.startswith("@odata.") or k == "@odata.etag"}
    return kept | {"fields": [*(found.get("fields") or []), *missing], "semantic": semantic}


def _literal(value: str) -> str:
    """Quote a string for an OData filter.

    Args:
        value: The string.

    Returns:
        The literal (single quotes doubled inside).
    """
    return "'" + value.replace("'", "''") + "'"


def _any_of(field_name: str, values: Collection[str]) -> str:
    """Return an OData clause matching any of these values (``search.in``, or ``eq`` clauses).

    Args:
        field_name: The field, or a lambda's variable.
        values: The values; at least one.

    Returns:
        The clause.
    """
    distinct = list(dict.fromkeys(values))
    for delimiter in AZURE_SEARCH_DELIMITERS:
        if not any(delimiter in v for v in distinct):
            joined = _literal(delimiter.join(distinct))
            return f"search.in({field_name}, {joined}, {_literal(delimiter)})"
    return "(" + " or ".join(f"{field_name} eq {_literal(v)}" for v in distinct) + ")"


def _filter(manifest_ids: Collection[str], tag_filter: TagFilter) -> str:
    """Return the OData filter of a query: these versions, and the tags.

    Args:
        manifest_ids: The versions; at least one.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The filter.
    """
    clauses = [_any_of("manifest_id", manifest_ids)]
    if tag_filter.tags and tag_filter.match is TagMatch.ALL:
        clauses += [f"tags/any(t: t eq {_literal(tag)})" for tag in tag_filter.tags]
    elif tag_filter.tags:
        clauses.append(f"tags/any(t: {_any_of('t', tag_filter.tags)})")
    return " and ".join(clauses)


def _lucene(terms: Sequence[str]) -> str | None:
    """Return the full Lucene query matching any of the terms, each escaped: never syntax.

    Args:
        terms: The query's terms (``search_terms``: lower case, so ``AND`` is never an operator).

    Returns:
        The terms, escaped and separated by spaces; ``None`` when there are none.
    """
    escaped = [
        "".join(f"\\{c}" if c in AZURE_SEARCH_LUCENE_SPECIAL else c for c in term) for term in terms
    ]
    return " ".join(escaped) or None


@dataclass(frozen=True, slots=True, kw_only=True)
class _Query:
    """One search request, as the backends ask it of an index."""

    where: str | None = None
    """The OData filter."""
    terms: Sequence[str] = ()
    """The words matched (any of them, in the word fields, weighted); none: no full-text part."""
    vectors: Sequence[VectorizedQuery] = ()
    """The vector query, if any (with words too: Azure's hybrid query)."""
    order_by: Sequence[str] = ()
    """The ``$orderby`` clauses; none: by score."""
    select: Sequence[str] = ("manifest_id", "chunk_id")
    """The fields returned."""
    top: int = 0
    """The most results returned."""
    facets: Sequence[str] = ()
    """The facet expressions."""
    total: bool = False
    """Whether to count every match (``$count``)."""
    semantic: str | None = None
    """The semantic configuration that reranks the results, if any (``semanticConfiguration``)."""
    semantic_query: str | None = None
    """The plain text the semantic ranker reads (``semanticQuery``); with ``semantic``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _Answer:
    """What a search returned."""

    rows: list[Document]
    """The results."""
    facets: Mapping[str, list[Document]]
    """The facets' values and counts, by field."""
    count: int
    """Every match, when ``total`` was asked; else 0."""


def _hits(rows: Sequence[Document], limit: int) -> list[BackendHit]:
    """Turn search results into hits, best first, ties by chunk ID then manifest ID.

    Args:
        rows: The results (``manifest_id``, ``chunk_id``, ``@search.score``).
        limit: The most hits.

    Returns:
        The hits.
    """
    hits = [
        BackendHit(
            manifest_id=str(row["manifest_id"]),
            chunk_id=ChunkId(str(row["chunk_id"])),
            score=float(row["@search.score"]),
        )
        for row in rows
    ]
    hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
    return hits[:limit]


def _reranked(rows: Sequence[Document], limit: int) -> NativeRanking:
    """Turn the results of a semantically reranked query into hits.

    Args:
        rows: The results; those the semantic ranker scored carry ``@search.reranker_score``
            (none of them when it could not rerank: Azure's partial answer).
        limit: The most hits.

    Returns:
        The reranked hits first, by the ranker's score (0 to 4), then the others in the hybrid
        order (Azure reranks the best ``AZURE_SEARCH_SEMANTIC_DEPTH`` only); ties by chunk ID,
        then manifest ID. ``reranked`` counts the ranker's hits kept.
    """
    head = [
        BackendHit(
            manifest_id=str(row["manifest_id"]),
            chunk_id=ChunkId(str(row["chunk_id"])),
            score=float(row["@search.reranker_score"]),
        )
        for row in rows
        if row.get("@search.reranker_score") is not None
    ]
    head.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
    rest = [row for row in rows if row.get("@search.reranker_score") is None]
    hits = [*head, *_hits(rest, len(rest))][:limit]
    return NativeRanking(hits=tuple(hits), reranked=min(len(head), len(hits)))


# ---------------------------------------------------------------- errors


def _short(text: str, hidden: Collection[str]) -> str:
    """Return a message on one line, cut at 200 characters, without any secret.

    Args:
        text: The message.
        hidden: The secrets (the API key) never to repeat.

    Returns:
        The message.
    """
    line = " ".join(text.split())
    for secret in hidden:
        line = line.replace(secret, "***")
    return line[:200]


def _server_message(error: HttpResponseError) -> str:
    """Return what the service said about a refused request.

    Args:
        error: The error.

    Returns:
        The service's own message when it gave one, else the HTTP reason.
    """
    response = error.response
    try:
        body = json.loads(response.text()) if response is not None else {}
    except ValueError, TypeError:
        body = {}
    message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
    return str(message or error.reason or type(error).__name__)


def _reason(error: AzureError, hidden: Collection[str]) -> str:
    """Say briefly why Azure AI Search did not answer, never with a credential.

    Args:
        error: What the client raised.
        hidden: The secrets never to repeat.

    Returns:
        The kind of failure, with the service's own message for a refused request.
    """
    status = getattr(error, "status_code", None)
    if status in {401, 403}:
        return (
            f"authentication failed (HTTP {status}): check the API key, or the Entra ID "
            "identity's roles on the service (Search Service Contributor and Search Index Data "
            "Contributor)"
        )
    if isinstance(error, ClientAuthenticationError):
        return f"no Entra ID token ({_short(str(error), hidden)})"
    if isinstance(error, HttpResponseError) and status is not None:
        return f"HTTP {status}: {_short(_server_message(error), hidden)}"
    if isinstance(error, ServiceResponseError):
        return f"the answer was cut or timed out ({type(error).__name__})"
    if isinstance(error, ServiceRequestError):
        return f"no answer ({_short(str(error), hidden)})"
    return f"{type(error).__name__}: {_short(str(error), hidden)}"


# ---------------------------------------------------------------- credentials


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- wraps one credential
class _ThreadedCredential:
    """An async Entra ID credential over a sync one (``azure.identity.aio`` would need aiohttp).

    A token is asked for about once an hour (the credentials cache it), in a worker thread.
    """

    credential: TokenCredential
    """The sync credential (``DefaultAzureCredential``, ``ManagedIdentityCredential``)."""

    async def get_token(
        self,
        *scopes: str,
        claims: str | None = None,
        tenant_id: str | None = None,
        enable_cae: bool = False,
        **kwargs: object,
    ) -> AccessToken:
        """Ask the sync credential for a token, in a thread.

        Args:
            *scopes: The scopes.
            claims: Extra claims, from a claims challenge.
            tenant_id: The tenant, if not the credential's.
            enable_cae: Whether to ask for a continuous access evaluation token.
            **kwargs: Passed on.

        Returns:
            The token.
        """
        ask = functools.partial(
            self.credential.get_token,
            *scopes,
            claims=claims,
            tenant_id=tenant_id,
            enable_cae=enable_cae,
            **kwargs,
        )
        return await asyncio.to_thread(ask)

    async def close(self) -> None:
        """Release the credential's own HTTP session."""
        close = getattr(self.credential, "close", None)
        if close is not None:
            await asyncio.to_thread(close)

    async def __aenter__(self) -> Self:
        """Enter: nothing to open.

        Returns:
            The credential.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """Release the credential.

        Args:
            exc_type: The exception's type, if one is leaving the block.
            exc_value: The exception.
            traceback: Its traceback.
        """
        await self.close()


# ---------------------------------------------------------------- the service


@dataclass(frozen=True, slots=True, kw_only=True)
class _Connection:
    """How to reach the service: what both backends are built from."""

    endpoint: str
    """``https://<service>.search.windows.net``."""
    credential: Callable[[], Credential] = field(repr=False)
    """Makes the credential (a key, or an Entra ID one), at ``open``."""
    transport: Transport = field(repr=False)
    """Makes the HTTP transport, at ``open`` (tests: the in-process fake)."""
    index: str
    """The ``index`` option: the search index, and the spaces' indexes' prefix."""
    index_timeout: float
    """The ``index_timeout`` option, in seconds."""
    audience: str | None = None
    """The Entra ID audience, for a sovereign cloud; ``None``: the public cloud."""
    hidden: tuple[str, ...] = field(default=(), repr=False)
    """The secrets (the API key) no message ever repeats; never in the ``repr``."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its clients
class _Service:
    """The clients of one backend and what both backends do with them."""

    connection: _Connection
    """How to reach the service."""
    name: str = AZURE_SEARCH_BACKEND
    """The registered name, for messages."""
    _indexes: SearchIndexClient | None = field(default=None, init=False)
    """The index client, from ``open`` to ``close``."""
    _credential: Credential | None = field(default=None, init=False, repr=False)
    """The credential, from ``open`` to ``close``."""
    _transport: AsyncHttpTransport | None = field(default=None, init=False, repr=False)
    """The HTTP transport every client shares."""
    _clients: dict[str, SearchClient] = field(default_factory=dict, init=False)
    """One document client per index used."""
    _ready: set[str] = field(default_factory=set, init=False)
    """The indexes this process made sure exist with ExactDocs' schema."""

    def open(self) -> None:
        """Make the credential, the transport and the index client (no request yet)."""
        connection = self.connection
        self._credential = connection.credential()
        self._transport = connection.transport()
        self._indexes = SearchIndexClient(
            connection.endpoint, self._credential, **self._client_options()
        )

    async def close(self) -> None:
        """Release the clients, the credential and the transport."""
        clients = [*self._clients.values(), *([self._indexes] if self._indexes else [])]
        self._clients.clear()
        self._ready.clear()
        self._indexes = None
        for client in clients:
            await client.close()
        credential, self._credential = self._credential, None
        if isinstance(credential, _ThreadedCredential):
            await credential.close()
        transport, self._transport = self._transport, None
        if transport is not None:
            await transport.__aexit__(None, None, None)  # its close is sync on some transports

    def _client_options(self) -> Document:
        """Return the keywords every client is made with.

        Returns:
            The shared transport, the retries, and the audience when one is set.
        """
        options: Document = {"transport": self._transport, "retry_total": AZURE_SEARCH_RETRIES}
        if self.connection.audience:
            options["audience"] = self.connection.audience
        return options

    @property
    def indexes(self) -> SearchIndexClient:
        """The index client.

        Raises:
            IndexBackendUnavailableError: The backend was not opened.
        """
        if self._indexes is None:
            raise IndexBackendUnavailableError(self.name, "not opened")
        return self._indexes

    def documents(self, index: str) -> SearchClient:
        """Return the document client of an index.

        Args:
            index: The index.

        Returns:
            Its client, made on first use.

        Raises:
            IndexBackendUnavailableError: The backend was not opened.
        """
        if self._credential is None:
            raise IndexBackendUnavailableError(self.name, "not opened")
        client = self._clients.get(index)
        if client is None:
            client = SearchClient(
                endpoint=self.connection.endpoint,
                index_name=index,
                credential=self._credential,
                **self._client_options(),
            )
            self._clients[index] = client
        return client

    async def call[T](self, call: Awaitable[T]) -> T:
        """Await a client call, turning its failures into the port's error.

        Args:
            call: The call.

        Returns:
            Its result.

        Raises:
            IndexBackendUnavailableError: The service did not answer or refused it.
        """
        try:
            return await call
        except AzureError as error:
            reason = _reason(error, self.connection.hidden)
            raise IndexBackendUnavailableError(self.name, reason) from error

    async def ensure(self, index: str, dimensions: int | None, semantic: str | None = None) -> None:
        """Create the index when it is missing; refuse one with another schema.

        With ``semantic``, an existing index without the semantic configuration (or its
        plain-text fields) gets them added in place: Azure adds fields and semantic
        configurations without a rebuild, but the documents written before carry no plain text
        until ``exactdocs index rebuild`` writes them again (a warning says so).

        Args:
            index: The index.
            dimensions: A space's dimensions; ``None`` for the search index.
            semantic: A space's semantic configuration (``semantic_configuration``), if any.

        Raises:
            IndexBackendUnavailableError: The index exists with another schema (a semantic
                configuration of that name over other fields included), or the service did not
                answer.
        """
        if index in self._ready:
            return
        wanted = _definition(index, dimensions, semantic)
        found = await self._definition_of(index)
        if found is None:
            try:
                await self.indexes.create_index(wanted)
            except ResourceExistsError:  # made meanwhile by another process: check it
                found = await self._definition_of(index)
            except AzureError as error:
                reason = _reason(error, self.connection.hidden)
                raise IndexBackendUnavailableError(self.name, reason) from error
        problem = None if found is None else _mismatch(_definition(index, dimensions), found)
        if found is not None and semantic is not None:
            problem = problem or _semantic_mismatch(semantic, found)
        if problem:
            message = (
                f"the index {index!r} does not have ExactDocs' schema ({problem}): delete it, "
                "or set another index, then run `exactdocs index rebuild`"
            )
            raise IndexBackendUnavailableError(self.name, message)
        if found is not None and semantic is not None:
            await self._add_semantic(index, semantic, found)
        self._ready.add(index)

    async def _add_semantic(self, index: str, semantic: str, found: Document) -> None:
        """Add the semantic configuration and its fields to an existing index that lacks them.

        Args:
            index: The index.
            semantic: The ``semantic_configuration`` option.
            found: The index's definition, which serves otherwise.
        """
        updated = _with_semantic(semantic, found)
        if updated is None:
            return
        await self.call(
            self.indexes.create_or_update_index(
                updated, match_condition=MatchConditions.IfNotModified
            )
        )
        logger.warning(
            "%s: added the semantic configuration %r to the index %r; run `exactdocs index "
            "rebuild` so the documents written before carry the text the semantic ranker reads",
            self.name,
            semantic,
            index,
        )

    async def _definition_of(self, index: str) -> Document | None:
        """Read an index's definition.

        Args:
            index: The index.

        Returns:
            Its definition (REST shape), or ``None`` when there is no such index.
        """

        async def get() -> Document | None:
            """Ask for it.

            Returns:
                The definition, or ``None``.
            """
            try:
                return (await self.indexes.get_index(index)).as_dict()
            except ResourceNotFoundError:
                return None

        return await self.call(get())

    async def drop(self, index: str) -> None:
        """Delete an index; a no-op when there is none.

        Args:
            index: The index.
        """
        self._ready.discard(index)  # its client stays: closing one closes the shared transport
        await self.call(self.indexes.delete_index(index))

    async def index_names(self) -> list[str]:
        """Return the names of every index of the service.

        Returns:
            The names.
        """

        async def names() -> list[str]:
            """List them.

            Returns:
                The names.
            """
            return [name async for name in self.indexes.list_index_names()]

        return await self.call(names())

    async def search(self, index: str, query: _Query) -> _Answer:
        """Run a search on an index.

        Args:
            index: The index.
            query: The request.

        Returns:
            The results, facets and count; nothing when there is no such index.
        """
        words = _lucene(query.terms)

        async def run() -> _Answer:
            """Search and read every result.

            Returns:
                What the search returned.
            """
            try:
                results = await self.documents(index).search(
                    search_text=words,
                    query_type="full" if words else None,
                    search_mode="any" if words else None,
                    search_fields=list(AZURE_SEARCH_TEXT_FIELDS) if words else None,
                    scoring_profile=AZURE_SEARCH_SCORING_PROFILE if words else None,
                    # The same entry in two versions scores the same, wherever its shard is.
                    scoring_statistics="global" if words else None,
                    filter=query.where,
                    vector_queries=list(query.vectors) or None,
                    vector_filter_mode="preFilter" if query.vectors else None,
                    order_by=list(query.order_by) or None,
                    select=list(query.select),
                    top=query.top,
                    facets=list(query.facets) or None,
                    include_total_count=query.total or None,
                    # The ranker reads the query's plain text; the words above stay full Lucene.
                    semantic_configuration_name=query.semantic,
                    semantic_query=query.semantic_query if query.semantic else None,
                    semantic_error_mode=AZURE_SEARCH_SEMANTIC_ERRORS if query.semantic else None,
                )
                rows = [dict(row) async for row in results]
                facets = await results.get_facets() if query.facets else None
                count = await results.get_count() if query.total else None
            except ResourceNotFoundError:
                return _Answer(rows=[], facets={}, count=0)
            return _Answer(rows=rows, facets=dict(facets or {}), count=int(count or 0))

        return await self.call(run())

    async def count(self, index: str, where: str) -> int:
        """Count an index's documents that pass a filter.

        Args:
            index: The index.
            where: The OData filter.

        Returns:
            How many; 0 when there is no such index.
        """
        return (await self.search(index, _Query(where=where, total=True))).count

    async def facets(self, index: str, facet: str, query: _Query) -> list[tuple[str, int]]:
        """Count the matching documents of an index by the values of a field.

        Args:
            index: The index.
            facet: The facet expression (``<field>,count:<n>``).
            query: The search (the filter, the words).

        Returns:
            Each value and its count; zeros left out.
        """
        answer = await self.search(index, replace(query, facets=(facet,), top=0))
        values = answer.facets.get(facet.partition(",")[0]) or []
        return [(str(v["value"]), int(v["count"])) for v in values if v.get("count")]

    async def held(self, index: str, library: str | None) -> list[HeldVersion]:
        """List the versions an index holds, and how many entries each.

        Args:
            index: The index.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID.
        """
        if library is None:
            counted = await self.facets(index, f"library,count:{AZURE_SEARCH_FACETS}", _Query())
            libraries = [name for name, _ in counted]
        else:
            libraries = [library]
        held = [
            HeldVersion(manifest_id=manifest_id, library=name, entries=entries)
            for name in libraries
            for manifest_id, entries in await self.facets(
                index,
                f"manifest_id,count:{AZURE_SEARCH_FACETS}",
                _Query(where=f"library eq {_literal(name)}"),
            )
        ]
        return sorted(held, key=lambda h: h.manifest_id)

    async def until(self, done: Callable[[], Awaitable[bool]], what: str) -> None:
        """Wait until ``done`` says so, looking less and less often, up to ``index_timeout``.

        Args:
            done: Tells whether the wait is over.
            what: What is waited for, for the error.

        Raises:
            IndexBackendUnavailableError: It did not happen in time.
        """
        deadline = time.monotonic() + self.connection.index_timeout
        pause, longest = AZURE_SEARCH_POLL_SECONDS
        while not await done():
            if time.monotonic() >= deadline:
                timeout = self.connection.index_timeout
                message = f"{what} did not catch up within {timeout:g} s"
                raise IndexBackendUnavailableError(self.name, message)
            await asyncio.sleep(pause)
            pause = min(pause * 2, longest)

    async def write(self, index: str, documents: Sequence[Document], write_id: str) -> None:
        """Add or replace documents (by key), then wait until the index counts them all.

        Args:
            index: The index.
            documents: The documents, each marked with ``write_id``.
            write_id: Their mark.

        Raises:
            IndexBackendUnavailableError: The service refused some, or did not answer.
        """
        client = self.documents(index)
        for start in range(0, len(documents), AZURE_SEARCH_WRITE_BATCH):
            batch = list(documents[start : start + AZURE_SEARCH_WRITE_BATCH])
            try:
                results = await self.call(client.upload_documents(batch))
            except IndexBackendUnavailableError as error:
                if isinstance(error.__cause__, ResourceNotFoundError):
                    self._ready.discard(index)  # dropped behind ExactDocs' back: made again
                raise
            failed = [r for r in results if not r.succeeded]
            if failed:
                first = failed[0]
                message = (
                    f"{len(failed)} of {len(batch)} documents were refused (HTTP "
                    f"{first.status_code}: {_short(first.error_message or '', ())})"
                )
                raise IndexBackendUnavailableError(self.name, message)
        marked = f"write_id eq {_literal(write_id)}"

        async def counted() -> bool:
            """Tell whether the index counts every document written.

            Returns:
                True when it does.
            """
            return await self.count(index, marked) >= len(documents)

        await self.until(counted, f"the index {index!r}")

    async def delete_keys(self, index: str, keys: Collection[str]) -> None:
        """Delete documents by key, then wait until the index counts none of them.

        Args:
            index: The index; a missing one has nothing to delete.
            keys: The keys.

        Raises:
            IndexBackendUnavailableError: The service did not delete them.
        """
        keys = list(dict.fromkeys(keys))
        for start in range(0, len(keys), AZURE_SEARCH_PAGE):
            batch = keys[start : start + AZURE_SEARCH_PAGE]
            try:
                await self.call(
                    self.documents(index).delete_documents(
                        [{AZURE_SEARCH_KEY_FIELD: key} for key in batch]
                    )
                )
            except IndexBackendUnavailableError as error:
                if isinstance(error.__cause__, ResourceNotFoundError):
                    return
                raise
            gone = _any_of(AZURE_SEARCH_KEY_FIELD, batch)

            async def deleted(gone: str = gone) -> bool:
                """Tell whether the index counts none of them.

                Args:
                    gone: The filter of the deleted keys.

                Returns:
                    True when it counts none.
                """
                return await self.count(index, gone) == 0

            await self.until(deleted, f"the index {index!r}")

    async def delete_where(self, index: str, where: str) -> None:
        """Delete every document of an index that passes a filter, a page of keys at a time.

        Args:
            index: The index; a missing one has nothing to delete.
            where: The OData filter.
        """
        while True:
            page = _Query(where=where, select=(AZURE_SEARCH_KEY_FIELD,), top=AZURE_SEARCH_PAGE)
            rows = (await self.search(index, page)).rows
            if not rows:
                return
            await self.delete_keys(index, [str(row[AZURE_SEARCH_KEY_FIELD]) for row in rows])


# ---------------------------------------------------------------- the backends


@dataclass(frozen=True, slots=True, kw_only=True)
class AzureSearchBackend:
    """Implements ``ports.driven.SearchBackend`` on Azure AI Search (BM25 on the words)."""

    service: _Service
    """The clients."""

    @property
    def name(self) -> str:
        """The registered name (``azure_search``)."""
        return self.service.name

    @property
    def index(self) -> str:
        """The search index."""
        return self.service.connection.index

    async def open(self) -> None:
        """Connect, and create the search index when missing (or refuse another schema).

        ``IndexBackendUnavailableError`` when the service does not answer or refuses the
        credentials, or the index has another schema.
        """
        self.service.open()
        await self.service.ensure(self.index, None)

    async def close(self) -> None:
        """Release the clients."""
        await self.service.close()

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries' documents; returns once the index counts them.

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        del manifest  # every entry names its manifest
        if not entries:
            return
        await self.service.ensure(self.index, None)
        write_id = secrets.token_hex(8)
        documents = {
            (e.manifest_id, e.chunk_id): _document(e, write_id, words=True) for e in entries
        }
        await self.service.write(self.index, list(documents.values()), write_id)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every document of these versions.

        Args:
            manifest_ids: The versions.
        """
        if manifest_ids:
            await self.service.delete_where(self.index, _any_of("manifest_id", manifest_ids))

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the index holds, by facets on ``library`` and ``manifest_id``.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self.service.held(self.index, library)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' documents with BM25 on the weighted words.

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
        answer = await self.service.search(
            self.index,
            _Query(
                where=_filter(manifest_ids, tag_filter),
                terms=query.terms,
                order_by=("search.score() desc", "chunk_id asc", "manifest_id asc"),
                top=limit,
            ),
        )
        return _hits(answer.rows, limit)

    async def count(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the matching documents of each version (a facet on ``manifest_id``).

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many match, by manifest ID; zeros left out.
        """
        if not manifest_ids or not query.terms:
            return {}
        counted = await self.service.facets(
            self.index,
            # As many values as versions asked: every shard returns all of them, so exact counts.
            f"manifest_id,count:{len(set(manifest_ids))}",
            _Query(where=_filter(manifest_ids, tag_filter), terms=query.terms),
        )
        return dict(counted)


@dataclass(frozen=True, slots=True, kw_only=True)
class AzureVectorBackend:
    """Implements ``ports.driven.VectorBackend`` on Azure AI Search: an index per space."""

    service: _Service
    """The clients."""
    words: bool = False
    """Whether the documents carry the words too (``hybrid``)."""
    exact: bool = False
    """``vector_search = "exact"``: every vector of the asked versions, not HNSW."""
    semantic: str | None = None
    """``semantic_configuration`` (#473): the documents also carry their headings and text as
    plain text, and the spaces' indexes this semantic configuration over them."""

    @property
    def name(self) -> str:
        """The registered name (``azure_search``)."""
        return self.service.name

    def space_index(self, space_id: EmbeddingSpaceId) -> str:
        """Return the index of a space.

        Args:
            space_id: The space.

        Returns:
            ``<index>-space<id>``.
        """
        return f"{self.service.connection.index}{AZURE_SEARCH_SPACE}{int(space_id)}"

    async def open(self) -> None:
        """Connect and check the service answers (it lists its indexes).

        ``IndexBackendUnavailableError`` when the service does not answer or refuses the
        credentials.
        """
        self.service.open()
        await self.service.index_names()

    async def close(self) -> None:
        """Release the clients."""
        await self.service.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' documents in the space's index; made when missing.

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.

        Raises:
            IndexBackendUnavailableError: The space's metric is not cosine, its index has another
                schema (other dimensions), or the service did not take the entries.
        """
        del manifest  # every entry names its manifest
        if space.spec.metric is not VectorMetric.COSINE:
            message = f"the {space.spec.metric} metric is not supported (cosine only)"
            raise IndexBackendUnavailableError(self.name, message)
        with_vectors = [e for e in entries if e.vector is not None]
        if not with_vectors:
            return
        index = self.space_index(space.id)
        await self.service.ensure(index, space.spec.dimensions, self.semantic)
        write_id = secrets.token_hex(8)
        semantic = self.semantic is not None
        documents = {
            (e.manifest_id, e.chunk_id): _document(e, write_id, words=self.words, semantic=semantic)
            | {AZURE_SEARCH_VECTOR_FIELD: list(as_float32(e.vector or ()))}
            for e in with_vectors
        }
        await self.service.write(index, list(documents.values()), write_id)

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        if chunk_ids:
            keys = [_key(manifest_id, chunk_id) for chunk_id in chunk_ids]
            await self.service.delete_keys(self.space_index(space_id), keys)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' documents in every space's index.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        where = _any_of("manifest_id", manifest_ids)
        for index in await self._spaces():
            await self.service.delete_where(index, where)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Delete a space's index; a no-op for an unknown space.

        Args:
            space_id: The space.
        """
        await self.service.drop(self.space_index(space_id))

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the space's index holds.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held; empty for an unknown space.
        """
        return await self.service.held(self.space_index(space_id), library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Find the versions' nearest vectors, pre-filtered to them and the tags.

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
        wanted = limit + AZURE_SEARCH_TIE_MARGIN
        answer = await self.service.search(
            self.space_index(space.id),
            _Query(
                where=_filter(manifest_ids, tag_filter),
                vectors=(self._vector_query(query, wanted),),
                top=wanted,
            ),
        )
        rows = answer.rows
        # Azure scores cosine as 1 / (1 + distance).
        hits = [
            BackendNeighbour(
                manifest_id=str(row["manifest_id"]),
                chunk_id=ChunkId(str(row["chunk_id"])),
                distance=max(0.0, 1.0 / float(row["@search.score"]) - 1.0),
            )
            for row in rows
            if float(row["@search.score"]) > 0
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits[:limit]

    async def hybrid_search(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Rank the versions' documents with one Azure hybrid query (RRF of BM25 and vectors).

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms (none: the vector query alone).
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The hits, best first (Azure's fused score).
        """
        if not manifest_ids or limit < 1:
            return []
        wanted = limit + AZURE_SEARCH_TIE_MARGIN
        answer = await self.service.search(
            self.space_index(space.id),
            _Query(
                where=_filter(manifest_ids, tag_filter),
                terms=query.terms,
                vectors=(self._vector_query(vector, max(wanted, RRF_DEPTH)),),
                top=wanted,
            ),
        )
        return _hits(answer.rows, limit)

    async def semantic_search(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> NativeRanking:
        """Rank with one Azure hybrid query reranked by the semantic ranker (``semantic``).

        The words and the vector are asked as ``hybrid_search`` asks them (the same filter,
        before ranking), with ``semanticConfiguration`` and the query's text as
        ``semanticQuery``; at least ``AZURE_SEARCH_SEMANTIC_DEPTH`` results are asked, so the
        cut at ``limit`` comes after the reranking.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms; the ranker reads its text.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The hits, the reranked ones first; without a semantic configuration or a query
            text, the hybrid query's, none reranked.
        """
        text = " ".join(query.text.split())
        if self.semantic is None or not text:
            hits = await self.hybrid_search(space, manifest_ids, query, vector, tag_filter, limit)
            return NativeRanking(hits=tuple(hits), reranked=0)
        if not manifest_ids or limit < 1:
            return NativeRanking(hits=(), reranked=0)
        wanted = max(limit + AZURE_SEARCH_TIE_MARGIN, AZURE_SEARCH_SEMANTIC_DEPTH)
        answer = await self.service.search(
            self.space_index(space.id),
            _Query(
                where=_filter(manifest_ids, tag_filter),
                terms=query.terms,
                vectors=(self._vector_query(vector, max(wanted, RRF_DEPTH)),),
                top=wanted,
                semantic=self.semantic,
                semantic_query=text,
            ),
        )
        return _reranked(answer.rows, limit)

    def _vector_query(self, vector: Sequence[float], k: int) -> VectorizedQuery:
        """Return the vector query of a search.

        Args:
            vector: The query's vector.
            k: How many neighbours.

        Returns:
            The query: approximate (HNSW) or exhaustive, as ``vector_search`` says.
        """
        return VectorizedQuery(
            vector=list(as_float32(vector)),
            k_nearest_neighbors=k,
            fields=AZURE_SEARCH_VECTOR_FIELD,
            exhaustive=self.exact,
        )

    async def _spaces(self) -> list[str]:
        """Return the spaces' indexes of this ``index`` option.

        Returns:
            Their names.
        """
        pattern = re.compile(re.escape(self.service.connection.index + AZURE_SEARCH_SPACE) + r"\d+")
        return sorted(n for n in await self.service.index_names() if pattern.fullmatch(n))


@dataclass(frozen=True, slots=True, kw_only=True)
class AzureHybridVectorBackend:
    """``AzureVectorBackend`` with ``NativeHybrid``: its spaces' documents carry the words."""

    vectors: AzureVectorBackend
    """The vector backend (``words`` on)."""

    @property
    def name(self) -> str:
        """The registered name (``azure_search``)."""
        return self.vectors.name

    async def open(self) -> None:
        """Connect and check the service answers."""
        await self.vectors.open()

    async def close(self) -> None:
        """Release the clients."""
        await self.vectors.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' documents, words included.

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        await self.vectors.put(space, manifest, entries)

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        await self.vectors.remove(space_id, manifest_id, chunk_ids)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' documents in every space.

        Args:
            manifest_ids: The versions.
        """
        await self.vectors.delete(manifest_ids)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Delete a space's index.

        Args:
            space_id: The space.
        """
        await self.vectors.drop_space(space_id)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the space's index holds.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self.vectors.held(space_id, library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Find the versions' nearest vectors.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries, nearest first.
        """
        return await self.vectors.nearest(space, manifest_ids, query, tag_filter, limit)

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Rank the versions' documents with one Azure hybrid query.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The hits, best first.
        """
        return await self.vectors.hybrid_search(
            space, manifest_ids, query, vector, tag_filter, limit
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AzureSemanticVectorBackend(AzureHybridVectorBackend):
    """``AzureHybridVectorBackend`` with ``NativeRerank``: Azure's semantic ranker reranks (#473).

    Built when ``semantic_configuration`` names a semantic configuration (``vectors.semantic``).
    """

    async def hybrid_reranked(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> NativeRanking:
        """Rank with one Azure hybrid query reranked by the semantic ranker.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The hits, the reranked ones first, and how many were reranked.
        """
        return await self.vectors.semantic_search(
            space, manifest_ids, query, vector, tag_filter, limit
        )


# ---------------------------------------------------------------- options


def _switch(options: Mapping[str, object], name: str, *, default: bool) -> bool:
    """Read an on/off option (TOML booleans, or text from the environment).

    Args:
        options: The options.
        name: The option.
        default: Its value when unset.

    Returns:
        Its value.

    Raises:
        ValueError: It is neither.
    """
    value = options.get(name, default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in AZURE_SEARCH_TRUE:
        return True
    if text in AZURE_SEARCH_FALSE:
        return False
    message = f"{name} must be true or false (got {value!r})"
    raise ValueError(message)


def _seconds(options: Mapping[str, object], name: str, default: int) -> int:
    """Read a whole number of seconds.

    Args:
        options: The options.
        name: The option.
        default: Its value when unset.

    Returns:
        The seconds.

    Raises:
        ValueError: It is not a positive whole number.
    """
    try:
        seconds = int(str(options.get(name, default)).strip())
    except ValueError:
        seconds = 0
    if seconds < 1:
        message = f"{name} must be a whole number of seconds (got {options.get(name)!r})"
        raise ValueError(message)
    return seconds


def _text(options: Mapping[str, object], name: str) -> str | None:
    """Read a text option, trimmed.

    Args:
        options: The options.
        name: The option.

    Returns:
        The text, or ``None`` when unset or blank.
    """
    return str(options.get(name) or "").strip() or None


def _api_key(options: Mapping[str, object]) -> str | None:
    """Read the API key from ``api_key`` (the environment) or the file ``api_key_file`` names.

    Args:
        options: The options.

    Returns:
        The key, or ``None`` when neither is set.

    Raises:
        ValueError: Both are set, or the file cannot be read or is empty.
    """
    given = _text(options, "api_key")
    path = _text(options, "api_key_file")
    if given and path:
        message = "set api_key or api_key_file, not both"
        raise ValueError(message)
    if path is None:
        return given
    try:
        key = Path(path).expanduser().read_text("utf-8").strip()
    except OSError as error:
        message = f"api_key_file {path!r} cannot be read ({type(error).__name__})"
        raise ValueError(message) from error
    if not key:
        message = f"api_key_file {path!r} is empty"
        raise ValueError(message)
    return key


def _endpoint(options: Mapping[str, object]) -> str:
    """Read the service's endpoint.

    Args:
        options: The options.

    Returns:
        ``https://<host>``, without a trailing slash.

    Raises:
        ValueError: It is missing, not HTTPS, or holds a path, a query or credentials.
    """
    endpoint = (_text(options, "endpoint") or "").rstrip("/")
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        message = "endpoint must be the service's URL, https://<service>.search.windows.net"
        raise ValueError(message)
    if parts.path or parts.query or parts.fragment:
        message = "endpoint must be the service's URL alone (no path or query)"
        raise ValueError(message)
    return endpoint


def _credential(
    options: Mapping[str, object], key: str | None, entra: TokenCredential | None
) -> Callable[[], Credential]:
    """Choose how to authenticate, from ``auth`` (and whether a key is given).

    Args:
        options: The options.
        key: The API key, if one is given.
        entra: A sync Entra ID credential to use instead of the one ``auth`` names (tests).

    Returns:
        What makes the credential at ``open``.

    Raises:
        ValueError: ``auth`` is unknown, or does not match whether a key is given.
    """
    auth = (_text(options, "auth") or ("api_key" if key else "default")).lower()
    if auth not in AZURE_SEARCH_AUTH:
        known = ", ".join(sorted(AZURE_SEARCH_AUTH))
        message = f"auth must be one of {known} (got {auth!r})"
        raise ValueError(message)
    client_id = _text(options, "client_id")
    if auth == "api_key":
        if key is None:
            message = (
                "auth = api_key needs the key: EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__API_KEY, "
                "or api_key_file"
            )
            raise ValueError(message)
        if client_id:
            message = "client_id names a managed identity: set auth = managed_identity or default"
            raise ValueError(message)
        return functools.partial(AzureKeyCredential, key)
    if key is not None:
        message = f"auth = {auth} uses Entra ID: drop api_key / api_key_file, or set auth = api_key"
        raise ValueError(message)
    if entra is not None:
        return functools.partial(_ThreadedCredential, entra)

    def make() -> Credential:
        """Make the Entra ID credential (no token asked for yet).

        Returns:
            The credential.
        """
        if auth == "managed_identity":
            identity = ManagedIdentityCredential(client_id=client_id) if client_id else None
            return _ThreadedCredential(identity or ManagedIdentityCredential())
        chosen = {"managed_identity_client_id": client_id} if client_id else {}
        return _ThreadedCredential(DefaultAzureCredential(**chosen))

    return make


def _connection(
    options: Mapping[str, object],
    transport: Transport | None,
    credential: TokenCredential | None,
) -> _Connection:
    """Check the ``[index_backends.azure_search]`` options.

    Args:
        options: The options.
        transport: Makes the HTTP transport instead of azure-core's requests one (tests).
        credential: A sync Entra ID credential instead of the one ``auth`` names (tests).

    Returns:
        What the backends are built from.

    Raises:
        ValueError: An option is unknown, missing or invalid.
    """
    unknown = sorted(set(options) - AZURE_SEARCH_OPTIONS)
    if unknown:
        known = ", ".join(sorted(AZURE_SEARCH_OPTIONS))
        message = f"unknown options {', '.join(unknown)} (known: {known})"
        raise ValueError(message)
    endpoint = _endpoint(options)
    index = _text(options, "index") or AZURE_SEARCH_DEFAULT_INDEX
    if not AZURE_SEARCH_INDEX_NAME.fullmatch(index):
        message = (
            f"index {index!r} must be 2 to 100 lower-case letters, digits and single dashes, "
            "starting and ending with a letter or digit"
        )
        raise ValueError(message)
    audience = _text(options, "audience")
    if audience is not None and urlsplit(audience).scheme != "https":
        message = "audience must be an https:// URL (e.g. https://search.azure.us)"
        raise ValueError(message)
    key = _api_key(options)
    timeout = _seconds(options, "timeout", AZURE_SEARCH_DEFAULT_TIMEOUT_SECONDS)

    def requests_transport() -> AsyncHttpTransport:
        """Make azure-core's requests transport (requests run in threads; no aiohttp).

        Returns:
            The transport.
        """
        return AsyncioRequestsTransport(connection_timeout=timeout, read_timeout=timeout)

    return _Connection(
        endpoint=endpoint,
        credential=_credential(options, key, credential),
        transport=transport or requests_transport,
        index=index,
        index_timeout=_seconds(
            options, "index_timeout", AZURE_SEARCH_DEFAULT_INDEX_TIMEOUT_SECONDS
        ),
        audience=audience,
        hidden=(key,) if key else (),
    )


def _vector_search(options: Mapping[str, object]) -> bool:
    """Read ``vector_search``.

    Args:
        options: The options.

    Returns:
        Whether it is ``exact``.

    Raises:
        ValueError: It is neither ``approximate`` nor ``exact``.
    """
    search = (_text(options, "vector_search") or "approximate").lower()
    if search not in AZURE_SEARCH_VECTOR_SEARCH:
        message = f"vector_search must be approximate or exact (got {search!r})"
        raise ValueError(message)
    return search == "exact"


def _semantic(options: Mapping[str, object], *, hybrid: bool) -> str | None:
    """Read ``semantic_configuration``.

    Args:
        options: The options.
        hybrid: Whether ``hybrid`` is on (the semantic ranker reranks native hybrid answers).

    Returns:
        The semantic configuration's name, or ``None`` when unset.

    Raises:
        ValueError: It is not a valid name, or ``hybrid`` is off.
    """
    name = _text(options, "semantic_configuration")
    if name is None:
        return None
    if not AZURE_SEARCH_SEMANTIC_NAME.fullmatch(name):
        message = (
            f"semantic_configuration {name!r} must be 1 to 128 letters, digits, _ and -, "
            "starting with a letter or digit"
        )
        raise ValueError(message)
    if not hybrid:
        message = "semantic_configuration reranks native hybrid searches: it needs hybrid = true"
        raise ValueError(message)
    return name


def search_backend(
    options: Mapping[str, object],
    *,
    transport: Transport | None = None,
    credential: TokenCredential | None = None,
) -> AzureSearchBackend:
    """Build the Azure AI Search search backend from its ``[index_backends.azure_search]`` options.

    Options: ``endpoint`` (``https://<service>.search.windows.net``), ``index`` (``exactdocs``),
    ``auth`` (``api_key`` when a key is given, else ``default``; or ``managed_identity``),
    ``api_key`` (from the environment only) or ``api_key_file``, ``client_id`` (a user-assigned
    managed identity), ``audience`` (a sovereign cloud's), ``timeout`` (seconds, 10),
    ``index_timeout`` (seconds, 60), and the vector backend's ``hybrid``, ``vector_search`` and
    ``semantic_configuration``. An invalid option raises ``ValueError``.

    Args:
        options: The options.
        transport: Makes the HTTP transport instead of azure-core's requests one (tests).
        credential: A sync Entra ID credential instead of the one ``auth`` names (tests).

    Returns:
        The backend, not connected yet.
    """
    _semantic(options, hybrid=_switch(options, "hybrid", default=True))
    _vector_search(options)
    return AzureSearchBackend(
        service=_Service(connection=_connection(options, transport, credential))
    )


def vector_backend(
    options: Mapping[str, object],
    *,
    transport: Transport | None = None,
    credential: TokenCredential | None = None,
) -> AzureVectorBackend | AzureHybridVectorBackend | AzureSemanticVectorBackend:
    """Build the Azure AI Search vector backend from its ``[index_backends.azure_search]`` options.

    Options as ``search_backend``'s, and ``hybrid`` (native hybrid search, on: a space's
    documents carry the words too), ``vector_search`` (``approximate``, HNSW, or ``exact``) and
    ``semantic_configuration`` (the name of the semantic configuration whose semantic ranker
    reranks hybrid searches that ask for reranking; unset: never used). An invalid option raises
    ``ValueError``.

    Args:
        options: The options.
        transport: Makes the HTTP transport instead of azure-core's requests one (tests).
        credential: A sync Entra ID credential instead of the one ``auth`` names (tests).

    Returns:
        The backend, not connected yet; with ``NativeHybrid`` when ``hybrid`` is on, and
        ``NativeRerank`` too with ``semantic_configuration``.
    """
    hybrid = _switch(options, "hybrid", default=True)
    semantic = _semantic(options, hybrid=hybrid)
    vectors = AzureVectorBackend(
        service=_Service(connection=_connection(options, transport, credential)),
        words=hybrid,
        exact=_vector_search(options),
        semantic=semantic,
    )
    if semantic is not None:
        return AzureSemanticVectorBackend(vectors=vectors)
    return AzureHybridVectorBackend(vectors=vectors) if hybrid else vectors
