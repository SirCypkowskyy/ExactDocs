"""Check that the vector store works in a built image's Python (#242).

Run inside the image, with the sqlite-vec wheel of the image's platform on PYTHONPATH (the base
image does not ship the `[ai]` extra; the `-ai` image of #246 will):

    docker run --rm -i --network none -v "$vec:/opt/sqlite-vec:ro" -e PYTHONPATH=/opt/sqlite-vec \
        --entrypoint python exactdocs:ci - < deploy/check_sqlite_vec.py

It proves what the decision record could only check on uv's Python: the image's Python
(python:3.14-slim-trixie) loads SQLite extensions, and ExactDocs' own loader finds sqlite-vec,
stores vectors and searches them with `vec_distance_cosine`. Exits non-zero otherwise.
"""

import asyncio
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.adapters.driven.sqlite_vectors import SqliteVectorIndex
from exactdocs.retrieval.models import (
    Chunk,
    ChunkId,
    ChunkSet,
    EmbeddingSpec,
    IndexedManifest,
    ManifestChunk,
    TagFilter,
)

NOW = datetime.now(UTC)


async def check(data_dir: Path) -> str:
    """Store two chunks with vectors and find the nearest one.

    Args:
        data_dir: An empty data directory.

    Returns:
        What was checked, for the log.
    """
    engine = open_database(Settings(data_dir=data_dir))
    try:
        await migrate(engine)
        chunks = tuple(
            Chunk(heading_path=(h,), occurrence_index=0, content=h, content_hash=h, anchor=h)
            for h in ("near", "far")
        )
        await SqliteChunkRepository(engine=engine).add(
            IndexedManifest(manifest_id="m", version_id="/x/y/v1", library="/x/y", indexed_at=NOW),
            {("b", "c"): ChunkSet(blob_sha="b", config_hash="c", chunks=chunks)},
            [
                ManifestChunk(
                    chunk_id=ChunkId(h),
                    article_path="a.md",
                    position=i,
                    total=2,
                    prev_chunk_id=None,
                    next_chunk_id=None,
                    tags=(),
                    chunk_set=("b", "c"),
                )
                for i, h in enumerate(("near", "far"))
            ],
        )
        vectors = SqliteVectorIndex(engine=engine)
        if not await vectors.available():
            return ""
        space = await vectors.create_space(
            EmbeddingSpec(profile_kind="check", model="m", dimensions=3), NOW
        )
        await vectors.upsert(space.id, {("b", "c", 0): [1, 0, 0], ("b", "c", 1): [0, 1, 0]})
        hits = await vectors.nearest(space.id, "m", [1, 0.1, 0], TagFilter(), 2)
        if [h.chunk_id for h in hits] != ["near", "far"]:
            return ""
        return f"SQLite {sqlite3.sqlite_version}, nearest at cosine distance {hits[0].distance:.4f}"
    finally:
        await engine.dispose()


def main() -> int:
    """Run the check in a temporary data directory.

    Returns:
        The exit status.
    """
    with tempfile.TemporaryDirectory() as data:
        found = asyncio.run(check(Path(data)))
    if not found:
        sys.stderr.write("sqlite-vec does not load or search in this Python\n")
        return 1
    sys.stdout.write(f"vector store OK: {found}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
