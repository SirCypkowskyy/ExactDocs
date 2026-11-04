import json
from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    delete,
    exists,
    insert,
    select,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.retrieval.errors import ChunkSetMismatchError
from exactdocs.retrieval.models import (
    Chunk,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    IndexedManifest,
    ManifestChunk,
    Removed,
    StoredChunk,
)

# Retrieval's tables, prefixed `retrieval_`. The schema itself is created by an Alembic revision
# in `exactdocs.bootstrap`; this is only the adapter's query-side description of it. There is no
# foreign key to the catalog: manifest IDs are held by value.
metadata = MetaData()
chunk_set_rows = Table(
    "retrieval_chunk_sets",
    metadata,
    Column("blob_sha", Text, primary_key=True),
    Column("config_hash", Text, primary_key=True),
    Column("digest", Text, nullable=False),  # ChunkSet.digest, to notice a stale config_hash
)
chunks = Table(
    "retrieval_chunks",
    metadata,
    Column("blob_sha", Text, primary_key=True),
    Column("config_hash", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("heading_path", Text, nullable=False),  # JSON list
    Column("occurrence_index", Integer, nullable=False),
    Column("content", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("anchor", Text, nullable=False),
    Column("code_languages", Text, nullable=False),  # JSON list
    ForeignKeyConstraint(
        ["blob_sha", "config_hash"],
        ["retrieval_chunk_sets.blob_sha", "retrieval_chunk_sets.config_hash"],
        ondelete="CASCADE",
    ),
)
indexed_manifests = Table(
    "retrieval_manifests",
    metadata,
    Column("manifest_id", Text, primary_key=True),
    Column("version_id", Text, nullable=False),
    Column("library", Text, nullable=False),
    Column("indexed_at", Text, nullable=False),  # ISO 8601, UTC
    Index("ix_retrieval_manifests_library_indexed_at", "library", "indexed_at"),
    Index("ix_retrieval_manifests_indexed_at", "indexed_at"),
)
manifest_chunks = Table(
    "retrieval_manifest_chunks",
    metadata,
    Column(
        "manifest_id",
        Text,
        ForeignKey("retrieval_manifests.manifest_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("chunk_id", Text, primary_key=True),
    Column("article_path", Text, nullable=False),
    Column("position", Integer, nullable=False),
    Column("total", Integer, nullable=False),
    Column("prev_chunk_id", Text),
    Column("next_chunk_id", Text),
    Column("tags", Text, nullable=False),  # JSON list
    Column("blob_sha", Text, nullable=False),
    Column("config_hash", Text, nullable=False),
    ForeignKeyConstraint(
        ["blob_sha", "config_hash"],
        ["retrieval_chunk_sets.blob_sha", "retrieval_chunk_sets.config_hash"],
    ),
    Index("ix_retrieval_manifest_chunks_article", "manifest_id", "article_path", "position"),
)


def _iso(moment: datetime) -> str:
    """UTC ISO 8601, so stored timestamps compare as text."""
    return moment.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class SqliteChunkRepository:
    """Implements ``ports.driven.ChunkRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    def _write(self) -> AbstractAsyncContextManager[AsyncConnection]:
        # BEGIN IMMEDIATE: see the catalog's manifest repository.
        return self.engine.execution_options(begin_immediate=True).begin()

    async def add(
        self,
        manifest: IndexedManifest,
        chunk_sets: Mapping[ChunkSetKey, ChunkSet],
        rows: Sequence[ManifestChunk],
    ) -> int | None:
        """Store rows and the new chunk sets; ``None`` when the manifest is already indexed."""
        async with self._write() as connection:
            if await connection.scalar(
                select(exists().where(indexed_manifests.c.manifest_id == manifest.manifest_id))
            ):
                return None
            # Look up only this manifest's keys (batched), never the whole table.
            known: dict[ChunkSetKey, str] = {}
            keys = list(chunk_sets)
            for start in range(0, len(keys), 400):  # two bound variables per key
                found = await connection.execute(
                    select(chunk_set_rows).where(
                        tuple_(chunk_set_rows.c.blob_sha, chunk_set_rows.c.config_hash).in_(
                            keys[start : start + 400]
                        )
                    )
                )
                known |= {(r.blob_sha, r.config_hash): r.digest for r in found}
            for key, digest in known.items():
                if chunk_sets[key].digest != digest:
                    raise ChunkSetMismatchError(*key)
            new = [s for key, s in chunk_sets.items() if key not in known]
            if new:
                await connection.execute(
                    insert(chunk_set_rows),
                    [
                        {"blob_sha": s.blob_sha, "config_hash": s.config_hash, "digest": s.digest}
                        for s in new
                    ],
                )
            chunk_rows = [
                {
                    "blob_sha": s.blob_sha,
                    "config_hash": s.config_hash,
                    "position": i,
                    "heading_path": json.dumps(c.heading_path),
                    "occurrence_index": c.occurrence_index,
                    "content": c.content,
                    "content_hash": c.content_hash,
                    "anchor": c.anchor,
                    "code_languages": json.dumps(c.code_languages),
                }
                for s in new
                for i, c in enumerate(s.chunks)
            ]
            if chunk_rows:
                await connection.execute(insert(chunks), chunk_rows)
            await connection.execute(
                insert(indexed_manifests).values(
                    manifest_id=manifest.manifest_id,
                    version_id=manifest.version_id,
                    library=manifest.library,
                    indexed_at=_iso(manifest.indexed_at),
                )
            )
            if rows:
                await connection.execute(
                    insert(manifest_chunks),
                    [
                        {
                            "manifest_id": manifest.manifest_id,
                            "chunk_id": r.chunk_id,
                            "article_path": r.article_path,
                            "position": r.position,
                            "total": r.total,
                            "prev_chunk_id": r.prev_chunk_id,
                            "next_chunk_id": r.next_chunk_id,
                            "tags": json.dumps(r.tags),
                            "blob_sha": r.chunk_set[0],
                            "config_hash": r.chunk_set[1],
                        }
                        for r in rows
                    ],
                )
            return len(new)

    async def get(self, manifest_id: str, chunk_id: ChunkId) -> StoredChunk | None:
        """Return one chunk of the manifest with its content, or ``None``."""
        query = (
            select(manifest_chunks, chunks, indexed_manifests.c.version_id)
            .select_from(
                manifest_chunks.join(
                    indexed_manifests,
                    indexed_manifests.c.manifest_id == manifest_chunks.c.manifest_id,
                ).join(
                    chunks,
                    (chunks.c.blob_sha == manifest_chunks.c.blob_sha)
                    & (chunks.c.config_hash == manifest_chunks.c.config_hash)
                    & (chunks.c.position == manifest_chunks.c.position),
                )
            )
            .where(
                manifest_chunks.c.manifest_id == manifest_id, manifest_chunks.c.chunk_id == chunk_id
            )
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        if row is None:
            return None
        return StoredChunk(
            manifest_id=manifest_id,
            version_id=row.version_id,
            row=ManifestChunk(
                chunk_id=ChunkId(row.chunk_id),
                article_path=row.article_path,
                position=row.position,
                total=row.total,
                prev_chunk_id=None if row.prev_chunk_id is None else ChunkId(row.prev_chunk_id),
                next_chunk_id=None if row.next_chunk_id is None else ChunkId(row.next_chunk_id),
                tags=tuple(json.loads(row.tags)),
                chunk_set=(row.blob_sha, row.config_hash),
            ),
            chunk=Chunk(
                heading_path=tuple(json.loads(row.heading_path)),
                occurrence_index=row.occurrence_index,
                content=row.content,
                content_hash=row.content_hash,
                anchor=row.anchor,
                code_languages=tuple(json.loads(row.code_languages)),
            ),
        )

    async def find_manifests(
        self, *, manifest_id: str | None, library: str | None, indexed_before: datetime | None
    ) -> Sequence[IndexedManifest]:
        """Return the indexed manifests that match every given filter."""
        query = select(indexed_manifests)
        if manifest_id is not None:
            query = query.where(indexed_manifests.c.manifest_id == manifest_id)
        if library is not None:
            query = query.where(indexed_manifests.c.library == library)
        if indexed_before is not None:
            query = query.where(indexed_manifests.c.indexed_at < _iso(indexed_before))
        async with self.engine.connect() as connection:
            found = (await connection.execute(query)).all()
        return tuple(
            IndexedManifest(
                manifest_id=r.manifest_id,
                version_id=r.version_id,
                library=r.library,
                indexed_at=datetime.fromisoformat(r.indexed_at),
            )
            for r in found
        )

    async def remove(self, manifest_ids: Collection[str]) -> Removed:
        """Delete these manifests' rows, then every chunk set no row points at."""
        async with self._write() as connection:
            gone = 0
            for batch in _batches(list(manifest_ids)):
                gone += (
                    await connection.execute(
                        delete(indexed_manifests).where(indexed_manifests.c.manifest_id.in_(batch))
                    )
                ).rowcount
            # Sets with no chunk rows (articles without sections) are never referenced, so they
            # go here too and count in `chunk_sets`.
            unused = await connection.execute(
                delete(chunk_set_rows).where(
                    ~exists().where(
                        manifest_chunks.c.blob_sha == chunk_set_rows.c.blob_sha,
                        manifest_chunks.c.config_hash == chunk_set_rows.c.config_hash,
                    )
                )
            )
        return Removed(manifests=gone, chunk_sets=unused.rowcount)


def _batches(items: list[str], size: int = 500) -> list[list[str]]:
    """Slices small enough for SQLite's bound-variable limit."""
    return [items[i : i + size] for i in range(0, len(items), size)]
