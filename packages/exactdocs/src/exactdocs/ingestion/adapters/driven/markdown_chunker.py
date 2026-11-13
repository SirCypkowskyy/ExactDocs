"""Heading-based chunker on markdown-it-py, which the article parser already uses.

Chonkie (named in the issue) was not used: its Markdown recipe downloads rules from the Hugging
Face Hub, and its ``MarkdownChef`` mis-detects fences inside block quotes. Chunks are cut only at
top-level headings, or between top-level blocks of a section too long for ``max_section_chars``,
so a fence, table or any other block can never be split. Nor is an MDX component or a block HTML
element that holds blank lines (``<Tabs>`` ... ``</Tabs>``): CommonMark ends an HTML block at a
blank line, so the chunker counts the open tags itself and cuts nowhere while one is open.

A link reference definition (``[x]: https://...``) is a block like any other: a cut can leave it
in another chunk than the text that uses it, as a cut at a heading always could.
"""

import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import markdown_it
from markdown_it import MarkdownIt
from markdown_it.token import Token

from exactdocs.ingestion import models
from exactdocs.ingestion.constants import DEFAULT_CHUNKER
from exactdocs.ingestion.constants._chunker import (
    _ANCHOR_DROP,
    _BLOCK_TAGS,
    _HTML_COMMENT,
    _HTML_TAG,
    _LANGUAGE,
    _LINE,
)
from exactdocs.ingestion.errors import InvalidChunkingConfigError
from exactdocs.ingestion.models import ArticleChunk, ChunkHeading, ChunkingConfig, ParsedArticle

_markdown = MarkdownIt("commonmark").enable("table")


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- grows as lines come
class _Section:
    """The lines from one top-level heading to the next (``level`` 0: before the first)."""

    level: int
    """Heading level 1-6 (``#`` to ``######``); 0 for the text before the first heading."""
    path: tuple[str, ...]
    """Every heading above it, whatever the split level."""
    anchor: str
    """GitHub-style slug of the heading; empty before the first heading."""
    start: int
    """First line."""
    end: int
    """One past the last line."""
    fences: list[tuple[int, str]] = field(default_factory=list)
    """First line and language of each fenced code block that names one, in order."""
    blocks: list[int] = field(default_factory=list)
    """First line of each top-level block in it, in order (the heading first)."""
    size: int = 0
    """Characters."""
    part: int = 0
    """Index of the part among the parts of a section split at its blocks; 0 for the first (or a
    section not split). A part after the first has no heading line."""
    split: bool = False
    """Whether this is a part of a section split at its blocks (``part`` says which)."""

    @property
    def languages(self) -> list[str]:
        """Languages of the fenced code blocks in its lines, in order, repeats included."""
        return [lang for line, lang in self.fences if self.start <= line < self.end]


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- grows as lines come
class _Piece:
    """Consecutive sections that become one chunk; named after the first."""

    sections: list[_Section]
    """The sections, in document order."""
    size: int
    """Characters."""

    @property
    def first(self) -> _Section:
        """The section the chunk is named after."""
        return self.sections[0]

    @property
    def opens_split_section(self) -> bool:
        """Whether it is the first part of a split section, which must start a chunk."""
        return self.first.split and not self.first.part

    def add(self, other: _Piece) -> None:
        """Append another piece's sections to this one.

        Args:
            other: The piece that follows this one.
        """
        self.sections.extend(other.sections)
        self.size += other.size


class MarkdownChunker:
    """The default ``Chunker`` (``markdown``): cuts at top-level headings, see ``ChunkingConfig``.

    Every top-level heading starts a section. Sections whose heading is deeper than the split
    level join the one before (their parent); a chunk longer than ``max_chars`` or
    ``max_section_chars`` is cut again at the sections it is made of; a section still longer than
    ``max_section_chars`` is split at its top-level blocks into parts as long as fit (a block
    longer than it is a part of its own); then chunks shorter than ``min_chars`` are merged with
    the next (the last with the one before) while the result stays within both bounds. The text
    before the first heading, and the first part of a split section, are never merged into the
    chunk before, so a split section's parts follow the chunk that starts it. A chunk is named
    after its first heading: a cut below the split level names the deeper heading, a merge keeps
    the first one's name, and every part of a split section keeps the section's heading path,
    anchor and occurrence index and is numbered by ``part``, so splitting a section changes no
    other section's identity. Each chunk records every heading it holds
    (``ArticleChunk.headings``), the one it is named after first; a part after the first holds
    none of its own.
    """

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        """Cut with ``config``.

        Args:
            config: The chunking settings; None for the defaults.
        """
        self._config = config or ChunkingConfig()

    @property
    def config_hash(self) -> str:
        """Hash of the config, the parser and chunker versions and the markdown-it version."""
        return models.chunking_config_hash(
            self._config, f"markdown-it-py {markdown_it.__version__}"
        )

    def configured(self, config: ChunkingConfig) -> MarkdownChunker:
        """Return a chunker that cuts with ``config``; see the ``Chunker`` port.

        Args:
            config: A library's chunking settings.

        Returns:
            A new chunker; this one is unchanged.

        Raises:
            InvalidChunkingConfigError: ``config`` names a chunker other than ``markdown``.
        """
        if config.chunker != DEFAULT_CHUNKER:
            reason = f"unsupported chunker {config.chunker!r}"
            raise InvalidChunkingConfigError(reason)
        return MarkdownChunker(config)

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        """Cut ``article`` at its headings; see the ``Chunker`` port.

        Args:
            article: The parsed article; its body is what is cut.

        Returns:
            The chunks in order; their contents add up to the body.
        """
        body = article.body
        lines = _LINE.findall(body)
        skip = 0  # broken front matter stays in the body, but is not Markdown to cut at
        if any(p.startswith("malformed front matter") for p in article.problems):
            skip = len(_LINE.findall(body[: models.malformed_front_matter_length(body)]))
        sections = _sections(_markdown.parse(body), len(lines), skip)
        offsets = list(itertools.accumulate((len(line) for line in lines), initial=0))
        for section in sections:
            section.size = offsets[section.end] - offsets[section.start]
        seen: dict[tuple[str, ...], int] = {}
        chunks = []
        blank = ""  # blank text before the first heading rides along with that heading's chunk
        for piece in self._pieces(sections, offsets):
            content = blank + "".join(lines[piece.first.start : piece.sections[-1].end])
            blank = ""
            if not content.strip():
                blank = content
                continue
            path = piece.first.path
            if piece.first.part:  # a later part of the section the last occurrence started
                occurrence = seen.get(path, 1) - 1
            else:
                occurrence = seen.get(path, 0)
                seen[path] = occurrence + 1
            languages = dict.fromkeys(lang for s in piece.sections for lang in s.languages)
            chunks.append(
                ArticleChunk(
                    heading_path=path,
                    occurrence_index=occurrence,
                    part=piece.first.part,
                    position=len(chunks),
                    content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    anchor=piece.first.anchor,
                    code_languages=tuple(languages),
                    headings=tuple(
                        ChunkHeading(
                            heading_path=s.path, anchor=s.anchor, starts_chunk=s is piece.first
                        )
                        for s in piece.sections
                        if s.level  # the text before the first heading has none
                        and not s.part  # nor a part after the first of a split section
                    ),
                )
            )
        if blank and not chunks:  # a body of whitespace only is still one (unaddressed) chunk
            chunks.append(
                ArticleChunk(
                    heading_path=(),
                    occurrence_index=0,
                    position=0,
                    content=blank,
                    content_hash=hashlib.sha256(blank.encode()).hexdigest(),
                    anchor="",
                    headings=(),
                )
            )
        return tuple(chunks)

    def _pieces(self, sections: list[_Section], offsets: list[int]) -> list[_Piece]:
        """Group the sections by split level, cut what is too long, merge what is too short.

        Args:
            sections: Every top-level section of the body, in order.
            offsets: Characters before each line of the body, and the body's length last.

        Returns:
            The pieces that become chunks, in order.
        """
        config = self._config
        limit = _bound(config.max_chars, config.max_section_chars)
        grouped: list[_Piece] = []
        for section in sections:
            if grouped and section.level > config.split_depth:
                grouped[-1].add(_Piece(sections=[section], size=section.size))
            else:
                grouped.append(_Piece(sections=[section], size=section.size))
        pieces: list[_Piece] = []
        for piece in grouped:
            if limit is None or piece.size <= limit:
                pieces.append(piece)
                continue
            cut: list[_Piece] = []
            for section in piece.sections:
                if cut and cut[-1].size + section.size <= limit:
                    cut[-1].add(_Piece(sections=[section], size=section.size))
                else:
                    cut.append(_Piece(sections=[section], size=section.size))
            pieces.extend(cut)
        ceiling = config.max_section_chars
        if ceiling is not None:  # a piece still too long is one section: split it at its blocks
            pieces = [
                part
                for piece in pieces
                for part in (
                    _parts(piece.first, ceiling, offsets) if piece.size > ceiling else [piece]
                )
            ]
        return self._merged(pieces) if config.min_chars else pieces

    def _merged(self, pieces: list[_Piece]) -> list[_Piece]:
        """Merge pieces under ``min_chars`` with the next one, the last with the one before.

        Args:
            pieces: The pieces after grouping and cutting.

        Returns:
            The pieces after merging, in order.
        """
        config = self._config
        limit = _bound(config.max_chars, config.max_section_chars)

        def fits(a: _Piece, b: _Piece) -> bool:
            """Tell whether two pieces together stay within ``max_chars`` and ``max_section_chars``.

            Args:
                a: The first piece.
                b: The piece after it.

            Returns:
                True when there is no bound or their sizes add up to at most the smaller one.
            """
            return limit is None or a.size + b.size <= limit

        merged: list[_Piece] = []
        for piece in pieces:
            last = merged[-1] if merged else None
            if (
                last is not None
                and last.first.level  # the text before the first heading stays on its own
                and not piece.opens_split_section  # its parts take its identity: keep it a chunk
                and last.size < config.min_chars
                and fits(last, piece)
            ):
                last.add(piece)
            else:
                merged.append(piece)
        if len(merged) > 1:
            tail, before = merged[-1], merged[-2]
            if (
                tail.size < config.min_chars
                and before.first.level
                and not tail.opens_split_section
                and fits(before, tail)
            ):
                before.add(merged.pop())
        return merged


def _bound(*limits: int | None) -> int | None:
    """Return the smallest of the given size bounds.

    Args:
        *limits: Bounds in characters; ``None`` is no bound.

    Returns:
        The smallest bound, or ``None`` when none is set.
    """
    return min((limit for limit in limits if limit is not None), default=None)


def _parts(section: _Section, ceiling: int, offsets: list[int]) -> list[_Piece]:
    """Split a section at its top-level blocks into the fewest parts within ``ceiling``, in order.

    Each part takes the blocks that follow while they fit; a block longer than ``ceiling`` is a
    part of its own. The blank lines after a block stay with it, and the lines before the first
    block (blank) with the first part, so every part starts with a block. A heading is never
    left alone: the first part holds it and the block after it, however long that block is.

    Args:
        section: A section longer than ``ceiling``.
        ceiling: The most characters a part may hold.
        offsets: Characters before each line of the body, and the body's length last.

    Returns:
        One piece per part, numbered from 0 (``_Section.part``).
    """
    inside = [line for line in section.blocks if section.start <= line < section.end]
    # Never before the first block (that part would be blank), nor right after the heading.
    cuts = [*inside[2 if section.level else 1 :], section.end]
    parts: list[_Piece] = []
    start = end = section.start
    for cut in cuts:
        if end > start and offsets[cut] - offsets[start] > ceiling:
            parts.append(_part(section, start, end, offsets, part=len(parts)))
            start = end
        end = cut
    parts.append(_part(section, start, end, offsets, part=len(parts)))
    return parts


def _part(section: _Section, start: int, end: int, offsets: list[int], *, part: int) -> _Piece:
    """Make the piece of one part of a split section.

    Args:
        section: The section split.
        start: The part's first line.
        end: One past its last line.
        offsets: Characters before each line of the body, and the body's length last.
        part: Its index among the section's parts (after the first, it has no heading line).

    Returns:
        The piece, named after the section.
    """
    size = offsets[end] - offsets[start]
    return _Piece(
        sections=[replace(section, start=start, end=end, size=size, part=part, split=True)],
        size=size,
    )


def _sections(tokens: list[Token], line_count: int, skip: int) -> list[_Section]:
    """Cut the body at every top-level heading; each section knows its full heading path.

    A top-level block inside an open MDX component or block HTML element (``_html_depth``) is
    not recorded as a block start, so no part is cut there. Tags count in HTML blocks and at the
    start of a line of a top-level paragraph (``_line_start_html``), not in running text. The
    count starts again at every top-level heading, which cuts there anyway, so a tag never closed
    only keeps the rest of its own section whole.

    Args:
        tokens: The body's markdown-it tokens.
        line_count: How many lines the body has.
        skip: Lines of malformed front matter at the start, where no heading or fence counts.

    Returns:
        The text before the first heading (level 0), then one section per top-level heading.
    """
    sections = [_Section(level=0, path=(), anchor="", start=0, end=line_count)]
    stack: list[tuple[int, str]] = []
    anchors: set[str] = set()
    depth = 0  # MDX components and block HTML elements open at this point
    for i, token in enumerate(tokens):
        if token.level == 0 and token.type == "heading_open":
            depth = 0
        opens = token.level == 0 and token.nesting >= 0 and token.type != "heading_open"
        if opens and not depth and token.map and token.map[0] >= skip:
            sections[-1].blocks.append(token.map[0])  # a top-level block (a heading: below)
        counted = token.map is not None and token.map[0] >= skip
        if counted and token.level == 0 and token.type == "html_block":
            depth = max(0, depth + _html_depth(token.content))
        elif counted and token.type == "inline" and _opens_top_paragraph(tokens[i - 1]):
            depth = max(0, depth + _html_depth(_line_start_html(token)))
        if token.type == "fence" and token.map and token.map[0] >= skip:
            match = _LANGUAGE.search(token.info.split(maxsplit=1)[0]) if token.info else None
            if match:
                sections[-1].fences.append((token.map[0], match[0]))
        elif token.type == "heading_open" and token.map and token.map[0] >= skip:
            text = _plain(tokens[i + 1])
            anchor = _anchor(text, anchors)  # every heading takes a slug, as on GitHub
            if token.level != 0:
                continue
            level = int(token.tag[1:])
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, text)]
            sections[-1].end = token.map[0]
            sections.append(
                _Section(
                    level=level,
                    path=tuple(t for _, t in stack),
                    anchor=anchor,
                    start=token.map[0],
                    end=line_count,
                    blocks=[token.map[0]],
                )
            )
    return sections


def _opens_top_paragraph(token: Token) -> bool:
    """Tell whether ``token`` opens a top-level paragraph (not one in a list or a quote).

    Args:
        token: The token before an inline one.

    Returns:
        True for a ``paragraph_open`` at level 0.
    """
    return token.type == "paragraph_open" and token.level == 0


def _line_start_html(inline: Token) -> str:
    """The inline HTML of the lines of a paragraph that start with a tag.

    Such a tag could not start an HTML block (``</TabItem>`` right after a paragraph line). A
    tag in running text (``returns Promise<Response>``, ``wrap it in <Note> tags``) is prose, not
    a component, and does not count; a line that starts with one counts whole, so ``<Kbd>C</Kbd>``
    opens nothing.

    Args:
        inline: A paragraph's inline token.

    Returns:
        The tags of those lines, joined.
    """
    html: list[str] = []
    counts = at_start = True
    for child in inline.children or ():
        if child.type in {"softbreak", "hardbreak"}:
            at_start = True
            continue
        if at_start:
            counts, at_start = child.type == "html_inline", False
        if counts and child.type == "html_inline":
            html.append(child.content)
    return "".join(html)


def _html_depth(html: str) -> int:
    """Count the MDX components and block HTML elements ``html`` opens, less those it closes.

    A JSX component (capitalised name) or a tag of ``_BLOCK_TAGS`` counts; a self-closing tag
    (``<Tab />``) and every other tag (inline ones, or ``p`` whose end tag may be left out) do not.

    Args:
        html: The HTML of a block, or the inline HTML of a paragraph.

    Returns:
        Elements opened minus elements closed.
    """
    depth = 0
    for match in _HTML_TAG.finditer(_HTML_COMMENT.sub("", html)):
        closing, name, attributes = match.groups()
        if not (name[0].isupper() or name.lower() in _BLOCK_TAGS):
            continue
        if closing:
            depth -= 1
        elif not attributes.rstrip().endswith("/"):
            depth += 1
    return depth


def _plain(inline: Token) -> str:
    """Heading text without markup: ``The `x` *option*`` -> ``The x option``.

    Args:
        inline: The heading's inline token.

    Returns:
        The heading's text, stripped.
    """
    parts = []
    for child in inline.children or ():
        if child.type in {"text", "code_inline"} or (child.type == "image" and child.content):
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
    return "".join(parts).strip()


def _anchor(text: str, used: set[str]) -> str:
    """GitHub's slug (github-slugger): lower-case, no punctuation, dashes for spaces.

    A taken slug gets ``-1``, ``-2``... until it is unused, and every issued slug is remembered.

    Args:
        text: The heading's plain text.
        used: Slugs already issued in this article; the new one is added.

    Returns:
        The slug, unique within the article.
    """
    base = _ANCHOR_DROP.sub("", text.lower()).replace(" ", "-")
    slug, n = base, 0
    while slug in used:
        n += 1
        slug = f"{base}-{n}"
    used.add(slug)
    return slug
