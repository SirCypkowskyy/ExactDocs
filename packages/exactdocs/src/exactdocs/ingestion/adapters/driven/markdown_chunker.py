"""Heading-based chunker on markdown-it-py, which the article parser already uses.

Chonkie (named in the issue) was not used: its Markdown recipe downloads rules from the Hugging
Face Hub, and its ``MarkdownChef`` mis-detects fences inside block quotes. Chunks are cut only at
top-level headings, so a fence, table or any other block can never be split.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

import markdown_it
from markdown_it import MarkdownIt
from markdown_it.token import Token

from exactdocs.ingestion import models
from exactdocs.ingestion.models import ArticleChunk, ChunkingConfig, ParsedArticle

_MARKDOWN = MarkdownIt("commonmark").enable("table")
# markdown-it numbers lines by \n, \r\n and \r only (not U+2028, U+0085 and the like)
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_ANCHOR_DROP = re.compile(r"[^\w\- ]")
_LANGUAGE = re.compile(r"[\w+#-]+")  # `python{1,3}` and `{.python}` both name python


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
        """Hash of the config, the parser and chunker versions and the markdown-it version."""
        return models.chunking_config_hash(
            self._config, f"markdown-it-py {markdown_it.__version__}"
        )

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        """Cut ``article`` at its headings; see the ``Chunker`` port."""
        body = article.body
        lines = _LINE.findall(body)
        skip = 0  # broken front matter stays in the body, but is not Markdown to cut at
        if any(p.startswith("malformed front matter") for p in article.problems):
            skip = len(_LINE.findall(body[: models.malformed_front_matter_length(body)]))
        sections = self._sections(_MARKDOWN.parse(body), len(lines), skip)
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
        if blank and not chunks:  # a body of whitespace only is still one (unaddressed) chunk
            chunks.append(
                ArticleChunk(
                    heading_path=(),
                    occurrence_index=0,
                    position=0,
                    content=blank,
                    content_hash=hashlib.sha256(blank.encode()).hexdigest(),
                    anchor="",
                )
            )
        return tuple(chunks)

    def _sections(self, tokens: list[Token], line_count: int, skip: int) -> list[_Section]:
        sections = [_Section(path=(), anchor="", start=0, end=line_count)]
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
                level = int(token.tag[1:])
                if token.level != 0 or level > self._config.split_depth:
                    continue
                stack = [(lv, t) for lv, t in stack if lv < level] + [(level, text)]
                sections[-1].end = token.map[0]
                sections.append(
                    _Section(
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
