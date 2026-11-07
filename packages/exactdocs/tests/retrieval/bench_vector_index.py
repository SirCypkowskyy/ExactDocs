"""Benchmark of #242: exact search over 50,000 vectors of 1,024 dimensions in one manifest.

Not collected by pytest (a run takes a minute). Run it from the repository root:

    uv run python packages/exactdocs/tests/retrieval/bench_vector_index.py [chunks] [dimensions]

The target (docs/decisions/ai-retrieval.md, *Vector store*) is a p95 under 150 ms on the CI
runner; above it, an ANN index per space is the follow-up.
"""

import asyncio
import math
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from exactdocs.bootstrap.container import Container
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

T0 = datetime(2026, 11, 7, tzinfo=UTC)
PER_SET = 100
QUERIES = 40
WRITE_BATCH = 2_000


def _vector(seed: int, dimensions: int) -> list[float]:
    """A deterministic vector that differs per seed (its values do not matter, only its size)."""
    return [math.sin(seed * 0.618 + d * 1.37) for d in range(dimensions)]


async def main(chunks: int, dimensions: int) -> None:
    with tempfile.TemporaryDirectory() as data:
        container = Container.build(Settings(data_dir=Path(data)))
        async with container.running(jobs=False):
            engine = container.engine
            sets = {
                (f"blob{s}", "cfg"): ChunkSet(
                    blob_sha=f"blob{s}",
                    config_hash="cfg",
                    chunks=tuple(
                        Chunk(
                            heading_path=(f"h{i}",),
                            occurrence_index=0,
                            content=f"section {s}.{i}",
                            content_hash=f"{s}.{i}",
                            anchor=f"h{i}",
                        )
                        for i in range(PER_SET)
                    ),
                )
                for s in range(chunks // PER_SET)
            }
            rows = [
                ManifestChunk(
                    chunk_id=ChunkId(f"{blob}:{i}"),
                    article_path=f"docs/{blob}.md",
                    position=i,
                    total=PER_SET,
                    prev_chunk_id=None,
                    next_chunk_id=None,
                    tags=(),
                    chunk_set=(blob, config),
                )
                for blob, config in sets
                for i in range(PER_SET)
            ]
            manifest = IndexedManifest(
                manifest_id="m", version_id="/bench/x/v1", library="/bench/x", indexed_at=T0
            )
            await SqliteChunkRepository(engine=engine).add(manifest, sets, rows)
            vectors = SqliteVectorIndex(engine=engine)
            space = await vectors.create_space(
                EmbeddingSpec(profile_kind="bench", model="m", dimensions=dimensions), T0
            )
            keys = [(blob, config, i) for blob, config in sets for i in range(PER_SET)]
            started = time.perf_counter()
            for start in range(0, len(keys), WRITE_BATCH):
                await vectors.upsert(
                    space.id,
                    {
                        k: _vector(start + n, dimensions)
                        for n, k in enumerate(keys[start : start + WRITE_BATCH])
                    },
                )
            written = time.perf_counter() - started
            took = []
            for q in range(QUERIES):
                query = _vector(-q - 1, dimensions)
                started = time.perf_counter()
                hits = await vectors.nearest(space.id, "m", query, TagFilter(), 10)
                took.append((time.perf_counter() - started) * 1000)
                assert len(hits) == 10
            took.sort()
            p95 = took[int(0.95 * (len(took) - 1))]
            sys.stdout.write(
                f"{len(keys)} vectors x {dimensions} dimensions, one manifest\n"
                f"write: {written:.1f} s; nearest (k=10, {QUERIES} queries, first one loads "
                f"sqlite-vec): p50 {statistics.median(took):.1f} ms, p95 {p95:.1f} ms, "
                f"max {took[-1]:.1f} ms\n"
            )


if __name__ == "__main__":
    asyncio.run(main(*(int(a) for a in sys.argv[1:3])) if len(sys.argv) > 1 else main(50_000, 1024))
