"""Pure ingestion logic: git URL parsing and article parsing (front matter, title, invisibles).

Parsing covers front matter, the title rule and removal of invisible characters. Nothing here
touches the filesystem or evaluates content. ``.mdx`` is plain Markdown: JSX, ``import`` and
``export`` lines stay in the body as text and are never executed.
"""

import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from itertools import pairwise, starmap
from operator import itemgetter
from pathlib import PurePosixPath
from typing import Any, NewType, Self
from urllib.parse import unquote, urlsplit

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from exactdocs.ingestion.errors import (
    AmbiguousRefError,
    CredentialProblem,
    InvalidChunkingConfigError,
    InvalidCredentialError,
    InvalidPathPatternError,
    InvalidProgressError,
    InvalidRepositoryUrlError,
    InvalidTagError,
    PatternProblem,
    TagProblem,
    UnknownRefError,
    UrlProblem,
)
from exactdocs_kernel import MAX_TAGS, normalize_tag

# Bump on any change to the sanitizer or the parser. It feeds the chunking-config hash (E4-02),
# so a fix here re-chunks stored articles instead of reusing stale chunk sets.
PARSER_VERSION = 3

# Bump on any change to how a chunker cuts articles. Like PARSER_VERSION it feeds the config hash.
CHUNKER_VERSION = 1
MAX_HEADING_LEVEL = 6

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
_README_MARKDOWN = MarkdownIt("commonmark").enable("table")  # a table is not a description


def malformed_front_matter_length(body: str) -> int:
    """Length of the broken front-matter block ``parse_article`` left at the start of ``body``."""
    match = _FRONT_MATTER.match(body)
    return match.end() if match else 0


def strip_invisible(text: str) -> str:
    """Remove invisible and control characters (see ``_ALWAYS_INVISIBLE``); change nothing else."""
    return _STRAY_JOINER.sub("", _ALWAYS_INVISIBLE.sub(lambda m: m["flag"] or "", text))


MAX_TAG_RULES = 64
_MAX_RAW_TAGS = 100


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
    named = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
    skipped = max(0, len(named) - _MAX_RAW_TAGS)  # not even normalized: bounded work
    normalized = [normalize_tag(tag) for tag in named[:_MAX_RAW_TAGS]]
    if (invalid := normalized.count(None) + skipped) or len(set(normalized)) > MAX_TAGS:
        problems.append(f"front matter tags: {invalid} invalid ignored, at most {MAX_TAGS} kept")
    declared_tags = tuple(dict.fromkeys(t for t in normalized if t))[:MAX_TAGS]
    description = front_matter.get("description")
    return ParsedArticle(
        path=path,
        title=_title(declared, body, path),
        body=body,
        tags=declared_tags,
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


README_TITLE_MAX = 120
README_DESCRIPTION_MAX = 500


@dataclass(frozen=True, slots=True)
class ReadmeSummary:
    """What a root README says about its library; ``None`` where it says nothing usable."""

    title: str | None = None
    description: str | None = None


def readme_summary(source: str) -> ReadmeSummary:
    """Take the first heading and the first paragraph after it from untrusted README text.

    Run through ``parse_article`` first, so invisible characters and front matter are gone. Only
    plain text is kept (no markup, images or HTML), whitespace is collapsed and the values are
    cut to ``README_TITLE_MAX`` / ``README_DESCRIPTION_MAX``. Paragraphs inside lists or quotes,
    and paragraphs with no text (badges, images), are skipped. Without a heading the first
    paragraph of the file is used.
    """
    tokens = _README_MARKDOWN.parse(parse_article("README.md", source).body)
    title, start = None, 0
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and (text := _inline_text(tokens[index + 1])):
            title, start = text[:README_TITLE_MAX].rstrip(), index
            break
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


def _inline_text(inline: Token, *, skip_link_only: bool = False) -> str:
    """Join the visible text of an inline token, collapsing whitespace.

    With ``skip_link_only`` a line that is nothing but links (a nav bar) gives ``""``.
    """
    words, outside, in_link = [], [], False
    for child in inline.children or []:
        match child.type:
            case "link_open":
                in_link = True
            case "link_close":
                in_link = False
            case "softbreak" | "hardbreak":
                words.append(" ")
                outside.append(" ")
            case "text" | "code_inline":
                words.append(child.content)
                if not in_link:
                    outside.append(child.content)
    if skip_link_only and not "".join(outside).strip(" |-*\u00b7\u2022"):
        return ""
    return " ".join("".join(words).split())


# ---------------------------------------------------------------- jobs

JobId = NewType("JobId", str)
JobKind = NewType("JobKind", str)
IMPORT_JOB = JobKind("import")
"""The kind of job that imports one version of a library."""
REFRESH_JOB = JobKind("refresh")
"""Imports a version the catalog has; fails if it was removed meanwhile (no resurrection)."""
IMPORT_KINDS = frozenset({IMPORT_JOB, REFRESH_JOB})
"""Kinds of job that import; removal waits for them and the sync state counts them."""
COLLECT_JOB = JobKind("collect")
"""The kind of job that frees what removed or replaced versions left on disk."""
DEFAULT_GRACE_SECONDS = 7 * 24 * 3600
"""How long a replaced manifest is kept so that its chunk IDs can still be recognized as stale."""


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
    FRONT_MATTER = "front_matter"
    """The article was imported, but its front matter is malformed or partly ignored."""
    TRUNCATED = "truncated"
    """The marker that says more files were skipped than ``MAX_JOB_PROBLEMS``."""

    @property
    def is_skip(self) -> bool:
        """Whether the file was left out of the version (as opposed to imported with a note)."""
        return self not in {ProblemCode.FRONT_MATTER, ProblemCode.TRUNCATED}


@dataclass(frozen=True, slots=True)
class FileProblem:
    """A problem with one file of an import: ``code`` is the stable kind, ``reason`` the text."""

    path: str
    code: ProblemCode
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Job:
    """A long task for one library (optionally one version) and how far it got.

    ``total`` is 0 until the job knows its size. ``chunked`` and ``reused`` count the articles an
    import cut into chunks and those whose chunks an earlier import had already stored.
    ``commit_sha`` is the commit the job's ``version`` was pinned to when it was queued,
    ``ref_kind`` what ``version`` is (a tag, a branch or a bare commit) as resolved then.
    Every transition returns a new job.
    """

    id: JobId
    kind: JobKind
    library: str
    version: str | None
    state: JobState
    commit_sha: str | None = None
    ref_kind: RefKind | None = None
    done: int = 0
    total: int = 0
    problems: tuple[FileProblem, ...] = ()
    notes: int = 0
    """How many of ``problems`` are notes on imported files (derived, not stored)."""
    chunked: int = 0
    reused: int = 0
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

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
    ) -> Self:
        """Create a job that waits for the worker."""
        return cls(
            id=job_id,
            kind=kind,
            library=library,
            version=version,
            commit_sha=commit_sha,
            ref_kind=ref_kind,
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

    def chunking(self, *, chunked: int, reused: int) -> Self:
        """Record how many articles were chunked now and how many reused stored chunks."""
        return replace(self, chunked=chunked, reused=reused)

    def with_problem(self, path: str, code: ProblemCode, reason: str) -> Self:
        """Record a problem with a file; the job goes on.

        Skips are kept up to ``MAX_JOB_PROBLEMS``, then counted in one ``truncated`` marker.
        Notes (``front_matter``) have a separate, lower ``MAX_JOB_NOTES`` and are dropped beyond
        it, so they can never crowd skips out.
        """
        if code is ProblemCode.FRONT_MATTER:
            if self.notes >= MAX_JOB_NOTES:
                return self
            problem = FileProblem(path, code, reason)
            return replace(self, problems=(*self.problems, problem), notes=self.notes + 1)
        if len(self.problems) - self.notes < MAX_JOB_PROBLEMS:
            return replace(self, problems=(*self.problems, FileProblem(path, code, reason)))
        # The marker is the last skip-sized entry; notes may have been appended after it.
        marker = next(
            (i for i, p in enumerate(self.problems) if p.code is ProblemCode.TRUNCATED), None
        )
        if marker is None:
            problem = FileProblem("", ProblemCode.TRUNCATED, _dropped_reason(1))
            return replace(self, problems=(*self.problems, problem))
        dropped = _dropped(self.problems[marker]) + 1
        problems = list(self.problems)
        problems[marker] = FileProblem("", ProblemCode.TRUNCATED, _dropped_reason(dropped))
        return replace(self, problems=tuple(problems))

    @property
    def skipped_count(self) -> int:
        """Files left out of the version, including the ones past the cap."""
        return sum(
            _dropped(p) if p.code is ProblemCode.TRUNCATED else p.code.is_skip
            for p in self.problems
        )

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
            chunked=0,
            reused=0,
            notes=0,
            error=None,
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


_KNOWN_HOSTS = {
    "github.com": RepositoryHost.GITHUB,
    "gitlab.com": RepositoryHost.GITLAB,
    "bitbucket.org": RepositoryHost.BITBUCKET,
    "gitea.com": RepositoryHost.GITEA,
    "codeberg.org": RepositoryHost.GITEA,
}
# These hosts have no nested groups: a longer path is a page (`/tree/main/docs`), not a repo.
_FLAT_HOSTS = frozenset(_KNOWN_HOSTS) - {"gitlab.com"}
_GIT_SUFFIX = re.compile(r"\.git\Z", re.IGNORECASE)
_SCHEMES = frozenset({"https", "http", "ssh", "file"})
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
_SSH_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
# `user@host:path`, git's scp-like syntax. The path cannot start with `:` (`ext::...`).
_SCP_LIKE = re.compile(
    r"(?P<user>[A-Za-z0-9_][A-Za-z0-9._-]*)@(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*):(?P<path>[^:].*)"
)
_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_ID_SEGMENTS = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryUrl:
    """A git URL that passed ``parse``: the text to hand to git, where it lives, a library ID.

    ``parse`` is the gate. It accepts only ``https``, ``http``, ``ssh`` (``ssh://`` and
    ``user@host:path``) and ``file`` URLs; refuses a leading ``-`` (an option), whitespace and
    control characters, transport helpers such as ``ext::`` and ``fd::``, ``git://``, and any
    credential, query or fragment in the URL. Nothing it raises repeats the input.
    """

    url: str
    host_kind: RepositoryHost
    library_id: ProposedId

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
        """Validate ``text`` and propose a library ID (``/owner/repo``, lower-case)."""
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
        if host in _FLAT_HOSTS and len(segments) != _ID_SEGMENTS:
            raise InvalidRepositoryUrlError(UrlProblem.PAGE_URL)
        owner, name = (segments[0] if top_level_owner else segments[-2]), segments[-1]
        name = _GIT_SUFFIX.sub("", name)
        return cls(
            url=url,
            host_kind=_host_kind(host),
            library_id=ProposedId(f"/{_id_segment(owner)}/{_id_segment(name)}"),
        )


def _split_url(url: str) -> tuple[str, list[str], bool]:
    """Check a ``scheme://`` URL; return its host, path segments and the owner-group flag."""
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
    segments = [unquote(s) for s in path.split("/") if s]
    if any(s in {".", ".."} or "/" in s for s in segments):
        raise InvalidRepositoryUrlError(UrlProblem.DOTS)
    return segments


def _is_host(host: str) -> bool:
    if _HOST.fullmatch(host):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _host_kind(host: str) -> RepositoryHost:
    return _KNOWN_HOSTS.get(host, RepositoryHost.GIT)


def _id_segment(raw: str) -> str:
    """Shape a path segment like a library ID segment (letters, digits, ``._-``), lower-case."""
    segment = _UNSAFE_ID_CHARS.sub("-", raw).strip("-").lower()
    if not segment or set(segment) == {"."}:
        raise InvalidRepositoryUrlError(UrlProblem.NO_ID)
    return segment


_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessToken:
    """An HTTPS token (a personal or project access token); ``username`` is what the host expects.

    GitHub and GitLab accept any user name next to a token; Bitbucket repository tokens want
    ``x-token-auth``. ``repr`` never shows the token.
    """

    token: str = field(repr=False)
    username: str = "x-access-token"

    def __post_init__(self) -> None:
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

    def __post_init__(self) -> None:
        key = self.private_key.replace("\r\n", "\n").strip()
        if not key:
            raise InvalidCredentialError(CredentialProblem.EMPTY)
        if len(key) > _MAX_KEY:
            raise InvalidCredentialError(CredentialProblem.TOO_LONG)
        lines = key.split("\n")
        if (
            not (lines[0].startswith("-----BEGIN ") and lines[0].endswith("PRIVATE KEY-----"))
            or not lines[-1].startswith("-----END ")
            or "ENCRYPTED" in lines[0]
            or any(not line.isprintable() for line in lines)
        ):
            raise InvalidCredentialError(CredentialProblem.KEY)
        object.__setattr__(self, "private_key", key + "\n")  # ssh wants the final newline


Credential = AccessToken | DeployKey
_MAX_TOKEN = 4096
_MAX_KEY = 16 * 1024
_TOKEN_USER = re.compile(r"[A-Za-z0-9._-]{1,100}")


def check_credential_fits(repository: RepositoryUrl, credential: Credential) -> None:
    """Refuse a credential the repository's transport cannot carry safely.

    A token over plain ``http://`` would cross the network in the clear, so only localhost (a
    local mirror, the test servers) may use it. A deploy key needs an SSH URL.
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
    """
    if isinstance(credential, AccessToken):
        body = {"kind": "token", "token": credential.token, "username": credential.username}
    else:
        body = {"kind": "ssh_key", "private_key": credential.private_key}
    return json.dumps({"library": library, "scope": scope, **body})


def load_credential(library: str, scope: str, text: str) -> Credential:
    """Inverse of ``dump_credential``; ``ValueError`` when it is for another library or host."""
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
    sha: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteRefs:
    """What ``git ls-remote`` saw: the branch ``HEAD`` points at (``None`` if unknown) and refs."""

    default_branch: str | None
    refs: tuple[RemoteRef, ...] = ()


_BAD_REF_CHARS = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
_MAX_BRANCH = 255


def branch_name(raw: str) -> str | None:
    """Return ``raw`` if it is a branch name git would accept (``git check-ref-format``), else None.

    The name comes from a remote, so it is also capped and checked for control characters
    before it is stored or shown.
    """
    parts = raw.split("/")
    ok = (
        0 < len(raw) <= _MAX_BRANCH
        and not _BAD_REF_CHARS.search(raw)
        and all(p and not p.startswith(".") and not p.endswith(".lock") for p in parts)
        and ".." not in raw
        and "@{" not in raw
        and not raw.startswith("-")
        and not raw.endswith((".", "/"))
        and raw.isprintable()
    )
    return raw if ok else None


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkingConfig:
    """How articles are cut. ``split_depth`` is the deepest heading level that starts a chunk."""

    split_depth: int = MAX_HEADING_LEVEL

    def __post_init__(self) -> None:
        if not 1 <= self.split_depth <= MAX_HEADING_LEVEL:
            raise InvalidChunkingConfigError


def chunking_config_hash(config: ChunkingConfig, engine: str = "") -> str:
    """Return the hash that keys chunk sets: the effective config plus both version constants.

    ``engine`` names the library an adapter cuts with and its version, so upgrading it re-chunks.

    A fix to the parser or the chunker changes it, so stored articles are re-chunked instead of
    reusing a chunk set made by older code.
    """
    payload = json.dumps(
        [PARSER_VERSION, CHUNKER_VERSION, config.split_depth, engine], separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass(frozen=True, slots=True, kw_only=True)
class ArticleChunk:
    """One section of an article. The contents of all chunks, joined, are the article body."""

    heading_path: tuple[str, ...]  # empty for the text before the first heading
    occurrence_index: int  # among chunks with the same heading path: 0, 1, ...
    position: int  # 0-based index in the article
    content: str
    content_hash: str
    anchor: str  # GitHub-style, unique in the article; empty before the first heading
    code_languages: tuple[str, ...] = ()


class RefKind(StrEnum):
    """What a requested ref turned out to be."""

    TAG = "tag"
    BRANCH = "branch"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedRef:
    """A ref pinned to a commit. For a commit, ``name`` is the full SHA."""

    name: str
    kind: RefKind
    commit_sha: str


_HEADS, _TAGS, _PEELED = "refs/heads/", "refs/tags/", "^{}"
_SHA_PREFIX = re.compile(r"[0-9a-f]{7,64}")


def ref_tips(refs: RemoteRefs) -> tuple[ResolvedRef, ...]:
    """List the branches then the tags a remote advertises, each sorted, with commit SHAs.

    An annotated tag points at a tag object; its ``^{}`` line carries the commit, which is used.
    """
    branches: dict[str, str] = {}
    tags: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for ref in refs.refs:
        if ref.name.startswith(_HEADS) and (name := branch_name(ref.name.removeprefix(_HEADS))):
            branches[name] = ref.sha
        elif ref.name.startswith(_TAGS):
            tag = ref.name.removeprefix(_TAGS)
            if tag.endswith(_PEELED):
                peeled[tag.removesuffix(_PEELED)] = ref.sha
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


ARTICLE_SUFFIXES = (".md", ".mdx")
_MAX_PATTERNS = 64
_MAX_PATTERN = 256
_MAX_PATH = 1024
_MAX_SEGMENT = 255
_GLOB_CHARS = frozenset("*?{")

type _Token = str | tuple[str, ...]  # text, or the alternatives of a `{a,b}`
_ANY, _ONE = "*", "?"  # as tokens they are the 1-tuples ("*",) and ("?",)
type _Segment = tuple[_Token, ...] | None  # None: `**`, any number of folders


@dataclass(frozen=True, slots=True)
class _Glob:
    segments: tuple[_Segment, ...]
    folder: bool  # a plain name also selects everything below it


def _segment(text: str) -> _Segment:
    """Split one path segment into tokens; ``**`` alone is a globstar."""
    if text == "**":
        return None
    tokens: list[_Token] = []
    literal = ""
    i = 0
    while i < len(text):
        char = text[i]
        if char in "*?{":
            if literal:
                tokens.append(literal)
                literal = ""
            if char == "{":
                end = text.find("}", i)
                if end < 0:
                    raise InvalidPathPatternError(PatternProblem.BRACE)
                tokens.append(("{", *text[i + 1 : end].split(",")))
                i = end
            elif not (char == "*" and tokens and tokens[-1] == (_ANY,)):  # `**` in a name is `*`
                tokens.append((char,))
        else:
            literal += char
        i += 1
    if literal:
        tokens.append(literal)
    return tuple(tokens)


@lru_cache(maxsize=512)
def _glob(pattern: str) -> _Glob:
    """Parse a cleaned pattern. Matching never backtracks: see ``_matches``."""
    folder = not _GLOB_CHARS & set(pattern)
    parts = pattern.split("/")
    if not parts[-1]:  # `docs/` is `docs/**`
        parts[-1] = "**"
    segments: list[_Segment] = []
    for part in parts:
        segment = _segment(part)
        if segment is None and segments and segments[-1] is None:
            continue  # `**/**` is `**`
        segments.append(segment)
    return _Glob(tuple(segments), folder)


def _name_matches(tokens: tuple[_Token, ...], name: str) -> bool:
    """Match one segment: the set of reachable positions, so the time is tokens x length."""
    if len(name) > _MAX_SEGMENT:
        return False
    reach = {0}
    for token in tokens:
        if isinstance(token, str):
            reach = {p + len(token) for p in reach if name.startswith(token, p)}
        elif token == (_ANY,):
            reach = set(range(min(reach), len(name) + 1)) if reach else set()
        elif token == (_ONE,):
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


@dataclass(frozen=True, slots=True)
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
    exclude: tuple[str, ...] = ()

    @classmethod
    def of(cls, include: Sequence[str] = (), exclude: Sequence[str] = ()) -> Self:
        """Validate and normalise the patterns (blank, duplicate-free, bounded)."""
        if len(include) + len(exclude) > _MAX_PATTERNS:
            raise InvalidPathPatternError(PatternProblem.TOO_MANY)
        return cls(
            include=tuple(dict.fromkeys(map(_clean_pattern, include))),
            exclude=tuple(dict.fromkeys(map(_clean_pattern, exclude))),
        )

    def selects(self, path: str) -> bool:
        """Tell whether the file at this repo-relative path is an article."""
        if not path.lower().endswith(ARTICLE_SUFFIXES):
            return False
        if any(_matches(_glob(p), path) for p in self.exclude):
            return False
        return not self.include or any(_matches(_glob(p), path) for p in self.include)


@dataclass(frozen=True, slots=True)
class TagRule:
    """Articles whose path matches the glob get the tag (``docs/api/** -> api``).

    The glob follows the rules of ``PathSelection`` (and so only ``.md``/``.mdx`` files match).
    """

    selection: PathSelection
    tag: str

    @classmethod
    def of(cls, pattern: str, tag: str) -> Self:
        """Validate the glob and normalize the tag; a tag that cannot be one is refused."""
        if (normalized := normalize_tag(tag)) is None:
            raise InvalidTagError(TagProblem.INVALID)
        return cls(PathSelection.of([pattern]), normalized)

    @classmethod
    def many(cls, pairs: Sequence[tuple[str, str]]) -> tuple[Self, ...]:
        """Build the rules of a library: bounded and duplicate-free."""
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
    """
    ruled = (rule.tag for rule in rules if rule.selection.selects(path))
    return tuple(dict.fromkeys((*ruled, *declared)))[:MAX_TAGS]


@dataclass(frozen=True, slots=True, kw_only=True)
class NewLibrary:
    """What a library is created from: its repository, default branch and doc selection."""

    library_id: ProposedId
    title: str
    source_url: str
    host: RepositoryHost
    default_branch: str | None
    selection: PathSelection
    tag_rules: tuple[TagRule, ...] = ()


# ---------------------------------------------------------------- import

DEFAULT_MAX_ARTICLE_BYTES = 2 * 2**20
"""Files above this many bytes are skipped without being read."""

DEFAULT_MAX_IMPORT_BYTES = 256 * 2**20
"""An import whose selected articles add up to more than this many bytes fails."""

MAX_JOB_PROBLEMS = 1000
MAX_JOB_NOTES = 200


def _dropped_reason(count: int) -> str:
    return f"{count} more skipped files are not listed"


def _dropped(marker: FileProblem) -> int:
    return int(marker.reason.split()[0])


"""Skipped files a job lists; the rest are only counted in a last entry."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportSource:
    """Where a library's articles come from and which of them are taken."""

    url: RepositoryUrl
    selection: PathSelection
    tag_rules: tuple[TagRule, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedArticle:
    """An article ready to publish: its text, metadata and chunks."""

    path: str
    blob_sha: str
    title: str
    tags: tuple[str, ...]
    front_matter: dict[str, Any]
    content: str
    chunks: tuple[ArticleChunk, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class GitRename:
    """A file git sees as moved between two commits: ``old_path`` became ``new_path``."""

    old_path: str
    new_path: str
    similarity: int
    """Percent of the content kept (100: moved unchanged); git reports renames from 50."""

    def __post_init__(self) -> None:
        if not 0 < self.similarity <= MAX_SIMILARITY:
            message = f"similarity must be 1..{MAX_SIMILARITY}, not {self.similarity}"
            raise ValueError(message)


MAX_SIMILARITY = 100
MAX_RENAMES = 10_000
"""Renames kept per version; git lists more only for a rewrite of the whole tree."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedVersion:
    """Every article of one library version at one commit, chunked with ``config_hash``."""

    library: str
    ref: str
    kind: RefKind
    commit_sha: str
    config_hash: str
    articles: tuple[ImportedArticle, ...]
    refresh: bool = False
    """The version must still exist when it is stored (a re-sync never re-creates a removed one)."""
    renamed_from: str | None = None
    """The ref whose commit ``renames`` were detected against; ``None`` when none were."""
    renames: tuple[GitRename, ...] = ()


def git_blob_sha(data: bytes) -> str:
    """Return the SHA-1 git gives a file with exactly these bytes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Removed:
    """What the catalog took out: the manifests other domains must forget, the new default."""

    library: str
    ref: str | None
    manifest_ids: tuple[str, ...]
    default_ref: str | None


@dataclass(frozen=True, slots=True)
class Collected:
    """What one collector deleted."""

    deleted: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedRef:
    """A version a library has: its ref, what kind of ref it is and the commit it serves."""

    ref: str
    kind: RefKind
    commit_sha: str


_NUMERIC_REF = re.compile(r"[vV]?(\d{1,9}(?:\.\d{1,9}){0,7})")


def _numbers(ref: str) -> tuple[int, ...] | None:
    match = _NUMERIC_REF.fullmatch(ref)
    return tuple(map(int, match[1].split("."))) if match else None


def _precedes(older: tuple[int, ...], newer: tuple[int, ...]) -> bool:
    """Tell whether ``older`` is a lower version; ``1.4`` and ``1.4.0`` are the same one."""
    width = max(len(older), len(newer))
    return older + (0,) * (width - len(older)) < newer + (0,) * (width - len(newer))


def previous_version(ref: str, imported: Sequence[ImportedRef]) -> ImportedRef | None:
    """Pick the version whose commit renames are detected against when ``ref`` is imported.

    A numeric ref (``v1.4.0``, ``2.1``) is compared with the highest lower numeric tag, never
    with itself, so a re-sync of it gives the same map. A ref without an order (a branch, a
    commit) is compared with what it served before, if it was imported; ``None`` otherwise.
    Pre-releases and other names have no order and get ``None`` as well.
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
    """Tell whether renames of ``ref`` build up over its syncs (it has no place in an order)."""
    return _numbers(ref) is None


def compose_renames(
    earlier: Sequence[GitRename], latest: Sequence[GitRename], articles: Collection[str]
) -> tuple[GitRename, ...]:
    """Chain a branch's earlier renames with the ones of its latest sync.

    ``A -> B`` earlier and ``B -> C`` now gives ``A -> C`` (the lower similarity); renames of
    the latest sync stay too, unless their old path is one the earlier map already tells about.
    Entries whose target is not an article any more, or that came back to their old path, go.
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


ACTIVE_JOB_STATES = frozenset({JobState.QUEUED, JobState.RUNNING})
"""A job in one of these states is unfinished: at most one import per (library, ref) may be."""


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
