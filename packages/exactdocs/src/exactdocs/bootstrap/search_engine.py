"""Which search engine answers on PostgreSQL: chosen at start from what the database offers.

With ParadeDB's `pg_search` installed in the database, its BM25 (``PgSearchIndex``) answers, as
FTS5 does on SQLite; without it, PostgreSQL's own full-text search (``PostgresSearchIndex``) does.
Both read and write the same `retrieval_search` rows, so the choice can change from one start to
the next without a rebuild. ``/api/health`` names the engine in use (``search_engine``).
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from exactdocs.retrieval.adapters.driven.pg_search import PgSearchIndex
from exactdocs.retrieval.adapters.driven.postgres_fts import PostgresSearchIndex
from exactdocs.retrieval.models import (
    ChunkSet,
    ManifestHit,
    RebuiltIndex,
    SearchHit,
    SearchIndexState,
    TagFilter,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- chosen at start
class PostgresSearchChoice:
    """Implements ``SearchIndex`` and ``SearchIndexMaintenance`` with the engine chosen at start.

    Full-text search answers until ``choose`` has run (it needs the migrated database).
    """

    full_text: PostgresSearchIndex
    """PostgreSQL's full-text search: every database has it."""
    bm25: PgSearchIndex
    """`pg_search`'s BM25: when the database has the extension."""
    chosen: PostgresSearchIndex | PgSearchIndex = field(init=False)
    """The engine that answers."""

    def __post_init__(self) -> None:
        """Answer with full-text search until ``choose`` runs."""
        self.chosen = self.full_text

    async def choose(self, *, create: bool) -> None:
        """Answer with `pg_search` when the database has it (making its index), else full-text.

        Args:
            create: Make the BM25 index when it is missing (``False``: a read-only process).
        """
        missing = await self.bm25.prepare(create=create)
        if missing is None:
            self.chosen = self.bm25
            logger.info("Search uses pg_search's BM25.")
            return
        self.chosen = self.full_text
        logger.info(
            "Search uses PostgreSQL full-text search, not pg_search's BM25: %s. Rankings may "
            "differ slightly from SQLite's.",
            missing,
        )

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index a stored chunk set (both engines write the same rows).

        Args:
            chunk_set: A stored chunk set.
        """
        await self.chosen.index(chunk_set)

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Search one manifest with the chosen engine.

        Args:
            manifest_id: The manifest searched.
            query: What the caller typed.
            tag_filter: Tags the chunks must have.
            limit: How many hits at most.

        Returns:
            The hits, best first.
        """
        return await self.chosen.search(manifest_id, query, tag_filter, limit)

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Search several manifests at once with the chosen engine.

        Args:
            manifest_ids: The manifests searched.
            query: What the caller typed.
            tag_filter: Tags the chunks must have.
            limit: How many hits at most, over all manifests.

        Returns:
            The hits with their manifests, best first.
        """
        return await self.chosen.search_many(manifest_ids, query, tag_filter, limit)

    async def count_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the matches per manifest with the chosen engine.

        Args:
            manifest_ids: The manifests searched.
            query: What the caller typed.
            tag_filter: Tags the chunks must have.

        Returns:
            Matches per manifest; a manifest without any is left out.
        """
        return await self.chosen.count_many(manifest_ids, query, tag_filter)

    async def state(self) -> SearchIndexState:
        """Return the index's formats and the engine that answers.

        Returns:
            The chosen engine's state.
        """
        return await self.chosen.state()

    async def rebuild(self) -> RebuiltIndex:
        """Rebuild the index for the chosen engine.

        Returns:
            The format written and the number of rows.
        """
        return await self.chosen.rebuild()
