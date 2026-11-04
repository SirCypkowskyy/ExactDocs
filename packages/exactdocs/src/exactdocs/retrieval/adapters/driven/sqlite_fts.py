import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.retrieval.models import ChunkId, ChunkSet, SearchHit, identifier_tokens, search_terms

# The FTS5 table `retrieval_search` (and the trigger that empties it with `retrieval_chunks`) is
# created by an Alembic revision in `exactdocs.bootstrap`. Its rowid is the rowid of the chunk's
# row in `retrieval_chunks`, so one entry exists per stored chunk, not per manifest. The tokenizer
# keeps `-_.` inside a token (see `identifier_tokens`). Columns: heading, text, identifiers.
HEADING_WEIGHT = 10.0
OPEN, CLOSE = (
    "\x02",
    "\x03",
)  # highlight markers; stripped from indexed text so they are unambiguous

_MISSING = text(
    """
    SELECT c.rowid, c.position FROM retrieval_chunks c
    WHERE c.blob_sha = :blob AND c.config_hash = :config
      AND NOT EXISTS (SELECT 1 FROM retrieval_search s WHERE s.rowid = c.rowid)
    """
)
_INSERT = text(
    "INSERT INTO retrieval_search (rowid, heading, text, identifiers) "
    "VALUES (:rowid, :heading, :text, :identifiers)"
)
_SEARCH = """
    SELECT mc.chunk_id AS chunk_id,
           -bm25(retrieval_search, :heading_weight, 1.0, 1.0) AS score,
           snippet(retrieval_search, 1, :open, :close, '…', 24) AS snippet
    FROM retrieval_search
    JOIN retrieval_chunks c ON c.rowid = retrieval_search.rowid
    JOIN retrieval_manifest_chunks mc
      ON mc.blob_sha = c.blob_sha AND mc.config_hash = c.config_hash AND mc.position = c.position
    WHERE retrieval_search MATCH :match AND mc.manifest_id = :manifest {tags}
    ORDER BY score DESC, mc.chunk_id
    LIMIT :limit
"""
_TAGS = (
    "AND EXISTS (SELECT 1 FROM json_each(mc.tags)"
    " WHERE value IN (SELECT value FROM json_each(:tags)))"
)


def _match(query: str) -> str | None:
    """FTS5 query: every word as a quoted string, OR-ed; ``None`` when there is no word.

    Words only hold letters, digits, marks and ``-_.``, so they are quoted for good measure and
    nothing a user typed can reach FTS5's query syntax (`NEAR`, `*`, `"`, `(`, `col:`).
    """
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in search_terms(query)) or None


def _highlights(marked: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Split FTS5's marked snippet into plain text and ``[start, end)`` offsets."""
    plain: list[str] = []
    spans: list[tuple[int, int]] = []
    start = 0
    for char in marked:
        if char == OPEN:
            start = len(plain)
        elif char == CLOSE:
            spans.append((start, len(plain)))
        else:
            plain.append(char)
    return "".join(plain), tuple(spans)


@dataclass(frozen=True, slots=True)
class SqliteSearchIndex:
    """Implements ``ports.driven.SearchIndex`` with SQLite FTS5 and its ``bm25()`` ranking.

    BM25 statistics are global over the stored chunks (content is deduplicated across versions).
    The index keeps its own copy of the text, which costs disk but lets ``snippet()`` work.
    """

    engine: AsyncEngine

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index the chunks of this set that have no entry yet."""
        strip = str.maketrans("", "", OPEN + CLOSE)
        async with self.engine.execution_options(begin_immediate=True).begin() as connection:
            missing = await connection.execute(
                _MISSING, {"blob": chunk_set.blob_sha, "config": chunk_set.config_hash}
            )
            rows = []
            for rowid, position in missing:
                chunk = chunk_set.chunks[position]
                heading = " / ".join(chunk.heading_path).translate(strip)
                body = chunk.content.translate(strip)
                rows.append(
                    {
                        "rowid": rowid,
                        "heading": heading,
                        "text": body,
                        "identifiers": identifier_tokens(f"{heading}\n{body}"),
                    }
                )
            if rows:
                await connection.execute(_INSERT, rows)

    async def search(
        self, manifest_id: str, query: str, tag_filter: Collection[str], limit: int
    ) -> Sequence[SearchHit]:
        """Return the manifest's best matches; the manifest's rows decide what is visible."""
        match = _match(query)
        if match is None:
            return []
        statement = text(_SEARCH.format(tags=_TAGS if tag_filter else ""))
        params: dict[str, object] = {
            "heading_weight": HEADING_WEIGHT,
            "open": OPEN,
            "close": CLOSE,
            "match": match,
            "manifest": manifest_id,
            "limit": limit,
        }
        if tag_filter:
            params["tags"] = json.dumps(list(tag_filter))
        async with self.engine.connect() as connection:
            found = (await connection.execute(statement, params)).all()
        hits = []
        for row in found:
            snippet, spans = _highlights(row.snippet)
            hits.append(
                SearchHit(
                    chunk_id=ChunkId(row.chunk_id),
                    score=row.score,
                    snippet=snippet,
                    highlights=spans,
                )
            )
        return hits
