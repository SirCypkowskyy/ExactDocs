"""Weaviate as the search and vector backend (#359), ``weaviate`` in either backend setting.

``EXACTDOCS_SEARCH_BACKEND=weaviate`` and/or ``EXACTDOCS_VECTOR_BACKEND=weaviate``. The search
index is one collection, ``<collection>_search``; each embedding space is one collection,
``<collection>_space<id>``. Either is created on its first write when it is missing, with
ExactDocs' own (self-provided) vectors only: no Weaviate vectorizer, so no Weaviate module
ever calls a model provider. An object is one chunk of one version (its UUID is derived from the
manifest and chunk IDs) carrying the ``manifest_id``, ``library``, ``version_id``, ``chunk_id``,
``article_path`` and ``tags`` properties, and its words in three BM25-searchable properties
(``heading``, ``path``, ``body``: ``identifier_tokens``, boosted as the database's FTS columns).
Every query filters on the asked versions' ``manifest_id`` (and the tags) in Weaviate, before
ranking, so another version's chunks are never returned. Keyword search is Weaviate's BM25
query, vector search its ``near_vector`` query, and ``hybrid`` (``NativeHybrid``) its hybrid
query, which fuses both in one request.

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Its client, ``weaviate-client`` (v4), is the ``weaviate`` extra; only this module imports it.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import weaviate
from weaviate import WeaviateAsyncClient
from weaviate.classes.aggregate import GroupByAggregate
from weaviate.classes.config import (
    Configure,
    DataType,
    Property,
    StopwordsPreset,
    Tokenization,
    VectorDistances,
)
from weaviate.classes.data import DataObject
from weaviate.classes.init import AdditionalConfig, Auth, Timeout
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery
from weaviate.collections.classes.filters import _Filters
from weaviate.exceptions import UnexpectedStatusCodeError, WeaviateBaseError

from exactdocs.retrieval.constants import (
    WEAVIATE_BACKEND,
    WEAVIATE_COLLECTION_NAME,
    WEAVIATE_DEFAULT_ALPHA,
    WEAVIATE_DEFAULT_COLLECTION,
    WEAVIATE_DEFAULT_GRPC_PORT,
    WEAVIATE_DEFAULT_TIMEOUT_SECONDS,
    WEAVIATE_DELETE_ROUNDS,
    WEAVIATE_FUSIONS,
    WEAVIATE_GROUP_LIMIT,
    WEAVIATE_HELD_SEPARATOR,
    WEAVIATE_INIT_TIMEOUT_SECONDS,
    WEAVIATE_INSERT_BATCH,
    WEAVIATE_OBJECT_NAMESPACE,
    WEAVIATE_OPTIONS,
    WEAVIATE_RETURNED,
    WEAVIATE_SEARCH_SUFFIX,
    WEAVIATE_SPACE_SUFFIX,
    WEAVIATE_TEXT_FIELDS,
    WEAVIATE_TIE_MARGIN,
    WEAVIATE_VECTOR_NAME,
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

type Connect = Callable[[], WeaviateAsyncClient]
"""Makes a new client; called by each ``open()`` (a client is bound to the event loop it ran in)."""


def object_id(manifest_id: str, chunk_id: str) -> uuid.UUID:
    """Return the UUID of a chunk's object in a version: the same every time it is written.

    Args:
        manifest_id: The version's manifest.
        chunk_id: The chunk.

    Returns:
        A UUID (v5), so writing the entry again replaces its object.
    """
    return uuid.uuid5(WEAVIATE_OBJECT_NAMESPACE, f"{manifest_id}\n{chunk_id}")


def _properties(entry: IndexEntry) -> dict[str, Any]:
    """Return an entry's object properties: what filters, counts and BM25 read.

    Args:
        entry: The entry.

    Returns:
        The properties, by name.
    """
    heading = entry.heading_path[-1] if entry.heading_path else ""
    return {
        "manifest_id": entry.manifest_id,
        "library": entry.library,
        "version_id": entry.version_id,
        "chunk_id": str(entry.chunk_id),
        "article_path": entry.article_path,
        "tags": list(entry.tags),
        "held_key": f"{entry.library}{WEAVIATE_HELD_SEPARATOR}{entry.manifest_id}",
        "heading": identifier_tokens(heading),
        "path": identifier_tokens(" / ".join(entry.heading_path[:-1])),
        "body": identifier_tokens(entry.content),
    }


def _schema() -> list[Property]:
    """Return the properties every collection is created with.

    The identifiers are whole values (``field`` tokenization) for exact filters and grouping;
    the three text properties are split on whitespace only, as ``identifier_tokens`` already cut
    the words (``retry_policy`` stays one token next to ``retry`` and ``policy``).

    Returns:
        The properties.
    """
    keys = [
        Property(
            name=name,
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_searchable=False,
            index_filterable=True,
        )
        for name in ("manifest_id", "library", "version_id", "chunk_id", "held_key")
    ]
    words = [
        Property(
            name=name,
            data_type=DataType.TEXT,
            tokenization=Tokenization.WHITESPACE,
            index_searchable=True,
            index_filterable=True,
        )
        for name in WEAVIATE_TEXT_FIELDS
    ]
    return [
        *keys,
        Property(
            name="article_path",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_searchable=False,
            index_filterable=False,
        ),
        Property(
            name="tags",
            data_type=DataType.TEXT_ARRAY,
            tokenization=Tokenization.FIELD,
            index_searchable=False,
            index_filterable=True,
        ),
        *words,
    ]


def _distance(metric: VectorMetric) -> VectorDistances:
    """Map a space's metric to Weaviate's distance.

    Args:
        metric: The space's metric.

    Returns:
        Weaviate's distance of the same name.
    """
    match metric:
        case VectorMetric.COSINE:
            return VectorDistances.COSINE


def _boosted() -> list[str]:
    """Return the properties BM25 searches, each with its boost (``heading^20``...).

    Returns:
        The query properties.
    """
    return [f"{name}^{weight:g}" for name, weight in WEAVIATE_TEXT_FIELDS.items()]


def _filter(manifest_ids: Collection[str], tag_filter: TagFilter) -> _Filters:
    """Filter a query to these versions and the tag filter (applied before ranking).

    Args:
        manifest_ids: The versions searched; at least one.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The Weaviate filter.
    """
    where = Filter.by_property("manifest_id").contains_any(list(manifest_ids))
    if tag_filter.tags and tag_filter.match is TagMatch.ALL:
        where &= Filter.by_property("tags").contains_all(list(tag_filter.tags))
    elif tag_filter.tags:
        where &= Filter.by_property("tags").contains_any(list(tag_filter.tags))
    return where


def _matching(terms: Collection[str]) -> _Filters:
    """Filter to the objects any of these terms occurs in (what BM25 matches, uncapped).

    Args:
        terms: The query's terms; at least one.

    Returns:
        The Weaviate filter.
    """
    return Filter.any_of(
        [Filter.by_property(name).contains_any(list(terms)) for name in WEAVIATE_TEXT_FIELDS]
    )


def _reason(error: BaseException) -> str:
    """Say briefly why Weaviate did not answer, never with a credential or a response body.

    Args:
        error: What the client raised.

    Returns:
        The HTTP status, or the type of the error.
    """
    if isinstance(error, UnexpectedStatusCodeError):
        return f"HTTP {error.status_code}"
    return type(error).__name__


def _hits(found: Sequence[Any], wanted: Collection[str], limit: int) -> list[BackendHit]:
    """Turn a scored query's objects into hits: best first, ties by chunk ID, cut at ``limit``.

    Args:
        found: The objects Weaviate returned (with their score).
        wanted: The versions searched (a hit of any other is dropped, should one slip in).
        limit: The most hits.

    Returns:
        The hits.
    """
    hits = [
        BackendHit(
            manifest_id=str(o.properties["manifest_id"]),
            chunk_id=ChunkId(str(o.properties["chunk_id"])),
            score=float(o.metadata.score or 0.0),
        )
        for o in found
        if o.properties.get("manifest_id") in wanted
    ]
    hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
    return hits[:limit]


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class _WeaviateBackend:
    """The connection and collection handling both Weaviate backends share."""

    connect: Connect
    """Makes the client ``open()`` uses until ``close()``."""
    collection: str = WEAVIATE_DEFAULT_COLLECTION
    """The prefix of every collection's name (its first letter upper case, as Weaviate has it)."""
    name: str = WEAVIATE_BACKEND
    """The registered name."""
    _client: WeaviateAsyncClient | None = field(default=None, init=False, repr=False)
    """The open client; ``None`` before ``open()`` and after ``close()``."""
    _known: set[str] = field(default_factory=set, init=False, repr=False)
    """The collections seen to exist, in this process (forgotten when a query on one fails)."""
    _setting_up: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    """Lets one task create a collection at a time."""

    async def open(self) -> None:
        """Connect and check that Weaviate answers (REST and gRPC), and takes the API key.

        Raises:
            IndexBackendUnavailableError: It cannot be reached, or refused the key.
        """
        await self.close()
        client = self.connect()
        try:
            await client.connect()
        except (WeaviateBaseError, OSError) as error:
            await _quietly(client.close())
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        self._client = client
        self._known.clear()

    async def close(self) -> None:
        """Close the client, if open."""
        client, self._client = self._client, None
        if client is not None:
            await _quietly(client.close())

    def _open(self) -> WeaviateAsyncClient:
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
            IndexBackendUnavailableError: Weaviate did not answer, or answered with an error.
        """
        try:
            return await call
        except (WeaviateBaseError, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error

    def _named(self, suffix: str) -> str:
        """Return a collection's name, as Weaviate keeps it (the first letter upper case).

        Args:
            suffix: What follows the ``collection`` option.

        Returns:
            The name.
        """
        return f"{self.collection[:1].upper()}{self.collection[1:]}{suffix}"

    async def _exists(self, collection: str) -> bool:
        """Tell whether a collection exists (remembered once seen).

        Args:
            collection: The collection.

        Returns:
            True when it exists.
        """
        if collection in self._known:
            return True
        found = await self._call(self._open().collections.exists(collection))
        if found:
            self._known.add(collection)
        return found

    async def _ensure(self, collection: str, distance: VectorDistances | None) -> None:
        """Create a collection when it is missing (asked on every write).

        Weaviate's auto-schema would otherwise make one with its own types, should it have been
        dropped behind ExactDocs' back.

        Args:
            collection: The collection.
            distance: Its vectors' distance; ``None`` for the search index (no vectors).

        Raises:
            IndexBackendUnavailableError: Weaviate did not create it (one that another process
                created meanwhile is fine).
        """
        client = self._open()
        async with self._setting_up:
            if await self._call(client.collections.exists(collection)):
                self._known.add(collection)
                return
            index = (
                Configure.VectorIndex.flat()
                if distance is None
                else Configure.VectorIndex.hnsw(distance_metric=distance)
            )
            try:
                await cast(
                    "Awaitable[object]",
                    client.collections.create(
                        collection,
                        description="ExactDocs index (derived data: exactdocs index rebuild)",
                        properties=_schema(),
                        vector_config=Configure.Vectors.self_provided(
                            name=WEAVIATE_VECTOR_NAME, vector_index_config=index
                        ),
                        inverted_index_config=Configure.inverted_index(
                            stopwords_preset=StopwordsPreset.NONE, index_property_length=True
                        ),
                    ),
                )
            except (WeaviateBaseError, OSError) as error:
                # Another process may have created it meanwhile (Weaviate refuses a second one).
                if not await self._call(client.collections.exists(collection)):
                    raise IndexBackendUnavailableError(self.name, _reason(error)) from error
            self._known.add(collection)

    async def _insert(self, collection: str, objects: Sequence[DataObject[Any, Any]]) -> None:
        """Write objects, a batch at a time (an object with the same UUID is replaced).

        Args:
            collection: The collection.
            objects: The objects.

        Raises:
            IndexBackendUnavailableError: Weaviate did not take them all.
        """
        data = self._open().collections.use(collection).data
        for start in range(0, len(objects), WEAVIATE_INSERT_BATCH):
            batch = objects[start : start + WEAVIATE_INSERT_BATCH]
            result = await self._call(data.insert_many(batch))
            if result.has_errors:
                self._known.discard(collection)
                first = next(iter(result.errors.values()))
                reason = f"{len(result.errors)} objects refused: {first.message[:200]}"
                raise IndexBackendUnavailableError(self.name, reason)

    async def _delete(self, collection: str, where: _Filters) -> None:
        """Delete every object of a collection a filter matches.

        A batch delete takes the server's ``QUERY_MAXIMUM_RESULTS`` at most, so it is repeated
        until none matches.

        Args:
            collection: The collection.
            where: The filter.
        """
        data = self._open().collections.use(collection).data
        for _ in range(WEAVIATE_DELETE_ROUNDS):
            result = await self._call(data.delete_many(where=where))
            if not result.matches or not result.successful:
                return

    async def _groups(
        self, collection: str, where: _Filters | None, prop: str, limit: int
    ) -> dict[str, int]:
        """Count the objects a filter matches per value of a property.

        Args:
            collection: The collection.
            where: The filter; every object when ``None``.
            prop: The property counted by.
            limit: The most values counted.

        Returns:
            The count of each value held (no zeros).
        """
        found = await self._call(
            self._open()
            .collections.use(collection)
            .aggregate.over_all(
                filters=where,
                group_by=GroupByAggregate(prop=prop, limit=limit),
                total_count=True,
            )
        )
        return {
            str(group.grouped_by.value): group.total_count
            for group in found.groups
            if group.total_count
        }

    async def _held(self, collection: str, library: str | None) -> list[HeldVersion]:
        """List the versions a collection holds objects of, and how many (exact counts).

        Args:
            collection: The collection.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID; empty for a missing collection.
        """
        if not await self._exists(collection):
            return []
        where = None if library is None else Filter.by_property("library").equal(library)
        counts = await self._groups(collection, where, "held_key", WEAVIATE_GROUP_LIMIT)
        held = []
        for key, entries in counts.items():
            owner, _, manifest_id = key.rpartition(WEAVIATE_HELD_SEPARATOR)
            held.append(HeldVersion(manifest_id=manifest_id, library=owner, entries=entries))
        return sorted(held, key=lambda h: h.manifest_id)

    async def _query[T](self, collection: str, run: Callable[[Any], Awaitable[T]], empty: T) -> T:
        """Run a query on a collection; a missing collection gives ``empty``.

        Args:
            collection: The collection.
            run: Runs the query on the collection's handle.
            empty: The answer when the collection does not exist.

        Returns:
            The query's answer.

        Raises:
            IndexBackendUnavailableError: Weaviate did not answer.
        """
        if not await self._exists(collection):
            return empty
        handle = self._open().collections.use(collection)
        try:
            return await run(handle)
        except (WeaviateBaseError, OSError) as error:
            self._known.discard(collection)  # dropped elsewhere since? asked again next time
            if not await self._exists(collection):
                return empty
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error


async def _quietly(call: Awaitable[object]) -> None:
    """Await a client's ``close()``, ignoring what a dead connection raises then.

    Args:
        call: The call.
    """
    with suppress(WeaviateBaseError, OSError):
        await call


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class WeaviateSearchBackend(_WeaviateBackend):
    """Implements ``ports.driven.SearchBackend`` over Weaviate's BM25 (one collection)."""

    @property
    def _collection(self) -> str:
        """The search index's collection."""
        return self._named(WEAVIATE_SEARCH_SUFFIX)

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries' objects (the collection is created when missing).

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        del manifest  # every entry names its manifest
        if not entries:
            return
        await self._ensure(self._collection, None)
        await self._insert(
            self._collection,
            [
                DataObject(properties=_properties(e), uuid=object_id(e.manifest_id, e.chunk_id))
                for e in entries
            ],
        )

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every object of these versions.

        Args:
            manifest_ids: The versions.
        """
        if manifest_ids and await self._exists(self._collection):
            where = Filter.by_property("manifest_id").contains_any(list(manifest_ids))
            await self._delete(self._collection, where)

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """Count the objects per version (an aggregate grouped by library and manifest).

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self._held(self._collection, library)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' objects with Weaviate's BM25 (headings boosted), best first.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms (matched as alternatives).
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or not query.terms or limit < 1:
            return []
        found = await self._query(
            self._collection,
            lambda handle: handle.query.bm25(
                " ".join(query.terms),
                query_properties=_boosted(),
                filters=_filter(manifest_ids, tag_filter),
                limit=limit + WEAVIATE_TIE_MARGIN,
                return_metadata=MetadataQuery(score=True),
                return_properties=list(WEAVIATE_RETURNED),
            ),
            None,
        )
        return [] if found is None else _hits(found.objects, set(manifest_ids), limit)

    async def count(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the objects of each version any term occurs in (an aggregate, uncapped).

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many objects match, by manifest ID; zeros left out.
        """
        if not manifest_ids or not query.terms or not await self._exists(self._collection):
            return {}
        where = _filter(manifest_ids, tag_filter) & _matching(query.terms)
        return await self._groups(self._collection, where, "manifest_id", len(manifest_ids))


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class WeaviateVectorBackend(_WeaviateBackend):
    """Implements ``ports.driven.VectorBackend`` and ``NativeHybrid`` over Weaviate.

    One collection per space, whose objects carry ExactDocs' vectors and the chunk's words.
    """

    alpha: float = WEAVIATE_DEFAULT_ALPHA
    """How much the vector counts in a hybrid query (0: the words alone, 1: the vector alone)."""
    fusion: HybridFusion = HybridFusion.RELATIVE_SCORE
    """How Weaviate fuses the two rankings of a hybrid query."""

    def _space(self, space_id: EmbeddingSpaceId) -> str:
        """Return a space's collection.

        Args:
            space_id: The space.

        Returns:
            Its collection's name.
        """
        return self._named(f"{WEAVIATE_SPACE_SUFFIX}{space_id}")

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' objects in the space's collection (created when missing).

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        del manifest  # every entry names its manifest
        objects = [
            DataObject(
                properties=_properties(e),
                uuid=object_id(e.manifest_id, e.chunk_id),
                vector={WEAVIATE_VECTOR_NAME: [float(v) for v in e.vector]},
            )
            for e in entries
            if e.vector is not None
        ]
        if not objects:
            return
        collection = self._space(space.id)
        await self._ensure(collection, _distance(space.spec.metric))
        await self._insert(collection, objects)

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some objects of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        collection = self._space(space_id)
        if not chunk_ids or not await self._exists(collection):
            return
        where = Filter.by_id().contains_any([object_id(manifest_id, c) for c in chunk_ids])
        await self._delete(collection, where)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every object of these versions, in every space's collection.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        where = Filter.by_property("manifest_id").contains_any(list(manifest_ids))
        for collection in await self._spaces():
            await self._delete(collection, where)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Delete a space's collection; nothing happens for an unknown space.

        Args:
            space_id: The space.
        """
        collection = self._space(space_id)
        await self._call(self._open().collections.delete(collection))
        self._known.discard(collection)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """Count the space's objects per version.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held; empty for an unknown space.
        """
        return await self._held(self._space(space_id), library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Find the versions' objects nearest to the query vector (Weaviate's ``near_vector``).

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest objects with their cosine distances, nearest first; ties by chunk ID.
        """
        if not manifest_ids or limit < 1:
            return []
        found = await self._query(
            self._space(space.id),
            lambda handle: handle.query.near_vector(
                [float(v) for v in query],
                filters=_filter(manifest_ids, tag_filter),
                limit=limit + WEAVIATE_TIE_MARGIN,
                return_metadata=MetadataQuery(distance=True),
                return_properties=list(WEAVIATE_RETURNED),
            ),
            None,
        )
        if found is None:
            return []
        wanted = set(manifest_ids)
        hits = [
            BackendNeighbour(
                manifest_id=str(o.properties["manifest_id"]),
                chunk_id=ChunkId(str(o.properties["chunk_id"])),
                distance=max(0.0, float(o.metadata.distance or 0.0)),
            )
            for o in found.objects
            if o.properties.get("manifest_id") in wanted
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits[:limit]

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Rank the versions' objects by their words (BM25) and vectors in one hybrid query.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms (a query without terms ranks by its vector alone).
            vector: The query's vector.
            tag_filter: Which chunks may be returned; applied to both halves.
            limit: The most hits.

        Returns:
            The fused hits, best first.
        """
        if not manifest_ids or limit < 1:
            return []
        if not query.terms:
            near = await self.nearest(space, manifest_ids, vector, tag_filter, limit)
            return [
                BackendHit(manifest_id=n.manifest_id, chunk_id=n.chunk_id, score=1.0 - n.distance)
                for n in near
            ]
        found = await self._query(
            self._space(space.id),
            lambda handle: handle.query.hybrid(
                " ".join(query.terms),
                vector=[float(v) for v in vector],
                alpha=self.alpha,
                fusion_type=self.fusion,
                query_properties=_boosted(),
                filters=_filter(manifest_ids, tag_filter),
                limit=limit + WEAVIATE_TIE_MARGIN,
                return_metadata=MetadataQuery(score=True),
                return_properties=list(WEAVIATE_RETURNED),
            ),
            None,
        )
        return [] if found is None else _hits(found.objects, set(manifest_ids), limit)

    async def _spaces(self) -> list[str]:
        """List the spaces' collections this instance's prefix names.

        Returns:
            Their names.
        """
        prefix = self._named(WEAVIATE_SPACE_SUFFIX)
        found = await self._call(self._open().collections.list_all(simple=True))
        return [
            name
            for name in found
            if name.startswith(prefix) and name.removeprefix(prefix).isdigit()
        ]


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


@dataclass(frozen=True, slots=True, kw_only=True)
class _Endpoint:
    """Where a Weaviate API listens."""

    host: str
    """The host name or address."""
    port: int
    """The port."""
    secure: bool
    """Whether it speaks TLS (``https``)."""


def _endpoint(option: str, url: str, default_port: int | None) -> _Endpoint:
    """Read an ``http(s)://host[:port]`` option.

    Args:
        option: The option's name, for messages.
        url: Its value.
        default_port: The port when none is given; ``None``: 443 for https, 8080 for http.

    Returns:
        The endpoint.

    Raises:
        ValueError: It is not such a URL.
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        message = f"{option} must be http(s)://host[:port] (got {url!r})"
        raise ValueError(message)
    secure = parts.scheme == "https"
    try:
        port = parts.port
    except ValueError as error:
        message = f"{option} has an invalid port (got {url!r})"
        raise ValueError(message) from error
    if port is None:
        port = default_port if default_port is not None else (443 if secure else 8080)
    return _Endpoint(host=parts.hostname, port=port, secure=secure)


def _grpc(options: Mapping[str, object], http: _Endpoint) -> _Endpoint:
    """Read ``grpc_url``, or derive it: Weaviate Cloud's ``grpc-<host>:443``, else port 50051.

    Args:
        options: The options.
        http: The REST endpoint.

    Returns:
        The gRPC endpoint.
    """
    given = str(options.get("grpc_url") or "").strip()
    if given:
        return _endpoint("grpc_url", given, 443 if given.startswith("https") else 50051)
    if http.secure and http.host.endswith((".weaviate.cloud", ".weaviate.network")):
        return _Endpoint(host=f"grpc-{http.host}", port=443, secure=True)
    return _Endpoint(host=http.host, port=WEAVIATE_DEFAULT_GRPC_PORT, secure=http.secure)


def _number(options: Mapping[str, object], name: str, default: float) -> float:
    """Read a number option (TOML numbers, or text from the environment).

    Args:
        options: The options.
        name: The option.
        default: Its value when unset.

    Returns:
        The number.

    Raises:
        ValueError: It is not a number.
    """
    value = options.get(name, default)
    try:
        return float(str(value))
    except ValueError:
        message = f"{name} must be a number (got {value!r})"
        raise ValueError(message) from None


@dataclass(frozen=True, slots=True, kw_only=True)
class _Options:
    """The validated ``[index_backends.weaviate]`` options both backends are built from."""

    connect: Connect
    """Makes a client of the configured server."""
    collection: str
    """The collections' prefix."""
    alpha: float
    """Native hybrid's weight of the vector."""
    fusion: HybridFusion
    """Native hybrid's fusion algorithm."""


def _options(options: Mapping[str, object]) -> _Options:
    """Validate the options and make the client factory.

    Options: ``url`` (required: the REST endpoint ``http(s)://host[:port]``, port 8080 or 443
    when none), ``grpc_url`` (the gRPC endpoint; the same host on port 50051 by default, or
    Weaviate Cloud's ``grpc-<host>:443``), ``collection`` (the collections' prefix,
    ``ExactDocs``), ``api_key`` (from the environment only) or ``api_key_file``, ``timeout``
    (seconds, 10), ``alpha`` (native hybrid's weight of the vector, 0.5) and ``fusion``
    (``relative_score`` or ``ranked``).

    Args:
        options: The options.

    Returns:
        What the backends are built from.

    Raises:
        ValueError: An option is unknown, missing or invalid.
    """
    unknown = sorted(set(options) - WEAVIATE_OPTIONS)
    if unknown:
        known = ", ".join(sorted(WEAVIATE_OPTIONS))
        message = f"unknown options {', '.join(unknown)} (known: {known})"
        raise ValueError(message)
    url = str(options.get("url") or "").strip()
    if not url:
        message = "url is required: the Weaviate server's http(s)://host[:port]"
        raise ValueError(message)
    http = _endpoint("url", url, None)
    grpc = _grpc(options, http)
    collection = str(options.get("collection") or WEAVIATE_DEFAULT_COLLECTION).strip()
    if not WEAVIATE_COLLECTION_NAME.fullmatch(collection):
        message = f"collection {collection!r} must be a letter, then letters, digits and '_'"
        raise ValueError(message)
    timeout = _number(options, "timeout", WEAVIATE_DEFAULT_TIMEOUT_SECONDS)
    if timeout <= 0:
        message = f"timeout must be a positive number of seconds (got {options.get('timeout')!r})"
        raise ValueError(message)
    alpha = _number(options, "alpha", WEAVIATE_DEFAULT_ALPHA)
    if not 0 <= alpha <= 1:
        message = f"alpha must be between 0 and 1 (got {options.get('alpha')!r})"
        raise ValueError(message)
    fusion = str(options.get("fusion") or "relative_score").strip().lower()
    if fusion not in WEAVIATE_FUSIONS:
        message = f"fusion must be relative_score or ranked (got {fusion!r})"
        raise ValueError(message)
    api_key = _api_key(options)

    def connect() -> WeaviateAsyncClient:
        """Make a client of the configured server.

        Returns:
            The client (not connected yet).
        """
        return weaviate.use_async_with_custom(
            http_host=http.host,
            http_port=http.port,
            http_secure=http.secure,
            grpc_host=grpc.host,
            grpc_port=grpc.port,
            grpc_secure=grpc.secure,
            auth_credentials=None if api_key is None else Auth.api_key(api_key),
            additional_config=AdditionalConfig(
                timeout=Timeout(init=WEAVIATE_INIT_TIMEOUT_SECONDS, query=timeout, insert=timeout)
            ),
        )

    return _Options(
        connect=connect,
        collection=collection,
        alpha=alpha,
        fusion=HybridFusion.RANKED if fusion == "ranked" else HybridFusion.RELATIVE_SCORE,
    )


def search_backend(options: Mapping[str, object]) -> WeaviateSearchBackend:
    """Build the Weaviate search backend from its ``[index_backends.weaviate]`` options.

    Args:
        options: The options (see ``_options``).

    Returns:
        The backend, not connected yet.
    """
    built = _options(options)
    return WeaviateSearchBackend(connect=built.connect, collection=built.collection)


def vector_backend(options: Mapping[str, object]) -> WeaviateVectorBackend:
    """Build the Weaviate vector backend (with native hybrid) from its options.

    Args:
        options: The options (see ``_options``).

    Returns:
        The backend, not connected yet.
    """
    built = _options(options)
    return WeaviateVectorBackend(
        connect=built.connect,
        collection=built.collection,
        alpha=built.alpha,
        fusion=built.fusion,
    )
