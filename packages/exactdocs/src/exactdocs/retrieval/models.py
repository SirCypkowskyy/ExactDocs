"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
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
    MASK,
    MAX_EMBEDDING_DIMENSIONS,
    MAX_FLOAT32,
    MAX_HEADER_VALUE,
    MAX_HEADERS,
    MAX_MODEL_NAME,
    MAX_REQUEST_TIMEOUT,
    MAX_RETRIES,
    PROFILE_NAME,
    STOP_WORDS,
)
from exactdocs.retrieval.errors import (
    DuplicateChunkError,
    EmptySearchTextError,
    InvalidEmbeddingSpaceError,
    InvalidModelRefError,
    InvalidProviderError,
    InvalidVectorError,
    UnavailableModeError,
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

    @property
    def needs_rebuild(self) -> bool:
        """Whether the index is older than this build writes, or its format is unknown."""
        return self.stored_format is None or self.stored_format < self.current_format


@dataclass(frozen=True, slots=True, kw_only=True)
class RebuiltIndex:
    """What a rebuild left: the format it is now in and how many chunks it holds."""

    format: int
    entries: int


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
    """The library's AI overrides as read for this search, so the reranker resolves from the same
    read; ``None`` when there is no reranking."""


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
        if asked is not None:
            return ModeChoice(mode=self.check(asked), rerank=rerank)
        reason: FallbackReason | None = None
        for setting in (library, instance):
            if setting is None:
                continue
            if self.is_available(setting):
                return ModeChoice(mode=setting, rerank=rerank, fallback_reason=reason)
            reason = reason or self._skipped(setting)
        best = self.best()
        if reason is None and not self.vector_store:
            with_store = ModeRegistry(roles=self.roles, pipelines=self.pipelines)
            if with_store.best() != best:
                reason = FallbackReason.VECTOR_STORE_UNAVAILABLE
        return ModeChoice(mode=best, rerank=rerank, fallback_reason=reason)


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
