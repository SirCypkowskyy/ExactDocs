"""DuckDB as the search and vector backend (#357): one embedded database file (extra ``duckdb``).

``EXACTDOCS_SEARCH_BACKEND=duckdb`` / ``EXACTDOCS_VECTOR_BACKEND=duckdb`` with
``[index_backends.duckdb] path = "/data/index.duckdb"``. Both backends may name the same file: a
process opens it once and shares it. Every table carries the library, the version and the
manifest of each chunk, so the file can be queried directly (with ExactDocs stopped).

- **Search**: ``exactdocs_search`` holds each chunk's text, tokenized the way the database's own
  FTS5 index is (whole words in the heading, path and text columns, identifier parts in a fourth),
  and DuckDB's ``fts`` extension ranks it with BM25, the columns weighted as in SQLite. The ``fts``
  index does not follow writes: a write marks it stale and the next search rebuilds it.
- **Vectors**: one table per embedding space, ``exactdocs_vectors_<space id>``, with a
  ``FLOAT[<dimensions>]`` column scanned with ``array_cosine_distance`` (core DuckDB, exact).
  The ``vss`` extension's HNSW index is not used: persisting it in a database file is still
  experimental in DuckDB 2.0 (``hnsw_enable_experimental_persistence``) and can lose the index on
  a crash.
- **Offline**: the ``fts`` extension is loaded from the file the ``duckdb-extension-fts`` wheel
  installed (DuckDB checks its signature), never downloaded; extension auto-install and
  auto-load are off, so DuckDB makes no outbound request.
- **One process**: DuckDB lets one process write a file. A second process (another server
  worker, ``exactdocs index check`` beside a running server) is refused at open, with a message
  saying so.
"""

import asyncio
import importlib.resources
import re
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

import duckdb

from exactdocs.retrieval.constants import (
    _DUCKDB_COUNT,
    _DUCKDB_FTS_BUILD,
    _DUCKDB_FTS_BUILT,
    _DUCKDB_HELD,
    _DUCKDB_MARK_FRESH,
    _DUCKDB_MARK_STALE,
    _DUCKDB_NEAREST,
    _DUCKDB_SEARCH,
    _DUCKDB_SEARCH_CREATE,
    _DUCKDB_SEARCH_DELETE_CHUNKS,
    _DUCKDB_SEARCH_DELETE_MANIFESTS,
    _DUCKDB_SEARCH_INSERT,
    _DUCKDB_STATE_FIRST,
    _DUCKDB_STATE_READ,
    _DUCKDB_TAGS,
    _DUCKDB_VECTOR_CREATE,
    _DUCKDB_VECTOR_DELETE_CHUNKS,
    _DUCKDB_VECTOR_DELETE_MANIFESTS,
    _DUCKDB_VECTOR_DROP,
    _DUCKDB_VECTOR_INSERT,
    _DUCKDB_VECTOR_TABLES,
    DUCKDB_BACKEND,
    DUCKDB_CONFIG,
    DUCKDB_FTS_PACKAGE,
    DUCKDB_FTS_SCHEMA,
    DUCKDB_LOCK_HELD,
    DUCKDB_OPTIONS,
    DUCKDB_VECTOR_TABLE_PREFIX,
    HEADING_WEIGHT,
    IDENTIFIERS_WEIGHT,
    PATH_WEIGHT,
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
    TextQuery,
    identifier_tokens,
)

type _Connection = duckdb.DuckDBPyConnection
type _Config = dict[str, str | bool | int | float | list[str]]

_space_table = re.compile(rf"{DUCKDB_VECTOR_TABLE_PREFIX}\d+")


def _is_word_char(char: str) -> bool:
    """Tell whether a character belongs inside a word (as ``identifier_tokens`` reads words).

    Args:
        char: One character.

    Returns:
        True for a letter, a digit, a combining mark, ``_``, ``.`` and ``-``.
    """
    return char.isalnum() or unicodedata.category(char).startswith("M") or char in "_.-"


def _words(text: str) -> str:
    """Return a text's whole words, as ``identifier_tokens`` writes each one before its parts.

    Args:
        text: A heading, a path or a chunk's text.

    Returns:
        The words, casefolded, separated by spaces (`--dry-run` and `retry_policy` stay whole).
    """
    words: list[str] = []
    for is_word, run in groupby(unicodedata.normalize("NFC", text), _is_word_char):
        if not is_word:
            continue
        whole = "".join(run).lstrip(".").rstrip(".-").casefold()
        if any(char.isalnum() for char in whole):
            words.append(whole)
    return " ".join(words)


def _search_columns(entry: IndexEntry) -> tuple[str, str, str, str]:
    """Tokenize an entry's indexed columns: heading, ancestor headings, text, identifiers.

    Args:
        entry: The entry.

    Returns:
        What the ``fts`` index reads from each column (split as SQLite's ``fts_row`` splits a
        chunk).
    """
    headings = entry.heading_path
    full = " / ".join(headings)
    return (
        _words(headings[-1] if headings else ""),
        _words(" / ".join(headings[:-1])),
        _words(entry.content),
        identifier_tokens(f"{full}\n{entry.content}"),
    )


def _space_table_of(space_id: EmbeddingSpaceId) -> str:
    """Name a space's table.

    Args:
        space_id: The space.

    Returns:
        ``exactdocs_vectors_<id>``.
    """
    return f"{DUCKDB_VECTOR_TABLE_PREFIX}{int(space_id)}"


def _held_rows(connection: _Connection, table: str, library: str | None) -> list[HeldVersion]:
    """List the versions a table holds.

    Args:
        connection: The connection.
        table: The table.
        library: Only this library's, if given.

    Returns:
        One per version, by manifest ID.
    """
    if library is None:
        rows = connection.execute(_DUCKDB_HELD.format(table=table, where="")).fetchall()
    else:
        sql = _DUCKDB_HELD.format(table=table, where="WHERE library = $library")
        rows = connection.execute(sql, {"library": library}).fetchall()
    return [HeldVersion(manifest_id=m, library=lib, entries=int(n)) for m, lib, n in rows]


def fts_extension(version: str) -> Path:
    """Find the ``fts`` extension the ``duckdb-extension-fts`` wheel installed for this DuckDB.

    Args:
        version: DuckDB's version, as ``PRAGMA version`` says it (``v2.0.0``).

    Returns:
        The extension's file.

    Raises:
        FileNotFoundError: The package is missing, or has no file for this DuckDB release.
    """
    try:
        package = importlib.resources.files(DUCKDB_FTS_PACKAGE)
    except ModuleNotFoundError as error:
        message = "the duckdb-extension-fts package is not installed"
        raise FileNotFoundError(message) from error
    found = Path(str(package)) / "extensions" / version / "fts.duckdb_extension"
    if not found.is_file():
        message = f"duckdb-extension-fts has no fts extension for DuckDB {version}"
        raise FileNotFoundError(message)
    return found


def _lock_holder(error: duckdb.Error) -> str:
    """Pick the process holding the file out of DuckDB's lock error.

    Args:
        error: DuckDB's error.

    Returns:
        ``<program> (PID <n>)``, or ``another process`` when the message does not say.
    """
    found = re.search(r"Conflicting lock is held in (.+?\(PID \d+\))", str(error))
    return found.group(1) if found else "another process"


def _one(connection: _Connection, sql: str, params: object = None) -> tuple:
    """Run a query that returns one row.

    Args:
        connection: The connection.
        sql: The query.
        params: Its parameters.

    Returns:
        The row.

    Raises:
        duckdb.InternalException: It returned no row.
    """
    row = connection.execute(sql, params).fetchone()
    if row is None:
        message = f"no row from {sql!r}"
        raise duckdb.InternalException(message)
    return row


def _in_transaction(connection: _Connection, work: Callable[[], None]) -> None:
    """Run statements in one transaction, rolled back if one fails.

    Args:
        connection: The connection.
        work: The statements.
    """
    connection.begin()
    try:
        work()
    except BaseException:
        connection.rollback()
        raise
    connection.commit()


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- opened at start
class _DuckDBFile:
    """One DuckDB database file, opened at start, used from one worker thread at a time."""

    name: str
    """The backend's registered name, for messages."""
    path: Path
    """The database file."""
    config: _Config
    """What the file is opened with (``DUCKDB_CONFIG`` plus the options)."""
    connection: _Connection | None = None
    """The open connection; ``None`` before ``open`` and after ``close``."""
    executor: ThreadPoolExecutor | None = None
    """The single thread every statement runs on, so the event loop never waits for DuckDB."""

    def connect(self, *, fts: bool) -> None:
        """Open the file (and load the ``fts`` extension from its installed file).

        Args:
            fts: Load the ``fts`` extension too.

        Raises:
            IndexBackendUnavailableError: The file cannot be opened (another process holds it,
                or its folder is missing), or the extension is not installed.
        """
        if not self.path.parent.is_dir():
            reason = f"the folder of {self.path} does not exist"
            raise IndexBackendUnavailableError(self.name, reason)
        try:
            connection = duckdb.connect(str(self.path), config=self.config)
        except duckdb.Error as error:
            if DUCKDB_LOCK_HELD in str(error):
                reason = (
                    f"{self.path} is open in {_lock_holder(error)}. DuckDB lets one process "
                    "write a database file: run one ExactDocs process on it (WEB_CONCURRENCY=1), "
                    "and stop the server before `exactdocs index check` or `exactdocs index "
                    "rebuild`"
                )
                raise IndexBackendUnavailableError(self.name, reason) from error
            raise IndexBackendUnavailableError(self.name, f"{self.path}: {error}") from error
        try:
            if fts:
                version = str(_one(connection, "PRAGMA version")[0])
                quoted = str(fts_extension(version)).replace("'", "''")
                connection.execute(f"LOAD '{quoted}'")
        except (duckdb.Error, FileNotFoundError) as error:
            connection.close()
            reason = f"the fts extension did not load: {error} (pip install 'exactdocs[duckdb]')"
            raise IndexBackendUnavailableError(self.name, reason) from error
        self.connection = connection

    async def open(self, prepare: Callable[[_Connection], None], *, fts: bool) -> None:
        """Start the worker thread, open the file and create the tables it lacks.

        Args:
            prepare: Creates the backend's tables (runs on the worker thread).
            fts: Load the ``fts`` extension.
        """
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="duckdb-index")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, lambda: self.connect(fts=fts))
        await self.run(prepare)

    async def close(self) -> None:
        """Close the connection and stop the worker thread."""
        executor, connection = self.executor, self.connection
        self.executor = self.connection = None
        if executor is None:
            return
        if connection is not None:
            await asyncio.get_running_loop().run_in_executor(executor, connection.close)
        executor.shutdown(wait=True)

    async def run[T](self, work: Callable[[_Connection], T]) -> T:
        """Run statements on the worker thread.

        Args:
            work: What to run, given the connection.

        Returns:
            What ``work`` returns.

        Raises:
            IndexBackendUnavailableError: The file is not open, or DuckDB failed.
        """
        connection, executor = self.connection, self.executor
        if connection is None or executor is None:
            raise IndexBackendUnavailableError(self.name, "the database file is not open")
        try:
            return await asyncio.get_running_loop().run_in_executor(executor, work, connection)
        except duckdb.Error as error:
            reason = f"{type(error).__name__}: {error}"
            raise IndexBackendUnavailableError(self.name, reason) from error


def _prepare_search(connection: _Connection) -> None:
    """Create the search tables it lacks; a missing ``fts`` index counts as stale.

    Args:
        connection: The connection.
    """
    for statement in _DUCKDB_SEARCH_CREATE:
        connection.execute(statement)
    if connection.execute(_DUCKDB_STATE_READ).fetchone() is None:
        connection.execute(_DUCKDB_STATE_FIRST)
    if connection.execute(_DUCKDB_FTS_BUILT, {"schema": DUCKDB_FTS_SCHEMA}).fetchone() is None:
        connection.execute(_DUCKDB_MARK_STALE)


def _refresh_fts(connection: _Connection) -> None:
    """Rebuild the ``fts`` index if a write came after it (it never updates by itself).

    Args:
        connection: The connection.
    """
    (stale,) = _one(connection, _DUCKDB_STATE_READ)
    if not stale:
        return

    def rebuild() -> None:
        """Index the whole table again, and record that it is current."""
        connection.execute(_DUCKDB_FTS_BUILD)
        connection.execute(_DUCKDB_MARK_FRESH)

    _in_transaction(connection, rebuild)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- opened at start
class DuckDBSearchBackend:
    """Implements ``ports.driven.SearchBackend`` on a DuckDB file, ranked by its ``fts`` BM25."""

    file: _DuckDBFile
    """The database file."""
    name: str = DUCKDB_BACKEND
    """The registered name."""

    async def open(self) -> None:
        """Open the file, load ``fts`` from its installed file, create the tables it lacks."""
        await self.file.open(_prepare_search, fts=True)

    async def close(self) -> None:
        """Close the file."""
        await self.file.close()

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries; the ``fts`` index is rebuilt at the next search.

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        if not entries:
            return
        columns = [_search_columns(e) for e in entries]
        chunks = [e.chunk_id for e in entries]
        params = {
            "manifest": manifest.manifest_id,
            "library": manifest.library,
            "version": manifest.version_id,
            "chunks": chunks,
            "articles": [e.article_path for e in entries],
            "headings": [list(e.heading_path) for e in entries],
            "contents": [e.content for e in entries],
            "tags": [list(e.tags) for e in entries],
            "fts_heading": [c[0] for c in columns],
            "fts_path": [c[1] for c in columns],
            "fts_text": [c[2] for c in columns],
            "fts_identifiers": [c[3] for c in columns],
        }

        def write(connection: _Connection) -> None:
            """Replace the rows and mark the ``fts`` index stale, in one transaction.

            Args:
                connection: The connection.
            """

            def statements() -> None:
                """The delete, the insert and the mark."""
                connection.execute(
                    _DUCKDB_SEARCH_DELETE_CHUNKS,
                    {"manifest": manifest.manifest_id, "chunks": chunks},
                )
                connection.execute(_DUCKDB_SEARCH_INSERT, params)
                connection.execute(_DUCKDB_MARK_STALE)

            _in_transaction(connection, statements)

        await self.file.run(write)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        params = {"manifests": list(manifest_ids)}

        def write(connection: _Connection) -> None:
            """Delete the rows; mark the ``fts`` index stale when some went.

            Args:
                connection: The connection.
            """

            def statements() -> None:
                """The delete and, if it took rows, the mark."""
                (deleted,) = _one(connection, _DUCKDB_SEARCH_DELETE_MANIFESTS, params)
                if deleted:
                    connection.execute(_DUCKDB_MARK_STALE)

            _in_transaction(connection, statements)

        await self.file.run(write)

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """List the versions held.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID.
        """
        return await self.file.run(
            lambda connection: _held_rows(connection, "exactdocs_search", library)
        )

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' entries with BM25 over the weighted columns.

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
        sql = _DUCKDB_SEARCH.format(tags=_DUCKDB_TAGS[tag_filter.match])
        params = {
            "manifests": list(dict.fromkeys(manifest_ids)),
            "terms": " ".join(query.terms),
            "tags": list(tag_filter.tags),
            "limit": limit,
            "heading_weight": HEADING_WEIGHT,
            "path_weight": PATH_WEIGHT,
            "text_weight": TEXT_WEIGHT,
            "identifiers_weight": IDENTIFIERS_WEIGHT,
        }

        def ranked(connection: _Connection) -> list[BackendHit]:
            """Rebuild a stale ``fts`` index, then rank.

            Args:
                connection: The connection.

            Returns:
                The hits.
            """
            _refresh_fts(connection)
            return [
                BackendHit(manifest_id=m, chunk_id=ChunkId(c), score=float(s))
                for m, c, s in connection.execute(sql, params).fetchall()
            ]

        return await self.file.run(ranked)

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
        sql = _DUCKDB_COUNT.format(tags=_DUCKDB_TAGS[tag_filter.match])
        params = {
            "manifests": list(dict.fromkeys(manifest_ids)),
            "terms": " ".join(query.terms),
            "tags": list(tag_filter.tags),
        }

        def counted(connection: _Connection) -> dict[str, int]:
            """Rebuild a stale ``fts`` index, then count.

            Args:
                connection: The connection.

            Returns:
                The counts.
            """
            _refresh_fts(connection)
            return {m: int(n) for m, n in connection.execute(sql, params).fetchall()}

        return await self.file.run(counted)


def _space_tables(connection: _Connection) -> list[str]:
    """List the spaces' tables.

    Args:
        connection: The connection.

    Returns:
        Their names.
    """
    rows = connection.execute(_DUCKDB_VECTOR_TABLES, {"prefix": DUCKDB_VECTOR_TABLE_PREFIX})
    return [name for (name,) in rows.fetchall() if _space_table.fullmatch(name)]


def _no_tables(_: _Connection) -> None:
    """Prepare nothing: a space's table is made at its first put.

    Args:
        _: The connection.
    """


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- opened at start
class DuckDBVectorBackend:
    """Implements ``ports.driven.VectorBackend`` on a DuckDB file: exact cosine over a column."""

    file: _DuckDBFile
    """The database file."""
    name: str = DUCKDB_BACKEND
    """The registered name."""

    async def open(self) -> None:
        """Open the file (each space's table is made at its first put)."""
        await self.file.open(_no_tables, fts=False)

    async def close(self) -> None:
        """Close the file."""
        await self.file.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries in the space's table (made at its first put).

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        kept = [e for e in entries if e.vector is not None]
        if not kept:
            return
        table, dimensions = _space_table_of(space.id), int(space.spec.dimensions)
        chunks = [e.chunk_id for e in kept]
        params = {
            "manifest": manifest.manifest_id,
            "library": manifest.library,
            "version": manifest.version_id,
            "chunks": chunks,
            "articles": [e.article_path for e in kept],
            "headings": [list(e.heading_path) for e in kept],
            "tags": [list(e.tags) for e in kept],
            "vectors": [list(e.vector or ()) for e in kept],
        }

        def write(connection: _Connection) -> None:
            """Make the table if needed, then replace the rows in one transaction.

            Args:
                connection: The connection.
            """
            connection.execute(_DUCKDB_VECTOR_CREATE.format(table=table, dimensions=dimensions))

            def statements() -> None:
                """The delete and the insert."""
                connection.execute(
                    _DUCKDB_VECTOR_DELETE_CHUNKS.format(table=table),
                    {"manifest": manifest.manifest_id, "chunks": chunks},
                )
                connection.execute(
                    _DUCKDB_VECTOR_INSERT.format(table=table, dimensions=dimensions), params
                )

            _in_transaction(connection, statements)

        await self.file.run(write)

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        if not chunk_ids:
            return
        table = _space_table_of(space_id)
        params = {"manifest": manifest_id, "chunks": list(chunk_ids)}

        def write(connection: _Connection) -> None:
            """Delete the rows, if the space has a table.

            Args:
                connection: The connection.
            """
            if table in _space_tables(connection):
                connection.execute(_DUCKDB_VECTOR_DELETE_CHUNKS.format(table=table), params)

        await self.file.run(write)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries in every space.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        params = {"manifests": list(manifest_ids)}

        def write(connection: _Connection) -> None:
            """Delete the rows from every space's table, in one transaction.

            Args:
                connection: The connection.
            """

            def statements() -> None:
                """One delete per space."""
                for table in _space_tables(connection):
                    connection.execute(_DUCKDB_VECTOR_DELETE_MANIFESTS.format(table=table), params)

            _in_transaction(connection, statements)

        await self.file.run(write)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Drop a space's table.

        Args:
            space_id: The space.
        """
        sql = _DUCKDB_VECTOR_DROP.format(table=_space_table_of(space_id))
        await self.file.run(lambda connection: connection.execute(sql))

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the space holds.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held; none for an unknown space.
        """
        table = _space_table_of(space_id)

        def listed(connection: _Connection) -> list[HeldVersion]:
            """List them, if the space has a table.

            Args:
                connection: The connection.

            Returns:
                The versions.
            """
            if table not in _space_tables(connection):
                return []
            return _held_rows(connection, table, library)

        return await self.file.run(listed)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Compare the query with every vector of the versions (an exact scan).

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
        table = _space_table_of(space.id)
        sql = _DUCKDB_NEAREST.format(
            table=table,
            dimensions=int(space.spec.dimensions),
            tags=_DUCKDB_TAGS[tag_filter.match],
        )
        params = {
            "manifests": list(dict.fromkeys(manifest_ids)),
            "query": [float(v) for v in query],
            "tags": list(tag_filter.tags),
            "limit": limit,
        }

        def found(connection: _Connection) -> list[BackendNeighbour]:
            """Scan the space's table, if it has one.

            Args:
                connection: The connection.

            Returns:
                The neighbours.
            """
            if table not in _space_tables(connection):
                return []
            return [
                BackendNeighbour(manifest_id=m, chunk_id=ChunkId(c), distance=float(d))
                for m, c, d in connection.execute(sql, params).fetchall()
            ]

        return await self.file.run(found)


def _file(options: Mapping[str, object]) -> _DuckDBFile:
    """Check the ``[index_backends.duckdb]`` options and describe the file they name.

    Args:
        options: ``path`` (required), ``threads``, ``memory_limit``.

    Returns:
        The file, not opened yet.

    Raises:
        ValueError: An option is unknown, ``path`` is missing or names no file, or ``threads`` is
            not a positive number.
    """
    unknown = sorted(set(options) - DUCKDB_OPTIONS)
    if unknown:
        known = ", ".join(sorted(DUCKDB_OPTIONS))
        message = f"the duckdb backend takes {known} (got {', '.join(unknown)})"
        raise ValueError(message)
    raw = str(options.get("path") or "").strip()
    if not raw or raw.startswith(":memory:"):
        message = "the duckdb backend needs `path`, the database file (e.g. /data/index.duckdb)"
        raise ValueError(message)
    config: _Config = dict(DUCKDB_CONFIG)
    if (threads := options.get("threads")) is not None:
        count = int(str(threads))
        if count < 1:
            message = f"the duckdb backend's `threads` must be at least 1 (got {count})"
            raise ValueError(message)
        config["threads"] = count
    if (memory := options.get("memory_limit")) is not None:
        config["memory_limit"] = str(memory)
    return _DuckDBFile(name=DUCKDB_BACKEND, path=Path(raw).expanduser(), config=config)


def search_backend(options: Mapping[str, object]) -> DuckDBSearchBackend:
    """Build the search backend from its ``[index_backends.duckdb]`` options.

    Args:
        options: ``path`` (required), ``threads``, ``memory_limit``.

    Returns:
        The backend, not opened yet.
    """
    return DuckDBSearchBackend(file=_file(options))


def vector_backend(options: Mapping[str, object]) -> DuckDBVectorBackend:
    """Build the vector backend from its ``[index_backends.duckdb]`` options.

    Args:
        options: ``path`` (required), ``threads``, ``memory_limit``.

    Returns:
        The backend, not opened yet.
    """
    return DuckDBVectorBackend(file=_file(options))
