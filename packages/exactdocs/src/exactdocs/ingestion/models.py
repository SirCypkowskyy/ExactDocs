"""Pure ingestion logic: git URL parsing and article parsing (front matter, title, invisibles).

Parsing covers front matter, the title rule and removal of invisible characters. Nothing here
touches the filesystem or evaluates content. ``.mdx`` is plain Markdown: JSX, ``import`` and
``export`` lines stay in the body as text and are never executed.
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import math
import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from fnmatch import fnmatchcase
from functools import lru_cache
from html.parser import HTMLParser
from itertools import pairwise, starmap
from operator import itemgetter
from pathlib import PurePosixPath
from typing import Any, NewType, Self
from urllib.parse import unquote, urlsplit

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from exactdocs.ingestion.constants import (
    ANY,
    ARTICLE_SUFFIXES,
    CHUNKER_VERSION,
    CHUNKERS,
    CONTEXT7_MAX_BYTES,
    DEFAULT_CHUNKER,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_KEEP_LAST,
    DEFAULT_MAX_SECTION_CHARS,
    FLAT_HOSTS,
    GITHUB_SIGNATURE_HEADER,
    GLOB_CHARS,
    HEADS,
    INSTRUCTION_FILE_NAMES,
    KNOWN_HOSTS,
    MAX_CHECK_ERROR,
    MAX_CHUNK_CHARS,
    MAX_CONTEXT7_RULE_CHARS,
    MAX_CONTEXT7_RULES,
    MAX_DELIVERY_ID,
    MAX_HEADING_LEVEL,
    MAX_IMAGES_PER_ARTICLE,
    MAX_INSTRUCTION_DIRS,
    MAX_INTERVAL_MINUTES,
    MAX_JOB_NOTES,
    MAX_JOB_PROBLEMS,
    MAX_KEEP_LAST,
    MAX_PREVIOUS_VERSION_CHARS,
    MAX_PREVIOUS_VERSIONS,
    MAX_RENAMES,
    MAX_SIMILARITY,
    MAX_TAG_PATTERN,
    MAX_TAG_RULES,
    MERGED_HEADINGS_VERSION,
    MIN_INTERVAL_MINUTES,
    ONE,
    OPENSSH_MAGIC,
    PARSER_VERSION,
    PEELED,
    README_DESCRIPTION_MAX,
    README_TITLE_MAX,
    SIGNATURE_SCHEME,
    SOURCE_MISMATCH,
    TAGS,
    JobKind,
)
from exactdocs.ingestion.constants._models import (
    _ALWAYS_INVISIBLE,
    _BAD_REF_CHARS,
    _BADGE_SOURCES,
    _FRONT_MATTER,
    _GIT_SUFFIX,
    _HOST,
    _ID_SEGMENTS,
    _LOGO_WORDS,
    _LOOPBACK,
    _MAX_BRANCH,
    _MAX_IMAGE_DEPTH,
    _MAX_KEY,
    _MAX_PATH,
    _MAX_PATTERN,
    _MAX_PATTERNS,
    _MAX_RAW_TAGS,
    _MAX_SEGMENT,
    _MAX_TOKEN,
    _NO_ALIASES,
    _NUMERIC_REF,
    _ORDER_WIDTH,
    _README_LABEL,
    _README_NAV_CHARS,
    _SCHEME,
    _SCHEMES,
    _SCP_LIKE,
    _SHA_PREFIX,
    _SSH_USER,
    _STRAY_JOINER,
    _SVG,
    _TOKEN_USER,
    _UNSAFE_ID_CHARS,
)
from exactdocs.ingestion.errors import (
    AmbiguousRefError,
    CredentialProblem,
    InvalidAutoSyncError,
    InvalidChunkingConfigError,
    InvalidContext7Error,
    InvalidCredentialError,
    InvalidPathPatternError,
    InvalidProgressError,
    InvalidRepositoryUrlError,
    InvalidTagError,
    InvalidWebhookPayloadError,
    MissingDeliveryIdError,
    PatternProblem,
    TagProblem,
    UnknownRefError,
    UrlProblem,
)
from exactdocs_kernel import MAX_TAGS, normalize_tag


class NotJsonSafeError(ValueError):
    """Front matter holds values that cannot be stored as standard JSON."""

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "values must be text, numbers, booleans, null, lists or maps with text keys"
        )


class _FrontMatterLoader(yaml.SafeLoader):
    """Safe YAML loader without anchors and aliases and with dates kept as text.

    Aliases would let a few hundred bytes expand into gigabytes once the metadata is serialised
    (and make it recursive), so they are rejected while the document is composed.
    """

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node | None:
        """Compose a node, refusing anchors and aliases.

        Args:
            parent: The node being composed around it, if any.
            index: Its key or position in ``parent``.

        Returns:
            The composed node.

        Raises:
            MarkedYAMLError: The document uses an anchor or an alias.
        """
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            raise yaml.MarkedYAMLError(problem=_NO_ALIASES, problem_mark=event.start_mark)
        return super().compose_node(parent, index)


_FrontMatterLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_markdown = MarkdownIt("commonmark")
_readme_markdown = MarkdownIt("commonmark").enable("table")  # a table is not a description


def malformed_front_matter_length(body: str) -> int:
    """Length of the broken front-matter block ``parse_article`` left at the start of ``body``.

    Args:
        body: An article's body.

    Returns:
        The block's length in characters; 0 when the body does not start with one.
    """
    match = _FRONT_MATTER.match(body)
    return match.end() if match else 0


def stored_front_matter_problems(
    path: str, content: str, front_matter: Mapping[str, Any], blob_sha: str
) -> tuple[str, ...] | None:
    """Return the malformed-front-matter note a parse of the file gave, from what was stored.

    ``content`` and ``front_matter`` are what ``parse_article`` gave the file whose git blob SHA
    is ``blob_sha``. Whether its front matter was malformed (it is then the start of the body,
    not Markdown to cut at) is not stored. It can be only when nothing was taken from the file
    and ``content`` starts with a block the YAML loader refuses. Then the file either was that
    text (its blob SHA says so: the front matter was malformed) or had a front matter that loaded
    to nothing (blank lines or comments) before it, and that block is Markdown (#228). ``None``
    when the blob SHA cannot tell them apart (the parser also strips invisible characters): only
    a parse of the file can.

    Args:
        path: The file's repository path.
        content: The stored body.
        front_matter: The stored front matter.
        blob_sha: The file's git blob SHA.

    Returns:
        The note (``()`` when there was none), or ``None`` when only a parse can tell.
    """
    if front_matter or not malformed_front_matter_length(content):
        return ()
    reparsed = parse_article(path, content)
    if reparsed.body != content or not reparsed.problems:
        return ()  # a mapping (so taken from a file) or not YAML front matter at all: Markdown
    return reparsed.problems if git_blob_sha(content.encode()) == blob_sha else None


def strip_invisible(text: str) -> str:
    """Remove invisible and control characters (see ``_ALWAYS_INVISIBLE``); change nothing else.

    Args:
        text: Untrusted text.

    Returns:
        The text without them.
    """
    return _STRAY_JOINER.sub("", _ALWAYS_INVISIBLE.sub(lambda m: m["flag"] or "", text))


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedArticle:
    """An article ready to store: clean Markdown body plus what the front matter said."""

    path: str
    """The file's repository path."""
    title: str
    """The front-matter ``title``, else the first H1, else the file name without its extension."""
    body: str
    """The Markdown after the front matter (all of it when the front matter is malformed)."""
    tags: tuple[str, ...] = ()
    """The normalized front-matter tags."""
    description: str | None = None
    """The front-matter ``description``, if it is text."""
    front_matter: dict[str, Any] = field(default_factory=dict)
    """The front matter as loaded; empty when there is none or it is malformed."""
    problems: tuple[str, ...] = ()
    """Notes on the front matter: the article is imported anyway."""
    images: tuple[str, ...] = ()
    """Repository paths of the images the body references by a relative link (``image_paths``)."""


def parse_article(path: str, source: str) -> ParsedArticle:
    """Parse one ``.md`` / ``.mdx`` file.

    The title is the front-matter ``title``, else the first H1, else the file name without its
    extension. Malformed front matter does not fail the article: it stays in the body, the
    metadata is empty and the reason is listed in ``problems``. A leading ``---`` block that is
    not a mapping (a thematic break around prose) is just body text, with no problem.

    Args:
        path: The file's repository path.
        source: The file's text.

    Returns:
        The article.
    """
    text = strip_invisible(source)
    front_matter: dict[str, Any] = {}
    problems: list[str] = []
    body = text
    if match := _FRONT_MATTER.match(text):
        try:
            loaded = _load_front_matter(match["yaml"] or "")
        except (yaml.YAMLError, RecursionError, ValueError) as error:
            problems.append(f"malformed front matter: {_reason(error)}")
        else:
            if loaded is None or isinstance(loaded, dict):
                front_matter = loaded or {}
                body = text[match.end() :]

    declared_tags, declared_problems = _declared(front_matter)
    return ParsedArticle(
        path=path,
        title=_title(front_matter.get("title"), body, path),
        body=body,
        tags=declared_tags,
        description=_description(front_matter),
        front_matter=front_matter,
        problems=(*problems, *declared_problems),
        images=image_paths(path, body),
    )


def _declared(front_matter: Mapping[str, Any]) -> tuple[tuple[str, ...], list[str]]:
    """Return the tags a parsed front matter declares, and the notes on its title and tags.

    Args:
        front_matter: The loaded front matter.

    Returns:
        The normalized tags, and the notes.
    """
    problems: list[str] = []
    declared = front_matter.get("title")
    if declared is not None and not isinstance(declared, str):
        problems.append("front matter title must be text")
    tags, tag_problems = front_matter_tags(front_matter)
    return tags, [*problems, *tag_problems]


def _description(front_matter: Mapping[str, Any]) -> str | None:
    """Take the front-matter ``description`` if it is text.

    Args:
        front_matter: The loaded front matter.

    Returns:
        The description, or None.
    """
    description = front_matter.get("description")
    return description if isinstance(description, str) else None


def front_matter_tags(front_matter: Mapping[str, Any]) -> tuple[tuple[str, ...], list[str]]:
    """Return the normalized tags a front matter declares, and what was wrong with them.

    ``tags`` is a list or a comma-separated string; invalid items are dropped, at most
    ``MAX_TAGS`` kept. Pure, so the tags of a stored article can be derived again from its
    stored front matter (re-tagging without a fetch).

    Args:
        front_matter: The loaded or stored front matter.

    Returns:
        The tags, and the notes on what was ignored.
    """
    problems: list[str] = []
    tags = front_matter.get("tags")
    if isinstance(tags, str):
        tags = tags.split(",")
    if tags is not None and not isinstance(tags, list):
        problems.append("front matter tags must be a list or a string")
        tags = []
    tags = tags or []
    if not all(isinstance(tag, str) for tag in tags):
        problems.append("front matter tags must be text; other items were ignored")
    named = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
    skipped = max(0, len(named) - _MAX_RAW_TAGS)  # not even normalized: bounded work
    normalized = [normalize_tag(tag) for tag in named[:_MAX_RAW_TAGS]]
    if (invalid := normalized.count(None) + skipped) or len(set(normalized)) > MAX_TAGS:
        problems.append(f"front matter tags: {invalid} invalid ignored, at most {MAX_TAGS} kept")
    return tuple(dict.fromkeys(t for t in normalized if t))[:MAX_TAGS], problems


def image_paths(article_path: str, body: str) -> tuple[str, ...]:
    """Repository paths of the images ``![](src)`` of a Markdown body points at, first-seen order.

    Mirrors the web renderer's ``repoPath``: ``src`` is resolved against the article's folder (a
    leading ``/`` means the repository root), query and fragment are dropped, a path that leaves
    the repository, has a scheme (``https:``, ``data:``), starts with ``//`` or holds a control
    character, a backslash or a ``.git`` segment is ignored. At most ``MAX_IMAGES_PER_ARTICLE``.

    Args:
        article_path: The article's repository path.
        body: Its Markdown body.

    Returns:
        The image paths.
    """
    found: dict[str, None] = {}
    if "![" not in body:  # every image, inline or by reference, starts so: skip the parse
        return ()
    for token in _markdown.parse(body):
        for child in token.children or ():
            if child.type != "image" or len(found) >= MAX_IMAGES_PER_ARTICLE:
                continue
            if path := _resolve(article_path, str(child.attrGet("src") or "").strip()):
                found[path] = None
    return tuple(found)


def _resolve(article_path: str, src: str) -> str | None:
    """Resolve an image's ``src`` against its article's folder.

    Args:
        article_path: The article's repository path.
        src: The image's ``src``, trimmed.

    Returns:
        The image's repository path, or None when it is ignored.
    """
    if _SCHEME.match(src) or src.startswith("//"):
        return None
    target = unquote(re.split(r"[?#]", src, maxsplit=1)[0])
    if not target or "\\" in target or not target.isprintable():
        return None
    parts = [] if target.startswith("/") else article_path.split("/")[:-1]
    for part in target.split("/"):
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part not in {".", ""}:
            parts.append(part)
    if not parts or len(parts) > _MAX_IMAGE_DEPTH or any(p.lower() == ".git" for p in parts):
        return None
    return "/".join(parts)


def _load_front_matter(text: str) -> object:
    """Load YAML front matter with ``_FrontMatterLoader``.

    Args:
        text: The YAML between the ``---`` lines.

    Returns:
        What it loads to.

    Raises:
        NotJsonSafeError: It holds a value standard JSON cannot.
    """
    loader = _FrontMatterLoader(text)
    try:
        loaded = loader.get_single_data()
    finally:
        loader.dispose()
    if not _is_json_safe(loaded):
        raise NotJsonSafeError
    return loaded


def _is_json_safe(value: object) -> bool:
    """Tell whether standard JSON can hold it (no bytes, sets, dates, NaN or Infinity).

    Args:
        value: A loaded YAML value.

    Returns:
        True when it can be stored as JSON.
    """
    match value:
        case None | bool() | str() | int():
            return True
        case float():
            return math.isfinite(value)
        case list():
            return all(_is_json_safe(item) for item in value)
        case dict():
            return all(isinstance(k, str) and _is_json_safe(v) for k, v in value.items())
        case _:
            return False


def _reason(error: Exception) -> str:
    """Say what is wrong and where, without echoing the file's content.

    Args:
        error: Why the front matter did not load.

    Returns:
        The reason, with the line for a YAML error.
    """
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark:
        # +2: the front matter starts on line 2 (after the opening ---), marks are 0-based
        where = f"at line {error.problem_mark.line + 2}"
        return f"{_NO_ALIASES} {where}" if error.problem == _NO_ALIASES else f"invalid YAML {where}"
    return str(error) if isinstance(error, ValueError) else "invalid YAML"


def _title(declared: object, body: str, path: str) -> str:
    """Pick an article's title.

    Args:
        declared: The front-matter ``title``, whatever its type.
        body: The Markdown body.
        path: The file's repository path.

    Returns:
        The declared title if it is text, else the first H1, else the file name's stem.
    """
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    tokens = _markdown.parse(body)
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadmeSummary:
    """What a root README says about its library; ``None`` where it says nothing usable."""

    title: str | None = None
    """The first H1's text (or its image's ``alt``), else the ``alt`` of a logo opening the file."""
    description: str | None = None
    """The first paragraph's text after where the title was found."""


def readme_summary(source: str) -> ReadmeSummary:
    """Take the title and the first paragraph after it from untrusted README text.

    The title is the first H1, Markdown or HTML: its text, or its image's ``alt`` when it is a
    logo. Without one it is the ``alt`` of the image the file opens with (before any heading or
    text, and not a badge), as in READMEs that start with a centered logo. A lower heading is a
    section, never the title: without both the title is ``None`` (the caller falls back to the
    repository name).

    Run through ``parse_article`` first, so invisible characters and front matter are gone. Only
    plain text is kept (no markup, images or HTML), whitespace is collapsed and the values are
    cut to ``README_TITLE_MAX`` / ``README_DESCRIPTION_MAX``. Paragraphs inside lists or quotes,
    paragraphs with no text (badges, images) and nav lines (links, alone or after short labels
    such as ``Documentation:``) are skipped. Without a title the first paragraph of the file is
    used.

    Args:
        source: The README's text.

    Returns:
        The title and the description found.
    """
    tokens = _readme_markdown.parse(parse_article("README.md", source).body)
    title, start = _readme_title(tokens)
    if title is not None:
        title = title[:README_TITLE_MAX].rstrip()
    description = None
    for index in range(start, len(tokens)):
        if (
            tokens[index].type == "paragraph_open"
            and tokens[index].level == 0
            and (text := _inline_text(tokens[index + 1], skip_link_only=True))
        ):
            description = text[:README_DESCRIPTION_MAX].rstrip()
            break
    return ReadmeSummary(title=title, description=description)


type _HeadEvent = tuple[str, str, str]
"""``("h1", title, "")``, ``("img", alt, src)`` or ``("text", "", "")``, in document order."""


class _HtmlHead(HTMLParser):
    """Turn README HTML into ``_HeadEvent``s: each ``<h1>``, image and piece of visible text."""

    def __init__(self) -> None:
        """Start with no events, outside any ``<h1>``; character references are decoded."""
        super().__init__(convert_charrefs=True)
        self.events: list[_HeadEvent] = []
        self._h1: list[str] | None = None  # the text of the open <h1>
        self._h1_alt = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open an ``<h1>``, or note an image: inside an ``<h1>`` its ``alt`` names the heading.

        Args:
            tag: The tag's name, lowercased.
            attrs: Its attributes.
        """
        values = {name: value or "" for name, value in attrs}
        if tag == "h1":
            self._h1, self._h1_alt = [], ""
        elif tag == "img" and self._h1 is not None:
            self._h1_alt = self._h1_alt or values.get("alt", "")
        elif tag == "img":
            self.events.append(("img", values.get("alt", ""), values.get("src", "")))

    def handle_endtag(self, tag: str) -> None:
        """Close an ``<h1>``: its text, else its image's ``alt``; empty, it is plain text.

        Args:
            tag: The tag's name, lowercased.
        """
        if tag == "h1" and self._h1 is not None:
            text = " ".join("".join(self._h1).split()) or _logo_name(self._h1_alt)
            self.events.append(("h1", text, "") if text else ("text", "", ""))
            self._h1 = None

    def handle_data(self, data: str) -> None:
        """Collect the text of the open ``<h1>``, or note visible text.

        Args:
            data: Text between tags.
        """
        if self._h1 is not None:
            self._h1.append(data)
        elif data.strip():
            self.events.append(("text", "", ""))


def _html_events(html: str) -> list[_HeadEvent]:
    """Parse a piece of README HTML; an ``<h1>`` left open still counts.

    Args:
        html: An HTML block or inline tag.

    Returns:
        Its events, in order.
    """
    parser = _HtmlHead()
    parser.feed(html)
    parser.close()
    parser.handle_endtag("h1")
    return parser.events


def _head_events(tokens: Sequence[Token]) -> Iterator[tuple[int, _HeadEvent]]:
    """Walk a README's blocks as the events that decide its title, each with its token index.

    Args:
        tokens: The parsed README.

    Yields:
        The index of the block and one of its events.
    """
    for index, token in enumerate(tokens):
        match token.type:
            case "heading_open" if token.tag == "h1":
                inline = tokens[index + 1]
                text = _inline_text(inline) or _logo_name(_image_alt(inline))
                yield index, ("h1", text, "") if text else ("text", "", "")
            case "heading_open" | "fence" | "code_block":
                yield index, ("text", "", "")
            case "html_block":
                for event in _html_events(token.content):
                    yield index, event
            case "inline" if tokens[index - 1].type == "paragraph_open":
                for event in _inline_events(token):
                    yield index - 1, event
            case _:
                pass


def _inline_events(inline: Token) -> Iterator[_HeadEvent]:
    """The events of a paragraph's text: its images, inline HTML and visible text.

    Args:
        inline: The paragraph's inline token.

    Yields:
        Its events, in order.
    """
    for child in inline.children or []:
        match child.type:
            case "image":
                yield "img", child.content, str(child.attrs.get("src", ""))
            case "html_inline":
                yield from _html_events(child.content)
            case "text" | "code_inline" if child.content.strip():
                yield "text", "", ""
            case _:
                pass


def _readme_title(tokens: Sequence[Token]) -> tuple[str | None, int]:
    """Find a README's title: its first H1, else the logo it opens with.

    Args:
        tokens: The parsed README.

    Returns:
        The title (``None`` if there is none) and the index of the block it came from (0 then).
    """
    logo: tuple[str, int] | None = None
    first_image, text_seen = True, False
    for index, (kind, value, source) in _head_events(tokens):
        match kind:
            case "h1":
                return value, index
            case "img":
                if first_image and not text_seen and not _is_badge(source):
                    name = _logo_name(value)
                    logo = (name, index) if name else None
                first_image = False
            case _:
                text_seen = True
    return logo if logo is not None else (None, 0)


def _image_alt(inline: Token) -> str:
    """The ``alt`` of the first image of an inline token, Markdown or an HTML ``<img>``.

    Args:
        inline: An inline token, such as a heading's.

    Returns:
        The ``alt`` text; empty when there is no image.
    """
    for child in inline.children or []:
        if child.type == "image":
            return child.content
        if child.type == "html_inline":
            for kind, alt, _ in _html_events(child.content):
                if kind == "img":
                    return alt
    return ""


def _logo_name(alt: str) -> str:
    """The project name an image's ``alt`` gives: without "logo" or "banner", collapsed.

    Args:
        alt: The image's ``alt`` text.

    Returns:
        The name; empty when nothing is left.
    """
    return " ".join(_LOGO_WORDS.sub(" ", alt).split()).strip(" -|:")


def _is_badge(source: str) -> bool:
    """Tell a badge image (CI status, package version) by its source.

    Args:
        source: The image's ``src``.

    Returns:
        True for a badge.
    """
    lowered = source.lower()
    return any(part in lowered for part in _BADGE_SOURCES)


def _inline_text(inline: Token, *, skip_link_only: bool = False) -> str:
    """Join the visible text of an inline token, collapsing whitespace.

    With ``skip_link_only`` text that is nothing but links (a nav bar), each line alone or after
    a short label (``Documentation: <link>``), gives ``""``.

    Args:
        inline: An inline token.
        skip_link_only: Give ``""`` for text that is nothing but links.

    Returns:
        The text, whitespace collapsed.
    """
    words, outside, in_link, links = [], [], False, False
    for child in inline.children or []:
        match child.type:
            case "link_open":
                in_link = links = True
            case "link_close":
                in_link = False
            case "softbreak" | "hardbreak":
                words.append(" ")
                outside.append("\n")
            case "text" | "code_inline":
                words.append(child.content)
                if not in_link:
                    outside.append(child.content)
    if skip_link_only:
        rest = "".join(outside)
        if links:
            rest = _README_LABEL.sub("", rest)
        if not rest.strip(_README_NAV_CHARS):
            return ""
    return " ".join("".join(words).split())


# ---------------------------------------------------------------- jobs

JobId = NewType("JobId", str)


class VersionOrigin(StrEnum):
    """Who asked for a version: a person (``manual``) or the scheduled check (``auto``).

    Retention (``AutoSync.keep_last``) only ever removes ``auto`` versions.
    """

    MANUAL = "manual"
    AUTO = "auto"


class JobState(StrEnum):
    """Where a job is in its life. Only ``queued`` and ``running`` jobs are unfinished."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProblemCode(StrEnum):
    """Why a file shows up in a job's problems; stable, clients may branch on it."""

    BINARY = "binary"
    TOO_LARGE = "too_large"
    UNDECODABLE = "undecodable"
    NOT_A_FILE = "not_a_file"
    UNREADABLE = "unreadable"
    BAD_FILE_NAME = "bad_file_name"
    UNPARSABLE = "unparsable"
    """The file was read but could not be parsed or cut into chunks; the rest was imported."""
    FRONT_MATTER = "front_matter"
    """The article was imported, but its front matter is malformed or partly ignored."""
    NOT_AN_IMAGE = "not_an_image"
    """A referenced image is not a PNG, JPEG, GIF, WebP or SVG by its content."""
    IMAGE_BUDGET = "image_budget"
    """An image was left out because the version's images already use their count or byte budget."""
    MISSING_IMAGE = "missing_image"
    """An article references an image that the repository does not have at this commit."""
    TRUNCATED = "truncated"
    """The marker that says more files were skipped than ``MAX_JOB_PROBLEMS``."""
    CONTEXT7 = "context7"
    """The root ``context7.json`` cannot be used and was ignored; the import went on without it."""
    INSTRUCTION_FILES = "instruction_files"
    """The instruction files (repo guidance) could not be read; the version has none."""

    @property
    def is_skip(self) -> bool:
        """Whether the file was left out of the version (as opposed to imported with a note)."""
        return self not in {
            ProblemCode.FRONT_MATTER,
            ProblemCode.TRUNCATED,
            ProblemCode.CONTEXT7,
            ProblemCode.INSTRUCTION_FILES,
        }


class SyncErrorCode(StrEnum):
    """Why a re-sync could not bring a version up to date; stable, clients may branch on it.

    The version keeps serving what it had in every case: these say which upstream problem it was.
    """

    REPO_UNREACHABLE = "repo_unreachable"
    """The repository cannot be read: deleted, made private, moved, or the server is down."""
    AUTH_FAILED = "auth_failed"
    """The server refused the credential (expired, revoked) or the stored one cannot be read."""
    REF_DELETED = "ref_deleted"
    """The branch or tag the version follows is no longer in the repository."""
    TAG_MOVED = "tag_moved"
    """The tag now points at another commit; it is reported, never re-imported by a sync."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FileProblem:
    """A problem with one file of an import: ``code`` is the stable kind, ``reason`` the text."""

    path: str
    """The file's repository path; empty for the ``truncated`` marker."""
    code: ProblemCode
    """What kind of problem it is."""
    reason: str
    """What happened, in words for users."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Job:
    """A long task for one library (optionally one version) and how far it got.

    ``total`` is 0 until the job knows its size. ``chunked`` and ``reused`` count the articles an
    import cut into chunks and those whose chunks an earlier import had already stored (for an
    ``embed`` job, ``reused`` counts the chunks another job embedded meanwhile, within ``done``);
    ``parsed`` and ``taken`` the articles it parsed and those it took as an earlier import had
    stored them.
    ``commit_sha`` is the commit the job's ``version`` was pinned to when it was queued,
    ``ref_kind`` what ``version`` is (a tag, a branch or a bare commit) as resolved then.
    Every transition returns a new job.
    """

    id: JobId
    """Time-ordered: a later job has a greater ID."""
    kind: JobKind
    """What the job does."""
    library: str
    """The library ID."""
    version: str | None
    """The ref of the version the job is for; ``None`` for a job of the whole library."""
    state: JobState
    """Where the job is in its life."""
    commit_sha: str | None = None
    """The commit ``version`` was pinned to when the job was queued."""
    ref_kind: RefKind | None = None
    """What ``version`` is, as resolved when the job was queued."""
    done: int = 0
    """How much of ``total`` is done."""
    total: int = 0
    """The job's size; 0 until it is known."""
    problems: tuple[FileProblem, ...] = ()
    """The files skipped or imported with a note."""
    notes: int = 0
    """How many of ``problems`` are notes on imported files (derived, not stored)."""
    chunked: int = 0
    """Articles an import cut into chunks."""
    reused: int = 0
    """Articles whose chunks an earlier import had stored; for ``embed``, chunks found embedded."""
    parsed: int = 0
    """Articles an import parsed."""
    taken: int = 0
    """Articles an import took as an earlier import had stored them."""
    error: str | None = None
    """Why the job failed, for users; ``None`` unless it failed."""
    error_code: str | None = None
    """The stable code of ``error``: a ``SyncErrorCode``, an error's own code or ``unexpected``."""
    origin: VersionOrigin = VersionOrigin.MANUAL
    """Who queued it; the first import of a version gives the version this origin."""
    created_at: datetime
    """When the job was queued."""
    started_at: datetime | None = None
    """When the job last started running."""
    finished_at: datetime | None = None
    """When the job ended."""

    @classmethod
    def queued(
        cls,
        *,
        job_id: JobId,
        kind: JobKind,
        library: str,
        version: str | None,
        now: datetime,
        commit_sha: str | None = None,
        ref_kind: RefKind | None = None,
        origin: VersionOrigin = VersionOrigin.MANUAL,
    ) -> Self:
        """Create a job that waits for the worker.

        Args:
            job_id: The new job's ID.
            kind: What the job does.
            library: The library ID.
            version: The version's ref; ``None`` for a job of the whole library.
            now: The time it is queued.
            commit_sha: The commit ``version`` is pinned to.
            ref_kind: What ``version`` is.
            origin: Who queued it.

        Returns:
            The queued job.
        """
        return cls(
            id=job_id,
            kind=kind,
            library=library,
            version=version,
            commit_sha=commit_sha,
            ref_kind=ref_kind,
            origin=origin,
            state=JobState.QUEUED,
            created_at=now,
        )

    def started(self, now: datetime) -> Self:
        """Mark the job as picked up by the worker.

        Args:
            now: The time it starts.

        Returns:
            The running job.
        """
        return replace(self, state=JobState.RUNNING, started_at=now)

    def progressed(self, *, done: int, total: int) -> Self:
        """``done`` of ``total`` files processed so far.

        Args:
            done: How much is done.
            total: How much there is.

        Returns:
            The job with that progress.

        Raises:
            InvalidProgressError: ``done`` is negative or more than ``total``.
        """
        if not 0 <= done <= total:
            raise InvalidProgressError(done, total)
        return replace(self, done=done, total=total)

    def chunking(self, *, chunked: int, reused: int) -> Self:
        """Record how many articles were chunked now and how many reused stored chunks.

        Args:
            chunked: Articles cut into chunks.
            reused: Articles whose stored chunks were reused.

        Returns:
            The job with those counts.
        """
        return replace(self, chunked=chunked, reused=reused)

    def parsing(self, *, parsed: int, taken: int) -> Self:
        """Record how many articles were parsed now and how many taken as stored before.

        Args:
            parsed: Articles parsed.
            taken: Articles taken as stored.

        Returns:
            The job with those counts.
        """
        return replace(self, parsed=parsed, taken=taken)

    def with_problem(self, path: str, code: ProblemCode, reason: str) -> Self:
        """Record a problem with a file; the job goes on.

        Skips are kept up to ``MAX_JOB_PROBLEMS``, then counted in one ``truncated`` marker.
        Notes (``front_matter``) have a separate, lower ``MAX_JOB_NOTES`` and are dropped beyond
        it, so they can never crowd skips out.

        Args:
            path: The file's repository path.
            code: What kind of problem it is.
            reason: What happened, in words for users.

        Returns:
            The job with the problem recorded, counted or dropped.
        """
        if code is ProblemCode.FRONT_MATTER:
            if self.notes >= MAX_JOB_NOTES:
                return self
            problem = FileProblem(path=path, code=code, reason=reason)
            return replace(self, problems=(*self.problems, problem), notes=self.notes + 1)
        if len(self.problems) - self.notes < MAX_JOB_PROBLEMS:
            return replace(
                self, problems=(*self.problems, FileProblem(path=path, code=code, reason=reason))
            )
        # The marker is the last skip-sized entry; notes may have been appended after it.
        marker = next(
            (i for i, p in enumerate(self.problems) if p.code is ProblemCode.TRUNCATED), None
        )
        if marker is None:
            problem = FileProblem(path="", code=ProblemCode.TRUNCATED, reason=_dropped_reason(1))
            return replace(self, problems=(*self.problems, problem))
        dropped = _dropped(self.problems[marker]) + 1
        problems = list(self.problems)
        problems[marker] = FileProblem(
            path="", code=ProblemCode.TRUNCATED, reason=_dropped_reason(dropped)
        )
        return replace(self, problems=tuple(problems))

    @property
    def skipped_count(self) -> int:
        """Files left out of the version, including the ones past the cap."""
        return sum(
            _dropped(p) if p.code is ProblemCode.TRUNCATED else p.code.is_skip
            for p in self.problems
        )

    def succeeded(self, now: datetime) -> Self:
        """Mark the job as finished.

        Args:
            now: The time it ended.

        Returns:
            The succeeded job.
        """
        return replace(self, state=JobState.SUCCEEDED, finished_at=now)

    def failed(self, error: str, now: datetime, *, code: str | None = None) -> Self:
        """Mark the job as stopped with ``error`` (the text) and its stable ``code``.

        Args:
            error: Why it failed, for users.
            now: The time it ended.
            code: The stable code of ``error``.

        Returns:
            The failed job.
        """
        return replace(self, state=JobState.FAILED, error=error, error_code=code, finished_at=now)

    def requeued(self) -> Self:
        """Run again from the beginning, as if never started.

        Returns:
            The job queued again, its progress, problems and error cleared.
        """
        return replace(
            self,
            state=JobState.QUEUED,
            done=0,
            total=0,
            problems=(),
            chunked=0,
            reused=0,
            parsed=0,
            taken=0,
            notes=0,
            error=None,
            error_code=None,
            started_at=None,
            finished_at=None,
        )


ProposedId = NewType("ProposedId", str)
"""A proposed `/owner/repo` library ID."""


class RepositoryHost(StrEnum):
    """Where a repository is hosted, by exact host name; ``git`` is any other server."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GITEA = "gitea"
    GIT = "git"


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryUrl:
    """A git URL that passed ``parse``: the text to hand to git, where it lives, a library ID.

    ``parse`` is the gate. It accepts only ``https``, ``http``, ``ssh`` (``ssh://`` and
    ``user@host:path``) and ``file`` URLs; refuses a leading ``-`` (an option), whitespace and
    control characters, transport helpers such as ``ext::`` and ``fd::``, ``git://``, and any
    credential, query or fragment in the URL. Nothing it raises repeats the input.
    """

    url: str
    """The URL as typed, trimmed: what git is given."""
    host_kind: RepositoryHost
    """The hosting service, for source links."""
    library_id: ProposedId
    """The proposed library ID."""

    @property
    def transport(self) -> str:
        """``https``, ``http``, ``ssh`` (also ``user@host:path``) or ``file``."""
        return urlsplit(self.url).scheme.lower() if "://" in self.url else "ssh"

    @property
    def hostname(self) -> str:
        """The lower-case host name (no user, no port); empty for ``file:``."""
        if "://" in self.url:
            return (urlsplit(self.url).hostname or "").lower()
        match = _SCP_LIKE.fullmatch(self.url)
        return match["host"].lower() if match else ""

    @property
    def authority(self) -> str:
        """``host[:port]`` as git prints it in credential prompts; empty for scp-like URLs."""
        if "://" not in self.url:
            return ""
        return urlsplit(self.url).netloc.rpartition("@")[2].lower()

    @property
    def credential_scope(self) -> str:
        """``scheme://host[:port]``, lower-case: the only place a credential may be offered."""
        return f"{self.transport}://{self.authority or self.hostname}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """Validate ``text`` and propose a library ID (``/owner/repo``, lower-case).

        Args:
            text: The URL a user typed.

        Returns:
            The URL and the library ID it proposes.

        Raises:
            InvalidRepositoryUrlError: The URL is not one ExactDocs accepts, or no library ID
                can be derived from it.
        """
        url = text.strip()
        if not url:
            raise InvalidRepositoryUrlError(UrlProblem.EMPTY)
        if url.startswith("-") or any(c.isspace() or not c.isprintable() for c in url):
            raise InvalidRepositoryUrlError(UrlProblem.OPTION)
        if "?" in url or "#" in url:
            raise InvalidRepositoryUrlError(UrlProblem.QUERY)
        if "://" in url:
            host, segments, top_level_owner = _split_url(url)
        elif match := _SCP_LIKE.fullmatch(url):
            host = match["host"].lower()
            segments, top_level_owner = _segments(match["path"]), True
        else:
            raise InvalidRepositoryUrlError(UrlProblem.FORM)
        # Hosts with nested groups (GitLab) key a library by its top-level group; plain HTTP
        # and file URLs (fixture servers, local mirrors) have no such convention: last two.
        if len(segments) < _ID_SEGMENTS:
            raise InvalidRepositoryUrlError(UrlProblem.NO_OWNER)
        if host in FLAT_HOSTS and len(segments) != _ID_SEGMENTS:
            raise InvalidRepositoryUrlError(UrlProblem.PAGE_URL)
        owner, name = (segments[0] if top_level_owner else segments[-2]), segments[-1]
        name = _GIT_SUFFIX.sub("", name)
        return cls(
            url=url,
            host_kind=_host_kind(host),
            library_id=ProposedId(f"/{_id_segment(owner)}/{_id_segment(name)}"),
        )


def _split_url(url: str) -> tuple[str, list[str], bool]:
    """Check a ``scheme://`` URL; return its host, path segments and the owner-group flag.

    Args:
        url: The URL, trimmed.

    Returns:
        The lower-case host, the path segments, and whether the first segment is the owner
        (``https`` and ``ssh``: a host with nested groups keys a library by its top group).

    Raises:
        InvalidRepositoryUrlError: The URL is malformed, has another scheme, an invalid host or
            credentials.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise InvalidRepositoryUrlError(UrlProblem.MALFORMED) from None
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    if scheme not in _SCHEMES:
        raise InvalidRepositoryUrlError(UrlProblem.SCHEME)
    if scheme == "file":
        if host not in {"", "localhost"} or port is not None or "@" in parts.netloc:
            raise InvalidRepositoryUrlError(UrlProblem.FILE_HOST)
    else:
        if not _is_host(host):
            raise InvalidRepositoryUrlError(UrlProblem.HOST)
        userinfo = parts.netloc.rpartition("@")[0] if "@" in parts.netloc else None
        if userinfo is not None and (scheme != "ssh" or not _SSH_USER.fullmatch(userinfo)):
            raise InvalidRepositoryUrlError(UrlProblem.CREDENTIALS)
    return host, _segments(parts.path), scheme in {"https", "ssh"}


def _segments(path: str) -> list[str]:
    """Split a URL's path into its segments, unquoted.

    Args:
        path: The URL's path.

    Returns:
        The non-empty segments.

    Raises:
        InvalidRepositoryUrlError: A segment is ``.`` or ``..`` or holds an encoded ``/``.
    """
    segments = [unquote(s) for s in path.split("/") if s]
    if any(s in {".", ".."} or "/" in s for s in segments):
        raise InvalidRepositoryUrlError(UrlProblem.DOTS)
    return segments


def _is_host(host: str) -> bool:
    """Tell whether ``host`` is a valid host name or an IP address.

    Args:
        host: The lower-case host.

    Returns:
        True when it is.
    """
    if _HOST.fullmatch(host):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _host_kind(host: str) -> RepositoryHost:
    """Tell which hosting service a host is.

    Args:
        host: The lower-case host.

    Returns:
        Its service; ``git`` for any host ExactDocs does not know.
    """
    return RepositoryHost(KNOWN_HOSTS.get(host, RepositoryHost.GIT))


def _id_segment(raw: str) -> str:
    """Shape a path segment like a library ID segment (letters, digits, ``._-``), lower-case.

    Args:
        raw: A path segment.

    Returns:
        The library ID segment.

    Raises:
        InvalidRepositoryUrlError: Nothing usable is left of it.
    """
    segment = _UNSAFE_ID_CHARS.sub("-", raw).strip("-").lower()
    if not segment or set(segment) == {"."}:
        raise InvalidRepositoryUrlError(UrlProblem.NO_ID)
    return segment


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessToken:
    """An HTTPS token (a personal or project access token); ``username`` is what the host expects.

    GitHub and GitLab accept any user name next to a token; Bitbucket repository tokens want
    ``x-token-auth``. ``repr`` never shows the token.
    """

    token: str = field(repr=False)
    """The token, on one line."""
    username: str = "x-access-token"
    """The user name sent with the token."""

    def __post_init__(self) -> None:
        """Refuse a token that is empty, not one line or too long, or a bad user name.

        Raises:
            InvalidCredentialError: The token or the user name cannot be used.
        """
        if not self.token:
            raise InvalidCredentialError(CredentialProblem.EMPTY)
        if (
            len(self.token) > _MAX_TOKEN
            or not self.token.isprintable()
            or self.token != self.token.strip()
        ):
            raise InvalidCredentialError(CredentialProblem.ONE_LINE)
        if not _TOKEN_USER.fullmatch(self.username):
            raise InvalidCredentialError(CredentialProblem.USERNAME)


@dataclass(frozen=True, slots=True, kw_only=True)
class DeployKey:
    """An SSH private key without a passphrase, kept in the OpenSSH or PEM text format."""

    private_key: str = field(repr=False)
    """The key, armour lines included; normalized to ``\\n`` line ends and a final newline."""

    def __post_init__(self) -> None:
        """Normalize the key; refuse one that is empty, too long, flattened or encrypted.

        Raises:
            InvalidCredentialError: The key cannot be used.
        """
        key = self.private_key.replace("\r\n", "\n").strip()
        if not key:
            raise InvalidCredentialError(CredentialProblem.EMPTY)
        if len(key) > _MAX_KEY:
            raise InvalidCredentialError(CredentialProblem.TOO_LONG)
        lines = key.split("\n")
        if len(lines) == 1 and key.startswith("-----BEGIN ") and "-----END " in key:
            # A password box or a JSON client flattened it. Re-wrapping a secret here would
            # guess at its layout; saying why is safer, and the web form re-wraps it itself.
            raise InvalidCredentialError(CredentialProblem.ONE_LINE_KEY)
        if (
            not (lines[0].startswith("-----BEGIN ") and lines[0].endswith("PRIVATE KEY-----"))
            or not lines[-1].startswith("-----END ")
            or any(not line.isprintable() for line in lines)
        ):
            raise InvalidCredentialError(CredentialProblem.KEY)
        if _has_passphrase(lines):
            raise InvalidCredentialError(CredentialProblem.ENCRYPTED_KEY)
        object.__setattr__(self, "private_key", key + "\n")  # ssh wants the final newline


def _has_passphrase(lines: Sequence[str]) -> bool:
    """Whether the key is encrypted: said in a PEM armour or header, or an OpenSSH cipher.

    ssh would only prompt for it (and, with no terminal, fail as if the repository refused the
    key), so it is refused here with words that say why. An OpenSSH key names its cipher right
    after the magic: ``none`` when there is no passphrase.

    Args:
        lines: The key's lines, armour included.

    Returns:
        True when the key needs a passphrase.
    """
    if "ENCRYPTED" in lines[0] or any(line.startswith("Proc-Type: 4,ENCRYPTED") for line in lines):
        return True
    if "OPENSSH" not in lines[0]:
        return False
    try:
        blob = base64.b64decode("".join(lines[1:-1]), validate=True)
    except ValueError:
        return False
    if not blob.startswith(OPENSSH_MAGIC):
        return False
    rest = blob[len(OPENSSH_MAGIC) :]
    size = int.from_bytes(rest[:4])
    return rest[4 : 4 + size] not in {b"none", b""}


Credential = AccessToken | DeployKey


def check_credential_fits(repository: RepositoryUrl, credential: Credential) -> None:
    """Refuse a credential the repository's transport cannot carry safely.

    A token over plain ``http://`` would cross the network in the clear, so only localhost (a
    local mirror, the test servers) may use it. A deploy key needs an SSH URL.

    Args:
        repository: The repository.
        credential: The token or deploy key.

    Raises:
        InvalidCredentialError: A token without https (or http to localhost), or a deploy key
            without SSH.
    """
    transport = repository.transport
    if isinstance(credential, AccessToken):
        if transport == "https" or (transport == "http" and repository.hostname in _LOOPBACK):
            return
        raise InvalidCredentialError(CredentialProblem.HTTPS_ONLY)
    if transport != "ssh":
        raise InvalidCredentialError(CredentialProblem.SSH_ONLY)


def dump_credential(library: str, scope: str, credential: Credential) -> str:
    """Serialize a credential for storage (always encrypted before it is written).

    The library and the ``credential_scope`` it was given for are part of the text, so it opens
    for that library and that host only.

    Args:
        library: The library ID.
        scope: The repository's ``credential_scope``.
        credential: The token or deploy key.

    Returns:
        JSON text holding the secret.
    """
    if isinstance(credential, AccessToken):
        body = {"kind": "token", "token": credential.token, "username": credential.username}
    else:
        body = {"kind": "ssh_key", "private_key": credential.private_key}
    return json.dumps({"library": library, "scope": scope, **body})


def load_credential(library: str, scope: str, text: str) -> Credential:
    """Inverse of ``dump_credential``; ``ValueError`` when it is for another library or host.

    Args:
        library: The library ID it must be for.
        scope: The ``credential_scope`` it must be for.
        text: What ``dump_credential`` returned.

    Returns:
        The credential.

    Raises:
        ValueError: It was stored for another library or scope.
    """
    body = json.loads(text)
    if body["library"] != library or body["scope"] != scope:
        raise ValueError(library)  # a copied row, or the library now lives on another host
    if body["kind"] == "token":
        return AccessToken(token=body["token"], username=body["username"])
    return DeployKey(private_key=body["private_key"])


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteRef:
    """One ref a remote advertises: ``refs/heads/main`` or ``refs/tags/v1.4.0`` and its object."""

    name: str
    """The full ref name, e.g. ``refs/heads/main``; ``^{}`` ends a peeled annotated tag."""
    sha: str
    """The object it points at."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteRefs:
    """What ``git ls-remote`` saw: the branch ``HEAD`` points at (``None`` if unknown) and refs."""

    default_branch: str | None
    """The branch ``HEAD`` points at."""
    refs: tuple[RemoteRef, ...] = ()
    """Every ref listed, in git's order."""


def branch_name(raw: str) -> str | None:
    """Return ``raw`` if it is a branch name git would accept (``git check-ref-format``), else None.

    The name comes from a remote, so it is also capped and checked for control characters
    before it is stored or shown.

    Args:
        raw: A branch name without ``refs/heads/``.

    Returns:
        ``raw``, or None.
    """
    parts = raw.split("/")
    ok = (
        0 < len(raw) <= _MAX_BRANCH
        and not _BAD_REF_CHARS.search(raw)
        and all(p and not p.startswith(".") and not p.endswith(".lock") for p in parts)
        and ".." not in raw
        and "@{" not in raw
        and raw != "@"  # git refuses the single character @
        and not raw.startswith("-")
        and not raw.endswith((".", "/"))
        and raw.isprintable()
    )
    return raw if ok else None


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkingConfig:
    """How articles are cut (per library, LIB-09).

    ``split_depth`` is the deepest heading level that starts a chunk (``h1``...``h6``). A section
    longer than ``max_chars`` is cut again at its deeper headings, and sections shorter than
    ``min_chars`` are merged with the next one (the last with the one before) while the merged
    chunk stays within ``max_chars``: never inside a block, never with the text before the first
    heading. ``max_section_chars`` bounds every chunk the same way, and a section still longer
    than it is split at its top-level blocks (#141): never inside a code fence, table or list, so
    a single block longer than it stays whole. ``None`` means no upper bound. ``chunker`` is one
    of ``CHUNKERS``. A ``max_chars`` or ``min_chars`` above ``max_section_chars`` has no effect:
    the settings API refuses one (``refuse_sizes_above_section_bound``), but a config stored
    before the bound existed still loads.
    """

    split_depth: int = MAX_HEADING_LEVEL
    """The deepest heading level that starts a chunk."""
    min_chars: int = 0
    """Shorter chunks are merged; 0 merges none."""
    max_chars: int | None = None
    """Longer chunks are cut again at deeper headings; ``None``: no bound."""
    max_section_chars: int | None = DEFAULT_MAX_SECTION_CHARS
    """Longer chunks are cut again at deeper headings, then at top-level blocks; ``None``: no
    bound."""
    chunker: str = DEFAULT_CHUNKER
    """Which chunker cuts."""

    def __post_init__(self) -> None:
        """Refuse settings out of range or a chunker that is not provided.

        Raises:
            InvalidChunkingConfigError: A setting is out of range, ``max_chars`` is below
                ``min_chars`` or the chunker is unknown.
        """
        if not 1 <= self.split_depth <= MAX_HEADING_LEVEL:
            raise InvalidChunkingConfigError
        if not 0 <= self.min_chars <= MAX_CHUNK_CHARS:
            reason = f"min_chars must be between 0 and {MAX_CHUNK_CHARS}"
            raise InvalidChunkingConfigError(reason)
        if self.max_chars is not None and not 1 <= self.max_chars <= MAX_CHUNK_CHARS:
            reason = f"max_chars must be between 1 and {MAX_CHUNK_CHARS}"
            raise InvalidChunkingConfigError(reason)
        if self.max_section_chars is not None and not (
            1 <= self.max_section_chars <= MAX_CHUNK_CHARS
        ):
            reason = f"max_section_chars must be between 1 and {MAX_CHUNK_CHARS}"
            raise InvalidChunkingConfigError(reason)
        if self.max_chars is not None and self.max_chars < self.min_chars:
            reason = "max_chars must not be smaller than min_chars"
            raise InvalidChunkingConfigError(reason)
        if self.chunker not in CHUNKERS:
            reason = f"chunker must be one of {', '.join(sorted(CHUNKERS))}"
            raise InvalidChunkingConfigError(reason)

    def refuse_sizes_above_section_bound(self) -> None:
        """Refuse a ``max_chars`` or ``min_chars`` that ``max_section_chars`` would make void.

        No chunk is longer than ``max_section_chars`` (but a single block), so a bigger
        ``max_chars`` never cuts and a bigger ``min_chars`` never merges. Only new settings are
        checked: a config stored before the bound existed is not refused when it is read.

        Raises:
            InvalidChunkingConfigError: ``max_chars`` or ``min_chars`` is above
                ``max_section_chars``.
        """
        bound = self.max_section_chars
        if bound is None:
            return
        for name, value in (("max_chars", self.max_chars), ("min_chars", self.min_chars)):
            if value is not None and value > bound:
                reason = (
                    f"{name} must be at most {bound}: no chunk is longer than that, unless a "
                    "single block is"
                )
                raise InvalidChunkingConfigError(reason)


def chunking_config_hash(config: ChunkingConfig, engine: str = "") -> str:
    """Return the hash that keys chunk sets: the effective config plus both version constants.

    ``engine`` names the library an adapter cuts with and its version, so upgrading it re-chunks.

    A fix to the parser or the chunker changes it, so stored articles are re-chunked instead of
    reusing a chunk set made by older code. The size bounds and the chunker are added only when
    they differ from the defaults, so the chunk sets stored before they existed stay valid.
    A config that can merge headings into a chunk (a split level above h6, or ``min_chars``) also
    names ``MERGED_HEADINGS_VERSION``: its chunks record those headings, and a set cut before
    they did is cut again instead of reused. The others cut at every heading (``max_chars`` only
    cuts whole sections), so their chunk sets already tell every heading and keep their hash.
    ``max_section_chars`` is named whenever it bounds the chunks (#141), so the default config's
    hash changed with it and changes again with ``DEFAULT_MAX_SECTION_CHARS``; a config without
    it cuts as before #141 and keeps the hash it had.

    Args:
        config: The chunking settings.
        engine: The cutting library and its version.

    Returns:
        32 hexadecimal characters.
    """
    fields: list[object] = [PARSER_VERSION, CHUNKER_VERSION, config.split_depth, engine]
    extra = (config.min_chars, config.max_chars, config.chunker)
    if extra != (0, None, DEFAULT_CHUNKER):
        fields.extend(extra)
    if config.split_depth < MAX_HEADING_LEVEL or config.min_chars:  # it can merge headings
        fields.append(f"headings-{MERGED_HEADINGS_VERSION}")
    if config.max_section_chars is not None:
        fields.append(f"sections-{config.max_section_chars}")
    payload = json.dumps(fields, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkHeading:
    """One heading a chunk holds, as the chunker found it."""

    heading_path: tuple[str, ...]
    """The heading and every heading above it, whatever the split level."""
    anchor: str
    """The heading's own GitHub-style anchor in the article."""
    starts_chunk: bool
    """True for the heading the chunk starts with (and is named after); false for one merged in."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ArticleChunk:
    """One section of an article. The contents of all chunks, joined, are the article body."""

    heading_path: tuple[str, ...]
    """Empty for the text before the first heading."""
    occurrence_index: int
    """Among sections with the same heading path: 0, 1, ...; every part of a split section has
    its section's."""
    part: int = 0
    """Among the parts of a section split at its blocks (#141): 0, 1, ...; 0 for a section that
    is not split."""
    position: int
    """0-based index in the article."""
    content: str
    """The chunk's Markdown, verbatim."""
    content_hash: str
    """SHA-256 of ``content``, hexadecimal."""
    anchor: str
    """GitHub-style, unique in the article; empty before the first heading."""
    code_languages: tuple[str, ...] = ()
    """Languages of the fenced code blocks in it, in order of first appearance."""
    headings: tuple[ChunkHeading, ...] | None = None
    """Every heading the chunk holds, in order; ``None`` when not recorded (a chunk set stored
    before heading records existed)."""


class RefKind(StrEnum):
    """What a requested ref turned out to be."""

    TAG = "tag"
    BRANCH = "branch"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedRef:
    """A ref pinned to a commit. For a commit, ``name`` is the full SHA."""

    name: str
    """The tag or branch name, or the full commit SHA."""
    kind: RefKind
    """What the ref is."""
    commit_sha: str
    """The full SHA of the commit it names."""


def ref_tips(refs: RemoteRefs) -> tuple[ResolvedRef, ...]:
    """List the branches then the tags a remote advertises, each sorted, with commit SHAs.

    An annotated tag points at a tag object; its ``^{}`` line carries the commit, which is used.

    Args:
        refs: What the remote advertised.

    Returns:
        The branches, then the tags whose names git accepts.
    """
    branches: dict[str, str] = {}
    tags: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for ref in refs.refs:
        if ref.name.startswith(HEADS) and (name := branch_name(ref.name.removeprefix(HEADS))):
            branches[name] = ref.sha
        elif ref.name.startswith(TAGS):
            tag = ref.name.removeprefix(TAGS)
            if tag.endswith(PEELED):
                peeled[tag.removesuffix(PEELED)] = ref.sha
            else:
                tags[tag] = ref.sha
    return (
        *(
            ResolvedRef(name=n, kind=RefKind.BRANCH, commit_sha=s)
            for n, s in sorted(branches.items())
        ),
        *(
            ResolvedRef(name=n, kind=RefKind.TAG, commit_sha=peeled.get(n, s))
            for n, s in sorted(tags.items())
            if branch_name(n)
        ),
    )


def resolve_ref(refs: RemoteRefs, requested: str | None) -> ResolvedRef:
    """Pin ``requested`` to a commit using only what the remote advertises.

    No ref means the default branch. A name is a tag (preferred) or a branch; otherwise a full
    or short (7+ characters) commit SHA that is the tip of some advertised ref.
    ponytail: a commit that is not a ref tip cannot be seen by ``ls-remote``, so it is refused;
    verify it with a fetch (E3-03) if importing arbitrary commits matters.

    Args:
        refs: What the remote advertised.
        requested: A tag, a branch, a full or short commit SHA; ``None`` for the default branch.

    Returns:
        The ref, its kind and its commit.

    Raises:
        UnknownRefError: Nothing advertised matches (or there is no default branch).
        AmbiguousRefError: A short SHA starts more than one advertised commit.
    """
    tips = ref_tips(refs)
    if requested is None:
        default = next(
            (t for t in tips if t.kind is RefKind.BRANCH and t.name == refs.default_branch), None
        )
        if default is None:
            raise UnknownRefError(None)
        return default
    named = {t.kind: t for t in tips if t.name == requested}
    if found := named.get(RefKind.TAG) or named.get(RefKind.BRANCH):
        return found
    prefix = requested.lower()
    commits = {
        t.commit_sha
        for t in tips
        if _SHA_PREFIX.fullmatch(prefix) and t.commit_sha.startswith(prefix)
    }
    if len(commits) > 1:
        raise AmbiguousRefError(prefix)
    if not commits:
        raise UnknownRefError(requested)
    (sha,) = commits
    return ResolvedRef(name=sha, kind=RefKind.COMMIT, commit_sha=sha)


type _Token = str | tuple[str, ...]  # text, or the alternatives of a `{a,b}`
type _Segment = tuple[_Token, ...] | None  # None: `**`, any number of folders


@dataclass(frozen=True, slots=True, kw_only=True)
class _Glob:
    """A parsed path pattern."""

    segments: tuple[_Segment, ...]
    """One per folder level; ``None`` for ``**``."""
    folder: bool
    """A plain name also selects everything below it."""


def _segment(text: str) -> _Segment:
    """Split one path segment into tokens; ``**`` alone is a globstar.

    Args:
        text: One segment of a pattern.

    Returns:
        Its tokens, or ``None`` for ``**``.

    Raises:
        InvalidPathPatternError: A ``{`` has no ``}``.
    """
    if text == "**":
        return None
    tokens: list[_Token] = []
    literal = ""
    i = 0
    while i < len(text):
        char = text[i]
        if char in GLOB_CHARS:
            if literal:
                tokens.append(literal)
                literal = ""
            if char == "{":
                end = text.find("}", i)
                if end < 0:
                    raise InvalidPathPatternError(PatternProblem.BRACE)
                tokens.append(("{", *text[i + 1 : end].split(",")))
                i = end
            elif not (char == "*" and tokens and tokens[-1] == (ANY,)):  # `**` in a name is `*`
                tokens.append((char,))
        else:
            literal += char
        i += 1
    if literal:
        tokens.append(literal)
    return tuple(tokens)


@lru_cache(maxsize=512)
def _glob(pattern: str) -> _Glob:
    """Parse a cleaned pattern. Matching never backtracks: see ``_matches``.

    Args:
        pattern: A pattern ``_clean_pattern`` accepted.

    Returns:
        The parsed pattern.
    """
    folder = not GLOB_CHARS & set(pattern)
    parts = pattern.split("/")
    if not parts[-1]:  # `docs/` is `docs/**`
        parts[-1] = "**"
    segments: list[_Segment] = []
    for part in parts:
        segment = _segment(part)
        if segment is None and segments and segments[-1] is None:
            continue  # `**/**` is `**`
        segments.append(segment)
    return _Glob(segments=tuple(segments), folder=folder)


def _name_matches(tokens: tuple[_Token, ...], name: str) -> bool:
    """Match one segment: the set of reachable positions, so the time is tokens x length.

    Args:
        tokens: A pattern segment's tokens.
        name: One name of a path.

    Returns:
        True when the whole name matches.
    """
    if len(name) > _MAX_SEGMENT:
        return False
    reach = {0}
    for token in tokens:
        if isinstance(token, str):
            reach = {p + len(token) for p in reach if name.startswith(token, p)}
        elif token == (ANY,):
            reach = set(range(min(reach), len(name) + 1)) if reach else set()
        elif token == (ONE,):
            reach = {p + 1 for p in reach if p < len(name)}
        else:
            reach = {p + len(a) for p in reach for a in token[1:] if name.startswith(a, p)}
        if not reach:
            return False
    return len(name) in reach


def _matches(glob: _Glob, path: str) -> bool:
    """Match ``path`` folder by folder, keeping the set of positions reached so far.

    ``**`` reaches every position from the first one on. Linear in pattern segments times path
    segments, whatever the pattern (a regex would backtrack on stacked wildcards).

    Args:
        glob: The parsed pattern.
        path: A repository path.

    Returns:
        True when the pattern selects the path.
    """
    if len(path) > _MAX_PATH:
        return False
    names = path.split("/")
    reach = {0}
    for segment in glob.segments:
        if segment is None:
            reach = set(range(min(reach), len(names) + 1))
        else:
            reach = {i + 1 for i in reach if i < len(names) and _name_matches(segment, names[i])}
        if not reach:
            return False
    return len(names) in reach or (glob.folder and bool(reach))


def _clean_pattern(raw: str) -> str:
    """Trim a pattern and refuse what cannot be one.

    Args:
        raw: A pattern as given.

    Returns:
        The pattern without surrounding blanks or a leading ``./``.

    Raises:
        InvalidPathPatternError: It is empty, too long, absolute, has ``.``/``..`` parts, a
            backslash or a control character.
    """
    pattern = raw.strip().removeprefix("./")
    if not pattern or len(pattern) > _MAX_PATTERN or not pattern.isprintable():
        raise InvalidPathPatternError(PatternProblem.EMPTY)
    parts = pattern.split("/")
    if (
        pattern.startswith("/")
        or "\\" in pattern
        or any(p in {"", ".", ".."} for p in parts[:-1])
        or parts[-1] in {".", ".."}
    ):
        raise InvalidPathPatternError(PatternProblem.PATH)
    _glob(pattern)  # fails on an unclosed brace
    return pattern


@dataclass(frozen=True, slots=True, kw_only=True)
class PathSelection:
    """Which repository files are articles: ``include`` minus ``exclude``, only ``.md``/``.mdx``.

    Patterns are repo-relative with ``/`` (an absolute path, ``..`` or a backslash is refused) and
    **case-sensitive**: ``Docs/`` does not match ``docs/``. Only the ``.md``/``.mdx`` suffix is
    case-insensitive. ``docs/`` is a folder and all below it, ``docs`` a file or a folder, ``*``
    and ``?`` stay within one name, ``**`` as a whole name crosses folders, ``{a,b}`` is a choice
    (not nestable; ``{}`` matches nothing; a lone ``}`` is a plain character). No ``include``
    means every ``.md``/``.mdx`` file. An exclusion always wins.
    """

    include: tuple[str, ...] = ()
    """Patterns of what to import; empty: every ``.md``/``.mdx`` file."""
    exclude: tuple[str, ...] = ()
    """Patterns of what to leave out; they win over ``include``."""

    @classmethod
    def of(cls, include: Sequence[str] = (), exclude: Sequence[str] = ()) -> Self:
        """Validate and normalise the patterns (blank, duplicate-free, bounded).

        Args:
            include: Patterns of what to import.
            exclude: Patterns of what to leave out.

        Returns:
            The selection.

        Raises:
            InvalidPathPatternError: There are too many patterns.
        """
        if len(include) + len(exclude) > _MAX_PATTERNS:
            raise InvalidPathPatternError(PatternProblem.TOO_MANY)
        return cls(
            include=tuple(dict.fromkeys(map(_clean_pattern, include))),
            exclude=tuple(dict.fromkeys(map(_clean_pattern, exclude))),
        )

    def selects(self, path: str) -> bool:
        """Tell whether the file at this repo-relative path is an article.

        Args:
            path: A repository path.

        Returns:
            True for a ``.md``/``.mdx`` file the patterns select.
        """
        if not path.lower().endswith(ARTICLE_SUFFIXES):
            return False
        if any(_matches(_glob(p), path) for p in self.exclude):
            return False
        return not self.include or any(_matches(_glob(p), path) for p in self.include)


@dataclass(frozen=True, slots=True, kw_only=True)
class TagRule:
    """Articles whose path matches the glob get the tag (``docs/api/** -> api``).

    The glob follows the rules of ``PathSelection`` (and so only ``.md``/``.mdx`` files match).
    """

    selection: PathSelection
    """The glob, as a selection of one include pattern."""
    tag: str
    """The tag, normalized."""

    @classmethod
    def of(cls, pattern: str, tag: str) -> Self:
        """Validate the glob and normalize the tag; a tag that cannot be one is refused.

        Args:
            pattern: A path pattern.
            tag: The tag as given.

        Returns:
            The rule.

        Raises:
            InvalidTagError: The tag cannot be one.
        """
        if (normalized := normalize_tag(tag)) is None:
            raise InvalidTagError(TagProblem.INVALID)
        return cls(selection=PathSelection.of([pattern]), tag=normalized)

    @classmethod
    def many(cls, pairs: Sequence[tuple[str, str]]) -> tuple[Self, ...]:
        """Build the rules of a library: bounded and duplicate-free.

        Args:
            pairs: ``(pattern, tag)`` of each rule.

        Returns:
            The rules, in order, without duplicates.

        Raises:
            InvalidTagError: There are too many rules.
        """
        if len(pairs) > MAX_TAG_RULES:
            raise InvalidTagError(TagProblem.TOO_MANY)
        return tuple(dict.fromkeys(starmap(cls.of, pairs)))

    @property
    def pattern(self) -> str:
        """The glob, as cleaned."""
        return self.selection.include[0]


def article_tags(path: str, declared: Sequence[str], rules: Sequence[TagRule]) -> tuple[str, ...]:
    """Combine the tags of the rules matching ``path`` with the front-matter ones.

    Rule tags come first (they are the library owner's), then ``declared`` (already normalized by
    ``parse_article``); duplicates go; at most ``MAX_TAGS`` are kept.

    Args:
        path: The article's repository path.
        declared: Its front-matter tags.
        rules: The library's tag rules.

    Returns:
        The article's imported tags.
    """
    return imported_tags(path, declared, rules).tags


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedTags:
    """An article's imported tags, and which of them come from the front matter and path rules.

    A tag both give is in both. The catalog keeps the sources so readers can tell them apart.
    """

    tags: tuple[str, ...]
    """Every imported tag: path rules first, then front matter, at most ``MAX_TAGS``."""
    front_matter: tuple[str, ...] = ()
    """Declared in the front matter, normalized."""
    rules: tuple[str, ...] = ()
    """Given by the library's tag rules that match the article's path."""


def imported_tags(path: str, declared: Sequence[str], rules: Sequence[TagRule]) -> ImportedTags:
    """Combine the tags of the rules matching ``path`` with the front-matter ones, keeping both.

    See ``article_tags`` for how they combine.

    Args:
        path: The article's repository path.
        declared: Its front-matter tags.
        rules: The library's tag rules.

    Returns:
        The article's imported tags and their sources.
    """
    ruled = tuple(dict.fromkeys(rule.tag for rule in rules if rule.selection.selects(path)))
    front_matter = tuple(dict.fromkeys(declared))
    return ImportedTags(
        tags=tuple(dict.fromkeys((*ruled, *front_matter)))[:MAX_TAGS],
        front_matter=front_matter,
        rules=ruled,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviousVersion:
    """An older tag a ``context7.json`` offers for import, with its optional display title."""

    tag: str
    """The tag, as the file gives it."""
    title: str = ""
    """Its display title, flattened to one line; empty when the file gives none."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Context7Config:
    """What a repository's ``context7.json`` says, validated and ready to apply.

    ``selection`` is ``folders`` / ``excludeFolders`` / ``excludeFiles`` as ``PathSelection``
    patterns (see ``context7_selection``), or ``None`` when the file names none of them. All
    text is untrusted repository text: title and description are flattened and cut like a
    README's, every rule is one printable line.
    """

    project_title: str | None = None
    """Its ``projectTitle``, cut like a README's title."""
    description: str | None = None
    """Its ``description``, cut like a README's description."""
    folders: tuple[str, ...] = ()
    """Its ``folders``, as given."""
    exclude_folders: tuple[str, ...] = ()
    """Its ``excludeFolders``, as given."""
    exclude_files: tuple[str, ...] = ()
    """Its ``excludeFiles``, as given."""
    rules: tuple[str, ...] = ()
    """Its ``rules``, distinct, each one line."""
    previous_versions: tuple[PreviousVersion, ...] = ()
    """Its importable ``previousVersions``, one per tag."""
    selection: PathSelection | None = None
    """The folders and excludes as patterns; ``None`` when the file names none."""
    notes: tuple[str, ...] = ()
    """What was left out of an otherwise usable file (``previousVersions`` entries), and why."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FetchedFile:
    """One file of a commit read on its own: its bytes, nothing (absent), or why it was not read."""

    data: bytes | None = None
    """The file's bytes; ``None`` when it is absent or was not read."""
    problem: str | None = None
    """Why it was not read; ``None`` when it was, or is absent."""
    code: ProblemCode | None = None
    """The problem's kind, when the reader names one (``TOO_LARGE``, ``NOT_A_FILE``)."""


def parse_context7(data: bytes) -> Context7Config:
    """Validate the bytes of a ``context7.json``; ``InvalidContext7Error`` says why it is unusable.

    Only the keys ExactDocs uses are read (``projectTitle``, ``description``, ``folders``,
    ``excludeFolders``, ``excludeFiles``, ``rules``, ``previousVersions``); any other key
    (``$schema``, ``url``, ...) is ignored. A known key of the wrong type, too many rules or
    versions, or a path ExactDocs would refuse makes the whole file unusable: half-applying a
    file would import something nobody asked for. A ``previousVersions`` entry that cannot be
    imported (no tag, or one git would not take as a ref name) only offers nothing: it is left
    out and named in ``notes``.

    Args:
        data: The file's bytes.

    Returns:
        The file's settings.

    Raises:
        InvalidContext7Error: The file is too big, not UTF-8 JSON, not an object, has too many
            or too long rules, or names a path ExactDocs refuses.
    """
    if len(data) > CONTEXT7_MAX_BYTES:
        reason = f"it is larger than {CONTEXT7_MAX_BYTES} bytes"
        raise InvalidContext7Error(reason)
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        reason = "it is not UTF-8"
        raise InvalidContext7Error(reason) from None
    except ValueError, RecursionError:
        reason = "it is not valid JSON"
        raise InvalidContext7Error(reason) from None
    if not isinstance(document, dict):
        reason = "it is not a JSON object"
        raise InvalidContext7Error(reason)
    folders = _c7_strings(document, "folders")
    exclude_folders = _c7_strings(document, "excludeFolders")
    exclude_files = _c7_strings(document, "excludeFiles")
    lines = (_c7_line(r, "rules") for r in _c7_strings(document, "rules"))
    rules = tuple(dict.fromkeys(r for r in lines if r))  # the limit counts distinct rules
    if len(rules) > MAX_CONTEXT7_RULES or any(len(r) > MAX_CONTEXT7_RULE_CHARS for r in rules):
        message = (
            f"rules: at most {MAX_CONTEXT7_RULES} of at most {MAX_CONTEXT7_RULE_CHARS} characters"
        )
        raise InvalidContext7Error(message)
    try:
        selection = context7_selection(folders, exclude_folders, exclude_files)
    except InvalidPathPatternError as error:
        reason = f"folders or excludes: {error}"
        raise InvalidContext7Error(reason) from None
    title = _c7_text(document, "projectTitle")
    description = _c7_text(document, "description")
    versions, notes = _c7_previous_versions(document.get("previousVersions"))
    return Context7Config(
        project_title=title[:README_TITLE_MAX].rstrip() if title else None,
        description=description[:README_DESCRIPTION_MAX].rstrip() if description else None,
        folders=folders,
        exclude_folders=exclude_folders,
        exclude_files=exclude_files,
        rules=rules,
        previous_versions=versions,
        selection=selection,
        notes=notes,
    )


def context7_selection(
    folders: Sequence[str], exclude_folders: Sequence[str], exclude_files: Sequence[str]
) -> PathSelection | None:
    """Translate context7's folder and file lists into a ``PathSelection``; ``None`` if all empty.

    As context7 reads them: a folder is a repository path and everything below it (``.`` is the
    whole repository). An excluded folder or file given by its bare name (``archive``,
    ``CHANGELOG.md``) is excluded wherever it is; one with a ``/`` (``./docs/internal``) only at
    that path. Entries with glob characters are taken as ``PathSelection`` patterns.

    Args:
        folders: The ``folders`` to import.
        exclude_folders: The ``excludeFolders``.
        exclude_files: The ``excludeFiles``.

    Returns:
        The selection.
    """
    if not (folders or exclude_folders or exclude_files):
        return None
    include = [] if any(_c7_root(f) for f in folders) else [_c7_folder(f) for f in folders]
    exclude = [_c7_exclude(f, folder=True) for f in exclude_folders] + [
        _c7_exclude(f, folder=False) for f in exclude_files
    ]
    return PathSelection.of(include, exclude)


def _c7_path(entry: str) -> tuple[str, bool]:
    """Strip ``./`` and ``/`` at the start (both mean the repository root) and ``/`` at the end.

    Also tell whether the entry is anchored at a path (it started at the root or has a ``/``).

    Args:
        entry: A folder or file entry.

    Returns:
        The cleaned entry, and whether it is anchored.
    """
    stripped = entry.strip()
    cleaned = stripped.removeprefix("./").lstrip("/").rstrip("/")
    return cleaned, stripped.startswith(("./", "/")) or "/" in cleaned


def _c7_root(folder: str) -> bool:
    """Tell whether a ``folders`` entry is the repository root.

    Args:
        folder: The entry.

    Returns:
        True for ``.``, ``./`` or ``/``.
    """
    return _c7_path(folder)[0] in {"", "."}


def _c7_folder(folder: str) -> str:
    """Turn a ``folders`` entry into an include pattern.

    Args:
        folder: The entry.

    Returns:
        The folder and everything below it, or the entry itself when it is a glob.
    """
    cleaned, _ = _c7_path(folder)
    return cleaned if GLOB_CHARS & set(cleaned) else f"{cleaned}/"


def _c7_exclude(entry: str, *, folder: bool) -> str:
    """Turn an ``excludeFolders`` or ``excludeFiles`` entry into an exclude pattern.

    Args:
        entry: The entry.
        folder: Whether it is a folder (everything below it goes too).

    Returns:
        The pattern: anywhere for a bare name, at that path for an anchored one.
    """
    cleaned, anchored = _c7_path(entry)
    if GLOB_CHARS & set(cleaned):
        return cleaned
    suffix = "/" if folder else ""
    return f"{cleaned}{suffix}" if anchored else f"**/{cleaned}{suffix}"


def _c7_strings(document: dict[str, Any], key: str) -> tuple[str, ...]:
    """Read a list of strings.

    Args:
        document: The parsed file.
        key: The key.

    Returns:
        The strings; empty when the key is absent.

    Raises:
        InvalidContext7Error: The value is not a list of strings.
    """
    value = document.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        reason = f"{key} must be a list of strings"
        raise InvalidContext7Error(reason)
    return tuple(value)


def _c7_text(document: dict[str, Any], key: str) -> str | None:
    """Read a text, flattened to one line.

    Args:
        document: The parsed file.
        key: The key.

    Returns:
        The text; None when the key is absent or the text blank.

    Raises:
        InvalidContext7Error: The value is not a string.
    """
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        reason = f"{key} must be a string"
        raise InvalidContext7Error(reason)
    return _c7_line(value, key) or None


def _c7_line(value: str, key: str) -> str:
    """Flatten to one line; a control or invisible formatting character makes the file unusable.

    Args:
        value: A text of the file.
        key: Its key, for the error.

    Returns:
        The text on one line.

    Raises:
        InvalidContext7Error: It has a control or invisible character.
    """
    line = " ".join(value.split())
    if not line.isprintable():
        reason = f"{key} has control or invisible characters"
        raise InvalidContext7Error(reason)
    return line


def _c7_previous_versions(value: object) -> tuple[tuple[PreviousVersion, ...], tuple[str, ...]]:
    """Return the importable entries and a note for each one that is left out.

    Args:
        value: The ``previousVersions`` value.

    Returns:
        The entries, one per tag, and the notes.

    Raises:
        InvalidContext7Error: It is not a list, or too long.
    """
    if value is None:
        return (), ()
    if not isinstance(value, list) or len(value) > MAX_PREVIOUS_VERSIONS:
        reason = (
            'previousVersions must be a list of {"tag": ..., "title": ...} objects, '
            f"at most {MAX_PREVIOUS_VERSIONS}"
        )
        raise InvalidContext7Error(reason)
    found: dict[str, PreviousVersion] = {}
    notes: list[str] = []
    for entry in value:
        version = _c7_previous_version(entry)
        if isinstance(version, str):
            notes.append(f"previousVersions: an entry is left out: {version}")
        else:
            found.setdefault(version.tag, version)
    return tuple(found.values()), tuple(notes)


def _c7_previous_version(entry: object) -> PreviousVersion | str:
    """Validate one entry; a string says why it cannot be offered (never echoes control text).

    Args:
        entry: One ``previousVersions`` entry.

    Returns:
        The version, or why it is left out.
    """
    if not isinstance(entry, dict):
        return 'it is not a {"tag": ..., "title": ...} object'
    tag, title = entry.get("tag"), entry.get("title", "")
    if not isinstance(tag, str) or not isinstance(title, str):
        return "its tag and title must be strings"
    shown = " ".join(tag.split())[:MAX_PREVIOUS_VERSION_CHARS]
    if not shown.isprintable():
        return "its tag has control or invisible characters"
    title = " ".join(title.split())
    if (
        len(tag) > MAX_PREVIOUS_VERSION_CHARS
        or branch_name(tag) is None
        or len(title) > MAX_PREVIOUS_VERSION_CHARS
        or not title.isprintable()
    ):
        return f"{shown!r} is not a tag name git accepts, or its title is too long"
    return PreviousVersion(tag=tag, title=title)


@dataclass(frozen=True, slots=True, kw_only=True)
class NewLibrary:
    """What a library is created from: its repository, default branch and doc selection."""

    library_id: ProposedId
    """The library ID."""
    title: str
    """The display title until an import finds a better one."""
    source_url: str
    """The repository URL, as git is given it."""
    host: RepositoryHost
    """The hosting service, for source links."""
    default_branch: str | None
    """The branch ``HEAD`` points at, if any."""
    selection: PathSelection
    """Which files are articles."""
    tag_rules: tuple[TagRule, ...] = ()
    """Tags given to articles by path."""
    chunking: ChunkingConfig | None = None
    """How articles are cut into chunks; ``None``: the defaults."""


# ---------------------------------------------------------------- import


def _dropped_reason(count: int) -> str:
    """Say how many skipped files are not listed.

    Args:
        count: How many.

    Returns:
        The ``truncated`` marker's reason.
    """
    return f"{count} more skipped files are not listed"


def _dropped(marker: FileProblem) -> int:
    """Read how many skipped files a ``truncated`` marker counts.

    Args:
        marker: The marker.

    Returns:
        The count its reason starts with.
    """
    return int(marker.reason.split()[0])


"""Skipped files a job lists; the rest are only counted in a last entry."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportSource:
    """Where a library's articles come from and which of them are taken."""

    url: RepositoryUrl
    """The library's repository."""
    selection: PathSelection
    """Which files are articles."""
    tag_rules: tuple[TagRule, ...] = ()
    """Tags given to articles by path."""
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    """How articles are cut into chunks."""
    title: str = ""
    """The library's title as stored (a sources file compares its declared title with it)."""
    description: str = ""
    """The library's description as stored."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedArticle:
    """An article ready to publish: its text, metadata and chunks."""

    path: str
    """The file's repository path."""
    blob_sha: str
    """The file's git blob SHA."""
    title: str
    """The article's title."""
    tags: tuple[str, ...]
    """The tags its chunks carry: imported (path rules first, then front matter), and once the
    catalog has the article, the manual ones too."""
    imported: ImportedTags
    """The imported tags, and which come from the front matter and which from path rules."""
    front_matter: dict[str, Any]
    """The front matter as loaded."""
    content: str
    """The body, verbatim (invisible characters removed)."""
    chunks: tuple[ArticleChunk, ...]
    """The body's chunks, in order."""


def sniff_image(data: bytes) -> str | None:
    """Name the allowed image type by the content (never by the file name), else ``None``.

    PNG, JPEG, GIF, WebP and SVG. An SVG is a document whose root element is ``<svg``; one that
    declares entities is refused (nothing here parses it, but a browser would expand them).

    Args:
        data: The file's bytes.

    Returns:
        The media type, e.g. ``image/png``, or ``None``.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # XML is case-sensitive: `<!entity` declares nothing, so only the exact spelling is refused.
    if _SVG.match(data[:4096]) and b"<!ENTITY" not in data:
        return "image/svg+xml"
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedImage:
    """An image an article references: its repository path, git blob SHA, sniffed type, bytes."""

    path: str
    """The image's repository path."""
    blob_sha: str
    """Its git blob SHA."""
    content_type: str
    """The media type sniffed from its bytes."""
    data: bytes = field(repr=False)
    """Its bytes."""


class InstructionPolicy(StrEnum):
    """Whether a library's imports keep its ``AGENTS.md`` / ``CLAUDE.md`` files (RET-08)."""

    DROP = "drop"
    """Keep none (repo guidance off, the default)."""
    KEEP = "keep"
    """Keep the root's and the selected files' folders' files with each version."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedInstruction:
    """An instruction file (``AGENTS.md`` / ``CLAUDE.md``) of the commit (RET-08).

    Kept for agentic retrieval when the library's repo guidance is on. Untrusted repository text.
    """

    path: str
    """Repository-relative: the root's or a selected file's folder's."""
    content: str = field(repr=False)
    """Its decoded text."""


def instruction_candidates(paths: Sequence[str]) -> list[str]:
    """Name the instruction files to look for: the root's and the selected files' folders'.

    Folders go shallowest first (then by name), at most ``MAX_INSTRUCTION_DIRS`` of them, each
    with every name of ``INSTRUCTION_FILE_NAMES``; a folder named ``.git`` is never one.

    Args:
        paths: The selected files, repository-relative.

    Returns:
        The repository paths, in that order.
    """
    folders = {""}
    for path in paths:
        parts = path.split("/")[:-1]
        folders.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    kept = sorted(
        (f for f in folders if ".git" not in f.lower().split("/")),
        key=lambda f: (f.count("/") + bool(f), f),
    )[:MAX_INSTRUCTION_DIRS]
    return [
        f"{folder}/{name}" if folder else name for folder in kept for name in INSTRUCTION_FILE_NAMES
    ]


@dataclass(frozen=True, slots=True, kw_only=True)
class GitRename:
    """A file git sees as moved between two commits: ``old_path`` became ``new_path``."""

    old_path: str
    """The path in the older commit."""
    new_path: str
    """The path in the newer commit."""
    similarity: int
    """Percent of the content kept (100: moved unchanged); git reports renames from 50."""

    def __post_init__(self) -> None:
        """Refuse a similarity out of range.

        Raises:
            ValueError: ``similarity`` is not a percentage above 0.
        """
        if not 0 < self.similarity <= MAX_SIMILARITY:
            message = f"similarity must be 1..{MAX_SIMILARITY}, not {self.similarity}"
            raise ValueError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedVersion:
    """Every article of one library version at one commit, chunked with ``config_hash``."""

    library: str
    """The library ID."""
    ref: str
    """The version's ref."""
    kind: RefKind
    """What the ref is."""
    commit_sha: str
    """The full SHA of the commit imported."""
    config_hash: str
    """The chunker's ``config_hash``: keys the chunk sets."""
    articles: tuple[ImportedArticle, ...]
    """Every article, chunked."""
    images: tuple[ImportedImage, ...] = ()
    """The images the articles reference, within the version's budget."""
    refresh: bool = False
    """The version must still exist when it is stored (a re-sync never re-creates a removed one)."""
    renamed_from: str | None = None
    """The ref whose commit ``renames`` were detected against, also when nothing moved (the
    version this one follows); ``None`` when no version was compared."""
    renames: tuple[GitRename, ...] = ()
    """Renames from ``renamed_from``'s commit to this one, Markdown files only."""
    origin: VersionOrigin = VersionOrigin.MANUAL
    """Given to the version when this creates it; a version that exists keeps its own."""
    instructions: tuple[ImportedInstruction, ...] = ()
    """The commit's instruction files, kept with the manifest (only with repo guidance on)."""


def git_blob_sha(data: bytes) -> str:
    """Return the SHA-1 git gives a file with exactly these bytes.

    Args:
        data: The file's bytes.

    Returns:
        The blob SHA, hexadecimal.
    """
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Removed:
    """What the catalog took out: the manifests other domains must forget, the new default."""

    library: str
    """The library ID."""
    ref: str | None
    """The removed version; ``None`` when the whole library was removed."""
    manifest_ids: tuple[str, ...]
    """The deleted manifests."""
    default_ref: str | None
    """The library's default version now; ``None`` when none is left."""


type ArticleTags = Mapping[str, tuple[str, ...]]
"""Article path -> every tag the article carries now."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TaggedPath:
    """Manual tags the catalog stored for a path, and the manifests whose articles they touched."""

    library: str
    """The library ID."""
    path: str
    """The article's repository path."""
    tags: tuple[str, ...]
    """Its manual tags, normalized."""
    retagged: Mapping[str, ArticleTags]
    """Manifest ID -> its touched articles."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredArticleTags:
    """What a stored article's imported tags are derived from, and what they are now."""

    path: str
    """The article's repository path."""
    front_matter: Mapping[str, Any]
    """Its stored front matter."""
    tags: tuple[str, ...]
    """Imported: path rules and front matter (manual tags are kept apart)."""

    def retagged(self, rules: Sequence[TagRule]) -> ImportedTags:
        """Return the imported tags the article gets under ``rules`` (as an import would).

        Args:
            rules: The library's tag rules.

        Returns:
            The imported tags and their sources.
        """
        return imported_tags(self.path, front_matter_tags(self.front_matter)[0], rules)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredArticle:
    """What an import stored for a file: an import of the same file takes it instead of parsing.

    Found by path, git blob SHA and ``PARSER_VERSION``: the title and the image links depend on
    the path, everything else on the bytes and the parser. Tags are not stored here: they are
    derived again (path rules are the library's settings, which may have changed).
    """

    path: str
    """The file's repository path."""
    blob_sha: str
    """The file's git blob SHA."""
    title: str
    """The title the parse gave."""
    front_matter: Mapping[str, Any]
    """The front matter the parse gave."""
    content: str
    """The body the parse gave."""

    def parsed(self) -> ParsedArticle | None:
        """Return what ``parse_article`` gives the file, rebuilt without parsing it.

        ``None`` when only a parse can tell whether the front matter was malformed (kept in the
        body, with a note to list again; ``stored_front_matter_problems``).

        Returns:
            The parsed article, or ``None``.
        """
        kept = stored_front_matter_problems(
            self.path, self.content, self.front_matter, self.blob_sha
        )
        if kept is None:
            return None
        front_matter = dict(self.front_matter)
        tags, problems = _declared(front_matter)
        return ParsedArticle(
            path=self.path,
            title=self.title,
            body=self.content,
            tags=tags,
            description=_description(front_matter),
            front_matter=front_matter,
            problems=(*kept, *problems),
            images=image_paths(self.path, self.content),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredTags:
    """The active manifest of a version, with the tag sources of its articles."""

    manifest_id: str
    """The active manifest."""
    articles: tuple[StoredArticleTags, ...]
    """Every article's tag sources."""


class SettingsChange(StrEnum):
    """What an edit of a library's settings asks of its versions; each does what follows it too.

    ``PATHS`` re-imports with the new chunking and tag rules, ``CHUNKING`` re-tags as well.
    """

    PATHS = "paths"
    """The selection changed: every version is fetched again at its commit and re-imported."""
    CHUNKING = "chunking"
    """The chunking changed: every version is re-chunked from what is stored, nothing fetched."""
    TAGS = "tags"
    """Only tag rules changed: every version is re-tagged from what is stored, nothing fetched."""

    @property
    def reach(self) -> int:
        """How much it redoes: a change of greater reach does all that one of smaller reach does."""
        return {SettingsChange.TAGS: 1, SettingsChange.CHUNKING: 2, SettingsChange.PATHS: 3}[self]


@dataclass(frozen=True, slots=True, kw_only=True)
class CopiedArticle:
    """An article of a version's copied manifest, with its stored text (re-chunking)."""

    path: str
    """The file's repository path."""
    blob_sha: str
    """The file's git blob SHA."""
    title: str
    """The stored title."""
    front_matter: Mapping[str, Any]
    """The stored front matter."""
    tags: tuple[str, ...]
    """Imported: path rules and front matter (manual tags are kept apart)."""
    content: str
    """The stored body."""

    def parsed(self) -> ParsedArticle | None:
        """Return the article as the parser gave it: what a chunker cuts.

        ``None`` when only a parse of the file can tell whether its front matter was malformed
        (``stored_front_matter_problems``): the version is then re-imported.

        Returns:
            The parsed article, or ``None``.
        """
        problems = stored_front_matter_problems(
            self.path, self.content, self.front_matter, self.blob_sha
        )
        if problems is None:
            return None
        return ParsedArticle(
            path=self.path,
            title=self.title,
            body=self.content,
            front_matter=dict(self.front_matter),
            problems=problems,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CopiedVersion:
    """A version's active manifest copied into a new pending one, to be re-chunked."""

    manifest_id: str
    """The copy: pending, with the same entries, images and renames."""
    kind: RefKind
    """What the version's ref is."""
    commit_sha: str
    """The commit the version serves."""
    articles: tuple[CopiedArticle, ...]
    """Every article, with its stored text."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Collected:
    """What one collector deleted."""

    deleted: int
    """How many things it deleted."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedRef:
    """A version a library has: its ref, what kind of ref it is and the commit it serves."""

    ref: str
    """The version's ref."""
    kind: RefKind
    """What the ref is."""
    commit_sha: str
    """The commit the version serves."""
    origin: VersionOrigin = VersionOrigin.MANUAL
    """Who asked for the version: retention only removes ``auto`` ones."""
    pinned: bool = False
    """The library's owner pinned it as the default version (LIB-10): retention keeps it."""


def _numbers(ref: str) -> tuple[int, ...] | None:
    """Read the numbers of a numeric ref (``v1.4.0`` -> ``(1, 4, 0)``).

    Args:
        ref: A ref.

    Returns:
        The numbers, or None for a ref without a version order.
    """
    match = _NUMERIC_REF.fullmatch(ref)
    return tuple(map(int, match[1].split("."))) if match else None


def _precedes(older: tuple[int, ...], newer: tuple[int, ...]) -> bool:
    """Tell whether ``older`` is a lower version; ``1.4`` and ``1.4.0`` are the same one.

    Args:
        older: A version's numbers.
        newer: Another version's numbers.

    Returns:
        True when ``older`` comes before ``newer``.
    """
    width = max(len(older), len(newer))
    return older + (0,) * (width - len(older)) < newer + (0,) * (width - len(newer))


def previous_version(ref: str, imported: Sequence[ImportedRef]) -> ImportedRef | None:
    """Pick the version whose commit renames are detected against when ``ref`` is imported.

    A numeric ref (``v1.4.0``, ``2.1``) is compared with the highest lower numeric tag, never
    with itself, so a re-sync of it gives the same map. A ref without an order (a branch, a
    commit) is compared with what it served before, if it was imported; ``None`` otherwise.
    Pre-releases and other names have no order and get ``None`` as well.

    Args:
        ref: The ref being imported.
        imported: The library's versions.

    Returns:
        The version to compare with, or ``None``.
    """
    wanted = _numbers(ref)
    if wanted is None:
        return next((v for v in imported if v.ref == ref), None)
    older = [
        (number, v)
        for v in imported
        if v.kind is RefKind.TAG and (number := _numbers(v.ref)) is not None
        if _precedes(number, wanted)
    ]
    return max(older, key=itemgetter(0))[1] if older else None


def is_unordered(ref: str) -> bool:
    """Tell whether renames of ``ref`` build up over its syncs (it has no place in an order).

    Args:
        ref: A ref.

    Returns:
        True for a ref without a version order.
    """
    return _numbers(ref) is None


def compose_renames(
    earlier: Sequence[GitRename], latest: Sequence[GitRename], articles: Collection[str]
) -> tuple[GitRename, ...]:
    """Chain a branch's earlier renames with the ones of its latest sync.

    ``A -> B`` earlier and ``B -> C`` now gives ``A -> C`` (the lower similarity); renames of
    the latest sync stay too, unless their old path is one the earlier map already tells about.
    Entries whose target is not an article any more, or that came back to their old path, go.

    Args:
        earlier: The renames the branch had.
        latest: The renames of its latest sync.
        articles: The article paths of the new version.

    Returns:
        The chained renames, at most ``MAX_RENAMES``.
    """
    now = {r.old_path: r for r in latest}
    chained = [
        replace(
            r,
            new_path=(moved := now.get(r.new_path, r)).new_path,
            similarity=min(r.similarity, moved.similarity),
        )
        for r in earlier
    ]
    seen = {r.old_path for r in chained}
    chained += [r for r in latest if r.old_path not in seen]
    return tuple(r for r in chained if r.new_path in articles and r.new_path != r.old_path)[
        :MAX_RENAMES
    ]


class SyncStatus(StrEnum):
    """What a re-sync did with one version."""

    QUEUED = "queued"
    """The branch moved: an import of the new tip was queued."""
    UP_TO_DATE = "up_to_date"
    """The branch did not move: nothing was queued."""
    IMPORTING = "importing"
    """An import of this branch is already queued or running: nothing was queued for it."""
    PINNED = "pinned"
    """A tag or a commit never moves: it is not synced."""
    FAILED = "failed"
    """The branch is gone upstream: the version keeps what it served; the failure is on a job."""


# ---------------------------------------------------------------- the scheduled check (SYNC-02)


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoSync:
    """When and how a library is checked on its own: new tags imported, branches re-synced.

    Every ``interval_minutes`` the scheduled check asks the remote for its refs once. With a
    ``tag_pattern`` (a glob over tag names, ``v*``), tags it matches that have a version order
    (``v1.4.0``, ``2.1``) become ``auto`` versions, and of those only the newest ``keep_last``
    are kept: older ``auto`` versions are removed once their replacements are versions,
    ``manual`` ones and the pinned default never. With
    ``sync_branches`` every branch version is re-synced as ``SyncLibrary`` would. ``checked_at``
    is when the last check ended (``None``: at the next tick) and ``last_error`` what it could
    not do.
    """

    library: str
    """The library ID."""
    tag_pattern: str | None = None
    """A case-sensitive glob over tag names; ``None`` imports no tag."""
    keep_last: int = DEFAULT_KEEP_LAST
    """How many ``auto`` versions are kept, the newest."""
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    """Minutes between two checks."""
    sync_branches: bool = False
    """Whether every branch version is re-synced at each check."""
    checked_at: datetime | None = None
    """When the last check ended."""
    last_error: str | None = None
    """What the last check could not do, cut to ``MAX_CHECK_ERROR`` characters."""
    revision: str = ""
    """Changes on every save of the settings: a check records itself only on the one it read."""

    def __post_init__(self) -> None:
        """Refuse a tag pattern, retention or interval out of range.

        Raises:
            InvalidAutoSyncError: A setting cannot be used.
        """
        pattern = self.tag_pattern
        if pattern is not None and (
            not pattern
            or len(pattern) > MAX_TAG_PATTERN
            or not all(c.isprintable() and not c.isspace() for c in pattern)
        ):
            message = f"a tag pattern is 1 to {MAX_TAG_PATTERN} characters without spaces"
            raise InvalidAutoSyncError(message)
        if not 1 <= self.keep_last <= MAX_KEEP_LAST:
            message = f"keep_last must be between 1 and {MAX_KEEP_LAST}"
            raise InvalidAutoSyncError(message)
        if not MIN_INTERVAL_MINUTES <= self.interval_minutes <= MAX_INTERVAL_MINUTES:
            message = (
                f"interval_minutes must be between {MIN_INTERVAL_MINUTES} "
                f"and {MAX_INTERVAL_MINUTES}"
            )
            raise InvalidAutoSyncError(message)

    def matches(self, tag: str) -> bool:
        """Tell whether the tag is one to import automatically (case-sensitive glob).

        Args:
            tag: A tag name.

        Returns:
            True when ``tag_pattern`` matches it.
        """
        return self.tag_pattern is not None and fnmatchcase(tag, self.tag_pattern)

    @property
    def next_check_at(self) -> datetime | None:
        """When the library is due again; ``None``: at the next tick of the schedule."""
        if self.checked_at is None:
            return None
        return self.checked_at + timedelta(minutes=self.interval_minutes)

    def is_due(self, now: datetime) -> bool:
        """Tell whether the scheduled check should look at the library ``now``.

        Args:
            now: The time of the tick.

        Returns:
            True when it was never checked or its interval has passed.
        """
        due = self.next_check_at
        return due is None or now >= due

    def checked(self, now: datetime, error: str | None) -> Self:
        """Record that a check ended at ``now``, with what it could not do.

        Args:
            now: The time the check ended.
            error: What it could not do; ``None`` when it did everything.

        Returns:
            The schedule with the check recorded.
        """
        if error is not None and len(error) > MAX_CHECK_ERROR:
            error = error[: MAX_CHECK_ERROR - 1] + "…"
        return replace(self, checked_at=now, last_error=error)


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoImportPlan:
    """What one scheduled check does with a library's tags."""

    imports: tuple[ResolvedRef, ...] = ()
    """Tags to import as ``auto`` versions, oldest first."""
    removals: tuple[str, ...] = ()
    """``auto`` versions that fell out of the newest ``keep_last``."""


def _order(ref: str) -> tuple[tuple[int, ...], str]:
    """Rank a numeric ref: ``1.4`` equals ``1.4.0``, and the name breaks a tie.

    Args:
        ref: A ref.

    Returns:
        The sort key.
    """
    numbers = _numbers(ref) or ()
    padded = numbers + (0,) * (_ORDER_WIDTH - len(numbers)) if numbers else ()
    return padded, ref


def plan_auto_imports(
    auto_sync: AutoSync,
    tips: Sequence[ResolvedRef],
    versions: Sequence[ImportedRef],
    *,
    failed: Collection[tuple[str, str]] = (),
) -> AutoImportPlan:
    """Pick the tags to import and the ``auto`` versions to remove (pure).

    Imports: the matching tags that are not versions yet and are among the newest ``keep_last``
    of (those tags plus the ``auto`` versions). Removals: the ``auto`` versions outside the
    newest ``keep_last`` *versions*, so an old one goes only at the first check after its
    replacement is imported (a failed import never leaves the library short). A tag without a
    version order (a pre-release, a name) is never imported; a ``manual`` version and the
    pinned default version are never removed and do not count. ``failed`` holds the (tag,
    commit) pairs whose last import failed for good: they are not tried again until the tag
    moves.

    Args:
        auto_sync: The library's schedule.
        tips: The refs the remote advertises.
        versions: The library's versions.
        failed: The (tag, commit) pairs whose last import failed for good.

    Returns:
        The imports, oldest first, and the removals.
    """
    if auto_sync.tag_pattern is None:
        return AutoImportPlan()
    have = {v.ref for v in versions}
    new = {
        tip.name: tip
        for tip in tips
        if tip.kind is RefKind.TAG
        and tip.name not in have
        and auto_sync.matches(tip.name)
        and _numbers(tip.name) is not None
        and (tip.name, tip.commit_sha) not in failed
    }
    autos = sorted(
        (
            v.ref
            for v in versions
            if v.origin is VersionOrigin.AUTO
            and not v.pinned
            and v.kind is RefKind.TAG
            and _numbers(v.ref) is not None
        ),
        key=_order,
        reverse=True,
    )
    ranked = sorted({*new, *autos}, key=_order, reverse=True)
    wanted = set(ranked[: auto_sync.keep_last])
    return AutoImportPlan(
        imports=tuple(new[name] for name in reversed(ranked) if name in wanted and name in new),
        removals=tuple(reversed(autos[auto_sync.keep_last :])),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionToEmbed:
    """A version the instance's embedding model has not fully embedded."""

    library: str
    """The library ID."""
    ref: str
    """The version."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbedPlan:
    """What an ``embed`` job of one version does (a durable step's result)."""

    space_id: int | None
    """The embedding space it fills; ``None`` when nothing of the version is to be sent."""
    manifest_id: str | None
    """The version's manifest when the job started."""
    missing: int
    """Chunks without a vector then, each once: the job's ``total``."""
    created: bool
    """The job created the space (the model changed): every other version needs embedding too."""
    skipped: str | None
    """Why nothing is sent (``ai_off``, ``no_embedding_model``...), if nothing is."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddedBatch:
    """One batch of an ``embed`` job (a durable step's result)."""

    embedded: int
    """Vectors stored."""
    finished: bool
    """Nothing of the version is left to embed, or nothing more may be sent."""
    left: int | None = None
    """Chunks of the plan's ``missing`` still without a vector after the batch; ``None`` when not
    counted (the job stopped early). What is neither embedded by the job nor left was embedded
    meanwhile by another job sharing chunks with it (identical files in another library)."""


# ---------------------------------------------------------------- the sources file (TEAM-02)


@dataclass(frozen=True, slots=True, kw_only=True)
class KnownLibrary:
    """A library the instance has, as listed: its ID and where it comes from."""

    library_id: str
    """The canonical library ID."""
    source_url: str
    """The repository URL it was added with."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclaredLibrary:
    """A library as a sources file declares it, normalized the way the server stores it.

    A setting left ``None`` is not managed: plan never compares it and apply never changes it.
    ``manages_auto_sync`` says whether the scheduled check is managed; then ``auto_sync`` is the
    wanted schedule, ``None`` meaning off.
    """

    library_id: str
    """The canonical (lower-case) library ID."""
    url: RepositoryUrl
    """The repository."""
    refs: tuple[str, ...]
    """The versions to have, in the file's order: the first one is imported when it is created."""
    include: tuple[str, ...] | None = None
    """The paths to import; ``None``: not managed."""
    exclude: tuple[str, ...] | None = None
    """The paths to leave out; ``None``: not managed."""
    tag_rules: tuple[TagRule, ...] | None = None
    """The tag rules; ``None``: not managed."""
    chunking: ChunkingConfig | None = None
    """The chunking; ``None``: not managed."""
    title: str | None = None
    """The library's title, kept like an edit by hand; ``None``: not managed."""
    description: str | None = None
    """The library's description, kept like an edit by hand; ``None``: not managed. Empty is a
    declared "no description"."""
    manages_auto_sync: bool = False
    """Whether the scheduled check is managed."""
    auto_sync: AutoSync | None = None
    """The wanted schedule when managed; ``None`` turns it off."""

    @property
    def manages_paths(self) -> bool:
        """Whether either path list is managed: then empty lists mean every file."""
        return self.include is not None or self.exclude is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentLibrary:
    """What the instance has for a library, as far as a sources file can declare it."""

    library_id: str
    """The canonical library ID."""
    source: ImportSource
    """Its repository and settings."""
    versions: tuple[ImportedRef, ...] = ()
    """Its versions."""
    busy_refs: frozenset[str] = frozenset()
    """Refs whose import is queued or running: present already for a sources file."""
    auto_sync: AutoSync | None = None
    """Its scheduled check; ``None``: off."""


class SourcesField(StrEnum):
    """A library setting a sources file manages."""

    INCLUDE_PATHS = "include_paths"
    EXCLUDE_PATHS = "exclude_paths"
    TAG_RULES = "tag_rules"
    CHUNKING = "chunking"
    TITLE = "title"
    DESCRIPTION = "description"

    @property
    def is_text(self) -> bool:
        """Whether this is the library's text, stored apart from its import settings."""
        return self in {SourcesField.TITLE, SourcesField.DESCRIPTION}


@dataclass(frozen=True, slots=True, kw_only=True)
class LibraryUpdate:
    """How an existing library differs from its declaration, and what apply does about it."""

    declared: DeclaredLibrary
    """The declaration."""
    current: CurrentLibrary
    """The library as it is."""
    changed: tuple[SourcesField, ...] = ()
    """The managed settings that differ (as sets: order and spelling do not count)."""
    refs_to_add: tuple[str, ...] = ()
    """Declared refs that are neither versions nor being imported."""
    auto_sync_changes: bool = False
    """The scheduled check is turned on, off or changed."""
    reprocess: SettingsChange | None = None
    """What the settings change asks of the versions; ``None``: no re-processing job."""
    undeclared_versions: tuple[str, ...] = ()
    """``manual`` versions the file does not declare (``auto`` ones belong to the schedule)."""
    prune: bool = False
    """Whether apply removes ``undeclared_versions``."""

    @property
    def library_id(self) -> str:
        """The library ID."""
        return self.current.library_id

    @property
    def selection(self) -> PathSelection:
        """The paths to store: the declared ones, the stored ones where the file has none."""
        stored = self.current.source.selection
        include, exclude = self.declared.include, self.declared.exclude
        return PathSelection(
            include=stored.include if include is None else include,
            exclude=stored.exclude if exclude is None else exclude,
        )

    @property
    def tag_rules(self) -> tuple[TagRule, ...]:
        """The tag rules to store: the declared ones, else the stored ones."""
        declared = self.declared.tag_rules
        return self.current.source.tag_rules if declared is None else declared

    @property
    def settings_changed(self) -> bool:
        """Whether an import setting (paths, tag rules, chunking) differs."""
        return any(not name.is_text for name in self.changed)

    @property
    def text_changed(self) -> bool:
        """Whether the title or the description differs."""
        return any(name.is_text for name in self.changed)

    @property
    def writes(self) -> bool:
        """Whether apply calls any write port for the library."""
        return bool(
            self.changed
            or self.refs_to_add
            or self.auto_sync_changes
            or (self.prune and self.undeclared_versions)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceError:
    """A declared library that plan cannot reconcile; apply leaves it alone."""

    library_id: str
    """The declared library ID."""
    code: str
    """A stable machine code, e.g. ``source_mismatch``."""
    message: str
    """What is wrong, for people."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SourcesPlan:
    """The difference between a sources file and the instance (``plan_sources``)."""

    create: tuple[DeclaredLibrary, ...] = ()
    """Declared libraries that do not exist."""
    update: tuple[LibraryUpdate, ...] = ()
    """Existing libraries that differ from their declaration (or have undeclared versions)."""
    unchanged: tuple[str, ...] = ()
    """Existing libraries that match their declaration."""
    undeclared: tuple[CurrentLibrary, ...] = ()
    """Libraries the file does not declare."""
    errors: tuple[SourceError, ...] = ()
    """Declared libraries that cannot be reconciled."""
    prune: bool = False
    """Whether apply removes undeclared libraries and versions."""


def _same_repository(declared: RepositoryUrl, stored: RepositoryUrl) -> bool:
    """Tell whether two URLs name one repository.

    A trailing ``/`` or ``.git`` (in any letter case) and the letter case of the scheme and
    host do not count. The path keeps its case: forges differ on whether it matters.

    Args:
        declared: The URL the file declares.
        stored: The URL the library was created from.

    Returns:
        True when they are the same repository.
    """
    return _repository_key(declared.url) == _repository_key(stored.url)


def _repository_key(url: str) -> str:
    """Spell a URL the way ``_same_repository`` compares it.

    Args:
        url: A URL that passed ``RepositoryUrl.parse``.

    Returns:
        The URL without a trailing ``/`` or ``.git``, its scheme and host in lower case.
    """
    url = url.rstrip("/")
    if url[-len(".git") :].lower() == ".git":
        url = url[: -len(".git")]
    if "://" in url:
        parts = urlsplit(url)
        user, at, host = parts.netloc.rpartition("@")
        return f"{parts.scheme.lower()}://{user}{at}{host.lower()}{parts.path}"
    if match := _SCP_LIKE.fullmatch(url):
        return f"{match['user']}@{match['host'].lower()}:{match['path']}"
    return url


def _schedule(auto_sync: AutoSync | None) -> tuple[object, ...] | None:
    """Return what a sources file can say about a schedule (not when it last ran).

    Args:
        auto_sync: A schedule, or ``None`` for off.

    Returns:
        Its settings, or ``None``.
    """
    if auto_sync is None:
        return None
    return (
        auto_sync.tag_pattern,
        auto_sync.keep_last,
        auto_sync.interval_minutes,
        auto_sync.sync_branches,
    )


def _changed_fields(declared: DeclaredLibrary, source: ImportSource) -> tuple[SourcesField, ...]:
    """List the managed settings that differ from the stored ones, compared as sets.

    Args:
        declared: The declaration.
        source: The stored settings.

    Returns:
        The fields that differ, in ``SourcesField`` order.
    """
    stored = source.selection
    pairs: tuple[tuple[SourcesField, object, object], ...] = (
        (SourcesField.INCLUDE_PATHS, declared.include, frozenset(stored.include)),
        (SourcesField.EXCLUDE_PATHS, declared.exclude, frozenset(stored.exclude)),
        (SourcesField.TAG_RULES, declared.tag_rules, frozenset(source.tag_rules)),
    )
    changed = [
        name for name, wanted, have in pairs if wanted is not None and frozenset(wanted) != have
    ]
    if declared.chunking is not None and declared.chunking != source.chunking:
        changed.append(SourcesField.CHUNKING)
    if declared.title is not None and declared.title != source.title:
        changed.append(SourcesField.TITLE)
    if declared.description is not None and declared.description != source.description:
        changed.append(SourcesField.DESCRIPTION)
    return tuple(changed)


def _reprocess_of(changed: Collection[SourcesField]) -> SettingsChange | None:
    """Say which re-processing a settings change queues (as ``UpdateLibrarySettings`` does).

    Args:
        changed: The settings that change.

    Returns:
        The widest change, or ``None``.
    """
    if {SourcesField.INCLUDE_PATHS, SourcesField.EXCLUDE_PATHS} & set(changed):
        return SettingsChange.PATHS
    if SourcesField.CHUNKING in changed:
        return SettingsChange.CHUNKING
    if SourcesField.TAG_RULES in changed:
        return SettingsChange.TAGS
    return None


def _update_of(declared: DeclaredLibrary, current: CurrentLibrary, *, prune: bool) -> LibraryUpdate:
    """Compare one declared library with what the instance has.

    Args:
        declared: The declaration.
        current: The library as it is.
        prune: Whether undeclared versions are removed.

    Returns:
        The difference (``writes`` false and no undeclared version: unchanged).
    """
    present = {v.ref for v in current.versions} | current.busy_refs
    changed = _changed_fields(declared, current.source)
    reprocess = _reprocess_of(changed)
    if not (current.versions or current.busy_refs):
        reprocess = None  # nothing to re-process: imports to come read the new settings
    wanted = set(declared.refs)
    return LibraryUpdate(
        declared=declared,
        current=current,
        changed=changed,
        refs_to_add=tuple(r for r in declared.refs if r not in present),
        auto_sync_changes=declared.manages_auto_sync
        and _schedule(declared.auto_sync) != _schedule(current.auto_sync),
        reprocess=reprocess,
        undeclared_versions=tuple(
            v.ref
            for v in current.versions
            if v.origin is VersionOrigin.MANUAL and v.ref not in wanted
        ),
        prune=prune,
    )


def plan_sources(
    declared: Sequence[DeclaredLibrary], current: Sequence[CurrentLibrary], *, prune: bool = False
) -> SourcesPlan:
    """Compare a sources file with the instance (pure; nothing is called).

    A declared library that does not exist is created; one that exists with the same repository
    is compared setting by setting, only for the settings it manages; one whose ID exists with
    another repository is a ``source_mismatch`` error. A declared ref is present when it is a
    version or its import is queued or running, so an apply right after another one is a no-op.
    ``manual`` versions the file does not declare and libraries it does not declare are always
    listed, and removed by apply only with ``prune``; ``auto`` versions are never listed.

    Args:
        declared: The libraries the file declares, IDs unique.
        current: Every library of the instance.
        prune: Whether apply removes what the file does not declare.

    Returns:
        The plan.
    """
    have = {c.library_id: c for c in current}
    create: list[DeclaredLibrary] = []
    update: list[LibraryUpdate] = []
    unchanged: list[str] = []
    errors: list[SourceError] = []
    for wanted in declared:
        found = have.get(wanted.library_id)
        if found is None:
            create.append(wanted)
        elif not _same_repository(wanted.url, found.source.url):
            message = (
                f"library {wanted.library_id!r} exists with another repository URL; "
                "declare that URL or another id"
            )
            errors.append(
                SourceError(library_id=wanted.library_id, code=SOURCE_MISMATCH, message=message)
            )
        elif (diff := _update_of(wanted, found, prune=prune)).writes or diff.undeclared_versions:
            update.append(diff)
        else:
            unchanged.append(found.library_id)
    named = {d.library_id for d in declared}
    return SourcesPlan(
        create=tuple(create),
        update=tuple(update),
        unchanged=tuple(unchanged),
        undeclared=tuple(c for c in current if c.library_id not in named),
        errors=tuple(errors),
        prune=prune,
    )


# ---------------------------------------------------------------- push webhooks (TEAM-03)


class WebhookProvider(StrEnum):
    """The forge a webhook delivery comes from, told by its headers."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


@dataclass(frozen=True, slots=True, kw_only=True)
class Webhook:
    """A library's webhook: the shared secret its forge proves its deliveries with."""

    library: str
    """The library ID."""
    secret: str = field(repr=False)
    """The shared secret (URL-safe text); never logged or shown again after it is created."""
    created_at: datetime
    """When it was created (or last rotated)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebhookDelivery:
    """One delivery a forge made, remembered so a redelivery is not acted on twice."""

    library: str
    """The library ID."""
    provider: WebhookProvider
    """The forge."""
    delivery_id: str
    """The forge's ID of the delivery."""
    received_at: datetime
    """When it was accepted."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PushedRef:
    """A branch or tag a push changed, by name only: the job lists the remote itself."""

    kind: RefKind
    """``branch`` or ``tag``."""
    name: str
    """The branch or tag name, without ``refs/heads/`` or ``refs/tags/``."""
    deleted: bool = False
    """The push deleted it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PushEvent:
    """What a delivery says: its ID and the refs it pushed (none for a ping or another event)."""

    delivery_id: str
    """The forge's ID of the delivery."""
    refs: tuple[PushedRef, ...] = ()
    """The branches and tags pushed, in the payload's order."""


def _lowered(headers: Mapping[str, str]) -> dict[str, str]:
    """Return the headers by lower-case name (HTTP header names are case-insensitive).

    Args:
        headers: The request's headers.

    Returns:
        The same headers, keyed by lower-case name.
    """
    return {name.lower(): value for name, value in headers.items()}


def webhook_provider(headers: Mapping[str, str]) -> WebhookProvider | None:
    """Tell which forge sent a delivery by the event header it carries.

    Args:
        headers: The request's headers.

    Returns:
        The forge, or ``None`` when no known event header is there.
    """
    lowered = _lowered(headers)
    if "x-github-event" in lowered:
        return WebhookProvider.GITHUB
    if "x-gitlab-event" in lowered:
        return WebhookProvider.GITLAB
    if "x-event-key" in lowered:
        return WebhookProvider.BITBUCKET
    return None


def verify_webhook(
    provider: WebhookProvider, headers: Mapping[str, str], body: bytes, secret: str
) -> bool:
    """Tell whether the delivery was made by someone who holds the secret (constant time).

    GitHub signs the raw body in ``X-Hub-Signature-256: sha256=<hex>`` and Bitbucket (Cloud and
    Data Center) in ``X-Hub-Signature: sha256=<hex>``, both HMAC-SHA256 with the secret as key;
    GitLab sends the secret itself in ``X-Gitlab-Token``. Every comparison is
    ``hmac.compare_digest``, and the HMAC is computed even when the header is missing. A SHA-1
    signature (``sha1=``, GitHub's ``X-Hub-Signature``) is never accepted.

    Args:
        provider: The forge, told by ``webhook_provider``.
        headers: The request's headers.
        body: The raw body, exactly as received (before it is parsed).
        secret: The library's webhook secret.

    Returns:
        True when the signature or token matches.
    """
    lowered = _lowered(headers)
    key = secret.encode()
    if provider is WebhookProvider.GITLAB:
        sent = lowered.get("x-gitlab-token", "").encode()
        # Digests of both: equal lengths, so the comparison says nothing about the length.
        return hmac.compare_digest(hashlib.sha256(sent).digest(), hashlib.sha256(key).digest())
    header = GITHUB_SIGNATURE_HEADER if provider is WebhookProvider.GITHUB else "x-hub-signature"
    expected = SIGNATURE_SCHEME + hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(lowered.get(header, "").encode(), expected.encode())


def _delivery_id(provider: WebhookProvider, headers: Mapping[str, str]) -> str | None:
    """Return the delivery's ID from the forge's header for it.

    Args:
        provider: The forge.
        headers: The request's headers, by lower-case name.

    Returns:
        The ID, or ``None`` when there is none (or it is empty or too long).
    """
    names = {
        WebhookProvider.GITHUB: ("x-github-delivery",),
        WebhookProvider.GITLAB: ("idempotency-key", "x-gitlab-event-uuid"),
        WebhookProvider.BITBUCKET: ("x-request-uuid", "x-request-id"),
    }[provider]
    found = next((headers[n].strip() for n in names if headers.get(n, "").strip()), None)
    if found is None or len(found) > MAX_DELIVERY_ID or not found.isprintable():
        return None
    return found


def _pushed(full: str, *, deleted: bool) -> PushedRef | None:
    """Read a full ref name (``refs/heads/main``, ``refs/tags/v1``) as a pushed branch or tag.

    Args:
        full: The full ref name.
        deleted: The push deleted it.

    Returns:
        The ref, or ``None`` for another kind of ref or a name git would not accept.
    """
    for prefix, kind in ((HEADS, RefKind.BRANCH), (TAGS, RefKind.TAG)):
        if full.startswith(prefix) and (name := branch_name(full.removeprefix(prefix))):
            return PushedRef(kind=kind, name=name, deleted=deleted)
    return None


def _named(kind: object, name: object, *, deleted: bool) -> PushedRef | None:
    """Read a ref Bitbucket names by its type and short name.

    Args:
        kind: The ref's type (``branch``/``tag`` on Cloud, ``BRANCH``/``TAG`` on Data Center).
        name: The short name.
        deleted: The push deleted it.

    Returns:
        The ref, or ``None`` for another type or a name git would not accept.
    """
    kinds = {"branch": RefKind.BRANCH, "tag": RefKind.TAG}
    if not isinstance(kind, str) or not isinstance(name, str) or kind.lower() not in kinds:
        return None
    valid = branch_name(name)
    return (
        None if valid is None else PushedRef(kind=kinds[kind.lower()], name=valid, deleted=deleted)
    )


def _github_refs(payload: Mapping[str, Any]) -> list[PushedRef | None]:
    """Read the ref of a GitHub ``push`` (``ref``, ``deleted``).

    Args:
        payload: The JSON body.

    Returns:
        The pushed ref, or ``None`` when it is not a branch or tag.
    """
    ref = payload.get("ref")
    return [_pushed(ref, deleted=payload.get("deleted") is True) if isinstance(ref, str) else None]


def _gitlab_refs(payload: Mapping[str, Any]) -> list[PushedRef | None]:
    """Read the ref of a GitLab ``Push Hook`` or ``Tag Push Hook`` (deleted: ``after`` is zeros).

    Args:
        payload: The JSON body.

    Returns:
        The pushed ref, or ``None`` when it is not a branch or tag.
    """
    ref, after = payload.get("ref"), payload.get("after")
    deleted = isinstance(after, str) and bool(after) and set(after) == {"0"}
    return [_pushed(ref, deleted=deleted) if isinstance(ref, str) else None]


def _bitbucket_refs(payload: Mapping[str, Any]) -> list[PushedRef | None]:
    """Read every change of a Bitbucket Cloud ``repo:push`` or Data Center ``repo:refs_changed``.

    Cloud lists ``push.changes[]`` with the ref's ``new`` state (``None`` once deleted) and its
    ``old`` one; Data Center lists ``changes[]`` with the ``ref`` and a ``type`` (``DELETE``).

    Args:
        payload: The JSON body.

    Returns:
        One entry per change: the ref, or ``None`` when it is not a branch or tag.

    Raises:
        InvalidWebhookPayloadError: The changes are not a list of objects.
    """
    push = payload.get("push")
    changes = push.get("changes") if isinstance(push, dict) else payload.get("changes")
    if not isinstance(changes, list) or not all(isinstance(c, dict) for c in changes):
        reason = "no list of changes"
        raise InvalidWebhookPayloadError(reason)
    found: list[PushedRef | None] = []
    for change in changes:
        if "ref" in change:  # Data Center
            ref = change["ref"] if isinstance(change["ref"], dict) else {}
            deleted = change.get("type") == "DELETE"
            full = ref.get("id")
            pushed = _pushed(full, deleted=deleted) if isinstance(full, str) else None
            found.append(pushed or _named(ref.get("type"), ref.get("displayId"), deleted=deleted))
            continue
        new, old = change.get("new"), change.get("old")
        state = new if isinstance(new, dict) else old if isinstance(old, dict) else {}
        found.append(_named(state.get("type"), state.get("name"), deleted=new is None))
    return found


def parse_push(provider: WebhookProvider, headers: Mapping[str, str], body: bytes) -> PushEvent:
    """Read a verified delivery: its ID and, for a push, the branches and tags it changed.

    Only ref names are read: the payload is a hint, and a commit SHA in it is never trusted.
    Push events are GitHub's ``push``, GitLab's ``Push Hook`` and ``Tag Push Hook``, and
    Bitbucket's ``repo:push`` (Cloud) and ``repo:refs_changed`` (Data Center); any other event
    (a ping, diagnostics) has no refs. A ref that is not a branch or tag is left out.

    Args:
        provider: The forge.
        headers: The request's headers.
        body: The raw body.

    Returns:
        The delivery's ID and the refs it pushed.

    Raises:
        MissingDeliveryIdError: The delivery has no usable ID.
        InvalidWebhookPayloadError: A push event's body is not the JSON its forge sends.
    """
    lowered = _lowered(headers)
    delivery = _delivery_id(provider, lowered)
    if delivery is None:
        raise MissingDeliveryIdError
    event = {
        WebhookProvider.GITHUB: lowered.get("x-github-event", ""),
        WebhookProvider.GITLAB: lowered.get("x-gitlab-event", ""),
        WebhookProvider.BITBUCKET: lowered.get("x-event-key", ""),
    }[provider].strip()
    readers = {
        (WebhookProvider.GITHUB, "push"): _github_refs,
        (WebhookProvider.GITLAB, "Push Hook"): _gitlab_refs,
        (WebhookProvider.GITLAB, "Tag Push Hook"): _gitlab_refs,
        (WebhookProvider.BITBUCKET, "repo:push"): _bitbucket_refs,
        (WebhookProvider.BITBUCKET, "repo:refs_changed"): _bitbucket_refs,
    }
    reader = readers.get((provider, event))
    if reader is None:
        return PushEvent(delivery_id=delivery)
    try:
        payload = json.loads(body)
    except ValueError:
        reason = "not JSON"
        raise InvalidWebhookPayloadError(reason) from None
    if not isinstance(payload, dict):
        reason = "not a JSON object"
        raise InvalidWebhookPayloadError(reason)
    refs = tuple(dict.fromkeys(r for r in reader(payload) if r is not None))
    return PushEvent(delivery_id=delivery, refs=refs)


def route_push(
    event: PushEvent, versions: Sequence[ImportedRef], auto_sync: AutoSync | None
) -> tuple[PushedRef, ...]:
    """Pick the pushed refs that queue a job (pure).

    A branch that is a version of the library is synced, deleted too (the sync records
    ``ref_deleted`` on it). A tag the library's auto-sync ``tag_pattern`` matches starts the
    auto-import. Anything else (an untracked branch, a tag without auto-import, a deleted tag)
    queues nothing.

    Args:
        event: The verified delivery.
        versions: The library's versions.
        auto_sync: The library's scheduled check, if it has one.

    Returns:
        The refs to queue a ``push`` job for, in the payload's order.
    """
    branches = {v.ref for v in versions if v.kind is RefKind.BRANCH}
    return tuple(
        ref
        for ref in event.refs
        if (ref.kind is RefKind.BRANCH and ref.name in branches)
        or (
            ref.kind is RefKind.TAG
            and not ref.deleted
            and auto_sync is not None
            and auto_sync.matches(ref.name)
        )
    )


class Access(StrEnum):
    """The library role a caller needs for an action; the values are the role names."""

    READ = "viewer"
    """Search and read."""
    CONTRIBUTE = "contributor"
    """Import content: add versions, sync, tag articles."""
    ADMINISTER = "admin"
    """Configure the library and remove versions."""
    OWN = "creator"
    """Remove the library."""
