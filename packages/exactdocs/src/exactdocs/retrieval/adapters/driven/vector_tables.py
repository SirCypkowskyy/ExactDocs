"""What the SQLite and PostgreSQL vector stores share: the tables they read and how rows map.

`retrieval_embedding_spaces` is created by an Alembic revision in `exactdocs.bootstrap`; this is
only the stores' query-side description of it. The vectors of a space live in a table the store
creates and drops itself (`retrieval_vec_<id>`), like the search index tables of
`exactdocs reindex`: one fixed dimension per table, and no way to mix two models. Each row is a
`retrieval_chunks` row (its `id`, with ON DELETE CASCADE, so garbage collection removes vectors
with their chunk sets) and its vector, in the store's own format.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, Integer, MetaData, Row, Table, Text, select, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection

from exactdocs.retrieval.constants import VECTOR_BATCH, VECTOR_TABLE_PREFIX
from exactdocs.retrieval.models import (
    ChunkKey,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    SpaceState,
    VectorMetric,
)

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


def vector_table(space_id: EmbeddingSpaceId) -> str:
    """Name the vector table of a space (an integer ID: safe to put in SQL).

    Args:
        space_id: The space.

    Returns:
        ``retrieval_vec_<id>``.
    """
    return f"{VECTOR_TABLE_PREFIX}{int(space_id)}"


def iso(moment: datetime) -> str:
    """UTC ISO 8601, so stored timestamps compare as text.

    Args:
        moment: An aware time.

    Returns:
        The text stored.
    """
    return moment.astimezone(UTC).isoformat()


def space_from_row(row: Row[Any]) -> EmbeddingSpace:
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


async def chunk_ids(connection: AsyncConnection, keys: Sequence[ChunkKey]) -> dict[ChunkKey, int]:
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
