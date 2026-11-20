"""The vector store on PostgreSQL: pgvector, one ``vector(<dimensions>)`` table per space.

It keeps the layout of the SQLite store (``sqlite_vectors.py``): ``retrieval_embedding_spaces``
lists the spaces, and the vectors of a space live in ``retrieval_vec_<id>``, which this adapter
creates and drops, each row a ``retrieval_chunks`` row (``ON DELETE CASCADE``) and its vector.
Search is exact, pgvector's cosine distance ``<=>`` over one manifest's chunks, with no index:
the same results and order as on SQLite, and no limit at 2,000 dimensions as an HNSW index would
have.

pgvector's extension is looked for (and created when the role may) once per process, the first
time the store is needed: an instance without an embedding model never asks. Its Python package
(``[ai]`` extra) is imported only then, for its SQLAlchemy type.
"""

import importlib
import json
import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Row, bindparam, insert, select, text, update
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.types import TypeEngine

from exactdocs.retrieval.adapters.driven.vector_tables import (
    chunk_ids,
    iso,
    space_from_row,
    spaces_table,
    vector_table,
)
from exactdocs.retrieval.constants import (
    _PG_EXTENSION_CREATE,
    _PG_EXTENSION_SCHEMA,
    _PG_EXTENSIONS_SCHEMA_WRITABLE,
    _PG_READ_ONLY,
    _PG_VECTOR_ANALYZE,
    _PG_VECTOR_CREATE,
    _PG_VECTOR_INLINE,
    _PG_VECTOR_NEAREST,
    _PG_VECTOR_PENDING,
    _PG_VECTOR_UPSERT,
    _VECTOR_ABSENT,
    _VECTOR_COVERAGE,
    _VECTOR_COVERAGE_MANY,
    _VECTOR_DELETE,
    _VECTOR_DROP,
    _VECTOR_MISSING,
    _VECTOR_MISSING_COUNT,
    _VECTOR_PENDING_ARTICLES,
    EXTENSIONS_SCHEMA,
    PGVECTOR_EXTENSION,
    PGVECTOR_MODULE,
    POSTGRES_TAG_CONDITIONS,
    TRANSIENT_SQLSTATES,
    VECTOR_BATCH,
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

logger = logging.getLogger(__name__)


def _pgvector_type() -> TypeEngine[Any]:
    """Return pgvector's SQLAlchemy type, importing its package (``[ai]`` extra) only now.

    Returns:
        A ``VECTOR``: it sends a list of floats as pgvector's text form.
    """
    return importlib.import_module(PGVECTOR_MODULE).VECTOR()


def _first_line(error: DBAPIError) -> str:
    """Return the first line of what the database answered.

    Args:
        error: The failure.

    Returns:
        Its message, without PostgreSQL's detail lines.
    """
    lines = str(error.orig).strip().splitlines()
    return lines[0] if lines else type(error.orig).__name__


def _transient(error: DBAPIError) -> bool:
    """Tell whether a failure may pass by itself (the server is away, a lock, a restart).

    Args:
        error: What the database answered.

    Returns:
        True when the check should be tried again later instead of given up.
    """
    sqlstate = getattr(error.orig, "sqlstate", None)
    return sqlstate is None or sqlstate.startswith(TRANSIENT_SQLSTATES)


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresVectorIndex:
    """Implements ``ports.driven.VectorIndex`` with pgvector.

    What a check found is kept for the life of the process (a search asks at every call): once
    the extension is there it stays, and an operator who installs it after a failed check
    restarts the server. A failure that may pass (the database unreachable) is not kept.
    """

    engine: AsyncEngine
    """The application database (PostgreSQL)."""
    extension: str = PGVECTOR_EXTENSION
    """The extension's name (tests: one that is not installed)."""
    vector_type: Callable[[], TypeEngine[Any]] = _pgvector_type
    """Returns pgvector's SQLAlchemy type (raises ``ImportError`` without the ``[ai]`` extra)."""
    _found: dict[str, str] = field(default_factory=dict)
    """``schema``: where the extension is, once found; ``missing``: why it cannot be had."""
    _dimensions: dict[EmbeddingSpaceId, int] = field(default_factory=dict)
    """The dimensions of each space searched (a spec never changes)."""

    def requirement(self) -> str:
        """Name what the store needs.

        Returns:
            The extension, ``vector``.
        """
        return self.extension

    async def available(self) -> bool:
        """Find pgvector's extension, or create it, once; and say whether the store can search.

        Returns:
            False when the ``[ai]`` extra is missing, or the extension is not in the database and
            this role may not (or the server cannot) create it.
        """
        try:
            await self._schema()
        except VectorStoreUnavailableError:
            return False
        return True

    async def spaces(self) -> Sequence[EmbeddingSpace]:
        """List every space, oldest first.

        Returns:
            The spaces.
        """
        async with self.engine.connect() as connection:
            rows = await connection.execute(select(spaces_table).order_by(spaces_table.c.id))
            return [space_from_row(r) for r in rows]

    async def create_space(self, spec: EmbeddingSpec, at: datetime) -> EmbeddingSpace:
        """Record the space and create its ``vector(<dimensions>)`` table, in one transaction.

        Args:
            spec: The model and format of its vectors.
            at: When it is created.

        Returns:
            The new space.
        """
        schema = await self._schema()
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
            table = vector_table(space_id)
            await connection.exec_driver_sql(
                _PG_VECTOR_CREATE.format(
                    table=table, schema=schema, dimensions=int(spec.dimensions)
                )
            )
            await connection.exec_driver_sql(_PG_VECTOR_INLINE.format(table=table))
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
            # It was just filled: searches must not wait for autovacuum to get good plans.
            await connection.exec_driver_sql(
                _PG_VECTOR_ANALYZE.format(table=vector_table(space_id))
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
        # Everything that needs no turn comes first: finding the extension may take one, and
        # checking the vectors should not keep the other writers waiting.
        dimensions = await self._dimensions_of(space_id)
        checked = {k: checked_vector(v, dimensions) for k, v in vectors.items()}
        schema = await self._schema()
        statement = text(
            _PG_VECTOR_UPSERT.format(table=vector_table(space_id), schema=schema)
        ).bindparams(bindparam("embedding", type_=self.vector_type()))
        async with self._write() as connection:
            await self._live(connection, space_id)  # not retired meanwhile
            ids = await chunk_ids(connection, list(checked))
            rows = [{"key": ids[k], "embedding": list(checked[k])} for k in checked if k in ids]
            if rows:
                await connection.execute(statement, rows)
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
            ProgrammingError: The query failed although the space is not retired (a retired space
                raises ``RetiredEmbeddingSpaceError`` instead).
        """
        schema = await self._schema()
        checked = checked_vector(query, await self._dimensions_of(space_id))
        async with self.engine.connect() as connection:
            tags = POSTGRES_TAG_CONDITIONS[tag_filter.match if tag_filter.tags else None]
            statement = text(
                _PG_VECTOR_NEAREST.format(table=vector_table(space_id), schema=schema, tags=tags)
            ).bindparams(bindparam("query", type_=self.vector_type()))
            params: dict[str, object] = {
                "query": list(checked),
                "manifest": manifest_id,
                "limit": limit,
            }
            if tag_filter.tags:
                params["tags"] = json.dumps(list(tag_filter.tags))
            try:
                rows = (await connection.execute(statement, params)).all()
            except ProgrammingError:  # the table is gone: the space was retired meanwhile
                await connection.rollback()
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

        Plain SQL over the chunk tables: it needs no extension, so an estimate works before
        pgvector is installed.

        Args:
            space_id: The space; ``None`` counts every chunk.
            manifest_ids: The manifests.

        Returns:
            The chunks and the characters of their text and heading paths.
        """
        if not manifest_ids:
            return PendingChunks(chunks=0, characters=0)
        missing = "" if space_id is None else _VECTOR_ABSENT.format(table=vector_table(space_id))
        statement = text(_PG_VECTOR_PENDING.format(missing=missing)).bindparams(
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
            chunks=int(row.chunks),
            characters=int(row.characters),
            articles=tuple(
                PendingArticle(
                    manifest_id=a.manifest_id, article_path=a.article_path, chunks=int(a.chunks)
                )
                for a in articles
            ),
        )

    def _write(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Open a write transaction that takes its turn with the others (``begin_immediate``).

        Returns:
            The transaction's connection, as a context manager.
        """
        return self.engine.execution_options(begin_immediate=True).begin()

    async def _schema(self) -> str:
        """Find the schema of pgvector's extension, creating the extension if it is not there.

        A plain read first (no write turn): once the extension is there, that is all it takes,
        and the answer is kept for the life of the process. Only when it is missing, and this
        process may write, it takes the write turn (two processes never create it together)
        and creates it. What cannot change by itself (the role may not create it, the server
        does not have pgvector) is kept too; a read-only process (``serve --stdio``), a busy
        write turn or an unreachable database is asked again next time. The schema is quoted,
        ready for SQL.

        Returns:
            The quoted schema, e.g. ``public``.

        Raises:
            VectorStoreUnavailableError: The ``[ai]`` extra is missing, or the extension is not
                in the database and cannot be created here (now).
        """
        if "schema" in self._found:
            return self._found["schema"]
        if "missing" in self._found:
            raise VectorStoreUnavailableError(self._found["missing"])
        try:
            self.vector_type()
        except ImportError as exc:
            self._found["missing"] = "pgvector's Python package (the [ai] extra) is not installed"
            raise VectorStoreUnavailableError(self._found["missing"]) from exc
        schema, read_only = await self._look()
        if schema is None and read_only:
            reason = (
                f'the PostgreSQL extension "{self.extension}" (pgvector) is not created yet in '
                "this database, and this process only reads: waiting for the ExactDocs server to "
                f"create it (or a superuser: CREATE EXTENSION {self.extension}; on Supabase, "
                f"CREATE EXTENSION {self.extension} WITH SCHEMA {EXTENSIONS_SCHEMA}, as postgres)"
            )
            raise VectorStoreUnavailableError(reason)
        if schema is None:
            schema = await self._create()
        self._found["schema"] = schema
        return schema

    def _check_usable(self, found: Row[Any] | None) -> str | None:
        """Return the quoted schema of the extension, or ``None`` when it is not there.

        Args:
            found: The extension's schema row (``_PG_EXTENSION_SCHEMA``), if any.

        Returns:
            The schema, quoted for SQL.

        Raises:
            VectorStoreUnavailableError: This role may not use that schema (kept).
        """
        if found is None:
            return None
        if not found.usable:
            reason = (
                f'the PostgreSQL extension "{self.extension}" (pgvector) is in schema '
                f'"{found.schema}", which this role may not use: run GRANT USAGE ON SCHEMA '
                f"{self._quote(str(found.schema))} TO {self._quote(str(found.role))} (then "
                "restart ExactDocs); until then hybrid search answers with BM25"
            )
            self._found["missing"] = reason
            logger.warning("vector search is off: %s", reason)
            raise VectorStoreUnavailableError(reason)
        return self._quote(str(found.schema))

    async def _look(self) -> tuple[str | None, bool]:
        """Read where the extension is, and whether this process's transactions are read-only.

        Returns:
            The quoted schema (``None`` when the extension is not in the database), and whether
            this process may not write.

        Raises:
            VectorStoreUnavailableError: The database did not answer (not kept).
        """
        try:
            async with self.engine.connect() as connection:
                found = (
                    await connection.execute(text(_PG_EXTENSION_SCHEMA), {"name": self.extension})
                ).first()
                read_only = await connection.scalar(text(_PG_READ_ONLY))
        except DBAPIError as exc:
            reason = f"the database did not answer: {_first_line(exc)}"
            raise VectorStoreUnavailableError(reason) from exc
        return self._check_usable(found), read_only == "on"

    async def _create(self) -> str:
        """Create the extension in a write turn (it may have been created meanwhile).

        Returns:
            The quoted schema it is in.

        Raises:
            VectorStoreUnavailableError: It cannot be created; kept unless it may pass.
        """
        try:
            async with self._write() as connection:
                return await self._install(connection)
        except DBAPIError as exc:
            reason = (
                f'the PostgreSQL extension "{self.extension}" (pgvector) is not in this database '
                f"and could not be created: {_first_line(exc)}. "
                f"A superuser can run CREATE EXTENSION {self.extension} in this database (on "
                f"Supabase, CREATE EXTENSION {self.extension} WITH SCHEMA {EXTENSIONS_SCHEMA}, as "
                "postgres), then restart ExactDocs; until then hybrid search answers with BM25"
            )
            if not _transient(exc):
                self._found["missing"] = reason
                logger.warning("vector search is off: %s", reason)
            raise VectorStoreUnavailableError(reason) from exc
        except RuntimeError as exc:
            # The write turn timed out (bootstrap's WriteTurnTimeoutError, which a domain
            # adapter cannot import): another process writes for long; ask again next time.
            reason = f"the extension could not be created now: {exc}"
            raise VectorStoreUnavailableError(reason) from exc

    async def _install(self, connection: AsyncConnection) -> str:
        """Find the extension's schema; create the extension first when it is not there.

        Args:
            connection: A write turn's connection.

        Returns:
            The schema, quoted.

        Raises:
            VectorStoreUnavailableError: The extension is still not there once created.
        """
        name = {"name": self.extension}
        found = (await connection.execute(text(_PG_EXTENSION_SCHEMA), name)).first()
        if found is None:
            into = await connection.scalar(
                text(_PG_EXTENSIONS_SCHEMA_WRITABLE), {"schema": EXTENSIONS_SCHEMA}
            )
            schema = f" WITH SCHEMA {self._quote(EXTENSIONS_SCHEMA)}" if into else ""
            await connection.exec_driver_sql(
                _PG_EXTENSION_CREATE.format(extension=self._quote(self.extension), schema=schema)
            )
            found = (await connection.execute(text(_PG_EXTENSION_SCHEMA), name)).first()
            logger.info("created the PostgreSQL extension %r for vector search", self.extension)
        schema = self._check_usable(found)
        if schema is None:  # CREATE EXTENSION IF NOT EXISTS succeeded: it is there
            reason = f'the PostgreSQL extension "{self.extension}" was not found once created'
            raise VectorStoreUnavailableError(reason)
        return schema

    def _quote(self, name: str) -> str:
        """Quote an identifier for SQL.

        Args:
            name: A schema or extension name.

        Returns:
            It, quoted where PostgreSQL needs it.
        """
        return self.engine.dialect.identifier_preparer.quote(name)

    async def _dimensions_of(self, space_id: EmbeddingSpaceId) -> int:
        """Return a space's dimensions, read once (a spec never changes).

        Args:
            space_id: The space.

        Returns:
            Its dimensions.
        """
        if space_id not in self._dimensions:
            async with self.engine.connect() as connection:
                space = await self._live(connection, space_id)
            self._dimensions[space_id] = space.spec.dimensions
        return self._dimensions[space_id]

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
