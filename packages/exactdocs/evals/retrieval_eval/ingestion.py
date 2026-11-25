"""The ingestion benchmark's metrics (#346): what the importer made of the articles, model-free.

Every metric reads the chunks the importer stored next to the source they were cut from, and
judges the cut with its own small line reader (fences, tables, lists, headings), not with the
importer's parser: a block structure the parser gets wrong (an MDX fence it pairs differently)
then shows as a disagreement instead of agreeing with itself. See docs/evals/ingestion.md
 for each definition.
"""

import itertools
import math
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict

from exactdocs.retrieval.constants import CHARS_PER_TOKEN

MIN_USEFUL_TOKENS: Final[int] = 50
"""A chunk under this many estimated tokens (about 200 characters, a heading and a sentence or
two) is too small to answer anything on its own."""
EXAMPLES: Final[int] = 10
"""How many examples a list of offenders keeps (the missing sections are all kept)."""
_DIGITS: Final[int] = 4
"""Shares are rounded to this many decimals."""
_FENCE: Final[re.Pattern[str]] = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
"""A fence line: up to three spaces, then three or more backticks or tildes."""
_ATX: Final[re.Pattern[str]] = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)")
"""An ATX heading line; group 1 gives its level."""
_SETEXT: Final[re.Pattern[str]] = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
"""A setext underline (``===`` for H1, ``---`` for H2) under a paragraph line."""
_TABLE_ROW: Final[re.Pattern[str]] = re.compile(r"^\s*\|.*\|\s*$")
"""A pipe-table row."""
_LIST_ITEM: Final[re.Pattern[str]] = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])[ \t]+\S")
"""A bullet or ordered list item."""
_MKDOCS_BLOCK: Final[re.Pattern[str]] = re.compile(r"^ {0,3}(?:!!!|\?\?\?\+?|===)[ \t]")
"""The first line of a MkDocs admonition (``!!!``, ``???``) or content tab (``===``)."""
_INCLUDE: Final[re.Pattern[str]] = re.compile(r"\{!.+?!\}|^-{2}8<-{2}", re.MULTILINE)
"""An include directive the docs build expands (``{!file!}``, ``--8<--``) and Markdown does not."""
_HEADING_MARKUP: Final[re.Pattern[str]] = re.compile(
    r"\{#[^}]*\}"  # attribute list: {#id}
    r"|\[#[^\]]*\]"  # anchor: [#id]
    # a link left as text: [text][ref], [text][], [text](url); not a signature's `a[, b][, c]`
    r"|\[[^\],][^\]]*\]\[(?:[^\],\s][^\]]*)?\]|\]\("
    r"|\{/\*|\{!"  # MDX comment, include directive
)
"""Markup that must not survive in a heading path's plain text."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Chunk:
    """One stored chunk, as the benchmark reads it."""

    heading_path: tuple[str, ...]
    """Its heading path; empty for the text before the first heading."""
    content: str
    """Its Markdown, verbatim."""
    headings: tuple[tuple[str, ...], ...] = ()
    """The heading path of every heading it holds, the one it starts with included."""
    chunk_id: str = ""
    """Its ID in the version's manifest (empty when not read from one)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Article:
    """One selected file of a version: its source and the chunks the importer stored for it."""

    key: str
    """Names it in a report: ``<project> <version>:<path>``."""
    source: str | None
    """The article's body (front matter left out) as the repository has it; ``None``: unreadable."""
    chunks: tuple[Chunk, ...]
    """Its chunks in order; empty when the importer stored none."""


type Section = tuple[str, tuple[str, ...]]
"""An expected section: the article's key and the heading path."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class IngestionMetrics(_Model):
    """The ingestion metrics of a set of articles (one version, or a whole corpus)."""

    articles: int
    """Selected files at the pinned commit."""
    articles_without_chunks: int
    """Of those, files the importer stored no chunk for."""
    articles_without_h1: int
    """Readable, non-empty files whose body has no level-1 heading (the line reader's count)."""
    chunks: int
    """Chunks stored."""
    expected_sections: int
    """Distinct sections the golden set expects."""
    covered_sections: int
    """Of those, sections that start at least one chunk: a chunk's heading path is theirs."""
    held_sections: int
    """Sections that start a chunk or are a heading inside one (merged into a bigger chunk)."""
    coverage: float
    """``covered_sections / expected_sections``; 1 when nothing is expected."""
    missing_sections: list[str]
    """Every expected section that starts no chunk, ``<key> [A > B]``; ``(held)`` when merged."""
    cuts_in_code_fence: int
    """Chunks that end inside a fenced code block, by the line reader (the next chunk goes on
    with the block)."""
    cuts_in_table: int
    """Chunks whose last line and the next chunk's first line are rows of one table."""
    cuts_in_list: int
    """Chunks whose last line and the next chunk's first line belong to one list."""
    source_chars: int
    """Non-whitespace characters of the readable sources."""
    lost_chars: int
    """Of those, characters that appear in no chunk (chunks are matched in order, verbatim)."""
    tokens_p50: int
    """Median chunk size, in estimated tokens (``CHARS_PER_TOKEN`` characters each)."""
    tokens_p95: int
    """95th percentile chunk size, in estimated tokens."""
    tokens_max: int
    """The largest chunk, in estimated tokens."""
    small_chunks: int
    """Chunks under ``MIN_USEFUL_TOKENS``."""
    small_share: float
    """``small_chunks / chunks``."""
    multi_top_chunks: int
    """Chunks holding more than one top-level heading (heading path of length 1)."""
    multi_top_share: float
    """``multi_top_chunks / chunks``."""
    empty_heading_paths: int
    """Chunks with an empty heading path (text before the first heading, or no heading at all)."""
    wrong_heading_paths: int
    """Chunks whose heading path holds an empty heading or markup that should not survive
    (``{#id}``, ``[#id]``, ``[text][ref]``, ``[text](url)``, ``{/*``, ``{!``)."""
    wrong_heading_examples: list[str]
    """Up to ``EXAMPLES`` such heading paths."""
    source_headings: int
    """Headings the line reader finds outside fenced code in the readable sources."""
    headings_missed: int
    """Per article, how many fewer headings the chunks record than the line reader finds
    (headings swallowed into code, a paragraph or an HTML block), summed."""
    headings_extra: int
    """Per article, how many more headings the chunks record than the line reader finds (lines
    of code read as headings), summed."""
    unexpanded_includes: int
    """Chunks holding an include directive the docs build expands (``{!...!}``, ``--8<--``)."""
    mkdocs_blocks_as_code: int
    """MkDocs admonitions and content tabs whose 4-space-indented body Markdown reads as an
    indented code block."""
    examples: dict[str, list[str]]
    """Up to ``EXAMPLES`` article keys per article-level metric: ``articles_without_chunks``,
    ``headings_missed``, ``headings_extra``, ``cuts_in_code_fence``, ``lost_chars``,
    ``unexpanded_includes``, ``mkdocs_blocks_as_code``."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- a line reader
class _Reader:
    """Reads Markdown line by line, keeping whether it is inside a fenced code block."""

    fence: str = ""
    """The open fence's marker (e.g. three backticks); empty outside a fence."""

    def feed(self, line: str) -> bool:
        """Take one line.

        Args:
            line: The line, without its newline.

        Returns:
            True when the line is outside fenced code (fence lines themselves are inside).
        """
        found = _FENCE.match(line)
        if self.fence:
            marker = found.group(1) if found else ""
            closes = marker[:1] == self.fence[0] and len(marker) >= len(self.fence)
            if found and closes and not found.group(2).strip():
                self.fence = ""
            return False
        if found and not (found.group(1)[0] == "`" and "`" in found.group(2)):
            self.fence = found.group(1)
            return False
        return True


def source_headings(source: str) -> list[int]:
    """Find the headings of a Markdown text with the line reader, outside fenced code.

    ATX headings (``#`` to ``######``) and setext headings (a ``===`` or ``---`` underline below a
    paragraph line) count; nothing inside a fence does. HTML blocks, MDX and indented code are
    not understood: that is the point, the importer's parser is checked against it.

    Args:
        source: The text.

    Returns:
        The level of each heading, in order.
    """
    reader = _Reader()
    levels = []
    previous = ""
    for line in source.splitlines():
        outside = reader.feed(line)
        if not outside:
            previous = ""
            continue
        if found := _ATX.match(line):
            levels.append(len(found.group(1)))
            previous = ""
            continue
        if (
            (found := _SETEXT.match(line))
            and previous.strip()
            and not _LIST_ITEM.match(previous)
            and not _TABLE_ROW.match(previous)
        ):
            levels.append(1 if found.group(1)[0] == "=" else 2)
            previous = ""
            continue
        previous = line
    return levels


def tokens(text: str) -> int:
    """Estimate a text's tokens as retrieval does: ``CHARS_PER_TOKEN`` characters each.

    Args:
        text: The text.

    Returns:
        The estimate, rounded up.
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def percentile(values: Sequence[int], share: float) -> int:
    """Nearest-rank percentile.

    Args:
        values: The values.
        share: The percentile as a share (0.95).

    Returns:
        The value, or 0 for no values.
    """
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)] if ordered else 0


def _last_line(text: str) -> str:
    """The text's last line; empty when it ends with a blank line.

    Returns:
        The line.
    """
    lines = text.split("\n")
    if lines and not lines[-1]:
        lines.pop()  # the newline that ends the last line
    return lines[-1] if lines else ""


def _first_line(text: str) -> str:
    """The text's first line.

    Returns:
        The line.
    """
    return text.split("\n", 1)[0]


def _listish(line: str) -> bool:
    """A list item, or a line indented as a list item's continuation.

    Returns:
        True for either.
    """
    return bool(line.strip()) and (bool(_LIST_ITEM.match(line)) or line.startswith("  "))


def cuts(chunks: Sequence[Chunk]) -> tuple[int, int, int]:
    """Count the cuts between chunks that fall inside a fenced code block, a table or a list.

    The chunks are read in order with one line reader, as one text: a cut is inside a fence when
    the reader is inside one after the chunk; inside a table or list when the chunk's last line
    and the next chunk's first line are both rows of a table, or both belong to a list.

    Args:
        chunks: An article's chunks, in order.

    Returns:
        ``(in code fence, in table, in list)``.
    """
    reader = _Reader()
    fence = table = listed = 0
    for chunk, after in itertools.pairwise(chunks):
        for line in chunk.content.splitlines():
            reader.feed(line)
        if reader.fence:
            fence += 1
            continue
        last, first = _last_line(chunk.content), _first_line(after.content)
        if _TABLE_ROW.match(last) and _TABLE_ROW.match(first):
            table += 1
        elif (
            _listish(last)
            and _listish(first)
            and (_LIST_ITEM.match(last) or _LIST_ITEM.match(first))
        ):
            listed += 1
    return fence, table, listed


def lost_chars(source: str, chunks: Sequence[Chunk]) -> int:
    """Count the source's non-whitespace characters that appear in no chunk.

    Each chunk is looked for verbatim in the source, after the previous one's match; a chunk not
    found covers nothing.

    Args:
        source: The article's body.
        chunks: Its chunks, in order.

    Returns:
        The characters left out.
    """
    covered = [False] * len(source)
    cursor = 0
    for chunk in chunks:
        if not chunk.content:
            continue
        at = source.find(chunk.content, cursor)
        if at < 0:
            continue
        end = at + len(chunk.content)
        covered[at:end] = [True] * (end - at)
        cursor = end
    return sum(
        1 for char, seen in zip(source, covered, strict=True) if not seen and not char.isspace()
    )


def mkdocs_blocks_as_code(text: str) -> int:
    """Count MkDocs admonitions and content tabs whose body is indented by four spaces.

    Markdown reads such a body (after the blank line that usually follows the marker, or when the
    marker is not a paragraph) as an indented code block, prose and fences included.

    Args:
        text: A chunk's Markdown.

    Returns:
        How many such blocks it holds.
    """
    lines = text.splitlines()
    found = 0
    reader = _Reader()
    for at, line in enumerate(lines):
        if not reader.feed(line) or not _MKDOCS_BLOCK.match(line):
            continue
        body = next((nxt for nxt in lines[at + 1 :] if nxt.strip()), "")
        found += body.startswith(("    ", "\t"))
    return found


def wrong_heading_path(path: Sequence[str]) -> bool:
    """Tell whether a heading path holds an empty heading or markup that should be plain text.

    Args:
        path: The heading path.

    Returns:
        True when it does.
    """
    return any(not heading.strip() or _HEADING_MARKUP.search(heading) for heading in path)


def _shown(key: str, path: Sequence[str]) -> str:
    """Show a section.

    Returns:
        ``<key> [A > B]``.
    """
    return f"{key} [{' > '.join(path)}]"


def _share(part: int, whole: int) -> float:
    """A rounded share; 0 of nothing is 0.

    Returns:
        The share.
    """
    return round(part / whole, _DIGITS) if whole else 0.0


def coverage(
    articles: Iterable[Article], expected: Iterable[Section]
) -> tuple[int, int, int, list[str]]:
    """Find which expected sections the chunks cover.

    Args:
        articles: The articles.
        expected: The expected sections.

    Returns:
        ``(expected, covered, held, missing)``: covered sections start a chunk, held ones start a
        chunk or are a heading inside one; ``missing`` names every uncovered one.
    """
    starts: set[Section] = set()
    held: set[Section] = set()
    for article in articles:
        for chunk in article.chunks:
            starts.add((article.key, chunk.heading_path))
            held.update((article.key, path) for path in (chunk.heading_path, *chunk.headings))
    wanted = sorted(set(expected))
    missing = [
        _shown(key, path) + (" (held)" if (key, path) in held else "")
        for key, path in wanted
        if (key, path) not in starts
    ]
    covered = len(wanted) - len(missing)
    return len(wanted), covered, sum(1 for s in wanted if s in held), missing


_EXAMPLED: Final[tuple[str, ...]] = (
    "articles_without_chunks",
    "headings_missed",
    "headings_extra",
    "cuts_in_code_fence",
    "lost_chars",
    "unexpanded_includes",
    "mkdocs_blocks_as_code",
)
"""The article-level counts a report keeps example articles of."""


def _article_counts(article: Article) -> Counter[str]:
    """Count what is measured per article, named as the metrics are.

    Args:
        article: The article, its source and its chunks.

    Returns:
        The counts; a zero count may be absent.
    """
    counts: Counter[str] = Counter()
    contents = [chunk.content for chunk in article.chunks]
    counts["articles_without_chunks"] = not article.chunks
    fence, table, listed = cuts(article.chunks)
    counts.update(cuts_in_code_fence=fence, cuts_in_table=table, cuts_in_list=listed)
    counts["unexpanded_includes"] = sum(1 for c in contents if _INCLUDE.search(c))
    counts["mkdocs_blocks_as_code"] = sum(mkdocs_blocks_as_code(c) for c in contents)
    if article.source is None:
        return counts
    levels = source_headings(article.source)
    recorded = sum(len(chunk.headings) for chunk in article.chunks)
    counts.update(
        articles_without_h1=bool(article.source.strip()) and 1 not in levels,
        source_headings=len(levels),
        headings_missed=max(0, len(levels) - recorded),
        headings_extra=max(0, recorded - len(levels)),
        source_chars=sum(1 for char in article.source if not char.isspace()),
        lost_chars=lost_chars(article.source, article.chunks),
    )
    return counts


def measure(articles: Sequence[Article], expected: Iterable[Section]) -> IngestionMetrics:
    """Measure the chunks of a set of articles.

    Args:
        articles: The articles, each with its source and stored chunks.
        expected: The sections the golden set expects in them.

    Returns:
        The metrics (docs/evals/ingestion.md).
    """
    chunks = [chunk for article in articles for chunk in article.chunks]
    sizes = [tokens(chunk.content) for chunk in chunks]
    totals: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for article in articles:
        counts = _article_counts(article)
        totals.update(counts)
        for metric in _EXAMPLED:
            if counts[metric] and len(kept := examples.setdefault(metric, [])) < EXAMPLES:
                kept.append(article.key)
    wanted, covered, held, missing = coverage(articles, expected)
    small = sum(1 for size in sizes if size < MIN_USEFUL_TOKENS)
    multi = sum(1 for c in chunks if sum(1 for h in c.headings if len(h) == 1) > 1)
    wrong = [c.heading_path for c in chunks if wrong_heading_path(c.heading_path)]
    return IngestionMetrics(
        articles=len(articles),
        chunks=len(chunks),
        expected_sections=wanted,
        covered_sections=covered,
        held_sections=held,
        coverage=round(covered / wanted, _DIGITS) if wanted else 1.0,
        missing_sections=missing,
        tokens_p50=percentile(sizes, 0.5),
        tokens_p95=percentile(sizes, 0.95),
        tokens_max=max(sizes, default=0),
        small_chunks=small,
        small_share=_share(small, len(chunks)),
        multi_top_chunks=multi,
        multi_top_share=_share(multi, len(chunks)),
        empty_heading_paths=sum(1 for c in chunks if not c.heading_path),
        wrong_heading_paths=len(wrong),
        wrong_heading_examples=[" > ".join(path) for path in _distinct(wrong)][:EXAMPLES],
        examples=examples,
        **{name: totals[name] for name in _COUNTED},
    )


_COUNTED: Final[tuple[str, ...]] = (
    "articles_without_chunks",
    "articles_without_h1",
    "cuts_in_code_fence",
    "cuts_in_table",
    "cuts_in_list",
    "source_chars",
    "lost_chars",
    "source_headings",
    "headings_missed",
    "headings_extra",
    "unexpanded_includes",
    "mkdocs_blocks_as_code",
)
"""The metrics that are a sum of per-article counts (``_article_counts``)."""


def _distinct[T](items: Iterable[T]) -> Iterator[T]:
    """Each item once, in order.

    Yields:
        The items, first occurrences only.
    """
    seen: set[T] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            yield item
