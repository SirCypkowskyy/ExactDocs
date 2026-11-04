"""Ingestion entities and pure logic: jobs, and article parsing.

Parsing covers front matter, the title rule and removal of invisible characters. Nothing here
touches the filesystem or evaluates content. ``.mdx`` is plain Markdown: JSX, ``import`` and
``export`` lines stay in the body as text and are never executed.
"""

import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Any, NewType, Self

import yaml
from markdown_it import MarkdownIt

from exactdocs.ingestion.errors import InvalidProgressError

# Bump on any change to the sanitizer or the parser. It feeds the chunking-config hash (E4-02),
# so a fix here re-chunks stored articles instead of reusing stale chunk sets.
PARSER_VERSION = 2

# Characters that render as nothing (or as a control) but reach an LLM as text: zero-width
# space and friends, the byte order mark, bidi controls (Trojan Source), Unicode "tag"
# characters and supplementary variation selectors (byte smuggling), invisible math operators,
# fillers, the blank Braille cell, and C0/C1 controls except tab, newline and carriage return
# (ANSI escapes, NUL). Everything else, including every visible character and the regular
# variation selectors next to emoji, is left alone. Known cost: LRM/RLM/ALM and the Mongolian
# vowel separator also have typographic uses, so punctuation placement in RTL text can change.
_ALWAYS_INVISIBLE = re.compile(
    # a subdivision flag (England, Scotland, Wales...) is visible text, keep it whole
    r"(?P<flag>\N{WAVING BLACK FLAG}"
    r"[\N{TAG DIGIT ZERO}-\N{TAG DIGIT NINE}"
    r"\N{TAG LATIN SMALL LETTER A}-\N{TAG LATIN SMALL LETTER Z}]"
    r"{2,7}\N{CANCEL TAG})"
    r"|[\N{ZERO WIDTH SPACE}\N{WORD JOINER}\N{ZERO WIDTH NO-BREAK SPACE}"
    r"\N{MONGOLIAN VOWEL SEPARATOR}"
    r"\N{ARABIC LETTER MARK}\N{LEFT-TO-RIGHT MARK}\N{RIGHT-TO-LEFT MARK}"
    r"\N{LEFT-TO-RIGHT EMBEDDING}-\N{RIGHT-TO-LEFT OVERRIDE}"  # embeddings, pop, overrides
    r"\N{LEFT-TO-RIGHT ISOLATE}-\N{POP DIRECTIONAL ISOLATE}"
    r"\N{FUNCTION APPLICATION}-\N{INVISIBLE PLUS}"  # invisible math operators
    r"\N{COMBINING GRAPHEME JOINER}"
    r"\N{HANGUL CHOSEONG FILLER}\N{HANGUL JUNGSEONG FILLER}\N{HANGUL FILLER}"
    r"\N{HALFWIDTH HANGUL FILLER}\N{KHMER VOWEL INHERENT AQ}\N{KHMER VOWEL INHERENT AA}"
    r"\N{BRAILLE PATTERN BLANK}"
    r"\N{VARIATION SELECTOR-17}-\N{VARIATION SELECTOR-256}"
    r"\N{LANGUAGE TAG}-\N{CANCEL TAG}"  # Unicode tag characters
    r"\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"  # C0 and C1 controls, not \t \n \r
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


class NotJsonSafeError(ValueError):
    """Front matter holds values that cannot be stored as standard JSON."""

    def __init__(self) -> None:
        super().__init__(
            "values must be text, numbers, booleans, null, lists or maps with text keys"
        )


_NO_ALIASES = "anchors and aliases are not allowed"


class _FrontMatterLoader(yaml.SafeLoader):
    """Safe YAML loader without anchors and aliases and with dates kept as text.

    Aliases would let a few hundred bytes expand into gigabytes once the metadata is serialised
    (and make it recursive), so they are rejected while the document is composed.
    """

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node | None:
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            raise yaml.MarkedYAMLError(problem=_NO_ALIASES, problem_mark=event.start_mark)
        return super().compose_node(parent, index)


_FrontMatterLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_MARKDOWN = MarkdownIt("commonmark")


def strip_invisible(text: str) -> str:
    """Remove invisible and control characters (see ``_ALWAYS_INVISIBLE``); change nothing else."""
    return _STRAY_JOINER.sub("", _ALWAYS_INVISIBLE.sub(lambda m: m["flag"] or "", text))


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
    metadata is empty and the reason is listed in ``problems``. A leading ``---`` block that is
    not a mapping (a thematic break around prose) is just body text, with no problem.
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

    declared = front_matter.get("title")
    if declared is not None and not isinstance(declared, str):
        problems.append("front matter title must be text")
    tags = front_matter.get("tags")
    if isinstance(tags, str):
        tags = tags.split(",")
    if tags is not None and not isinstance(tags, list):
        problems.append("front matter tags must be a list or a string")
        tags = []
    tags = tags or []
    if not all(isinstance(tag, str) for tag in tags):
        problems.append("front matter tags must be text; other items were ignored")
    description = front_matter.get("description")
    return ParsedArticle(
        path=path,
        title=_title(declared, body, path),
        body=body,
        tags=tuple(
            dict.fromkeys(t for tag in tags if isinstance(tag, str) and (t := tag.strip().lower()))
        ),
        description=description if isinstance(description, str) else None,
        front_matter=front_matter,
        problems=tuple(problems),
    )


def _load_front_matter(text: str) -> object:
    loader = _FrontMatterLoader(text)
    try:
        loaded = loader.get_single_data()
    finally:
        loader.dispose()
    if not _is_json_safe(loaded):
        raise NotJsonSafeError
    return loaded


def _is_json_safe(value: object) -> bool:
    """Tell whether standard JSON can hold it (no bytes, sets, dates, NaN or Infinity)."""
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
    """Say what is wrong and where, without echoing the file's content."""
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark:
        # +2: the front matter starts on line 2 (after the opening ---), marks are 0-based
        where = f"at line {error.problem_mark.line + 2}"
        return f"{_NO_ALIASES} {where}" if error.problem == _NO_ALIASES else f"invalid YAML {where}"
    return str(error) if isinstance(error, ValueError) else "invalid YAML"


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


# ---------------------------------------------------------------- jobs

JobId = NewType("JobId", str)
JobKind = NewType("JobKind", str)


class JobState(StrEnum):
    """Where a job is in its life. Only ``queued`` and ``running`` jobs are unfinished."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FileProblem:
    """A file a job skipped, and why."""

    path: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Job:
    """A long task for one library (optionally one version) and how far it got.

    ``total`` is 0 until the job knows its size. Every transition returns a new job.
    """

    id: JobId
    kind: JobKind
    library: str
    version: str | None
    state: JobState
    done: int = 0
    total: int = 0
    problems: tuple[FileProblem, ...] = ()
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def queued(
        cls, *, job_id: JobId, kind: JobKind, library: str, version: str | None, now: datetime
    ) -> Self:
        """Create a job that waits for the worker."""
        return cls(
            id=job_id,
            kind=kind,
            library=library,
            version=version,
            state=JobState.QUEUED,
            created_at=now,
        )

    def started(self, now: datetime) -> Self:
        """Mark the job as picked up by the worker."""
        return replace(self, state=JobState.RUNNING, started_at=now)

    def progressed(self, *, done: int, total: int) -> Self:
        """``done`` of ``total`` files processed so far."""
        if not 0 <= done <= total:
            raise InvalidProgressError(done, total)
        return replace(self, done=done, total=total)

    def with_problem(self, path: str, reason: str) -> Self:
        """Record a skipped file; the job goes on."""
        return replace(self, problems=(*self.problems, FileProblem(path, reason)))

    def succeeded(self, now: datetime) -> Self:
        """Mark the job as finished."""
        return replace(self, state=JobState.SUCCEEDED, finished_at=now)

    def failed(self, error: str, now: datetime) -> Self:
        """Mark the job as stopped with ``error``."""
        return replace(self, state=JobState.FAILED, error=error, finished_at=now)

    def requeued(self) -> Self:
        """Run again from the beginning, as if never started."""
        return replace(
            self,
            state=JobState.QUEUED,
            done=0,
            total=0,
            problems=(),
            error=None,
            started_at=None,
            finished_at=None,
        )
