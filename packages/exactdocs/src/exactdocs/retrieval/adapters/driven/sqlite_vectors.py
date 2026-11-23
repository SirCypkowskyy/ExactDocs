import importlib
import json
import sqlite3
import struct
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from itertools import batched

import aiosqlite
from sqlalchemy import bindparam, insert, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.retrieval.adapters.driven.vector_tables import (
    chunk_ids,
    iso,
    space_from_row,
    spaces_table,
    vector_table,
)
from exactdocs.retrieval.constants import (
    _DIMENSIONS,
    _LOADED,
    _VECTOR_ABSENT,
    _VECTOR_COVERAGE,
    _VECTOR_COVERAGE_MANY,
    _VECTOR_CREATE,
    _VECTOR_DELETE,
    _VECTOR_DROP,
    _VECTOR_MISSING,
    _VECTOR_MISSING_COUNT,
    _VECTOR_NEAREST,
    _VECTOR_PENDING,
    _VECTOR_PENDING_ARTICLES,
    _VECTOR_READ,
    _VECTOR_UPSERT,
    SQLITE_VEC_EXTENSION,
    SQLITE_VEC_MODULE,
    TAG_CONDITIONS,
    VECTOR_BATCH,
    VECTOR_MMAP_BYTES,
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
    PendingArticle,
    PendingChunks,
    SpaceState,
    TagFilter,
    VectorCoverage,
    VectorHit,
    checked_vector,
)

# The tables (`vector_tables.py`) are plain SQLite: each vector is a little-endian float32 BLOB,
# the format sqlite-vec reads, so storing, backing up and restoring them needs no extension; only
# the distance function in `nearest` does.


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

    def requirement(self) -> str:
        """Name what searching needs.

        Returns:
            ``sqlite-vec``.
        """
        return SQLITE_VEC_EXTENSION

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
            return [space_from_row(r) for r in rows]

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
                    created_at=iso(at),
                )
                .returning(spaces_table.c.id)
            )
            space_id = EmbeddingSpaceId(int(space_id or 0))
            await connection.exec_driver_sql(
                _VECTOR_CREATE.format(table=vector_table(space_id), size=4 * spec.dimensions)
            )
            row = (
                await connection.execute(select(spaces_table).where(spaces_table.c.id == space_id))
            ).one()
        return space_from_row(row)

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
                    activated_at=iso(space.activated_at or at),
                )
            )
            row = (
                await connection.execute(select(spaces_table).where(spaces_table.c.id == space_id))
            ).one()
        return space_from_row(row)

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
            await connection.exec_driver_sql(_VECTOR_DROP.format(table=vector_table(space_id)))

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
            ids = await chunk_ids(connection, list(blobs))
            rows = [{"key": ids[k], "embedding": blobs[k]} for k in blobs if k in ids]
            if rows:
                await connection.execute(
                    text(_VECTOR_UPSERT.format(table=vector_table(space_id))), rows
                )
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
            ids = list((await chunk_ids(connection, list(set(keys)))).values())
            statement = text(_VECTOR_DELETE.format(table=vector_table(space_id))).bindparams(
                bindparam("keys", expanding=True)
            )
            gone = 0
            for start in range(0, len(ids), VECTOR_BATCH):
                batch = ids[start : start + VECTOR_BATCH]
                gone += (await connection.execute(statement, {"keys": batch})).rowcount
        return gone

    async def stored(
        self, space_id: EmbeddingSpaceId, keys: Collection[ChunkKey]
    ) -> Mapping[ChunkKey, tuple[float, ...]]:
        """Read back the vectors of these chunks (what an external copy is written from).

        Args:
            space_id: The space.
            keys: The chunks.

        Returns:
            Each vector found, by chunk.
        """
        statement = text(_VECTOR_READ.format(table=vector_table(space_id))).bindparams(
            bindparam("keys", expanding=True)
        )
        async with self.engine.connect() as connection:
            await self._live(connection, space_id)
            ids = await chunk_ids(connection, list(set(keys)))
            by_id = {row_id: key for key, row_id in ids.items()}
            found: dict[ChunkKey, tuple[float, ...]] = {}
            for batch in batched(list(by_id), VECTOR_BATCH, strict=False):
                for row in await connection.execute(statement, {"keys": list(batch)}):
                    blob: bytes = row.embedding
                    found[by_id[row.chunk_key]] = struct.unpack(f"<{len(blob) // 4}f", blob)
        return found

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

        Raises:
            OperationalError: The query failed although the space is not retired (a retired space
                raises ``RetiredEmbeddingSpaceError`` instead).
        """
        tags = TAG_CONDITIONS[tag_filter.match if tag_filter.tags else None]
        statement = text(_VECTOR_NEAREST.format(table=vector_table(space_id), tags=tags))
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
        statement = text(_VECTOR_COVERAGE.format(table=vector_table(space_id)))
        async with self.engine.connect() as connection:
            await self._live(connection, space_id)
            row = (await connection.execute(statement, {"manifest": manifest_id})).one()
        return VectorCoverage(chunks=row.chunks, embedded=row.embedded)

    async def coverage_many(
        self, space_id: EmbeddingSpaceId, manifest_ids: Collection[str]
    ) -> Mapping[str, VectorCoverage]:
        """Count the chunk rows of these manifests and those with a vector, in one query.

        Args:
            space_id: The space.
            manifest_ids: The manifests.

        Returns:
            The counts per manifest that has chunks.
        """
        if not manifest_ids:
            return {}
        statement = text(_VECTOR_COVERAGE_MANY.format(table=vector_table(space_id))).bindparams(
            bindparam("manifests", expanding=True)
        )
        async with self.engine.connect() as connection:
            await self._live(connection, space_id)
            rows = await connection.execute(statement, {"manifests": list(manifest_ids)})
            return {
                r.manifest_id: VectorCoverage(chunks=r.chunks, embedded=r.embedded) for r in rows
            }

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
        statement = text(_VECTOR_MISSING.format(table=vector_table(space_id)))
        async with self.engine.connect() as connection:
            await self._live(connection, space_id)
            rows = await connection.execute(statement, {"manifest": manifest_id, "limit": limit})
            return [(r.blob_sha, r.config_hash, r.position) for r in rows]

    async def count_missing(self, space_id: EmbeddingSpaceId, manifest_id: str) -> int:
        """Count the manifest's chunks without a vector, each once, in one query.

        Args:
            space_id: The space.
            manifest_id: The manifest.

        Returns:
            The count.
        """
        statement = text(_VECTOR_MISSING_COUNT.format(table=vector_table(space_id)))
        async with self.engine.connect() as connection:
            await self._live(connection, space_id)
            return int(
                (await connection.execute(statement, {"manifest": manifest_id})).scalar_one()
            )

    async def pending(
        self, space_id: EmbeddingSpaceId | None, manifest_ids: Collection[str]
    ) -> PendingChunks:
        """Count the distinct chunks of these manifests without a vector in the space, in SQL.

        Args:
            space_id: The space; ``None`` counts every chunk.
            manifest_ids: The manifests.

        Returns:
            The chunks and the characters of their text and heading paths.
        """
        if not manifest_ids:
            return PendingChunks(chunks=0, characters=0)
        missing = "" if space_id is None else _VECTOR_ABSENT.format(table=vector_table(space_id))
        statement = text(_VECTOR_PENDING.format(missing=missing)).bindparams(
            bindparam("manifests", expanding=True)
        )
        by_article = text(_VECTOR_PENDING_ARTICLES.format(missing=missing)).bindparams(
            bindparam("manifests", expanding=True)
        )
        params = {"manifests": sorted(set(manifest_ids))}
        async with self.engine.connect() as connection:
            if space_id is not None:
                await self._live(connection, space_id)
            row = (await connection.execute(statement, params)).one()
            articles = (await connection.execute(by_article, params)).all()
        return PendingChunks(
            chunks=row.chunks,
            characters=row.characters,
            articles=tuple(
                PendingArticle(
                    manifest_id=a.manifest_id, article_path=a.article_path, chunks=a.chunks
                )
                for a in articles
            ),
        )

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
        return space_from_row(row)

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
