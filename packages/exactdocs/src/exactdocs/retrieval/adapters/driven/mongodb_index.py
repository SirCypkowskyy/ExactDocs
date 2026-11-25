"""MongoDB (Atlas Search and Atlas Vector Search) as the search and vector backend (#363).

``EXACTDOCS_SEARCH_BACKEND=mongodb`` / ``EXACTDOCS_VECTOR_BACKEND=mongodb``. Every entry is one
document, ``_id`` ``{manifest_id, chunk_id}``: in the ``collection`` option's collection for the
full-text index, and in ``<collection>.space<id>`` for an embedding space. Each document carries
``manifest_id``, ``library``, ``version_id``, ``chunk_id`` and ``tags``, and the chunk's words as
``identifier_tokens`` (whole identifiers and their parts) in three fields weighted as the
database's indexes weigh them (the section's heading, its ancestors, its text). A space's
documents carry the vector too, as BSON float32.

The search indexes are created on the first write when missing, and the write waits until they
are queryable: an Atlas Search index (``$search``, BM25) over the words, with the five fields as
``token`` fields; an Atlas Vector Search index (``$vectorSearch``, cosine) per space, with them as
``filter`` fields. Every query filters on the asked versions' ``manifest_id`` (and the tags) in
MongoDB, before ranking, so another version's chunks are never returned. The search indexes
follow the collection a moment behind (``mongot`` reads its change stream), so every write marks
its documents (``write_id``) and returns once the indexes return them (a delete: once they no
longer do).

With the ``hybrid`` option (on by default) a space's documents carry the words too, with an Atlas
Search index of their own, and ``hybrid`` is one ``$rankFusion`` stage (reciprocal rank fusion of
``$search`` and ``$vectorSearch``, MongoDB 8.1 or later); on a server without it, the backend runs
both and fuses them with ExactDocs' own reciprocal rank fusion.

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Its client, ``pymongo`` (its async API), is the ``mongodb`` extra; only this module imports it.
"""

import asyncio
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from bson.binary import Binary, BinaryVectorDtype
from pymongo import AsyncMongoClient, ReplaceOne
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import (
    CollectionInvalid,
    ConfigurationError,
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)
from pymongo.operations import SearchIndexModel

from exactdocs.retrieval.constants import (
    HEADING_WEIGHT,
    MONGODB_ANALYZER,
    MONGODB_AUTH_FAILED,
    MONGODB_BACKEND,
    MONGODB_CANDIDATES_FACTOR,
    MONGODB_DEFAULT_COLLECTION,
    MONGODB_DEFAULT_DATABASE,
    MONGODB_DEFAULT_INDEX_TIMEOUT_SECONDS,
    MONGODB_DEFAULT_TIMEOUT_SECONDS,
    MONGODB_FALSE,
    MONGODB_FILTER_FIELDS,
    MONGODB_INDEX_EXISTS,
    MONGODB_MAX_CANDIDATES,
    MONGODB_MIN_CANDIDATES,
    MONGODB_NAME,
    MONGODB_OPTIONS,
    MONGODB_POLL_SECONDS,
    MONGODB_SEARCH_INDEX,
    MONGODB_SPACE,
    MONGODB_TEXT_FIELDS,
    MONGODB_TIE_MARGIN,
    MONGODB_TRUE,
    MONGODB_UNAUTHORIZED,
    MONGODB_UNKNOWN_STAGE,
    MONGODB_URL_SECRETS,
    MONGODB_VECTOR_INDEX,
    MONGODB_VECTOR_SEARCH,
    MONGODB_WRITE_BATCH,
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
    TagFilter,
    TagMatch,
    TextQuery,
    VectorMetric,
    as_float32,
    fuse_across_manifests,
    identifier_tokens,
)
from exactdocs_kernel import OutboundNetwork

logger = logging.getLogger(__name__)

type Document = dict[str, Any]
type Connect = Callable[[], AsyncMongoClient[Document]]


def _text_fields(entry: IndexEntry) -> Document:
    """Return an entry's three text fields: its heading, the headings above, its text.

    Args:
        entry: The entry.

    Returns:
        The fields, each the text's ``identifier_tokens``.
    """
    heading = entry.heading_path[-1] if entry.heading_path else ""
    return {
        "heading": identifier_tokens(heading),
        "path": identifier_tokens(" / ".join(entry.heading_path[:-1])),
        "body": identifier_tokens(entry.content),
    }


def _document(entry: IndexEntry, write_id: str) -> Document:
    """Return the document of an entry, without its words or vector.

    Args:
        entry: The entry.
        write_id: The mark of the write that puts it.

    Returns:
        The document.
    """
    return {
        "_id": {"manifest_id": entry.manifest_id, "chunk_id": entry.chunk_id},
        "manifest_id": entry.manifest_id,
        "library": entry.library,
        "version_id": entry.version_id,
        "chunk_id": entry.chunk_id,
        "article_path": entry.article_path,
        "tags": list(entry.tags),
        "write_id": write_id,
    }


def _vector(values: Sequence[float]) -> Binary:
    """Pack a vector as BSON float32 (a quarter of an array of doubles' size).

    Args:
        values: The values.

    Returns:
        The BSON vector.
    """
    return Binary.from_vector(list(as_float32(values)), BinaryVectorDtype.FLOAT32)


def _search_definition() -> Document:
    """Return the Atlas Search index definition: the words, and the filter fields as tokens.

    Returns:
        The definition.
    """
    words = {
        "type": "string",
        "analyzer": MONGODB_ANALYZER,
        "searchAnalyzer": MONGODB_ANALYZER,
        "indexOptions": "freqs",
        "store": False,
    }
    fields: Document = {name: dict(words) for name in MONGODB_TEXT_FIELDS}
    fields |= {name: {"type": "token"} for name in MONGODB_FILTER_FIELDS}
    return {"mappings": {"dynamic": False, "fields": fields}}


def _vector_definition(dimensions: int) -> Document:
    """Return the Atlas Vector Search index definition of a space.

    Args:
        dimensions: The space's dimensions.

    Returns:
        The definition: the vector (cosine) and the filter fields.
    """
    vector = {"type": "vector", "path": "vector", "numDimensions": dimensions}
    return {
        "fields": [
            vector | {"similarity": "cosine"},
            *({"type": "filter", "path": name} for name in MONGODB_FILTER_FIELDS),
        ]
    }


def _dimensions(index: Document) -> int | None:
    """Read the dimensions of an existing vector index.

    Args:
        index: The index, as ``list_search_indexes`` gives it.

    Returns:
        Its vector field's dimensions, or ``None`` when it has none.
    """
    definition = index.get("latestDefinition") or index.get("definition") or {}
    for spec in definition.get("fields", []):
        if spec.get("type") == "vector":
            return int(spec.get("numDimensions", 0))
    return None


def _search_filter(manifest_ids: Collection[str], tag_filter: TagFilter) -> list[Document]:
    """Return the ``$search`` filter clauses: these versions, and the tags.

    Args:
        manifest_ids: The versions.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The clauses, for a ``compound`` operator's ``filter``.
    """
    clauses: list[Document] = [{"in": {"path": "manifest_id", "value": list(manifest_ids)}}]
    if tag_filter.tags and tag_filter.match is TagMatch.ALL:
        clauses += [{"equals": {"path": "tags", "value": tag}} for tag in tag_filter.tags]
    elif tag_filter.tags:
        clauses.append({"in": {"path": "tags", "value": list(tag_filter.tags)}})
    return clauses


def _words(manifest_ids: Collection[str], terms: Sequence[str], tag_filter: TagFilter) -> Document:
    """Return the ``compound`` operator matching any term, in these versions only.

    Each term is analysed as the fields were (whitespace only): it is never parsed as syntax.

    Args:
        manifest_ids: The versions.
        terms: The query's terms (alternatives).
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The operator.
    """
    should = [
        {"text": {"query": list(terms), "path": name, "score": {"boost": {"value": weight}}}}
        for name, weight in zip(
            MONGODB_TEXT_FIELDS, (HEADING_WEIGHT, PATH_WEIGHT, TEXT_WEIGHT), strict=True
        )
    ]
    return {
        "compound": {
            "filter": _search_filter(manifest_ids, tag_filter),
            "should": should,
            "minimumShouldMatch": 1,
        }
    }


def _vector_filter(manifest_ids: Collection[str], tag_filter: TagFilter) -> Document:
    """Return the ``$vectorSearch`` pre-filter: these versions, and the tags.

    Args:
        manifest_ids: The versions.
        tag_filter: Which chunks may be returned.

    Returns:
        The filter (MQL).
    """
    clauses: list[Document] = [{"manifest_id": {"$in": list(manifest_ids)}}]
    if tag_filter.tags and tag_filter.match is TagMatch.ALL:
        clauses += [{"tags": {"$eq": tag}} for tag in tag_filter.tags]
    elif tag_filter.tags:
        clauses.append({"tags": {"$in": list(tag_filter.tags)}})
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _hit(row: Document, score: str = "score") -> BackendHit:
    """Make a hit of an aggregation's row.

    Args:
        row: The row: ``manifest_id``, ``chunk_id`` and a score.
        score: The score's field.

    Returns:
        The hit.
    """
    return BackendHit(
        manifest_id=str(row["manifest_id"]),
        chunk_id=ChunkId(str(row["chunk_id"])),
        score=float(row[score]),
    )


def _ranked(hits: Sequence[BackendHit], limit: int) -> list[BackendHit]:
    """Order hits best first, ties by chunk ID then manifest ID, and cut at the limit.

    Args:
        hits: The hits.
        limit: The most hits.

    Returns:
        The hits.
    """
    return sorted(hits, key=lambda h: (-h.score, h.chunk_id, h.manifest_id))[:limit]


def _short(error: BaseException, hidden: Collection[str]) -> str:
    """Return an error's message on one line, cut at 200 characters, without any secret.

    Args:
        error: The error.
        hidden: The secrets (the password) never to repeat.

    Returns:
        The message.
    """
    text = " ".join(str(error).split())
    for secret in hidden:
        text = text.replace(secret, "***")
    return text[:200]


def _reason(error: BaseException, hidden: Collection[str]) -> str:
    """Say briefly why MongoDB did not answer, never with a credential.

    Args:
        error: What the client raised.
        hidden: The secrets never to repeat.

    Returns:
        The kind of failure, with the server's own message for a refused command.
    """
    if isinstance(error, OperationFailure) and error.code == MONGODB_AUTH_FAILED:
        return "authentication failed: check the user and password"
    if isinstance(error, OperationFailure) and error.code == MONGODB_UNAUTHORIZED:
        return f"permission denied ({_short(error, hidden)})"
    if isinstance(error, ServerSelectionTimeoutError):
        return f"no server answered ({_short(error, hidden)})"
    if isinstance(error, ExecutionTimeout | NetworkTimeout):
        return f"timed out ({type(error).__name__})"
    if isinstance(error, ConfigurationError):
        return f"invalid connection string or options ({_short(error, hidden)})"
    return f"{type(error).__name__}: {_short(error, hidden)}"


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class _MongoIndex:
    """What both backends share: the client, the collections, the index waits."""

    connect: Connect
    """Makes a client of the configured server (no connection made yet)."""
    database: str
    """The ``database`` option."""
    collection: str
    """The ``collection`` option: the search collection, and the spaces' collections' prefix."""
    index_timeout: float
    """The ``index_timeout`` option, in seconds."""
    hidden: tuple[str, ...] = field(default=(), repr=False)
    """The secrets (the password) no message ever repeats; never in the ``repr``."""
    name: str = MONGODB_BACKEND
    """The registered name."""
    _client: AsyncMongoClient[Document] | None = field(default=None, init=False)
    """The client, from ``open`` to ``close``."""

    async def open(self) -> None:
        """Connect and check the server answers (a ``ping``).

        Raises:
            IndexBackendUnavailableError: The connection string is invalid, or the server does
                not answer or refuses the credentials.
        """
        try:
            self._client = self.connect()
        except PyMongoError as error:
            raise IndexBackendUnavailableError(self.name, _reason(error, self.hidden)) from error
        await self._call(self._client.admin.command("ping"))

    async def close(self) -> None:
        """Release the client."""
        if self._client is not None:
            client, self._client = self._client, None
            await client.close()

    @property
    def _db(self) -> AsyncDatabase[Document]:
        """The database.

        Raises:
            IndexBackendUnavailableError: The backend was not opened.
        """
        if self._client is None:
            raise IndexBackendUnavailableError(self.name, "not opened")
        return self._client[self.database]

    async def _call[T](self, call: Awaitable[T]) -> T:
        """Await a client call, turning its failures into the port's error.

        Args:
            call: The call.

        Returns:
            Its result.

        Raises:
            IndexBackendUnavailableError: The server did not answer or refused it.
        """
        try:
            return await call
        except PyMongoError as error:
            raise IndexBackendUnavailableError(self.name, _reason(error, self.hidden)) from error

    async def _aggregate(self, collection: str, pipeline: list[Document]) -> list[Document]:
        """Run an aggregation and read every row.

        Args:
            collection: The collection.
            pipeline: The stages.

        Returns:
            The rows; none for a collection that does not exist.
        """

        async def rows() -> list[Document]:
            """Run it.

            Returns:
                The rows.
            """
            cursor = await self._db[collection].aggregate(pipeline)
            return [dict(row) for row in await cursor.to_list()]

        return await self._call(rows())

    async def _ensure(
        self,
        collection: str,
        wanted: Mapping[str, tuple[str, Document]],
        check: Callable[[str, Document], None],
    ) -> None:
        """Make the collection and its search indexes when missing, and wait until queryable.

        Args:
            collection: The collection.
            wanted: Each index's type (``search``, ``vectorSearch``) and definition, by name.
            check: Refuses an existing index that cannot serve (its name and description).

        Raises:
            IndexBackendUnavailableError: The server refused, or the indexes did not become
                queryable within ``index_timeout``.
        """
        target = self._db[collection]
        existing = await self._indexes(target)
        for name in wanted.keys() & existing.keys():
            check(name, existing[name])
        missing = [n for n in wanted if n not in existing]
        if missing:
            await self._prepare(collection)
            models = [
                SearchIndexModel(definition=wanted[n][1], name=n, type=wanted[n][0])
                for n in missing
            ]
            try:
                await target.create_search_indexes(models)
            except OperationFailure as error:
                if error.code != MONGODB_INDEX_EXISTS:  # another write made it first
                    reason = _reason(error, self.hidden)
                    raise IndexBackendUnavailableError(self.name, reason) from error
            except PyMongoError as error:
                raise IndexBackendUnavailableError(
                    self.name, _reason(error, self.hidden)
                ) from error
        elif all(existing[n].get("queryable") for n in wanted):
            return

        async def queryable() -> bool:
            """Tell whether every wanted index answers queries.

            Returns:
                True when they all do.

            Raises:
                IndexBackendUnavailableError: An index failed to build.
            """
            found = await self._indexes(target)
            for name in wanted:
                if found.get(name, {}).get("status") == "FAILED":
                    message = f"the search index {name!r} of {collection!r} failed to build"
                    raise IndexBackendUnavailableError(self.name, message)
            return all(found.get(n, {}).get("queryable") for n in wanted)

        await self._until(queryable, f"the search indexes of {collection!r}")

    async def _prepare(self, collection: str) -> None:
        """Create the collection (a search index needs one) and its lookup indexes.

        Args:
            collection: The collection.

        Raises:
            IndexBackendUnavailableError: The server refused.
        """
        try:
            await self._db.create_collection(collection, check_exists=True)
        except CollectionInvalid:
            pass  # already there
        except PyMongoError as error:
            raise IndexBackendUnavailableError(self.name, _reason(error, self.hidden)) from error
        target = self._db[collection]
        await self._call(target.create_index([("manifest_id", 1), ("chunk_id", 1)]))
        await self._call(target.create_index([("library", 1), ("manifest_id", 1)]))

    async def _indexes(self, target: AsyncCollection[Document]) -> dict[str, Document]:
        """List a collection's search indexes.

        Args:
            target: The collection.

        Returns:
            Each index's description, by name; none for a collection that does not exist.
        """

        async def listed() -> list[Document]:
            """List them.

            Returns:
                The descriptions.
            """
            cursor = await target.list_search_indexes()
            return [dict(index) for index in await cursor.to_list()]

        return {str(i["name"]): i for i in await self._call(listed())}

    async def _until(self, done: Callable[[], Awaitable[bool]], what: str) -> None:
        """Wait until ``done`` says so, looking less and less often, up to ``index_timeout``.

        Args:
            done: Tells whether the wait is over.
            what: What is waited for, for the error.

        Raises:
            IndexBackendUnavailableError: It did not happen in time.
        """
        deadline = time.monotonic() + self.index_timeout
        pause, longest = MONGODB_POLL_SECONDS
        while not await done():
            if time.monotonic() >= deadline:
                message = f"{what} did not catch up within {self.index_timeout:g} s"
                raise IndexBackendUnavailableError(self.name, message)
            await asyncio.sleep(pause)
            pause = min(pause * 2, longest)

    async def _write(self, collection: str, documents: Sequence[Document]) -> None:
        """Add or replace documents, by ``_id``.

        Args:
            collection: The collection.
            documents: The documents.
        """
        target = self._db[collection]
        for start in range(0, len(documents), MONGODB_WRITE_BATCH):
            batch = documents[start : start + MONGODB_WRITE_BATCH]
            replaced = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in batch]
            await self._call(target.bulk_write(replaced, ordered=False))

    async def _delete(self, collection: str, where: Document) -> None:
        """Delete the documents that match.

        Args:
            collection: The collection.
            where: The filter (MQL).
        """
        await self._call(self._db[collection].delete_many(where))

    async def _text_count(self, collection: str, operator: Document) -> int:
        """Count what the collection's search index returns for an operator.

        Args:
            collection: The collection.
            operator: The ``$searchMeta`` operator.

        Returns:
            The exact count.
        """
        meta = {"index": MONGODB_SEARCH_INDEX, "count": {"type": "total"}} | operator
        rows = await self._aggregate(collection, [{"$searchMeta": meta}])
        return int(rows[0]["count"]["total"]) if rows else 0

    async def _held(self, collection: str, library: str | None) -> list[HeldVersion]:
        """Count a collection's documents per version (in the collection itself, not an index).

        Args:
            collection: The collection.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID.
        """
        where = [{"$match": {"library": library}}] if library is not None else []
        group = {"_id": "$manifest_id", "library": {"$first": "$library"}, "n": {"$sum": 1}}
        rows = await self._aggregate(collection, [*where, {"$group": group}, {"$sort": {"_id": 1}}])
        return [
            HeldVersion(manifest_id=str(r["_id"]), library=str(r["library"]), entries=int(r["n"]))
            for r in rows
        ]

    async def _search(
        self,
        collection: str,
        manifest_ids: Sequence[str],
        terms: Sequence[str],
        tag_filter: TagFilter,
        limit: int,
    ) -> list[BackendHit]:
        """Rank a collection's matching documents with BM25, best first.

        Ties are ordered by chunk ID, then manifest ID, by the search index itself.

        Args:
            collection: The collection.
            manifest_ids: The versions searched.
            terms: The query's terms.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits.
        """
        if not manifest_ids or not terms or limit < 1:
            return []
        order = {"score": {"$meta": "searchScore", "order": -1}, "chunk_id": 1, "manifest_id": 1}
        stage = {"index": MONGODB_SEARCH_INDEX, "sort": order} | _words(
            manifest_ids, terms, tag_filter
        )
        shown = {"_id": 0, "manifest_id": 1, "chunk_id": 1, "score": {"$meta": "searchScore"}}
        rows = await self._aggregate(
            collection, [{"$search": stage}, {"$limit": limit}, {"$project": shown}]
        )
        return [_hit(r) for r in rows]


def _no_check(name: str, index: Document) -> None:
    """Accept any existing full-text index.

    Args:
        name: The index.
        index: Its description.
    """
    del name, index


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class MongoSearchBackend(_MongoIndex):
    """Implements ``ports.driven.SearchBackend`` over Atlas Search: BM25 on weighted fields."""

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries' documents, and wait until the search index returns them.

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        del manifest  # every entry names its manifest
        if not entries:
            return
        wanted = {MONGODB_SEARCH_INDEX: ("search", _search_definition())}
        await self._ensure(self.collection, wanted, _no_check)
        write_id = secrets.token_hex(8)
        documents = {
            (e.manifest_id, e.chunk_id): _document(e, write_id) | _text_fields(e) for e in entries
        }
        await self._write(self.collection, list(documents.values()))
        marked = {"equals": {"path": "write_id", "value": write_id}}

        async def returned() -> bool:
            """Tell whether the search index returns every document written.

            Returns:
                True when it does.
            """
            return await self._text_count(self.collection, marked) >= len(documents)

        await self._until(returned, f"the search index of {self.collection!r}")

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every document of these versions, and wait until the index has none of them.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        ids = sorted(manifest_ids)
        await self._delete(self.collection, {"manifest_id": {"$in": ids}})
        theirs = {"in": {"path": "manifest_id", "value": ids}}

        async def gone() -> bool:
            """Tell whether the search index returns none of them.

            Returns:
                True when it returns none.
            """
            return await self._text_count(self.collection, theirs) == 0

        await self._until(gone, f"the search index of {self.collection!r}")

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """Count the documents per version.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self._held(self.collection, library)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' matching documents with BM25, filtered in MongoDB before ranking.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first; ties by chunk ID, then manifest ID.
        """
        return await self._search(self.collection, manifest_ids, query.terms, tag_filter, limit)

    async def count(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the matching documents of each version.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many entries match, by manifest ID; zeros left out.
        """
        if not manifest_ids or not query.terms:
            return {}
        stage = {"index": MONGODB_SEARCH_INDEX} | _words(manifest_ids, query.terms, tag_filter)
        group = {"_id": "$manifest_id", "n": {"$sum": 1}}
        rows = await self._aggregate(self.collection, [{"$search": stage}, {"$group": group}])
        return {str(r["_id"]): n for r in rows if (n := int(r["n"]))}


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class MongoVectorBackend(_MongoIndex):
    """Implements ``ports.driven.VectorBackend`` over Atlas Vector Search, by space."""

    exact: bool = False
    """``vector_search = "exact"``: a full scan of the filtered vectors instead of HNSW."""
    _spaces_dimensions: dict[str, int] = field(default_factory=dict, init=False)
    """The dimensions of each space collection's vector index seen so far, by collection."""

    @property
    def words(self) -> bool:
        """Whether a space's documents carry the words too (native hybrid)."""
        return False

    def _collection(self, space_id: EmbeddingSpaceId) -> str:
        """Name a space's collection.

        Args:
            space_id: The space.

        Returns:
            ``<collection>.space<id>``.
        """
        return f"{self.collection}{MONGODB_SPACE}{space_id}"

    def _wanted(self, dimensions: int) -> dict[str, tuple[str, Document]]:
        """Return the search indexes a space's collection needs.

        Args:
            dimensions: The space's dimensions.

        Returns:
            Each index's type and definition, by name.
        """
        wanted = {MONGODB_VECTOR_INDEX: ("vectorSearch", _vector_definition(dimensions))}
        if self.words:
            wanted[MONGODB_SEARCH_INDEX] = ("search", _search_definition())
        return wanted

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' documents in the space's collection.

        The collection and its search indexes are made when missing; the put returns once the
        indexes return every document written.

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.

        Raises:
            IndexBackendUnavailableError: The space's metric is not cosine, the collection's
                vector index has other dimensions, or the server did not take the entries.
        """
        del manifest  # every entry names its manifest
        if space.spec.metric is not VectorMetric.COSINE:
            message = f"the {space.spec.metric} metric is not supported (cosine only)"
            raise IndexBackendUnavailableError(self.name, message)
        with_vectors = [e for e in entries if e.vector is not None]
        if not with_vectors:
            return
        collection = self._collection(space.id)
        dimensions = space.spec.dimensions

        def check(name: str, index: Document) -> None:
            """Refuse a vector index of other dimensions (another instance's collection).

            Args:
                name: The index.
                index: Its description.

            Raises:
                IndexBackendUnavailableError: Its dimensions are not the space's.
            """
            found = _dimensions(index) if name == MONGODB_VECTOR_INDEX else dimensions
            if found != dimensions:
                message = (
                    f"the collection {collection!r} has a vector index of {found} dimensions, not"
                    f" {dimensions}: set another collection, or drop it"
                )
                raise IndexBackendUnavailableError(self.name, message)

        await self._ensure(collection, self._wanted(dimensions), check)
        self._spaces_dimensions[collection] = dimensions
        write_id = secrets.token_hex(8)
        documents: dict[tuple[str, str], Document] = {}
        for e in with_vectors:
            document = _document(e, write_id) | {"vector": _vector(e.vector or ())}
            documents[e.manifest_id, e.chunk_id] = document | (
                _text_fields(e) if self.words else {}
            )
        await self._write(collection, list(documents.values()))
        marked = {"write_id": {"$eq": write_id}}
        probe = next(iter(documents.values()))["vector"]

        async def returned() -> bool:
            """Tell whether the space's indexes return every document written.

            Returns:
                True when they do.
            """
            found = await self._vector_count(collection, probe, marked, len(documents))
            if found < len(documents):
                return False
            if not self.words:
                return True
            mark = {"equals": {"path": "write_id", "value": write_id}}
            return await self._text_count(collection, mark) >= len(documents)

        await self._until(returned, f"the search indexes of {collection!r}")

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some documents of a version in a space, and wait until its indexes forget them.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        if chunk_ids:
            where = {"manifest_id": manifest_id, "chunk_id": {"$in": sorted(chunk_ids)}}
            await self._forget(self._collection(space_id), where)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every document of these versions in every space.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        where = {"manifest_id": {"$in": sorted(manifest_ids)}}
        for collection in await self._spaces():
            await self._forget(collection, where)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Drop a space's collection, with its search indexes.

        Args:
            space_id: The space.
        """
        collection = self._collection(space_id)
        await self._call(self._db.drop_collection(collection))
        self._spaces_dimensions.pop(collection, None)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """Count the documents per version in a space's collection.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self._held(self._collection(space_id), library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Find the versions' vectors nearest the query, filtered in MongoDB before ranking.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries with their cosine distances; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or limit < 1:
            return []
        wanted = min(limit + MONGODB_TIE_MARGIN, MONGODB_MAX_CANDIDATES)
        stage = self._vector_stage(query, _vector_filter(manifest_ids, tag_filter), wanted)
        shown = {"_id": 0, "manifest_id": 1, "chunk_id": 1, "score": {"$meta": "vectorSearchScore"}}
        rows = await self._aggregate(
            self._collection(space.id), [{"$vectorSearch": stage}, {"$project": shown}]
        )
        # The score of a cosine index is (1 + cosine) / 2: the distance is 2 - 2 * score.
        found = [
            BackendNeighbour(
                manifest_id=str(r["manifest_id"]),
                chunk_id=ChunkId(str(r["chunk_id"])),
                distance=min(2.0, max(0.0, 2.0 - 2.0 * float(r["score"]))),
            )
            for r in rows
        ]
        found.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return found[:limit]

    def _vector_stage(
        self, query: Sequence[float] | Binary, where: Document, limit: int, *, exact: bool = False
    ) -> Document:
        """Build a ``$vectorSearch`` stage.

        Args:
            query: The query's vector.
            where: The pre-filter.
            limit: How many hits.
            exact: A full scan, whatever ``vector_search`` says.

        Returns:
            The stage's body.
        """
        vector = query if isinstance(query, Binary) else _vector(query)
        stage: Document = {
            "index": MONGODB_VECTOR_INDEX,
            "path": "vector",
            "queryVector": vector,
            "limit": limit,
            "filter": where,
        }
        if exact or self.exact:
            return stage | {"exact": True}
        candidates = max(limit * MONGODB_CANDIDATES_FACTOR, MONGODB_MIN_CANDIDATES)
        return stage | {"numCandidates": min(candidates, MONGODB_MAX_CANDIDATES)}

    async def _vector_count(
        self, collection: str, probe: Binary, where: Document, limit: int
    ) -> int:
        """Count what a space's vector index returns for a filter (a full scan of it).

        Args:
            collection: The space's collection.
            probe: Any vector of the space's dimensions.
            where: The pre-filter.
            limit: The most to count.

        Returns:
            How many it returns, at most ``limit``.
        """
        stage = self._vector_stage(probe, where, min(limit, MONGODB_MAX_CANDIDATES), exact=True)
        rows = await self._aggregate(
            collection, [{"$vectorSearch": stage}, {"$project": {"_id": 1}}]
        )
        return len(rows)

    async def _forget(self, collection: str, where: Document) -> None:
        """Delete documents of a space's collection, and wait until its indexes return none.

        Args:
            collection: The space's collection.
            where: The documents (MQL on ``manifest_id`` and ``chunk_id``).
        """
        await self._delete(collection, where)
        dimensions = self._spaces_dimensions.get(collection)
        if dimensions is None:
            found = (await self._indexes(self._db[collection])).get(MONGODB_VECTOR_INDEX)
            dimensions = _dimensions(found) if found is not None else None
        if not dimensions:
            return  # no vector index: nothing to wait for
        self._spaces_dimensions[collection] = dimensions
        probe = _vector([1.0] + [0.0] * (dimensions - 1))
        if "chunk_id" in where:  # some chunks of one version
            text: Document = {
                "compound": {
                    "filter": [
                        {"equals": {"path": "manifest_id", "value": where["manifest_id"]}},
                        {"in": {"path": "chunk_id", "value": where["chunk_id"]["$in"]}},
                    ]
                }
            }
        else:  # whole versions
            text = {"in": {"path": "manifest_id", "value": where["manifest_id"]["$in"]}}

        async def gone() -> bool:
            """Tell whether the space's indexes return none of them.

            Returns:
                True when they return none.
            """
            if await self._vector_count(collection, probe, where, 1):
                return False
            return not self.words or await self._text_count(collection, text) == 0

        await self._until(gone, f"the search indexes of {collection!r}")

    async def _spaces(self) -> list[str]:
        """List the spaces' collections.

        Returns:
            Their names.
        """
        pattern = f"^{re.escape(self.collection + MONGODB_SPACE)}[0-9]+$"
        names = await self._call(
            self._db.list_collection_names(filter={"name": {"$regex": pattern}})
        )
        return sorted(names)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class MongoHybridVectorBackend(MongoVectorBackend):
    """``MongoVectorBackend`` with ``NativeHybrid``: a space's documents carry the words too.

    ``hybrid`` is one ``$rankFusion`` stage where the server has it (MongoDB 8.1 or later, found
    at ``open``); otherwise the backend runs ``$search`` and ``$vectorSearch`` and fuses them
    with ExactDocs' reciprocal rank fusion.
    """

    rank_fusion: bool = field(default=False, init=False)
    """Whether the server has ``$rankFusion`` (asked at ``open``)."""

    @property
    def words(self) -> bool:
        """Whether a space's documents carry the words too: always, here."""
        return True

    async def open(self) -> None:
        """Connect, check the server answers, and ask whether it has ``$rankFusion``.

        Raises:
            IndexBackendUnavailableError: The server does not answer or refuses the credentials.
        """
        await MongoVectorBackend.open(self)
        probe = [{"$rankFusion": {"input": {"pipelines": {"probe": [{"$sort": {"_id": 1}}]}}}}]
        try:
            cursor = await self._db[self.collection].aggregate([*probe, {"$limit": 1}])
            await cursor.to_list()
        except OperationFailure as error:
            if error.code in {MONGODB_UNAUTHORIZED, MONGODB_AUTH_FAILED}:
                reason = _reason(error, self.hidden)
                raise IndexBackendUnavailableError(self.name, reason) from error
            self.rank_fusion = False
            how = "unknown stage" if error.code == MONGODB_UNKNOWN_STAGE else f"code {error.code}"
            logger.info("MongoDB has no $rankFusion (%s): hybrid search fuses in ExactDocs", how)
        except PyMongoError as error:
            raise IndexBackendUnavailableError(self.name, _reason(error, self.hidden)) from error
        else:
            self.rank_fusion = True

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Rank the versions' documents by the query's words and its vector together.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms (may have none: only the vector counts then).
            vector: The query's vector.
            tag_filter: Which chunks may be returned; applied before ranking.
            limit: The most hits.

        Returns:
            The fused hits, best first (reciprocal rank fusion); ties by chunk, then manifest ID.
        """
        if not manifest_ids or limit < 1:
            return []
        depth = max(RRF_DEPTH, limit)
        collection = self._collection(space.id)
        if not self.rank_fusion:
            words = await self._search(collection, manifest_ids, query.terms, tag_filter, depth)
            near = await self.nearest(space, manifest_ids, vector, tag_filter, depth)
            fused = fuse_across_manifests(
                [(h.manifest_id, h.chunk_id) for h in words],
                [(h.manifest_id, h.chunk_id) for h in near],
            )
            return [
                BackendHit(manifest_id=f.manifest_id, chunk_id=f.chunk_id, score=f.score)
                for f in fused[:limit]
            ]
        stage = self._vector_stage(vector, _vector_filter(manifest_ids, tag_filter), depth)
        pipelines: Document = {"vectors": [{"$vectorSearch": stage}]}
        if query.terms:
            words = {"index": MONGODB_SEARCH_INDEX} | _words(manifest_ids, query.terms, tag_filter)
            pipelines["words"] = [{"$search": words}, {"$limit": depth}]
        shown = {"_id": 0, "manifest_id": 1, "chunk_id": 1, "score": {"$meta": "score"}}
        rows = await self._aggregate(
            collection,
            [
                {"$rankFusion": {"input": {"pipelines": pipelines}}},
                {"$limit": limit + MONGODB_TIE_MARGIN},
                {"$project": shown},
            ],
        )
        return _ranked([_hit(r) for r in rows], limit)


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
    if text in MONGODB_TRUE:
        return True
    if text in MONGODB_FALSE:
        return False
    message = f"{name} must be true or false (got {value!r})"
    raise ValueError(message)


def _secret_file(options: Mapping[str, object], name: str) -> str | None:
    """Read the file a ``*_file`` option names (a mounted secret), trimmed.

    Args:
        options: The options.
        name: The option.

    Returns:
        The file's text, or ``None`` when the option is unset.

    Raises:
        ValueError: The file cannot be read or is empty.
    """
    path = str(options.get(name) or "").strip()
    if not path:
        return None
    try:
        text = Path(path).expanduser().read_text("utf-8").strip()
    except OSError as error:
        message = f"{name} {path!r} cannot be read ({type(error).__name__})"
        raise ValueError(message) from error
    if not text:
        message = f"{name} {path!r} is empty"
        raise ValueError(message)
    return text


def _url(options: Mapping[str, object]) -> str:
    """Read the connection string: ``url`` (no secret in it) or the file ``url_file`` names.

    Args:
        options: The options.

    Returns:
        The connection string.

    Raises:
        ValueError: Neither or both are set, it is not ``mongodb://`` / ``mongodb+srv://``, or
            ``url`` holds a password or another secret.
    """
    given = str(options.get("url") or "").strip()
    if bool(given) == bool(str(options.get("url_file") or "").strip()):
        message = (
            "set url (a connection string without a password) or url_file (a file holding the "
            "connection string), one of them"
        )
        raise ValueError(message)
    url = given or _secret_file(options, "url_file") or ""
    parts = urlsplit(url)
    if parts.scheme not in {"mongodb", "mongodb+srv"} or not parts.netloc.rpartition("@")[2]:
        message = "the connection string must be mongodb://host[:port] or mongodb+srv://host"
        raise ValueError(message)
    if given:
        userinfo = parts.netloc.rpartition("@")[0]
        names = [k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)]
        if ":" in userinfo or any(s in k for k in names for s in MONGODB_URL_SECRETS):
            message = (
                "url may not hold a password or another secret: set password (or "
                "password_file), or put the whole connection string in url_file"
            )
            raise ValueError(message)
    return url


def _password(options: Mapping[str, object]) -> str | None:
    """Read the password from ``password`` (the environment) or the file ``password_file`` names.

    Args:
        options: The options.

    Returns:
        The password, or ``None`` when neither is set.

    Raises:
        ValueError: Both are set, or the file cannot be read or is empty.
    """
    given = str(options.get("password") or "").strip() or None
    from_file = _secret_file(options, "password_file")
    if given and from_file:
        message = "set password or password_file, not both"
        raise ValueError(message)
    return given or from_file


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


def _name(options: Mapping[str, object], option: str, default: str) -> str:
    """Read the ``database`` or ``collection`` option.

    Args:
        options: The options.
        option: Which.
        default: Its value when unset.

    Returns:
        The name.

    Raises:
        ValueError: It is not letters, digits, ``_`` and ``-``.
    """
    value = str(options.get(option) or default).strip()
    if not MONGODB_NAME.fullmatch(value):
        message = f"{option} {value!r} must be 1 to 64 letters, digits, '_' and '-'"
        raise ValueError(message)
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class _Settings:
    """The options, checked: what both factories build from."""

    connect: Connect
    """Makes a client of the configured server."""
    database: str
    """The ``database`` option."""
    collection: str
    """The ``collection`` option."""
    index_timeout: int
    """The ``index_timeout`` option, in seconds."""
    hidden: tuple[str, ...] = field(repr=False)
    """The secrets no message repeats; never in the ``repr``."""
    hybrid: bool
    """The ``hybrid`` option."""
    exact: bool
    """``vector_search = "exact"``."""


def _uses_tls(url: str) -> bool:
    """Whether a connection string asks for TLS (``mongodb+srv://`` does by default).

    Args:
        url: The connection string.

    Returns:
        True for ``mongodb+srv://`` without ``tls=false``, or ``tls=true`` / ``ssl=true``.
    """
    query = {k.lower(): v.lower() for k, v in parse_qsl(urlsplit(url).query)}
    asked = query.get("tls", query.get("ssl"))
    if asked is not None:
        return asked == "true"
    return url.lower().startswith("mongodb+srv://")


def _settings(options: Mapping[str, object], network: OutboundNetwork | None) -> _Settings:
    """Check the ``[index_backends.mongodb]`` options.

    Args:
        options: The options.
        network: The outbound settings (#538): their CA bundle checks a TLS server's certificate
            when the options name no CA file. An HTTP proxy does not carry this protocol: the
            server is reached directly.

    Returns:
        What the backends are built from.

    Raises:
        ValueError: An option is unknown, missing or invalid.
    """
    unknown = sorted(set(options) - MONGODB_OPTIONS)
    if unknown:
        known = ", ".join(sorted(MONGODB_OPTIONS))
        message = f"unknown options {', '.join(unknown)} (known: {known})"
        raise ValueError(message)
    url = _url(options)
    username = str(options.get("username") or "").strip() or None
    password = _password(options)
    timeout_ms = _seconds(options, "timeout", MONGODB_DEFAULT_TIMEOUT_SECONDS) * 1000
    search = str(options.get("vector_search") or "approximate").strip().lower()
    if search not in MONGODB_VECTOR_SEARCH:
        message = f"vector_search must be approximate or exact (got {search!r})"
        raise ValueError(message)
    in_url = urlsplit(url).password
    # Only what is set: a None would override the user or password the connection string names.
    credentials: dict[str, Any] = {}
    if username:
        credentials["username"] = username
    if password:
        credentials["password"] = password
    hidden = tuple(s for s in (password, in_url) if s)
    ca_bundle = (network or OutboundNetwork()).ca_bundle
    if ca_bundle is not None and _uses_tls(url) and "tlscafile=" not in url.lower():
        credentials["tlsCAFile"] = ca_bundle

    def connect() -> AsyncMongoClient[Document]:
        """Make a client of the configured server.

        Returns:
            The client (it connects on its first command).
        """
        return AsyncMongoClient(
            url,
            appname="exactdocs",
            timeoutMS=timeout_ms,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms,
            **credentials,
        )

    return _Settings(
        connect=connect,
        database=_name(options, "database", MONGODB_DEFAULT_DATABASE),
        collection=_name(options, "collection", MONGODB_DEFAULT_COLLECTION),
        index_timeout=_seconds(options, "index_timeout", MONGODB_DEFAULT_INDEX_TIMEOUT_SECONDS),
        hidden=hidden,
        hybrid=_switch(options, "hybrid", default=True),
        exact=search == "exact",
    )


def search_backend(
    options: Mapping[str, object], *, network: OutboundNetwork | None = None
) -> MongoSearchBackend:
    """Build the MongoDB search backend from its ``[index_backends.mongodb]`` options.

    Options: ``url`` (a ``mongodb://`` or ``mongodb+srv://`` connection string without a
    password) or ``url_file`` (a file holding the whole connection string), ``username``,
    ``password`` (from the environment only) or ``password_file``, ``database`` (``exactdocs``),
    ``collection`` (``chunks``), ``timeout`` (seconds, 10), ``index_timeout`` (seconds, 120), and
    the vector backend's ``hybrid`` and ``vector_search``. An invalid option raises
    ``ValueError``.

    Args:
        options: The options.
        network: The outbound settings (#538): their CA bundle checks a TLS server's certificate
            when the options name no CA file. An HTTP proxy does not carry this protocol: the
            server is reached directly.

    Returns:
        The backend, not connected yet.
    """
    settings = _settings(options, network)
    return MongoSearchBackend(
        connect=settings.connect,
        database=settings.database,
        collection=settings.collection,
        index_timeout=settings.index_timeout,
        hidden=settings.hidden,
    )


def vector_backend(
    options: Mapping[str, object], *, network: OutboundNetwork | None = None
) -> MongoVectorBackend:
    """Build the MongoDB vector backend from its ``[index_backends.mongodb]`` options.

    Options as ``search_backend``'s, and ``hybrid`` (native hybrid search, on: a space's
    documents carry the words too) and ``vector_search`` (``approximate``, HNSW, or ``exact``).
    An invalid option raises ``ValueError``.

    Args:
        options: The options.
        network: The outbound settings (#538): their CA bundle checks a TLS server's certificate
            when the options name no CA file. An HTTP proxy does not carry this protocol: the
            server is reached directly.

    Returns:
        The backend, not connected yet; with ``NativeHybrid`` when ``hybrid`` is on.
    """
    settings = _settings(options, network)
    kind = MongoHybridVectorBackend if settings.hybrid else MongoVectorBackend
    return kind(
        connect=settings.connect,
        database=settings.database,
        collection=settings.collection,
        index_timeout=settings.index_timeout,
        hidden=settings.hidden,
        exact=settings.exact,
    )
