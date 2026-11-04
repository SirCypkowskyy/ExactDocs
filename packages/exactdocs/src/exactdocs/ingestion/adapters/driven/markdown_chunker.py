"""Heading-based chunker on markdown-it-py, which the article parser already uses.

Chonkie (named in the issue) was not used: its Markdown recipe downloads rules from the Hugging
Face Hub, and its ``MarkdownChef`` mis-detects fences inside block quotes. Chunks are cut only at
top-level headings, so a fence, table or any other block can never be split.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from markdown_it.token import Token

from exactdocs.ingestion import models
from exactdocs.ingestion.models import ArticleChunk, ChunkingConfig, ParsedArticle

_MARKDOWN = MarkdownIt("commonmark").enable("table")
# markdown-it counts these as line ends, so line numbers in token maps use them too
_LINE = re.compile(r"[^\r\n\u0085\u2028\u2029\u2424]*(?:\r\n?|[\n\u0085\u2028\u2029\u2424])|.+")
_ANCHOR_DROP = re.compile(r"[^\w\- ]")


@dataclass(slots=True)
class _Section:
    path: tuple[str, ...]
    anchor: str
    start: int  # first line
    end: int  # one past the last line
    languages: list[str] = field(default_factory=list)


class MarkdownChunker:
    """The default ``Chunker``."""

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self._config = config or ChunkingConfig()

    @property
    def config_hash(self) -> str:
        """Hash of the config and of the parser and chunker versions."""
        return models.chunking_config_hash(self._config)

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        """Cut ``article`` at its headings; see the ``Chunker`` port."""
        lines = _LINE.findall(article.body)
        tokens = _MARKDOWN.parse(article.body)
        sections = self._sections(tokens, len(lines))
        seen: dict[tuple[str, ...], int] = {}
        chunks = []
        blank = ""  # blank text before the first heading rides along with that heading's chunk
        for section in sections:
            content = blank + "".join(lines[section.start : section.end])
            blank = ""
            if not content.strip():
                blank = content
                continue
            occurrence = seen.get(section.path, 0)
            seen[section.path] = occurrence + 1
            chunks.append(
                ArticleChunk(
                    heading_path=section.path,
                    occurrence_index=occurrence,
                    position=len(chunks),
                    content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    anchor=section.anchor,
                    code_languages=tuple(section.languages),
                )
            )
        return tuple(chunks)

    def _sections(self, tokens: list[Token], line_count: int) -> list[_Section]:
        sections = [_Section(path=(), anchor="", start=0, end=line_count)]
        stack: list[tuple[int, str]] = []
        anchors: dict[str, int] = {}
        for i, token in enumerate(tokens):
            if token.type == "fence":
                language = token.info.split(maxsplit=1)[:1]
                if language and language[0] not in sections[-1].languages:
                    sections[-1].languages.append(language[0])
            elif token.type == "heading_open" and token.level == 0 and token.map:
                level, text = int(token.tag[1:]), _plain(tokens[i + 1])
                if level > self._config.split_depth:
                    continue
                stack = [(lv, t) for lv, t in stack if lv < level] + [(level, text)]
                sections[-1].end = token.map[0]
                sections.append(
                    _Section(
                        path=tuple(t for _, t in stack),
                        anchor=_anchor(text, anchors),
                        start=token.map[0],
                        end=line_count,
                    )
                )
        return sections


def _plain(inline: Token) -> str:
    """Heading text without markup: ``The `x` *option*`` -> ``The x option``."""
    parts = [
        child.content
        for child in inline.children or ()
        if child.type in {"text", "code_inline"} or (child.type == "image" and child.content)
    ]
    return "".join(parts).strip()


def _anchor(text: str, used: dict[str, int]) -> str:
    """GitHub's heading anchor: lower-case, no punctuation, dashes for spaces, ``-1`` on repeats."""
    base = _ANCHOR_DROP.sub("", text.lower()).replace(" ", "-")
    count = used.get(base, 0)
    used[base] = count + 1
    return base if count == 0 else f"{base}-{count}"
