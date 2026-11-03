"""Pure article parsing: front matter, title rule and removal of invisible characters.

Nothing here touches the filesystem or evaluates content. ``.mdx`` is plain Markdown: JSX,
``import`` and ``export`` lines stay in the body as text and are never executed.
"""

import re
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Any

import yaml
from markdown_it import MarkdownIt

# Bump on any change to the sanitizer or the parser. It feeds the chunking-config hash (E4-02),
# so a fix here re-chunks stored articles instead of reusing stale chunk sets.
PARSER_VERSION = 1

# Characters that render as nothing but reach an LLM as text: zero-width space and friends,
# the byte order mark, bidi controls (Trojan Source) and Unicode "tag" characters (ASCII
# smuggling). Everything else, including every visible character, is left alone.
_ALWAYS_INVISIBLE = re.compile(
    r"[\N{ZERO WIDTH SPACE}\N{WORD JOINER}\N{ZERO WIDTH NO-BREAK SPACE}"
    r"\N{MONGOLIAN VOWEL SEPARATOR}"
    r"\N{ARABIC LETTER MARK}\N{LEFT-TO-RIGHT MARK}\N{RIGHT-TO-LEFT MARK}"
    r"\N{LEFT-TO-RIGHT EMBEDDING}-\N{RIGHT-TO-LEFT OVERRIDE}"  # embeddings, pop, overrides
    r"\N{LEFT-TO-RIGHT ISOLATE}-\N{POP DIRECTIONAL ISOLATE}"
    r"\N{LANGUAGE TAG}-\N{CANCEL TAG}]"  # Unicode tag characters
)
# ZWJ and ZWNJ also carry meaning (emoji sequences, Persian and Indic scripts), so a single one
# between two non-ASCII characters is kept. Next to ASCII or another joiner it can only be a
# hidden channel, and it goes.
_JOINERS = r"\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}"
_STRAY_JOINER = re.compile(
    rf"(?<![^\x00-\x7f{_JOINERS}])[{_JOINERS}]|[{_JOINERS}](?![^\x00-\x7f{_JOINERS}])"
)

_FRONT_MATTER = re.compile(
    r"\A---[ \t]*\r?\n(?:(?P<yaml>.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.DOTALL
)


class _FrontMatterLoader(yaml.SafeLoader):
    """Safe YAML loader that keeps dates as text, so metadata stays JSON-serialisable."""


_FrontMatterLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_MARKDOWN = MarkdownIt("commonmark")


def strip_invisible(text: str) -> str:
    """Remove zero-width, bidi-control and tag characters; change nothing else."""
    return _STRAY_JOINER.sub("", _ALWAYS_INVISIBLE.sub("", text))


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedArticle:
    """An article ready to store: clean Markdown body plus what the front matter said."""

    path: str
    title: str
    body: str
    tags: tuple[str, ...] = ()
    description: str | None = None
    front_matter: dict[str, Any] = field(default_factory=dict)
    problems: tuple[str, ...] = ()


def parse_article(path: str, source: str) -> ParsedArticle:
    """Parse one ``.md`` / ``.mdx`` file.

    The title is the front-matter ``title``, else the first H1, else the file name without its
    extension. Malformed front matter does not fail the article: it stays in the body, the
    metadata is empty and the reason is listed in ``problems``.
    """
    text = strip_invisible(source)
    front_matter: dict[str, Any] = {}
    problems: list[str] = []
    body = text
    if match := _FRONT_MATTER.match(text):
        loader = _FrontMatterLoader(match["yaml"] or "")
        try:
            loaded = loader.get_single_data()
        except (yaml.YAMLError, RecursionError) as error:
            problems.append(f"malformed front matter: {type(error).__name__}")
        else:
            if loaded is None or isinstance(loaded, dict):
                front_matter = loaded or {}
                body = text[match.end() :]
            else:
                problems.append("malformed front matter: not a mapping")
        finally:
            loader.dispose()

    tags = front_matter.get("tags")
    if isinstance(tags, str):
        tags = tags.split(",")
    if tags is not None and not isinstance(tags, list):
        problems.append("front matter tags must be a list or a string")
        tags = []
    description = front_matter.get("description")
    return ParsedArticle(
        path=path,
        title=_title(front_matter.get("title"), body, path),
        body=body,
        tags=tuple(dict.fromkeys(t for item in tags or [] if (t := str(item).strip()))),
        description=description if isinstance(description, str) else None,
        front_matter=front_matter,
        problems=tuple(problems),
    )


def _title(declared: object, body: str, path: str) -> str:
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    tokens = _MARKDOWN.parse(body)
    for opening, inline in pairwise(tokens):
        if opening.type == "heading_open" and opening.tag == "h1":
            heading = "".join(
                child.content
                for child in inline.children or []
                if child.type in {"text", "code_inline"}
            ).strip()
            if heading:
                return heading
    return PurePosixPath(path).stem
