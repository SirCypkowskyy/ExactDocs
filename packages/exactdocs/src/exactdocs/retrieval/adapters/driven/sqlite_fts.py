import json
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.retrieval.models import (
    ChunkId,
    ChunkSet,
    SearchHit,
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
# `-_.` inside a token (see `identifier_tokens`). Columns: heading, text, identifiers.
# FTS5 adds the weighted term counts of all columns *before* BM25 saturates them, so a repeated
# word in the body can drown a heading hit. The identifiers column repeats every word (and adds
# its parts), so it only gets a small weight: it makes camelCase and snake_case parts findable
# without counting twice.
HEADING_WEIGHT, TEXT_WEIGHT, IDENTIFIERS_WEIGHT = 20.0, 1.0, 0.1

_MISSING = text(
    """
    SELECT c.id, c.position FROM retrieval_chunks c
    WHERE c.blob_sha = :blob AND c.config_hash = :config
      AND NOT EXISTS (SELECT 1 FROM retrieval_search s WHERE s.rowid = c.id)
    """
)
_INSERT = text(
    "INSERT INTO retrieval_search (rowid, heading, text, identifiers) "
    "VALUES (:rowid, :heading, :text, :identifiers)"
)
# Rank first and cut to LIMIT, then build snippets for the survivors only.
_SEARCH = """
    WITH ranked AS (
        SELECT c.id AS id, mc.chunk_id AS chunk_id,
               -bm25(retrieval_search, :heading_weight, :text_weight, :identifiers_weight) AS score
        FROM retrieval_search
        JOIN retrieval_chunks c ON c.id = retrieval_search.rowid
        JOIN retrieval_manifest_chunks mc
          ON mc.blob_sha = c.blob_sha AND mc.config_hash = c.config_hash
         AND mc.position = c.position
        WHERE retrieval_search MATCH :match AND mc.manifest_id = :manifest {tags}
        ORDER BY score DESC, mc.chunk_id
        LIMIT :limit
    )
    SELECT r.chunk_id, r.score, snippet(retrieval_search, 1, '', '', '', 24) AS snippet
    FROM ranked r
    JOIN retrieval_search ON retrieval_search.rowid = r.id
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
_SEARCHES = {match: text(_SEARCH.format(tags=sql)) for match, sql in _TAG_CONDITIONS.items()}


def fts_row(rowid: int, heading_path: Sequence[str], content: str) -> dict[str, object]:
    """Return the values of one `retrieval_search` row; the migration backfills with it too."""
    heading = " / ".join(heading_path)
    return {
        "rowid": rowid,
        "heading": heading,
        "text": content,
        "identifiers": identifier_tokens(f"{heading}\n{content}"),
    }


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
        match = _match(query)
        if match is None:
            return []
        params: dict[str, object] = {
            "heading_weight": HEADING_WEIGHT,
            "text_weight": TEXT_WEIGHT,
            "identifiers_weight": IDENTIFIERS_WEIGHT,
            "match": match,
            "manifest": manifest_id,
            "limit": limit,
        }
        if tag_filter.tags:
            params["tags"] = json.dumps(list(tag_filter.tags))
        statement = _SEARCHES[tag_filter.match if tag_filter.tags else None]
        async with self.engine.connect() as connection:
            found = (await connection.execute(statement, params)).all()
        terms = search_terms(query)
        return [
            SearchHit(
                chunk_id=ChunkId(row.chunk_id),
                score=row.score,
                snippet=row.snippet,
                highlights=highlights(row.snippet, terms),
            )
            for row in found
        ]
