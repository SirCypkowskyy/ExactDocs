"""The search index on PostgreSQL with ParadeDB's `pg_search`: BM25, as FTS5 ranks on SQLite.

It reads the table PostgreSQL's full-text search keeps (`retrieval_search`, revision 0c4e8a2f6b19:
FTS5's four columns, the identifier column included) through a BM25 index on those columns
(`retrieval_search_bm25`), made at start by ``prepare`` when the database has the extension. The
rows are written, rebuilt and versioned by that table's own adapter (``table``): both engines
share them, so a database can move from one to the other without a rebuild. Words are cut as FTS5
cuts them (`_PG_SEARCH_PATTERN`); each field's BM25 score is boosted by FTS5's column weight.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.retrieval.constants import (
    _PG_BM25_EXISTS,
    _PG_BM25_INDEX,
    _PG_BM25_INDEX_NEXT,
    _PG_BM25_LOCK,
    _PG_BM25_RENAME,
    _PG_COUNT_BM25,
    _PG_EXTENSION,
    _PG_QUERY,
    _PG_SEARCH_BM25,
    _PG_SEARCH_MATCH,
    _PG_WHOLE_IDENTIFIER,
    PG_SEARCH_ENGINE,
    PG_SEARCH_EXTENSION,
    POSTGRES_HEADLINE,
    POSTGRES_SNIPPET_WORDS,
    POSTGRES_TAG_CONDITIONS,
)
from exactdocs.retrieval.models import (
    ChunkId,
    ChunkSet,
    ManifestHit,
    RebuiltIndex,
    SearchHit,
    SearchIndexState,
    TagFilter,
    highlights,
    search_terms,
)


class SearchTable(Protocol):
    """The rows the BM25 index is built on: PostgreSQL's ``retrieval_search``, kept by its adapter.

    ``build_next`` fills ``retrieval_search_next`` beside it; ``swap`` replaces the table with it.
    """

    async def index(self, chunk_set: ChunkSet) -> None:
        """Add the rows of a stored chunk set that has none yet.

        Args:
            chunk_set: A stored chunk set.
        """
        ...

    async def state(self) -> SearchIndexState:
        """Return the format the rows were written in, and the one this build writes.

        Returns:
            Both formats.
        """
        ...

    async def build_next(self) -> None:
        """Fill ``retrieval_search_next`` with the rows of every stored chunk."""
        ...

    async def swap(self) -> RebuiltIndex:
        """Add what was stored meanwhile, then replace ``retrieval_search`` in one transaction.

        Returns:
            The format written and the number of rows.
        """
        ...


def _statements(template: str) -> dict[object, Any]:
    """Return the statement of each tag condition, with the manifests bound as a list.

    Args:
        template: The SQL, with ``{match}``, ``{query}`` and ``{tags}`` slots.

    Returns:
        One statement per ``POSTGRES_TAG_CONDITIONS`` key.
    """
    return {
        match: text(template.format(match=_PG_SEARCH_MATCH, query=_PG_QUERY, tags=sql)).bindparams(
            bindparam("manifests", expanding=True)
        )
        for match, sql in POSTGRES_TAG_CONDITIONS.items()
    }


_searches, _counts = _statements(_PG_SEARCH_BM25), _statements(_PG_COUNT_BM25)


@dataclass(frozen=True, slots=True, kw_only=True)
class PgSearchIndex:
    """Implements ``ports.driven.SearchIndex`` and ``SearchIndexMaintenance`` with `pg_search`.

    Every term of a query is an alternative (OR), scored with BM25 over the global statistics of
    the stored chunks. Snippets come from ``ts_headline``, as PostgreSQL full-text search's do.
    """

    engine: AsyncEngine
    """The PostgreSQL database."""
    table: SearchTable
    """Writes, rebuilds and versions the rows the BM25 index is built on."""

    async def prepare(self, *, create: bool) -> str | None:
        """Make sure the BM25 index exists, or say why `pg_search` cannot answer here.

        Processes that start together take turns (an advisory lock), so the index is made once.
        Making it reads every row: a first start on a large index takes a while.

        Args:
            create: Make the index when it is missing (``False``: a read-only process).

        Returns:
            ``None`` when the index answers, else why not (a sentence for the operator).
        """
        async with self.engine.begin() as connection:
            found = (
                await connection.execute(text(_PG_EXTENSION), {"extension": PG_SEARCH_EXTENSION})
            ).one()
            if not found.installed:
                return (
                    f"the {PG_SEARCH_EXTENSION} extension is available but not installed in this "
                    f"database (CREATE EXTENSION {PG_SEARCH_EXTENSION} CASCADE adds it)"
                    if found.available
                    else f"this PostgreSQL server has no {PG_SEARCH_EXTENSION} extension"
                )
            if await connection.scalar(text(_PG_BM25_EXISTS)):
                return None
            if not create:
                return "the BM25 index is missing and this process may not create it"
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _PG_BM25_LOCK}
            )
            if not await connection.scalar(text(_PG_BM25_EXISTS)):
                await connection.exec_driver_sql(_PG_BM25_INDEX)
        return None

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index the chunks of this set that have no row yet (the BM25 index follows its table).

        Args:
            chunk_set: A stored chunk set.
        """
        await self.table.index(chunk_set)

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Return the manifest's best matches; the manifest's rows decide what is visible.

        Args:
            manifest_id: The manifest searched.
            query: What the caller typed.
            tag_filter: Tags the chunks must have.
            limit: How many hits at most.

        Returns:
            The hits, best first.
        """
        found = await self.search_many([manifest_id], query, tag_filter, limit)
        return [f.hit for f in found]

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Return the best matches of any of the manifests, in one query.

        Args:
            manifest_ids: The manifests searched.
            query: What the caller typed.
            tag_filter: Tags the chunks must have.
            limit: How many hits at most, over all manifests.

        Returns:
            The hits with their manifests, best first.
        """
        terms = search_terms(query)
        if not terms or not manifest_ids:
            return []
        params = self._params(terms, manifest_ids, tag_filter) | {
            "headline": POSTGRES_HEADLINE,
            "words": POSTGRES_SNIPPET_WORDS,
            "limit": limit,
        }
        statement = _searches[tag_filter.match if tag_filter.tags else None]
        async with self.engine.connect() as connection:
            found = (await connection.execute(statement, params)).all()
        return [
            ManifestHit(
                manifest_id=row.manifest_id,
                hit=SearchHit(
                    chunk_id=ChunkId(row.chunk_id),
                    score=row.score,
                    snippet=row.snippet,
                    highlights=highlights(row.snippet, terms),
                ),
            )
            for row in found
        ]

    async def count_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Return the number of matching chunks per manifest, in one query.

        Args:
            manifest_ids: The manifests searched.
            query: What the caller typed.
            tag_filter: Tags the chunks must have.

        Returns:
            Matches per manifest; a manifest without any is left out.
        """
        terms = search_terms(query)
        if not terms or not manifest_ids:
            return {}
        statement = _counts[tag_filter.match if tag_filter.tags else None]
        async with self.engine.connect() as connection:
            found = await connection.execute(
                statement, self._params(terms, manifest_ids, tag_filter)
            )
            return {row.manifest_id: row.matches for row in found}

    async def state(self) -> SearchIndexState:
        """Return the table's formats, answered by `pg_search`.

        Returns:
            Both formats and this engine.
        """
        return replace(await self.table.state(), engine=PG_SEARCH_ENGINE)

    async def rebuild(self) -> RebuiltIndex:
        """Rebuild the table beside the one that answers, index it with BM25, then swap it in.

        Returns:
            The format written and the number of rows.
        """
        await self.table.build_next()
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql(_PG_BM25_INDEX_NEXT)
        rebuilt = await self.table.swap()
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql(_PG_BM25_RENAME)
        return rebuilt

    @staticmethod
    def _params(
        terms: Sequence[str], manifest_ids: Sequence[str], tag_filter: TagFilter
    ) -> dict[str, object]:
        """Return the parameters every search and count binds.

        Args:
            terms: The query's search terms.
            manifest_ids: The manifests searched.
            tag_filter: Tags the chunks must have.

        Returns:
            The parameters.
        """
        params: dict[str, object] = {
            "terms": list(terms),
            "wanted": " ".join(terms),
            "whole": " ".join(t for t in terms if _PG_WHOLE_IDENTIFIER.search(t)),
            "manifests": list(manifest_ids),
        }
        if tag_filter.tags:
            params["tags"] = json.dumps(list(tag_filter.tags))
        return params
