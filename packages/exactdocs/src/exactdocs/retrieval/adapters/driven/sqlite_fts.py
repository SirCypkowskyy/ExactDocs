import json
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.retrieval.models import (
    ChunkId,
    ChunkSet,
    ManifestHit,
    RebuiltIndex,
    SearchHit,
    SearchIndexState,
    TagFilter,
    TagMatch,
    highlights,
    identifier_tokens,
    search_terms,
)

# The FTS5 table `retrieval_search` (and the trigger that empties it with `retrieval_chunks`) is
# created by an Alembic revision in `exactdocs.bootstrap`. Its rowid is `retrieval_chunks.id`,
# the explicit INTEGER PRIMARY KEY, so one entry exists per stored chunk, not per manifest, and
# neither VACUUM nor a table rebuild can detach an entry from its chunk. The tokenizer keeps
# `-_.` inside a token (see `identifier_tokens`). Columns: heading, path, text, identifiers.
# FTS5 adds the weighted term counts of all columns *before* BM25 saturates them, so a repeated
# word in the body can drown a heading hit. The identifiers column repeats every word (and adds
# its parts), so it only gets a small weight: it makes camelCase and snake_case parts findable
# without counting twice.
# `heading` is the section's own heading and `path` its ancestors: a section that *defines* a term
# outranks the sub-sections that merely sit under a heading naming it (ranking suite: `docker`
# finds "Docker", not "Docker > Troubleshooting"), yet "docker troubleshooting" still finds the
# latter because the path still counts.
HEADING_WEIGHT, PATH_WEIGHT, TEXT_WEIGHT, IDENTIFIERS_WEIGHT = 20.0, 4.0, 1.0, 0.1

# The format this build writes, stored in `retrieval_search_format` by every rebuild. Bump it when
# what an entry holds changes but the table keeps its columns (`fts_row`, `identifier_tokens`, the
# tokenizer): old entries keep answering, built the old way, until `exactdocs reindex`, and the
# release notes say "requires reindex" (docs/releasing.md). A change of columns needs an Alembic
# revision that rebuilds the table instead (as a91c4e7b3d02 did), since these queries name them.
FORMAT = 2
REBUILD_BATCH = 500  # chunks per write transaction while the new index is built

# `exactdocs reindex` builds `retrieval_search_next` beside `retrieval_search`, then renames it over
# it. Same definition as the Alembic revisions' (columns, tokenizer). While it is built, a trigger
# deletes from it the chunks deleted meanwhile, so a reused chunk id never keeps the old text.
_CREATE_NEXT = """
    CREATE VIRTUAL TABLE retrieval_search_next USING fts5(
        heading, path, text, identifiers,
        tokenize = "unicode61 tokenchars '-_.'"
    )
"""
_CREATE_NEXT_TRIGGER = """
    CREATE TRIGGER retrieval_chunks_search_next_delete AFTER DELETE ON retrieval_chunks
    BEGIN
        DELETE FROM retrieval_search_next WHERE rowid = old.id;
    END
"""
_CREATE_TRIGGER = """
    CREATE TRIGGER retrieval_chunks_search_delete AFTER DELETE ON retrieval_chunks
    BEGIN
        DELETE FROM retrieval_search WHERE rowid = old.id;
    END
"""
_CHUNKS_AFTER = text(
    "SELECT id, heading_path, content FROM retrieval_chunks WHERE id > :after "
    "ORDER BY id LIMIT :limit"
)
_NOT_IN_NEXT = text(
    """
    SELECT c.id, c.heading_path, c.content FROM retrieval_chunks c
    WHERE NOT EXISTS (SELECT 1 FROM retrieval_search_next s WHERE s.rowid = c.id)
    """
)
_INSERT_NEXT = text(
    "INSERT INTO retrieval_search_next (rowid, heading, path, text, identifiers) "
    "VALUES (:rowid, :heading, :path, :text, :identifiers)"
)

_MISSING = text(
    """
    SELECT c.id, c.position FROM retrieval_chunks c
    WHERE c.blob_sha = :blob AND c.config_hash = :config
      AND NOT EXISTS (SELECT 1 FROM retrieval_search s WHERE s.rowid = c.id)
    """
)
_INSERT = text(
    "INSERT INTO retrieval_search (rowid, heading, path, text, identifiers) "
    "VALUES (:rowid, :heading, :path, :text, :identifiers)"
)
# Rank first and cut to LIMIT, then build snippets for the survivors only. MATERIALIZED and CROSS
# JOIN pin that order: left to itself the planner can scan the FTS table on the outside and re-run
# the ranking for every match (seconds instead of milliseconds).
_SEARCH = """
    WITH ranked AS MATERIALIZED (
        SELECT c.id AS id, mc.manifest_id AS manifest_id, mc.chunk_id AS chunk_id,
               -bm25(retrieval_search, :heading_weight, :path_weight, :text_weight,
                     :identifiers_weight) AS score
        FROM retrieval_search
        JOIN retrieval_chunks c ON c.id = retrieval_search.rowid
        JOIN retrieval_manifest_chunks mc
          ON mc.blob_sha = c.blob_sha AND mc.config_hash = c.config_hash
         AND mc.position = c.position
        WHERE retrieval_search MATCH :match AND mc.manifest_id IN :manifests {tags}
        ORDER BY score DESC, mc.chunk_id
        LIMIT :limit
    )
    SELECT r.manifest_id, r.chunk_id, r.score,
           snippet(retrieval_search, 2, '', '', '', 24) AS snippet
    FROM ranked r
    CROSS JOIN retrieval_search ON retrieval_search.rowid = r.id
    WHERE retrieval_search MATCH :match
    ORDER BY r.score DESC, r.chunk_id
"""
# The tag condition sits in WHERE, so it is applied before ORDER BY ... LIMIT.
_TAG_CONDITIONS = {
    None: "",
    TagMatch.ANY: (
        "AND EXISTS (SELECT 1 FROM json_each(mc.tags)"
        " WHERE value IN (SELECT value FROM json_each(:tags)))"
    ),
    TagMatch.ALL: (
        "AND NOT EXISTS (SELECT 1 FROM json_each(:tags) wanted"
        " WHERE wanted.value NOT IN (SELECT value FROM json_each(mc.tags)))"
    ),
}
_COUNT = """
    SELECT mc.manifest_id AS manifest_id, count(*) AS matches
    FROM retrieval_search
    JOIN retrieval_chunks c ON c.id = retrieval_search.rowid
    JOIN retrieval_manifest_chunks mc
      ON mc.blob_sha = c.blob_sha AND mc.config_hash = c.config_hash
     AND mc.position = c.position
    WHERE retrieval_search MATCH :match AND mc.manifest_id IN :manifests {tags}
    GROUP BY mc.manifest_id
"""


def _statements(template: str) -> dict[object, Any]:
    return {
        match: text(template.format(tags=sql)).bindparams(bindparam("manifests", expanding=True))
        for match, sql in _TAG_CONDITIONS.items()
    }


_SEARCHES, _COUNTS = _statements(_SEARCH), _statements(_COUNT)


def fts_row(rowid: int, heading_path: Sequence[str], content: str) -> dict[str, object]:
    """Return the values of one `retrieval_search` row (migrations freeze their own copy)."""
    full = " / ".join(heading_path)
    return {
        "rowid": rowid,
        "heading": heading_path[-1] if heading_path else "",
        "path": " / ".join(heading_path[:-1]),
        "text": content,
        "identifiers": identifier_tokens(f"{full}\n{content}"),
    }


def _rows(chunks: Sequence[Any]) -> list[dict[str, object]]:
    return [fts_row(c.id, json.loads(c.heading_path), c.content) for c in chunks]


def _match(query: str) -> str | None:
    """FTS5 query: every word as a quoted string, OR-ed; ``None`` when there is no word.

    Words only hold letters, digits, marks and ``-_.``, so they are quoted for good measure and
    nothing a user typed can reach FTS5's query syntax (`NEAR`, `*`, `"`, `(`, `col:`).
    """
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in search_terms(query)) or None


@dataclass(frozen=True, slots=True)
class SqliteSearchIndex:
    """Implements ``ports.driven.SearchIndex`` with SQLite FTS5 and its ``bm25()`` ranking.

    BM25 statistics are global over the stored chunks (content is deduplicated across versions).
    The index keeps its own copy of the text, which costs disk but lets ``snippet()`` work.
    """

    engine: AsyncEngine
    rebuild_batch: int = REBUILD_BATCH

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index the chunks of this set that have no entry yet.

        One write transaction per set (about 3 ms): thousands of new sets take seconds. Batch
        them behind this method if import time ever shows it.
        """
        async with self.engine.execution_options(begin_immediate=True).begin() as connection:
            missing = await connection.execute(
                _MISSING, {"blob": chunk_set.blob_sha, "config": chunk_set.config_hash}
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
                await connection.execute(_INSERT, rows)

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Return the manifest's best matches; the manifest's rows decide what is visible."""
        found = await self.search_many([manifest_id], query, tag_filter, limit)
        return [f.hit for f in found]

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Return the best matches of any of the manifests: one query, one global BM25 scale."""
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
        statement = _SEARCHES[tag_filter.match if tag_filter.tags else None]
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
        """Return the number of matching chunks per manifest, in one query."""
        match = _match(query)
        if match is None or not manifest_ids:
            return {}
        statement = _COUNTS[tag_filter.match if tag_filter.tags else None]
        async with self.engine.connect() as connection:
            found = await connection.execute(
                statement, self._params(match, manifest_ids, tag_filter)
            )
            return {row.manifest_id: row.matches for row in found}

    async def state(self) -> SearchIndexState:
        """Return the format recorded with the index and the one this build writes."""
        async with self.engine.connect() as connection:
            stored = await connection.scalar(text("SELECT format FROM retrieval_search_format"))
        return SearchIndexState(stored_format=stored, current_format=FORMAT)

    async def rebuild(self) -> RebuiltIndex:
        """Build ``retrieval_search_next`` of every stored chunk, then swap it in (`swap`)."""
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
                        _CHUNKS_AFTER, {"after": after, "limit": self.rebuild_batch}
                    )
                ).all()
                if not batch:
                    break
                await connection.execute(_INSERT_NEXT, _rows(batch))
            after = batch[-1].id
        async with self._writing() as connection:  # merge the b-trees: faster searches after
            await connection.exec_driver_sql(
                "INSERT INTO retrieval_search_next(retrieval_search_next) VALUES ('optimize')"
            )

    async def swap(self) -> RebuiltIndex:
        """Add what was indexed since `build_next` began, then replace the index in one step.

        One write transaction: a search sees the old index or the new one, never a mix.
        """
        async with self._writing() as connection:
            missing = (await connection.execute(_NOT_IN_NEXT)).all()
            if missing:
                await connection.execute(_INSERT_NEXT, _rows(missing))
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
        return self.engine.execution_options(begin_immediate=True).begin()

    @staticmethod
    def _params(
        match: str, manifest_ids: Sequence[str], tag_filter: TagFilter
    ) -> dict[str, object]:
        params: dict[str, object] = {"match": match, "manifests": list(manifest_ids)}
        if tag_filter.tags:
            params["tags"] = json.dumps(list(tag_filter.tags))
        return params
