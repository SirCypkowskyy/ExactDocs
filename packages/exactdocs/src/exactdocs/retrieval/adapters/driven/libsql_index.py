"""libSQL as the search and vector backend (``libsql``, #358).

libSQL is the open-source fork of SQLite behind Turso. It has FTS5, as SQLite does, and native
vectors: an ``F32_BLOB(<dimensions>)`` column, a vector index (``libsql_vector_idx``, DiskANN) and
``vector_top_k`` to read it, with no extension to load. The backend holds a copy of each version,
as every external backend does (derived data, rebuilt from the database):

- **search**: one row per chunk of each version in ``<prefix>_search_entries`` and its FTS5 row
  in ``<prefix>_search`` (with the columns, tokenizer and ``bm25()`` weights of
  ExactDocs' SQLite index), so a search ranks as on SQLite;
- **vectors**: one table per embedding space, ``<prefix>_space_<id>``, with its vector index
  ``<prefix>_space_<id>_ann`` (cosine), listed in ``<prefix>_spaces``.

Every search names the versions (manifest IDs) it may look at, in SQL. A vector search asks the
index for enough neighbours that the asked versions' share of them fills the limit, keeps those,
and scans the asked versions' vectors exactly when the index cannot give enough of them (a small
version in a big space, a narrow tag filter): never a chunk of another version.

The ``url`` option says how libSQL is reached:

- a **libSQL server** (``sqld``, or Turso): ``libsql://``, ``https://`` or ``http://``, over the
  server's HTTP API (Hrana over HTTP, ``/v2/pipeline``) with ExactDocs' own HTTP client, so
  nothing more is installed and several ExactDocs processes and hosts share it. Its
  ``auth_token`` (a JWT) comes from the environment or ``auth_token_file``, never the TOML file;
- a **local file** (``file:<path>`` or a path): libSQL embedded in this process through the
  ``libsql`` package (the ``libsql`` extra, imported only then), on a thread of its own.
"""

import asyncio
import base64
import importlib
import importlib.util
import json
import math
import struct
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

import httpx2

from exactdocs.retrieval.adapters.driven.sqlite_fts import fts_row
from exactdocs.retrieval.constants import (
    HEADING_WEIGHT,
    IDENTIFIERS_WEIGHT,
    LIBSQL_ANN_MAX_CANDIDATES,
    LIBSQL_ANN_OVERFETCH,
    LIBSQL_BACKEND,
    LIBSQL_BUSY_TIMEOUT_MS,
    LIBSQL_COMPRESSIONS,
    LIBSQL_COUNT,
    LIBSQL_DEFAULT_COMPRESSION,
    LIBSQL_DEFAULT_PREFIX,
    LIBSQL_DEFAULT_TIMEOUT_SECONDS,
    LIBSQL_HELD,
    LIBSQL_NEAREST_INDEX,
    LIBSQL_NEAREST_SCAN,
    LIBSQL_NEAREST_SIZES,
    LIBSQL_OPTIONS,
    LIBSQL_PREFIX,
    LIBSQL_SEARCH,
    LIBSQL_SEARCH_DELETE,
    LIBSQL_SEARCH_PUT,
    LIBSQL_SEARCH_TABLES,
    LIBSQL_SPACE_CREATE,
    LIBSQL_SPACE_DROP,
    LIBSQL_SPACE_IDS,
    LIBSQL_SPACES_TABLE,
    LIBSQL_TAG_CONDITIONS,
    LIBSQL_URL_SCHEMES,
    LIBSQL_VECTOR_CHECK,
    LIBSQL_VECTOR_DELETE,
    LIBSQL_VECTOR_PUT,
    LIBSQL_VECTOR_REMOVE,
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
)

type _Statement = tuple[str, Sequence[object]]
type _Row = tuple[Any, ...]


class _StatementError(IndexBackendUnavailableError):
    """A statement failed; ``missing_table`` when it named a table that is not there."""

    def __init__(self, message: str) -> None:
        """Keep libSQL's message (it names SQL objects, never a credential).

        Args:
            message: libSQL's message.
        """
        super().__init__(LIBSQL_BACKEND, message)
        self.missing_table = "no such table" in message


class _Engine(Protocol):
    """How the backend reaches libSQL: a server over HTTP, or a local file in this process."""

    async def open(self) -> None:
        """Connect (``IndexBackendUnavailableError`` when it cannot)."""
        ...

    async def close(self) -> None:
        """Release the connection."""
        ...

    async def run(self, statements: Sequence[_Statement], *, atomic: bool) -> list[list[_Row]]:
        """Run the statements in order, stopping at the first that fails.

        Raises ``IndexBackendUnavailableError`` when libSQL does not answer, ``_StatementError``
        when a statement fails.

        Args:
            statements: The SQL and its positional arguments, each.
            atomic: Run them in one write transaction (all or nothing).

        Returns:
            Each statement's rows.
        """
        ...


class _Cursor(Protocol):
    """What the backend uses of a ``libsql`` cursor (DB-API)."""

    def execute(self, sql: str, parameters: Sequence[object], /) -> _Cursor:
        """Run one statement.

        Args:
            sql: The statement.
            parameters: Its positional arguments.

        Returns:
            The cursor, holding the rows.
        """
        ...

    def fetchall(self) -> list[Sequence[Any]] | None:
        """Return every row of the last statement.

        Returns:
            The rows; ``None`` after a statement that returns none (``libsql`` does that).
        """
        ...


def _value(value: object) -> dict[str, object]:
    """Encode one argument as a Hrana value.

    Args:
        value: ``None``, an int, a float, a string or bytes.

    Returns:
        The value as the HTTP API takes it.
    """
    match value:
        case None:
            return {"type": "null"}
        case bool() | int():
            return {"type": "integer", "value": str(int(value))}
        case float():
            return {"type": "float", "value": value}
        case bytes():
            return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
        case _:
            return {"type": "text", "value": str(value)}


def _decoded(value: Mapping[str, Any]) -> object:
    """Decode one Hrana value of a result row.

    Args:
        value: The value as the HTTP API returns it.

    Returns:
        The Python value.
    """
    match value.get("type"):
        case "integer":
            return int(value["value"])
        case "float":
            return float(value["value"])
        case "text":
            return value["value"]
        case "blob":
            encoded = str(value["base64"])
            return base64.b64decode(encoded + "=" * (-len(encoded) % 4))
        case _:
            return None


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- the open client
class _HttpEngine:
    """A libSQL server (``sqld``, Turso) over its HTTP API: one pipeline request per call."""

    url: str
    """The server's base URL, ``http(s)://host[:port]``."""
    token: str | None = field(default=None, repr=False)
    """The JWT sent as ``Authorization: Bearer``; ``None`` for a server without auth."""
    timeout: float = LIBSQL_DEFAULT_TIMEOUT_SECONDS
    """Seconds one request may take."""
    client: httpx2.AsyncClient | None = field(default=None, init=False, repr=False)
    """The open client, between ``open`` and ``close``."""

    async def open(self) -> None:
        """Make the client (the backend then checks that the server answers)."""
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client = httpx2.AsyncClient(
            base_url=self.url, headers=headers, timeout=self.timeout, follow_redirects=False
        )

    async def close(self) -> None:
        """Close the client."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def run(self, statements: Sequence[_Statement], *, atomic: bool) -> list[list[_Row]]:
        """Send the statements as one batch; a transaction when ``atomic``.

        Each step runs only if the one before succeeded; an atomic batch is wrapped in
        ``BEGIN IMMEDIATE`` ... ``COMMIT``, with a ``ROLLBACK`` when the commit did not happen.

        Args:
            statements: The SQL and its positional arguments, each.
            atomic: Run them in one write transaction.

        Returns:
            Each statement's rows.

        Raises:
            _StatementError: A statement failed.
        """
        if not statements:
            return []
        wrapped = [("BEGIN IMMEDIATE", ()), *statements, ("COMMIT", ())] if atomic else statements
        steps: list[dict[str, object]] = []
        for index, (sql, args) in enumerate(wrapped):
            step: dict[str, object] = {"stmt": {"sql": sql, "args": [_value(a) for a in args]}}
            if index:
                step["condition"] = {"type": "ok", "step": index - 1}
            steps.append(step)
        if atomic:
            committed = {"type": "ok", "step": len(wrapped) - 1}
            steps.append(
                {"stmt": {"sql": "ROLLBACK"}, "condition": {"type": "not", "cond": committed}}
            )
        result = await self._post(
            {"requests": [{"type": "batch", "batch": {"steps": steps}}, {"type": "close"}]}
        )
        errors = result.get("step_errors") or []
        failed = next((e for e in errors[: len(wrapped)] if e), None)
        if failed is not None:
            raise _StatementError(str(failed.get("message", "a statement failed")))
        results = result["step_results"][1 : len(wrapped) - 1] if atomic else result["step_results"]
        return [[tuple(_decoded(v) for v in row) for row in r["rows"]] for r in results]

    async def _post(self, body: Mapping[str, object]) -> Mapping[str, Any]:
        """Send one pipeline request and return its batch's result.

        Args:
            body: The pipeline request.

        Returns:
            The batch's ``step_results`` and ``step_errors``.

        Raises:
            IndexBackendUnavailableError: No answer, an HTTP error, or not a pipeline answer.
            _StatementError: The server refused the batch itself.
        """
        if self.client is None:
            raise IndexBackendUnavailableError(LIBSQL_BACKEND, "not open")
        try:
            response = await self.client.post("/v2/pipeline", json=body)
        except (httpx2.HTTPError, RuntimeError) as error:
            # Its text may hold the URL: only the kind is told.
            raise IndexBackendUnavailableError(LIBSQL_BACKEND, type(error).__name__) from None
        if response.is_error:
            raise IndexBackendUnavailableError(LIBSQL_BACKEND, f"HTTP {response.status_code}")
        try:
            first = response.json()["results"][0]
            ok = first["type"] == "ok"
            found = first["response"]["result"] if ok else first["error"]["message"]
        except (ValueError, KeyError, TypeError, IndexError) as error:
            reason = f"the answer is not a pipeline result ({type(error).__name__})"
            raise IndexBackendUnavailableError(LIBSQL_BACKEND, reason) from None
        if not ok:
            raise _StatementError(str(found))
        return found


def _fetched(cursor: _Cursor, sql: str, args: Sequence[object]) -> list[_Row]:
    """Run one statement on a ``libsql`` cursor and return its rows.

    Args:
        cursor: The cursor.
        sql: The statement.
        args: Its positional arguments.

    Returns:
        The rows, as tuples.
    """
    return [tuple(row) for row in cursor.execute(sql, tuple(args)).fetchall() or ()]


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- the open connection
class _FileEngine:
    """A local libSQL file, through the ``libsql`` package, on one thread of its own."""

    path: str
    """The database file."""
    connection: Any = field(default=None, init=False, repr=False)
    """The ``libsql`` connection, used on ``executor``'s thread only."""
    executor: ThreadPoolExecutor | None = field(default=None, init=False, repr=False)
    """The thread every call runs on, between ``open`` and ``close``."""

    async def open(self) -> None:
        """Open (or create) the file in WAL mode, on the backend's thread."""
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="exactdocs-libsql")
        await self._call(self._connect)

    async def close(self) -> None:
        """Close the connection and stop the thread."""
        if self.executor is None:
            return
        try:
            await self._call(self._disconnect)
        finally:
            self.executor.shutdown(wait=False)
            self.executor = None

    async def run(self, statements: Sequence[_Statement], *, atomic: bool) -> list[list[_Row]]:
        """Run the statements on the backend's thread; in a transaction when ``atomic``.

        Args:
            statements: The SQL and its positional arguments, each.
            atomic: Run them in one write transaction.

        Returns:
            Each statement's rows.
        """
        if not statements:
            return []
        return await self._call(lambda: self._run(statements, atomic=atomic))

    async def _call[T](self, work: Callable[[], T]) -> T:
        """Run ``work`` on the backend's thread.

        Args:
            work: A function without arguments.

        Returns:
            What it returned.

        Raises:
            IndexBackendUnavailableError: The backend is not open.
            _StatementError: The driver raised (a statement failed, or the file cannot be used).
        """
        if self.executor is None:
            raise IndexBackendUnavailableError(LIBSQL_BACKEND, "not open")
        try:
            return await asyncio.get_running_loop().run_in_executor(self.executor, work)
        except Exception as error:  # ruff: ignore[blind-except] -- the driver's own types and ValueError
            raise _StatementError(str(error) or type(error).__name__) from None

    def _connect(self) -> None:
        """Open the file (on the backend's thread)."""
        driver: Any = importlib.import_module("libsql")
        self.connection = driver.connect(self.path, isolation_level=None)
        cursor = self.connection.cursor()
        cursor.execute(f"PRAGMA busy_timeout={LIBSQL_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA journal_mode=WAL")

    def _disconnect(self) -> None:
        """Close the file (on the backend's thread)."""
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _run(self, statements: Sequence[_Statement], *, atomic: bool) -> list[list[_Row]]:
        """Run the statements (on the backend's thread).

        Args:
            statements: The SQL and its positional arguments, each.
            atomic: Run them in one write transaction.

        Returns:
            Each statement's rows.
        """
        cursor: _Cursor = self.connection.cursor()
        if not atomic:
            return [_fetched(cursor, sql, args) for sql, args in statements]
        cursor.execute("BEGIN IMMEDIATE", ())
        try:
            found = [_fetched(cursor, sql, args) for sql, args in statements]
        except BaseException:
            cursor.execute("ROLLBACK", ())
            raise
        cursor.execute("COMMIT", ())
        return found


def _tag_condition(tag_filter: TagFilter) -> tuple[str, list[object]]:
    """Return the SQL condition of a tag filter on an entry ``e``, and its argument.

    Args:
        tag_filter: The filter.

    Returns:
        The condition (empty without tags) and its arguments.
    """
    if not tag_filter.tags:
        return "", []
    return LIBSQL_TAG_CONDITIONS[tag_filter.match.value], [json.dumps(list(tag_filter.tags))]


def _marks(count: int) -> str:
    """Return ``count`` comma-separated placeholders.

    Args:
        count: How many.

    Returns:
        ``?, ?, ...``.
    """
    return ", ".join("?" * count)


def _held(rows: Sequence[_Row]) -> list[HeldVersion]:
    """Turn ``(manifest_id, library, count)`` rows into held versions.

    Args:
        rows: The rows, by manifest ID.

    Returns:
        One per version held.
    """
    return [HeldVersion(manifest_id=m, library=lib, entries=int(n)) for m, lib, n in rows]


def _blob(vector: Sequence[float]) -> bytes:
    """Pack a vector as libSQL's ``F32_BLOB`` holds it (little-endian float32).

    Args:
        vector: The values.

    Returns:
        The bytes.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def _match(query: TextQuery) -> str:
    """Build the FTS5 query: every term quoted, OR-ed (nothing typed reaches FTS5's syntax).

    Args:
        query: The query and its terms.

    Returns:
        The FTS5 query.
    """
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in query.terms)


@dataclass(frozen=True, slots=True, kw_only=True)
class LibsqlSearchBackend:
    """Implements ``ports.driven.SearchBackend`` with FTS5 in libSQL, ranked as on SQLite."""

    engine: _Engine = field(repr=False)
    """The server or the local file."""
    prefix: str = LIBSQL_DEFAULT_PREFIX
    """What every table name starts with."""
    name: str = LIBSQL_BACKEND
    """The registered name."""

    @property
    def _tables(self) -> dict[str, str]:
        """The table names the SQL templates take: ``entries`` and ``fts``."""
        return {"entries": f"{self.prefix}_search_entries", "fts": f"{self.prefix}_search"}

    async def open(self) -> None:
        """Connect and create the tables if they are not there (FTS5 is checked by that)."""
        await self.engine.open()
        await self.engine.run(
            [(sql.format(**self._tables), ()) for sql in LIBSQL_SEARCH_TABLES], atomic=True
        )

    async def close(self) -> None:
        """Release the connection."""
        await self.engine.close()

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries and their FTS5 rows, in one transaction.

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        upsert, index = (sql.format(**self._tables) for sql in LIBSQL_SEARCH_PUT)
        statements: list[_Statement] = []
        for e in entries:
            row = fts_row(0, e.heading_path, e.content)
            tags = json.dumps(list(e.tags))
            fts = (row["heading"], row["path"], row["text"], row["identifiers"])
            statements.extend(
                [
                    (upsert, (manifest.manifest_id, e.chunk_id, e.library, tags)),
                    (index, (manifest.manifest_id, e.chunk_id, *fts)),
                ]
            )
        await self.engine.run(statements, atomic=True)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries and FTS5 rows.

        Args:
            manifest_ids: The versions.
        """
        ids = sorted(set(manifest_ids))
        if not ids:
            return
        names = {**self._tables, "ids": _marks(len(ids))}
        await self.engine.run(
            [(sql.format(**names), ids) for sql in LIBSQL_SEARCH_DELETE], atomic=True
        )

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """List the versions held, with their entry counts.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID.
        """
        where, args = ("WHERE library = ?", [library]) if library is not None else ("", [])
        sql = LIBSQL_HELD.format(table=self._tables["entries"], where=where)
        (rows,) = await self.engine.run([(sql, args)], atomic=False)
        return _held(rows)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' entries with FTS5's ``bm25()``, weighted as ExactDocs' SQLite index.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first; ties by chunk ID, then manifest ID.
        """
        ids = list(dict.fromkeys(manifest_ids))
        if not ids or not query.terms or limit <= 0:
            return []
        tags, tag_args = _tag_condition(tag_filter)
        sql = LIBSQL_SEARCH.format(**self._tables, ids=_marks(len(ids)), tags=tags)
        weights = [HEADING_WEIGHT, PATH_WEIGHT, TEXT_WEIGHT, IDENTIFIERS_WEIGHT]
        (rows,) = await self.engine.run(
            [(sql, [*weights, _match(query), *ids, *tag_args, limit])], atomic=False
        )
        return [BackendHit(manifest_id=m, chunk_id=ChunkId(c), score=float(s)) for m, c, s in rows]

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
        ids = list(dict.fromkeys(manifest_ids))
        if not ids or not query.terms:
            return {}
        tags, tag_args = _tag_condition(tag_filter)
        sql = LIBSQL_COUNT.format(**self._tables, ids=_marks(len(ids)), tags=tags)
        (rows,) = await self.engine.run([(sql, [_match(query), *ids, *tag_args])], atomic=False)
        return {m: int(n) for m, n in rows}


@dataclass(frozen=True, slots=True, kw_only=True)
class LibsqlVectorBackend:
    """Implements ``ports.driven.VectorBackend`` with libSQL's native vectors and vector index."""

    engine: _Engine = field(repr=False)
    """The server or the local file."""
    prefix: str = LIBSQL_DEFAULT_PREFIX
    """What every table name starts with."""
    compress_neighbors: str = LIBSQL_DEFAULT_COMPRESSION
    """How the vector index stores a neighbour's vector (``float8``, ``float1bit``...)."""
    max_neighbors: int | None = None
    """The most neighbours of a node in the index; ``None``: libSQL's default."""
    name: str = LIBSQL_BACKEND
    """The registered name."""
    known: dict[EmbeddingSpaceId, int] = field(default_factory=dict, repr=False)
    """The spaces this process found or made in the registry, with their dimensions."""

    @property
    def _spaces(self) -> str:
        """The registry of spaces: their IDs and dimensions."""
        return f"{self.prefix}_spaces"

    def _table(self, space_id: EmbeddingSpaceId | int) -> str:
        """Name a space's table.

        Args:
            space_id: The space.

        Returns:
            ``<prefix>_space_<id>``.
        """
        return f"{self.prefix}_space_{int(space_id)}"

    async def open(self) -> None:
        """Connect, check that it has native vectors, and create the registry.

        Raises:
            IndexBackendUnavailableError: It is not libSQL (no ``vector32``).
        """
        await self.engine.open()
        try:
            await self.engine.run([(LIBSQL_VECTOR_CHECK, ())], atomic=False)
        except _StatementError as error:
            reason = f"no native vectors here, is it libSQL? ({error.reason})"
            raise IndexBackendUnavailableError(self.name, reason) from None
        await self.engine.run([(LIBSQL_SPACES_TABLE.format(spaces=self._spaces), ())], atomic=True)

    async def close(self) -> None:
        """Release the connection."""
        await self.engine.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries in the space's table, creating it on the first put.

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.

        Raises:
            _StatementError: A statement failed (a missing table is not an error here).
        """
        sql = LIBSQL_VECTOR_PUT.format(table=self._table(space.id))
        statements: list[_Statement] = [
            (
                sql,
                (
                    manifest.manifest_id,
                    e.chunk_id,
                    e.library,
                    json.dumps(list(e.tags)),
                    _blob(e.vector),
                ),
            )
            for e in entries
            if e.vector is not None
        ]
        await self._ensure(space)
        try:
            await self.engine.run(statements, atomic=True)
        except _StatementError as error:
            if not error.missing_table:
                raise
            self.known.pop(space.id, None)  # dropped by another process since: make it again
            await self._ensure(space)
            await self.engine.run(statements, atomic=True)

    async def _ensure(self, space: EmbeddingSpace) -> None:
        """Create the space's table and vector index unless they are there with its dimensions.

        Args:
            space: The space.

        Raises:
            IndexBackendUnavailableError: The registry holds the space with other dimensions
                (another ExactDocs instance with the same ``prefix``).
        """
        dimensions = space.spec.dimensions
        if self.known.get(space.id) == dimensions:
            return
        table = self._table(space.id)
        settings = ["'metric=cosine'", f"'compress_neighbors={self.compress_neighbors}'"]
        if self.max_neighbors is not None:
            settings.append(f"'max_neighbors={self.max_neighbors}'")
        names = {
            "spaces": self._spaces,
            "table": table,
            "dimensions": dimensions,
            "settings": ", ".join(settings),
        }
        register, *create, read = (sql.format(**names) for sql in LIBSQL_SPACE_CREATE)
        found = await self.engine.run(
            [
                (register, (int(space.id), dimensions)),
                *((sql, ()) for sql in create),
                (read, (int(space.id),)),
            ],
            atomic=True,
        )
        held = int(found[-1][0][0])
        if held != dimensions:
            reason = (
                f"the table {table} holds vectors of {held} dimensions, not {dimensions}: "
                "another instance uses this prefix"
            )
            raise IndexBackendUnavailableError(self.name, reason)
        self.known[space.id] = dimensions

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space; an unknown space is a no-op.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.

        Raises:
            _StatementError: A statement failed (a missing table is not an error here).
        """
        ids = sorted(set(chunk_ids))
        if not ids:
            return
        sql = LIBSQL_VECTOR_REMOVE.format(table=self._table(space_id), ids=_marks(len(ids)))
        try:
            await self.engine.run([(sql, [manifest_id, *ids])], atomic=True)
        except _StatementError as error:
            if not error.missing_table:
                raise
            self.known.pop(space_id, None)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries in every space, in one transaction.

        Args:
            manifest_ids: The versions.

        Raises:
            _StatementError: A statement failed (a missing table is not an error here).
        """
        ids = sorted(set(manifest_ids))
        if not ids:
            return
        try:
            await self._delete(ids)
        except _StatementError as error:
            if not error.missing_table:
                raise
            await self._delete(ids)  # a space was dropped meanwhile: the registry has moved on

    async def _delete(self, ids: Sequence[str]) -> None:
        """Delete the versions' entries in every space the registry lists now.

        Args:
            ids: The versions.
        """
        (spaces,) = await self.engine.run(
            [(LIBSQL_SPACE_IDS.format(spaces=self._spaces), ())], atomic=False
        )
        marks = _marks(len(ids))
        await self.engine.run(
            [
                (LIBSQL_VECTOR_DELETE.format(table=self._table(int(s)), ids=marks), ids)
                for (s,) in spaces
            ],
            atomic=True,
        )

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Drop the space's vector index and table, and forget it.

        Args:
            space_id: The space.
        """
        self.known.pop(space_id, None)
        names = {"spaces": self._spaces, "table": self._table(space_id)}
        *drops, forget = (sql.format(**names) for sql in LIBSQL_SPACE_DROP)
        await self.engine.run(
            [*((sql, ()) for sql in drops), (forget, (int(space_id),))], atomic=True
        )

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the space holds; empty for an unknown space.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID.

        Raises:
            _StatementError: A statement failed (a missing table is not an error here).
        """
        where, args = ("WHERE library = ?", [library]) if library is not None else ("", [])
        sql = LIBSQL_HELD.format(table=self._table(space_id), where=where)
        try:
            (rows,) = await self.engine.run([(sql, args)], atomic=False)
        except _StatementError as error:
            if not error.missing_table:
                raise
            self.known.pop(space_id, None)
            return []
        return _held(rows)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Find the versions' entries nearest to the query, through the vector index.

        The index is shared by every version of the space, so it is asked for enough neighbours
        that the asked versions' share of them fills the limit; those are kept (filtered by
        version and tags in SQL) and ranked by their exact cosine distance. When that share is
        too small for the index to give enough, the asked versions' vectors are scanned exactly.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries, nearest first; ties by chunk ID, then manifest ID.

        Raises:
            _StatementError: A statement failed (a missing table is not an error here).
        """
        ids = list(dict.fromkeys(manifest_ids))
        if not ids or limit <= 0:
            return []
        tags, tag_args = _tag_condition(tag_filter)
        names = {"table": self._table(space.id), "ids": _marks(len(ids)), "tags": tags}
        scoped, everything = (sql.format(**names) for sql in LIBSQL_NEAREST_SIZES)
        try:
            (held,), (top,) = await self.engine.run(
                [(scoped, [*ids, *tag_args]), (everything, ())], atomic=False
            )
        except _StatementError as error:
            if not error.missing_table:
                raise
            self.known.pop(space.id, None)
            return []
        count, rows = int(held[0]), int(top[0])
        if not count:
            return []
        blob = _blob(query)
        wanted = min(limit, count)
        k = math.ceil(wanted * LIBSQL_ANN_OVERFETCH * rows / count)
        found: list[_Row] = []
        if k < min(rows, LIBSQL_ANN_MAX_CANDIDATES):
            sql = LIBSQL_NEAREST_INDEX.format(**names, k=k)
            (found,) = await self.engine.run(
                [(sql, [blob, blob, *ids, *tag_args, limit])], atomic=False
            )
        if len(found) < wanted:  # the index gave too few of theirs: compare all of theirs
            sql = LIBSQL_NEAREST_SCAN.format(**names)
            (found,) = await self.engine.run([(sql, [blob, *ids, *tag_args, limit])], atomic=False)
        return [
            BackendNeighbour(manifest_id=m, chunk_id=ChunkId(c), distance=max(0.0, float(d)))
            for m, c, d in found
        ]


@dataclass(frozen=True, slots=True, kw_only=True)
class _Options:
    """The ``[index_backends.libsql]`` options, checked."""

    engine: _Engine
    """How to reach libSQL."""
    prefix: str
    """What every table name starts with."""
    compress_neighbors: str
    """How the vector index stores a neighbour's vector."""
    max_neighbors: int | None
    """The most neighbours of a node in the vector index."""


def _text(options: Mapping[str, object], name: str) -> str | None:
    """Read a text option; blank is unset.

    Args:
        options: The options.
        name: The option.

    Returns:
        The trimmed text, or ``None``.

    Raises:
        TypeError: It is not text.
    """
    value = options.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        message = f"{name} must be text"
        raise TypeError(message)
    return value.strip() or None


def _as_float(value: object) -> float:
    """Read a number given as a number or as text; NaN when it is neither.

    Args:
        value: The option's value.

    Returns:
        The number, or NaN.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return math.nan
    try:
        return float(value)
    except ValueError:
        return math.nan


def _number(options: Mapping[str, object], name: str) -> float | None:
    """Read a positive number option (from the environment it comes as text).

    Args:
        options: The options.
        name: The option.

    Returns:
        The number, or ``None`` when unset.

    Raises:
        ValueError: It is not a positive number.
    """
    value = options.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = _as_float(value)
    if not math.isfinite(number) or number <= 0:
        message = f"{name} must be a positive number"
        raise ValueError(message)
    return number


def _token(options: Mapping[str, object]) -> str | None:
    """Read the auth token from ``auth_token`` or ``auth_token_file``.

    Args:
        options: The options.

    Returns:
        The token, or ``None`` when neither is set.

    Raises:
        ValueError: Both are set, or the file cannot be read (its content is never shown).
    """
    token, path = _text(options, "auth_token"), _text(options, "auth_token_file")
    if token is not None and path is not None:
        message = "set auth_token or auth_token_file, not both"
        raise ValueError(message)
    if path is None:
        return token
    try:
        return Path(path).expanduser().read_text("utf-8").strip() or None
    except OSError as error:
        message = f"auth_token_file cannot be read ({type(error).__name__})"
        raise ValueError(message) from None


def _file_engine(url: str, token: str | None) -> _Engine:
    """Make the engine of a local file.

    Args:
        url: ``file:<path>``, ``file://<path>`` or a path.
        token: The auth token (must be unset).

    Returns:
        The engine (not open yet).

    Raises:
        ValueError: A token is set, or the ``libsql`` extra is not installed.
    """
    if token is not None:
        message = "auth_token is for a libSQL server, not a local file"
        raise ValueError(message)
    if importlib.util.find_spec("libsql") is None:
        message = (
            "a local libSQL file needs the libsql extra: pip install 'exactdocs[libsql]' "
            "(or name a libSQL server: libsql://, https:// or http://)"
        )
        raise ValueError(message)
    path = url.removeprefix("file://").removeprefix("file:")
    return _FileEngine(path=str(Path(path).expanduser()))


def _engine(url: str, token: str | None, timeout: float) -> _Engine:
    """Make the engine the URL names: a server over HTTP, or a local file.

    Args:
        url: The ``url`` option.
        token: The auth token, for a server.
        timeout: Seconds one request to a server may take.

    Returns:
        The engine (not open yet).

    Raises:
        ValueError: The URL is not a libSQL server's or a file's.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in {"", "file"}:
        return _file_engine(url, token)
    if scheme not in LIBSQL_URL_SCHEMES or not parts.hostname:
        message = (
            "url must be libsql://host, https://host, http://host[:port], or a local file "
            "(file:<path>)"
        )
        raise ValueError(message)
    if parts.path.strip("/") or parts.username or parts.password:
        message = "url must name the server only (no path, user or password: use auth_token)"
        raise ValueError(message)
    tls = parse_qs(parts.query).get("tls", ["1"])[-1] != "0"
    http = ("https" if tls else "http") if scheme == "libsql" else scheme
    return _HttpEngine(url=f"{http}://{parts.netloc}", token=token, timeout=timeout)


def _options(options: Mapping[str, object]) -> _Options:
    """Check the ``[index_backends.libsql]`` options.

    Args:
        options: The options, from the TOML file or the environment.

    Returns:
        The checked options.

    Raises:
        ValueError: An option is unknown or invalid.
    """
    unknown = sorted(set(options) - LIBSQL_OPTIONS)
    if unknown:
        message = (
            f"unknown option(s) {', '.join(unknown)}; the libsql backend takes "
            f"{', '.join(sorted(LIBSQL_OPTIONS))}"
        )
        raise ValueError(message)
    url = _text(options, "url")
    if url is None:
        message = "url is required: libsql://host, https://host or file:<path>"
        raise ValueError(message)
    prefix = _text(options, "prefix") or LIBSQL_DEFAULT_PREFIX
    if not LIBSQL_PREFIX.fullmatch(prefix):
        message = "prefix must start with a letter and hold letters, digits and _ (at most 40)"
        raise ValueError(message)
    compression = (_text(options, "compress_neighbors") or LIBSQL_DEFAULT_COMPRESSION).lower()
    if compression not in LIBSQL_COMPRESSIONS:
        message = f"compress_neighbors must be one of {', '.join(sorted(LIBSQL_COMPRESSIONS))}"
        raise ValueError(message)
    neighbours = _number(options, "max_neighbors")
    if neighbours is not None and not neighbours.is_integer():
        message = "max_neighbors must be a whole number"
        raise ValueError(message)
    timeout = _number(options, "timeout") or LIBSQL_DEFAULT_TIMEOUT_SECONDS
    return _Options(
        engine=_engine(url, _token(options), timeout),
        prefix=prefix,
        compress_neighbors=compression,
        max_neighbors=None if neighbours is None else int(neighbours),
    )


def search_backend(options: Mapping[str, object]) -> LibsqlSearchBackend:
    """Build the search backend from its ``[index_backends.libsql]`` options.

    ``ValueError`` (or ``TypeError``) for an unknown or invalid option.

    Args:
        options: ``url`` (required), ``auth_token`` / ``auth_token_file``, ``prefix``,
            ``timeout``.

    Returns:
        The backend, not connected yet.
    """
    checked = _options(options)
    return LibsqlSearchBackend(engine=checked.engine, prefix=checked.prefix)


def vector_backend(options: Mapping[str, object]) -> LibsqlVectorBackend:
    """Build the vector backend from its ``[index_backends.libsql]`` options.

    ``ValueError`` (or ``TypeError``) for an unknown or invalid option.

    Args:
        options: ``url`` (required), ``auth_token`` / ``auth_token_file``, ``prefix``,
            ``timeout``, ``compress_neighbors``, ``max_neighbors``.

    Returns:
        The backend, not connected yet.
    """
    checked = _options(options)
    return LibsqlVectorBackend(
        engine=checked.engine,
        prefix=checked.prefix,
        compress_neighbors=checked.compress_neighbors,
        max_neighbors=checked.max_neighbors,
    )
