"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from itertools import groupby
from typing import NewType

from exactdocs.retrieval.constants import (
    _LANGUAGE_ALIASES,
    _WORD,
    DEFAULT_MODE_ORDER,
    EMBEDDING_INPUT_FORMAT,
    MAX_EMBEDDING_DIMENSIONS,
    MAX_FLOAT32,
    STOP_WORDS,
)
from exactdocs.retrieval.errors import (
    DuplicateChunkError,
    EmptySearchTextError,
    InvalidEmbeddingSpaceError,
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
class Chunk:
    """One section of an article, as the chunker cut it."""

    heading_path: tuple[str, ...]
    occurrence_index: int
    """0 for the first heading with this text, 1 for the next one, ..."""
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


@dataclass(frozen=True, slots=True, kw_only=True)
class OutlineNode:
    """One heading of an article's outline and the headings under it, in document order."""

    heading: str
    """The heading's text, untrusted repository text."""
    section: SectionRef | None
    """The chunk this heading starts; ``None`` when it starts none (only deeper headings do)."""
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

    Every section becomes the node of its own (last) heading, so two sections with the same
    headings are two sibling nodes. An ancestor heading that starts no chunk of its own is a node
    without a section. Headings inside a chunk (merged by the chunking config) are not in its
    heading path, so they are not in the outline either.

    Args:
        sections: The article's sections, ordered by position.

    Returns:
        The tree, with the text before the first heading (if a chunk) apart as the preamble.
    """
    preamble = next((s for s in sections if not s.heading_path), None)
    return Outline(
        preamble=preamble, sections=_outline_nodes([s for s in sections if s.heading_path], 0)
    )


def _outline_nodes(sections: Sequence[SectionRef], depth: int) -> tuple[OutlineNode, ...]:
    """Group sections whose heading paths are all longer than ``depth`` into nodes at ``depth``.

    Args:
        sections: Consecutive sections in document order, each deeper than ``depth``.
        depth: The index of the heading in each heading path that names the nodes.

    Returns:
        One node per heading at ``depth``, each with the deeper sections that follow it.
    """
    nodes: list[OutlineNode] = []
    start = 0
    while start < len(sections):
        head = sections[start]
        prefix = head.heading_path[: depth + 1]
        own = head if len(head.heading_path) == depth + 1 else None
        end = start + 1
        while (
            end < len(sections)
            and len(sections[end].heading_path) > depth + 1
            and sections[end].heading_path[: depth + 1] == prefix
        ):
            end += 1
        below = sections[start + 1 if own else start : end]
        nodes.append(
            OutlineNode(heading=prefix[-1], section=own, children=_outline_nodes(below, depth + 1))
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

    The decision record's fourth role, ``judge`` (an LLM that reranks, defaulting to ``llm``),
    is not here yet: no mode needs it to run. The LLM judge (#96) adds it as a way to rerank.
    """

    EMBEDDING = "embedding"
    """Turns chunks and queries into vectors (hybrid search)."""
    RERANKER = "reranker"
    """Reorders the best candidates of any mode (reranking is a flag on top of a mode)."""
    LLM = "llm"
    """Writes hypothetical answers (HyDE) and drives the agentic explorer."""


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


@dataclass(frozen=True, slots=True, kw_only=True)
class ModeChoice:
    """The mode a search runs in, whether it reranks, and why a better mode was skipped."""

    mode: RetrievalMode
    """The mode whose pipeline runs."""
    rerank: bool
    """A reranker is configured: the pipeline reorders its best candidates."""
    fallback_reason: FallbackReason | None = None
    """Why the library's or the instance's mode was skipped, if it was."""


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
    """Reorder the best candidates with the configured reranker."""


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
