import importlib
import json
import sqlite3
import struct
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import aiosqlite
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Row,
    Table,
    Text,
    bindparam,
    insert,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.retrieval.constants import (
    _DIMENSIONS,
    _LOADED,
    _VECTOR_COVERAGE,
    _VECTOR_CREATE,
    _VECTOR_DELETE,
    _VECTOR_DROP,
    _VECTOR_MISSING,
    _VECTOR_NEAREST,
    _VECTOR_UPSERT,
    SQLITE_VEC_MODULE,
    TAG_CONDITIONS,
    VECTOR_BATCH,
    VECTOR_MMAP_BYTES,
    VECTOR_TABLE_PREFIX,
)
from exactdocs.retrieval.errors import (
    RetiredEmbeddingSpaceError,
    UnknownEmbeddingSpaceError,
    VectorStoreUnavailableError,
)
from exactdocs.retrieval.models import (
    ChunkId,
    ChunkKey,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    SpaceState,
    TagFilter,
    VectorCoverage,
    VectorHit,
    VectorMetric,
    checked_vector,
)

# `retrieval_embedding_spaces` is created by an Alembic revision in `exactdocs.bootstrap`; this is
# only the adapter's query-side description of it. The vectors of a space live in a table this
# adapter creates and drops itself (`retrieval_vec_<id>`), like the search index tables of
# `exactdocs reindex`: one fixed dimension per table, and no way to mix two models. Each row is a
# `retrieval_chunks` row (its `id`, with ON DELETE CASCADE, so garbage collection removes vectors
# with their chunk sets) and its vector as little-endian float32, the format sqlite-vec reads.
# The tables are plain SQLite: storing, backing up and restoring them needs no extension; only
# the distance function in `nearest` does.
metadata = MetaData()
spaces_table = Table(
    "retrieval_embedding_spaces",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("profile_kind", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("metric", Text, nullable=False),
    Column("input_format", Integer, nullable=False),
    Column("state", Text, nullable=False),
    Column("created_at", Text, nullable=False),  # ISO 8601, UTC
    Column("activated_at", Text),
)

# Only the columns that identify a chunk; the chunk repository owns the table.
chunk_rows = Table(
    "retrieval_chunks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("blob_sha", Text, nullable=False),
    Column("config_hash", Text, nullable=False),
    Column("position", Integer, nullable=False),
)


def _table(space_id: EmbeddingSpaceId) -> str:
    """Name the vector table of a space (an integer ID: safe to put in SQL).

    Args:
        space_id: The space.

    Returns:
        ``retrieval_vec_<id>``.
    """
    return f"{VECTOR_TABLE_PREFIX}{int(space_id)}"


def _pack(vector: Sequence[float]) -> bytes:
    """Encode a vector as sqlite-vec reads a BLOB: little-endian float32.

    Args:
        vector: The checked values.

    Returns:
        The BLOB.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def _sqlite_vec_path() -> str:
    """Find sqlite-vec's loadable extension, importing its package (``[ai]`` extra) only now.

    Returns:
        The path ``load_extension`` takes.
    """
    return importlib.import_module(SQLITE_VEC_MODULE).loadable_path()


def _iso(moment: datetime) -> str:
    """UTC ISO 8601, so stored timestamps compare as text.

    Args:
        moment: An aware time.

    Returns:
        The text stored.
    """
    return moment.astimezone(UTC).isoformat()


def _space(row: Row[Any]) -> EmbeddingSpace:
    """Map a row of ``retrieval_embedding_spaces``.

    Args:
        row: The row.

    Returns:
        The space.
    """
    return EmbeddingSpace(
        id=EmbeddingSpaceId(row.id),
        spec=EmbeddingSpec(
            profile_kind=row.profile_kind,
            model=row.model,
            dimensions=row.dimensions,
            input_format=row.input_format,
            metric=VectorMetric(row.metric),
        ),
        state=SpaceState(row.state),
        created_at=datetime.fromisoformat(row.created_at),
        activated_at=None if row.activated_at is None else datetime.fromisoformat(row.activated_at),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteVectorIndex:
    """Implements ``ports.driven.VectorIndex`` with plain tables and sqlite-vec's distance.

    Search is exact: ``vec_distance_cosine`` over the BLOBs of one manifest's chunks, ordered in
    SQL. sqlite-vec is loaded into a connection the first time that connection searches (or
    ``available`` is asked), never before: an instance without embeddings never loads it. That
    connection also gets ``mmap_size`` (``VECTOR_MMAP_BYTES``), and remembers in its ``info`` that
    it is loaded and the dimensions of the spaces it searched, so a search costs one query.
    """

    engine: AsyncEngine
    """The application database."""
    extension: Callable[[], str] = _sqlite_vec_path
    """Returns the path of sqlite-vec's loadable extension (raises when it is not installed)."""
    _loads: dict[str, bool] = field(default_factory=dict)
    """Whether sqlite-vec loaded, once ``available`` found out (key ``"loads"``)."""

    async def available(self) -> bool:
        """Load sqlite-vec into a connection once, and remember whether it worked.

        Returns:
            False when the ``[ai]`` extra is missing, or this Python cannot load extensions.
        """
        if "loads" not in self._loads:
            try:
                async with self.engine.connect() as connection:
                    await self._load(connection)
            except VectorStoreUnavailableError:
                self._loads["loads"] = False
            else:
                self._loads["loads"] = True
        return self._loads["loads"]

    async def spaces(self) -> Sequence[EmbeddingSpace]:
        """List every space, oldest first.

        Returns:
            The spaces.
        """
        async with self.engine.connect() as connection:
            rows = await connection.execute(select(spaces_table).order_by(spaces_table.c.id))
            return [_space(r) for r in rows]

    async def create_space(self, spec: EmbeddingSpec, at: datetime) -> EmbeddingSpace:
        """Record the space and create its table, in one transaction.

        Args:
            spec: The model and format of its vectors.
            at: When it is created.

        Returns:
            The new space.
        """
        async with self._write() as connection:
            space_id = await connection.scalar(
                insert(spaces_table)
                .values(
                    profile_kind=spec.profile_kind,
                    model=spec.model,
                    dimensions=spec.dimensions,
                    metric=spec.metric.value,
                    input_format=spec.input_format,
                    state=SpaceState.BUILDING.value,
                    created_at=_iso(at),
                )
                .returning(spaces_table.c.id)
            )
            space_id = EmbeddingSpaceId(int(space_id or 0))
            await connection.exec_driver_sql(
                _VECTOR_CREATE.format(table=_table(space_id), size=4 * spec.dimensions)
            )
            row = (
                await connection.execute(select(spaces_table).where(spaces_table.c.id == space_id))
            ).one()
        return _space(row)

    async def activate_space(self, space_id: EmbeddingSpaceId, at: datetime) -> EmbeddingSpace:
        """Mark the space active, keeping the time of its first activation.

        Args:
            space_id: The space.
            at: When it became active.

        Returns:
            The space now.
        """
        async with self._write() as connection:
            space = await self._live(connection, space_id)
            await connection.execute(
                update(spaces_table)
                .where(spaces_table.c.id == space_id)
                .values(
                    state=SpaceState.ACTIVE.value,
                    activated_at=_iso(space.activated_at or at),
                )
            )
            row = (
                await connection.execute(select(spaces_table).where(spaces_table.c.id == space_id))
            ).one()
        return _space(row)

    async def retire_space(self, space_id: EmbeddingSpaceId) -> None:
        """Mark the space retired and drop its table, in one transaction.

        Args:
            space_id: The space.
        """
        async with self._write() as connection:
            await self._find(connection, space_id)
            await connection.execute(
                update(spaces_table)
                .where(spaces_table.c.id == space_id)
                .values(state=SpaceState.RETIRED.value)
            )
            await connection.exec_driver_sql(_VECTOR_DROP.format(table=_table(space_id)))

    async def upsert(
        self, space_id: EmbeddingSpaceId, vectors: Mapping[ChunkKey, Sequence[float]]
    ) -> int:
        """Store or replace the vectors of the chunks that exist, all in one transaction.

        Args:
            space_id: The space.
            vectors: The vector of each chunk.

        Returns:
            How many were stored.
        """
        async with self._write() as connection:
            space = await self._live(connection, space_id)
            blobs = {k: _pack(checked_vector(v, space.spec.dimensions)) for k, v in vectors.items()}
            ids = await self._chunk_ids(connection, list(blobs))
            rows = [{"key": ids[k], "embedding": blobs[k]} for k in blobs if k in ids]
            if rows:
                await connection.execute(text(_VECTOR_UPSERT.format(table=_table(space_id))), rows)
        return len(rows)

    async def delete(self, space_id: EmbeddingSpaceId, keys: Collection[ChunkKey]) -> int:
        """Delete the vectors of these chunks.

        Args:
            space_id: The space.
            keys: The chunks.

        Returns:
            How many were deleted.
        """
        async with self._write() as connection:
            await self._live(connection, space_id)
            ids = list((await self._chunk_ids(connection, list(set(keys)))).values())
            statement = text(_VECTOR_DELETE.format(table=_table(space_id))).bindparams(
                bindparam("keys", expanding=True)
            )
            gone = 0
            for start in range(0, len(ids), VECTOR_BATCH):
                batch = ids[start : start + VECTOR_BATCH]
                gone += (await connection.execute(statement, {"keys": batch})).rowcount
        return gone

    async def nearest(
        self,
        space_id: EmbeddingSpaceId,
        manifest_id: str,
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[VectorHit]:
        """Rank the manifest's chunks by cosine distance, in SQL.

        Args:
            space_id: The space.
            manifest_id: The manifest.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest chunks, nearest first, ties by chunk ID.
        """
        tags = TAG_CONDITIONS[tag_filter.match if tag_filter.tags else None]
        statement = text(_VECTOR_NEAREST.format(table=_table(space_id), tags=tags))
        async with self.engine.connect() as connection:
            dimensions = await self._dimensions(connection, space_id)
            params: dict[str, object] = {
                "query": _pack(checked_vector(query, dimensions)),
                "manifest": manifest_id,
                "limit": limit,
            }
            if tag_filter.tags:
                params["tags"] = json.dumps(list(tag_filter.tags))
            await self._load(connection)
            try:
                rows = (await connection.execute(statement, params)).all()
            except OperationalError:  # the table is gone: the space was retired meanwhile
                connection.info.get(_DIMENSIONS, {}).pop(space_id, None)
                await self._live(connection, space_id)
                raise
        return [VectorHit(chunk_id=ChunkId(r.chunk_id), distance=r.distance) for r in rows]

    async def coverage(self, space_id: EmbeddingSpaceId, manifest_id: str) -> VectorCoverage:
        """Count the manifest's chunk rows and those with a vector, in one query.

        Args:
            space_id: The space.
            manifest_id: The manifest.

        Returns:
            The counts.
        """
        statement = text(_VECTOR_COVERAGE.format(table=_table(space_id)))
        async with self.engine.connect() as connection:
            await self._live(connection, space_id)
            row = (await connection.execute(statement, {"manifest": manifest_id})).one()
        return VectorCoverage(chunks=row.chunks, embedded=row.embedded)

    async def missing(
        self, space_id: EmbeddingSpaceId, manifest_id: str, limit: int
    ) -> Sequence[ChunkKey]:
        """Return keys of the manifest's chunks without a vector, sorted.

        Args:
            space_id: The space.
            manifest_id: The manifest.
            limit: How many at most.

        Returns:
            The keys.
        """
        statement = text(_VECTOR_MISSING.format(table=_table(space_id)))
        async with self.engine.connect() as connection:
            await self._live(connection, space_id)
            rows = await connection.execute(statement, {"manifest": manifest_id, "limit": limit})
            return [(r.blob_sha, r.config_hash, r.position) for r in rows]

    def _write(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Open a write transaction (BEGIN IMMEDIATE, as the other repositories do).

        Returns:
            The transaction's connection, as a context manager.
        """
        return self.engine.execution_options(begin_immediate=True).begin()

    async def _find(
        self, connection: AsyncConnection, space_id: EmbeddingSpaceId
    ) -> EmbeddingSpace:
        """Read a space.

        Args:
            connection: The connection to read with.
            space_id: The space.

        Returns:
            It, in any state.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
        """
        row = (
            await connection.execute(select(spaces_table).where(spaces_table.c.id == space_id))
        ).one_or_none()
        if row is None:
            raise UnknownEmbeddingSpaceError(space_id)
        return _space(row)

    async def _live(
        self, connection: AsyncConnection, space_id: EmbeddingSpaceId
    ) -> EmbeddingSpace:
        """Read a space that is not retired.

        Args:
            connection: The connection to read with.
            space_id: The space.

        Returns:
            It.

        Raises:
            RetiredEmbeddingSpaceError: It was retired.
        """
        space = await self._find(connection, space_id)
        if space.state is SpaceState.RETIRED:
            raise RetiredEmbeddingSpaceError(space_id)
        return space

    async def _chunk_ids(
        self, connection: AsyncConnection, keys: Sequence[ChunkKey]
    ) -> dict[ChunkKey, int]:
        """Find the ``retrieval_chunks`` row of each key; keys without one are left out.

        Args:
            connection: The connection to read with.
            keys: The chunks.

        Returns:
            The row ID of each stored chunk.
        """
        found: dict[ChunkKey, int] = {}
        columns = tuple_(chunk_rows.c.blob_sha, chunk_rows.c.config_hash, chunk_rows.c.position)
        for start in range(0, len(keys), VECTOR_BATCH):  # three bound variables per key
            rows = await connection.execute(
                select(
                    chunk_rows.c.id,
                    chunk_rows.c.blob_sha,
                    chunk_rows.c.config_hash,
                    chunk_rows.c.position,
                ).where(columns.in_(keys[start : start + VECTOR_BATCH]))
            )
            found |= {(r.blob_sha, r.config_hash, r.position): r.id for r in rows}
        return found

    async def _load(self, connection: AsyncConnection) -> None:
        """Load sqlite-vec into this pooled connection, unless it already has it.

        Extension loading is switched on only for the call and off again right after.

        Args:
            connection: The connection that is about to search.

        Raises:
            VectorStoreUnavailableError: The package is missing, this Python cannot load
                extensions, or the extension does not load.
        """
        if connection.info.get(_LOADED):
            return
        try:
            path = self.extension()
        except ImportError as exc:  # the [ai] extra is not installed
            raise VectorStoreUnavailableError from exc
        raw = await connection.get_raw_connection()
        await _load_extension(raw.driver_connection, path)
        # Searches read every vector of a manifest: map the file instead of copying its pages.
        # Per connection, and only on connections that search.
        await connection.exec_driver_sql(f"PRAGMA mmap_size={VECTOR_MMAP_BYTES:d}")
        connection.info[_LOADED] = True

    async def _dimensions(self, connection: AsyncConnection, space_id: EmbeddingSpaceId) -> int:
        """Return a space's dimensions, read once per pooled connection (a spec never changes).

        Args:
            connection: The connection that is about to search.
            space_id: The space.

        Returns:
            Its dimensions.
        """
        known: dict[EmbeddingSpaceId, int] = connection.info.setdefault(_DIMENSIONS, {})
        if space_id not in known:
            known[space_id] = (await self._live(connection, space_id)).spec.dimensions
        return known[space_id]


async def _load_extension(driver: aiosqlite.Connection | None, path: str) -> None:
    """Load an extension into an aiosqlite connection, allowing it only for this call.

    Args:
        driver: The aiosqlite connection under SQLAlchemy's adapter.
        path: The extension's path.

    Raises:
        VectorStoreUnavailableError: This Python cannot load extensions, or this one.
    """
    if driver is None:
        raise VectorStoreUnavailableError
    try:
        await driver.enable_load_extension(value=True)
    except (AttributeError, sqlite3.Error) as exc:  # built without loadable extensions
        raise VectorStoreUnavailableError from exc
    try:
        await driver.load_extension(path)
    except sqlite3.Error as exc:
        raise VectorStoreUnavailableError from exc
    finally:
        await driver.enable_load_extension(value=False)
