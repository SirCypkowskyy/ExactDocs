"""Qdrant as the vector backend (#355): ``EXACTDOCS_VECTOR_BACKEND=qdrant``.

Each embedding space is one collection, ``<collection>_space<id>``, created on the space's first
write with the space's dimensions and cosine distance, and keyword indexes on the payload fields
every search filters on (``manifest_id``, ``library``, ``tags``). A point is one chunk of one
version (its ID is derived from the manifest and chunk IDs), so a search filtered to a version's
manifest never sees another version's chunks. With the ``hybrid`` option, each point also carries
a sparse vector of its words (BM25 term weights; Qdrant applies the IDF), and ``hybrid`` asks
Qdrant once, fusing the sparse and dense prefetches with reciprocal rank fusion.

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Its client, ``qdrant-client``, is the ``qdrant`` extra; only this module imports it.
"""

import asyncio
import hashlib
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.http.models import QueryResponse

from exactdocs.retrieval.constants import (
    QDRANT_BACKEND,
    QDRANT_BM25_AVERAGE_WORDS,
    QDRANT_BM25_B,
    QDRANT_BM25_K1,
    QDRANT_COLLECTION_NAME,
    QDRANT_DEFAULT_COLLECTION,
    QDRANT_DEFAULT_TIMEOUT_SECONDS,
    QDRANT_DENSE_VECTOR,
    QDRANT_FACET_LIMIT,
    QDRANT_FALSE,
    QDRANT_HEADING_WEIGHT,
    QDRANT_INDEXED_FIELDS,
    QDRANT_OPTIONS,
    QDRANT_POINT_NAMESPACE,
    QDRANT_SPACE_SUFFIX,
    QDRANT_SPARSE_VECTOR,
    QDRANT_TRUE,
    QDRANT_UPSERT_BATCH,
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
    VectorMetric,
    identifier_tokens,
)

type Connect = Callable[[], AsyncQdrantClient]
"""Makes a new client; called by each ``open()`` (a client is bound to the event loop it ran in)."""


def point_id(manifest_id: str, chunk_id: str) -> str:
    """Return the ID of a chunk's point in a version: the same every time it is written.

    Args:
        manifest_id: The version's manifest.
        chunk_id: The chunk.

    Returns:
        A UUID (v5), as Qdrant takes point IDs.
    """
    return str(uuid.uuid5(QDRANT_POINT_NAMESPACE, f"{manifest_id}\n{chunk_id}"))


def _term_index(term: str) -> int:
    """Map a term to its dimension in the sparse vectors (a stable 32-bit hash).

    Args:
        term: One of ``identifier_tokens``.

    Returns:
        The dimension.
    """
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big")


def words_vector(heading_path: Sequence[str], content: str) -> models.SparseVector:
    """Weigh a chunk's words as BM25 does, before IDF (Qdrant's ``idf`` modifier adds that).

    The words are ``identifier_tokens``, as every search index of ExactDocs splits them; a word
    of the headings counts ``QDRANT_HEADING_WEIGHT`` times.

    Args:
        heading_path: The chunk's headings.
        content: The chunk's text.

    Returns:
        The sparse vector; empty for a chunk without words.
    """
    counts = Counter(identifier_tokens(content).split())
    for term in identifier_tokens(" ".join(heading_path)).split():
        counts[term] += QDRANT_HEADING_WEIGHT
    length = sum(counts.values())
    norm = QDRANT_BM25_K1 * (1 - QDRANT_BM25_B + QDRANT_BM25_B * length / QDRANT_BM25_AVERAGE_WORDS)
    weights: dict[int, float] = {}
    for term, count in counts.items():
        index = _term_index(term)
        weights[index] = weights.get(index, 0.0) + count * (QDRANT_BM25_K1 + 1) / (count + norm)
    return models.SparseVector(indices=list(weights), values=list(weights.values()))


def query_words(terms: Collection[str]) -> models.SparseVector:
    """Make the sparse vector of a query: each term once.

    Args:
        terms: The query's terms.

    Returns:
        The sparse vector.
    """
    indices = list(dict.fromkeys(_term_index(t) for t in terms))
    return models.SparseVector(indices=indices, values=[1.0] * len(indices))


def _distance(metric: VectorMetric) -> models.Distance:
    """Map a space's metric to Qdrant's distance.

    Args:
        metric: The space's metric.

    Returns:
        Qdrant's distance of the same name.
    """
    match metric:
        case VectorMetric.COSINE:
            return models.Distance.COSINE


def _filter(manifest_ids: Collection[str], tag_filter: TagFilter) -> models.Filter:
    """Filter a search to these versions and the tag filter (applied before ranking).

    Args:
        manifest_ids: The versions searched.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The Qdrant filter.
    """
    must: list[models.Condition] = [
        models.FieldCondition(key="manifest_id", match=models.MatchAny(any=list(manifest_ids)))
    ]
    if tag_filter.tags and tag_filter.match is TagMatch.ALL:
        must += [
            models.FieldCondition(key="tags", match=models.MatchValue(value=t))
            for t in tag_filter.tags
        ]
    elif tag_filter.tags:
        must.append(
            models.FieldCondition(key="tags", match=models.MatchAny(any=list(tag_filter.tags)))
        )
    return models.Filter(must=must)


def _reason(error: Exception) -> str:
    """Say briefly why Qdrant did not answer, never with a credential or a response body.

    Args:
        error: What the client raised.

    Returns:
        The HTTP status, or the type of the transport error.
    """
    if isinstance(error, UnexpectedResponse):
        return f"HTTP {error.status_code} {error.reason_phrase}".strip()
    if isinstance(error, ResponseHandlingException):
        return type(error.source).__name__
    return type(error).__name__


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class QdrantVectorBackend:
    """Implements ``ports.driven.VectorBackend`` over Qdrant: one collection per space."""

    connect: Connect
    """Makes the client ``open()`` uses until ``close()``."""
    collection: str = QDRANT_DEFAULT_COLLECTION
    """The prefix of every collection: a space's is ``<collection>_space<id>``."""
    hybrid_words: bool = False
    """Write each point's sparse vector of words too (native hybrid search)."""
    on_disk: bool = False
    """Keep the dense vectors on disk (memory-mapped) instead of in memory."""
    quantization: bool = False
    """Quantise the dense vectors to int8 (scalar), kept in memory, for a smaller footprint."""
    name: str = QDRANT_BACKEND
    """The registered name."""
    _client: AsyncQdrantClient | None = field(default=None, init=False, repr=False)
    """The open client; ``None`` before ``open()`` and after ``close()``."""
    _known: set[str] = field(default_factory=set, init=False, repr=False)
    """The collections seen to exist, in this process (forgotten when one answers 404)."""
    _ready: set[str] = field(default_factory=set, init=False, repr=False)
    """The collections known to exist with their payload indexes, in this process."""
    _setting_up: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    """Lets one task create a collection at a time."""

    async def open(self) -> None:
        """Connect and check that Qdrant answers (and takes the API key, if one is set).

        ``IndexBackendUnavailableError`` when it cannot be reached, or refused the key.
        """
        await self.close()
        self._client = self.connect()
        self._known.clear()
        self._ready.clear()
        await self._call(self._client.get_collections())

    async def close(self) -> None:
        """Close the client, if open."""
        client, self._client = self._client, None
        if client is not None:
            await client.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' points in the space's collection (created when missing).

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        del manifest  # every entry names its manifest
        points = [self._point(e) for e in entries if e.vector is not None]
        if not points:
            return
        collection = await self._collection_for(space)
        if not await self._upsert(collection, points):  # dropped elsewhere since: create it again
            await self._upsert(await self._collection_for(space), points, again=False)

    async def _upsert(
        self, collection: str, points: Sequence[models.PointStruct], *, again: bool = True
    ) -> bool:
        """Write points, a batch at a time.

        Args:
            collection: The collection.
            points: The points.
            again: Whether the caller creates the collection and calls again when it is gone.

        Returns:
            False when the collection is gone (and ``again``), True once written.

        Raises:
            IndexBackendUnavailableError: Qdrant did not take them.
        """
        client = self._open()
        for start in range(0, len(points), QDRANT_UPSERT_BATCH):
            batch = points[start : start + QDRANT_UPSERT_BATCH]
            try:
                await client.upsert(collection, points=batch, wait=True)
            except UnexpectedResponse as error:
                if error.status_code == HTTPStatus.NOT_FOUND:
                    self._forget(collection)
                    if again:
                        return False
                raise IndexBackendUnavailableError(self.name, _reason(error)) from error
            except (ResponseHandlingException, OSError) as error:
                raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        return True

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some points of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        collection = self._name(space_id)
        if not chunk_ids or not await self._exists(collection):
            return
        ids: list[models.ExtendedPointId] = [point_id(manifest_id, c) for c in chunk_ids]
        selector = models.PointIdsList(points=ids)
        await self._call(self._open().delete(collection, points_selector=selector, wait=True))

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every point of these versions, in every space's collection.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        selector = models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="manifest_id", match=models.MatchAny(any=list(manifest_ids))
                    )
                ]
            )
        )
        client = self._open()
        for collection in await self._collections():
            await self._call(client.delete(collection, points_selector=selector, wait=True))

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Delete a space's collection; nothing happens for an unknown space.

        Args:
            space_id: The space.
        """
        collection = self._name(space_id)
        if await self._exists(collection):
            await self._call(self._open().delete_collection(collection))
        self._forget(collection)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """Count the space's points per version (facets on the indexed payload fields).

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID; empty for an unknown space.
        """
        collection = self._name(space_id)
        if not await self._exists(collection):
            return []
        libraries = [library] if library is not None else await self._facet(collection, "library")
        held = [
            HeldVersion(manifest_id=manifest_id, library=name, entries=count)
            for name in libraries
            for manifest_id, count in (
                await self._counts(collection, "manifest_id", "library", name)
            ).items()
        ]
        return sorted(held, key=lambda h: h.manifest_id)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Ask Qdrant for the versions' points nearest to the query, filtered server-side.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries with their cosine distances, nearest first; ties by chunk ID.
        """
        if not manifest_ids or limit < 1:
            return []
        found = await self._points(
            self._name(space.id),
            lambda client, collection: client.query_points(
                collection,
                query=[float(v) for v in query],
                using=QDRANT_DENSE_VECTOR,
                query_filter=_filter(manifest_ids, tag_filter),
                limit=limit,
                with_payload=["manifest_id", "chunk_id"],
            ),
        )
        wanted = set(manifest_ids)
        hits = [
            BackendNeighbour(
                manifest_id=str(payload["manifest_id"]),
                chunk_id=ChunkId(str(payload["chunk_id"])),
                distance=min(2.0, max(0.0, 1.0 - point.score)),
            )
            for point in found
            if (payload := point.payload or {}).get("manifest_id") in wanted
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits

    def _point(self, entry: IndexEntry) -> models.PointStruct:
        """Make an entry's point: its vectors and the payload searches filter on.

        Args:
            entry: The entry, with a vector.

        Returns:
            The point.
        """
        vector: dict[str, models.Vector] = {QDRANT_DENSE_VECTOR: list(entry.vector or ())}
        words = words_vector(entry.heading_path, entry.content) if self.hybrid_words else None
        if words is not None and words.indices:
            vector[QDRANT_SPARSE_VECTOR] = words
        return models.PointStruct(
            id=point_id(entry.manifest_id, entry.chunk_id),
            vector=vector,
            payload={
                "manifest_id": entry.manifest_id,
                "library": entry.library,
                "version_id": entry.version_id,
                "chunk_id": entry.chunk_id,
                "article_path": entry.article_path,
                "heading_path": list(entry.heading_path),
                "tags": list(entry.tags),
            },
        )

    def _name(self, space_id: EmbeddingSpaceId) -> str:
        """Name a space's collection.

        Args:
            space_id: The space.

        Returns:
            ``<collection>_space<id>``.
        """
        return f"{self.collection}{QDRANT_SPACE_SUFFIX}{space_id}"

    async def _collections(self) -> list[str]:
        """List this instance's collections (those named after the ``collection`` option).

        Returns:
            Their names.
        """
        found = await self._call(self._open().get_collections())
        prefix = f"{self.collection}{QDRANT_SPACE_SUFFIX}"
        return [
            c.name
            for c in found.collections
            if c.name.startswith(prefix) and c.name.removeprefix(prefix).isdigit()
        ]

    async def _exists(self, collection: str) -> bool:
        """Tell whether a collection exists.

        Args:
            collection: Its name.

        Returns:
            True when it does.
        """
        if collection in self._known:
            return True
        if found := await self._call(self._open().collection_exists(collection)):
            self._known.add(collection)
        return found

    def _forget(self, collection: str) -> None:
        """Forget that a collection exists (it was dropped, here or elsewhere).

        Args:
            collection: Its name.
        """
        self._known.discard(collection)
        self._ready.discard(collection)

    async def _points(
        self,
        collection: str,
        ask: Callable[[AsyncQdrantClient, str], Awaitable[QueryResponse]],
    ) -> list[models.ScoredPoint]:
        """Run a query on a collection; a missing one (never made, or dropped) holds nothing.

        Args:
            collection: The collection.
            ask: Sends the query, given the client and the collection.

        Returns:
            The points found, best first.

        Raises:
            IndexBackendUnavailableError: Qdrant did not answer.
        """
        if not await self._exists(collection):
            return []
        try:
            return (await ask(self._open(), collection)).points
        except UnexpectedResponse as error:
            if error.status_code == HTTPStatus.NOT_FOUND:
                self._forget(collection)
                return []
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        except (ResponseHandlingException, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error

    async def _collection_for(self, space: EmbeddingSpace) -> str:
        """Create the space's collection and its payload indexes when missing.

        Args:
            space: The space: its dimensions and metric make the dense vector's parameters.

        Returns:
            The collection's name.

        Raises:
            IndexBackendUnavailableError: The collection exists with vectors of other dimensions
                (another instance's, under the same ``collection`` option).
        """
        collection = self._name(space.id)
        if collection in self._ready:
            return collection
        async with self._setting_up:
            if collection in self._ready:
                return collection
            client = self._open()
            if not await self._call(client.collection_exists(collection)):
                await self._create(collection, space)
            info = await self._call(client.get_collection(collection))
            dense = info.config.params.vectors
            size = dense[QDRANT_DENSE_VECTOR].size if isinstance(dense, Mapping) else None
            if size != space.spec.dimensions:
                reason = (
                    f"the collection {collection!r} does not hold {QDRANT_DENSE_VECTOR!r} vectors "
                    f"of {space.spec.dimensions} dimensions: give this instance its own "
                    "`collection`"
                )
                raise IndexBackendUnavailableError(self.name, reason)
            for name in QDRANT_INDEXED_FIELDS:
                if name not in (info.payload_schema or {}):
                    await self._call(
                        client.create_payload_index(
                            collection,
                            field_name=name,
                            field_schema=models.KeywordIndexParams(
                                type=models.KeywordIndexType.KEYWORD,
                                is_tenant=name == "manifest_id" or None,
                            ),
                            wait=True,
                        )
                    )
            self._known.add(collection)
            self._ready.add(collection)
        return collection

    async def _create(self, collection: str, space: EmbeddingSpace) -> None:
        """Create a space's collection: a dense vector of its size, a sparse one for words.

        Args:
            collection: The name.
            space: The space.

        Raises:
            IndexBackendUnavailableError: Qdrant did not create it (one that another process
                created meanwhile is fine).
        """
        quantization = (
            models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, always_ram=True)
            )
            if self.quantization
            else None
        )
        try:
            await self._open().create_collection(
                collection,
                vectors_config={
                    QDRANT_DENSE_VECTOR: models.VectorParams(
                        size=space.spec.dimensions,
                        distance=_distance(space.spec.metric),
                        on_disk=self.on_disk or None,
                    )
                },
                sparse_vectors_config={
                    QDRANT_SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
                quantization_config=quantization,
            )
        except UnexpectedResponse as error:
            # Another process may have created it meanwhile (Qdrant refuses a second creation).
            if not await self._call(self._open().collection_exists(collection)):
                raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        except (ResponseHandlingException, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error

    async def _facet(self, collection: str, key: str) -> list[str]:
        """List the distinct values of an indexed payload field.

        Args:
            collection: The collection.
            key: The field.

        Returns:
            Its values.
        """
        found = await self._call(
            self._open().facet(collection, key=key, limit=QDRANT_FACET_LIMIT, exact=True)
        )
        return [str(hit.value) for hit in found.hits]

    async def _counts(self, collection: str, key: str, where: str, value: str) -> dict[str, int]:
        """Count the points per value of a field, among those whose ``where`` field is ``value``.

        Args:
            collection: The collection.
            key: The field counted by.
            where: The field filtered on.
            value: Its value.

        Returns:
            The exact count of each value held.
        """
        found = await self._call(
            self._open().facet(
                collection,
                key=key,
                facet_filter=models.Filter(
                    must=[models.FieldCondition(key=where, match=models.MatchValue(value=value))]
                ),
                limit=QDRANT_FACET_LIMIT,
                exact=True,
            )
        )
        return {str(hit.value): hit.count for hit in found.hits if hit.count}

    def _open(self) -> AsyncQdrantClient:
        """Return the open client.

        Returns:
            The client.

        Raises:
            IndexBackendUnavailableError: ``open()`` was not called, or ``close()`` was.
        """
        if self._client is None:
            raise IndexBackendUnavailableError(self.name, "not open")
        return self._client

    async def _call[T](self, call: Awaitable[T]) -> T:
        """Await a client call, turning a transport or server failure into the domain's error.

        Args:
            call: The call.

        Returns:
            Its answer.

        Raises:
            IndexBackendUnavailableError: Qdrant did not answer, or answered with an error.
        """
        try:
            return await call
        except (UnexpectedResponse, ResponseHandlingException, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class QdrantHybridVectorBackend(QdrantVectorBackend):
    """Implements ``VectorBackend`` and ``NativeHybrid``: words and vectors fused by Qdrant.

    The ``hybrid`` option: every point also carries its words as a BM25-weighted sparse vector
    (with the IDF Qdrant computes), and ``hybrid`` is one Qdrant query whose dense and sparse
    prefetches, both filtered to the versions and tags, are fused with reciprocal rank fusion.
    """

    hybrid_words: bool = True
    """Write each point's sparse vector of words: what the sparse prefetch ranks."""

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Fuse the versions' sparse (words) and dense (vector) rankings in one Qdrant query.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms (a query without terms ranks by its vector alone).
            vector: The query's vector.
            tag_filter: Which chunks may be returned; applied in both prefetches.
            limit: The most hits.

        Returns:
            The fused hits, best first.
        """
        if not manifest_ids or limit < 1:
            return []
        where = _filter(manifest_ids, tag_filter)
        depth = max(limit, RRF_DEPTH)
        prefetch = [
            models.Prefetch(
                query=[float(v) for v in vector],
                using=QDRANT_DENSE_VECTOR,
                filter=where,
                limit=depth,
            )
        ]
        if query.terms:
            prefetch.append(
                models.Prefetch(
                    query=query_words(query.terms),
                    using=QDRANT_SPARSE_VECTOR,
                    filter=where,
                    limit=depth,
                )
            )
        found = await self._points(
            self._name(space.id),
            lambda client, collection: client.query_points(
                collection,
                prefetch=prefetch,
                query=models.RrfQuery(rrf=models.Rrf(k=RRF_K)),
                query_filter=where,
                limit=limit,
                with_payload=["manifest_id", "chunk_id"],
            ),
        )
        wanted = set(manifest_ids)
        return [
            BackendHit(
                manifest_id=str(payload["manifest_id"]),
                chunk_id=ChunkId(str(payload["chunk_id"])),
                score=point.score,
            )
            for point in found
            if (payload := point.payload or {}).get("manifest_id") in wanted
        ]


def _switch(options: Mapping[str, object], name: str) -> bool:
    """Read an on/off option (TOML booleans, or text from the environment).

    Args:
        options: The options.
        name: The option.

    Returns:
        Its value; off when unset.

    Raises:
        ValueError: It is neither.
    """
    value = options.get(name, False)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in QDRANT_TRUE:
        return True
    if text in QDRANT_FALSE:
        return False
    message = f"{name} must be true or false (got {value!r})"
    raise ValueError(message)


def _api_key(options: Mapping[str, object]) -> str | None:
    """Read the API key from ``api_key`` (the environment) or the file ``api_key_file`` names.

    Args:
        options: The options.

    Returns:
        The key, or ``None`` when neither is set.

    Raises:
        ValueError: Both are set, or the file cannot be read or is empty.
    """
    key, path = options.get("api_key"), options.get("api_key_file")
    if key and path:
        message = "set api_key or api_key_file, not both"
        raise ValueError(message)
    if path:
        try:
            key = Path(str(path)).expanduser().read_text("utf-8").strip()
        except OSError as error:
            message = f"api_key_file {str(path)!r} cannot be read ({type(error).__name__})"
            raise ValueError(message) from error
        if not key:
            message = f"api_key_file {str(path)!r} is empty"
            raise ValueError(message)
    return (str(key).strip() or None) if key else None


def vector_backend(options: Mapping[str, object]) -> QdrantVectorBackend:
    """Build the Qdrant vector backend from its ``[index_backends.qdrant]`` options.

    Options: ``url`` (required: ``http(s)://host[:port]``, port 6333 when none), ``collection``
    (the collections' prefix, ``exactdocs``), ``api_key`` (from the environment only) or
    ``api_key_file``, ``timeout`` (seconds, 10), ``hybrid`` (native hybrid search, off),
    ``on_disk`` (dense vectors memory-mapped from disk, off) and ``quantization`` (``none`` or
    ``scalar``: int8 copies kept in memory).

    Args:
        options: The options.

    Returns:
        The backend, not connected yet; with ``NativeHybrid`` when ``hybrid`` is on.

    Raises:
        ValueError: An option is unknown, missing or invalid.
    """
    unknown = sorted(set(options) - QDRANT_OPTIONS)
    if unknown:
        message = (
            f"unknown options {', '.join(unknown)} (known: {', '.join(sorted(QDRANT_OPTIONS))})"
        )
        raise ValueError(message)
    url = str(options.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        message = "url is required: the Qdrant server's http(s)://host[:port]"
        raise ValueError(message)
    collection = str(options.get("collection") or QDRANT_DEFAULT_COLLECTION).strip()
    if not QDRANT_COLLECTION_NAME.fullmatch(collection):
        message = f"collection {collection!r} must be letters, digits, '_' and '-'"
        raise ValueError(message)
    try:
        timeout = int(str(options.get("timeout", QDRANT_DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = 0
    if timeout < 1:
        message = f"timeout must be a whole number of seconds (got {options.get('timeout')!r})"
        raise ValueError(message)
    quantization = str(options.get("quantization") or "none").strip().lower()
    if quantization not in {"none", "scalar"}:
        message = f"quantization must be none or scalar (got {quantization!r})"
        raise ValueError(message)
    api_key = _api_key(options)

    def connect() -> AsyncQdrantClient:
        """Make a client of the configured server.

        Returns:
            The client (no request sent yet).
        """
        return AsyncQdrantClient(
            url=url, api_key=api_key, timeout=timeout, check_compatibility=False
        )

    kind = QdrantHybridVectorBackend if _switch(options, "hybrid") else QdrantVectorBackend
    return kind(
        connect=connect,
        collection=collection,
        on_disk=_switch(options, "on_disk"),
        quantization=quantization == "scalar",
    )
