"""Pinecone as the vector index (``pinecone``, #362): ``EXACTDOCS_VECTOR_BACKEND=pinecone``.

The vectors of every version live in one namespace of a Pinecone index (``namespace``, one per
ExactDocs instance, so instances can share an index), each with its manifest, library, space
and tags as metadata. A vector's ID is ``<manifest>#<space>#<chunk>`` (each part
percent-quoted), so a version is deleted by listing its ID prefix: serverless indexes cannot
delete by metadata filter. Every search filters on the space and the versions asked for, so
nothing of another version is ever returned.

Vectors are stored at unit length, so a ``cosine`` or a ``dotproduct`` index ranks them by
cosine. A space whose model has fewer dimensions than the index is padded with zeros (cosine is
unchanged), so an index serves an embedding model as long as its dimension is at least the
model's. With ``hybrid = true`` (a ``dotproduct`` index), each vector also carries a sparse
vector of its chunk's terms and ``hybrid`` asks Pinecone for one sparse-dense query
(``NativeHybrid``) instead of ExactDocs fusing BM25 and the vectors.

The client is the official SDK's asyncio, HTTP-only client: no gRPC, no protobuf.
"""

import hashlib
import math
from collections import Counter
from collections.abc import Collection, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from pinecone import AsyncIndex, AsyncPinecone, PineconeError

from exactdocs.retrieval.constants import (
    PINECONE_BACKEND,
    PINECONE_DELETE_BATCH,
    PINECONE_FETCH_BATCH,
    PINECONE_HEADING_WEIGHT,
    PINECONE_HYBRID_ALPHA,
    PINECONE_HYBRID_METRIC,
    PINECONE_ID_SEPARATOR,
    PINECONE_LIST_PAGE,
    PINECONE_MAX_NAMESPACE,
    PINECONE_MAX_TOP_K,
    PINECONE_METRICS,
    PINECONE_NAMESPACE,
    PINECONE_SPARSE_TERMS,
    PINECONE_TIMEOUT_SECONDS,
    PINECONE_UPSERT_BATCH,
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
    identifier_tokens,
)

type _Filter = dict[str, Any]
type _Sparse = dict[str, list[int] | list[float]]

_OPTIONS = frozenset({
    "host",
    "index",
    "api_key",
    "api_key_file",
    "namespace",
    "hybrid",
    "hybrid_alpha",
    "timeout",
})  # fmt: skip
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True, kw_only=True)
class PineconeOptions:
    """The ``[index_backends.pinecone]`` options, checked."""

    host: str | None
    """The index's host (``https://<index>-<project>.svc.<env>.pinecone.io``); or ``index``."""
    index: str | None
    """The index's name, resolved to its host at start; or ``host``."""
    api_key: str
    """The API key (from the environment or ``api_key_file``; never the TOML file)."""
    namespace: str
    """The namespace this instance keeps its vectors in."""
    hybrid: bool
    """Store sparse vectors and answer hybrid searches (a ``dotproduct`` index)."""
    hybrid_alpha: float
    """The dense half's weight in a hybrid query, 0 to 1."""
    timeout: float
    """Seconds one request may take."""


def _vector_id(manifest_id: str, space_id: EmbeddingSpaceId, chunk_id: str) -> str:
    """Return the ID of a chunk's vector in a space.

    Args:
        manifest_id: The version.
        space_id: The space.
        chunk_id: The chunk.

    Returns:
        ``<manifest>#<space>#<chunk>``, each part percent-quoted (ASCII, no ``#`` inside).
    """
    parts = (quote(manifest_id, safe=""), str(space_id), quote(chunk_id, safe=""))
    return PINECONE_ID_SEPARATOR.join(parts)


def _version_prefix(manifest_id: str) -> str:
    """Return the prefix every vector ID of a version starts with (whatever the space).

    Args:
        manifest_id: The version.

    Returns:
        The quoted manifest ID and the separator.
    """
    return quote(manifest_id, safe="") + PINECONE_ID_SEPARATOR


def _parse_id(vector_id: str) -> tuple[str, int, ChunkId] | None:
    """Split a vector ID into its version, space and chunk.

    Args:
        vector_id: An ID ``_vector_id`` made.

    Returns:
        The manifest ID, space ID and chunk ID; ``None`` for an ID of another shape.
    """
    match vector_id.split(PINECONE_ID_SEPARATOR):
        case [manifest, space, chunk] if space.isdigit():
            return unquote(manifest), int(space), ChunkId(unquote(chunk))
        case _:
            return None


def _unit(vector: Sequence[float], dimensions: int) -> list[float]:
    """Scale a vector to unit length and pad it with zeros to the index's dimension.

    Unit vectors make a ``dotproduct`` index rank by cosine as a ``cosine`` index does, and the
    zeros change neither the norm nor any dot product.

    Args:
        vector: The vector (finite, not all zeros).
        dimensions: The index's dimension, at least the vector's length.

    Returns:
        The values Pinecone is sent.
    """
    norm = math.sqrt(math.fsum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector] + [0.0] * (dimensions - len(vector))


def _term_index(term: str) -> int:
    """Return the sparse dimension a term is counted in (a stable 32-bit hash).

    Args:
        term: A term, as ``identifier_tokens`` writes it.

    Returns:
        The index, 0 to 2**32 - 1.
    """
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big")


def _sparse(weights: Mapping[str, float], scale: float = 1.0) -> _Sparse | None:
    """Make a unit-length sparse vector of term weights, times ``scale``.

    Args:
        weights: Each term's weight (positive).
        scale: What the unit vector is multiplied by (the sparse half's weight in a query).

    Returns:
        Pinecone's ``{"indices": [...], "values": [...]}``; ``None`` without terms.
    """
    summed: dict[int, float] = {}
    for term, weight in weights.items():
        slot = _term_index(term)
        summed[slot] = summed.get(slot, 0.0) + weight  # two terms in one slot add up
    norm = math.sqrt(math.fsum(w * w for w in summed.values()))
    if not norm:
        return None
    ordered = sorted(summed.items())
    return {"indices": [i for i, _ in ordered], "values": [w / norm * scale for _, w in ordered]}


def entry_terms(entry: IndexEntry) -> dict[str, float]:
    """Weigh the terms of a chunk for its sparse vector: ``1 + ln(count)``, headings counting more.

    The terms are those a query is matched by (``identifier_tokens``), so the query's terms find
    them; only the ``PINECONE_SPARSE_TERMS`` heaviest are kept.

    Args:
        entry: The chunk.

    Returns:
        Each term's weight.
    """
    counts = Counter(identifier_tokens(entry.content).split())
    for term in identifier_tokens(" ".join(entry.heading_path)).split():
        counts[term] += PINECONE_HEADING_WEIGHT
    heaviest = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:PINECONE_SPARSE_TERMS]
    return {term: 1.0 + math.log(count) for term, count in heaviest}


def _tag_conditions(tag_filter: TagFilter) -> list[_Filter]:
    """Translate a tag filter into Pinecone metadata conditions (on the ``tags`` list).

    Args:
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The conditions, all of which must hold; none for an empty filter.
    """
    if not tag_filter.tags:
        return []
    if tag_filter.match is TagMatch.ALL:
        return [{"tags": {"$in": [tag]}} for tag in tag_filter.tags]
    return [{"tags": {"$in": list(tag_filter.tags)}}]


def _reason(error: Exception) -> str:
    """Say why a request failed, without the request (which carries the key in a header).

    Args:
        error: What the client raised.

    Returns:
        A short reason.
    """
    text = " ".join(str(error).split())
    return f"{type(error).__name__}: {text}"[:300] if text else type(error).__name__


@contextmanager
def _answering(name: str) -> Generator[None]:
    """Turn the client's failures into ``IndexBackendUnavailableError``.

    Args:
        name: The backend's name.

    Yields:
        Nothing; the block runs inside.

    Raises:
        IndexBackendUnavailableError: Pinecone refused, failed or did not answer.
    """
    try:
        yield
    except (PineconeError, OSError) as error:
        raise IndexBackendUnavailableError(name, _reason(error)) from error


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- opened at start
class PineconeVectorBackend:
    """Implements ``ports.driven.VectorBackend`` on one namespace of a Pinecone index."""

    options: PineconeOptions
    """The checked options."""
    name: str = PINECONE_BACKEND
    """The registered name."""
    _client: AsyncPinecone | None = field(default=None, init=False)
    """The control-plane client, from ``open``."""
    _index: AsyncIndex | None = field(default=None, init=False)
    """The index's data-plane client, from ``open``."""
    _dimension: int = field(default=0, init=False)
    """The index's dimension, read at ``open``."""

    async def open(self) -> None:
        """Connect to the index and check it can hold ExactDocs' vectors.

        Raises:
            IndexBackendUnavailableError: Pinecone does not answer, refuses the key, or the
                index is not a dense ``cosine`` / ``dotproduct`` one (``dotproduct`` with
                ``hybrid``).
        """
        options = self.options
        with _answering(self.name):
            self._client = AsyncPinecone(api_key=options.api_key, timeout=options.timeout)
            self._index = (
                await self._client.index(host=options.host)
                if options.host
                else await self._client.index(name=options.index or "")
            )
            stats = await self._index.describe_index_stats()
        if not stats.dimension:
            await self.close()
            raise IndexBackendUnavailableError(self.name, "the index holds no dense vectors")
        metric = (stats.metric or "").lower()
        wanted = {PINECONE_HYBRID_METRIC} if options.hybrid else PINECONE_METRICS
        if metric and metric not in wanted:
            await self.close()
            reason = f"the index's metric is {metric}; it must be {' or '.join(sorted(wanted))}"
            raise IndexBackendUnavailableError(self.name, reason)
        self._dimension = stats.dimension

    async def close(self) -> None:
        """Close the clients (each is closed even if the other fails)."""
        index, client, self._index, self._client = self._index, self._client, None, None
        try:
            if index is not None:
                await index.close()
        finally:
            if client is not None:
                await client.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Upsert the entries' vectors, with their version, library, space and tags.

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        index = self._open()
        self._check_dimensions(space)
        vectors = [self._record(space, manifest, e) for e in entries if e.vector is not None]
        with _answering(self.name):
            for start in range(0, len(vectors), PINECONE_UPSERT_BATCH):
                await index.upsert(
                    vectors=vectors[start : start + PINECONE_UPSERT_BATCH],
                    namespace=self.options.namespace,
                    show_progress=False,
                )

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space, by ID.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        await self._delete_ids([_vector_id(manifest_id, space_id, c) for c in chunk_ids])

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every vector of these versions, listing each one's ID prefix.

        Args:
            manifest_ids: The versions.
        """
        for manifest_id in manifest_ids:
            await self._delete_ids(await self._ids(_version_prefix(manifest_id)))

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Delete every vector of a space (lists the namespace: a space is dropped seldom).

        Args:
            space_id: The space.
        """
        doomed = [
            vector_id
            for vector_id in await self._ids(None)
            if (parsed := _parse_id(vector_id)) is not None and parsed[1] == space_id
        ]
        await self._delete_ids(doomed)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """Count the space's vectors per version, listing the namespace's IDs.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID.
        """
        counts: Counter[str] = Counter()
        first: dict[str, str] = {}
        for vector_id in await self._ids(None):
            parsed = _parse_id(vector_id)
            if parsed is not None and parsed[1] == space_id:
                counts[parsed[0]] += 1
                first.setdefault(parsed[0], vector_id)
        libraries = await self._libraries(first)
        return [
            HeldVersion(manifest_id=m, library=libraries[m], entries=counts[m])
            for m in sorted(counts)
            if m in libraries and (library is None or libraries[m] == library)
        ]

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Ask Pinecone for the versions' vectors nearest to the query, in the space.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries, nearest first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or limit <= 0 or space.spec.dimensions > self._open_dimension():
            return []
        matches = await self._query(
            space.id, manifest_ids, tag_filter, limit, _unit(query, self._dimension), None
        )
        hits = [
            BackendNeighbour(manifest_id=m, chunk_id=c, distance=min(2.0, max(0.0, 1.0 - score)))
            for m, c, score in matches
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits[:limit]

    def _record(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entry: IndexEntry
    ) -> dict[str, Any]:
        """Make the record Pinecone stores for an entry.

        Args:
            space: The space.
            manifest: The entry's version.
            entry: The entry, with its vector.

        Returns:
            Its ID, unit vector (padded) and metadata.
        """
        metadata: dict[str, Any] = {
            "manifest": manifest.manifest_id,
            "library": manifest.library,
            "space": int(space.id),
        }
        if entry.tags:
            metadata["tags"] = list(entry.tags)
        return {
            "id": _vector_id(manifest.manifest_id, space.id, entry.chunk_id),
            "values": _unit(entry.vector or (), self._dimension),
            "metadata": metadata,
        }

    async def _query(
        self,
        space_id: EmbeddingSpaceId,
        manifest_ids: Sequence[str],
        tag_filter: TagFilter,
        limit: int,
        vector: list[float],
        sparse: _Sparse | None,
    ) -> list[tuple[str, ChunkId, float]]:
        """Run one query in the space, filtered to the versions and tags.

        Args:
            space_id: The space.
            manifest_ids: The versions searched.
            tag_filter: Which chunks may be returned.
            limit: How many matches at most.
            vector: The dense query vector (unit length, padded).
            sparse: The sparse query vector, for a hybrid query.

        Returns:
            Each match's manifest ID, chunk ID and score, as Pinecone ranked them.
        """
        index = self._open()
        conditions: list[_Filter] = [
            {"space": {"$eq": int(space_id)}},
            {"manifest": {"$in": list(dict.fromkeys(manifest_ids))}},
            *_tag_conditions(tag_filter),
        ]
        with _answering(self.name):
            response = await index.query(
                top_k=min(limit, PINECONE_MAX_TOP_K),
                vector=vector,
                sparse_vector=sparse,
                namespace=self.options.namespace,
                filter={"$and": conditions},
            )
        wanted = set(manifest_ids)
        found: list[tuple[str, ChunkId, float]] = []
        for match in response.matches:
            parsed = _parse_id(match.id)
            if parsed is not None and parsed[1] == space_id and parsed[0] in wanted:
                found.append((parsed[0], parsed[2], float(match.score or 0.0)))
        return found

    async def _ids(self, prefix: str | None) -> list[str]:
        """List the namespace's vector IDs with a prefix, every page.

        Args:
            prefix: The prefix; every ID when ``None``.

        Returns:
            The IDs.
        """
        index = self._open()
        ids: list[str] = []
        token: str | None = None
        with _answering(self.name):
            while True:
                page = await index.list_paginated(
                    prefix=prefix,
                    limit=PINECONE_LIST_PAGE,
                    pagination_token=token,
                    namespace=self.options.namespace,
                )
                ids += [item.id for item in page.vectors if item.id]
                token = page.pagination.next if page.pagination else None
                if not token:
                    return ids

    async def _delete_ids(self, ids: Sequence[str]) -> None:
        """Delete vectors by ID (unknown ones are ignored).

        Args:
            ids: The IDs.
        """
        index = self._open()
        with _answering(self.name):
            for start in range(0, len(ids), PINECONE_DELETE_BATCH):
                await index.delete(
                    ids=list(ids[start : start + PINECONE_DELETE_BATCH]),
                    namespace=self.options.namespace,
                )

    async def _libraries(self, vector_ids: Mapping[str, str]) -> dict[str, str]:
        """Read each version's library from the metadata of one of its vectors.

        Args:
            vector_ids: One vector ID per manifest ID.

        Returns:
            The library of each version whose vector was found, by manifest ID.
        """
        index = self._open()
        by_id = {v: m for m, v in vector_ids.items()}
        ids = list(by_id)
        libraries: dict[str, str] = {}
        with _answering(self.name):
            for start in range(0, len(ids), PINECONE_FETCH_BATCH):
                fetched = await index.fetch(
                    ids=ids[start : start + PINECONE_FETCH_BATCH], namespace=self.options.namespace
                )
                for vector_id, vector in fetched.vectors.items():
                    library = (vector.metadata or {}).get("library")
                    if vector_id in by_id and isinstance(library, str):
                        libraries[by_id[vector_id]] = library
        return libraries

    def _check_dimensions(self, space: EmbeddingSpace) -> None:
        """Refuse a space whose vectors the index cannot hold.

        Args:
            space: The space.

        Raises:
            IndexBackendUnavailableError: The model has more dimensions than the index.
        """
        if space.spec.dimensions > self._open_dimension():
            reason = (
                f"the index holds {self._dimension}-dimension vectors, the embedding model "
                f"{space.spec.model!r} makes {space.spec.dimensions}: use an index of at least "
                f"{space.spec.dimensions} dimensions"
            )
            raise IndexBackendUnavailableError(self.name, reason)

    def _open(self) -> AsyncIndex:
        """Return the index's client.

        Returns:
            The data-plane client.

        Raises:
            IndexBackendUnavailableError: ``open`` was not called, or failed.
        """
        if self._index is None:
            raise IndexBackendUnavailableError(self.name, "not connected")
        return self._index

    def _open_dimension(self) -> int:
        """Return the index's dimension.

        Returns:
            The dimension ``open`` read.
        """
        self._open()
        return self._dimension


class PineconeHybridVectorBackend(PineconeVectorBackend):
    """A ``PineconeVectorBackend`` with sparse vectors, so it implements ``NativeHybrid`` too.

    Each vector carries a sparse vector of its chunk's terms (``entry_terms``, unit length);
    ``hybrid`` sends the query's dense vector times ``hybrid_alpha`` and its terms' sparse vector
    times ``1 - hybrid_alpha`` in one query, which a ``dotproduct`` index scores as their sum.
    """

    __slots__ = ()

    def _record(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entry: IndexEntry
    ) -> dict[str, Any]:
        """Make the record Pinecone stores for an entry, with its sparse vector.

        Args:
            space: The space.
            manifest: The entry's version.
            entry: The entry, with its vector.

        Returns:
            Its ID, unit vector (padded), sparse vector of its terms and metadata.
        """
        record = super()._record(space, manifest, entry)
        sparse = _sparse(entry_terms(entry))
        if sparse is not None:
            record["sparse_values"] = sparse
        return record

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Rank the versions' entries by one sparse-dense query.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The hits, best first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or limit <= 0 or space.spec.dimensions > self._open_dimension():
            return []
        alpha = self.options.hybrid_alpha
        dense = [v * alpha for v in _unit(vector, self._dimension)]
        sparse = _sparse(dict.fromkeys(query.terms, 1.0), 1.0 - alpha) if alpha < 1 else None
        matches = await self._query(space.id, manifest_ids, tag_filter, limit, dense, sparse)
        hits = [BackendHit(manifest_id=m, chunk_id=c, score=score) for m, c, score in matches]
        hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
        return hits[:limit]


def _text(options: Mapping[str, object], key: str) -> str | None:
    """Read a text option; blank counts as unset.

    Args:
        options: The options.
        key: The option.

    Returns:
        The trimmed text, or ``None``.

    Raises:
        TypeError: It is not text.
    """
    value = options.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        message = f"{key} must be text"
        raise TypeError(message)
    return value.strip() or None


def _flag(options: Mapping[str, object], key: str) -> bool:
    """Read a yes/no option (``true``/``false`` from the environment too); unset is no.

    Args:
        options: The options.
        key: The option.

    Returns:
        The flag.

    Raises:
        ValueError: It is neither.
    """
    value = options.get(key)
    if value is None or isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE | _FALSE:
        return text in _TRUE
    message = f"{key} must be true or false"
    raise ValueError(message)


def _number(options: Mapping[str, object], key: str, default: float) -> float:
    """Read a number option (text from the environment too).

    Args:
        options: The options.
        key: The option.
        default: Its value when unset.

    Returns:
        The number.

    Raises:
        ValueError: It is not a finite number.
    """
    value = options.get(key)
    if value is None:
        return default
    number = math.nan
    if isinstance(value, int | float | str) and not isinstance(value, bool):
        try:
            number = float(value)
        except ValueError:
            number = math.nan
    if not math.isfinite(number):
        message = f"{key} must be a number"
        raise ValueError(message)
    return number


def pinecone_options(options: Mapping[str, object]) -> PineconeOptions:
    """Check the ``[index_backends.pinecone]`` options.

    Args:
        options: ``host`` or ``index``; ``api_key`` (environment) or ``api_key_file``;
            optionally ``namespace``, ``hybrid``, ``hybrid_alpha`` and ``timeout``.

    Returns:
        The options.

    Raises:
        ValueError: An option is unknown, missing, or out of range.
    """
    unknown = sorted(set(options) - _OPTIONS)
    if unknown:
        message = f"unknown option(s) {', '.join(unknown)} (known: {', '.join(sorted(_OPTIONS))})"
        raise ValueError(message)
    host, index = _text(options, "host"), _text(options, "index")
    if (host is None) == (index is None):
        message = "set host (the index's host) or index (its name), not both"
        raise ValueError(message)
    api_key, key_file = _text(options, "api_key"), _text(options, "api_key_file")
    if api_key is not None and key_file is not None:
        message = "set api_key or api_key_file, not both"
        raise ValueError(message)
    if key_file is not None:
        try:
            api_key = Path(key_file).expanduser().read_text("utf-8").strip() or None
        except OSError as error:
            message = f"api_key_file {key_file!r} cannot be read ({type(error).__name__})"
            raise ValueError(message) from error
    if api_key is None:
        message = (
            "set api_key (EXACTDOCS_INDEX_BACKENDS__PINECONE__API_KEY) or api_key_file; "
            "Pinecone Local takes any key"
        )
        raise ValueError(message)
    namespace = _text(options, "namespace") or PINECONE_NAMESPACE
    if (
        not namespace.isascii()
        or not namespace.isprintable()
        or len(namespace) > PINECONE_MAX_NAMESPACE
    ):
        message = f"namespace must be printable ASCII, at most {PINECONE_MAX_NAMESPACE} characters"
        raise ValueError(message)
    alpha = _number(options, "hybrid_alpha", PINECONE_HYBRID_ALPHA)
    if not 0 <= alpha <= 1:
        message = "hybrid_alpha must be between 0 and 1"
        raise ValueError(message)
    timeout = _number(options, "timeout", PINECONE_TIMEOUT_SECONDS)
    if timeout <= 0:
        message = "timeout must be a positive number of seconds"
        raise ValueError(message)
    return PineconeOptions(
        host=host,
        index=index,
        api_key=api_key,
        namespace=namespace,
        hybrid=_flag(options, "hybrid"),
        hybrid_alpha=alpha,
        timeout=timeout,
    )


def vector_backend(options: Mapping[str, object]) -> PineconeVectorBackend:
    """Build the vector backend from its ``[index_backends.pinecone]`` options (no request yet).

    Args:
        options: The options (see ``pinecone_options``).

    Returns:
        The backend; one that answers hybrid searches itself when ``hybrid`` is set.
    """
    checked = pinecone_options(options)
    if checked.hybrid:
        return PineconeHybridVectorBackend(options=checked)
    return PineconeVectorBackend(options=checked)
