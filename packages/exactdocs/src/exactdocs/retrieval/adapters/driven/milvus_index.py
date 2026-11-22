"""Milvus as the vector backend (#360): ``EXACTDOCS_VECTOR_BACKEND=milvus``.

Each embedding space is one collection, ``<collection>_space<id>``, created on the space's first
write with the space's dimensions and cosine similarity. A row is one chunk of one version (its
primary key is derived from the manifest and chunk IDs, so writing it again replaces it) with
``manifest_id``, ``library``, ``version_id``, ``chunk_id``, ``article_path`` and ``tags``
fields; ``manifest_id``, ``library`` and ``version_id`` carry a scalar (inverted) index, and so do
the tags on a server. Every search filters on the asked versions' ``manifest_id`` (and the tags)
in Milvus, before ranking, so another version's chunks are never returned.

Native hybrid (``NativeHybrid``, on unless ``hybrid = false``): a row also keeps its words
(``identifier_tokens`` of its headings and text) in an analyzed ``text`` field, which a BM25
function turns into a sparse vector; ``hybrid`` asks Milvus for both halves, sparse BM25 and
dense cosine, fused by Milvus' RRF ranker, in one request.

Two connection modes, from the ``uri`` option: a Milvus server or Zilliz Cloud
(``http(s)://...``, with ``token``: ``user:password`` or an API key, from the environment or
``token_file``), or Milvus Lite, the embedded engine, on a local ``.db`` directory (the
``milvus-lite`` extra). The client is synchronous: each call runs in a worker thread.

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Only this module imports ``pymilvus`` (the ``milvus`` extra) and ``milvus_lite``.
"""

import asyncio
import hashlib
import importlib.util
import json
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pymilvus import (
    AnnSearchRequest,
    CollectionSchema,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    MilvusException,
    RRFRanker,
)
from pymilvus.milvus_client.index import IndexParams

from exactdocs.retrieval.constants import (
    MILVUS_BACKEND,
    MILVUS_COLLECTION_NAME,
    MILVUS_CONSISTENCY_LEVELS,
    MILVUS_DEFAULT_COLLECTION,
    MILVUS_DEFAULT_CONSISTENCY,
    MILVUS_DEFAULT_TIMEOUT_SECONDS,
    MILVUS_DELETE_BATCH,
    MILVUS_HYBRID_DEPTH,
    MILVUS_ID_LENGTH,
    MILVUS_LITE_SUFFIX,
    MILVUS_OPTIONS,
    MILVUS_QUERY_BATCH,
    MILVUS_RETURNED,
    MILVUS_SERVER_SCHEMES,
    MILVUS_SPACE_SUFFIX,
    MILVUS_SPARSE_FIELD,
    MILVUS_TAG_LENGTH,
    MILVUS_TAGS_CAPACITY,
    MILVUS_TEXT_FIELD,
    MILVUS_TEXT_LENGTH,
    MILVUS_TIE_MARGIN,
    MILVUS_TOP_K,
    MILVUS_UPSERT_BATCH,
    MILVUS_VECTOR_FIELD,
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
    identifier_tokens,
)


def row_key(manifest_id: str, chunk_id: str) -> str:
    """Return the primary key of a chunk's row in a version: the same every time it is written.

    Args:
        manifest_id: The version's manifest.
        chunk_id: The chunk.

    Returns:
        64 hex digits (SHA-256), so writing the entry again replaces its row.
    """
    return hashlib.sha256(f"{manifest_id}\n{chunk_id}".encode()).hexdigest()


def _literal(value: str) -> str:
    """Quote a string for a Milvus filter expression (Milvus Lite takes no expression templates).

    Args:
        value: The string.

    Returns:
        A double-quoted literal with backslash escapes, which Milvus and Milvus Lite both read.
    """
    return json.dumps(value, ensure_ascii=False)


def _listed(values: Iterable[str]) -> str:
    """Quote strings as a filter expression's list.

    Args:
        values: The strings.

    Returns:
        ``["a", "b"]``.
    """
    return f"[{', '.join(_literal(v) for v in values)}]"


def _where(manifest_ids: Collection[str], tag_filter: TagFilter) -> str:
    """Return the filter of a search: these versions, and the tags if the filter names any.

    Args:
        manifest_ids: The versions searched.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The filter expression.
    """
    where = f"manifest_id in {_listed(dict.fromkeys(manifest_ids))}"
    if not tag_filter.tags:
        return where
    contains = "ARRAY_CONTAINS_ALL" if tag_filter.match is TagMatch.ALL else "ARRAY_CONTAINS_ANY"
    return f"{where} and {contains}(tags, {_listed(tag_filter.tags)})"


def _words(entry: IndexEntry) -> str:
    """Return the words BM25 ranks an entry by: its headings and text, cut to fit the field.

    Args:
        entry: The entry.

    Returns:
        ``identifier_tokens`` of the heading path and the content, at most
        ``MILVUS_TEXT_LENGTH`` bytes, cut at a word.
    """
    text = identifier_tokens(" ".join((*entry.heading_path, entry.content)))
    encoded = text.encode()
    if len(encoded) <= MILVUS_TEXT_LENGTH:
        return text
    cut = encoded[:MILVUS_TEXT_LENGTH].decode(errors="ignore")
    return cut.rsplit(" ", 1)[0]


def _row(entry: IndexEntry, vector: Sequence[float], *, hybrid: bool) -> dict[str, Any]:
    """Return an entry's row.

    Args:
        entry: The entry.
        vector: Its vector.
        hybrid: The collection keeps the words for BM25.

    Returns:
        The row, by field.
    """
    row: dict[str, Any] = {
        "pk": row_key(entry.manifest_id, entry.chunk_id),
        "manifest_id": entry.manifest_id,
        "library": entry.library,
        "version_id": entry.version_id,
        "chunk_id": str(entry.chunk_id),
        "article_path": entry.article_path,
        "tags": list(entry.tags),
        MILVUS_VECTOR_FIELD: list(vector),
    }
    if hybrid:
        row[MILVUS_TEXT_FIELD] = _words(entry)
    return row


def _reason(error: BaseException) -> str:
    """Say briefly why Milvus did not answer, never with a credential.

    Args:
        error: What the client raised.

    Returns:
        Milvus' error code and message, or the type of the error.
    """
    if isinstance(error, MilvusException):
        return f"{type(error).__name__} {error.code}: {error.message}"[:200]
    return type(error).__name__


def _distance(similarity: float) -> float:
    """Turn Milvus' cosine similarity into the cosine distance the port speaks.

    Args:
        similarity: What Milvus calls the hit's distance with ``COSINE``: higher is nearer.

    Returns:
        ``1 - similarity``, within 0 to 2.
    """
    return min(2.0, max(0.0, 1.0 - similarity))


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class MilvusVectorBackend:
    """Implements ``ports.driven.VectorBackend`` on Milvus (a server, Zilliz Cloud or Lite)."""

    uri: str
    """A server's URI (``http(s)://host:port``), or Milvus Lite's absolute ``.db`` path."""
    token: str | None = field(default=None, repr=False)
    """The server's token (``user:password`` or an API key); ``None`` for none."""
    db_name: str | None = None
    """The Milvus database the collections are in; ``None`` for the default one."""
    collection: str = MILVUS_DEFAULT_COLLECTION
    """The prefix of every collection's name."""
    timeout: float = MILVUS_DEFAULT_TIMEOUT_SECONDS
    """Seconds one call may take."""
    consistency_level: str = MILVUS_DEFAULT_CONSISTENCY
    """The consistency new collections are created with."""
    bm25: bool = False
    """New collections keep the words for BM25 (``MilvusHybridVectorBackend`` sets it)."""
    name: str = MILVUS_BACKEND
    """The registered name."""
    _client: MilvusClient | None = field(default=None, init=False, repr=False)
    """The open client; ``None`` before ``open()`` and after ``close()``."""
    _fields: dict[str, frozenset[str]] = field(default_factory=dict, init=False, repr=False)
    """The fields of each collection seen to exist and loaded, in this process."""
    _setting_up: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    """Lets one task create or load a collection at a time."""

    @property
    def local(self) -> bool:
        """Whether this is Milvus Lite (a local ``.db`` directory) rather than a server."""
        return not self.uri.startswith(MILVUS_SERVER_SCHEMES)

    async def open(self) -> None:
        """Connect and check that Milvus answers (and takes the token)."""
        await self.close()

        def connect() -> MilvusClient:
            """Make the client and ask the server's version (Milvus Lite starts here).

            Returns:
                The connected client.
            """
            if self.local:
                Path(self.uri).parent.mkdir(parents=True, exist_ok=True)
            client = MilvusClient(
                uri=self.uri,
                token=self.token or "",
                db_name=self.db_name or "",
                timeout=self.timeout,
            )
            try:
                client.get_server_version(timeout=self.timeout)
            except BaseException:
                client.close()
                raise
            return client

        self._client = await self._call(connect)
        self._fields.clear()

    async def close(self) -> None:
        """Close the client, if open (and stop Milvus Lite's engine for the directory)."""
        client, self._client = self._client, None
        if client is None:
            return
        await asyncio.to_thread(client.close)
        if self.local:
            await asyncio.to_thread(release_lite, self.uri)

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' rows in the space's collection (created when missing).

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        del manifest  # every entry names its manifest
        with_vectors = [e for e in entries if e.vector is not None]
        if not with_vectors:
            return
        collection = self._space(space.id)
        fields = await self._ensure(collection, space.spec.dimensions)
        hybrid = MILVUS_TEXT_FIELD in fields
        client = self._open()
        for start in range(0, len(with_vectors), MILVUS_UPSERT_BATCH):
            rows = [
                _row(e, e.vector or (), hybrid=hybrid)
                for e in with_vectors[start : start + MILVUS_UPSERT_BATCH]
            ]
            await self._call(
                lambda rows=rows: client.upsert(collection, rows, timeout=self.timeout)
            )

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of one version in one space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        collection = self._space(space_id)
        if not chunk_ids or not await self._exists(collection):
            return
        client = self._open()
        keys = [row_key(manifest_id, c) for c in dict.fromkeys(chunk_ids)]
        for start in range(0, len(keys), MILVUS_DELETE_BATCH):
            batch = keys[start : start + MILVUS_DELETE_BATCH]
            await self._call(
                lambda batch=batch: client.delete(collection, ids=batch, timeout=self.timeout)
            )

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every entry of these versions, in every space's collection.

        Args:
            manifest_ids: The versions.
        """
        wanted = list(dict.fromkeys(manifest_ids))
        if not wanted:
            return
        client = self._open()
        for collection in await self._spaces():
            await self._ensure_loaded(collection)
            for start in range(0, len(wanted), MILVUS_DELETE_BATCH):
                where = f"manifest_id in {_listed(wanted[start : start + MILVUS_DELETE_BATCH])}"
                await self._call(
                    lambda collection=collection, where=where: client.delete(
                        collection, filter=where, timeout=self.timeout
                    )
                )

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Drop a space's collection; nothing to do for an unknown space.

        Args:
            space_id: The space.
        """
        collection = self._space(space_id)
        client = self._open()
        async with self._setting_up:
            self._fields.pop(collection, None)
            if await self._call(lambda: client.has_collection(collection, timeout=self.timeout)):
                await self._call(lambda: client.drop_collection(collection, timeout=self.timeout))

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """Count the space's entries per version (the drift check).

        A server counts them grouped by version in one query; Milvus Lite, which has no grouped
        count (or a server that refuses one), has them read a page at a time.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID; none for an unknown space.
        """
        collection = self._space(space_id)
        if not await self._exists(collection):
            return []
        where = 'manifest_id != ""' if library is None else f"library == {_literal(library)}"
        try:
            counted = await self._grouped(collection, where)
        except IndexBackendUnavailableError:  # a server that refuses grouping: count row by row
            counted = None
        if counted is None:
            counted = await self._counted(collection, where)
        return [
            HeldVersion(manifest_id=m, library=lib, entries=n)
            for (m, lib), n in sorted(counted.items())
            if n
        ]

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Return the versions' entries nearest to the query, filtered in Milvus.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries, nearest first; ties by chunk ID, then manifest ID.
        """
        collection = self._space(space.id)
        if not manifest_ids or limit <= 0 or not await self._exists(collection):
            return []
        client = self._open()
        where = _where(manifest_ids, tag_filter)
        depth = min(MILVUS_TOP_K, limit + MILVUS_TIE_MARGIN)
        found = await self._call(
            lambda: client.search(
                collection,
                data=[[float(v) for v in query]],
                anns_field=MILVUS_VECTOR_FIELD,
                filter=where,
                limit=depth,
                output_fields=list(MILVUS_RETURNED),
                search_params={"metric_type": "COSINE"},
                timeout=self.timeout,
            )
        )
        wanted = set(manifest_ids)
        hits = [
            BackendNeighbour(
                manifest_id=str(hit["entity"]["manifest_id"]),
                chunk_id=ChunkId(str(hit["entity"]["chunk_id"])),
                distance=_distance(float(hit["distance"])),
            )
            for hit in (found[0] if found else [])
            if hit["entity"]["manifest_id"] in wanted
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits[:limit]

    def _open(self) -> MilvusClient:
        """Return the open client.

        Returns:
            The client.

        Raises:
            IndexBackendUnavailableError: ``open()`` was not called, or ``close()`` was.
        """
        if self._client is None:
            raise IndexBackendUnavailableError(self.name, "not open")
        return self._client

    async def _call[T](self, work: Callable[[], T]) -> T:
        """Run one client call in a worker thread, turning any failure into the domain's error.

        Args:
            work: The call.

        Returns:
            What it returned.

        Raises:
            IndexBackendUnavailableError: Milvus did not answer, or answered with an error.
        """
        try:
            return await asyncio.to_thread(work)
        except IndexBackendUnavailableError:
            raise
        except Exception as error:  # the client raises gRPC and plain errors for transport
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error

    def _space(self, space_id: EmbeddingSpaceId) -> str:
        """Return a space's collection name.

        Args:
            space_id: The space.

        Returns:
            ``<collection>_space<id>``.
        """
        return f"{self.collection}{MILVUS_SPACE_SUFFIX}{int(space_id)}"

    async def _spaces(self) -> list[str]:
        """List this backend's collections (one per space).

        Returns:
            Their names.
        """
        client = self._open()
        prefix = f"{self.collection}{MILVUS_SPACE_SUFFIX}"
        names = await self._call(lambda: client.list_collections(timeout=self.timeout))
        return sorted(n for n in names if n.startswith(prefix) and n.removeprefix(prefix).isdigit())

    async def _exists(self, collection: str) -> bool:
        """Tell whether the collection exists; one that does is loaded for searches.

        Args:
            collection: Its name.

        Returns:
            True when it exists.
        """
        if collection in self._fields:
            return True
        return await self._ensure_loaded(collection) is not None

    async def _ensure_loaded(self, collection: str) -> frozenset[str] | None:
        """Load an existing collection (once per process) and learn its fields.

        Args:
            collection: Its name.

        Returns:
            Its fields; ``None`` when it does not exist.
        """
        if (known := self._fields.get(collection)) is not None:
            return known
        client = self._open()
        async with self._setting_up:
            if (known := self._fields.get(collection)) is not None:
                return known
            if not await self._call(
                lambda: client.has_collection(collection, timeout=self.timeout)
            ):
                return None
            described = await self._call(
                lambda: client.describe_collection(collection, timeout=self.timeout)
            )
            await self._call(lambda: client.load_collection(collection, timeout=self.timeout))
            fields = frozenset(str(f["name"]) for f in described["fields"])
            self._fields[collection] = fields
            return fields

    async def _ensure(self, collection: str, dimensions: int) -> frozenset[str]:
        """Return the collection's fields, creating (and loading) it when it does not exist.

        Args:
            collection: Its name.
            dimensions: The space's dimensions.

        Returns:
            Its fields.
        """
        if (fields := await self._ensure_loaded(collection)) is not None:
            return fields
        client = self._open()
        async with self._setting_up:
            if (known := self._fields.get(collection)) is not None:
                return known
            schema = self._schema(dimensions)
            indexes = self._indexes()
            await self._call(
                lambda: client.create_collection(
                    collection,
                    schema=schema,
                    index_params=indexes,
                    consistency_level=self.consistency_level,
                    timeout=self.timeout,
                )
            )
            fields = frozenset(f.name for f in schema.fields)
            self._fields[collection] = fields
            return fields

    def _schema(self, dimensions: int) -> CollectionSchema:
        """Return a new collection's schema.

        Args:
            dimensions: The space's dimensions.

        Returns:
            The schema: the keys, the dense vector and, for hybrid, the BM25 text and function.
        """
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("pk", DataType.VARCHAR, is_primary=True, max_length=64)
        for name in ("manifest_id", "library", "version_id"):
            schema.add_field(name, DataType.VARCHAR, max_length=MILVUS_ID_LENGTH)
        for name in ("chunk_id", "article_path"):
            schema.add_field(name, DataType.VARCHAR, max_length=MILVUS_TEXT_LENGTH)
        schema.add_field(
            "tags",
            DataType.ARRAY,
            element_type=DataType.VARCHAR,
            max_capacity=MILVUS_TAGS_CAPACITY,
            max_length=MILVUS_TAG_LENGTH,
        )
        schema.add_field(MILVUS_VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=dimensions)
        if self.bm25:
            schema.add_field(
                MILVUS_TEXT_FIELD,
                DataType.VARCHAR,
                max_length=MILVUS_TEXT_LENGTH,
                enable_analyzer=True,
                analyzer_params={"tokenizer": "standard", "filter": ["lowercase"]},
            )
            schema.add_field(MILVUS_SPARSE_FIELD, DataType.SPARSE_FLOAT_VECTOR)
            schema.add_function(
                Function(
                    name="bm25",
                    function_type=FunctionType.BM25,
                    input_field_names=[MILVUS_TEXT_FIELD],
                    output_field_names=[MILVUS_SPARSE_FIELD],
                )
            )
        return schema

    def _indexes(self) -> IndexParams:
        """Return a new collection's indexes.

        Returns:
            Cosine on the dense vector (``AUTOINDEX``: Milvus picks it), inverted indexes on the
            version and library keys (and the tags, on a server: Milvus Lite has no array
            index), and BM25's inverted index on the sparse vector for hybrid.
        """
        indexes = MilvusClient.prepare_index_params()
        indexes.add_index(MILVUS_VECTOR_FIELD, index_type="AUTOINDEX", metric_type="COSINE")
        for name in ("manifest_id", "library", "version_id"):
            indexes.add_index(name, index_type="INVERTED")
        if not self.local:
            indexes.add_index("tags", index_type="INVERTED")
        if self.bm25:
            indexes.add_index(
                MILVUS_SPARSE_FIELD, index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"
            )
        return indexes

    async def _grouped(self, collection: str, where: str) -> Counter[tuple[str, str]] | None:
        """Count the matching rows per version with one grouped query (a server).

        Args:
            collection: The collection.
            where: Which rows.

        Returns:
            The counts by (manifest, library); ``None`` when Milvus did not group them (Milvus
            Lite), or there may be more versions than one query returns.
        """
        client = self._open()
        rows = await self._call(
            lambda: client.query(
                collection,
                filter=where,
                output_fields=["manifest_id", "library", "count(*)"],
                group_by_fields=["manifest_id", "library"],
                limit=MILVUS_TOP_K,
                timeout=self.timeout,
            )
        )
        if len(rows) >= MILVUS_TOP_K or any("manifest_id" not in r for r in rows):
            return None
        return Counter(
            {(str(r["manifest_id"]), str(r["library"])): int(r["count(*)"]) for r in rows}
        )

    async def _counted(self, collection: str, where: str) -> Counter[tuple[str, str]]:
        """Count the matching rows per version by reading them a page at a time.

        Args:
            collection: The collection.
            where: Which rows.

        Returns:
            The counts by (manifest, library).
        """
        client = self._open()

        def count() -> Counter[tuple[str, str]]:
            """Read the rows a page at a time, counting them by version.

            Returns:
                The counts by (manifest, library).
            """
            counted: Counter[tuple[str, str]] = Counter()
            pages = client.query_iterator(
                collection,
                batch_size=MILVUS_QUERY_BATCH,
                filter=where,
                output_fields=["manifest_id", "library"],
                timeout=self.timeout,
            )
            try:
                while page := pages.next():
                    counted.update((str(r["manifest_id"]), str(r["library"])) for r in page)
            finally:
                pages.close()
            return counted

        return await self._call(count)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class MilvusHybridVectorBackend(MilvusVectorBackend):
    """``MilvusVectorBackend`` with ``NativeHybrid``: BM25 and dense, fused by Milvus' RRF."""

    bm25: bool = True
    """New collections keep the words for BM25."""

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Rank the versions' entries by BM25 and by the vector, fused by Milvus' RRF ranker.

        Both halves are filtered to the versions (and tags) in Milvus before ranking. A query
        without terms is ranked by its vector alone, with the RRF score of each rank.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The fused hits, best first; ties by chunk ID, then manifest ID.

        Raises:
            IndexBackendUnavailableError: Milvus did not answer, or the collection was created
                without the BM25 field (``hybrid = false``).
        """
        collection = self._space(space.id)
        if not manifest_ids or limit <= 0 or not await self._exists(collection):
            return []
        words = " ".join(query.terms)
        if not words:
            near = await self.nearest(space, manifest_ids, vector, tag_filter, limit)
            return [
                BackendHit(manifest_id=h.manifest_id, chunk_id=h.chunk_id, score=1 / (RRF_K + n))
                for n, h in enumerate(near, start=1)
            ]
        if MILVUS_SPARSE_FIELD not in self._fields.get(collection, frozenset()):
            reason = (
                f"the collection {collection} has no BM25 field (made with hybrid = false): drop "
                "it and run `exactdocs index rebuild`, or set hybrid = false"
            )
            raise IndexBackendUnavailableError(self.name, reason)
        client = self._open()
        where = _where(manifest_ids, tag_filter)
        depth = min(MILVUS_TOP_K, max(limit + MILVUS_TIE_MARGIN, MILVUS_HYBRID_DEPTH))
        halves = [
            AnnSearchRequest(
                data=[words],
                anns_field=MILVUS_SPARSE_FIELD,
                param={"metric_type": "BM25"},
                limit=depth,
                expr=where,
            ),
            AnnSearchRequest(
                data=[[float(v) for v in vector]],
                anns_field=MILVUS_VECTOR_FIELD,
                param={"metric_type": "COSINE"},
                limit=depth,
                expr=where,
            ),
        ]
        found = await self._call(
            lambda: client.hybrid_search(
                collection,
                halves,
                ranker=RRFRanker(RRF_K),
                limit=min(MILVUS_TOP_K, limit + MILVUS_TIE_MARGIN),
                output_fields=list(MILVUS_RETURNED),
                timeout=self.timeout,
            )
        )
        wanted = set(manifest_ids)
        hits = [
            BackendHit(
                manifest_id=str(hit["entity"]["manifest_id"]),
                chunk_id=ChunkId(str(hit["entity"]["chunk_id"])),
                score=float(hit["distance"]),
            )
            for hit in (found[0] if found else [])
            if hit["entity"]["manifest_id"] in wanted
        ]
        hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
        return hits[:limit]


def release_lite(uri: str) -> None:
    """Stop Milvus Lite's engine for a ``.db`` directory, if this process runs one.

    Args:
        uri: The directory, as the backend names it.
    """
    try:
        from milvus_lite.server_manager import (  # ruff: ignore[import-outside-top-level] -- optional extra
            server_manager_instance,
        )
    except ImportError:
        return
    server_manager_instance.release_server(uri)


def _token(options: Mapping[str, object]) -> str | None:
    """Read the token from ``token`` (the environment) or the file ``token_file`` names.

    Args:
        options: The options.

    Returns:
        The token, or ``None`` when neither is set.

    Raises:
        ValueError: Both are set, or the file cannot be read or is empty.
    """
    token, path = options.get("token"), options.get("token_file")
    if token and path:
        message = "set token or token_file, not both"
        raise ValueError(message)
    if path:
        try:
            token = Path(str(path)).expanduser().read_text("utf-8").strip()
        except OSError as error:
            message = f"token_file {str(path)!r} cannot be read ({type(error).__name__})"
            raise ValueError(message) from error
        if not token:
            message = f"token_file {str(path)!r} is empty"
            raise ValueError(message)
    return (str(token).strip() or None) if token else None


def _flag(options: Mapping[str, object], name: str, *, default: bool) -> bool:
    """Read a true/false option (the environment gives it as text).

    Args:
        options: The options.
        name: The option.
        default: Its value when unset.

    Returns:
        The value.

    Raises:
        ValueError: It is neither true nor false.
    """
    value = options.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    message = f"{name} must be true or false (got {value!r})"
    raise ValueError(message)


def _uri(options: Mapping[str, object]) -> str:
    """Read the ``uri`` option: a server's URI, or a Milvus Lite ``.db`` path made absolute.

    Args:
        options: The options.

    Returns:
        The URI.

    Raises:
        ValueError: It is missing, or a local path that does not end in ``.db``, or Milvus Lite
            is not installed for one.
    """
    raw = str(options.get("uri") or "").strip()
    if not raw:
        message = (
            "uri is required: a Milvus server (http://host:19530), Zilliz Cloud (https://...) "
            "or a Milvus Lite directory (/path/exactdocs.db)"
        )
        raise ValueError(message)
    if raw.startswith(MILVUS_SERVER_SCHEMES):
        return raw.rstrip("/")
    if not raw.endswith(MILVUS_LITE_SUFFIX):
        message = (
            f"uri {raw!r} is neither a server (http://, https://) nor a Milvus Lite path "
            f"ending in {MILVUS_LITE_SUFFIX}"
        )
        raise ValueError(message)
    if importlib.util.find_spec("milvus_lite") is None:
        message = (
            "a Milvus Lite uri needs the milvus-lite extra: pip install 'exactdocs[milvus-lite]'"
        )
        raise ValueError(message)
    return str(Path(raw).expanduser().resolve())


def _backend_options(options: Mapping[str, object]) -> dict[str, Any]:
    """Check the ``[index_backends.milvus]`` options and turn them into the backend's fields.

    Args:
        options: The options.

    Returns:
        The backend's keyword arguments.

    Raises:
        ValueError: An option is unknown or invalid.
    """
    unknown = sorted(set(options) - MILVUS_OPTIONS)
    if unknown:
        known = ", ".join(sorted(MILVUS_OPTIONS))
        message = f"unknown option(s) {', '.join(unknown)} (known: {known})"
        raise ValueError(message)
    uri = _uri(options)
    collection = str(options.get("collection") or MILVUS_DEFAULT_COLLECTION).strip()
    if not MILVUS_COLLECTION_NAME.fullmatch(collection):
        message = (
            f"collection {collection!r} must be letters, digits and _ (not starting with a "
            "digit), at most 200 characters"
        )
        raise ValueError(message)
    token = _token(options)
    if token and not uri.startswith(MILVUS_SERVER_SCHEMES):
        message = "token is for a Milvus server or Zilliz Cloud: Milvus Lite (a .db path) has none"
        raise ValueError(message)
    try:
        timeout = float(str(options.get("timeout", MILVUS_DEFAULT_TIMEOUT_SECONDS)))
    except ValueError as error:
        message = f"timeout must be a number of seconds (got {options.get('timeout')!r})"
        raise ValueError(message) from error
    if not timeout > 0:
        message = f"timeout must be more than 0 seconds (got {timeout:g})"
        raise ValueError(message)
    raw_level = str(options.get("consistency_level") or MILVUS_DEFAULT_CONSISTENCY).strip()
    level = next((c for c in MILVUS_CONSISTENCY_LEVELS if c.lower() == raw_level.lower()), None)
    if level is None:
        known = ", ".join(sorted(MILVUS_CONSISTENCY_LEVELS))
        message = f"consistency_level {raw_level!r} is not one of {known}"
        raise ValueError(message)
    db_name = str(options.get("db_name") or "").strip() or None
    return {
        "uri": uri,
        "token": token,
        "db_name": db_name,
        "collection": collection,
        "timeout": timeout,
        "consistency_level": level,
    }


def vector_backend(options: Mapping[str, object]) -> MilvusVectorBackend:
    """Build the vector backend from its ``[index_backends.milvus]`` options (no connection yet).

    Options: ``uri`` (required: ``http://host:19530``, ``https://...`` for Zilliz Cloud, or a
    Milvus Lite ``/path/name.db``), ``collection`` (the collections' prefix, ``exactdocs``),
    ``token`` or ``token_file`` (a server's ``user:password`` or API key; ``token`` from the
    environment only), ``db_name``, ``timeout`` (seconds, 30), ``hybrid`` (native BM25 and
    dense hybrid, ``true``) and ``consistency_level`` (``Strong``).

    Args:
        options: The options.

    Returns:
        The backend: with ``NativeHybrid`` unless ``hybrid = false``.
    """
    fields = _backend_options(options)
    if _flag(options, "hybrid", default=True):
        return MilvusHybridVectorBackend(**fields)
    return MilvusVectorBackend(**fields)
