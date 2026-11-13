import json
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.retrieval.constants import (
    _COUNT,
    _CREATE_NEXT,
    _CREATE_NEXT_TRIGGER,
    _CREATE_TRIGGER,
    _SEARCH,
    FORMAT,
    HEADING_WEIGHT,
    IDENTIFIERS_WEIGHT,
    PATH_WEIGHT,
    REBUILD_BATCH,
    TAG_CONDITIONS,
    TEXT_WEIGHT,
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

# The FTS5 table `retrieval_search` (and the trigger that empties it with `retrieval_chunks`) is
# created by an Alembic revision in `exactdocs.bootstrap`. Its rowid is `retrieval_chunks.id`,
# the explicit INTEGER PRIMARY KEY, so one entry exists per stored chunk, not per manifest, and
# neither VACUUM nor a table rebuild can detach an entry from its chunk. The tokenizer keeps
# `-_.` inside a token (see `identifier_tokens`). Columns: heading, path, text, identifiers.
# Column weights: see `HEADING_WEIGHT` and the others in `exactdocs.retrieval.constants`.


_chunks_after = text(
    "SELECT id, heading_path, content FROM retrieval_chunks WHERE id > :after "
    "ORDER BY id LIMIT :limit"
)
_not_in_next = text(
    """
    SELECT c.id, c.heading_path, c.content FROM retrieval_chunks c
    WHERE NOT EXISTS (SELECT 1 FROM retrieval_search_next s WHERE s.rowid = c.id)
    """
)
_insert_next = text(
    "INSERT INTO retrieval_search_next (rowid, heading, path, text, identifiers) "
    "VALUES (:rowid, :heading, :path, :text, :identifiers)"
)

_missing = text(
    """
    SELECT c.id, c.position FROM retrieval_chunks c
    WHERE c.blob_sha = :blob AND c.config_hash = :config
      AND NOT EXISTS (SELECT 1 FROM retrieval_search s WHERE s.rowid = c.id)
    """
)
_insert = text(
    "INSERT INTO retrieval_search (rowid, heading, path, text, identifiers) "
    "VALUES (:rowid, :heading, :path, :text, :identifiers)"
)


def _statements(template: str) -> dict[object, Any]:
    """Prepare one statement per tag-match condition from an SQL template.

    Args:
        template: The SQL, with ``{tags}`` where the tag condition goes.

    Returns:
        The statements by tag match (``None``: no tag filter), ``manifests`` expanding.
    """
    return {
        match: text(template.format(tags=sql)).bindparams(bindparam("manifests", expanding=True))
        for match, sql in TAG_CONDITIONS.items()
    }


_searches, _counts = _statements(_SEARCH), _statements(_COUNT)


def fts_row(rowid: int, heading_path: Sequence[str], content: str) -> dict[str, object]:
    """Return the values of one `retrieval_search` row (migrations freeze their own copy).

    Args:
        rowid: The chunk's row ID in ``retrieval_chunks``.
        heading_path: The chunk's heading path.
        content: The chunk's text.

    Returns:
        The row's column values, by name.
    """
    full = " / ".join(heading_path)
    return {
        "rowid": rowid,
        "heading": heading_path[-1] if heading_path else "",
        "path": " / ".join(heading_path[:-1]),
        "text": content,
        "identifiers": identifier_tokens(f"{full}\n{content}"),
    }


def _rows(chunks: Sequence[Any]) -> list[dict[str, object]]:
    """Turn ``retrieval_chunks`` rows into ``retrieval_search`` rows.

    Args:
        chunks: The chunk rows.

    Returns:
        The values of each index row.
    """
    return [fts_row(c.id, json.loads(c.heading_path), c.content) for c in chunks]


def _match(query: str) -> str | None:
    """FTS5 query: every word as a quoted string, OR-ed; ``None`` when there is no word.

    Words only hold letters, digits, marks and ``-_.``, so they are quoted for good measure and
    nothing a user typed can reach FTS5's query syntax (`NEAR`, `*`, `"`, `(`, `col:`).

    Args:
        query: The query text.

    Returns:
        The FTS5 query, or ``None``.
    """
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in search_terms(query)) or None


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteSearchIndex:
    """Implements ``ports.driven.SearchIndex`` with SQLite FTS5 and its ``bm25()`` ranking.

    BM25 statistics are global over the stored chunks (content is deduplicated across versions).
    The index keeps its own copy of the text, which costs disk but lets ``snippet()`` work.
    """

    engine: AsyncEngine
    """The application database."""
    rebuild_batch: int = REBUILD_BATCH
    """Chunks indexed per write transaction while a rebuild fills the new index."""

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index the chunks of this set that have no entry yet.

        One write transaction per set (about 3 ms): thousands of new sets take seconds. Batch
        them behind this method if import time ever shows it.

        Args:
            chunk_set: The stored chunk set.
        """
        async with self.engine.execution_options(begin_immediate=True).begin() as connection:
            missing = await connection.execute(
                _missing, {"blob": chunk_set.blob_sha, "config": chunk_set.config_hash}
            )
            rows = [
                fts_row(
                    rowid,
                    chunk_set.chunks[position].heading_path,
                    chunk_set.chunks[position].content,
                )
                for rowid, position in missing
            ]
            if rows:
                await connection.execute(_insert, rows)

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Return the manifest's best matches; the manifest's rows decide what is visible.

        Args:
            manifest_id: The manifest searched.
            query: The query text.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first.
        """
        found = await self.search_many([manifest_id], query, tag_filter, limit)
        return [f.hit for f in found]

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Return the best matches of any of the manifests: one query, one global BM25 scale.

        Args:
            manifest_ids: The manifests searched.
            query: The query text.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first, each naming its manifest.
        """
        match = _match(query)
        if match is None or not manifest_ids:
            return []
        params = self._params(match, manifest_ids, tag_filter) | {
            "heading_weight": HEADING_WEIGHT,
            "path_weight": PATH_WEIGHT,
            "text_weight": TEXT_WEIGHT,
            "identifiers_weight": IDENTIFIERS_WEIGHT,
            "limit": limit,
        }
        statement = _searches[tag_filter.match if tag_filter.tags else None]
        async with self.engine.connect() as connection:
            found = (await connection.execute(statement, params)).all()
        terms = search_terms(query)
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
            query: The query text.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many chunks match, by manifest ID.
        """
        match = _match(query)
        if match is None or not manifest_ids:
            return {}
        statement = _counts[tag_filter.match if tag_filter.tags else None]
        async with self.engine.connect() as connection:
            found = await connection.execute(
                statement, self._params(match, manifest_ids, tag_filter)
            )
            return {row.manifest_id: row.matches for row in found}

    async def state(self) -> SearchIndexState:
        """Return the format recorded with the index and the one this build writes.

        Returns:
            The stored and current formats and the engine.
        """
        async with self.engine.connect() as connection:
            stored = await connection.scalar(text("SELECT format FROM retrieval_search_format"))
        return SearchIndexState(
            stored_format=stored, current_format=FORMAT, engine=SearchEngine.FTS5
        )

    async def rebuild(self) -> RebuiltIndex:
        """Build ``retrieval_search_next`` of every stored chunk, then swap it in (`swap`).

        Returns:
            The new index's format and how many chunks it holds.
        """
        await self.build_next()
        return await self.swap()

    async def build_next(self) -> None:
        """Fill a new index beside the one that answers, ``REBUILD_BATCH`` chunks per transaction.

        Searches and imports go on meanwhile: each batch holds the write lock for milliseconds,
        and readers never wait in WAL mode. A rebuild that died left its table: it starts over.
        """
        async with self._writing() as connection:
            await connection.exec_driver_sql(
                "DROP TRIGGER IF EXISTS retrieval_chunks_search_next_delete"
            )
            await connection.exec_driver_sql("DROP TABLE IF EXISTS retrieval_search_next")
            await connection.exec_driver_sql(_CREATE_NEXT)
            await connection.exec_driver_sql(_CREATE_NEXT_TRIGGER)
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
        async with self._writing() as connection:  # merge the b-trees: faster searches after
            await connection.exec_driver_sql(
                "INSERT INTO retrieval_search_next(retrieval_search_next) VALUES ('optimize')"
            )

    async def swap(self) -> RebuiltIndex:
        """Add what was indexed since `build_next` began, then replace the index in one step.

        One write transaction: a search sees the old index or the new one, never a mix.

        Returns:
            The format the index is now in and how many chunks it holds.
        """
        async with self._writing() as connection:
            missing = (await connection.execute(_not_in_next)).all()
            if missing:
                await connection.execute(_insert_next, _rows(missing))
            for statement in (
                "DROP TRIGGER retrieval_chunks_search_next_delete",
                "DROP TRIGGER retrieval_chunks_search_delete",
                "DROP TABLE retrieval_search",
                "ALTER TABLE retrieval_search_next RENAME TO retrieval_search",
                _CREATE_TRIGGER,
            ):
                await connection.exec_driver_sql(statement)
            await connection.execute(
                text(
                    "INSERT INTO retrieval_search_format (id, format) VALUES (1, :format) "
                    "ON CONFLICT (id) DO UPDATE SET format = excluded.format"
                ),
                {"format": FORMAT},
            )
            entries = await connection.scalar(text("SELECT count(*) FROM retrieval_search"))
        return RebuiltIndex(format=FORMAT, entries=entries or 0)

    def _writing(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Begin a write transaction with BEGIN IMMEDIATE, so it never fails to upgrade a lock.

        Returns:
            The transaction's connection, as a context manager.
        """
        return self.engine.execution_options(begin_immediate=True).begin()

    @staticmethod
    def _params(
        match: str, manifest_ids: Sequence[str], tag_filter: TagFilter
    ) -> dict[str, object]:
        """Bind the parameters of a search or count statement.

        Args:
            match: The FTS5 query.
            manifest_ids: The manifests searched.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            The parameters, with ``tags`` as JSON when the filter has tags.
        """
        params: dict[str, object] = {"match": match, "manifests": list(manifest_ids)}
        if tag_filter.tags:
            params["tags"] = json.dumps(list(tag_filter.tags))
        return params
