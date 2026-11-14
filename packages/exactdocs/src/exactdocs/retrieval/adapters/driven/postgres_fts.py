"""The search index on PostgreSQL: its built-in full-text search, ranked with ``ts_rank_cd``.

`retrieval_search` (revision 0c4e8a2f6b19 in `exactdocs.bootstrap`) holds one row per stored
chunk, keyed by `retrieval_chunks.id` with a cascading foreign key, and the same four columns as
FTS5: the section's own heading, its ancestors, its text and `identifier_tokens` of them. PostgreSQL
computes `document` from them (the `simple` configuration, labels A to D). It is not BM25: ranking
follows the same column weights but may order close matches differently from SQLite. Where the
database has ParadeDB's `pg_search`, its BM25 (`pg_search.py`) answers over these same rows, and
this adapter still writes and rebuilds them (bootstrap chooses the engine at start).
"""

import json
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.retrieval.constants import (
    _PG_COUNT,
    _PG_CREATE_NEXT,
    _PG_INDEX_NEXT,
    _PG_QUERY,
    _PG_SEARCH,
    _PG_SWAP,
    POSTGRES_FORMAT,
    POSTGRES_HEADLINE,
    POSTGRES_SNIPPET_WORDS,
    POSTGRES_TAG_CONDITIONS,
    POSTGRES_WEIGHTS,
    REBUILD_BATCH,
)
from exactdocs.retrieval.models import (
    ChunkId,
    ChunkSet,
    ManifestHit,
    RebuiltIndex,
    SearchEngine,
    SearchHit,
    SearchIndexState,
    TagFilter,
    highlights,
    identifier_tokens,
    search_terms,
)

_missing = text(
    """
    SELECT c.id, c.position FROM retrieval_chunks c
    WHERE c.blob_sha = :blob AND c.config_hash = :config
      AND NOT EXISTS (SELECT 1 FROM retrieval_search s WHERE s.chunk_id = c.id)
    """
)
_insert = text(
    "INSERT INTO retrieval_search (chunk_id, heading, path, body, identifiers) "
    "VALUES (:chunk_id, :heading, :path, :body, :identifiers)"
)
_chunks_after = text(
    "SELECT id, heading_path, content FROM retrieval_chunks WHERE id > :after "
    "ORDER BY id LIMIT :limit"
)
_not_in_next = text(
    """
    SELECT c.id, c.heading_path, c.content FROM retrieval_chunks c
    WHERE NOT EXISTS (SELECT 1 FROM retrieval_search_next s WHERE s.chunk_id = c.id)
    """
)
_insert_next = text(
    "INSERT INTO retrieval_search_next (chunk_id, heading, path, body, identifiers) "
    "VALUES (:chunk_id, :heading, :path, :body, :identifiers)"
)


def _statements(template: str) -> dict[object, Any]:
    """Return the statement of each tag condition, with the manifests bound as a list.

    Args:
        template: The SQL, with a ``{tags}`` slot.

    Returns:
        One statement per ``POSTGRES_TAG_CONDITIONS`` key.
    """
    return {
        match: text(template.format(query=_PG_QUERY, tags=sql)).bindparams(
            bindparam("manifests", expanding=True)
        )
        for match, sql in POSTGRES_TAG_CONDITIONS.items()
    }


_searches, _counts = _statements(_PG_SEARCH), _statements(_PG_COUNT)


def search_row(chunk_id: int, heading_path: Sequence[str], content: str) -> dict[str, object]:
    """Return the values of one `retrieval_search` row (what FTS5's ``fts_row`` holds).

    Args:
        chunk_id: The chunk's `retrieval_chunks.id`.
        heading_path: The headings above the chunk, outermost first.
        content: The chunk's text.

    Returns:
        The row's columns, ``document`` excepted (PostgreSQL computes it).
    """
    full = " / ".join(heading_path)
    return {
        "chunk_id": chunk_id,
        "heading": heading_path[-1] if heading_path else "",
        "path": " / ".join(heading_path[:-1]),
        "body": content,
        "identifiers": identifier_tokens(f"{full}\n{content}"),
    }


def _rows(chunks: Sequence[Any]) -> list[dict[str, object]]:
    """Return the rows of stored chunks (``id``, ``heading_path`` JSON, ``content``).

    Args:
        chunks: Rows of `retrieval_chunks`.

    Returns:
        Their `retrieval_search` rows.
    """
    return [search_row(c.id, json.loads(c.heading_path), c.content) for c in chunks]


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresSearchIndex:
    """Implements ``ports.driven.SearchIndex`` with PostgreSQL full-text search.

    Every term of a query is an alternative (OR), ranked with ``ts_rank_cd`` over FTS5's column
    weights; snippets come from ``ts_headline``. The index keeps its own copy of the text.
    """

    engine: AsyncEngine
    """The PostgreSQL database."""
    rebuild_batch: int = REBUILD_BATCH
    """Chunks per transaction while ``exactdocs reindex`` fills the new index."""
    write_settings: tuple[str, ...] = ()
    """``SET LOCAL`` statements run before indexing a chunk set: with `pg_search` answering, its
    ``PG_SEARCH_QUIET_SCANS``, so the anti-join over the indexed table logs no warning."""

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index the chunks of this set that have no row yet.

        Args:
            chunk_set: A stored chunk set.
        """
        async with self._writing() as connection:
            for statement in self.write_settings:
                await connection.exec_driver_sql(statement)
            missing = await connection.execute(
                _missing, {"blob": chunk_set.blob_sha, "config": chunk_set.config_hash}
            )
            rows = [
                search_row(
                    chunk_id,
                    chunk_set.chunks[position].heading_path,
                    chunk_set.chunks[position].content,
                )
                for chunk_id, position in missing
            ]
            if rows:
                await connection.execute(_insert, rows)

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
            "weights": list(POSTGRES_WEIGHTS),
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
        """Return the format recorded with the index and the one this build writes.

        Returns:
            Both formats.
        """
        async with self.engine.connect() as connection:
            stored = await connection.scalar(text("SELECT format FROM retrieval_search_format"))
        return SearchIndexState(
            stored_format=stored, current_format=POSTGRES_FORMAT, engine=SearchEngine.POSTGRES_FTS
        )

    async def rebuild(self) -> RebuiltIndex:
        """Build ``retrieval_search_next`` of every stored chunk, then swap it in.

        Returns:
            The format written and the number of rows.
        """
        await self.build_next()
        return await self.swap()

    async def build_next(self) -> None:
        """Fill a new index beside the one that answers, ``rebuild_batch`` chunks at a time.

        Searches and imports go on meanwhile. A rebuild that died left its table: it starts over.
        """
        async with self._writing() as connection:
            await connection.exec_driver_sql("DROP TABLE IF EXISTS retrieval_search_next")
            await connection.exec_driver_sql(_PG_CREATE_NEXT)
        after = 0
        while True:
            async with self._writing() as connection:
                batch = (
                    await connection.execute(
                        _chunks_after, {"after": after, "limit": self.rebuild_batch}
                    )
                ).all()
                if not batch:
                    break
                await connection.execute(_insert_next, _rows(batch))
            after = batch[-1].id
        async with self._writing() as connection:
            await connection.exec_driver_sql(_PG_INDEX_NEXT)

    async def swap(self) -> RebuiltIndex:
        """Add what was indexed since ``build_next`` began, then replace the index in one step.

        One transaction: a search sees the old index or the new one, never a mix.

        Returns:
            The format written and the number of rows.
        """
        async with self._writing() as connection:
            missing = (await connection.execute(_not_in_next)).all()
            if missing:
                await connection.execute(_insert_next, _rows(missing))
            for statement in _PG_SWAP:
                await connection.exec_driver_sql(statement)
            await connection.execute(
                text(
                    "INSERT INTO retrieval_search_format (id, format) VALUES (1, :format) "
                    "ON CONFLICT (id) DO UPDATE SET format = excluded.format"
                ),
                {"format": POSTGRES_FORMAT},
            )
            entries = await connection.scalar(text("SELECT count(*) FROM retrieval_search"))
        return RebuiltIndex(format=POSTGRES_FORMAT, entries=entries or 0)

    def _writing(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Return a transaction that takes turns with the other writers (``begin_immediate``).

        Returns:
            The transaction's connection, as a context manager.
        """
        return self.engine.execution_options(begin_immediate=True).begin()

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
        params: dict[str, object] = {"terms": list(terms), "manifests": list(manifest_ids)}
        if tag_filter.tags:
            params["tags"] = json.dumps(list(tag_filter.tags))
        return params
