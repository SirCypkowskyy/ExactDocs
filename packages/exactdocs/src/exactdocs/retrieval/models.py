"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from itertools import groupby
from typing import NewType

from exactdocs.retrieval.errors import DuplicateChunkError, EmptySearchTextError
from exactdocs_kernel import section_link


@dataclass(frozen=True, slots=True, kw_only=True)
class DocTarget:
    """The exact library version a search is pinned to. Version is a hard filter."""

    library: str
    version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchText:
    """What the agent is looking for: an identifier, an error code or a question."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise EmptySearchTextError


def _is_mark(char: str) -> bool:
    return unicodedata.category(char).startswith("M")


def _is_segment_char(char: str) -> bool:
    return char.isalnum() or _is_mark(char)


def _is_word_char(char: str) -> bool:
    return _is_segment_char(char) or char in "_.-"


def identifier_tokens(text: str) -> str:
    """Text for the extra indexed column: every word whole, plus its parts when it has several.

    `retryPolicy` -> `retrypolicy retry policy`, `--dry-run` -> `--dry-run dry run`. Apply it
    once to chunk text when indexing and to the query when searching, so both sides see the same
    tokens. Parts split on `_`, `-`, `.`, case changes (`HTTPServer` -> `http server`) and
    letter/digit changes (`base64` -> `base 64`). Output is NFC-normalized and casefolded
    (`Straße` and `STRASSE` agree); combining marks stay inside their word. Leading dots and
    trailing dots/dashes are stripped from the whole (`.env` -> `env`), leading dashes are kept.

    Contract for the search adapters:

    - The column must be tokenized so that `-`, `_` and `.` stay inside a token: FTS5
      `tokenize="unicode61 tokenchars '-_.'"`; the pg_search configuration (E12-02) must match.
      With the default `unicode61` the whole tokens (`max_retries`, `--dry-run`) are lost.
    - Query tokens are alternatives: `split()` the result and OR / rank them. Do not match them
      as one phrase or AND them, or a query `retryPolicy` misses prose that says `retry policy`.
    """
    tokens: list[str] = []
    for is_word, run in groupby(unicodedata.normalize("NFC", text), _is_word_char):
        if not is_word:
            continue
        candidate = "".join(run)
        whole = candidate.lstrip(".").rstrip(".-").casefold()
        parts = [
            part.casefold()
            for is_segment, segment in groupby(candidate, _is_segment_char)
            if is_segment
            for part in _split_case("".join(segment))
        ]
        if parts:
            tokens.append(whole)
            tokens.extend(parts if len(parts) > 1 or parts[0] != whole else [])
    return " ".join(tokens)


def _split_case(segment: str) -> list[str]:
    """Split one alphanumeric run at lower->Upper, ACRONYMWord and letter<->digit boundaries."""
    parts: list[str] = []
    start = 0
    for i in range(1, len(segment)):
        prev, cur = segment[i - 1], segment[i]
        after = segment[i + 1] if i + 1 < len(segment) else ""
        if not _is_mark(cur) and (
            prev.isdigit() != cur.isdigit()
            or (cur.isupper() and (not prev.isupper() or after.islower()))
        ):
            parts.append(segment[start:i])
            start = i
    parts.append(segment[start:])
    return parts


_WORD = re.compile(r"[\w.-]+")

ChunkId = NewType("ChunkId", str)
type ChunkSetKey = tuple[str, str]  # (git blob SHA, chunking-config hash)


def chunk_id(
    version_id: str,
    article_path: str,
    heading_path: Sequence[str],
    occurrence_index: int,
    content_hash: str,
) -> ChunkId:
    """Return the ID of a chunk inside one version, a pure function of where and what it is.

    ``version_id`` is ``<library>/<ref>`` (`/acme/payments/main`). The same section of an
    unchanged article keeps its ID when the version moves to a new commit, and the same blob in
    another version gets another ID, so ``read_chunk`` names exactly one chunk. The fields are
    JSON-encoded so no separator can make two different inputs collide.
    """
    payload = json.dumps(
        [version_id, article_path, list(heading_path), occurrence_index, content_hash],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ChunkId(hashlib.sha256(payload.encode()).hexdigest()[:32])


@dataclass(frozen=True, slots=True, kw_only=True)
class Chunk:
    """One section of an article, as the chunker cut it."""

    heading_path: tuple[str, ...]
    occurrence_index: int  # 0 for the first heading with this text, 1 for the next one, ...
    content: str
    content_hash: str
    anchor: str
    code_languages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkSet:
    """The ordered chunks of one blob under one chunking config; shared by every version."""

    blob_sha: str
    config_hash: str
    chunks: tuple[Chunk, ...]

    @property
    def key(self) -> ChunkSetKey:
        """Where the set is stored."""
        return (self.blob_sha, self.config_hash)

    @property
    def digest(self) -> str:
        """Fingerprint of the chunks, to notice a set stored under the same key but cut differently.

        A key is (blob, ``config_hash``); the caller must change ``config_hash`` whenever the
        chunker changes. The repository compares digests so a forgotten bump fails loudly.
        """
        parts = [
            [list(c.heading_path), c.occurrence_index, c.content_hash, c.anchor]
            for c in self.chunks
        ]
        return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestChunk:
    """A chunk as one manifest sees it: its ID, its place in the article and the article's tags."""

    chunk_id: ChunkId
    article_path: str
    position: int  # 0-based index in the article
    total: int
    prev_chunk_id: ChunkId | None
    next_chunk_id: ChunkId | None
    tags: tuple[str, ...]
    chunk_set: ChunkSetKey


@dataclass(frozen=True, slots=True, kw_only=True)
class SectionRef:
    """A chunk of an article without its text: enough to tell sections apart."""

    chunk_id: ChunkId
    position: int
    heading_path: tuple[str, ...]
    occurrence_index: int
    content_hash: str
    anchor: str


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexedManifest:
    """A catalog manifest that has chunk rows. Its ID is held by value."""

    manifest_id: str
    version_id: str  # `<library>/<ref>`, as in `chunk_id`
    library: str
    indexed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredChunk:
    """A chunk with its content, as ``read_chunk`` returns it."""

    manifest_id: str
    version_id: str  # `<library>/<ref>` the manifest was indexed under
    row: ManifestChunk
    chunk: Chunk


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchHit:
    """One chunk a search found: higher ``score`` is better, scores only compare within a search."""

    chunk_id: ChunkId
    score: float
    snippet: str  # verbatim text of the chunk (no marker added), possibly cut at either end
    highlights: tuple[tuple[int, int], ...]  # [start, end) offsets into ``snippet``, in order


@dataclass(frozen=True, slots=True)
class ManifestHit:
    """A hit of a search over several manifests: which manifest (so which library) it came from."""

    manifest_id: str
    hit: SearchHit


def search_terms(query: str) -> list[str]:
    """Return the distinct alternatives a query is matched by: each word whole and by its parts."""
    return list(dict.fromkeys(identifier_tokens(query).split()))


def highlights(text: str, terms: Collection[str]) -> tuple[tuple[int, int], ...]:
    """Return ``[start, end)`` offsets of the words of ``text`` that match any of ``terms``.

    A word matches when one of its `identifier_tokens` is a term, so `retryPolicy` is marked for
    the query `retry`. Every search engine marks its snippets with this, so they agree.
    """
    wanted = set(terms)
    spans = []
    for match in _WORD.finditer(text):
        if wanted & set(identifier_tokens(match.group()).split()):
            word = match.group()
            start = match.start() + len(word) - len(word.lstrip("."))
            spans.append((start, match.end() - (len(word) - len(word.rstrip(".-")))))
    return tuple(spans)


@dataclass(frozen=True, slots=True, kw_only=True)
class Removed:
    """What a discard or collection deleted."""

    manifests: int
    chunk_sets: int


class ManifestStatus(StrEnum):
    """What the catalog says about a manifest ID; an unknown ID is absent from its answer."""

    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    OTHER = "other"  # a state this domain does not know; never remove such a manifest


def article_chunk_rows(
    version_id: str,
    article_path: str,
    chunk_set: ChunkSet,
    tags: tuple[str, ...],
) -> list[ManifestChunk]:
    """Return the rows one article contributes to a manifest, linked to their neighbours."""
    ids = [
        chunk_id(version_id, article_path, c.heading_path, c.occurrence_index, c.content_hash)
        for c in chunk_set.chunks
    ]
    if len(set(ids)) != len(ids):
        raise DuplicateChunkError(article_path)
    return [
        ManifestChunk(
            chunk_id=id_,
            article_path=article_path,
            position=i,
            total=len(ids),
            prev_chunk_id=ids[i - 1] if i else None,
            next_chunk_id=ids[i + 1] if i + 1 < len(ids) else None,
            tags=tags,
            chunk_set=chunk_set.key,
        )
        for i, id_ in enumerate(ids)
    ]


class TagMatch(StrEnum):
    """How a tag filter combines its tags."""

    ANY = "any"
    ALL = "all"


@dataclass(frozen=True, slots=True, kw_only=True)
class TagFilter:
    """Which chunks may be ranked: those whose article has any / all of ``tags``.

    No tags keeps everything. The filter is applied before ranking, so the top ``limit`` are
    the best of the matching chunks, not the matching part of the best chunks.
    """

    tags: tuple[str, ...] = ()
    match: TagMatch = TagMatch.ANY

    def keeps(self, chunk_tags: Collection[str]) -> bool:
        """Tell whether a chunk with these tags passes."""
        wanted = set(self.tags)
        if self.match is TagMatch.ALL:
            return wanted <= set(chunk_tags)
        return not wanted or bool(wanted & set(chunk_tags))


class RetrievalMode(StrEnum):
    """How a search found its results. One result shape serves every mode."""

    BM25 = "bm25"


class SourceHost(StrEnum):
    """Where the documented repository is hosted; ``git`` is any other server."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GITEA = "gitea"
    GIT = "git"


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchableVersion:
    """A library version a search may run on: exactly this version's active manifest."""

    library: str
    version: str
    manifest_id: str
    commit_sha: str
    repository_url: str
    host: SourceHost
    rules: tuple[str, ...] = ()
    """The library's ``context7.json`` rules (LIB-06), untrusted repository text."""


def source_link(version: SearchableVersion, article_path: str, anchor: str) -> str | None:
    """Link to the section at the version's commit, or ``None`` for hosts we cannot build one for.

    Pinned to the commit SHA, so the link keeps showing the text the search returned.
    """
    return section_link(
        version.host.value, version.repository_url, version.commit_sha, article_path, anchor
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLibrary:
    """A library as the catalog lists it. Title and description are untrusted repository text."""

    id: str
    title: str
    description: str
    source_url: str
    default_version: str | None
    versions: tuple[str, ...]
    version_count: int
    last_imported_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionCounts:
    """What one version holds: articles (with at least one chunk) and chunks."""

    articles: int
    chunks: int


class NameMatch(IntEnum):
    """How well a library name matches a library; lower is better. See ``name_match``."""

    ID = 0  # `/owner/repo` or `owner/repo`
    EXACT = 1  # the repo segment or the title, ignoring case and punctuation
    PREFIX = 2  # the repo segment or the title starts with the name
    PART = 3  # the name is inside the ID or title, or all its words are
    DESCRIPTION = 4  # only the description has all its words


def _squash(text: str) -> str:
    """Lowercase, letters and digits only: ``Next.js`` and ``nextjs`` and ``next-js`` agree."""
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^\w]+", unicodedata.normalize("NFKC", text).casefold()) if w}


# Words agents add to a library's name ("fastapi docs"); matched with and without them.
STOP_WORDS = frozenset({"docs", "doc", "documentation", "library", "lib", "sdk", "api", "the"})


def _match_once(name: str, library: CatalogLibrary) -> NameMatch | None:
    """Try the tiers best first, each only when the better ones failed (the description is dear)."""
    wanted = _squash(name)
    if not wanted:
        return None
    names = [_squash(library.id.rsplit("/", 1)[-1]), _squash(library.title)]
    words = _words(name)
    tiers = [
        (NameMatch.ID, lambda: wanted == _squash(library.id)),
        (NameMatch.EXACT, lambda: wanted in names),
        (NameMatch.PREFIX, lambda: any(n.startswith(wanted) for n in names)),
        (
            NameMatch.PART,
            lambda: (
                any(wanted in n for n in [*names, _squash(library.id)])
                or words <= _words(f"{library.id} {library.title}")
            ),
        ),
        (NameMatch.DESCRIPTION, lambda: words <= _words(library.description)),
    ]
    return next((tier for tier, holds in tiers if holds()), None)


def name_match(name: str, library: CatalogLibrary) -> NameMatch | None:
    """Match a library name against ID, title and description in memory; ``None`` is no match.

    The name is tried as written and without ``STOP_WORDS``; the better match counts. A name with
    no letter or digit matches nothing. Ties are broken by ``rank_matches``.
    """
    kept = " ".join(w for w in re.split(r"[^\w]+", name) if w and w.casefold() not in STOP_WORDS)
    found = [m for n in {name, kept} if (m := _match_once(n, library)) is not None]
    return min(found, default=None)


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """A library whose name matched, with how many chunks of its default version match the query."""

    library: CatalogLibrary
    match: NameMatch
    hits: int = 0


def rank_matches(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Order candidates, best first, by these rules in order.

    1. A library named by its ID comes first, whatever the query finds.
    2. A name found in the ID or title beats one found only in the description.
    3. An exact or prefix name beats a mere part of a name (``react`` before ``preact``).
    4. Within that, a library with hits for the query beats one without.
    5. A closer name match (exact, then prefix).
    6. More hits.
    7. The library ID, so equal candidates always come out in the same order.
    """

    def key(c: Candidate) -> tuple[int, int, int, int, int, int, str]:
        return (
            int(c.match is not NameMatch.ID),
            int(c.match is NameMatch.DESCRIPTION),
            int(c.match >= NameMatch.PART),
            int(c.hits == 0),
            c.match,
            -c.hits,
            c.library.id,
        )

    return sorted(candidates, key=key)


# Spellings of a fence language that mean the same as another; anything else compares by lowercase.
_LANGUAGE_ALIASES = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "jsx": "javascript",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "golang": "go",
    "c#": "csharp",
    "cs": "csharp",
    "yml": "yaml",
    "rb": "ruby",
    "rs": "rust",
    "cpp": "c++",
    "cc": "c++",
    "hpp": "c++",
    "cxx": "c++",
    "kt": "kotlin",
    "py3": "python",
    "python3": "python",
    "ps1": "powershell",
    "node": "javascript",
    "nodejs": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "objc": "objective-c",
    "dockerfile": "docker",
}


def canonical_language(name: str) -> str:
    """Return a code language in one spelling, so `TypeScript`, `ts` and `typescript` agree."""
    lowered = name.strip().lower()
    return _LANGUAGE_ALIASES.get(lowered, lowered)


def language_first[T](
    items: Sequence[T], languages: Callable[[T], Sequence[str]], wanted: str
) -> list[T]:
    """Put the items with code in ``wanted`` first; each group keeps its order (sort is stable)."""
    want = canonical_language(wanted)
    return sorted(items, key=lambda i: want not in {canonical_language(x) for x in languages(i)})


# What the `query-docs` payload adds around its parts, counted against the budget by the use case
# and produced by the driving adapter (a test holds the adapter to these numbers).
# A section is `### title\n\nSource: src\n\nChunk: id\n\ncontent`, sections are separated by 36
# characters; 4 + 10 + 9 + 2 + 36 = 61 <= 64. Title, source, ID and content are counted on top.
SECTION_FRAMING_CHARS = 64
# The closing line "N more matching chunks did not fit the size budget; narrow the query." and its
# separator, reserved whenever the answer could be partial.
FOOTER_CHARS = 140
# The rules block "### Rules from the repository's context7.json (...)\n\n- rule\n- rule" and its
# separator: the heading and separator, then each rule's "- " and newline. The rules are counted
# on top, and the block takes at most RULES_SHARE of the room, so documentation always fits too.
RULES_FRAMING_CHARS = 192
RULE_FRAMING_CHARS = 3
RULES_SHARE = 4  # rules use at most 1/RULES_SHARE of the budget
CHARS_PER_TOKEN = 4  # undercounts for CJK text and dense code, which cost more tokens per character
POINTER_TEXT = "Too large for the size budget; fetch it with read_chunk."
