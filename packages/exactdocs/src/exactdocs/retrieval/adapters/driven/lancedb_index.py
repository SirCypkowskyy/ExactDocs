"""LanceDB as the search and vector backend (#356): ``EXACTDOCS_*_BACKEND=lancedb``.

LanceDB is embedded: it stores Lance files in a local directory or under an object-store URI
(S3, GCS, Azure Blob), with no server. The search index is one table, ``<prefix>_chunks``; each
embedding space is one table, ``<prefix>_space_<id>``, made on the space's first write with the
space's dimensions. A row is one chunk of one version, keyed by its manifest and chunk IDs and
carrying its library and version, so every search is filtered to the asked manifests inside
LanceDB (``manifest_id IN (...)``, applied before ranking, as the tag filter is).

Full-text search is LanceDB's own (BM25 over three columns: the section's heading, its
ancestors' headings and its text, each as ``identifier_tokens`` gives it, boosted as the
database's indexes weigh them). The vector tables carry the same columns, so the vector backend
also implements ``NativeHybrid``: LanceDB's full-text search and its (exact, cosine) vector
search in one query, fused by its reciprocal rank fusion reranker.

**Writers.** Two processes upserting into one table at once leave duplicate rows (LanceDB's
commits are atomic, but a merge-insert does not see the rows another writer is adding). So, on a
local directory, every write takes an exclusive ``flock`` on ``.exactdocs-write.lock`` in it:
the server, its jobs and ``exactdocs index rebuild`` run in other processes take turns, and reads
never wait. An object store has no such lock: ExactDocs refuses an object-store URI unless the
operator sets ``single_writer = true``, stating that one process writes it.

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Its client, ``lancedb`` (with ``pyarrow``), is the ``lancedb`` extra; only this module imports
it.
"""

import asyncio
import fcntl
import logging
import os
from collections import Counter
from collections.abc import AsyncGenerator, Collection, Generator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import lancedb
import pyarrow as pa
from lancedb.db import AsyncConnection
from lancedb.index import FTS, Bitmap
from lancedb.query import MultiMatchQuery
from lancedb.rerankers import RRFReranker
from lancedb.table import AsyncTable

from exactdocs.retrieval.constants import (
    HEADING_WEIGHT,
    LANCEDB_BACKEND,
    LANCEDB_DEFAULT_PREFIX,
    LANCEDB_FALSE,
    LANCEDB_IN_BATCH,
    LANCEDB_LOCAL_SCHEMES,
    LANCEDB_LOCK_FILE,
    LANCEDB_LOCK_POLL_SECONDS,
    LANCEDB_LOCK_TIMEOUT_SECONDS,
    LANCEDB_OPTIMIZE_DELAY_SECONDS,
    LANCEDB_OPTIMIZE_ROWS,
    LANCEDB_OPTIONS,
    LANCEDB_PREFIX,
    LANCEDB_READ_CONSISTENCY_SECONDS,
    LANCEDB_SEARCH_TABLE,
    LANCEDB_SECRET_OPTION_PARTS,
    LANCEDB_SPACE_TABLE,
    LANCEDB_TIE_MARGIN,
    LANCEDB_TRUE,
    LANCEDB_WORD_COLUMNS,
    PATH_WEIGHT,
    RRF_DEPTH,
    RRF_K,
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
    as_float32,
    identifier_tokens,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class LanceDBSettings:
    """The ``[index_backends.lancedb]`` options, checked."""

    uri: str
    """The database: a local directory or an object-store URI (``s3://bucket/path``...)."""
    local: Path | None
    """The directory, when ``uri`` is local (it holds the write lock); ``None`` for an object
    store."""
    prefix: str = LANCEDB_DEFAULT_PREFIX
    """The tables' name prefix, so several instances can share one database."""
    storage_options: Mapping[str, str] = field(default_factory=dict)
    """LanceDB's storage options (region, endpoint...), never credentials."""
    single_writer: bool = False
    """The operator states that one process writes ``uri`` (required for an object store)."""
    read_consistency: float = LANCEDB_READ_CONSISTENCY_SECONDS
    """Seconds a read may lag behind another process's writes."""
    lock_timeout: float = LANCEDB_LOCK_TIMEOUT_SECONDS
    """Seconds a write waits for another process's write to end."""

    @property
    def search_table(self) -> str:
        """The search index's table."""
        return LANCEDB_SEARCH_TABLE.format(prefix=self.prefix)

    def space_table(self, space_id: EmbeddingSpaceId) -> str:
        """Name an embedding space's table.

        Args:
            space_id: The space.

        Returns:
            The table's name.
        """
        return LANCEDB_SPACE_TABLE.format(prefix=self.prefix, space=int(space_id))

    @property
    def space_tables(self) -> str:
        """The name every space table starts with."""
        return LANCEDB_SPACE_TABLE.format(prefix=self.prefix, space="")


def _schema(dimensions: int | None) -> pa.Schema:
    """Describe a table: the search table, or a space's (with its vectors).

    Args:
        dimensions: The space's dimensions; ``None`` for the search table.

    Returns:
        The Arrow schema.
    """
    fields = [
        pa.field("manifest_id", pa.string(), nullable=False),
        pa.field("library", pa.string(), nullable=False),
        pa.field("version_id", pa.string(), nullable=False),
        pa.field("chunk_id", pa.string(), nullable=False),
        pa.field("article_path", pa.string(), nullable=False),
        pa.field("tags", pa.list_(pa.string()), nullable=False),
        *(pa.field(column, pa.string(), nullable=False) for column in LANCEDB_WORD_COLUMNS),
    ]
    if dimensions is not None:
        fields.append(pa.field("vector", pa.list_(pa.float32(), dimensions), nullable=False))
    return pa.schema(fields)


def _rows(entries: Sequence[IndexEntry], dimensions: int | None) -> pa.Table:
    """Turn entries into a table's rows.

    Args:
        entries: The entries (with their vectors, for a space).
        dimensions: The space's dimensions; ``None`` for the search table.

    Returns:
        The rows.
    """
    rows = []
    for entry in entries:
        *above, heading = entry.heading_path or ("",)
        row: dict[str, object] = {
            "manifest_id": entry.manifest_id,
            "library": entry.library,
            "version_id": entry.version_id,
            "chunk_id": entry.chunk_id,
            "article_path": entry.article_path,
            "tags": list(entry.tags),
            "heading_words": identifier_tokens(heading),
            "path_words": identifier_tokens(" ".join(above)),
            "body_words": identifier_tokens(entry.content),
        }
        if dimensions is not None:
            row["vector"] = list(as_float32(entry.vector or ()))
        rows.append(row)
    return pa.Table.from_pylist(rows, schema=_schema(dimensions))


def _words_index() -> FTS:
    """Configure a full-text column: split on spaces only, the words as written.

    The columns hold ``identifier_tokens``' words (casefolded, ``retry_policy`` kept whole
    beside its parts); no stemming, stop words or folding is added.

    Returns:
        The index configuration.
    """
    return FTS(
        base_tokenizer="whitespace",
        lower_case=False,
        stem=False,
        remove_stop_words=False,
        ascii_folding=False,
        max_token_length=None,
    )


def _match(query: TextQuery) -> MultiMatchQuery:
    """Match any of the query's terms in the three word columns, the heading weighing most.

    The terms are matched as words, never parsed: LanceDB splits them on spaces only.

    Args:
        query: The query; its terms hold no spaces.

    Returns:
        The full-text query.
    """
    return MultiMatchQuery(
        " ".join(query.terms),
        list(LANCEDB_WORD_COLUMNS),
        boosts=[HEADING_WEIGHT, PATH_WEIGHT, TEXT_WEIGHT],
    )


def _quoted(value: str) -> str:
    """Quote a value as an SQL string literal.

    Args:
        value: The value.

    Returns:
        The literal.
    """
    return "'" + value.replace("'", "''") + "'"


def _listed(values: Collection[str]) -> str:
    """Quote values as an SQL list.

    Args:
        values: The values.

    Returns:
        ``'a', 'b'``.
    """
    return ", ".join(_quoted(v) for v in dict.fromkeys(values))


def _where(manifest_ids: Collection[str], tag_filter: TagFilter) -> str:
    """Filter a search to the versions and the tags (LanceDB applies it before ranking).

    Args:
        manifest_ids: The versions searched; not empty.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The predicate.
    """
    where = f"manifest_id IN ({_listed(manifest_ids)})"
    if tag_filter.tags:
        has = "array_has_all" if tag_filter.match is TagMatch.ALL else "array_has_any"
        where += f" AND {has}(tags, [{_listed(tag_filter.tags)}])"
    return where


def _batches(values: Collection[str]) -> Iterator[list[str]]:
    """Cut values into lists short enough for one ``IN (...)``.

    Args:
        values: The values.

    Yields:
        At most ``LANCEDB_IN_BATCH`` values at a time.
    """
    distinct = list(dict.fromkeys(values))
    for start in range(0, len(distinct), LANCEDB_IN_BATCH):
        yield distinct[start : start + LANCEDB_IN_BATCH]


def _held(rows: pa.Table) -> list[HeldVersion]:
    """Count the rows of each version.

    Args:
        rows: The ``manifest_id`` and ``library`` columns of some rows.

    Returns:
        One per version, by manifest ID.
    """
    counts = Counter(
        zip(rows.column("manifest_id").to_pylist(), rows.column("library").to_pylist(), strict=True)
    )
    return [
        HeldVersion(manifest_id=manifest_id, library=library, entries=entries)
        for (manifest_id, library), entries in sorted(counts.items())
    ]


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- connection, turn
class LanceDBStore:
    """One LanceDB database, opened at start, and the write turn every writer takes.

    Each write runs under ``writing()``: one at a time in this process, and, on a local
    directory, one at a time across processes (an exclusive ``flock`` on the lock file). Rows
    written are searched at once (by a scan until indexed); a quiet moment after the last write,
    or ``LANCEDB_OPTIMIZE_ROWS`` rows, adds them to the indexes and compacts the table.
    """

    settings: LanceDBSettings
    """The options."""
    name: str = LANCEDB_BACKEND
    """The registered name, for messages."""
    _db: AsyncConnection | None = field(default=None, init=False)
    """The connection, once opened."""
    _lock: int | None = field(default=None, init=False)
    """The open lock file (a local directory only)."""
    _turn: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    """Serialises this process's writes."""
    _tables: dict[str, AsyncTable] = field(default_factory=dict, init=False)
    """Open tables, by name."""
    _indexed: set[str] = field(default_factory=set, init=False)
    """Tables whose indexes this process made sure of (a write made them, or found them)."""
    _pending: dict[str, int] = field(default_factory=dict, init=False)
    """Rows written to each table since its indexes were last brought up to date."""
    _timer: asyncio.TimerHandle | None = field(default=None, init=False)
    """Starts ``_settle`` once writes went quiet; pushed back by each write."""
    _settler: asyncio.Task[None] | None = field(default=None, init=False)
    """The background task that indexes pending rows."""

    async def open(self) -> None:
        """Connect, and check the database answers (``IndexBackendUnavailableError`` if not)."""
        if self._db is not None:
            return
        self._turn = asyncio.Lock()  # bound to the event loop that serves
        with self.guard(f"opening {self.settings.uri}"):
            local = self.settings.local
            if local is not None:
                await asyncio.to_thread(local.mkdir, parents=True, exist_ok=True)
                self._lock = await asyncio.to_thread(
                    os.open, local / LANCEDB_LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600
                )
            self._db = await lancedb.connect_async(
                self.settings.uri,
                read_consistency_interval=timedelta(seconds=self.settings.read_consistency),
                storage_options=dict(self.settings.storage_options) or None,
            )
            await self.tables()

    async def close(self) -> None:
        """Index what is pending, then release the connection and the lock file."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._settler is not None:
            with suppress(asyncio.CancelledError):
                await self._settler  # an optimisation half done is not stopped midway
            self._settler = None
        if self._db is not None and any(self._pending.values()):
            try:
                async with self.writing():
                    await self._optimize_pending()
            except IndexBackendUnavailableError as error:
                logger.warning("LanceDB: rows left to index at the next write: %s", error)
        for table in self._tables.values():
            table.close()
        self._tables.clear()
        if self._db is not None:
            self._db.close()
            self._db = None
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None

    @contextmanager
    def guard(self, doing: str = "") -> Generator[None]:
        """Turn LanceDB's errors into ``IndexBackendUnavailableError`` (the error type only).

        Open tables are forgotten, so a table another process dropped or made again is opened
        afresh next time.

        Args:
            doing: What was being done, for the message (never a credential).

        Yields:
            Nothing.

        Raises:
            IndexBackendUnavailableError: LanceDB, Arrow or the storage failed.
        """
        try:
            yield
        except IndexBackendUnavailableError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError, pa.ArrowException) as error:
            self._tables.clear()
            reason = f"{type(error).__name__} {doing}".strip()
            raise IndexBackendUnavailableError(self.name, reason) from error

    def _connected(self) -> AsyncConnection:
        """Return the connection.

        Returns:
            The connection.

        Raises:
            IndexBackendUnavailableError: ``open()`` was not called.
        """
        if self._db is None:
            raise IndexBackendUnavailableError(self.name, "not opened")
        return self._db

    async def tables(self, prefix: str = "") -> list[str]:
        """List the database's tables.

        Args:
            prefix: Only those whose name starts with it.

        Returns:
            Their names.
        """
        return [name async for name in self._connected().list_tables() if name.startswith(prefix)]

    async def table(self, name: str) -> AsyncTable | None:
        """Open a table.

        Args:
            name: Its name.

        Returns:
            The table; ``None`` when it does not exist (nothing was written to it yet).
        """
        if (table := self._tables.get(name)) is not None:
            return table
        try:
            table = await self._connected().open_table(name)
        except ValueError:  # "Table '...' was not found"
            return None
        self._tables[name] = table
        return table

    async def made(self, name: str, dimensions: int | None) -> AsyncTable:
        """Open a table, making it (with its indexes) first if it does not exist; in a write.

        Args:
            name: Its name.
            dimensions: A space's dimensions; ``None`` for the search table.

        Returns:
            The table.

        Raises:
            IndexBackendUnavailableError: An existing space table holds vectors of other
                dimensions (another instance with the same prefix).
        """
        table = await self.table(name)
        if table is None:
            table = await self._connected().create_table(
                name, schema=_schema(dimensions), exist_ok=True
            )
            self._tables[name] = table
        elif dimensions is not None:
            held = (await table.schema()).field("vector").type.list_size
            if held != dimensions:
                reason = (
                    f"the table {name} holds vectors of {held} dimensions, the space has "
                    f"{dimensions}: another instance uses the table prefix "
                    f"{self.settings.prefix!r}"
                )
                raise IndexBackendUnavailableError(self.name, reason)
        if name not in self._indexed:
            # Also after a stop between making the table and its indexes.
            have = {column for index in await table.list_indices() for column in index.columns}
            if "manifest_id" not in have:
                await table.create_index("manifest_id", config=Bitmap())
            for column in LANCEDB_WORD_COLUMNS:
                if column not in have:
                    await table.create_index(column, config=_words_index())
            self._indexed.add(name)
        return table

    @asynccontextmanager
    async def writing(self) -> AsyncGenerator[None]:
        """Take the write turn: this process's, and the directory's lock across processes.

        ``IndexBackendUnavailableError`` when another process kept the lock past
        ``lock_timeout``.

        Yields:
            Nothing; the turn is held until the block ends.
        """
        async with self._turn:
            await self._take_lock()
            try:
                yield
            finally:
                if self._lock is not None:
                    fcntl.flock(self._lock, fcntl.LOCK_UN)

    async def _take_lock(self) -> None:
        """Wait for the directory's write lock (a local directory only).

        Raises:
            IndexBackendUnavailableError: Another process kept it past ``lock_timeout``.
        """
        if self._lock is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.lock_timeout
        while True:
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if loop.time() >= deadline:
                    reason = (
                        f"another process kept the write lock ({LANCEDB_LOCK_FILE} in "
                        f"{self.settings.local}) for {self.settings.lock_timeout:g} s"
                    )
                    raise IndexBackendUnavailableError(self.name, reason) from None
                await asyncio.sleep(LANCEDB_LOCK_POLL_SECONDS)
            else:
                return

    async def wrote(self, name: str, rows: int) -> None:
        """Note rows written to a table (in a write); index them now if enough are pending.

        Args:
            name: The table.
            rows: How many rows were written or deleted (at least 1).
        """
        self._pending[name] = self._pending.get(name, 0) + max(rows, 1)
        if self._pending[name] >= LANCEDB_OPTIMIZE_ROWS:
            try:
                await self._optimize(name)
            except IndexBackendUnavailableError as error:  # the rows are written: no retry
                logger.warning(
                    "LanceDB: indexing the rows written failed, retried later: %s", error
                )
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.get_running_loop().call_later(
            LANCEDB_OPTIMIZE_DELAY_SECONDS, self._start_settling
        )

    def _start_settling(self) -> None:
        """Start indexing the pending rows in the background (unless it is already running)."""
        self._timer = None
        if self._settler is None or self._settler.done():
            self._settler = asyncio.get_running_loop().create_task(self._settle())

    async def drop(self, name: str) -> None:
        """Drop a table, if it exists (in a write).

        Args:
            name: The table.
        """
        self._tables.pop(name, None)
        self._pending.pop(name, None)
        self._indexed.discard(name)
        await self._connected().drop_table(name, ignore_missing=True)

    async def _settle(self) -> None:
        """Index the pending rows, writes having gone quiet; a failure is logged and kept."""
        try:
            async with self.writing():
                await self._optimize_pending()
        except IndexBackendUnavailableError as error:
            logger.warning("LanceDB: indexing the rows written failed, retried later: %s", error)

    async def _optimize_pending(self) -> None:
        """Index every table's pending rows (in a write)."""
        for name in [n for n, rows in self._pending.items() if rows]:
            await self._optimize(name)

    async def _optimize(self, name: str) -> None:
        """Add a table's new rows to its indexes and compact it (in a write).

        Args:
            name: The table.
        """
        with self.guard():
            table = await self.table(name)
            if table is not None:
                await table.optimize()
        self._pending[name] = 0


def _store(settings: LanceDBSettings) -> LanceDBStore:
    """Make the store a backend uses (each backend opens its own connection).

    Args:
        settings: The options.

    Returns:
        A store, not opened.
    """
    return LanceDBStore(settings=settings)


@dataclass(frozen=True, slots=True, kw_only=True)
class LanceDBSearchBackend:
    """Implements ``ports.driven.SearchBackend`` with LanceDB's full-text search (BM25)."""

    store: LanceDBStore
    """The database."""

    @property
    def name(self) -> str:
        """The registered name."""
        return self.store.name

    async def open(self) -> None:
        """Connect and check the database answers."""
        await self.store.open()

    async def close(self) -> None:
        """Index what is pending and release the connection."""
        await self.store.close()

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries (keyed by manifest and chunk ID).

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        rows = [e for e in entries if e.manifest_id == manifest.manifest_id]
        if not rows:
            return
        name = self.store.settings.search_table
        async with self.store.writing():
            with self.store.guard():
                table = await self.store.made(name, None)
                await (
                    table.merge_insert(["manifest_id", "chunk_id"])
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute(_rows(rows, None))
                )
            await self.store.wrote(name, len(rows))

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries.

        Args:
            manifest_ids: The versions; unknown ones are ignored.
        """
        name = self.store.settings.search_table
        async with self.store.writing():
            with self.store.guard():
                table = await self.store.table(name)
                if table is None:
                    return
                for batch in _batches(manifest_ids):
                    await table.delete(f"manifest_id IN ({_listed(batch)})")
            await self.store.wrote(name, 1)

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """List the versions held, with their entry counts.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        with self.store.guard():
            return await _held_in(self.store, self.store.settings.search_table, library)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' entries by BM25, the heading weighing most.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or not query.terms or limit <= 0:
            return []
        with self.store.guard():
            table = await self.store.table(self.store.settings.search_table)
            if table is None:
                return []
            rows = await (
                table.query()
                .nearest_to_text(_match(query))
                .where(_where(manifest_ids, tag_filter))
                .select(["manifest_id", "chunk_id", "_score"])
                .limit(limit + LANCEDB_TIE_MARGIN)
                .to_list()
            )
        hits = [
            BackendHit(
                manifest_id=row["manifest_id"],
                chunk_id=ChunkId(row["chunk_id"]),
                score=float(row["_score"]),
            )
            for row in rows
        ]
        hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
        return hits[:limit]

    async def count(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the matching entries of each version.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many entries match, by manifest ID; zeros left out.
        """
        if not manifest_ids or not query.terms:
            return {}
        with self.store.guard():
            table = await self.store.table(self.store.settings.search_table)
            if table is None:
                return {}
            where = _where(manifest_ids, tag_filter)
            if not (candidates := await table.count_rows(where)):
                return {}
            rows = await (
                table.query()
                .nearest_to_text(_match(query))
                .where(where)
                .select(["manifest_id", "_score"])
                .limit(candidates)
                .to_arrow()
            )
        return dict(Counter(rows.column("manifest_id").to_pylist()))


@dataclass(frozen=True, slots=True, kw_only=True)
class LanceDBVectorBackend:
    """Implements ``ports.driven.VectorBackend`` and ``NativeHybrid`` with LanceDB.

    ``nearest`` is an exact cosine search over the asked versions' rows; ``hybrid`` adds
    LanceDB's full-text search on the same rows and fuses both with its RRF reranker.
    """

    store: LanceDBStore
    """The database."""

    @property
    def name(self) -> str:
        """The registered name."""
        return self.store.name

    async def open(self) -> None:
        """Connect and check the database answers."""
        await self.store.open()

    async def close(self) -> None:
        """Index what is pending and release the connection."""
        await self.store.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries in the space's table (made on its first write).

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        rows = [
            e for e in entries if e.vector is not None and e.manifest_id == manifest.manifest_id
        ]
        if not rows:
            return
        name = self.store.settings.space_table(space.id)
        dimensions = space.spec.dimensions
        async with self.store.writing():
            with self.store.guard():
                table = await self.store.made(name, dimensions)
                await (
                    table.merge_insert(["manifest_id", "chunk_id"])
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute(_rows(rows, dimensions))
                )
            await self.store.wrote(name, len(rows))

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks; unknown ones are ignored.
        """
        if not chunk_ids:
            return
        name = self.store.settings.space_table(space_id)
        async with self.store.writing():
            with self.store.guard():
                table = await self.store.table(name)
                if table is None:
                    return
                for batch in _batches(chunk_ids):
                    await table.delete(
                        f"manifest_id = {_quoted(manifest_id)} AND chunk_id IN ({_listed(batch)})"
                    )
            await self.store.wrote(name, 1)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries in every space.

        Args:
            manifest_ids: The versions; unknown ones are ignored.
        """
        async with self.store.writing():
            with self.store.guard():
                names = await self.store.tables(self.store.settings.space_tables)
                for name in names:
                    table = await self.store.table(name)
                    if table is None:
                        continue
                    for batch in _batches(manifest_ids):
                        await table.delete(f"manifest_id IN ({_listed(batch)})")
            for name in names:
                await self.store.wrote(name, 1)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Drop a space's table; a no-op for an unknown space.

        Args:
            space_id: The space.
        """
        name = self.store.settings.space_table(space_id)
        async with self.store.writing():
            with self.store.guard():
                await self.store.drop(name)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the space holds.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held; empty for an unknown space.
        """
        with self.store.guard():
            return await _held_in(self.store, self.store.settings.space_table(space_id), library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Compare the query with every vector of the versions (exact cosine distance).

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries, nearest first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or limit <= 0:
            return []
        with self.store.guard():
            table = await self.store.table(self.store.settings.space_table(space.id))
            if table is None:
                return []
            rows = await (
                table.query()
                .nearest_to(list(as_float32(query)))
                .distance_type("cosine")
                .where(_where(manifest_ids, tag_filter))
                .select(["manifest_id", "chunk_id", "_distance"])
                .limit(limit + LANCEDB_TIE_MARGIN)
                .to_list()
            )
        hits = [
            BackendNeighbour(
                manifest_id=row["manifest_id"],
                chunk_id=ChunkId(row["chunk_id"]),
                distance=max(0.0, float(row["_distance"])),
            )
            for row in rows
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
        """Rank the versions' entries by LanceDB's full-text and vector searches together.

        Each half takes the best ``RRF_DEPTH`` (or ``limit``) rows of the versions, filtered
        before ranking and ordered with ties by chunk ID: LanceDB's full-text search (BM25) and
        its exact cosine search. LanceDB's reciprocal rank fusion reranker (``k`` = ``RRF_K``)
        fuses them. A query without terms ranks by the vector alone.

        Args:
            space: The space the vector belongs to.
            manifest_ids: The versions searched.
            query: The query and its terms.
            vector: The query's vector, from the space's model.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The fused hits, best first; ties by chunk ID, then manifest ID.
        """
        if not manifest_ids or limit <= 0:
            return []
        if not query.terms:
            near = await self.nearest(space, manifest_ids, vector, tag_filter, limit)
            return [
                BackendHit(manifest_id=h.manifest_id, chunk_id=h.chunk_id, score=1 / (RRF_K + n))
                for n, h in enumerate(near, start=1)
            ]
        depth = max(RRF_DEPTH, limit)
        where = _where(manifest_ids, tag_filter)
        with self.store.guard():
            table = await self.store.table(self.store.settings.space_table(space.id))
            if table is None:
                return []
            near = await (
                table.query()
                .nearest_to(list(as_float32(vector)))
                .distance_type("cosine")
                .where(where)
                .select(["manifest_id", "chunk_id", "_distance"])
                .with_row_id()
                .limit(depth)
                .to_arrow()
            )
            words = await (
                table.query()
                .nearest_to_text(_match(query))
                .where(where)
                .select(["manifest_id", "chunk_id", "_score"])
                .with_row_id()
                .limit(depth)
                .to_arrow()
            )
            fused = RRFReranker(K=RRF_K).rerank_hybrid(
                query.text,
                near.sort_by([("_distance", "ascending"), ("chunk_id", "ascending")]),
                words.sort_by([("_score", "descending"), ("chunk_id", "ascending")]),
            )
        hits = [
            BackendHit(
                manifest_id=row["manifest_id"],
                chunk_id=ChunkId(row["chunk_id"]),
                score=float(row["_relevance_score"]),
            )
            for row in fused.to_pylist()
        ]
        hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
        return hits[:limit]


async def _held_in(store: LanceDBStore, name: str, library: str | None) -> list[HeldVersion]:
    """List the versions a table holds rows of.

    Args:
        store: The database.
        name: The table.
        library: Only this library's, if given.

    Returns:
        One per version held; empty for a table not made yet.
    """
    table = await store.table(name)
    if table is None:
        return []
    query = table.query().select(["manifest_id", "library"])
    if library is not None:
        query = query.where(f"library = {_quoted(library)}")
    return _held(await query.to_arrow())


# ---------------------------------------------------------------- options


def _switch(options: Mapping[str, object], name: str) -> bool:
    """Read a true/false option (a TOML boolean, or a string from the environment).

    Args:
        options: The options.
        name: The option.

    Returns:
        Its value; false when unset.

    Raises:
        ValueError: It is neither true nor false.
    """
    value = options.get(name, False)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in LANCEDB_TRUE | LANCEDB_FALSE:
        return text in LANCEDB_TRUE
    message = f"{name} must be true or false (got {value!r})"
    raise ValueError(message)


def _seconds(options: Mapping[str, object], name: str, default: float) -> float:
    """Read a number of seconds (0 or more).

    Args:
        options: The options.
        name: The option.
        default: Its value when unset.

    Returns:
        The seconds.

    Raises:
        ValueError: It is not a number, or it is negative.
    """
    value = options.get(name, default)
    try:
        seconds = float(str(value))
    except ValueError:
        seconds = -1.0
    if isinstance(value, bool) or not seconds >= 0:
        message = f"{name} must be a number of seconds, 0 or more (got {value!r})"
        raise ValueError(message)
    return seconds


def _storage_options(options: Mapping[str, object]) -> dict[str, str]:
    """Read LanceDB's storage options, refusing credentials.

    Args:
        options: The options.

    Returns:
        The storage options, as strings.

    Raises:
        TypeError: They are not a table.
        ValueError: One names a credential.
    """
    value = options.get("storage_options", {})
    if not isinstance(value, Mapping):
        message = "storage_options must be a table of names and values"
        raise TypeError(message)
    found = sorted(
        str(k) for k in value if any(p in str(k).lower() for p in LANCEDB_SECRET_OPTION_PARTS)
    )
    if found:
        message = (
            f"storage_options may not hold credentials ({', '.join(found)}): set the object "
            "store's own environment variables instead (AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY, GOOGLE_APPLICATION_CREDENTIALS, AZURE_STORAGE_ACCOUNT_KEY...)"
        )
        raise ValueError(message)
    return {str(k): str(v) for k, v in value.items()}


def lancedb_settings(options: Mapping[str, object]) -> LanceDBSettings:
    """Check the ``[index_backends.lancedb]`` options.

    Args:
        options: The options.

    Returns:
        The settings.

    Raises:
        ValueError: An option is unknown, missing or invalid, or an object-store URI is given
            without ``single_writer = true``.
    """
    unknown = sorted(set(options) - LANCEDB_OPTIONS)
    if unknown:
        message = (
            f"unknown option(s) {', '.join(unknown)} (known: {', '.join(sorted(LANCEDB_OPTIONS))})"
        )
        raise ValueError(message)
    uri = str(options.get("uri", "")).strip()
    if not uri:
        message = "uri is required: a local directory (/var/lib/exactdocs/lancedb) or s3://..."
        raise ValueError(message)
    prefix = str(options.get("table_prefix", LANCEDB_DEFAULT_PREFIX))
    if not LANCEDB_PREFIX.fullmatch(prefix):
        message = f"table_prefix must be lower-case letters, digits and _ (got {prefix!r})"
        raise ValueError(message)
    single_writer = _switch(options, "single_writer")
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if parts.query or parts.username or parts.password:
        message = (
            "uri may not carry credentials or parameters (user info, ?...): set the object "
            "store's own environment variables and storage_options instead"
        )
        raise ValueError(message)
    local = None
    if scheme in LANCEDB_LOCAL_SCHEMES:
        local = Path(uri.removeprefix("file://")).expanduser()
        if not local.is_absolute():
            message = f"uri must be an absolute directory or an object-store URI (got {uri!r})"
            raise ValueError(message)
        uri = str(local)
    elif not single_writer:
        message = (
            f"uri {scheme}://... is an object store, where ExactDocs cannot lock writes across "
            "processes, and two processes writing at once leave duplicate entries. Set "
            "single_writer = true if exactly one ExactDocs process writes it (no replicas, and "
            "`exactdocs index rebuild` only while the server is stopped); otherwise use a local "
            "directory (writers there take turns) or a server backend"
        )
        raise ValueError(message)
    timeout = _seconds(options, "lock_timeout_seconds", LANCEDB_LOCK_TIMEOUT_SECONDS)
    if timeout <= 0:
        message = "lock_timeout_seconds must be more than 0"
        raise ValueError(message)
    return LanceDBSettings(
        uri=uri,
        local=local,
        prefix=prefix,
        storage_options=_storage_options(options),
        single_writer=single_writer,
        read_consistency=_seconds(
            options, "read_consistency_seconds", LANCEDB_READ_CONSISTENCY_SECONDS
        ),
        lock_timeout=timeout,
    )


def search_backend(options: Mapping[str, object]) -> LanceDBSearchBackend:
    """Build the search backend from its ``[index_backends.lancedb]`` options.

    Args:
        options: The options (``uri`` at least).

    Returns:
        The backend, not opened.
    """
    return LanceDBSearchBackend(store=_store(lancedb_settings(options)))


def vector_backend(options: Mapping[str, object]) -> LanceDBVectorBackend:
    """Build the vector backend (with native hybrid) from its ``[index_backends.lancedb]``.

    Args:
        options: The options (``uri`` at least).

    Returns:
        The backend, not opened.
    """
    return LanceDBVectorBackend(store=_store(lancedb_settings(options)))
