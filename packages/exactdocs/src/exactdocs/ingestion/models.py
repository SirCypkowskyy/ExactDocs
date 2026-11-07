"""Pure ingestion logic: git URL parsing and article parsing (front matter, title, invisibles).

Parsing covers front matter, the title rule and removal of invisible characters. Nothing here
touches the filesystem or evaluates content. ``.mdx`` is plain Markdown: JSX, ``import`` and
``export`` lines stay in the body as text and are never executed.
"""

import base64
import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from fnmatch import fnmatchcase
from functools import lru_cache
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
    FLAT_HOSTS,
    GLOB_CHARS,
    HEADS,
    KNOWN_HOSTS,
    MAX_CHECK_ERROR,
    MAX_CHUNK_CHARS,
    MAX_CONTEXT7_RULE_CHARS,
    MAX_CONTEXT7_RULES,
    MAX_HEADING_LEVEL,
    MAX_IMAGES_PER_ARTICLE,
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
    TAGS,
    JobKind,
)
from exactdocs.ingestion.constants._models import (
    _ALWAYS_INVISIBLE,
    _BAD_REF_CHARS,
    _FRONT_MATTER,
    _GIT_SUFFIX,
    _HOST,
    _ID_SEGMENTS,
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
    PatternProblem,
    TagProblem,
    UnknownRefError,
    UrlProblem,
)
from exactdocs_kernel import MAX_TAGS, normalize_tag


class NotJsonSafeError(ValueError):
    """Front matter holds values that cannot be stored as standard JSON."""

    def __init__(self) -> None:
        super().__init__(
            "values must be text, numbers, booleans, null, lists or maps with text keys"
        )


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
_markdown = MarkdownIt("commonmark")
_readme_markdown = MarkdownIt("commonmark").enable("table")  # a table is not a description


def malformed_front_matter_length(body: str) -> int:
    """Length of the broken front-matter block ``parse_article`` left at the start of ``body``."""
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
    """
    if front_matter or not malformed_front_matter_length(content):
        return ()
    reparsed = parse_article(path, content)
    if reparsed.body != content or not reparsed.problems:
        return ()  # a mapping (so taken from a file) or not YAML front matter at all: Markdown
    return reparsed.problems if git_blob_sha(content.encode()) == blob_sha else None


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
    images: tuple[str, ...] = ()
    """Repository paths of the images the body references by a relative link (``image_paths``)."""


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
    """Return the tags a parsed front matter declares, and the notes on its title and tags."""
    problems: list[str] = []
    declared = front_matter.get("title")
    if declared is not None and not isinstance(declared, str):
        problems.append("front matter title must be text")
    tags, tag_problems = front_matter_tags(front_matter)
    return tags, [*problems, *tag_problems]


def _description(front_matter: Mapping[str, Any]) -> str | None:
    description = front_matter.get("description")
    return description if isinstance(description, str) else None


def front_matter_tags(front_matter: Mapping[str, Any]) -> tuple[tuple[str, ...], list[str]]:
    """Return the normalized tags a front matter declares, and what was wrong with them.

    ``tags`` is a list or a comma-separated string; invalid items are dropped, at most
    ``MAX_TAGS`` kept. Pure, so the tags of a stored article can be derived again from its
    stored front matter (re-tagging without a fetch).
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
    description: str | None = None


def readme_summary(source: str) -> ReadmeSummary:
    """Take the first heading and the first paragraph after it from untrusted README text.

    Run through ``parse_article`` first, so invisible characters and front matter are gone. Only
    plain text is kept (no markup, images or HTML), whitespace is collapsed and the values are
    cut to ``README_TITLE_MAX`` / ``README_DESCRIPTION_MAX``. Paragraphs inside lists or quotes,
    and paragraphs with no text (badges, images), are skipped. Without a heading the first
    paragraph of the file is used.
    """
    tokens = _readme_markdown.parse(parse_article("README.md", source).body)
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

    @property
    def is_skip(self) -> bool:
        """Whether the file was left out of the version (as opposed to imported with a note)."""
        return self not in {ProblemCode.FRONT_MATTER, ProblemCode.TRUNCATED, ProblemCode.CONTEXT7}


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
    code: ProblemCode
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Job:
    """A long task for one library (optionally one version) and how far it got.

    ``total`` is 0 until the job knows its size. ``chunked`` and ``reused`` count the articles an
    import cut into chunks and those whose chunks an earlier import had already stored;
    ``parsed`` and ``taken`` the articles it parsed and those it took as an earlier import had
    stored them.
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
    parsed: int = 0
    taken: int = 0
    error: str | None = None
    error_code: str | None = None
    """The stable code of ``error``: a ``SyncErrorCode``, an error's own code or ``unexpected``."""
    origin: VersionOrigin = VersionOrigin.MANUAL
    """Who queued it; the first import of a version gives the version this origin."""
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
        origin: VersionOrigin = VersionOrigin.MANUAL,
    ) -> Self:
        """Create a job that waits for the worker."""
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

    def parsing(self, *, parsed: int, taken: int) -> Self:
        """Record how many articles were parsed now and how many taken as stored before."""
        return replace(self, parsed=parsed, taken=taken)

    def with_problem(self, path: str, code: ProblemCode, reason: str) -> Self:
        """Record a problem with a file; the job goes on.

        Skips are kept up to ``MAX_JOB_PROBLEMS``, then counted in one ``truncated`` marker.
        Notes (``front_matter``) have a separate, lower ``MAX_JOB_NOTES`` and are dropped beyond
        it, so they can never crowd skips out.
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
        """Mark the job as finished."""
        return replace(self, state=JobState.SUCCEEDED, finished_at=now)

    def failed(self, error: str, now: datetime, *, code: str | None = None) -> Self:
        """Mark the job as stopped with ``error`` (the text) and its stable ``code``."""
        return replace(self, state=JobState.FAILED, error=error, error_code=code, finished_at=now)

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
    return RepositoryHost(KNOWN_HOSTS.get(host, RepositoryHost.GIT))


def _id_segment(raw: str) -> str:
    """Shape a path segment like a library ID segment (letters, digits, ``._-``), lower-case."""
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
    heading. ``None`` means no upper bound. ``chunker`` is one of ``CHUNKERS``.
    """

    split_depth: int = MAX_HEADING_LEVEL
    min_chars: int = 0
    max_chars: int | None = None
    chunker: str = DEFAULT_CHUNKER

    def __post_init__(self) -> None:
        if not 1 <= self.split_depth <= MAX_HEADING_LEVEL:
            raise InvalidChunkingConfigError
        if not 0 <= self.min_chars <= MAX_CHUNK_CHARS:
            reason = f"min_chars must be between 0 and {MAX_CHUNK_CHARS}"
            raise InvalidChunkingConfigError(reason)
        if self.max_chars is not None and not 1 <= self.max_chars <= MAX_CHUNK_CHARS:
            reason = f"max_chars must be between 1 and {MAX_CHUNK_CHARS}"
            raise InvalidChunkingConfigError(reason)
        if self.max_chars is not None and self.max_chars < self.min_chars:
            reason = "max_chars must not be smaller than min_chars"
            raise InvalidChunkingConfigError(reason)
        if self.chunker not in CHUNKERS:
            reason = f"chunker must be one of {', '.join(sorted(CHUNKERS))}"
            raise InvalidChunkingConfigError(reason)


def chunking_config_hash(config: ChunkingConfig, engine: str = "") -> str:
    """Return the hash that keys chunk sets: the effective config plus both version constants.

    ``engine`` names the library an adapter cuts with and its version, so upgrading it re-chunks.

    A fix to the parser or the chunker changes it, so stored articles are re-chunked instead of
    reusing a chunk set made by older code. The size bounds and the chunker are added only when
    they differ from the defaults, so the chunk sets stored before they existed stay valid.
    Every other config can merge headings into a chunk, so its hash also names
    ``MERGED_HEADINGS_VERSION``: the chunks record those headings, and a set cut before they did
    is cut again instead of reused. The default config cuts at every heading, so its chunk sets
    already tell every heading and keep their hash.
    """
    fields: list[object] = [PARSER_VERSION, CHUNKER_VERSION, config.split_depth, engine]
    extra = (config.min_chars, config.max_chars, config.chunker)
    if extra != (0, None, DEFAULT_CHUNKER):
        fields.extend(extra)
    if config != ChunkingConfig():  # it can merge headings, which its chunks now record
        fields.append(f"headings-{MERGED_HEADINGS_VERSION}")
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
    """Among chunks with the same heading path: 0, 1, ..."""
    position: int
    """0-based index in the article."""
    content: str
    content_hash: str
    anchor: str
    """GitHub-style, unique in the article; empty before the first heading."""
    code_languages: tuple[str, ...] = ()
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
    kind: RefKind
    commit_sha: str


def ref_tips(refs: RemoteRefs) -> tuple[ResolvedRef, ...]:
    """List the branches then the tags a remote advertises, each sorted, with commit SHAs.

    An annotated tag points at a tag object; its ``^{}`` line carries the commit, which is used.
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
    segments: tuple[_Segment, ...]
    folder: bool
    """A plain name also selects everything below it."""


def _segment(text: str) -> _Segment:
    """Split one path segment into tokens; ``**`` alone is a globstar."""
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
    """Parse a cleaned pattern. Matching never backtracks: see ``_matches``."""
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
    """Match one segment: the set of reachable positions, so the time is tokens x length."""
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


@dataclass(frozen=True, slots=True, kw_only=True)
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
        return cls(selection=PathSelection.of([pattern]), tag=normalized)

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
class PreviousVersion:
    """An older tag a ``context7.json`` offers for import, with its optional display title."""

    tag: str
    title: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Context7Config:
    """What a repository's ``context7.json`` says, validated and ready to apply.

    ``selection`` is ``folders`` / ``excludeFolders`` / ``excludeFiles`` as ``PathSelection``
    patterns (see ``context7_selection``), or ``None`` when the file names none of them. All
    text is untrusted repository text: title and description are flattened and cut like a
    README's, every rule is one printable line.
    """

    project_title: str | None = None
    description: str | None = None
    folders: tuple[str, ...] = ()
    exclude_folders: tuple[str, ...] = ()
    exclude_files: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    previous_versions: tuple[PreviousVersion, ...] = ()
    selection: PathSelection | None = None
    notes: tuple[str, ...] = ()
    """What was left out of an otherwise usable file (``previousVersions`` entries), and why."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FetchedFile:
    """One file of a commit read on its own: its bytes, nothing (absent), or why it was not read."""

    data: bytes | None = None
    problem: str | None = None


def parse_context7(data: bytes) -> Context7Config:
    """Validate the bytes of a ``context7.json``; ``InvalidContext7Error`` says why it is unusable.

    Only the keys ExactDocs uses are read (``projectTitle``, ``description``, ``folders``,
    ``excludeFolders``, ``excludeFiles``, ``rules``, ``previousVersions``); any other key
    (``$schema``, ``url``, ...) is ignored. A known key of the wrong type, too many rules or
    versions, or a path ExactDocs would refuse makes the whole file unusable: half-applying a
    file would import something nobody asked for. A ``previousVersions`` entry that cannot be
    imported (no tag, or one git would not take as a ref name) only offers nothing: it is left
    out and named in ``notes``.
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
    """
    stripped = entry.strip()
    cleaned = stripped.removeprefix("./").lstrip("/").rstrip("/")
    return cleaned, stripped.startswith(("./", "/")) or "/" in cleaned


def _c7_root(folder: str) -> bool:
    return _c7_path(folder)[0] in {"", "."}


def _c7_folder(folder: str) -> str:
    cleaned, _ = _c7_path(folder)
    return cleaned if GLOB_CHARS & set(cleaned) else f"{cleaned}/"


def _c7_exclude(entry: str, *, folder: bool) -> str:
    cleaned, anchored = _c7_path(entry)
    if GLOB_CHARS & set(cleaned):
        return cleaned
    suffix = "/" if folder else ""
    return f"{cleaned}{suffix}" if anchored else f"**/{cleaned}{suffix}"


def _c7_strings(document: dict[str, Any], key: str) -> tuple[str, ...]:
    value = document.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        reason = f"{key} must be a list of strings"
        raise InvalidContext7Error(reason)
    return tuple(value)


def _c7_text(document: dict[str, Any], key: str) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        reason = f"{key} must be a string"
        raise InvalidContext7Error(reason)
    return _c7_line(value, key) or None


def _c7_line(value: str, key: str) -> str:
    """Flatten to one line; a control or invisible formatting character makes the file unusable."""
    line = " ".join(value.split())
    if not line.isprintable():
        reason = f"{key} has control or invisible characters"
        raise InvalidContext7Error(reason)
    return line


def _c7_previous_versions(value: object) -> tuple[tuple[PreviousVersion, ...], tuple[str, ...]]:
    """Return the importable entries and a note for each one that is left out."""
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
    """Validate one entry; a string says why it cannot be offered (never echoes control text)."""
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
    title: str
    source_url: str
    host: RepositoryHost
    default_branch: str | None
    selection: PathSelection
    tag_rules: tuple[TagRule, ...] = ()


# ---------------------------------------------------------------- import


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
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)


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


def sniff_image(data: bytes) -> str | None:
    """Name the allowed image type by the content (never by the file name), else ``None``.

    PNG, JPEG, GIF, WebP and SVG. An SVG is a document whose root element is ``<svg``; one that
    declares entities is refused (nothing here parses it, but a browser would expand them).
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
    blob_sha: str
    content_type: str
    data: bytes = field(repr=False)


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


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedVersion:
    """Every article of one library version at one commit, chunked with ``config_hash``."""

    library: str
    ref: str
    kind: RefKind
    commit_sha: str
    config_hash: str
    articles: tuple[ImportedArticle, ...]
    images: tuple[ImportedImage, ...] = ()
    refresh: bool = False
    """The version must still exist when it is stored (a re-sync never re-creates a removed one)."""
    renamed_from: str | None = None
    """The ref whose commit ``renames`` were detected against; ``None`` when none were."""
    renames: tuple[GitRename, ...] = ()
    origin: VersionOrigin = VersionOrigin.MANUAL
    """Given to the version when this creates it; a version that exists keeps its own."""


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


type ArticleTags = Mapping[str, tuple[str, ...]]
"""Article path -> every tag the article carries now."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TaggedPath:
    """Manual tags the catalog stored for a path, and the manifests whose articles they touched."""

    library: str
    path: str
    tags: tuple[str, ...]
    retagged: Mapping[str, ArticleTags]
    """Manifest ID -> its touched articles."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredArticleTags:
    """What a stored article's imported tags are derived from, and what they are now."""

    path: str
    front_matter: Mapping[str, Any]
    tags: tuple[str, ...]
    """Imported: path rules and front matter (manual tags are kept apart)."""

    def retagged(self, rules: Sequence[TagRule]) -> tuple[str, ...]:
        """Return the imported tags the article gets under ``rules`` (as an import would)."""
        return article_tags(self.path, front_matter_tags(self.front_matter)[0], rules)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredArticle:
    """What an import stored for a file: an import of the same file takes it instead of parsing.

    Found by path, git blob SHA and ``PARSER_VERSION``: the title and the image links depend on
    the path, everything else on the bytes and the parser. Tags are not stored here: they are
    derived again (path rules are the library's settings, which may have changed).
    """

    path: str
    blob_sha: str
    title: str
    front_matter: Mapping[str, Any]
    content: str

    def parsed(self) -> ParsedArticle | None:
        """Return what ``parse_article`` gives the file, rebuilt without parsing it.

        ``None`` when only a parse can tell whether the front matter was malformed (kept in the
        body, with a note to list again; ``stored_front_matter_problems``).
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
    articles: tuple[StoredArticleTags, ...]


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
    blob_sha: str
    title: str
    front_matter: Mapping[str, Any]
    tags: tuple[str, ...]
    """Imported: path rules and front matter (manual tags are kept apart)."""
    content: str

    def parsed(self) -> ParsedArticle | None:
        """Return the article as the parser gave it: what a chunker cuts.

        ``None`` when only a parse of the file can tell whether its front matter was malformed
        (``stored_front_matter_problems``): the version is then re-imported.
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
    commit_sha: str
    articles: tuple[CopiedArticle, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Collected:
    """What one collector deleted."""

    deleted: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedRef:
    """A version a library has: its ref, what kind of ref it is and the commit it serves."""

    ref: str
    kind: RefKind
    commit_sha: str
    origin: VersionOrigin = VersionOrigin.MANUAL
    pinned: bool = False
    """The library's owner pinned it as the default version (LIB-10): retention keeps it."""


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
    tag_pattern: str | None = None
    keep_last: int = DEFAULT_KEEP_LAST
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    sync_branches: bool = False
    checked_at: datetime | None = None
    last_error: str | None = None
    revision: str = ""
    """Changes on every save of the settings: a check records itself only on the one it read."""

    def __post_init__(self) -> None:
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
        """Tell whether the tag is one to import automatically (case-sensitive glob)."""
        return self.tag_pattern is not None and fnmatchcase(tag, self.tag_pattern)

    @property
    def next_check_at(self) -> datetime | None:
        """When the library is due again; ``None``: at the next tick of the schedule."""
        if self.checked_at is None:
            return None
        return self.checked_at + timedelta(minutes=self.interval_minutes)

    def is_due(self, now: datetime) -> bool:
        """Tell whether the scheduled check should look at the library ``now``."""
        due = self.next_check_at
        return due is None or now >= due

    def checked(self, now: datetime, error: str | None) -> Self:
        """Record that a check ended at ``now``, with what it could not do."""
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
    """Rank a numeric ref: ``1.4`` equals ``1.4.0``, and the name breaks a tie."""
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
