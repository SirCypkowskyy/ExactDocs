"""Heading-based chunker on markdown-it-py, which the article parser already uses.

Chonkie (named in the issue) was not used: its Markdown recipe downloads rules from the Hugging
Face Hub, and its ``MarkdownChef`` mis-detects fences inside block quotes. Chunks are cut only at
top-level headings, so a fence, table or any other block can never be split.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

import markdown_it
from markdown_it import MarkdownIt
from markdown_it.token import Token

from exactdocs.ingestion import models
from exactdocs.ingestion.constants import DEFAULT_CHUNKER
from exactdocs.ingestion.constants._chunker import _ANCHOR_DROP, _LANGUAGE, _LINE
from exactdocs.ingestion.errors import InvalidChunkingConfigError
from exactdocs.ingestion.models import ArticleChunk, ChunkHeading, ChunkingConfig, ParsedArticle

_markdown = MarkdownIt("commonmark").enable("table")


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- grows as lines come
class _Section:
    """The lines from one top-level heading to the next (``level`` 0: before the first)."""

    level: int
    path: tuple[str, ...]
    """Every heading above it, whatever the split level."""
    anchor: str
    start: int
    """First line."""
    end: int
    """One past the last line."""
    languages: list[str] = field(default_factory=list)
    size: int = 0
    """Characters."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- grows as lines come
class _Piece:
    """Consecutive sections that become one chunk; named after the first."""

    sections: list[_Section]
    size: int
    """Characters."""

    @property
    def first(self) -> _Section:
        return self.sections[0]

    def add(self, other: _Piece) -> None:
        self.sections.extend(other.sections)
        self.size += other.size


class MarkdownChunker:
    """The default ``Chunker`` (``markdown``): cuts at top-level headings, see ``ChunkingConfig``.

    Every top-level heading starts a section. Sections whose heading is deeper than the split
    level join the one before (their parent); a chunk longer than ``max_chars`` is cut again at
    the sections it is made of; then chunks shorter than ``min_chars`` are merged with the next
    (the last with the one before) while the result stays within ``max_chars``. The text before
    the first heading is never merged. A chunk is named after its first heading: a cut below the
    split level names the deeper heading, a merge keeps the first one's name. Each chunk records
    every heading it holds (``ArticleChunk.headings``), the one it is named after first.
    """

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self._config = config or ChunkingConfig()

    @property
    def config_hash(self) -> str:
        """Hash of the config, the parser and chunker versions and the markdown-it version."""
        return models.chunking_config_hash(
            self._config, f"markdown-it-py {markdown_it.__version__}"
        )

    def configured(self, config: ChunkingConfig) -> MarkdownChunker:
        """Return a chunker that cuts with ``config``; see the ``Chunker`` port."""
        if config.chunker != DEFAULT_CHUNKER:
            reason = f"unsupported chunker {config.chunker!r}"
            raise InvalidChunkingConfigError(reason)
        return MarkdownChunker(config)

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        """Cut ``article`` at its headings; see the ``Chunker`` port."""
        body = article.body
        lines = _LINE.findall(body)
        skip = 0  # broken front matter stays in the body, but is not Markdown to cut at
        if any(p.startswith("malformed front matter") for p in article.problems):
            skip = len(_LINE.findall(body[: models.malformed_front_matter_length(body)]))
        sections = _sections(_markdown.parse(body), len(lines), skip)
        for section in sections:
            section.size = sum(len(line) for line in lines[section.start : section.end])
        seen: dict[tuple[str, ...], int] = {}
        chunks = []
        blank = ""  # blank text before the first heading rides along with that heading's chunk
        for piece in self._pieces(sections):
            content = blank + "".join(lines[piece.first.start : piece.sections[-1].end])
            blank = ""
            if not content.strip():
                blank = content
                continue
            path = piece.first.path
            occurrence = seen.get(path, 0)
            seen[path] = occurrence + 1
            languages = dict.fromkeys(lang for s in piece.sections for lang in s.languages)
            chunks.append(
                ArticleChunk(
                    heading_path=path,
                    occurrence_index=occurrence,
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

    def _pieces(self, sections: list[_Section]) -> list[_Piece]:
        """Group the sections by split level, cut what is too long, merge what is too short."""
        config = self._config
        grouped: list[_Piece] = []
        for section in sections:
            if grouped and section.level > config.split_depth:
                grouped[-1].add(_Piece(sections=[section], size=section.size))
            else:
                grouped.append(_Piece(sections=[section], size=section.size))
        pieces: list[_Piece] = []
        for piece in grouped:
            if config.max_chars is None or piece.size <= config.max_chars:
                pieces.append(piece)
                continue
            cut: list[_Piece] = []
            for section in piece.sections:
                if cut and cut[-1].size + section.size <= config.max_chars:
                    cut[-1].add(_Piece(sections=[section], size=section.size))
                else:
                    cut.append(_Piece(sections=[section], size=section.size))
            pieces.extend(cut)
        return self._merged(pieces) if config.min_chars else pieces

    def _merged(self, pieces: list[_Piece]) -> list[_Piece]:
        """Merge pieces under ``min_chars`` with the next one, the last with the one before."""
        config = self._config
        limit = config.max_chars

        def fits(a: _Piece, b: _Piece) -> bool:
            return limit is None or a.size + b.size <= limit

        merged: list[_Piece] = []
        for piece in pieces:
            last = merged[-1] if merged else None
            if (
                last is not None
                and last.first.level  # the text before the first heading stays on its own
                and last.size < config.min_chars
                and fits(last, piece)
            ):
                last.add(piece)
            else:
                merged.append(piece)
        if len(merged) > 1:
            tail, before = merged[-1], merged[-2]
            if tail.size < config.min_chars and before.first.level and fits(before, tail):
                before.add(merged.pop())
        return merged


def _sections(tokens: list[Token], line_count: int, skip: int) -> list[_Section]:
    """Cut the body at every top-level heading; each section knows its full heading path."""
    sections = [_Section(level=0, path=(), anchor="", start=0, end=line_count)]
    stack: list[tuple[int, str]] = []
    anchors: set[str] = set()
    for i, token in enumerate(tokens):
        if token.type == "fence" and token.map and token.map[0] >= skip:
            match = _LANGUAGE.search(token.info.split(maxsplit=1)[0]) if token.info else None
            if match and match[0] not in sections[-1].languages:
                sections[-1].languages.append(match[0])
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
                )
            )
    return sections


def _plain(inline: Token) -> str:
    """Heading text without markup: ``The `x` *option*`` -> ``The x option``."""
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
    """
    base = _ANCHOR_DROP.sub("", text.lower()).replace(" ", "-")
    slug, n = base, 0
    while slug in used:
        n += 1
        slug = f"{base}-{n}"
    used.add(slug)
    return slug
