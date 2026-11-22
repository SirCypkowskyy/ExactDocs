"""Chroma as the vector backend (#361): ``EXACTDOCS_VECTOR_BACKEND=chroma``.

Each embedding space is one collection, ``<collection>_space<id>``, created on the space's first
write with cosine distance and the space's dimensions in its metadata. A record is one chunk of one
version (its ID is derived from the manifest and chunk IDs), with ``manifest_id``, ``library``,
``version_id``, ``chunk_id``, ``article_path`` and ``headings`` as metadata, and one ``tag:<tag>``
key per tag, so every search filters on the asked versions' ``manifest_id`` (and tags) in Chroma,
before ranking. The metadata is scalars only: list metadata is not reliable in Chroma 1.5.9 (a
record reads back, and over HTTP is filtered by, list values of other records).

ExactDocs passes its own vectors in: no collection carries an embedding function, and no record
or query carries text to embed, so Chroma never runs a model (none is downloaded either). Chroma
does not fuse keyword and vector search here: ExactDocs fuses its own BM25 index with the
nearest vectors, as with the database.

Two connection modes, from the options: ``url`` (a Chroma server or Chroma Cloud, through the
HTTP client; the ``chroma`` extra, ``chromadb-client``) or ``path`` (the embedded persistent
client, in a local directory; the ``chroma-local`` extra, the full ``chromadb``). The client is
synchronous: each call runs in a worker thread, within the ``timeout`` option.

Everything here is derived data: ``exactdocs index rebuild`` writes it again from the database.
Only this module imports ``chromadb``.
"""

import asyncio
import re
import uuid
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import chromadb
from chromadb.api.client import Client
from chromadb.api.models.Collection import Collection as ChromaCollection
from chromadb.config import Settings
from chromadb.errors import ChromaError, NotFoundError

from exactdocs.retrieval.constants import (
    CHROMA_BACKEND,
    CHROMA_COLLECTION_NAME,
    CHROMA_DEFAULT_COLLECTION,
    CHROMA_DEFAULT_DATABASE,
    CHROMA_DEFAULT_TENANT,
    CHROMA_DEFAULT_TIMEOUT_SECONDS,
    CHROMA_DIMENSIONS_KEY,
    CHROMA_MODEL_KEY,
    CHROMA_OPTIONS,
    CHROMA_READ_PAGE,
    CHROMA_REASON_CHARS,
    CHROMA_RECORD_NAMESPACE,
    CHROMA_SPACE_SUFFIX,
    CHROMA_TAG_PREFIX,
    CHROMA_TIE_MARGIN,
    CHROMA_TOKEN_HEADERS,
    CHROMA_WRITE_BATCH,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs.retrieval.models import (
    BackendNeighbour,
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    HeldVersion,
    IndexedManifest,
    IndexEntry,
    TagFilter,
    TagMatch,
    VectorMetric,
)

type Connect = Callable[[], Client]
"""Makes a new client (it answers, or raises); called by each ``open()``, in a worker thread."""
type Where = dict[str, Any]
"""A Chroma metadata filter."""

_COSINE = "cosine"
"""Chroma's name of the cosine distance (``hnsw`` / ``spann`` ``space``)."""


class _GoneError(Exception):
    """A collection was not there (dropped behind the backend's back, or never made)."""


def record_id(manifest_id: str, chunk_id: str) -> str:
    """Return the ID of a chunk's record in a version: the same every time it is written.

    Args:
        manifest_id: The version's manifest.
        chunk_id: The chunk.

    Returns:
        A UUID (v5), as text.
    """
    return str(uuid.uuid5(CHROMA_RECORD_NAMESPACE, f"{manifest_id}\n{chunk_id}"))


def close_client(client: Client) -> None:
    """Close a client, and its HTTP connections.

    ``Client.close()`` stops the client's components but leaves the connection pools of its
    HTTP client (and of the admin client it checks the tenant with) to the garbage collector
    (chromadb 1.5.9). Each HTTP client has systems of its own, so closing those pools here never
    affects another client; the embedded client has none.

    Args:
        client: The client.
    """
    servers = [
        getattr(c, "_server", None) for c in (client, getattr(client, "_admin_client", None))
    ]
    client.close()
    for server in servers:
        pool_close = getattr(getattr(server, "_session", None), "close", None)
        if callable(pool_close):
            pool_close()


def _space_name(metric: VectorMetric) -> str:
    """Map a space's metric to Chroma's distance.

    Args:
        metric: The space's metric.

    Returns:
        Chroma's name for it.
    """
    match metric:
        case VectorMetric.COSINE:
            return _COSINE


def _every(clauses: Sequence[Where]) -> Where:
    """Join filter clauses with ``$and`` (Chroma wants two or more there).

    Args:
        clauses: One or more clauses.

    Returns:
        The clause, or their conjunction.
    """
    return clauses[0] if len(clauses) == 1 else {"$and": list(clauses)}


def search_filter(manifest_ids: Collection[str], tag_filter: TagFilter) -> Where:
    """Filter a search to these versions and the tag filter (applied before ranking).

    Args:
        manifest_ids: The versions searched.
        tag_filter: Which tags a chunk's article must carry.

    Returns:
        The Chroma ``where`` filter.
    """
    clauses: list[Where] = [{"manifest_id": {"$in": sorted(set(manifest_ids))}}]
    tags: list[Where] = [{tag_key(t): True} for t in dict.fromkeys(tag_filter.tags)]
    if tags and tag_filter.match is TagMatch.ALL:
        clauses += tags
    elif tags:
        clauses.append(tags[0] if len(tags) == 1 else {"$or": tags})
    return _every(clauses)


def tag_key(tag: str) -> str:
    """Name the metadata key that marks a record's article as carrying a tag (value ``true``).

    One key per tag, not a list: Chroma 1.5.9's list metadata reads back (and, over HTTP, is
    filtered by) list values of other records; a scalar key never is.

    Args:
        tag: The tag, normalized.

    Returns:
        ``tag:<tag>``.
    """
    return f"{CHROMA_TAG_PREFIX}{tag}"


def record_metadata(entry: IndexEntry) -> dict[str, str | bool]:
    """Make a record's metadata: what searches filter on, and where the chunk comes from.

    Scalars only (see ``tag_key``); the headings are one text, joined by `` > ``.

    Args:
        entry: The entry.

    Returns:
        The metadata.
    """
    found: dict[str, str | bool] = {
        "manifest_id": entry.manifest_id,
        "library": entry.library,
        "version_id": entry.version_id,
        "chunk_id": entry.chunk_id,
        "article_path": entry.article_path,
        "headings": " > ".join(entry.heading_path),
    }
    found.update(dict.fromkeys(map(tag_key, entry.tags), True))
    return found


def _reason(error: BaseException, secret: str | None) -> str:
    """Say briefly why Chroma did not answer, never with the token.

    Args:
        error: What the client raised.
        secret: The token, cut out of the message should a server echo it.

    Returns:
        Chroma's error name and message, or the transport error's type, shortened.
    """
    if isinstance(error, ChromaError):
        text = f"{error.name()}: {error.message()}"
    elif isinstance(error, (OSError, ConnectionError)) or type(error).__module__.startswith(
        "httpx"
    ):
        text = type(error).__name__
    else:  # what the client raises for a non-Chroma reply (a proxy's 401 page) or no answer
        text = f"{type(error).__name__}: {error}"
    if secret:
        text = text.replace(secret, "***")
    text = " ".join(text.split())
    return text if len(text) <= CHROMA_REASON_CHARS else f"{text[: CHROMA_REASON_CHARS - 1]}…"


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- holds its client
class ChromaVectorBackend:
    """Implements ``ports.driven.VectorBackend`` over Chroma: one collection per space."""

    connect: Connect
    """Makes the client ``open()`` uses until ``close()``."""
    collection: str = CHROMA_DEFAULT_COLLECTION
    """The prefix of every collection: a space's is ``<collection>_space<id>``."""
    timeout: float = CHROMA_DEFAULT_TIMEOUT_SECONDS
    """Seconds one call to Chroma may take."""
    secret: str | None = field(default=None, repr=False)
    """The token, only to keep it out of error messages."""
    name: str = CHROMA_BACKEND
    """The registered name."""
    _client: Client | None = field(default=None, init=False, repr=False)
    """The open client; ``None`` before ``open()`` and after ``close()``."""
    _batch: int = field(default=CHROMA_WRITE_BATCH, init=False, repr=False)
    """Records per upsert: ``CHROMA_WRITE_BATCH`` or the server's maximum, if smaller."""
    _known: dict[str, ChromaCollection] = field(default_factory=dict, init=False, repr=False)
    """The collections seen to exist (and checked), in this process, by name."""

    async def open(self) -> None:
        """Connect and check that Chroma answers (and takes the token, if one is set).

        ``IndexBackendUnavailableError`` when it cannot be reached, or refused the token.
        """
        await self.close()
        self._client = await self._call(self.connect)
        self._known.clear()
        client = self._client
        self._batch = max(1, min(CHROMA_WRITE_BATCH, await self._call(client.get_max_batch_size)))

    async def close(self) -> None:
        """Release the client, if open."""
        client, self._client = self._client, None
        self._known.clear()
        if client is not None:
            await asyncio.to_thread(close_client, client)

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries' records in the space's collection (created when missing).

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.

        Raises:
            IndexBackendUnavailableError: Chroma did not take them, or the collection of that
                name is not this space's (other dimensions, or not made by ExactDocs).
        """
        del manifest  # every entry names its manifest
        records = [e for e in entries if e.vector is not None]
        if not records:
            return
        for again in (True, False):
            collection = await self._created(space)
            try:
                for start in range(0, len(records), self._batch):
                    await self._upsert(collection, records[start : start + self._batch])
            except _GoneError as error:  # dropped elsewhere since: create it again, once
                self._known.pop(collection.name, None)
                if not again:
                    reason = f"the collection {collection.name!r} disappeared while written"
                    raise IndexBackendUnavailableError(self.name, reason) from error
            else:
                return

    async def _upsert(self, collection: ChromaCollection, batch: Sequence[IndexEntry]) -> None:
        """Write one batch of records: their IDs, vectors and metadata, no text.

        Args:
            collection: The space's collection.
            batch: The entries, each with a vector.
        """
        ids = [record_id(e.manifest_id, e.chunk_id) for e in batch]
        vectors = [[float(v) for v in e.vector or ()] for e in batch]
        metadatas = [record_metadata(e) for e in batch]
        await self._call(
            lambda: collection.upsert(
                ids=ids,
                embeddings=cast("Any", vectors),
                metadatas=cast("Any", metadatas),
            )
        )

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some records of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        if not chunk_ids:
            return
        collection = await self._collection(space_id)
        if collection is None:
            return
        ids = [record_id(manifest_id, c) for c in dict.fromkeys(chunk_ids)]
        try:
            await self._call(lambda: collection.delete(ids=ids))
        except _GoneError:
            self._known.pop(collection.name, None)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete every record of these versions, in every space's collection.

        Args:
            manifest_ids: The versions.
        """
        if not manifest_ids:
            return
        where: Where = {"manifest_id": {"$in": sorted(set(manifest_ids))}}
        for name in await self._collection_names():
            collection = await self._collection_named(name)
            if collection is None:
                continue
            try:
                await self._call(lambda c=collection: c.delete(where=cast("Any", where)))
            except _GoneError:
                self._known.pop(name, None)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Delete a space's collection; nothing happens for an unknown space.

        Args:
            space_id: The space.
        """
        name = self._name(space_id)
        client = self._open()
        self._known.pop(name, None)
        try:
            await self._call(lambda: client.delete_collection(name))
        except _GoneError:
            return

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """Count the space's records per version (their metadata, read a page at a time).

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held, by manifest ID; empty for an unknown space.
        """
        collection = await self._collection(space_id)
        if collection is None:
            return []
        where: Where | None = None if library is None else {"library": library}
        counts: Counter[tuple[str, str]] = Counter()
        offset = 0
        while True:
            try:
                page = await self._call(
                    lambda o=offset: collection.get(
                        where=cast("Any", where),
                        include=cast("Any", ["metadatas"]),
                        limit=CHROMA_READ_PAGE,
                        offset=o,
                    )
                )
            except _GoneError:
                self._known.pop(collection.name, None)
                return []
            metadatas = page["metadatas"] or []
            for metadata in metadatas:
                if metadata is not None:
                    counts[str(metadata.get("manifest_id")), str(metadata.get("library"))] += 1
            if len(page["ids"]) < CHROMA_READ_PAGE:
                break
            offset += CHROMA_READ_PAGE
        return [
            HeldVersion(manifest_id=manifest_id, library=held_library, entries=entries)
            for (manifest_id, held_library), entries in sorted(counts.items())
        ]

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Ask Chroma for the versions' records nearest to the query, filtered in Chroma.

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
        collection = await self._collection(space.id, check=space)
        if collection is None:
            return []
        where = search_filter(manifest_ids, tag_filter)
        vector = [float(v) for v in query]
        try:
            found = await self._call(
                lambda: collection.query(
                    query_embeddings=cast("Any", [vector]),
                    n_results=limit + CHROMA_TIE_MARGIN,
                    where=cast("Any", where),
                    include=cast("Any", ["metadatas", "distances"]),
                )
            )
        except _GoneError:
            self._known.pop(collection.name, None)
            return []
        wanted = set(manifest_ids)
        metadatas = (found["metadatas"] or [[]])[0]
        distances = (found["distances"] or [[]])[0]
        hits = [
            BackendNeighbour(
                manifest_id=str(metadata["manifest_id"]),
                chunk_id=ChunkId(str(metadata["chunk_id"])),
                distance=min(2.0, max(0.0, float(distance))),
            )
            for metadata, distance in zip(metadatas, distances, strict=True)
            if metadata is not None and metadata.get("manifest_id") in wanted
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits[:limit]

    def _name(self, space_id: EmbeddingSpaceId) -> str:
        """Name a space's collection.

        Args:
            space_id: The space.

        Returns:
            ``<collection>_space<id>``.
        """
        return f"{self.collection}{CHROMA_SPACE_SUFFIX}{space_id}"

    def _open(self) -> Client:
        """Return the open client.

        Returns:
            The client.

        Raises:
            IndexBackendUnavailableError: ``open()`` was not called (or ``close()`` was).
        """
        if self._client is None:
            raise IndexBackendUnavailableError(self.name, "not connected")
        return self._client

    async def _collection(
        self, space_id: EmbeddingSpaceId, *, check: EmbeddingSpace | None = None
    ) -> ChromaCollection | None:
        """Find a space's collection, without creating it.

        Args:
            space_id: The space.
            check: The space, to check the collection against.

        Returns:
            The collection; ``None`` when it does not exist.
        """
        return await self._collection_named(self._name(space_id), check)

    async def _created(self, create: EmbeddingSpace) -> ChromaCollection:
        """Find a space's collection, or create it.

        Args:
            create: The space.

        Returns:
            The collection.
        """
        name = self._name(create.id)
        if (found := self._known.get(name)) is not None:
            return found
        client = self._open()
        metadata = {
            CHROMA_DIMENSIONS_KEY: create.spec.dimensions,
            CHROMA_MODEL_KEY: f"{create.spec.profile_kind}:{create.spec.model}",
        }
        configuration = {"hnsw": {"space": _space_name(create.spec.metric)}}
        found = await self._call(
            lambda: client.get_or_create_collection(
                name,
                configuration=cast("Any", configuration),
                metadata=metadata,
                embedding_function=None,
            )
        )
        self._check(found, create)
        self._known[name] = found
        return found

    async def _collection_named(
        self, name: str, check: EmbeddingSpace | None = None
    ) -> ChromaCollection | None:
        """Find a collection by name, without creating it.

        Args:
            name: The collection.
            check: The space, to check it against; otherwise only that ExactDocs made it.

        Returns:
            The collection, or ``None`` when it does not exist.
        """
        found = self._known.get(name)
        if found is None:
            client = self._open()
            try:
                found = await self._call(
                    lambda: client.get_collection(name, embedding_function=None)
                )
            except _GoneError:
                return None
        self._check(found, check)
        self._known[name] = found
        return found

    def _check(self, collection: ChromaCollection, space: EmbeddingSpace | None) -> None:
        """Refuse a collection ExactDocs did not make for this space.

        Args:
            collection: The collection of the space's name.
            space: The space, when known: its dimensions and cosine distance must match.

        Raises:
            IndexBackendUnavailableError: It has no or other dimensions, or another distance.
        """
        dimensions = (collection.metadata or {}).get(CHROMA_DIMENSIONS_KEY)
        if dimensions is None:
            reason = (
                f"the collection {collection.name!r} was not made by ExactDocs: give this "
                "instance another `collection` prefix"
            )
            raise IndexBackendUnavailableError(self.name, reason)
        if space is None:
            return
        configuration = collection.configuration_json or {}
        distances = {
            (configuration.get(index) or {}).get("space") for index in ("hnsw", "spann")
        } - {None}
        if dimensions != space.spec.dimensions or (
            distances and _space_name(space.spec.metric) not in distances
        ):
            reason = (
                f"the collection {collection.name!r} holds vectors of {dimensions} dimensions "
                f"({', '.join(sorted(map(str, distances))) or 'unknown distance'}), not "
                f"{space.spec.dimensions} ({_space_name(space.spec.metric)}): another "
                "instance's? Give this one another `collection` prefix"
            )
            raise IndexBackendUnavailableError(self.name, reason)

    async def _collection_names(self) -> list[str]:
        """List this instance's collections, a page at a time.

        Returns:
            The names of the collections ``<collection>_space<id>`` that ExactDocs made (another
            one of such a name is left alone).
        """
        client = self._open()
        own = re.compile(rf"{re.escape(self.collection + CHROMA_SPACE_SUFFIX)}\d+")
        names: list[str] = []
        offset = 0
        while True:
            page = await self._call(
                lambda o=offset: client.list_collections(limit=CHROMA_READ_PAGE, offset=o)
            )
            names += [
                c.name
                for c in page
                if own.fullmatch(c.name) and CHROMA_DIMENSIONS_KEY in (c.metadata or {})
            ]
            if len(page) < CHROMA_READ_PAGE:
                return names
            offset += CHROMA_READ_PAGE

    async def _call[T](self, work: Callable[[], T]) -> T:
        """Run one client call in a worker thread, within the timeout.

        Args:
            work: The call.

        Returns:
            What it returned.

        Raises:
            _GoneError: Chroma answered that the collection does not exist.
            IndexBackendUnavailableError: Chroma did not answer in time, or failed.
        """
        try:
            async with asyncio.timeout(self.timeout):
                return await asyncio.to_thread(work)
        except NotFoundError as error:
            raise _GoneError from error
        except TimeoutError as error:
            reason = f"no answer within {self.timeout:g} s"
            raise IndexBackendUnavailableError(self.name, reason) from error
        except IndexBackendUnavailableError:
            raise
        except Exception as error:  # the client raises plain exceptions for transport errors
            raise IndexBackendUnavailableError(self.name, _reason(error, self.secret)) from error


def _text(options: Mapping[str, object], option: str, default: str = "") -> str:
    """Read a text option.

    Args:
        options: The options.
        option: Its name.
        default: When unset or blank.

    Returns:
        The value, stripped.
    """
    return str(options.get(option) or default).strip() or default


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


def _timeout(options: Mapping[str, object]) -> int:
    """Read the ``timeout`` option: whole seconds, at least one.

    Args:
        options: The options.

    Returns:
        The seconds.

    Raises:
        ValueError: It is not a whole number of seconds.
    """
    try:
        timeout = int(str(options.get("timeout", CHROMA_DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = 0
    if timeout < 1:
        message = f"timeout must be a whole number of seconds (got {options.get('timeout')!r})"
        raise ValueError(message)
    return timeout


def _http(
    url: str, tenant: str, database: str, token: str | None, header: str
) -> Callable[[], Client]:
    """Make the connector of a Chroma server (or Chroma Cloud).

    Args:
        url: ``http(s)://host[:port]``.
        tenant: The tenant.
        database: The database.
        token: The token, if any.
        header: The header the token is sent in.

    Returns:
        What makes a client of it (which checks the tenant and database, so the server answers).

    Raises:
        ValueError: The URL is not ``http(s)://host[:port]``.
    """
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    extra = parts.path.strip("/") or parts.query or parts.fragment or parts.username
    bad_port = port is not None and port < 1
    if parts.scheme not in {"http", "https"} or not parts.hostname or extra or bad_port:
        message = f"url {url!r} must be http(s)://host[:port] (no path, no credentials)"
        raise ValueError(message)
    ssl = parts.scheme == "https"
    host = parts.hostname
    port = port or (443 if ssl else 8000)
    headers = {header: f"{CHROMA_TOKEN_HEADERS[header]}{token}"} if token else None

    def connect() -> Client:
        """Make a client of the configured server.

        Returns:
            The client, once the server answered for the tenant and database.
        """
        client = chromadb.HttpClient(
            host=host,
            port=port,
            ssl=ssl,
            headers=dict(headers) if headers else None,
            settings=Settings(anonymized_telemetry=False),
            tenant=tenant,
            database=database,
        )
        return cast("Client", client)  # what both constructors build, typed as its protocol

    return connect


def _persistent(path: str, tenant: str, database: str) -> Callable[[], Client]:
    """Make the connector of the embedded persistent client.

    Args:
        path: The directory Chroma keeps its files in (created when missing).
        tenant: The tenant.
        database: The database.

    Returns:
        What makes the client.

    Raises:
        ValueError: The installed ``chromadb`` is the HTTP-only client.
    """
    if chromadb.is_client:
        message = (
            "path needs the embedded client, which the HTTP-only chromadb-client does not have: "
            "install exactdocs[chroma-local] instead of exactdocs[chroma], or give a url"
        )
        raise ValueError(message)
    directory = Path(path).expanduser()

    def connect() -> Client:
        """Open the directory.

        Returns:
            The client.
        """
        directory.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=directory,
            settings=Settings(anonymized_telemetry=False),
            tenant=tenant,
            database=database,
        )
        return cast("Client", client)  # what both constructors build, typed as its protocol

    return connect


def vector_backend(options: Mapping[str, object]) -> ChromaVectorBackend:
    """Build the Chroma vector backend from its ``[index_backends.chroma]`` options.

    Options: ``url`` (a server or Chroma Cloud: ``http(s)://host[:port]``, port 8000, or 443
    with https, when none) or ``path`` (the embedded persistent client's directory), one of the
    two; ``collection`` (the collections' prefix, ``exactdocs``); ``tenant`` and ``database``
    (``default_tenant`` / ``default_database``); ``token`` (from the environment only) or
    ``token_file``, sent in ``token_header`` (``x-chroma-token``, or ``authorization`` as a
    bearer token); ``timeout`` (seconds per call, 30).

    Args:
        options: The options.

    Returns:
        The backend, not connected yet.

    Raises:
        ValueError: An option is unknown, missing or invalid.
    """
    unknown = sorted(set(options) - CHROMA_OPTIONS)
    if unknown:
        message = (
            f"unknown options {', '.join(unknown)} (known: {', '.join(sorted(CHROMA_OPTIONS))})"
        )
        raise ValueError(message)
    url, path = _text(options, "url"), _text(options, "path")
    if bool(url) == bool(path):
        message = (
            "give url (a Chroma server's http(s)://host[:port], or Chroma Cloud's) or path "
            "(a local directory for the embedded client), one of the two"
        )
        raise ValueError(message)
    collection = _text(options, "collection", CHROMA_DEFAULT_COLLECTION)
    if not CHROMA_COLLECTION_NAME.fullmatch(collection):
        message = (
            f"collection {collection!r} must be letters, digits, '.', '_' and '-', starting "
            "with a letter or digit"
        )
        raise ValueError(message)
    tenant = _text(options, "tenant", CHROMA_DEFAULT_TENANT)
    database = _text(options, "database", CHROMA_DEFAULT_DATABASE)
    header = _text(options, "token_header", "x-chroma-token").lower()
    if header not in CHROMA_TOKEN_HEADERS:
        message = f"token_header must be {' or '.join(CHROMA_TOKEN_HEADERS)} (got {header!r})"
        raise ValueError(message)
    token = _token(options)
    if token and path:
        message = "token is for a server (url); the embedded client (path) takes none"
        raise ValueError(message)
    connect = (
        _http(url, tenant, database, token, header) if url else _persistent(path, tenant, database)
    )
    return ChromaVectorBackend(
        connect=connect, collection=collection, timeout=_timeout(options), secret=token
    )
