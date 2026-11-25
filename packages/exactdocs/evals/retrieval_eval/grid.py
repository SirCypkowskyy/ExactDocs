"""The retrieval grid (#494): chunking, context and embedding variants against plain baselines.

A grid file (``golden/matrix.yaml``) declares cells. An **app** cell is a configuration of the
retrieval benchmark (#347), run by ExactDocs itself and scored by chunk ID. Every other cell is
**eval-only**: this module cuts the pinned versions' raw Markdown itself (fixed token windows
with overlap, or ExactDocs' heading chunker), optionally puts the article title and heading path
in front of the text it embeds or indexes, searches it in process (BM25 in an in-memory SQLite
FTS5 table with ExactDocs' columns, weights and tokenizer; cosine over an embedding model's
vectors; or both fused by RRF), may widen each hit to its parent section at read time, and is
scored from its text with the text scorer (#491), as a keyword-grep baseline is. Nothing here
changes what ExactDocs ships. See docs/evals.md#the-retrieval-grid.
"""

import bisect
import math
import re
import sqlite3
import time
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.models import ChunkingConfig, ParsedArticle
from exactdocs.retrieval.adapters.driven.sqlite_fts import fts_row
from exactdocs.retrieval.constants import (
    CHARS_PER_TOKEN,
    HEADING_WEIGHT,
    IDENTIFIERS_WEIGHT,
    PATH_WEIGHT,
    RRF_DEPTH,
    TEXT_WEIGHT,
)
from exactdocs.retrieval.models import (
    ChunkId,
    question_terms,
    reciprocal_rank_fusion,
    search_terms,
)
from exactdocs.retrieval.ports.driven import Embeddings
from retrieval_eval.ingestion import Chunk
from retrieval_eval.retrieval_bench import NDCG_AT, Budget, IndexCost
from retrieval_eval.text_bench import TextAnswer
from retrieval_eval.text_match import SECTION_CHUNKING

GRID_FILE: Final[Path] = Path(__file__).parents[1] / "golden" / "matrix.yaml"
"""The grid the full run measures."""
GREP_CONTEXT: Final[int] = 3
"""Lines kept around a matching line, as ``rg -C 3`` prints them."""
RAW: Final[str] = "raw"
"""The chunking name of the grep baseline: the files as they are."""
_FTS_TABLE: Final[str] = (
    "CREATE VIRTUAL TABLE passages USING fts5(heading, path, text, identifiers, "
    "project UNINDEXED, version UNINDEXED, tokenize=\"unicode61 tokenchars '-_.'\")"
)
"""ExactDocs' FTS5 columns and tokenizer (``LIBSQL_SEARCH_TABLES``), plus the project and version
each passage is filtered by."""
_FTS_SEARCH: Final[str] = (
    "SELECT rowid FROM passages WHERE passages MATCH ? AND project = ? AND version = ? "
    "ORDER BY bm25(passages, ?, ?, ?, ?), rowid LIMIT ?"
)
"""Ranks one version's passages as ExactDocs' SQLite index does (column weights included)."""
_FTS_INSERT: Final[str] = (
    "INSERT INTO passages (rowid, heading, path, text, identifiers, project, version) "
    "VALUES (:rowid, :heading, :path, :text, :identifiers, :project, :version)"
)
"""Adds one passage."""

type Search = Literal["bm25", "dense", "hybrid", "grep"]
"""How an eval-only cell finds passages."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class Cell(_Model):
    """One cell of the grid: an app configuration, or an eval-only variant or baseline."""

    name: str = ""
    """Its name in the report (an app cell's is ``<configuration>@<chunking>`` when left out)."""
    app: str | None = None
    """A retrieval-benchmark configuration (``bm25``, ``hybrid:bge-base-en-v1.5+ce``): ExactDocs
    runs it and it is scored by chunk ID."""
    chunking: str = "default"
    """The heading chunking (a configuration of the ingestion benchmark) of an app cell, or of an
    eval-only cell without ``window``."""
    window: int | None = None
    """Eval-only: cut each article into windows of about this many estimated tokens instead."""
    overlap: int = 0
    """Eval-only: estimated tokens a window shares with the one before."""
    search: Search | None = None
    """Eval-only: how passages are found; ``grep`` searches the raw files."""
    embedding: str | None = None
    """Eval-only: the embedding model of ``dense`` and ``hybrid`` (a local model's name)."""
    prefix_embedded: bool = False
    """Eval-only: put the article title and heading path in front of the text embedded."""
    prefix_indexed: bool = False
    """Eval-only: put the article title and heading path in front of the text indexed for BM25."""
    expand: Literal["parent"] | None = None
    """Eval-only: return each hit's parent section, with its subsections, instead of the hit."""

    @model_validator(mode="after")
    def _complete(self) -> Self:
        """Check the cell is one thing, fully described, and name it.

        Returns:
            The cell, named.

        Raises:
            ValueError: An app cell with eval-only settings, or an eval-only cell without what
                its search needs.
        """
        if (self.app is None) == (self.search is None):
            message = f"cell {self.name!r}: give either app or search"
            raise ValueError(message)
        eval_only = (self.window, self.embedding, self.expand)
        if self.app is not None and (any(v is not None for v in eval_only) or self.prefixed):
            message = f"cell {self.name!r}: an app cell takes only app and chunking"
            raise ValueError(message)
        if self.search in {"dense", "hybrid"} and self.embedding is None:
            message = f"cell {self.name!r}: {self.search} needs an embedding model"
            raise ValueError(message)
        if self.window is not None and not 0 <= self.overlap < self.window:
            message = f"cell {self.name!r}: the overlap must be under the window"
            raise ValueError(message)
        if not self.name:
            message = "an eval-only cell needs a name"
            raise ValueError(message)
        return self

    @model_validator(mode="before")
    @classmethod
    def _named(cls, data: object) -> object:
        """Name an app cell ``<configuration>@<chunking>`` when the file gives no name.

        Args:
            data: The cell as the file has it.

        Returns:
            The same, named.
        """
        if isinstance(data, dict) and not data.get("name") and data.get("app"):
            return {**data, "name": f"{data['app']}@{data.get('chunking', 'default')}"}
        return data

    @property
    def prefixed(self) -> bool:
        """Whether a title and heading path go in front of any text."""
        return self.prefix_embedded or self.prefix_indexed

    @property
    def chunker(self) -> str:
        """The name of how the cell cuts: a heading chunking, ``window-<n>+<overlap>``, ``raw``."""
        if self.search == "grep":
            return RAW
        if self.window is not None:
            return f"window-{self.window}+{self.overlap}"
        return self.chunking

    @property
    def budget(self) -> Budget:
        """What an eval-only cell needs: an embedding model is local (hosted ones are app cells)."""
        return Budget.NONE if self.embedding is None else Budget.LOCAL


class Grid(_Model):
    """A grid file: the cells and the default each budget is tested against."""

    defaults: dict[Budget, str]
    """The cell each budget's results are tested against: what ExactDocs ships for it."""
    cells: list[Cell]
    """The cells, in the order they run."""

    @model_validator(mode="after")
    def _known(self) -> Self:
        """Check names are unique and every default is a cell.

        Returns:
            The grid.

        Raises:
            ValueError: A name repeats or a default names no cell.
        """
        names = [c.name for c in self.cells]
        if repeated := sorted({n for n in names if names.count(n) > 1}):
            message = f"cells named twice: {', '.join(repeated)}"
            raise ValueError(message)
        if unknown := sorted(set(self.defaults.values()) - set(names)):
            message = f"defaults that name no cell: {', '.join(unknown)}"
            raise ValueError(message)
        return self


def load_grid(path: Path = GRID_FILE) -> Grid:
    """Read a grid file.

    Args:
        path: The YAML file.

    Returns:
        The grid.
    """
    return Grid.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------- passages


@dataclass(frozen=True, slots=True, kw_only=True)
class Passage:
    """One piece of an article an eval-only cell indexes, and what it returns for it."""

    project: str
    version: str
    """The pinned version it is of: the hard filter."""
    article: str
    """The article's repository path."""
    title: str
    """The article's title."""
    chunk: Chunk
    """Its text, heading path (where it starts) and the headings it holds."""
    shown: str
    """What a search returns for it: its text, or its parent section (``expand``)."""

    @property
    def context(self) -> str:
        """The title and heading path put in front of a prefixed text, H1 = title not repeated."""
        path = self.chunk.heading_path
        if path and path[0] == self.title:
            path = path[1:]
        return " > ".join((self.title, *path))

    def text(self, *, prefixed: bool) -> str:
        """The text embedded or indexed.

        Args:
            prefixed: Put the title and heading path in front.

        Returns:
            The chunk's text, maybe prefixed.
        """
        return f"{self.context}\n\n{self.chunk.content}" if prefixed else self.chunk.content


@dataclass(frozen=True, slots=True, kw_only=True)
class _Span:
    """A range of an article's body and the heading path where it starts."""

    start: int
    end: int
    heading_path: tuple[str, ...]


def _sections(article: ParsedArticle) -> list[_Span]:
    """Cut a body at every heading, as the golden set names sections (``SECTION_CHUNKING``).

    Args:
        article: The parsed article.

    Returns:
        Its sections in order; they cover the body.
    """
    spans, at = [], 0
    for chunk in MarkdownChunker(SECTION_CHUNKING).chunk(article):
        spans.append(_Span(start=at, end=at + len(chunk.content), heading_path=chunk.heading_path))
        at += len(chunk.content)
    return spans


def _heading_spans(article: ParsedArticle, config: ChunkingConfig) -> list[tuple[int, int]]:
    """Cut a body with ExactDocs' heading chunker.

    Args:
        article: The parsed article.
        config: The chunking.

    Returns:
        Each chunk's ``[start, end)``; the chunks cover the body.
    """
    spans, at = [], 0
    for chunk in MarkdownChunker(config).chunk(article):
        spans.append((at, at + len(chunk.content)))
        at += len(chunk.content)
    return spans


def window_spans(body: str, tokens: int, overlap: int) -> list[tuple[int, int]]:
    """Cut a body into windows of whole lines, about ``tokens`` estimated tokens each.

    A window takes lines until it holds ``tokens * CHARS_PER_TOKEN`` characters (at least one
    line); the next starts at the latest line that keeps at most ``overlap`` tokens' worth of
    the window before it. Windows ignore headings, code blocks and tables: that is the variant.

    Args:
        body: The article's body.
        tokens: The window's size, in estimated tokens.
        overlap: The tokens two windows share, at most.

    Returns:
        Each window's ``[start, end)``.
    """
    ends = [m.end() for m in re.finditer(r"[^\n]*\n|[^\n]+$", body)]
    starts = [0, *ends[:-1]]
    size, shared = tokens * CHARS_PER_TOKEN, overlap * CHARS_PER_TOKEN
    windows: list[tuple[int, int]] = []
    first = 0
    while first < len(ends):
        last = first
        while last + 1 < len(ends) and ends[last] - starts[first] < size:
            last += 1
        windows.append((starts[first], ends[last]))
        if last + 1 == len(ends):
            break
        following = last + 1
        while following - 1 > first and ends[last] - starts[following - 1] <= shared:
            following -= 1
        first = following
    return windows


def _subtree_end(sections: Sequence[_Span], index: int) -> int:
    """Find where a section ends with every section nested in it.

    Args:
        sections: The article's sections.
        index: The section's index.

    Returns:
        The end offset.
    """
    path = sections[index].heading_path
    end = sections[index].end
    for later in sections[index + 1 :]:
        if (
            not path
            or len(later.heading_path) <= len(path)
            or later.heading_path[: len(path)] != path
        ):
            break
        end = later.end
    return end


def _parent(
    sections: Sequence[_Span], start: int, heading_path: tuple[str, ...]
) -> tuple[int, int]:
    """Find the parent section of the passage starting at ``start``, with its subsections.

    A passage under a top-level heading (or under none) widens to its own section.

    Args:
        sections: The article's sections.
        start: The passage's start.
        heading_path: Its heading path.

    Returns:
        The parent's ``[start, end)``.
    """
    wanted = heading_path[:-1] if len(heading_path) > 1 else heading_path
    at = bisect.bisect_right([s.start for s in sections], start) - 1
    index = next((i for i in range(at, -1, -1) if sections[i].heading_path == wanted), max(at, 0))
    return sections[index].start, _subtree_end(sections, index)


def passages_of(
    cell: Cell, project: str, version: str, article: ParsedArticle, chunking: ChunkingConfig
) -> list[Passage]:
    """Cut one article as an eval-only cell does.

    Args:
        cell: The cell (``window``, ``overlap``, ``expand``).
        project: The project.
        version: The pinned version.
        article: The parsed article.
        chunking: The heading chunking, when the cell has no window.

    Returns:
        Its passages, in order.
    """
    body = article.body
    sections = _sections(article)
    if not sections:
        return []
    spans = (
        window_spans(body, cell.window, cell.overlap)
        if cell.window is not None
        else _heading_spans(article, chunking)
    )
    starts = [s.start for s in sections]
    found = []
    for start, end in spans:
        at = max(bisect.bisect_right(starts, start) - 1, 0)
        held = tuple(s.heading_path for s in sections if s.heading_path and start <= s.start < end)
        path = sections[at].heading_path
        shown = body[start:end]
        if cell.expand == "parent":
            low, high = _parent(sections, start, path)
            shown = body[low:high]
        found.append(
            Passage(
                project=project,
                version=version,
                article=article.path,
                title=article.title,
                chunk=Chunk(heading_path=path, content=body[start:end], headings=held),
                shown=shown,
            )
        )
    return found


# ---------------------------------------------------------------- search


@dataclass(frozen=True, slots=True, kw_only=True)
class Found:
    """What one search returned, and what it cost."""

    passages: list[int]
    """The passages, best first (indexes into the index's passages)."""
    tokens: int = 0
    """Model tokens of the query embedding."""


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    """Scale a vector to length 1, so a dot product is the cosine.

    Args:
        vector: The vector.

    Returns:
        The unit vector (zeros stay zeros).
    """
    norm = math.sqrt(math.sumprod(vector, vector)) or 1.0
    return tuple(x / norm for x in vector)


@dataclass(frozen=True, slots=True, kw_only=True)
class PassageIndex:
    """An eval-only cell's passages, indexed for its search, with what indexing cost."""

    cell: Cell
    passages: tuple[Passage, ...]
    by_version: Mapping[tuple[str, str], tuple[int, ...]]
    """The passages of each ``(project, version)``."""
    database: sqlite3.Connection | None
    """The FTS5 table of ``bm25`` and ``hybrid``; closed by ``close``."""
    vectors: tuple[tuple[float, ...], ...]
    """Unit vectors of the passages (``dense`` and ``hybrid``)."""
    embeddings: Embeddings | None
    """The model that embeds the queries."""
    cost: IndexCost
    """What cutting, indexing and embedding the corpus took."""

    @classmethod
    async def build(
        cls, cell: Cell, passages: Sequence[Passage], embeddings: Embeddings | None
    ) -> Self:
        """Index the passages for the cell's search.

        Args:
            cell: The cell.
            passages: Every passage of the corpus.
            embeddings: The cell's embedding model (``dense``, ``hybrid``).

        Returns:
            The index.
        """
        started = time.perf_counter()
        by_version: dict[tuple[str, str], list[int]] = {}
        for i, p in enumerate(passages):
            by_version.setdefault((p.project, p.version), []).append(i)
        database = None
        if cell.search in {"bm25", "hybrid"}:
            database = sqlite3.connect(":memory:")
            database.execute(_FTS_TABLE)
            database.executemany(
                _FTS_INSERT,
                [
                    {
                        **fts_row(i, p.chunk.heading_path, p.text(prefixed=cell.prefix_indexed)),
                        "project": p.project,
                        "version": p.version,
                    }
                    for i, p in enumerate(passages)
                ],
            )
        vectors: tuple[tuple[float, ...], ...] = ()
        tokens = 0
        if cell.search in {"dense", "hybrid"} and embeddings is not None:
            embedded = await embeddings.embed_documents(
                [p.text(prefixed=cell.prefix_embedded) for p in passages]
            )
            vectors = tuple(_unit(v) for v in embedded.vectors)
            tokens = embedded.input_tokens
        return cls(
            cell=cell,
            passages=tuple(passages),
            by_version={k: tuple(v) for k, v in by_version.items()},
            database=database,
            vectors=vectors,
            embeddings=embeddings,
            cost=IndexCost(seconds=round(time.perf_counter() - started, 1), tokens=tokens, usd=0.0),
        )

    def close(self) -> None:
        """Close the FTS5 table."""
        if self.database is not None:
            self.database.close()

    def _bm25(self, project: str, version: str, query: str, limit: int) -> list[int]:
        """Rank one version's passages by BM25.

        Args:
            project: The project.
            version: The version.
            query: The question.
            limit: The most passages.

        Returns:
            Passage indexes, best first.
        """
        terms = search_terms(query)
        if self.database is None or not terms:
            return []
        match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        weights = (HEADING_WEIGHT, PATH_WEIGHT, TEXT_WEIGHT, IDENTIFIERS_WEIGHT)
        with closing(self.database.cursor()) as cursor:
            rows = cursor.execute(_FTS_SEARCH, (match, project, version, *weights, limit))
            return [row[0] for row in rows]

    async def _dense(
        self, project: str, version: str, query: str, limit: int
    ) -> tuple[list[int], int]:
        """Rank one version's passages by cosine to the query.

        Args:
            project: The project.
            version: The version.
            query: The question.
            limit: The most passages.

        Returns:
            Passage indexes, nearest first, and the query's tokens.
        """
        if self.embeddings is None or not self.vectors:
            return [], 0
        embedded = await self.embeddings.embed_query(query)
        q = _unit(embedded.vectors[0])
        held = self.by_version.get((project, version), ())
        ranked = sorted(held, key=lambda i: (-math.sumprod(q, self.vectors[i]), i))
        return ranked[:limit], embedded.input_tokens

    async def search(self, project: str, version: str, query: str) -> Found:
        """Answer a question from one version's passages.

        Args:
            project: The project.
            version: The version asked: nothing of another is searched.
            query: The question.

        Returns:
            The top passages (``NDCG_AT``), widened passages that repeat dropped.
        """
        tokens = 0
        match self.cell.search:
            case "bm25":
                ranked = self._bm25(project, version, query, RRF_DEPTH)
            case "dense":
                ranked, tokens = await self._dense(project, version, query, RRF_DEPTH)
            case _:
                dense, tokens = await self._dense(project, version, query, RRF_DEPTH)
                fused = reciprocal_rank_fusion(
                    [ChunkId(str(i)) for i in self._bm25(project, version, query, RRF_DEPTH)],
                    [ChunkId(str(i)) for i in dense],
                )
                ranked = [int(f.chunk_id) for f in fused]
        shown: dict[str, int] = {}
        for i in ranked:
            shown.setdefault(self.passages[i].shown, i)
        return Found(passages=list(shown.values())[:NDCG_AT], tokens=tokens)

    async def answer(self, project: str, version: str, query: str) -> TextAnswer:
        """Answer a question as text, timed.

        Args:
            project: The project.
            version: The version.
            query: The question.

        Returns:
            The text of each result, best first.
        """
        started = time.perf_counter()
        found = await self.search(project, version, query)
        return TextAnswer(
            texts=[self.passages[i].shown for i in found.passages],
            search_ms=round((time.perf_counter() - started) * 1000, 3),
            tokens=found.tokens,
        )


# ---------------------------------------------------------------- grep baseline


def grep_terms(query: str) -> list[str]:
    """The words a keyword grep looks for: the question's content terms.

    Args:
        query: The question.

    Returns:
        Its terms without stop words (``question_terms``), numbers as written.
    """
    return list(dict.fromkeys(t.removeprefix("#") for t in question_terms(query) if t))


def grep(articles: Mapping[str, str], query: str, context: int = GREP_CONTEXT) -> list[str]:
    """Search raw files as ``rg -i -w -C <context>`` would, best snippets first.

    Every line holding a term as a whole word matches; each match keeps ``context`` lines on
    either side, and overlapping ones merge into one snippet. Snippets are ranked by the distinct
    terms they hold, then by their matching lines, then by path and position.

    Args:
        articles: Each file's text, by path.
        query: The question.
        context: Lines kept around a match.

    Returns:
        The top snippets (``NDCG_AT``).
    """
    terms = grep_terms(query)
    if not terms:
        return []
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(t) for t in terms) + r")(?!\w)", re.IGNORECASE
    )
    snippets: list[tuple[int, int, str, int, str]] = []
    for path, text in sorted(articles.items()):
        lines = text.splitlines(keepends=True)
        hits = [i for i, line in enumerate(lines) if pattern.search(line)]
        groups: list[list[int]] = []
        for i in hits:
            if groups and i - groups[-1][-1] <= 2 * context + 1:
                groups[-1].append(i)
            else:
                groups.append([i])
        for group in groups:
            low, high = max(group[0] - context, 0), group[-1] + context + 1
            body = "".join(lines[low:high])
            held = {
                m.lower() for line in lines[group[0] : group[-1] + 1] for m in pattern.findall(line)
            }
            snippets.append((-len(held), -len(group), path, low, body))
    snippets.sort()
    return [s[4] for s in snippets[:NDCG_AT]]
