"""Redis (Query Engine) as the search and vector backend (#364): ``EXACTDOCS_*_BACKEND=redis``.

Every entry is one hash: ``<prefix>:search:<manifest>:<chunk>`` for the full-text index and
``<prefix>:space<id>:<manifest>:<chunk>`` for an embedding space. Each kind has its index, made
with ``FT.CREATE`` on the first write when missing: ``<prefix>:search``, and one
``<prefix>:space<id>`` per space with a ``VECTOR`` field of the space's dimensions (cosine). Both
carry ``manifest_id``, ``library``, ``version_id``, ``chunk_id`` and ``tags`` as ``TAG`` fields,
and every query filters on the asked versions' ``manifest_id`` (and the tags) in Redis, before
ranking, so another version's chunks are never returned. The text is indexed as
``identifier_tokens`` (whole identifiers and their parts), in three ``TEXT`` fields weighted as
the database's indexes weigh them (the section's heading, its ancestors, its text), ranked with
BM25. With the ``hybrid`` option, a space's hashes carry that text too and ``hybrid`` is one
``FT.HYBRID`` query (Redis 8.4 or later): the words and the vector, fused by Redis with
reciprocal rank fusion.

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Its client, ``redis`` (redis-py), is the ``redis`` extra; only this module imports it.
"""

import asyncio
import re
import struct
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import SplitResult, unquote, urlsplit

from redis.asyncio import Redis
from redis.exceptions import AuthenticationError, NoPermissionError, RedisError, ResponseError

from exactdocs.retrieval.constants import (
    EXTERNAL_HIT_MARGIN,
    HEADING_WEIGHT,
    PATH_WEIGHT,
    REDIS_BACKEND,
    REDIS_DEFAULT_PORT,
    REDIS_DEFAULT_PREFIX,
    REDIS_DEFAULT_TIMEOUT_SECONDS,
    REDIS_DELETE_BATCH,
    REDIS_FALSE,
    REDIS_OPTIONS,
    REDIS_PREFIX,
    REDIS_SCORER,
    REDIS_TAG_SEPARATOR,
    REDIS_TRUE,
    REDIS_VECTOR_ALGORITHMS,
    REDIS_WRITE_BATCH,
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
    VectorMetric,
    identifier_tokens,
)

type Connect = Callable[[], Redis]
"""Makes a new client; called by each ``open()`` (a client is bound to the event loop it ran in)."""
type Row = dict[str, str]
"""One result of a query: its fields (and ``id``, the key, for ``FT.SEARCH``), decoded."""

_MISSING_INDEX = ("no such index", "unknown index name", "index not found")
"""What the Query Engine says, in one version or another, about an index that does not exist."""
_TAG_FIELDS = ("manifest_id", "library", "version_id", "chunk_id")
"""The ``TAG`` fields of every index, besides ``tags``."""
_SORTABLE = frozenset({"manifest_id", "library", "chunk_id"})
"""The fields queries group or sort on: kept sortable, so no hash is read to do it."""
_TLS_FILES = ("tls_ca_file", "tls_cert_file", "tls_key_file")
"""The TLS options: the CA that signed the server's certificate, and a client certificate."""


def _escape(value: str) -> str:
    """Escape a value for the query syntax: every ASCII character but letters, digits and ``_``.

    Letters of other scripts are left as they are (the Query Engine reads them as letters).

    Args:
        value: A term or a tag.

    Returns:
        The value, each such character preceded by a backslash.
    """
    return "".join(
        f"\\{ch}" if ch.isascii() and not ch.isalnum() and ch != "_" else ch for ch in value
    )


def _indexed_text(text: str) -> str:
    """Make a ``TEXT`` field's value: the identifier tokens, ``-`` and ``.`` kept in a token.

    The Query Engine splits words on punctuation unless it is escaped, and the tokens of
    ``identifier_tokens`` keep ``-`` and ``.`` inside (``--dry-run``, ``v1.2``).

    Args:
        text: Headings or a chunk's text.

    Returns:
        The tokens, separated by spaces, ``-`` and ``.`` escaped.
    """
    return identifier_tokens(text).replace("-", "\\-").replace(".", "\\.")


def _text_fields(entry: IndexEntry) -> dict[str, str | bytes]:
    """Return an entry's three ``TEXT`` fields: its heading, the headings above, its text.

    Args:
        entry: The entry.

    Returns:
        The fields, by name.
    """
    heading = entry.heading_path[-1] if entry.heading_path else ""
    return {
        "heading": _indexed_text(heading),
        "path": _indexed_text(" / ".join(entry.heading_path[:-1])),
        "text": _indexed_text(entry.content),
    }


def _tag_fields(entry: IndexEntry) -> dict[str, str | bytes]:
    """Return an entry's ``TAG`` fields (``tags`` left out when it has none), and its path.

    Args:
        entry: The entry.

    Returns:
        The fields, by name.
    """
    fields: dict[str, str | bytes] = {
        "manifest_id": entry.manifest_id,
        "library": entry.library,
        "version_id": entry.version_id,
        "chunk_id": entry.chunk_id,
        "article_path": entry.article_path,
    }
    if entry.tags:
        fields["tags"] = REDIS_TAG_SEPARATOR.join(entry.tags)
    return fields


def _any_of(name: str, values: Collection[str]) -> str:
    """Match a ``TAG`` field against any of these values.

    Args:
        name: The field.
        values: The values (at least one).

    Returns:
        ``@name:{a|b}``, each value escaped.
    """
    return f"@{name}:{{{'|'.join(_escape(v) for v in values)}}}"


def _filter(manifest_ids: Collection[str], tag_filter: TagFilter) -> str:
    """Filter a query to these versions and the tag filter (applied before ranking).

    Args:
        manifest_ids: The versions searched (at least one).
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The query's filter clauses.
    """
    clauses = [_any_of("manifest_id", dict.fromkeys(manifest_ids))]
    if tag_filter.tags and tag_filter.match is TagMatch.ALL:
        clauses += [_any_of("tags", [t]) for t in tag_filter.tags]
    elif tag_filter.tags:
        clauses.append(_any_of("tags", tag_filter.tags))
    return " ".join(clauses)


def _words(terms: Collection[str]) -> str:
    """Match any of the terms in the ``TEXT`` fields (they are alternatives, never syntax).

    Args:
        terms: The query's terms (at least one).

    Returns:
        ``(@heading|path|text:(a|b))``, each term escaped.
    """
    return f"(@heading|path|text:({'|'.join(_escape(t) for t in dict.fromkeys(terms))}))"


def _vector_bytes(vector: Sequence[float]) -> bytes:
    """Pack a vector as the ``FLOAT32`` field holds it (little-endian).

    Args:
        vector: The values.

    Returns:
        Four bytes per value.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def _distance(metric: VectorMetric) -> str:
    """Map a space's metric to the Query Engine's ``DISTANCE_METRIC``.

    Args:
        metric: The space's metric.

    Returns:
        Its name in ``FT.CREATE``.
    """
    match metric:
        case VectorMetric.COSINE:
            return "COSINE"


def _text(value: object) -> str:
    """Decode a value of a reply (the client keeps replies as bytes).

    Args:
        value: Bytes or text.

    Returns:
        The text.
    """
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _get(reply: object, key: str) -> object:
    """Read one key of a reply map (RESP3), whose keys are bytes.

    Args:
        reply: The map.
        key: The key.

    Returns:
        Its value, or ``None``.
    """
    if not isinstance(reply, Mapping):
        return None
    return reply.get(key.encode(), reply.get(key))


def _items(value: object) -> list[object]:
    """Read a list of a reply.

    Args:
        value: The list (or nothing).

    Returns:
        Its items; none when it is not a list.
    """
    return list(value) if isinstance(value, list | tuple | set) else []


def _rows(reply: object) -> list[Row]:
    """Read the rows of an ``FT.SEARCH`` / ``FT.AGGREGATE`` / ``FT.HYBRID`` reply (RESP3).

    Args:
        reply: The reply.

    Returns:
        Each row's fields, decoded (``id`` too, for a search).
    """
    rows: list[Row] = []
    for result in _items(_get(reply, "results")):
        key = _get(result, "id")
        values = _get(result, "extra_attributes")
        if values is None:  # FT.HYBRID: the fields are the row itself; NOCONTENT: none
            values = {} if key is not None else result
        row = {_text(k): _text(v) for k, v in values.items()} if isinstance(values, Mapping) else {}
        if key is not None:
            row["id"] = _text(key)
        rows.append(row)
    return rows


def _timed_out(reply: object) -> bool:
    """Tell whether a query ran out of time (it would answer with part of its results).

    Args:
        reply: The reply.

    Returns:
        True when a warning says so.
    """
    warnings = _items(_get(reply, "warning")) + _items(_get(reply, "warnings"))
    return any("timeout" in _text(w).lower() for w in warnings)


def _short(error: BaseException) -> str:
    """Return an error's message on one line, cut at 200 characters.

    Args:
        error: The error.

    Returns:
        The message.
    """
    return " ".join(str(error).split())[:200]


def _reason(error: BaseException) -> str:
    """Say briefly why Redis did not answer, never with a credential.

    Args:
        error: What the client raised.

    Returns:
        The kind of failure, with the server's own message for a refused command.
    """
    if isinstance(error, AuthenticationError):
        return "authentication failed: check username and password"
    if isinstance(error, NoPermissionError):
        return f"permission denied ({_short(error)})"
    if isinstance(error, ResponseError):
        return _short(error)
    if isinstance(error, RedisError):
        return f"{type(error).__name__}: {_short(error)}"
    return type(error).__name__


def _missing_index(error: ResponseError) -> bool:
    """Tell whether the server refused a command because its index does not exist.

    Args:
        error: The refusal.

    Returns:
        True for a missing index.
    """
    message = str(error).lower()
    return any(m in message for m in _MISSING_INDEX)


def _schema(*, text: bool) -> list[object]:
    """Return the ``SCHEMA`` arguments both kinds of index share.

    Args:
        text: Include the three weighted ``TEXT`` fields.

    Returns:
        The arguments.
    """
    schema: list[object] = []
    for name in _TAG_FIELDS:
        schema += [name, "TAG", "CASESENSITIVE", *(["SORTABLE"] if name in _SORTABLE else [])]
    schema += ["tags", "TAG", "SEPARATOR", REDIS_TAG_SEPARATOR, "CASESENSITIVE"]
    if text:
        weights = (("heading", HEADING_WEIGHT), ("path", PATH_WEIGHT), ("text", TEXT_WEIGHT))
        for name, weight in weights:
            schema += [name, "TEXT", "WEIGHT", weight, "NOSTEM"]
    return schema


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class _RedisIndex:
    """What both backends share: the client, and the indexes known to exist in this process."""

    connect: Connect
    """Makes the client ``open()`` uses until ``close()``."""
    prefix: str = REDIS_DEFAULT_PREFIX
    """Names this instance's indexes and keys: ``<prefix>:search``, ``<prefix>:space<id>``."""
    timeout_ms: int = REDIS_DEFAULT_TIMEOUT_SECONDS * 1000
    """Each query's ``TIMEOUT``."""
    hybrid_words: bool = False
    """Write each vector's words too, and check at ``open()`` that ``FT.HYBRID`` is there."""
    name: str = REDIS_BACKEND
    """The registered name."""
    _client: Redis | None = field(default=None, init=False, repr=False)
    """The open client; ``None`` before ``open()`` and after ``close()``."""
    _ready: set[str] = field(default_factory=set, init=False, repr=False)
    """The indexes known to exist (with the right schema), in this process."""
    _setting_up: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    """Lets one task create an index at a time."""

    async def open(self) -> None:
        """Connect and check that Redis answers, with the Query Engine (and ``FT.HYBRID``).

        Raises:
            IndexBackendUnavailableError: It cannot be reached, refused the credentials, or has
                no Query Engine (or no ``FT.HYBRID`` while ``hybrid`` is on).
        """
        await self.close()
        self._client = self.connect()
        self._ready.clear()
        await self._call(self._client.ping())
        try:
            await self._client.execute_command("FT._LIST")
        except ResponseError as error:
            reason = _reason(error)
            if "unknown command" in reason.lower():
                reason = "the server has no Query Engine (FT.* commands): use Redis 8 or later"
            raise IndexBackendUnavailableError(self.name, reason) from error
        except (RedisError, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        if self.hybrid_words:
            await self._check_hybrid()

    async def _check_hybrid(self) -> None:
        """Check the server has ``FT.HYBRID`` (Redis 8.4 or later), for the ``hybrid`` option.

        A user not allowed to run ``COMMAND INFO`` is not refused: the first hybrid search tells.

        Raises:
            IndexBackendUnavailableError: The server does not know ``FT.HYBRID``.
        """
        try:
            found = await self._open().execute_command("COMMAND", "INFO", "FT.HYBRID")
        except NoPermissionError:
            return
        except (RedisError, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        known = list(found.values()) if isinstance(found, Mapping) else _items(found)
        if not any(known):
            reason = "the server has no FT.HYBRID (Redis 8.4 or later): set hybrid = false"
            raise IndexBackendUnavailableError(self.name, reason)

    async def close(self) -> None:
        """Close the client, if open."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def _open(self) -> Redis:
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
            IndexBackendUnavailableError: Redis did not answer, or refused the command.
        """
        try:
            return await call
        except (RedisError, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error

    async def _query(self, command: str, index: str, *args: object) -> object | None:
        """Run a command on an index; ``None`` when the index does not exist.

        Args:
            command: ``FT.SEARCH``, ``FT.AGGREGATE``...
            index: The index.
            *args: The rest of the command.

        Returns:
            The reply, or ``None`` for a missing index.

        Raises:
            IndexBackendUnavailableError: Redis did not answer, refused the command, or ran out
                of time (rather than answer with part of the results).
        """
        try:
            reply = await self._open().execute_command(command, index, *args)
        except ResponseError as error:
            if _missing_index(error):
                self._ready.discard(index)
                return None
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        except (RedisError, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        if _timed_out(reply):
            raise IndexBackendUnavailableError(self.name, f"a query on {index!r} timed out")
        return reply

    def _limits(self) -> list[object]:
        """Return the arguments every query ends with: its ``TIMEOUT`` and ``DIALECT 2``.

        Returns:
            The arguments.
        """
        return ["TIMEOUT", self.timeout_ms, "DIALECT", 2]

    async def _ensure(
        self, index: str, schema: Sequence[object], check: Callable[[object], None]
    ) -> None:
        """Create an index with ``FT.CREATE`` when it is missing, and check one that exists.

        Args:
            index: The index (its keys are those starting with ``<index>:``).
            schema: The ``SCHEMA`` arguments.
            check: Raises ``IndexBackendUnavailableError`` when an existing index cannot be
                used (given ``FT.INFO``'s reply).
        """
        if index in self._ready:
            return
        async with self._setting_up:
            if index in self._ready:
                return
            info = await self._query("FT.INFO", index)
            if info is None:
                await self._create(index, schema)
            else:
                check(info)
            self._ready.add(index)

    async def _create(self, index: str, schema: Sequence[object]) -> None:
        """Run ``FT.CREATE`` (one another process created meanwhile is fine).

        Args:
            index: The index.
            schema: The ``SCHEMA`` arguments.

        Raises:
            IndexBackendUnavailableError: Redis did not create it.
        """
        definition = ["ON", "HASH", "PREFIX", 1, f"{index}:", "STOPWORDS", 0, "SCHEMA"]
        try:
            await self._open().execute_command("FT.CREATE", index, *definition, *schema)
        except ResponseError as error:
            if "already exists" not in str(error).lower():
                raise IndexBackendUnavailableError(self.name, _reason(error)) from error
        except (RedisError, OSError) as error:
            raise IndexBackendUnavailableError(self.name, _reason(error)) from error

    async def _write(self, hashes: Sequence[tuple[str, dict[str, str | bytes]]]) -> None:
        """Replace hashes, a transaction per batch (``DEL`` then ``HSET``: no field lingers).

        Args:
            hashes: Each hash's key and fields.
        """
        client = self._open()
        for start in range(0, len(hashes), REDIS_WRITE_BATCH):
            pipe = client.pipeline(transaction=True)
            for key, fields in hashes[start : start + REDIS_WRITE_BATCH]:
                pipe.delete(key)
                pipe.hset(key, items=[part for pair in fields.items() for part in pair])
            await self._call(pipe.execute())

    async def _delete_where(self, index: str, query: str) -> None:
        """Unlink every hash of an index that a query matches, a batch at a time.

        Args:
            index: The index.
            query: The filter.
        """
        while True:
            batch = ["NOCONTENT", "LIMIT", 0, REDIS_DELETE_BATCH]
            reply = await self._query("FT.SEARCH", index, query, *batch, *self._limits())
            keys = [row["id"] for row in _rows(reply)]
            if not keys:
                return
            await self._call(self._open().unlink(*keys))

    async def _held(self, index: str, library: str | None) -> list[HeldVersion]:
        """Count an index's hashes per version.

        Args:
            index: The index.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID; empty for a missing index.
        """
        where = "*" if library is None else _any_of("library", [library])
        group = ["GROUPBY", 2, "@manifest_id", "@library", "REDUCE", "COUNT", 0, "AS", "n"]
        reply = await self._query("FT.AGGREGATE", index, where, *group, *self._limits())
        held = [
            HeldVersion(manifest_id=row["manifest_id"], library=row["library"], entries=n)
            for row in _rows(reply)
            if (n := int(row.get("n", 0)))
        ]
        return sorted(held, key=lambda h: h.manifest_id)


def _no_check(info: object) -> None:
    """Accept an existing search index as it is.

    Args:
        info: ``FT.INFO``'s reply.
    """
    del info


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class RedisSearchBackend(_RedisIndex):
    """Implements ``ports.driven.SearchBackend`` over the Query Engine: BM25 on weighted fields."""

    @property
    def index(self) -> str:
        """The full-text index: ``<prefix>:search``."""
        return f"{self.prefix}:search"

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries' hashes (the index is created when missing).

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        del manifest  # every entry names its manifest
        if not entries:
            return
        await self._ensure(self.index, _schema(text=True), _no_check)
        await self._write(
            [
                (f"{self.index}:{e.manifest_id}:{e.chunk_id}", _tag_fields(e) | _text_fields(e))
                for e in entries
            ]
        )

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every hash of these versions.

        Args:
            manifest_ids: The versions.
        """
        if manifest_ids:
            await self._delete_where(self.index, _any_of("manifest_id", manifest_ids))

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """Count the hashes per version.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        return await self._held(self.index, library)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' matching hashes with BM25, filtered in Redis before ranking.

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
        where = f"{_filter(manifest_ids, tag_filter)} {_words(query.terms)}"
        order = ["@__score", "DESC", "@chunk_id", "ASC", "@manifest_id", "ASC"]
        ranked = ["SCORER", REDIS_SCORER, "ADDSCORES", "SORTBY", len(order), *order, "MAX", limit]
        loaded = ["LOAD", 2, "@manifest_id", "@chunk_id"]
        reply = await self._query(
            "FT.AGGREGATE", self.index, where, *ranked, *loaded, *self._limits()
        )
        return [
            BackendHit(
                manifest_id=row["manifest_id"],
                chunk_id=ChunkId(row["chunk_id"]),
                score=float(row["__score"]),
            )
            for row in _rows(reply)
        ]

    async def count(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the matching hashes of each version.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many entries match, by manifest ID; zeros left out.
        """
        if not manifest_ids or not query.terms:
            return {}
        where = f"{_filter(manifest_ids, tag_filter)} {_words(query.terms)}"
        group = ["GROUPBY", 1, "@manifest_id", "REDUCE", "COUNT", 0, "AS", "n"]
        reply = await self._query("FT.AGGREGATE", self.index, where, *group, *self._limits())
        return {row["manifest_id"]: n for row in _rows(reply) if (n := int(row.get("n", 0)))}


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class RedisVectorBackend(_RedisIndex):
    """Implements ``ports.driven.VectorBackend`` over the Query Engine: one index per space."""

    algorithm: str = "hnsw"
    """``hnsw`` (approximate, the default) or ``flat`` (exact): the ``VECTOR`` field's kind."""

    def _index(self, space_id: EmbeddingSpaceId) -> str:
        """Name a space's index.

        Args:
            space_id: The space.

        Returns:
            ``<prefix>:space<id>``.
        """
        return f"{self.prefix}:space{space_id}"

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' hashes in the space's index (created when missing).

        Args:
            space: The space: its dimensions and metric make the ``VECTOR`` field.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        del manifest  # every entry names its manifest
        written = [e for e in entries if e.vector is not None]
        if not written:
            return
        index = self._index(space.id)
        vector = ["TYPE", "FLOAT32", "DIM", space.spec.dimensions]
        vector += ["DISTANCE_METRIC", _distance(space.spec.metric)]
        schema = [*_schema(text=True), "vector", "VECTOR", self.algorithm.upper(), 6, *vector]
        await self._ensure(index, schema, lambda info: self._check(index, info, space))
        await self._write(
            [(f"{index}:{e.manifest_id}:{e.chunk_id}", self._fields(e)) for e in written]
        )

    def _fields(self, entry: IndexEntry) -> dict[str, str | bytes]:
        """Return an entry's hash: its tags, its vector and (``hybrid``) its words.

        Args:
            entry: The entry, with a vector.

        Returns:
            The fields, by name.
        """
        fields = _tag_fields(entry) | {"vector": _vector_bytes(entry.vector or ())}
        return fields | _text_fields(entry) if self.hybrid_words else fields

    def _check(self, index: str, info: object, space: EmbeddingSpace) -> None:
        """Refuse an existing index whose vectors have other dimensions (another instance's).

        Args:
            index: The index.
            info: ``FT.INFO``'s reply.
            space: The space written.

        Raises:
            IndexBackendUnavailableError: Its ``vector`` field is not of the space's dimensions.
        """
        dimensions = [
            _text(_get(attribute, "dim"))
            for attribute in _items(_get(info, "attributes"))
            if _text(_get(attribute, "attribute")) == "vector"
        ]
        if dimensions != [str(space.spec.dimensions)]:
            reason = (
                f"the index {index!r} does not hold vectors of {space.spec.dimensions} "
                "dimensions: give this instance its own `prefix`"
            )
            raise IndexBackendUnavailableError(self.name, reason)

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some hashes of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        if chunk_ids:
            index = self._index(space_id)
            keys = [f"{index}:{manifest_id}:{c}" for c in chunk_ids]
            await self._call(self._open().unlink(*keys))

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every hash of these versions, in every space's index.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        for index in await self._spaces():
            await self._delete_where(index, _any_of("manifest_id", manifest_ids))

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Drop a space's index and its hashes (``FT.DROPINDEX ... DD``); unknown: nothing.

        Args:
            space_id: The space.
        """
        index = self._index(space_id)
        self._ready.discard(index)
        await self._query("FT.DROPINDEX", index, "DD")

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """Count the space's hashes per version.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held; empty for an unknown space.
        """
        return await self._held(self._index(space_id), library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Ask Redis for the versions' vectors nearest to the query (KNN, filtered first).

        A few more than ``limit`` are asked for, so ties at the cut go by chunk ID.

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
        rows = await self._knn(space, manifest_ids, query, tag_filter, limit + EXTERNAL_HIT_MARGIN)
        hits = [
            BackendNeighbour(
                manifest_id=row["manifest_id"],
                chunk_id=ChunkId(row["chunk_id"]),
                distance=min(2.0, max(0.0, float(row["distance"]))),
            )
            for row in rows
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits[:limit]

    async def _knn(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        k: int,
    ) -> list[Row]:
        """Run a filtered KNN query on the space's index.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            k: How many neighbours.

        Returns:
            The rows (``manifest_id``, ``chunk_id``, ``distance``), nearest first.
        """
        where = f"({_filter(manifest_ids, tag_filter)})=>[KNN $k @vector $vector AS distance]"
        params = ["PARAMS", 4, "k", k, "vector", _vector_bytes(query)]
        shown = ["SORTBY", "distance", "ASC", "RETURN", 3, "manifest_id", "chunk_id", "distance"]
        reply = await self._query(
            "FT.SEARCH", self._index(space.id), where, *params, *shown, "LIMIT", 0, k,
            *self._limits(),
        )  # fmt: skip
        return _rows(reply)

    async def _spaces(self) -> list[str]:
        """List this instance's space indexes (``<prefix>:space<id>``).

        Returns:
            Their names.
        """
        found = await self._call(self._open().execute_command("FT._LIST"))
        pattern = re.compile(rf"{re.escape(self.prefix)}:space\d+")
        return [name for name in map(_text, _items(found)) if pattern.fullmatch(name)]


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class RedisHybridVectorBackend(RedisVectorBackend):
    """Implements ``VectorBackend`` and ``NativeHybrid``: words and vectors fused by Redis.

    The ``hybrid`` option: each hash also carries its words (the same weighted ``TEXT`` fields
    as the search index), and ``hybrid`` is one ``FT.HYBRID`` query whose text search (BM25)
    and vector search, both filtered to the versions and tags, Redis fuses with reciprocal rank
    fusion.
    """

    hybrid_words: bool = True
    """Write each hash's words, and check at ``open()`` that the server has ``FT.HYBRID``."""

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Fuse the versions' word (BM25) and vector rankings in one ``FT.HYBRID`` query.

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
        if not query.terms:  # nothing to rank by words: the vector's ranking, with RRF scores
            near = await self._knn(space, manifest_ids, vector, tag_filter, limit)
            return [
                BackendHit(
                    manifest_id=row["manifest_id"],
                    chunk_id=ChunkId(row["chunk_id"]),
                    score=1.0 / (RRF_K + rank),
                )
                for rank, row in enumerate(near, start=1)
            ]
        where = _filter(manifest_ids, tag_filter)
        depth = max(limit, RRF_DEPTH)
        words = ["SEARCH", f"{where} {_words(query.terms)}", "SCORER", REDIS_SCORER]
        near = ["VSIM", "@vector", "$vector", "KNN", 2, "K", depth, "FILTER", where]
        fused = ["COMBINE", "RRF", 4, "CONSTANT", RRF_K, "WINDOW", depth]
        shown = ["LOAD", 3, "@manifest_id", "@chunk_id", "@__score", "LIMIT", 0, limit]
        params = ["PARAMS", 2, "vector", _vector_bytes(vector), "TIMEOUT", self.timeout_ms]
        reply = await self._query(
            "FT.HYBRID", self._index(space.id), *words, *near, *fused, *shown, *params
        )
        wanted = set(manifest_ids)
        hits = [
            BackendHit(
                manifest_id=row["manifest_id"],
                chunk_id=ChunkId(row["chunk_id"]),
                score=float(row["__score"]),
            )
            for row in _rows(reply)
            if row.get("manifest_id") in wanted
        ]
        hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
        return hits


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
    if text in REDIS_TRUE:
        return True
    if text in REDIS_FALSE:
        return False
    message = f"{name} must be true or false (got {value!r})"
    raise ValueError(message)


def _password(options: Mapping[str, object]) -> str | None:
    """Read the password from ``password`` (the environment) or the file ``password_file`` names.

    Args:
        options: The options.

    Returns:
        The password, or ``None`` when neither is set.

    Raises:
        ValueError: Both are set, or the file cannot be read or is empty.
    """
    password, path = options.get("password"), options.get("password_file")
    if password and path:
        message = "set password or password_file, not both"
        raise ValueError(message)
    if path:
        try:
            password = Path(str(path)).expanduser().read_text("utf-8").strip()
        except OSError as error:
            message = f"password_file {str(path)!r} cannot be read ({type(error).__name__})"
            raise ValueError(message) from error
        if not password:
            message = f"password_file {str(path)!r} is empty"
            raise ValueError(message)
    return (str(password).strip() or None) if password else None


def _url(options: Mapping[str, object]) -> SplitResult:
    """Read the ``url`` option: ``redis://host[:port]`` or ``rediss://`` (TLS), database 0.

    Args:
        options: The options.

    Returns:
        The URL, split.

    Raises:
        ValueError: It is missing, holds credentials, or names another database.
    """
    url = urlsplit(str(options.get("url") or "").strip())
    if url.scheme not in {"redis", "rediss"} or not url.hostname:
        message = "url is required: the server's redis://host[:port] (rediss:// for TLS)"
        raise ValueError(message)
    if url.username or url.password:
        message = "url may not hold credentials: set username and password (or password_file)"
        raise ValueError(message)
    if unquote(url.path).strip("/") not in {"", "0"}:
        message = "url names a database other than 0: the Query Engine indexes database 0 only"
        raise ValueError(message)
    try:
        _ = url.port  # raises for a port out of range
    except ValueError as error:
        message = "url has an invalid port"
        raise ValueError(message) from error
    return url


def _tls_files(options: Mapping[str, object], *, tls: bool) -> dict[str, str | None]:
    """Read the TLS options: each a file that must be there, and only with ``rediss://``.

    Args:
        options: The options.
        tls: Whether the URL is ``rediss://``.

    Returns:
        Each option's path, or ``None`` when unset.

    Raises:
        ValueError: A file is not there, TLS is off, or a client certificate lacks its key.
    """
    files: dict[str, str | None] = {}
    for name in _TLS_FILES:
        value = str(options.get(name) or "").strip()
        path = Path(value).expanduser() if value else None
        if path is not None and not path.is_file():
            message = f"{name} {value!r} is not a file"
            raise ValueError(message)
        files[name] = str(path) if path is not None else None
    if not tls and any(files.values()):
        message = "the tls_* options need a rediss:// url"
        raise ValueError(message)
    if bool(files["tls_cert_file"]) != bool(files["tls_key_file"]):
        message = "set tls_cert_file and tls_key_file together (a client certificate)"
        raise ValueError(message)
    return files


def _timeout(options: Mapping[str, object]) -> int:
    """Read the ``timeout`` option.

    Args:
        options: The options.

    Returns:
        The seconds.

    Raises:
        ValueError: It is not a positive whole number.
    """
    try:
        timeout = int(str(options.get("timeout", REDIS_DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = 0
    if timeout < 1:
        message = f"timeout must be a whole number of seconds (got {options.get('timeout')!r})"
        raise ValueError(message)
    return timeout


@dataclass(frozen=True, slots=True, kw_only=True)
class _Settings:
    """The options, checked: what both factories build from."""

    connect: Connect
    """Makes a client of the configured server."""
    prefix: str
    """The ``prefix`` option."""
    timeout_ms: int
    """The ``timeout`` option, in milliseconds."""
    hybrid: bool
    """The ``hybrid`` option."""
    algorithm: str
    """The ``vector_algorithm`` option."""


def _settings(options: Mapping[str, object]) -> _Settings:
    """Check the ``[index_backends.redis]`` options.

    Args:
        options: The options.

    Returns:
        What the backends are built from.

    Raises:
        ValueError: An option is unknown, missing or invalid.
    """
    unknown = sorted(set(options) - REDIS_OPTIONS)
    if unknown:
        known = ", ".join(sorted(REDIS_OPTIONS))
        message = f"unknown options {', '.join(unknown)} (known: {known})"
        raise ValueError(message)
    url = _url(options)
    prefix = str(options.get("prefix") or REDIS_DEFAULT_PREFIX).strip()
    if not REDIS_PREFIX.fullmatch(prefix):
        message = f"prefix {prefix!r} must be letters, digits, '_' and '-'"
        raise ValueError(message)
    algorithm = str(options.get("vector_algorithm") or "hnsw").strip().lower()
    if algorithm not in REDIS_VECTOR_ALGORITHMS:
        message = f"vector_algorithm must be hnsw or flat (got {algorithm!r})"
        raise ValueError(message)
    tls = url.scheme == "rediss"
    files = _tls_files(options, tls=tls)
    timeout = _timeout(options)
    username = str(options.get("username") or "").strip() or None
    password = _password(options)

    def connect() -> Redis:
        """Make a client of the configured server.

        Returns:
            The client (no command sent yet).
        """
        return Redis(
            host=url.hostname or "",
            port=url.port or REDIS_DEFAULT_PORT,
            username=username,
            password=password,
            ssl=tls,
            ssl_ca_certs=files["tls_ca_file"],
            ssl_certfile=files["tls_cert_file"],
            ssl_keyfile=files["tls_key_file"],
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
            protocol=3,
            client_name=f"exactdocs-{prefix}",
        )

    return _Settings(
        connect=connect,
        prefix=prefix,
        timeout_ms=timeout * 1000,
        hybrid=_switch(options, "hybrid"),
        algorithm=algorithm,
    )


def search_backend(options: Mapping[str, object]) -> RedisSearchBackend:
    """Build the Redis search backend from its ``[index_backends.redis]`` options.

    Options: ``url`` (required: ``redis://host[:port]``, ``rediss://`` for TLS), ``prefix`` (of
    the indexes and keys, ``exactdocs``), ``username``, ``password`` (from the environment only)
    or ``password_file``, ``tls_ca_file``, ``tls_cert_file`` and ``tls_key_file`` (with
    ``rediss://``), ``timeout`` (seconds, 10), and the vector backend's ``hybrid`` and
    ``vector_algorithm``. An invalid option raises ``ValueError``.

    Args:
        options: The options.

    Returns:
        The backend, not connected yet.
    """
    settings = _settings(options)
    return RedisSearchBackend(
        connect=settings.connect, prefix=settings.prefix, timeout_ms=settings.timeout_ms
    )


def vector_backend(options: Mapping[str, object]) -> RedisVectorBackend:
    """Build the Redis vector backend from its ``[index_backends.redis]`` options.

    Options as ``search_backend``'s, and ``hybrid`` (native hybrid search with ``FT.HYBRID``,
    off) and ``vector_algorithm`` (``hnsw``, approximate, or ``flat``, exact). An invalid
    option raises ``ValueError``.

    Args:
        options: The options.

    Returns:
        The backend, not connected yet; with ``NativeHybrid`` when ``hybrid`` is on.
    """
    settings = _settings(options)
    kind = RedisHybridVectorBackend if settings.hybrid else RedisVectorBackend
    return kind(
        connect=settings.connect,
        prefix=settings.prefix,
        timeout_ms=settings.timeout_ms,
        algorithm=settings.algorithm,
    )
