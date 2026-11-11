"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum, StrEnum
from itertools import groupby
from typing import NewType, NoReturn
from urllib.parse import urlsplit, urlunsplit

from exactdocs.retrieval.constants import (
    _EXCLUDED_KINDS,
    _HOSTED_KINDS,
    _KIND_FIELDS,
    _LANGUAGE_ALIASES,
    _OPTIONAL_KIND_FIELDS,
    _SELF_HOSTED_KINDS,
    _WORD,
    BUDGET_NOT_POSITIVE,
    BUDGET_WITHOUT_CEILING,
    CHARS_PER_TOKEN,
    CREDENTIAL_HEADER_SUFFIXES,
    CREDENTIAL_HEADERS,
    DEFAULT_MODE_ORDER,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RERANK_TIMEOUT,
    DEFAULT_RERANK_TOP_N,
    DEFAULT_RETRIES,
    DNS_LABEL,
    EMBEDDING_INPUT_FORMAT,
    HEADER_NAME,
    HEADING_SEPARATOR,
    LIBRARY_BUDGET_NOT_LIBRARY,
    LIBRARY_BUDGET_TWICE,
    MASK,
    MAX_EMBEDDING_DIMENSIONS,
    MAX_FLOAT32,
    MAX_HEADER_VALUE,
    MAX_HEADERS,
    MAX_MODEL_NAME,
    MAX_REQUEST_TIMEOUT,
    MAX_RETRIES,
    MICROS_PER_USD,
    MONTHS_PER_YEAR,
    PROFILE_NAME,
    RATE_LIMIT_BELOW_ONE,
    REPLAY_RETAIN_DAYS,
    SPEND_INSTANCE_ID,
    SPEND_SCOPE_EMBEDDING,
    SPEND_SCOPE_INSTANCE,
    SPEND_SCOPE_KINDS,
    SPEND_SCOPE_LIBRARY,
    SPEND_SCOPE_USER,
    STOP_WORDS,
    TOKENS_PER_MILLION,
)
from exactdocs.retrieval.errors import (
    DuplicateChunkError,
    EmptySearchTextError,
    InvalidBudgetError,
    InvalidEmbeddingSpaceError,
    InvalidModelRefError,
    InvalidProviderError,
    InvalidVectorError,
    LibraryBudgetAboveInstanceError,
    UnavailableModeError,
    UnknownSpendKeyError,
    VectorDimensionError,
)
from exactdocs_kernel import section_link


@dataclass(frozen=True, slots=True, kw_only=True)
class DocTarget:
    """The exact library version a search is pinned to. Version is a hard filter."""

    library: str
    version: str


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- one-field value object
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
      `tokenize="unicode61 tokenchars '-_.'"`; `pg_search`'s `_PG_SEARCH_PATTERN` matches.
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


ChunkId = NewType("ChunkId", str)
type ChunkSetKey = tuple[str, str]  # (git blob SHA, chunking-config hash)
type ChunkKey = tuple[str, str, int]
"""One stored chunk: (git blob SHA, chunking-config hash, position in its chunk set).

Shared by every manifest that holds the blob with the same chunking, so a vector keyed by it is
computed once for all of them.
"""


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
class ChunkHeading:
    """One heading a chunk holds: a chunking config may merge several headings into one chunk."""

    heading_path: tuple[str, ...]
    """The heading and every heading above it."""
    anchor: str
    """The heading's own anchor in the article."""
    starts_chunk: bool
    """True for the heading the chunk is named after; false for one merged into it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Chunk:
    """One section of an article, as the chunker cut it."""

    heading_path: tuple[str, ...]
    occurrence_index: int
    """0 for the first heading with this text, 1 for the next one, ..."""
    content: str
    content_hash: str
    anchor: str
    code_languages: tuple[str, ...] = ()
    headings: tuple[ChunkHeading, ...] | None = None
    """Every heading the chunk holds, in order; ``None`` for a chunk stored before they were
    recorded. Not part of ``ChunkSet.digest``: they follow from the text and the config hash."""


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
    position: int
    """0-based index in the article."""
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
    headings: tuple[ChunkHeading, ...] | None = None
    """Every heading the chunk holds, in order; ``None`` when they were not recorded."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OutlineEntry:
    """Where one heading of an outline is: the chunk that holds it and its own anchor."""

    chunk_id: ChunkId
    """The chunk that starts with this heading, or that it was merged into."""
    anchor: str
    """The heading's own anchor in the article."""
    starts_chunk: bool
    """False when the chunking merged this heading into a chunk another heading starts."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OutlineNode:
    """One heading of an article's outline and the headings under it, in document order."""

    heading: str
    """The heading's text, untrusted repository text."""
    entry: OutlineEntry | None
    """The chunk that holds this heading; ``None`` when no chunk records it (a chunk stored
    before heading records existed, whose first heading is a deeper one)."""
    children: tuple[OutlineNode, ...]
    """The headings directly under it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Outline:
    """The heading tree of one article, made from its chunks' heading paths (no text)."""

    preamble: SectionRef | None
    """The chunk before the first heading, when the article has one."""
    sections: tuple[OutlineNode, ...]
    """The top-level headings."""


def outline(sections: Sequence[SectionRef]) -> Outline:
    """Build the heading tree of an article from its sections, given in document order.

    Every heading a section records becomes a node pointing to that section: the one it starts
    with, and those the chunking config merged into it (``starts_chunk`` false). A section stored
    before heading records existed gives its own (last) heading only, so headings merged into it
    are missing until its library is re-chunked. Two headings with the same path are two sibling
    nodes; an ancestor heading no section records is a node without an entry.

    Args:
        sections: The article's sections, ordered by position.

    Returns:
        The tree, with the text before the first heading (if a chunk) apart as the preamble.
    """
    preamble = next((s for s in sections if not s.heading_path), None)
    headings = [h for s in sections for h in _outline_headings(s)]
    return Outline(preamble=preamble, sections=_outline_nodes(headings, 0))


type _Heading = tuple[tuple[str, ...], OutlineEntry]
"""A heading path and where the heading is."""


def _outline_headings(section: SectionRef) -> list[_Heading]:
    """List the headings a section holds, in order, each with where it is.

    Args:
        section: One section of the article.

    Returns:
        Its recorded headings, or its own heading when none were recorded (none for a preamble).
    """
    if section.headings is None:
        if not section.heading_path:
            return []
        entry = OutlineEntry(chunk_id=section.chunk_id, anchor=section.anchor, starts_chunk=True)
        return [(section.heading_path, entry)]
    return [
        (
            h.heading_path,
            OutlineEntry(chunk_id=section.chunk_id, anchor=h.anchor, starts_chunk=h.starts_chunk),
        )
        for h in section.headings
        if h.heading_path
    ]


def _outline_nodes(headings: Sequence[_Heading], depth: int) -> tuple[OutlineNode, ...]:
    """Group headings whose paths are all longer than ``depth`` into nodes at ``depth``.

    Args:
        headings: Consecutive headings in document order, each deeper than ``depth``.
        depth: The index of the heading in each heading path that names the nodes.

    Returns:
        One node per heading at ``depth``, each with the deeper headings that follow it.
    """
    nodes: list[OutlineNode] = []
    start = 0
    while start < len(headings):
        path, entry = headings[start]
        prefix = path[: depth + 1]
        own = entry if len(path) == depth + 1 else None
        end = start + 1
        while (
            end < len(headings)
            and len(headings[end][0]) > depth + 1
            and headings[end][0][: depth + 1] == prefix
        ):
            end += 1
        below = headings[start + 1 if own else start : end]
        nodes.append(
            OutlineNode(heading=prefix[-1], entry=own, children=_outline_nodes(below, depth + 1))
        )
        start = end
    return tuple(nodes)


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexedManifest:
    """A catalog manifest that has chunk rows. Its ID is held by value."""

    manifest_id: str
    version_id: str
    """`<library>/<ref>`, as in `chunk_id`"""
    library: str
    indexed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredChunk:
    """A chunk with its content, as ``read_chunk`` returns it."""

    manifest_id: str
    version_id: str
    """`<library>/<ref>` the manifest was indexed under."""
    row: ManifestChunk
    chunk: Chunk


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchHit:
    """One chunk a search found: higher ``score`` is better, scores only compare within a search."""

    chunk_id: ChunkId
    score: float
    snippet: str
    """Verbatim text of the chunk (no marker added), possibly cut at either end."""
    highlights: tuple[tuple[int, int], ...]
    """[start, end) offsets into ``snippet``, in order."""


@dataclass(frozen=True, slots=True, kw_only=True)
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


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchIndexState:
    """The format the stored search index was built in, against the one this build writes.

    A format names how entries are made from chunks (columns, tokenizer, ``identifier_tokens``).
    An index in an older format still answers, built the old way, until it is rebuilt. One in a
    newer format (written by a later release, before a downgrade) is left as it is.
    ``stored_format`` is ``None`` when no format is recorded; a rebuild records it.
    """

    stored_format: int | None
    current_format: int
    engine: SearchEngine
    """The search engine that answers."""

    @property
    def needs_rebuild(self) -> bool:
        """Whether the index is older than this build writes, or its format is unknown."""
        return self.stored_format is None or self.stored_format < self.current_format


@dataclass(frozen=True, slots=True, kw_only=True)
class RebuiltIndex:
    """What a rebuild left: the format it is now in and how many chunks it holds."""

    format: int
    entries: int


class SearchEngine(StrEnum):
    """The engine that answers full-text searches (``/healthz`` reports it)."""

    FTS5 = "fts5"
    """SQLite: FTS5's BM25."""
    PG_SEARCH = "pg_search"
    """PostgreSQL with ParadeDB's `pg_search` extension: BM25."""
    POSTGRES_FTS = "postgres_fts"
    """PostgreSQL without `pg_search`: its full-text search, ranked with `ts_rank_cd`."""
    MEMORY = "memory"
    """The in-memory reference index (tests only)."""


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


class ModelRole(StrEnum):
    """A model an operator can configure; which ones are set decides the modes on offer.

    No mode needs ``judge`` to run; the LLM judge (#96) uses it to rerank. It defaults to the
    ``llm`` role.
    """

    EMBEDDING = "embedding"
    """Turns chunks and queries into vectors (hybrid search). Instance-wide only."""
    RERANKER = "reranker"
    """Reorders the best candidates of any mode (reranking is a flag on top of a mode)."""
    LLM = "llm"
    """Writes hypothetical answers (HyDE) and drives the agentic explorer."""
    JUDGE = "judge"
    """An LLM that grades candidates (#96); the ``llm`` role when it is not set."""


class RetrievalMode(StrEnum):
    """How a search found its results. One result shape serves every mode."""

    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_HYDE = "hybrid_hyde"
    AGENTIC = "agentic"

    @property
    def roles(self) -> frozenset[ModelRole]:
        """The model roles this mode cannot run without (BM25 needs none).

        Returns:
            The roles that must all be configured.
        """
        match self:
            case RetrievalMode.BM25:
                return frozenset()
            case RetrievalMode.HYBRID:
                return frozenset({ModelRole.EMBEDDING})
            case RetrievalMode.HYBRID_HYDE:
                return frozenset({ModelRole.EMBEDDING, ModelRole.LLM})
            case RetrievalMode.AGENTIC:
                return frozenset({ModelRole.LLM})

    @property
    def needs_vectors(self) -> bool:
        """Say whether this mode searches the vector store (the hybrid ones do).

        Returns:
            True when the mode cannot run without the vector store.
        """
        return self in {RetrievalMode.HYBRID, RetrievalMode.HYBRID_HYDE}

    @property
    def needs_llm(self) -> bool:
        """Say whether this mode has an LLM step (HyDE, the agentic explorer).

        Returns:
            True when budgets and the LLM search rate limit apply to it.
        """
        return ModelRole.LLM in self.roles


class FallbackReason(StrEnum):
    """Why a search was answered by a cheaper mode than the one it would have used."""

    MODE_UNAVAILABLE = "mode_unavailable"
    """The library's or the instance's mode needs a model role that is not configured now."""
    EMBEDDING_IN_PROGRESS = "embedding_in_progress"
    """The version is not embedded with the current model yet."""
    LLM_BUDGET_REACHED = "llm_budget_reached"
    """A spend limit stopped the LLM step."""
    LLM_RATE_LIMITED = "llm_rate_limited"
    """Too many LLM searches in the last minute."""
    VECTOR_STORE_UNAVAILABLE = "vector_store_unavailable"
    """The vector store cannot be loaded here (sqlite-vec), so no hybrid mode can run."""
    RERANKER_TIMEOUT = "reranker_timeout"
    """The reranker did not answer in time: the candidates keep the order the mode found."""
    RERANKER_FAILED = "reranker_failed"
    """The reranker failed (an error, a bad answer, a profile that cannot rerank): the candidates
    keep the order the mode found."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModeChoice:
    """The mode a search runs in, whether it reranks, and why a better mode was skipped."""

    mode: RetrievalMode
    """The mode whose pipeline runs."""
    rerank: bool
    """A reranker is configured: the best candidates are reordered after the pipeline."""
    fallback_reason: FallbackReason | None = None
    """Why the library's or the instance's mode was skipped, if it was."""
    rerank_top_n: int = 0
    """How many of the best candidates the reranker reorders (the library's, else the
    instance's); 0 when there is no reranking."""
    library_ai: LibraryAi | None = None
    """The library's AI overrides as read for this search, so the reranker and the library's own
    budgets resolve from the same read; ``None`` when the choice was not made for a library."""
    caller: str | None = None
    """The account the search counts to (set with the budgets, ``within_budget``); ``None`` for a
    stdio MCP process."""
    cheaper: RetrievalMode = RetrievalMode.BM25
    """The best mode without an LLM step: what answers when a budget or the rate limit skips
    the LLM step of ``mode``."""

    def without_llm(self, reason: FallbackReason) -> ModeChoice:
        """Fall back to the cheaper mode, saying why.

        Args:
            reason: ``llm_budget_reached`` or ``llm_rate_limited``.

        Returns:
            The cheaper choice, reranking as before.
        """
        return replace(self, mode=self.cheaper, fallback_reason=reason)


@dataclass(frozen=True, slots=True, kw_only=True)
class ModeRegistry:
    """The modes this instance can run now: a pipeline is built for it and its roles are set.

    A configured mode that is no longer available (its role was removed, or the vector store
    cannot be loaded) never fails a search: it falls back with ``mode_unavailable`` or
    ``vector_store_unavailable``. Only a mode the caller asks for fails.
    """

    roles: frozenset[ModelRole]
    """The model roles configured now."""
    pipelines: frozenset[RetrievalMode]
    """The modes this build has a pipeline for; BM25 always."""
    vector_store: bool = True
    """The vector store can search here; without it no mode that ``needs_vectors`` runs."""

    def missing_roles(self, mode: RetrievalMode) -> tuple[ModelRole, ...]:
        """Name the roles ``mode`` needs that are not configured.

        Args:
            mode: The mode to check.

        Returns:
            The missing roles, in ``ModelRole`` order; empty when none is missing.
        """
        return tuple(r for r in ModelRole if r in mode.roles - self.roles)

    def blocked_by_vector_store(self, mode: RetrievalMode) -> bool:
        """Say whether only the vector store keeps ``mode`` from running.

        Args:
            mode: The mode to check.

        Returns:
            True when it has a pipeline and its roles, but needs the vector store, which is down.
        """
        return (
            mode in self.pipelines
            and not self.missing_roles(mode)
            and mode.needs_vectors
            and not self.vector_store
        )

    def is_available(self, mode: RetrievalMode) -> bool:
        """Say whether ``mode`` can run now.

        Args:
            mode: The mode to check.

        Returns:
            True when it has a pipeline, every role it needs and, if it needs one, the vector store.
        """
        return (
            mode in self.pipelines
            and not self.missing_roles(mode)
            and (self.vector_store or not mode.needs_vectors)
        )

    def available(self) -> tuple[RetrievalMode, ...]:
        """List the modes that can run now.

        Returns:
            The available modes, in ``RetrievalMode`` order (BM25 first).
        """
        return tuple(m for m in RetrievalMode if self.is_available(m))

    def best(self) -> RetrievalMode:
        """Pick the default when nothing is set: HyDE, then hybrid, then BM25.

        Returns:
            The best available mode.
        """
        return next(
            RetrievalMode(m) for m in DEFAULT_MODE_ORDER if self.is_available(RetrievalMode(m))
        )

    def check(self, name: str) -> RetrievalMode:
        """Turn a mode name (any letter case) into a mode that can run now.

        Args:
            name: The mode as a caller or an admin wrote it.

        Returns:
            The mode.

        Raises:
            UnavailableModeError: The name is unknown, or the mode cannot run now.
        """
        available = [m.value for m in self.available()]
        try:
            mode = RetrievalMode(name.strip().lower())
        except ValueError:
            raise UnavailableModeError(name, available, []) from None
        if not self.is_available(mode):
            missing = [r.value for r in self.missing_roles(mode)]
            raise UnavailableModeError(
                name, available, missing, vector_store=not self.blocked_by_vector_store(mode)
            )
        return mode

    def _skipped(self, mode: RetrievalMode) -> FallbackReason:
        """Say why a configured mode cannot run.

        Args:
            mode: The library's or the instance's mode, not available now.

        Returns:
            ``vector_store_unavailable`` when only the vector store is missing, else
            ``mode_unavailable``.
        """
        if self.blocked_by_vector_store(mode):
            return FallbackReason.VECTOR_STORE_UNAVAILABLE
        return FallbackReason.MODE_UNAVAILABLE

    def choose(
        self,
        *,
        asked: str | None,
        library: RetrievalMode | None,
        instance: RetrievalMode | None,
    ) -> ModeChoice:
        """Pick the mode: the call's, else the library's, else the instance's, else the best.

        Args:
            asked: The mode the call asked for, if any.
            library: The library's setting, if any.
            instance: The instance's setting, if any.

        Returns:
            The choice; ``fallback_reason`` says why a setting was skipped (the first one
            skipped), or ``vector_store_unavailable`` when the best mode would have been a
            hybrid one but the vector store is down. A call that asks for a mode that cannot
            run fails (``check``).
        """
        rerank = ModelRole.RERANKER in self.roles
        cheaper = self.without_llm().best()
        if asked is not None:
            return ModeChoice(mode=self.check(asked), rerank=rerank, cheaper=cheaper)
        reason: FallbackReason | None = None
        for setting in (library, instance):
            if setting is None:
                continue
            if self.is_available(setting):
                return ModeChoice(
                    mode=setting, rerank=rerank, fallback_reason=reason, cheaper=cheaper
                )
            reason = reason or self._skipped(setting)
        best = self.best()
        if reason is None and not self.vector_store:
            with_store = ModeRegistry(roles=self.roles, pipelines=self.pipelines)
            if with_store.best() != best:
                reason = FallbackReason.VECTOR_STORE_UNAVAILABLE
        return ModeChoice(mode=best, rerank=rerank, fallback_reason=reason, cheaper=cheaper)

    def without_llm(self) -> ModeRegistry:
        """Return the registry as it would be with no LLM: what a budget leaves to run.

        Returns:
            The same registry without the ``llm`` and ``judge`` roles.
        """
        return replace(self, roles=self.roles - {ModelRole.LLM, ModelRole.JUDGE})


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
class PipelineRequest:
    """What a retrieval pipeline searches: one exact version, never another."""

    version: SearchableVersion
    """The exact version; every hit must come from its manifest."""
    query: str
    """The query text."""
    tag_filter: TagFilter
    """Which chunks may be returned, applied before ranking."""
    limit: int
    """How many hits to return at most."""
    rerank: bool
    """The best candidates are reranked after the pipeline: ``limit`` already counts the top N
    that the reranker reorders, so the pipeline need not rerank itself."""
    space: EmbeddingSpace | None = None
    """The embedding space a mode that searches vectors must search: the configured model's, which
    the caller checked covers ``version``. Never look up the active space instead: during a switch
    of models it is another model's. ``None`` when no embedding model resolves (BM25 modes)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineAnswer:
    """What a pipeline found, and how: the mode that really answered may be a cheaper one."""

    mode: RetrievalMode
    """The mode that answered: the one asked for, or a cheaper one."""
    hits: tuple[SearchHit, ...]
    """At most the asked limit, best first, all from the requested version."""
    candidates: int
    """Matching chunks looked at (a lower bound)."""
    reranked: int
    """Of those, how many a reranker reordered."""
    complete: bool
    """False when more matches exist than the limit allowed."""
    fallback_reason: FallbackReason | None = None
    """Why a cheaper mode answered, if one did."""

    def cut(self, limit: int) -> PipelineAnswer:
        """Keep the best ``limit`` hits of an answer that holds more (the reranker's top N).

        Args:
            limit: How many hits the caller asked for.

        Returns:
            The answer with at most ``limit`` hits; not complete when hits were left out.
        """
        if len(self.hits) <= limit:
            return self
        return replace(self, hits=self.hits[:limit], complete=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class RerankLimits:
    """How much of a search the reranker may take: the instance's setting (``[ai.reranker]``)."""

    top_n: int = DEFAULT_RERANK_TOP_N
    """How many of the best candidates are reranked; a library may set its own."""
    timeout: float = DEFAULT_RERANK_TIMEOUT
    """How long a search gives the reranker to be built and to answer, in seconds, before it keeps
    its order; the candidates' text is read before the clock starts."""


def reorder(hits: Sequence[SearchHit], scores: Sequence[float]) -> tuple[SearchHit, ...]:
    """Order the first hits by the reranker's scores; the rest keep their place after them.

    Args:
        hits: The candidates, best first as the mode found them.
        scores: The reranker's score of each of the first ``len(scores)`` hits, in their order.

    Returns:
        The reranked hits, highest score first (ties keep the mode's order), each carrying its
        reranker score, then the hits that were not reranked, unchanged.
    """
    head = sorted(zip(hits, scores, strict=False), key=lambda pair: -pair[1])
    return (
        *(replace(hit, score=score) for hit, score in head),
        *hits[len(scores) :],
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


# ---------------------------------------------------------------- AI provider profiles (#241)
class ProviderKind(StrEnum):
    """What a provider profile talks to; each maps to one pydantic-ai provider and model class.

    See the table in docs/decisions/ai-retrieval.md (*Provider abstraction*). Kinds whose SDK is
    not in ``exactdocs[ai]`` (Bedrock, Groq, Mistral, Cohere, xAI, Hugging Face) are reached as
    ``openai-compatible`` or through ``litellm``.
    """

    OPENAI_COMPATIBLE = "openai-compatible"
    """Any gateway speaking the OpenAI Chat Completions API: a base URL, an optional key."""
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    ANTHROPIC = "anthropic"
    """Claude: the Anthropic API, or Claude on Vertex AI, Azure AI Foundry or Bedrock."""
    AZURE = "azure"
    """Azure OpenAI, with a key or Entra ID; the model name is the deployment."""
    GOOGLE_VERTEX = "google-vertex"
    GOOGLE = "google"
    """The Gemini API."""
    OLLAMA = "ollama"
    VLLM = "vllm"
    LITELLM = "litellm"
    DEEPSEEK = "deepseek"
    TOGETHER = "together"
    FIREWORKS = "fireworks"
    CEREBRAS = "cerebras"
    GITHUB = "github"
    """GitHub Models."""
    VERCEL = "vercel"
    MOONSHOTAI = "moonshotai"
    HEROKU = "heroku"
    NEBIUS = "nebius"
    OVHCLOUD = "ovhcloud"
    SAMBANOVA = "sambanova"
    ALIBABA = "alibaba"
    TEI = "tei"
    """Hugging Face Text Embeddings Inference serving a reranker (``POST /rerank``): the
    ``reranker`` role only."""
    LOCAL = "local"
    """Models in this process (fastembed, the ``[local]`` extra, #245): no endpoint at all."""

    @classmethod
    def parse(cls, name: str, text: str) -> ProviderKind:
        """Read a kind as written in a profile.

        Args:
            name: The profile, for the error message.
            text: The kind, any letter case.

        Returns:
            The kind.

        Raises:
            InvalidProviderError: The kind is unknown, or its SDK is not included.
        """
        wanted = text.strip().lower()
        try:
            return cls(wanted)
        except ValueError:
            pass
        if wanted in _EXCLUDED_KINDS:
            reason = (
                f"kind {wanted!r} needs an SDK that exactdocs[ai] does not include; reach it "
                "through its OpenAI-compatible endpoint (kind openai-compatible) or LiteLLM"
            )
        else:
            reason = f"unknown kind; one of {', '.join(k.value for k in cls)}"
        raise InvalidProviderError(name, reason)

    @property
    def needs_base_url(self) -> bool:
        """Say whether the kind has no endpoint of its own (a gateway, a server, Azure).

        Returns:
            True when a profile of this kind must give ``base_url``.
        """
        return self.value in _SELF_HOSTED_KINDS

    @property
    def needs_key(self) -> bool:
        """Say whether every call of the kind needs a key (a hosted platform).

        Returns:
            True when a profile of this kind must have a key.
        """
        return self.value in _HOSTED_KINDS

    @property
    def has_embeddings(self) -> bool:
        """Say whether the kind can serve the embedding role.

        Returns:
            False for Anthropic (no embedding API) and TEI (served here as a reranker).
        """
        return self not in {ProviderKind.ANTHROPIC, ProviderKind.TEI}

    @property
    def has_chat(self) -> bool:
        """Say whether the kind can serve the ``llm`` and ``judge`` roles.

        Returns:
            False for TEI, which serves a reranker only.
        """
        return self is not ProviderKind.TEI


class AnthropicPlatform(StrEnum):
    """Where an ``anthropic`` profile reaches Claude."""

    API = "api"
    """The Anthropic API (or a gateway at ``base_url``)."""
    VERTEX = "vertex"
    """Claude on Google Vertex AI: ``project``, ``location`` and Google credentials."""
    FOUNDRY = "foundry"
    """Claude on Azure AI Foundry: ``base_url`` or ``resource``, a key or Entra ID."""
    BEDROCK = "bedrock"
    """Claude on Amazon Bedrock: ``location`` is the AWS region; needs boto3 (not in images)."""


class AzureAuth(StrEnum):
    """How an Azure profile (Azure OpenAI, Claude on Foundry) signs its calls."""

    KEY = "key"
    """The profile's key."""
    ENTRA = "entra"
    """Entra ID: managed identity, workload identity or a client secret from the environment."""


class KeySource(StrEnum):
    """Where a profile's key comes from. The key itself never enters retrieval's models."""

    NONE = "none"
    """No key: the placeholder ``unused`` is sent, never an SDK's environment variable."""
    SEALED = "sealed"
    """Stored over the REST API, sealed by the secret box."""
    FILE = "file"
    """``api_key_file``: read at every call, so a rotated Docker or Kubernetes secret counts."""
    ENVIRONMENT = "environment"
    """``EXACTDOCS_AI__PROVIDERS__<NAME>__API_KEY``, held by bootstrap only."""


class ProfileOrigin(StrEnum):
    """Who manages a profile."""

    CONFIGURATION = "configuration"
    """The environment or the TOML file: read-only over the REST API."""
    API = "api"
    """The REST API (and the UI, #102): stored by retrieval."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderProfile:
    """One named model endpoint, configured once and used by any role (``<name>:<model>``).

    It never holds a plaintext key: a stored key is sealed, a file is named, an environment key
    stays in bootstrap. Header values and the proxy are left out of the repr.
    """

    name: str
    """Lower case, digits, ``_`` and ``-``."""
    kind: ProviderKind
    """What it talks to."""
    origin: ProfileOrigin = ProfileOrigin.API
    """Configuration (read-only here) or the REST API."""
    base_url: str | None = None
    """The endpoint; required for gateways, servers and Azure, the platform's own otherwise."""
    key: KeySource = KeySource.NONE
    """Where the key comes from."""
    sealed_key: str | None = field(default=None, repr=False)
    """The key sealed by the secret box (``KeySource.SEALED``)."""
    key_file: str | None = None
    """The file holding the key (``KeySource.FILE``)."""
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    """Extra headers of every call; their values never appear in logs or the REST API."""
    proxy: str | None = field(default=None, repr=False)
    """An HTTP(S) proxy for this profile's calls only."""
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    """Overall timeout of one call, in seconds."""
    max_retries: int = DEFAULT_RETRIES
    """Retries of one call (the SDK's: the one retry layer)."""
    api_version: str | None = None
    """Azure OpenAI's API version."""
    project: str | None = None
    """The Google Cloud project (Vertex AI, Claude on Vertex)."""
    location: str | None = None
    """The Google Cloud location, or the AWS region for Claude on Bedrock."""
    credentials_file: str | None = None
    """A Google service-account file."""
    adc: bool = False
    """Google Application Default Credentials (``credentials = "adc"``), only when said so."""
    platform: AnthropicPlatform | None = None
    """Where an ``anthropic`` profile reaches Claude; ``api`` when unset."""
    auth: AzureAuth | None = None
    """How an Azure profile signs its calls; ``key`` when unset."""
    resource: str | None = None
    """The Azure resource name (Azure OpenAI, Claude on Foundry), instead of ``base_url``."""

    def __post_init__(self) -> None:
        """Check the fields against the kind.

        Raises:
            InvalidProviderError: A field is missing, malformed, or does not apply to the kind.
        """
        if not PROFILE_NAME.fullmatch(self.name):
            raise InvalidProviderError(
                self.name, "the name may hold only a-z, 0-9, '_' and '-' (64 at most)"
            )
        self._check_common()
        self._check_kind_fields()
        self._check_ambient_identity()  # first: its reason is the one that matters
        match self.kind:
            case ProviderKind.AZURE:
                self._check_azure()
            case ProviderKind.GOOGLE_VERTEX:
                self._check_google_credentials(express=True)
            case ProviderKind.ANTHROPIC:
                self._check_anthropic()
            case ProviderKind.LOCAL:
                if self.base_url or self.key is not KeySource.NONE or self.headers or self.proxy:
                    self._fail("a local profile has no endpoint, key, headers or proxy")
            case _:
                pass
        if self.kind.needs_base_url and not self.base_url and not self._derived_endpoint:
            self._fail(f"kind {self.kind.value} needs base_url")
        if self.kind.needs_key and self.key is KeySource.NONE:
            self._fail(f"kind {self.kind.value} needs a key")

    def _fail(self, reason: str) -> NoReturn:
        """Raise the profile's validation error.

        Args:
            reason: A fixed text.

        Raises:
            InvalidProviderError: Always.
        """
        raise InvalidProviderError(self.name, reason)

    def _check_common(self) -> None:
        """Check the fields every kind has: key, URLs, limits and headers."""
        if (self.key is KeySource.SEALED) != (self.sealed_key is not None):
            self._fail("a sealed key needs its sealed text, and only then")
        if (self.key is KeySource.FILE) != bool(self.key_file):
            self._fail("api_key_file needs a path, and only then")
        if self.base_url is not None and not _is_url(self.base_url, {"http", "https"}):
            self._fail("base_url must be an http:// or https:// URL")
        if self.proxy is not None and not _is_url(self.proxy, {"http", "https", "socks5"}):
            self._fail("proxy must be an http://, https:// or socks5:// URL")
        if not 0 < self.request_timeout <= MAX_REQUEST_TIMEOUT:
            self._fail(f"request_timeout must be above 0 and at most {MAX_REQUEST_TIMEOUT:g}")
        if not 0 <= self.max_retries <= MAX_RETRIES:
            self._fail(f"max_retries must be between 0 and {MAX_RETRIES}")
        for field_name in ("resource", "location", "project"):
            value = getattr(self, field_name)
            if value is not None and not DNS_LABEL.fullmatch(value):
                self._fail(
                    f"{field_name} must be a single name of letters, digits and inner hyphens "
                    "(63 at most): it becomes part of the endpoint's host or path"
                )
        self._check_headers()

    def _check_headers(self) -> None:
        """At most ``MAX_HEADERS`` extra headers, token names, one-line values, no credentials.

        A header that carries a credential would sit unsealed in the database and the file:
        the key belongs in the key field, which is sealed (or read from a file).
        """
        if len(self.headers) > MAX_HEADERS:
            self._fail(f"at most {MAX_HEADERS} headers")
        for header, value in self.headers:
            if not HEADER_NAME.fullmatch(header):
                self._fail("a header name must be an HTTP token")
            lowered = header.lower()
            if lowered in CREDENTIAL_HEADERS or lowered.endswith(CREDENTIAL_HEADER_SUFFIXES):
                self._fail(
                    f"header {header} carries a credential: use the key field (api_key, "
                    "api_key_file), which is sealed"
                )
            if len(value) > MAX_HEADER_VALUE or any(c in value for c in "\r\n\0"):
                self._fail(f"the value of header {header} is too long or holds a line break")

    def _check_kind_fields(self) -> None:
        """Refuse fields that do not apply to the kind (and the Anthropic platform)."""
        if self.platform is not None and self.kind is not ProviderKind.ANTHROPIC:
            self._fail("platform applies to kind anthropic only")
        if self.kind is ProviderKind.ANTHROPIC:
            scope = f"anthropic/{self.anthropic_platform.value}"
            where = f"platform {self.anthropic_platform.value}"
        else:
            scope = where = self.kind.value
        allowed = _KIND_FIELDS.get(scope, frozenset())
        for name in _OPTIONAL_KIND_FIELDS:
            if name not in allowed and getattr(self, name) not in {None, False}:
                self._fail(f"{name} does not apply to {where}")

    def _check_azure(self) -> None:
        """Azure OpenAI: ``base_url`` or ``resource`` (one), an API version, a key or Entra ID."""
        if not self.api_version:
            self._fail("Azure OpenAI needs api_version")
        if self.base_url and self.resource:
            self._fail("Azure OpenAI needs base_url or resource, not both")
        self._check_azure_auth()

    def _check_ambient_identity(self) -> None:
        """The server's own cloud identity only from configuration, only to official endpoints.

        ADC, a service-account file and Entra ID are the identity of the machine ExactDocs runs
        on, not a secret the profile holds. A profile using one is configured by the operator
        (the environment or the TOML file), never over the REST API, and takes no ``base_url``:
        its endpoint is derived from ``location`` or ``resource`` and is always Google's or
        Azure's, so the token never reaches another host.
        """
        if not self.uses_ambient_identity:
            return
        if self.origin is ProfileOrigin.API:
            self._fail(
                'credentials = "adc", credentials_file, auth = "entra" and Claude on Bedrock '
                "use the server's own cloud identity: configure them in the environment or the "
                "configuration file"
            )
        if self.base_url:
            self._fail(
                "a profile using the server's cloud identity takes no base_url: its endpoint is "
                "derived from location or resource"
            )

    @property
    def uses_ambient_identity(self) -> bool:
        """Say whether calls are signed with the server's own cloud identity.

        Returns:
            True with ``credentials = "adc"``, a ``credentials_file``, ``auth = "entra"``, or
            Claude on Bedrock (signed with the server's AWS identity: boto3's default chain or
            ``AWS_BEARER_TOKEN_BEDROCK``).
        """
        bedrock = (
            self.kind is ProviderKind.ANTHROPIC
            and self.anthropic_platform is AnthropicPlatform.BEDROCK
        )
        return self.adc or bool(self.credentials_file) or self.auth is AzureAuth.ENTRA or bedrock

    @property
    def _derived_endpoint(self) -> bool:
        """Say whether the endpoint comes from ``resource`` instead of ``base_url``.

        Returns:
            True for Azure OpenAI with a ``resource``.
        """
        return self.kind is ProviderKind.AZURE and bool(self.resource)

    def _check_azure_auth(self) -> None:
        """A key with ``auth = "key"`` (the default), none with ``auth = "entra"``."""
        if self.auth is AzureAuth.ENTRA and self.key is not KeySource.NONE:
            self._fail('auth = "entra" takes no key')
        if self.auth is not AzureAuth.ENTRA and self.key is KeySource.NONE:
            self._fail('needs a key, or auth = "entra"')

    def _check_google_credentials(self, *, express: bool) -> None:
        """Vertex AI: a service-account file, ``adc``, or (Vertex Express mode) a key; one only.

        Args:
            express: Whether a key alone (Express mode) is allowed.
        """
        ways = [bool(self.credentials_file), self.adc, self.key is not KeySource.NONE]
        if sum(ways) != 1 or (self.key is not KeySource.NONE and not express):
            what = 'credentials_file, credentials = "adc"' + (" or a key" if express else "")
            self._fail(f"needs exactly one of {what}")
        if self.key is KeySource.NONE and not (self.project and self.location):
            self._fail("needs project and location")

    def _check_anthropic(self) -> None:
        """Claude: what each platform needs."""
        match self.anthropic_platform:
            case AnthropicPlatform.API:
                if self.key is KeySource.NONE and not self.base_url:
                    self._fail("the Anthropic API needs a key (only a gateway at base_url may not)")
            case AnthropicPlatform.VERTEX:
                if self.base_url:
                    self._fail("Claude on Vertex AI takes project and location, not base_url")
                self._check_google_credentials(express=False)
            case AnthropicPlatform.FOUNDRY:
                if bool(self.base_url) == bool(self.resource):
                    self._fail("Claude on Azure AI Foundry needs base_url or resource, not both")
                self._check_azure_auth()
            case AnthropicPlatform.BEDROCK:
                if not self.location or self.key is not KeySource.NONE:
                    self._fail("Claude on Bedrock needs location (the AWS region) and no key")

    @property
    def anthropic_platform(self) -> AnthropicPlatform:
        """Where an ``anthropic`` profile reaches Claude.

        Returns:
            ``platform``, or ``api`` when unset.
        """
        return self.platform or AnthropicPlatform.API

    def same_endpoint(self, other: ProviderProfile) -> bool:
        """Tell whether two profiles send their calls (and so their key) to the same place.

        Args:
            other: The other profile.

        Returns:
            True when kind, platform, endpoint, project, location and proxy are all equal.
        """
        fields = ("kind", "platform", "base_url", "resource", "project", "location", "proxy")
        return all(getattr(self, f) == getattr(other, f) for f in fields)

    @property
    def read_only(self) -> bool:
        """Say whether the REST API may not change it.

        Returns:
            True for a profile of the environment or the configuration file.
        """
        return self.origin is ProfileOrigin.CONFIGURATION

    @property
    def header_names(self) -> tuple[str, ...]:
        """Name the extra headers, never their values.

        Returns:
            The header names, in order.
        """
        return tuple(header for header, _ in self.headers)

    @property
    def shown_proxy(self) -> str | None:
        """Show the proxy without its password.

        Returns:
            The proxy URL with any password masked, or ``None``.
        """
        if self.proxy is None:
            return None
        parts = urlsplit(self.proxy)
        if parts.password is None:
            return self.proxy
        host = parts.netloc.rpartition("@")[2]
        return urlunsplit(parts._replace(netloc=f"{parts.username}:{MASK}@{host}"))


def _is_url(text: str, schemes: set[str]) -> bool:
    """Tell whether ``text`` is an absolute URL with a host in one of ``schemes``.

    Args:
        text: The URL.
        schemes: The schemes allowed.

    Returns:
        True when it is.
    """
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    return parts.scheme in schemes and bool(parts.hostname) and not any(c.isspace() for c in text)


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelRef:
    """A role's model: ``<profile>:<model>`` (the model may hold colons, as Ollama's do)."""

    profile: str
    """The provider profile's name."""
    model: str
    """The model (or Azure deployment) name, as the provider spells it."""

    def __post_init__(self) -> None:
        """Check both parts.

        Raises:
            InvalidModelRefError: A part is empty or malformed.
        """
        text = f"{self.profile}:{self.model}"
        if not PROFILE_NAME.fullmatch(self.profile):
            raise InvalidModelRefError(text)
        model = self.model
        if (
            not model
            or len(model) > MAX_MODEL_NAME
            or not model.isprintable()
            or model != model.strip()
        ):
            raise InvalidModelRefError(text)

    @classmethod
    def parse(cls, text: str) -> ModelRef:
        """Read ``<profile>:<model>``.

        Args:
            text: The role as written (the profile part in any letter case).

        Returns:
            The reference.

        Raises:
            InvalidModelRefError: It is not ``<profile>:<model>``.
        """
        profile, colon, model = text.strip().partition(":")
        if not colon:
            raise InvalidModelRefError(text)
        return cls(profile=profile.strip().lower(), model=model.strip())

    def __str__(self) -> str:
        """Write it back as ``<profile>:<model>``.

        Returns:
            The text form.
        """
        return f"{self.profile}:{self.model}"


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceRoles:
    """The roles the operator set for the whole instance (environment or TOML file)."""

    embedding: ModelRef | None = None
    """Embeds chunks and queries; instance-wide only (one vector space per instance)."""
    reranker: ModelRef | None = None
    """Reorders candidates."""
    llm: ModelRef | None = None
    """HyDE and the agentic explorer."""
    judge: ModelRef | None = None
    """The LLM judge; the ``llm`` role when unset."""

    def explicit(self, role: ModelRole) -> ModelRef | None:
        """Read the model set for ``role`` itself (no default).

        Args:
            role: The role.

        Returns:
            Its model, or ``None``.
        """
        match role:
            case ModelRole.EMBEDDING:
                return self.embedding
            case ModelRole.RERANKER:
                return self.reranker
            case ModelRole.LLM:
                return self.llm
            case ModelRole.JUDGE:
                return self.judge


@dataclass(frozen=True, slots=True, kw_only=True)
class LibraryAi:
    """A library's AI overrides (RET-06). Never the embedding model: it is instance-wide."""

    enabled: bool = True
    """Off: nothing of the library is ever sent to a provider, and its searches are BM25."""
    llm: ModelRef | None = None
    """Its own LLM instead of the instance's."""
    judge: ModelRef | None = None
    """Its own judge instead of the instance's."""
    reranker: ModelRef | None = None
    """Its own reranker instead of the instance's."""
    rerank_top_n: int | None = None
    """How many of its best candidates the reranker reorders; ``None``: the instance's."""
    budgets: tuple[BudgetLimit, ...] = ()
    """Its own spend limits (scope kind ``library``, at most one per window), within the
    instance's: the tighter of the two applies."""

    def __post_init__(self) -> None:
        """Refuse own budgets that limit another scope kind, or two for one window.

        Raises:
            InvalidBudgetError: A budget limits another scope kind, or a window has two.
        """
        if any(limit.scope_kind != SPEND_SCOPE_LIBRARY for limit in self.budgets):
            raise InvalidBudgetError(LIBRARY_BUDGET_NOT_LIBRARY)
        if len({limit.window for limit in self.budgets}) != len(self.budgets):
            raise InvalidBudgetError(LIBRARY_BUDGET_TWICE)

    def budget(self, window: SpendWindow) -> BudgetLimit | None:
        """Find the library's own budget for a window.

        Args:
            window: Day or month.

        Returns:
            The budget, or ``None`` when it has none.
        """
        return next((limit for limit in self.budgets if limit.window is window), None)

    def override(self, role: ModelRole) -> ModelRef | None:
        """Read the library's own model for ``role``.

        Args:
            role: The role.

        Returns:
            Its model; always ``None`` for the embedding role.
        """
        match role:
            case ModelRole.EMBEDDING:
                return None
            case ModelRole.RERANKER:
                return self.reranker
            case ModelRole.LLM:
                return self.llm
            case ModelRole.JUDGE:
                return self.judge

    @property
    def is_default(self) -> bool:
        """Say whether the library overrides nothing.

        Returns:
            True when AI is on and nothing is overridden.
        """
        return (
            self.enabled
            and not (self.llm or self.judge or self.reranker)
            and self.rerank_top_n is None
            and not self.budgets
        )

    def profiles(self) -> frozenset[str]:
        """Name the profiles the overrides use.

        Returns:
            The profile names.
        """
        return frozenset(r.profile for r in (self.llm, self.judge, self.reranker) if r)


class RoleSource(StrEnum):
    """Where a role's model came from."""

    INSTANCE = "instance"
    """The instance's setting."""
    LIBRARY = "library"
    """The library's override."""
    LLM = "llm"
    """The judge defaults to the ``llm`` role."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleBinding:
    """The model one role uses for one library, and where that came from."""

    role: ModelRole
    """The role."""
    ref: ModelRef
    """Its model."""
    source: RoleSource
    """Instance, library override, or the judge's ``llm`` default."""


def bind_role(role: ModelRole, instance: InstanceRoles, library: LibraryAi) -> RoleBinding | None:
    """Resolve the model a role uses: the library's, else the instance's (the judge: else ``llm``).

    Args:
        role: The role.
        instance: The instance's roles.
        library: The library's overrides (the default ones outside any library).

    Returns:
        The binding, or ``None`` when the role is not set or the library has AI off.
    """
    if not library.enabled:
        return None
    if (own := library.override(role)) is not None:
        return RoleBinding(role=role, ref=own, source=RoleSource.LIBRARY)
    if (set_ := instance.explicit(role)) is not None:
        return RoleBinding(role=role, ref=set_, source=RoleSource.INSTANCE)
    if role is ModelRole.JUDGE and (llm := bind_role(ModelRole.LLM, instance, library)):
        return RoleBinding(role=role, ref=llm.ref, source=RoleSource.LLM)
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelCheck:
    """The outcome of one minimal call to a model (``exactdocs ai check``)."""

    role: ModelRole | None
    """The role checked; ``None`` for a model named by hand."""
    profile: str
    """The profile called."""
    model: str
    """The model asked for."""
    ok: bool
    """The call answered as expected."""
    latency_ms: float = 0.0
    """How long the call took."""
    served_model: str | None = None
    """The model name the provider reported."""
    dimensions: int | None = None
    """An embedding model's vector size."""
    error: str | None = None
    """Why it failed; never holds a key."""


# ---------------------------------------------------------------- vector store
EmbeddingSpaceId = NewType("EmbeddingSpaceId", int)


class VectorMetric(StrEnum):
    """How two vectors of a space are compared."""

    COSINE = "cosine"
    """Cosine distance: 1 minus the cosine of their angle (0 is the same direction)."""


class SpaceState(StrEnum):
    """Where an embedding space is in its life."""

    BUILDING = "building"
    """Created for a new model: versions are being embedded into it."""
    ACTIVE = "active"
    """The space hybrid searches use."""
    RETIRED = "retired"
    """Replaced by another space; its vectors are dropped and it takes no new ones."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingSpec:
    """What makes vectors comparable: one model, its dimensions and what was embedded.

    Two specs that differ in anything need two spaces: their vectors are never compared. The
    profile's base URL or key is not part of it, so moving a model to another endpoint keeps
    its space.
    """

    profile_kind: str
    """The provider profile's kind (``openai``, ``local``...)."""
    model: str
    """The embedding model's name, as the provider spells it."""
    dimensions: int
    """How many numbers each vector holds."""
    input_format: int = EMBEDDING_INPUT_FORMAT
    """What a chunk's embedding is computed from (``EMBEDDING_INPUT_FORMAT``)."""
    metric: VectorMetric = VectorMetric.COSINE
    """How vectors are compared."""

    def __post_init__(self) -> None:
        """Refuse a spec no store can hold.

        Raises:
            InvalidEmbeddingSpaceError: No model or kind, or dimensions out of range.
        """
        if not self.model.strip() or not self.profile_kind.strip():
            reason = "the profile kind and the model must not be blank"
            raise InvalidEmbeddingSpaceError(reason)
        if not 1 <= self.dimensions <= MAX_EMBEDDING_DIMENSIONS:
            reason = f"dimensions must be between 1 and {MAX_EMBEDDING_DIMENSIONS}"
            raise InvalidEmbeddingSpaceError(reason)


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingSpace:
    """A set of vectors made by one ``EmbeddingSpec``; vectors of two spaces never meet."""

    id: EmbeddingSpaceId
    """Given by the store when the space is created; never reused."""
    spec: EmbeddingSpec
    """The model and format every vector of the space was made with."""
    state: SpaceState
    """Building, active or retired."""
    created_at: datetime
    """When the space was created."""
    activated_at: datetime | None = None
    """When it became the active space, if it did."""


@dataclass(frozen=True, slots=True, kw_only=True)
class VectorHit:
    """A chunk of the searched manifest and how far its vector is from the query's."""

    chunk_id: ChunkId
    """The chunk, as the manifest names it."""
    distance: float
    """The space's metric (cosine distance, 0 to 2): smaller is nearer, never below 0."""


@dataclass(frozen=True, slots=True, kw_only=True)
class VectorCoverage:
    """How much of one manifest a space has vectors for."""

    chunks: int
    """The manifest's chunks."""
    embedded: int
    """Of those, how many have a vector in the space."""

    @property
    def complete(self) -> bool:
        """Every chunk of the manifest has a vector (a manifest without chunks is complete).

        Returns:
            True when nothing is left to embed.
        """
        return self.embedded >= self.chunks


def checked_vector(values: Sequence[float], dimensions: int) -> tuple[float, ...]:
    """Return a vector that can be stored in, or searched in, a space of ``dimensions``.

    Args:
        values: The vector as a model returned it.
        dimensions: The space's dimensions.

    Returns:
        The values as floats.

    Raises:
        VectorDimensionError: The length is not the space's.
        InvalidVectorError: A value is not a finite float32, or every value is zero.
    """
    vector = tuple(float(v) for v in values)
    if len(vector) != dimensions:
        raise VectorDimensionError(dimensions, len(vector))
    if not all(math.isfinite(v) and abs(v) <= MAX_FLOAT32 for v in vector) or not any(vector):
        raise InvalidVectorError
    return vector


# ---------------------------------------------------------------- embedding jobs
@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingTarget:
    """The embedding model the instance is configured with now (RET-01).

    Its dimensions are known only when the operator set them: otherwise the model is asked once,
    when its space is created. A space made by this target is ``matches``.
    """

    profile_kind: str
    """The kind of the role's provider profile."""
    model: str
    """The embedding model, as the provider spells it."""
    dimensions: int | None = None
    """The configured dimensions (``EmbeddingSettings(dimensions=...)``), if any."""
    input_format: int = EMBEDDING_INPUT_FORMAT
    """What chunks are embedded from."""

    def matches(self, spec: EmbeddingSpec) -> bool:
        """Say whether a space's vectors were made by this target.

        Args:
            spec: The space's spec.

        Returns:
            True when the kind, the model and the input format are this target's, and the
            dimensions too when they are configured.
        """
        same = (spec.profile_kind, spec.model, spec.input_format) == (
            self.profile_kind,
            self.model,
            self.input_format,
        )
        return same and (self.dimensions is None or spec.dimensions == self.dimensions)

    def spec(self, dimensions: int) -> EmbeddingSpec:
        """Describe the space this target's vectors go to.

        Args:
            dimensions: The vectors' size (configured, or what the model answered).

        Returns:
            The spec.
        """
        return EmbeddingSpec(
            profile_kind=self.profile_kind,
            model=self.model,
            dimensions=dimensions,
            input_format=self.input_format,
        )


def current_space(
    target: EmbeddingTarget, spaces: Sequence[EmbeddingSpace]
) -> EmbeddingSpace | None:
    """Find the space the configured model embeds into and searches: the newest it made.

    Args:
        target: The configured model.
        spaces: Every space, oldest first.

    Returns:
        The newest space of the target that is not retired, or ``None``.
    """
    return next(
        (
            s
            for s in reversed(spaces)
            if s.state is not SpaceState.RETIRED and target.matches(s.spec)
        ),
        None,
    )


class EmbeddingSkip(StrEnum):
    """Why an ``embed`` job of a version sends nothing."""

    NO_MODEL = "no_embedding_model"
    """No embedding model is configured (or its profile does not exist)."""
    AI_OFF = "ai_off"
    """The library has AI off: nothing of it is ever sent to a provider."""
    NO_VERSION = "no_version"
    """The version has no active manifest (it was removed meanwhile)."""
    VECTOR_STORE_UNAVAILABLE = "vector_store_unavailable"
    """No vector store, or it cannot be loaded (sqlite-vec, pgvector): nothing could be stored."""
    SPACE_CHANGED = "space_changed"
    """The embedding model changed meanwhile: the job of the new model embeds the version."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingSource:
    """What one stored chunk is embedded from, as a manifest holds it."""

    article_path: str
    """Where the chunk's article is in the manifest (its title comes from the catalog)."""
    heading_path: tuple[str, ...]
    """The chunk's heading and every heading above it."""
    content: str
    """The chunk's text."""


def embedding_text(title: str, source: EmbeddingSource) -> str:
    """Write the text a chunk is embedded from (input format 1).

    The article title, then the heading path, then a blank line and the chunk's text; an empty
    title or path is left out.

    Args:
        title: The article's title.
        source: The chunk.

    Returns:
        The text sent to the embedding model.
    """
    head = [part for part in (title.strip(), HEADING_SEPARATOR.join(source.heading_path)) if part]
    return "\n".join(head) + "\n\n" + source.content if head else source.content


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddedTexts:
    """Vectors a model returned, in the order of the texts, and what it said they cost."""

    vectors: tuple[tuple[float, ...], ...]
    """One vector per text."""
    input_tokens: int
    """Tokens the provider reported in its returned ``usage``; 0 when it reported none."""
    requests: int
    """Calls made to the provider."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingArticle:
    """How many of the pending chunks are embedded with one article's title."""

    manifest_id: str
    """The manifest the chunks are counted under (the first one holding each chunk)."""
    article_path: str
    """The article (the first path holding each chunk)."""
    chunks: int
    """The chunks."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestPaths:
    """Some articles of one manifest, by path: whose titles are embedded with their chunks."""

    manifest_id: str
    """The manifest."""
    paths: tuple[str, ...]
    """The article paths."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingChunks:
    """Stored chunks some manifests hold that have no vector yet, each counted once."""

    chunks: int
    """Distinct stored chunks."""
    characters: int
    """Characters of their text and heading paths (titles are added by ``with_titles``)."""
    articles: tuple[PendingArticle, ...] = ()
    """Where the chunks are, per article: their titles are embedded with them."""

    def with_titles(self, titles: Mapping[tuple[str, str], str]) -> PendingChunks:
        """Count each chunk's article title in, as it is embedded (input format 1).

        Args:
            titles: The title of each (manifest ID, article path).

        Returns:
            The same chunks with their titles' characters added.
        """
        extra = sum(
            len(titles.get((a.manifest_id, a.article_path), "")) * a.chunks for a in self.articles
        )
        return replace(self, characters=self.characters + extra)

    @property
    def estimated_tokens(self) -> int:
        """Estimate their tokens at ``CHARS_PER_TOKEN`` characters each, never by a tokenizer.

        Returns:
            The estimate, rounded up.
        """
        return -(-self.characters // CHARS_PER_TOKEN)


def estimated_usd(tokens: int, usd_per_million: float | None) -> float | None:
    """Price some input tokens.

    Args:
        tokens: The tokens.
        usd_per_million: The input price per million tokens; ``None`` when unknown.

    Returns:
        US dollars, or ``None`` without a price.
    """
    return None if usd_per_million is None else tokens * usd_per_million / TOKENS_PER_MILLION


class SpendWindow(StrEnum):
    """A budget window of the spend ledger, in UTC."""

    DAY = "day"
    MONTH = "month"

    def start(self, at: datetime) -> date:
        """Find the first day of the window that holds ``at``.

        Args:
            at: An aware time.

        Returns:
            The window's first day, in UTC.
        """
        day = at.astimezone(UTC).date()
        return day if self is SpendWindow.DAY else day.replace(day=1)

    def kept_since(self, latest: date) -> date:
        """Find the oldest window start whose replay tokens are still kept.

        A response is replayed within the hour: a day's tokens are kept ``REPLAY_RETAIN_DAYS``
        days, a month's until the month after it ends.

        Args:
            latest: The newest window start being written.

        Returns:
            Tokens of windows starting before it can be dropped.
        """
        if self is SpendWindow.DAY:
            return latest - timedelta(days=REPLAY_RETAIN_DAYS)
        return (latest.replace(day=1) - timedelta(days=1)).replace(day=1)

    def resets_at(self, at: datetime) -> datetime:
        """Find when the window that holds ``at`` ends: the next UTC midnight or first of month.

        Args:
            at: An aware time.

        Returns:
            The first moment of the next window, in UTC.
        """
        first = self.start(at)
        if self is SpendWindow.DAY:
            following = first + timedelta(days=1)
        elif first.month == MONTHS_PER_YEAR:
            following = first.replace(year=first.year + 1, month=1)
        else:
            following = first.replace(month=first.month + 1)
        return datetime(following.year, following.month, following.day, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class SpendKey:
    """The ledger's own row key: (scope kind, scope ID, window, window start).

    Our format, not the harness's: its ``SpendEntry.key`` is parsed into this one by the
    ``BatchSpendStore`` adapter, so a harness that changed its keys could not split the spend
    over two sets of rows.
    """

    scope_kind: str
    """``instance``, ``library``, ``user`` or ``embedding``."""
    scope_id: str
    """The library ID, the account ID, or empty for the instance-wide kinds."""
    window: SpendWindow
    """Day or month."""
    window_start: date
    """The window's first day (UTC)."""

    def __post_init__(self) -> None:
        """Refuse a scope kind the ledger does not have.

        Raises:
            UnknownSpendKeyError: The kind is not one of ``SPEND_SCOPE_KINDS``.
        """
        if self.scope_kind not in SPEND_SCOPE_KINDS:
            raise UnknownSpendKeyError(self.scope_kind)


@dataclass(frozen=True, slots=True, kw_only=True)
class SpendEntry:
    """Usage to add to one row of the spend ledger: one scope in one window.

    A row is keyed by (scope kind, scope ID, window, window start); the ledger adds an entry to
    its row atomically. Budgets read the same rows. Read back, an entry is a row's totals.
    """

    scope_kind: str
    """``instance``, ``library``, ``user`` or ``embedding`` (``SPEND_SCOPE_KINDS``)."""
    scope_id: str
    """Who spent: a library ID, an account ID, or empty for the instance-wide kinds."""
    window: SpendWindow
    """Day or month."""
    window_start: date
    """The window's first day (UTC)."""
    input_tokens: int = 0
    """Tokens sent, as the provider reported them. The harness reports one total per response,
    which is booked here."""
    output_tokens: int = 0
    """Tokens received (none for embeddings)."""
    requests: int = 0
    """Calls made."""
    usd_micros: int = 0
    """Their price in millionths of a US dollar; 0 when the price is unknown."""
    unpriced: int = 0
    """Of ``requests``, those whose price is unknown (so ``usd_micros`` leaves them out)."""
    token: str | None = None
    """Identifies the response the entry comes from: an entry whose token its row has already
    taken is not added again (a replayed accrual). ``None``: always added."""

    @classmethod
    def empty(cls, key: SpendKey) -> SpendEntry:
        """Start a row with nothing spent.

        Args:
            key: The row.

        Returns:
            Its totals, all zero.
        """
        return cls(
            scope_kind=key.scope_kind,
            scope_id=key.scope_id,
            window=key.window,
            window_start=key.window_start,
        )

    @property
    def key(self) -> SpendKey:
        """The row this entry adds to.

        Returns:
            Its key.
        """
        return SpendKey(
            scope_kind=self.scope_kind,
            scope_id=self.scope_id,
            window=self.window,
            window_start=self.window_start,
        )

    @property
    def tokens(self) -> int:
        """Count the tokens in both directions, which token budgets limit.

        Returns:
            Input plus output tokens.
        """
        return self.input_tokens + self.output_tokens

    def plus(self, other: SpendEntry) -> SpendEntry:
        """Add another entry's counters to these (the same row).

        Args:
            other: The usage to add.

        Returns:
            The sums, without a replay token.
        """
        return replace(
            self,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            requests=self.requests + other.requests,
            usd_micros=self.usd_micros + other.usd_micros,
            unpriced=self.unpriced + other.unpriced,
            token=None,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelPrice:
    """What a model costs, in US dollars per million tokens."""

    input_usd_per_million: float
    """Tokens sent."""
    output_usd_per_million: float = 0.0
    """Tokens received."""

    def usd_micros(self, input_tokens: int, output_tokens: int = 0) -> int:
        """Price some tokens in millionths of a US dollar.

        Args:
            input_tokens: Tokens sent.
            output_tokens: Tokens received.

        Returns:
            The price, rounded to a whole millionth.
        """
        usd = (
            input_tokens * self.input_usd_per_million + output_tokens * self.output_usd_per_million
        ) / TOKENS_PER_MILLION
        return round(usd * MICROS_PER_USD)


@dataclass(frozen=True, slots=True, kw_only=True)
class AiCaller:
    """Who an AI call is made for: the scopes it counts to and its rate limit key."""

    library: str
    """The library searched or embedded."""
    user: str | None = None
    """The account (an API token's or a session's); ``None`` for a stdio MCP process."""

    def scopes(self) -> tuple[tuple[str, str], ...]:
        """Name the ledger scopes an LLM or a rerank call counts to.

        Returns:
            (kind, ID) of the instance, the library and, with an account, the user.
        """
        scopes = [(SPEND_SCOPE_INSTANCE, SPEND_INSTANCE_ID), (SPEND_SCOPE_LIBRARY, self.library)]
        if self.user is not None:
            scopes.append((SPEND_SCOPE_USER, self.user))
        return tuple(scopes)

    def embedding_scopes(self) -> tuple[tuple[str, str], ...]:
        """Name the ledger scopes an embedding batch counts to (never a user's).

        Returns:
            (kind, ID) of the embedding budget, the instance and the library.
        """
        return (
            (SPEND_SCOPE_EMBEDDING, SPEND_INSTANCE_ID),
            (SPEND_SCOPE_INSTANCE, SPEND_INSTANCE_ID),
            (SPEND_SCOPE_LIBRARY, self.library),
        )

    @property
    def rate_key(self) -> str:
        """Whose LLM searches per minute are counted together.

        Returns:
            The account ID; empty for callers without one (one stdio process).
        """
        return self.user or ""


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetLimit:
    """A ceiling on one kind of scope in one window: each scope of the kind has its own."""

    scope_kind: str
    """The scopes it limits: ``instance``, every ``library``, every ``user``, or ``embedding``."""
    window: SpendWindow
    """Per UTC day or month."""
    usd_micros: int | None = None
    """The most millionths of a US dollar; ``None``: US dollars are not limited."""
    tokens: int | None = None
    """The most tokens (input and output); ``None``: tokens are not limited."""

    def __post_init__(self) -> None:
        """Refuse a limit that limits nothing, or nothing at all.

        Raises:
            InvalidBudgetError: No ceiling, or a ceiling below one.
            UnknownSpendKeyError: The scope kind is not one of ``SPEND_SCOPE_KINDS``.
        """
        if self.scope_kind not in SPEND_SCOPE_KINDS:
            raise UnknownSpendKeyError(self.scope_kind)
        if self.usd_micros is None and self.tokens is None:
            raise InvalidBudgetError(BUDGET_WITHOUT_CEILING)
        if (self.usd_micros is not None and self.usd_micros < 1) or (
            self.tokens is not None and self.tokens < 1
        ):
            raise InvalidBudgetError(BUDGET_NOT_POSITIVE)

    def key(self, scope_id: str, at: datetime) -> SpendKey:
        """Find the row this limit reads for one scope at a time.

        Args:
            scope_id: The scope.
            at: An aware time.

        Returns:
            The row of the window holding ``at``.
        """
        return SpendKey(
            scope_kind=self.scope_kind,
            scope_id=scope_id,
            window=self.window,
            window_start=self.window.start(at),
        )

    def reached(self, spent: SpendEntry) -> bool:
        """Say whether a row has used this limit up.

        Args:
            spent: The row's totals.

        Returns:
            True at or past either ceiling.
        """
        return (self.usd_micros is not None and spent.usd_micros >= self.usd_micros) or (
            self.tokens is not None and spent.tokens >= self.tokens
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReachedBudget:
    """A limit a scope has used up, and when its window resets."""

    limit: BudgetLimit
    """The limit."""
    scope_id: str
    """The scope that used it up."""
    resets_at: datetime
    """The end of its window."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetCeiling:
    """The most one library may spend in a window, as the instance's limits set it."""

    usd_micros: int | None = None
    """Millionths of a US dollar; ``None``: not limited."""
    tokens: int | None = None
    """Tokens; ``None``: not limited."""


def _raised_over(value: int | None, ceiling: int | None, stored: int | None) -> bool:
    """Say whether a library's own ceiling goes over the instance's and was not stored so.

    Args:
        value: The ceiling as it would be saved; ``None``: not limited by the library.
        ceiling: The instance's; ``None``: no ceiling.
        stored: The library's ceiling as stored now; ``None``: none.

    Returns:
        True when it is over the instance's and higher than the stored one (or new).
    """
    if value is None or ceiling is None or value <= ceiling:
        return False
    return stored is None or value > stored


def _tighter(first: int | None, second: int | None) -> int | None:
    """Pick the lower of two ceilings, where ``None`` is no ceiling.

    Args:
        first: One ceiling.
        second: The other.

    Returns:
        The lower one; ``None`` only when neither is set.
    """
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


@dataclass(frozen=True, slots=True, kw_only=True)
class Budgets:
    """The instance's spend limits and its LLM search rate limit (docs/decisions/ai-retrieval.md).

    Limits are checked before each call or batch, so a burst can overshoot by the calls already
    in flight. With no limits nothing is refused; spend is still recorded.
    """

    limits: tuple[BudgetLimit, ...] = ()
    """Every ceiling."""
    llm_searches_per_minute: int | None = None
    """LLM searches each caller may make per minute; ``None``: not limited."""

    def __post_init__(self) -> None:
        """Refuse a rate limit below one.

        Raises:
            InvalidBudgetError: ``llm_searches_per_minute`` is below one.
        """
        if self.llm_searches_per_minute is not None and self.llm_searches_per_minute < 1:
            raise InvalidBudgetError(RATE_LIMIT_BELOW_ONE)

    @property
    def limits_usd(self) -> bool:
        """Say whether any limit is in US dollars (then every model must have a price).

        Returns:
            True when one is.
        """
        return any(limit.usd_micros is not None for limit in self.limits)

    def ceiling(self, window: SpendWindow) -> BudgetCeiling:
        """Say how much one library may spend in a window at most, as the instance sets it.

        Args:
            window: Day or month.

        Returns:
            The lowest instance and per-library ceilings of the window; ``None`` parts are
            not limited.
        """
        usd = [
            limit.usd_micros
            for limit in self.limits
            if limit.window is window
            and limit.scope_kind in {SPEND_SCOPE_INSTANCE, SPEND_SCOPE_LIBRARY}
            and limit.usd_micros is not None
        ]
        tokens = [
            limit.tokens
            for limit in self.limits
            if limit.window is window
            and limit.scope_kind in {SPEND_SCOPE_INSTANCE, SPEND_SCOPE_LIBRARY}
            and limit.tokens is not None
        ]
        return BudgetCeiling(
            usd_micros=min(usd) if usd else None, tokens=min(tokens) if tokens else None
        )

    def check_library(self, own: Sequence[BudgetLimit], stored: Sequence[BudgetLimit] = ()) -> None:
        """Refuse a library's own budgets that go over what the instance allows a library.

        A ceiling the library already had is kept even when the instance's limit was lowered
        below it since: only raising one over the instance's is refused (the tighter applies).

        Args:
            own: The library's budgets as they would be saved.
            stored: Its budgets as they are stored now.

        Raises:
            LibraryBudgetAboveInstanceError: One is raised over the instance's ceiling.
        """
        before = {limit.window: limit for limit in stored}
        for limit in own:
            ceiling = self.ceiling(limit.window)
            kept = before.get(limit.window)
            period = "daily" if limit.window is SpendWindow.DAY else "monthly"
            if _raised_over(
                limit.usd_micros, ceiling.usd_micros, kept.usd_micros if kept else None
            ):
                what, most = f"{period}_usd", f"{(ceiling.usd_micros or 0) / MICROS_PER_USD:g} USD"
                raise LibraryBudgetAboveInstanceError(what, most)
            if _raised_over(limit.tokens, ceiling.tokens, kept.tokens if kept else None):
                what, most = f"{period}_tokens", f"{ceiling.tokens} tokens"
                raise LibraryBudgetAboveInstanceError(what, most)

    def for_library(self, own: Sequence[BudgetLimit]) -> Budgets:
        """Apply a library's own budgets: per window, the tighter of its own and the instance's.

        Args:
            own: The library's budgets (scope kind ``library``).

        Returns:
            The limits a call of that library is checked against; these limits when it has none.
        """
        if not own:
            return self
        merged: list[BudgetLimit] = [
            limit for limit in self.limits if limit.scope_kind != SPEND_SCOPE_LIBRARY
        ]
        for window in SpendWindow:
            mine = next((limit for limit in own if limit.window is window), None)
            theirs = next(
                (
                    limit
                    for limit in self.limits
                    if limit.scope_kind == SPEND_SCOPE_LIBRARY and limit.window is window
                ),
                None,
            )
            if mine is None or theirs is None:
                if (kept := mine or theirs) is not None:
                    merged.append(kept)
                continue
            merged.append(
                BudgetLimit(
                    scope_kind=SPEND_SCOPE_LIBRARY,
                    window=window,
                    usd_micros=_tighter(mine.usd_micros, theirs.usd_micros),
                    tokens=_tighter(mine.tokens, theirs.tokens),
                )
            )
        return replace(self, limits=tuple(merged))

    def keys(self, scopes: Sequence[tuple[str, str]], at: datetime) -> tuple[SpendKey, ...]:
        """List the rows the limits on these scopes read.

        Args:
            scopes: (kind, ID) of each scope a call counts to.
            at: When the call would be made.

        Returns:
            One key per limit and scope of its kind, without repeats.
        """
        keys = {
            limit.key(scope_id, at): None
            for limit in self.limits
            for kind, scope_id in scopes
            if kind == limit.scope_kind
        }
        return tuple(keys)

    def reached(
        self,
        scopes: Sequence[tuple[str, str]],
        rows: Mapping[SpendKey, SpendEntry],
        at: datetime,
    ) -> ReachedBudget | None:
        """Find a limit one of these scopes has used up.

        Args:
            scopes: (kind, ID) of each scope a call counts to.
            rows: The rows ``keys`` named, as read; a missing row has spent nothing.
            at: When the call would be made.

        Returns:
            The used-up limit whose window resets last, or ``None`` when every one has room.
        """
        found: ReachedBudget | None = None
        for limit in self.limits:
            for kind, scope_id in scopes:
                if kind != limit.scope_kind:
                    continue
                key = limit.key(scope_id, at)
                if not limit.reached(rows.get(key) or SpendEntry.empty(key)):
                    continue
                resets_at = limit.window.resets_at(at)
                if found is None or resets_at > found.resets_at:
                    found = ReachedBudget(limit=limit, scope_id=scope_id, resets_at=resets_at)
        return found


def spend_entries(
    at: datetime,
    scopes: Sequence[tuple[str, str]],
    *,
    input_tokens: int,
    output_tokens: int = 0,
    requests: int,
    price: ModelPrice | None,
) -> tuple[SpendEntry, ...]:
    """Write one call's usage as ledger entries: one per scope and UTC window.

    Args:
        at: When the calls were made.
        scopes: (kind, ID) of each scope they count to.
        input_tokens: Tokens the provider reported sending.
        output_tokens: Tokens it reported receiving.
        requests: Calls made.
        price: The model's price, if known.

    Returns:
        One entry per scope and window (day, month).
    """
    micros = 0 if price is None else price.usd_micros(input_tokens, output_tokens)
    return tuple(
        SpendEntry(
            scope_kind=kind,
            scope_id=scope_id,
            window=window,
            window_start=window.start(at),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requests=requests,
            usd_micros=micros,
            unpriced=requests if price is None else 0,
        )
        for kind, scope_id in scopes
        for window in SpendWindow
    )


def embedding_spend(
    at: datetime,
    *,
    library: str,
    input_tokens: int,
    requests: int,
    usd_per_million: float | None,
) -> tuple[SpendEntry, ...]:
    """Write one embedding batch's usage as ledger entries.

    The same rows LLM spend uses (docs/decisions/ai-retrieval.md, *Cost and budgets*), the
    instance's and the library's, plus the instance-wide ``embedding`` rows the separate
    embedding budget reads.

    Args:
        at: When the calls were made.
        library: The library whose chunks were embedded.
        input_tokens: Tokens the provider reported.
        requests: Calls made.
        usd_per_million: The model's input price per million tokens, if known.

    Returns:
        One entry per scope (embedding, instance, library) and window (day, month).
    """
    price = None if usd_per_million is None else ModelPrice(input_usd_per_million=usd_per_million)
    return spend_entries(
        at,
        AiCaller(library=library).embedding_scopes(),
        input_tokens=input_tokens,
        requests=requests,
        price=price,
    )
