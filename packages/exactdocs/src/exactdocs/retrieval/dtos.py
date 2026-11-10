"""Data crossing the retrieval boundary. Immutable, validated."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from exactdocs.retrieval.constants import (
    DEFAULT_GRACE_SECONDS,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRIES,
    EMBEDDING_INPUT_FORMAT,
    ESTIMATE_NOTE,
    MAX_EMBEDDING_DIMENSIONS,
    MAX_KEY,
    MAX_MODEL_NAME,
    MAX_MODEL_REF,
    MAX_QUERY,
    MAX_TAG,
    MAX_TAGS,
    MAX_URL,
    PROFILE_NAME_PATTERN,
)
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    AzureAuth,
    Candidate,
    EmbeddingSkip,
    EmbeddingSpace,
    FallbackReason,
    KeySource,
    ModelCheck,
    ModelRole,
    Outline,
    OutlineNode,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RebuiltIndex,
    Removed,
    RetrievalMode,
    RoleSource,
    SearchableVersion,
    SearchHit,
    SearchIndexState,
    SpaceState,
    StoredChunk,
    TagMatch,
    VectorMetric,
    source_link,
)
from exactdocs_kernel import (
    LIBRARY_ID_PATTERN,
    MAX_NAME,
    MAX_PATH,
    NOTICE,
    normalize_tag,
)


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


Tag = Annotated[str, StringConstraints(max_length=MAX_TAG)]


def _normalize_tags(value: object) -> object:
    """Split on commas and normalize like ingestion stores tags; drop blanks and repeats."""
    if not isinstance(value, list | tuple):
        return value
    if not all(isinstance(v, str) for v in value):
        return value
    parts = [p for v in value for p in v.split(",") if p.strip()]
    tags = [normalize_tag(p) for p in parts]
    if None in tags:
        message = "tags must be valid tags"
        raise ValueError(message)
    return list(dict.fromkeys(tags))


class SearchDocsQuery(_Dto):
    """Search within exactly one library version; no ``ref`` means the default version."""

    library: str = Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """`/owner/repo`, any letter case; the version goes in `ref`."""
    ref: str | None = Field(default=None, max_length=MAX_NAME)
    """Exact imported ref; default version if empty."""
    query: str = Field(min_length=1, max_length=MAX_QUERY)
    tags: list[Tag] = Field(default_factory=list, max_length=MAX_TAGS)
    """Only chunks of articles so tagged. Case-insensitive; a comma separates tags."""
    tags_match: TagMatch = Field(default=TagMatch.ANY)
    """`any`: at least one of `tags`; `all`: every one."""
    limit: int = Field(default=5, ge=1, le=50)
    mode: str | None = Field(default=None, max_length=MAX_NAME)
    """`bm25`, `hybrid`, `hybrid_hyde` or `agentic`, if configured; default: the library's mode,
    else the instance's, else the best one configured.
    """

    @field_validator("ref", "mode", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("tags", mode="before")
    @classmethod
    def _split_tags(cls, value: object) -> object:
        return _normalize_tags(value)


class SearchAllQuery(_Dto):
    """Search the default version of every library at once, or of one when ``library`` is set."""

    query: str = Field(min_length=1, max_length=MAX_QUERY)
    library: str | None = Field(default=None, pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """`/owner/repo`: only its results (its default version); counts stay global."""
    tags: list[Tag] = Field(default_factory=list, max_length=MAX_TAGS)
    """Only chunks of articles so tagged. Case-insensitive; a comma separates tags."""
    tags_match: TagMatch = Field(default=TagMatch.ANY)
    """`any`: at least one of `tags`; `all`: every one."""
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("tags", mode="before")
    @classmethod
    def _split_tags(cls, value: object) -> object:
        return _normalize_tags(value)

    @field_validator("library", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class Span(_Dto):
    """A `[start, end)` range of characters."""

    start: int
    end: int


class SearchResultOut(_Dto):
    """One verbatim result with where it lives and how to read around it."""

    chunk_id: str
    article_path: str
    heading_path: list[str]
    anchor: str
    position: int
    """0-based index of the chunk in its article."""
    total: int
    """Number of chunks of the article."""
    prev_chunk_id: str | None
    next_chunk_id: str | None
    commit_sha: str
    source_url: str | None
    """Link to the section at the commit; null when the host is unknown."""
    tags: list[str]
    score: float
    """Higher is better; only comparable within one search."""
    snippet: str
    """Verbatim text of the chunk, possibly cut at either end."""
    highlights: list[Span]
    """Offsets into `snippet` of the words that matched."""

    @classmethod
    def from_models(cls, version: SearchableVersion, stored: StoredChunk, hit: SearchHit) -> Self:
        """Combine a hit with its chunk row and the version it was found in."""
        row, chunk = stored.row, stored.chunk
        return cls(
            chunk_id=row.chunk_id,
            article_path=row.article_path,
            heading_path=list(chunk.heading_path),
            anchor=chunk.anchor,
            position=row.position,
            total=row.total,
            prev_chunk_id=row.prev_chunk_id,
            next_chunk_id=row.next_chunk_id,
            commit_sha=version.commit_sha,
            source_url=source_link(version, row.article_path, chunk.anchor),
            tags=list(row.tags),
            score=hit.score,
            snippet=hit.snippet,
            highlights=[Span(start=a, end=b) for a, b in hit.highlights],
        )


class CoverageOut(_Dto):
    """How much of the index the answer stands on."""

    candidates: int
    """Lower bound: matching chunks the search looked at (`bm25`: usually `limit` + 1 at most;
    `hybrid`: the chunks of its BM25 and vector halves, each counted once)."""
    reranked: int
    """Of those, how many a reranker reordered."""
    complete: bool
    """False when more matches exist than `limit` allowed."""


class SearchDocsResult(_Dto):
    """Results of one search, best first, with the version and the way they were found."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the results."""
    library: str
    version: str
    commit_sha: str
    retrieval_mode: RetrievalMode
    """The mode that answered (the call's, the library's, the instance's, or the best one)."""
    reranked: bool
    coverage: CoverageOut
    fallback_reason: FallbackReason | None = Field(default=None)
    """Set when a cheaper mode answered than the one that would have: says why."""
    results: list[SearchResultOut]


class LibrarySearchResultOut(SearchResultOut):
    """A result of a search across libraries: also names the library and version it came from."""

    library: str
    version: str

    @classmethod
    def of(cls, version: SearchableVersion, stored: StoredChunk, hit: SearchHit) -> Self:
        """Like ``from_models``, plus the library and version."""
        result = SearchResultOut.from_models(version, stored, hit)
        return cls(**dict(result), library=version.library, version=version.version)


class LibraryFacetOut(_Dto):
    """How many chunks of one library's default version match the query."""

    library: str
    version: str
    commit_sha: str
    matches: int
    """All matching chunks, not capped by `limit`."""


class SearchAllResult(_Dto):
    """Results across libraries, best first, with the libraries that answer and their counts."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the results."""
    retrieval_mode: RetrievalMode
    reranked: bool
    coverage: CoverageOut
    libraries_searched: int
    """Libraries whose default version was searched."""
    libraries_omitted: int
    """Libraries with a default version left out because there are too many."""
    libraries: list[LibraryFacetOut]
    """Libraries with at least one match, most matches first. Never narrowed."""
    results: list[LibrarySearchResultOut]


class ChunkHeadingIn(_Dto):
    """One heading a chunk holds."""

    heading_path: list[str] = Field(min_length=1)
    """The heading and every heading above it."""
    anchor: str
    """The heading's own anchor in the article."""
    starts_chunk: bool
    """True for the heading the chunk is named after; false for one merged into it."""


class ChunkHeadingOut(_Dto):
    """One heading a stored chunk holds."""

    heading_path: list[str]
    """The heading and every heading above it."""
    anchor: str
    """The heading's own anchor in the article."""
    starts_chunk: bool
    """True for the heading the chunk is named after; false for one merged into it."""


class ChunkIn(_Dto):
    """One chunk as the chunker produced it."""

    heading_path: list[str]
    occurrence_index: int = Field(ge=0)
    content: str
    content_hash: str = Field(min_length=1)
    anchor: str
    code_languages: list[str] = Field(default_factory=list)
    headings: list[ChunkHeadingIn] | None = None
    """Every heading the chunk holds, in order, the one it is named after first; null: not
    recorded (a chunk set stored before heading records existed)."""

    @model_validator(mode="after")
    def _headings_match_the_chunk(self) -> Self:
        """Refuse heading records that contradict the chunk's own heading.

        Returns:
            The chunk unchanged.

        Raises:
            ValueError: A record other than the first starts the chunk, or the first one is not
                the chunk's own heading.
        """
        if self.headings is None:
            return self
        starting = [h for h in self.headings if h.starts_chunk]
        own = [(self.heading_path, self.anchor)] if self.heading_path else []
        if [(h.heading_path, h.anchor) for h in starting] != own or (
            starting and not self.headings[0].starts_chunk
        ):
            message = "the first heading record, and only it, is the chunk's own heading"
            raise ValueError(message)
        return self


class ArticleChunksIn(_Dto):
    """The chunks of one article of the manifest, in reading order."""

    path: str = Field(min_length=1)
    blob_sha: str = Field(min_length=1)
    """Git blob SHA of the article."""
    tags: list[str] = Field(default_factory=list)
    """Copied onto every chunk row."""
    chunks: list[ChunkIn]


class IndexManifestCommand(_Dto):
    """Index the chunks of a catalog manifest; invisible until the catalog activates it."""

    manifest_id: str = Field(min_length=1)
    """The catalog's manifest ID."""
    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)
    """Chunking-config hash the chunks were made with."""
    articles: list[ArticleChunksIn]


class IndexedManifestOut(_Dto):
    """The chunk IDs of every article, and how many chunk sets were new."""

    manifest_id: str
    chunk_ids: dict[str, list[str]]
    """Chunk IDs by article path, in order."""
    chunk_sets_stored: int
    """Chunk sets that were not stored yet."""
    already_indexed: bool = Field(default=False)
    """True when this manifest ID was indexed before; nothing changed."""


class GetChunkSetsQuery(_Dto):
    """The chunk sets of these blobs under this chunking config."""

    config_hash: str = Field(min_length=1)
    blob_shas: list[str] = Field(max_length=5000)


class SetChunkOut(_Dto):
    """One stored chunk of a chunk set."""

    heading_path: list[str]
    occurrence_index: int
    content: str
    content_hash: str
    anchor: str
    code_languages: list[str]
    headings: list[ChunkHeadingOut] | None = None
    """Every heading the chunk holds, in order; null when they were not recorded."""


class ChunkSetsOut(_Dto):
    """The chunks of every requested blob that is stored, in reading order, by blob SHA."""

    chunks: dict[str, list[SetChunkOut]]


class DiscardPendingChunksCommand(_Dto):
    """Discard the chunk rows of manifests the catalog still holds as pending.

    A manifest the catalog does not know is discarded only once it is older than a grace period,
    because indexing may legitimately run before the catalog has answered for it.

    At least one filter is required, like the catalog's command.
    """

    manifest_id: str | None = None
    library: str | None = Field(default=None)
    """`/owner/repo`, any letter case."""
    older_than_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _has_a_filter(self) -> Self:
        if self.manifest_id is None and self.library is None and self.older_than_seconds is None:
            message = "give a manifest_id, a library or older_than_seconds"
            raise ValueError(message)
        return self


class CollectChunksCommand(_Dto):
    """Collect chunk rows of manifests the catalog no longer knows, and unused chunk sets."""

    grace_seconds: int = Field(default=DEFAULT_GRACE_SECONDS, ge=0)


class RemoveChunksCommand(_Dto):
    """Delete the chunk rows of these manifests, which the catalog has just deleted."""

    manifest_ids: list[str] = Field(max_length=100_000)


class ArticleTagsIn(_Dto):
    """The tags an article of a manifest carries now (every source, already normalized)."""

    path: str = Field(min_length=1, max_length=MAX_PATH)
    tags: list[str] = Field(max_length=2 * MAX_TAGS)


class RetagArticlesCommand(_Dto):
    """Copy the articles' current tags onto their chunk rows, without chunking anything again."""

    manifest_id: str = Field(min_length=1)
    articles: list[ArticleTagsIn] = Field(max_length=100_000)


class RetaggedChunks(_Dto):
    """How many chunk rows got other tags."""

    chunks: int


class RemovedChunks(_Dto):
    """What a discard or collection deleted."""

    manifests: int
    chunk_sets: int

    @classmethod
    def from_model(cls, removed: Removed) -> Self:
        """Map the domain value object."""
        return cls(manifests=removed.manifests, chunk_sets=removed.chunk_sets)


class SearchIndexStateOut(_Dto):
    """The stored search index's format, and whether a rebuild would change it."""

    stored_format: int | None
    current_format: int
    needs_rebuild: bool

    @classmethod
    def from_model(cls, state: SearchIndexState) -> Self:
        """Map the domain value object."""
        return cls(
            stored_format=state.stored_format,
            current_format=state.current_format,
            needs_rebuild=state.needs_rebuild,
        )


class VectorStoreStateOut(_Dto):
    """Whether the vector store can search here, checked only once an embedding model is set."""

    requirement: str | None
    """What the store needs from the database: `sqlite-vec` or `vector` (pgvector); null when
    the instance has no vector store."""
    available: bool | None
    """It can search; null when no embedding model is configured (nothing is loaded then)."""

    @property
    def missing(self) -> str | None:
        """Name what the store needs and cannot load, or ``None`` when nothing is missing.

        Returns:
            ``requirement`` when the store was checked and cannot search.
        """
        return self.requirement if self.available is False else None


class RebuiltIndexOut(_Dto):
    """The format the search index was rebuilt in and how many chunks it holds."""

    format: int
    entries: int

    @classmethod
    def from_model(cls, rebuilt: RebuiltIndex) -> Self:
        """Map the domain value object."""
        return cls(format=rebuilt.format, entries=rebuilt.entries)


class ReadChunkQuery(_Dto):
    """Read one chunk by the ID a search result gave."""

    chunk_id: str = Field(min_length=1, max_length=MAX_NAME)


class ChunkOut(_Dto):
    """A chunk verbatim, with its place in the article and where it came from."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the fields below."""
    chunk_id: str
    library: str
    version: str
    commit_sha: str
    source_url: str | None
    """Link to the section at the commit; null when the host is unknown."""
    article_path: str
    heading_path: list[str]
    anchor: str
    content: str
    position: int
    total: int
    prev_chunk_id: str | None
    next_chunk_id: str | None
    tags: list[str]
    code_languages: list[str]

    @classmethod
    def from_stored(cls, version: SearchableVersion, stored: StoredChunk) -> Self:
        """Map a stored chunk of the active manifest of ``version``."""
        row, chunk = stored.row, stored.chunk
        return cls(
            chunk_id=row.chunk_id,
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            source_url=source_link(version, row.article_path, chunk.anchor),
            article_path=row.article_path,
            heading_path=list(chunk.heading_path),
            anchor=chunk.anchor,
            content=chunk.content,
            position=row.position,
            total=row.total,
            prev_chunk_id=row.prev_chunk_id,
            next_chunk_id=row.next_chunk_id,
            tags=list(row.tags),
            code_languages=list(chunk.code_languages),
        )


class ArticleOutlineQuery(_Dto):
    """The outline of one article of exactly one library version; no ``ref`` means the default."""

    library: str = Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """`/owner/repo`, any letter case; the version goes in `ref`."""
    ref: str | None = Field(default=None, max_length=MAX_NAME)
    """Exact imported ref; default version if empty."""
    path: str = Field(min_length=1, max_length=MAX_PATH)
    """Article path, as `list_articles` and search results give it."""

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Treat a blank ref as no ref (the default version).

        Args:
            value: The ref as sent.

        Returns:
            ``None`` for a blank string, else the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class OutlineSectionOut(_Dto):
    """One heading of the outline, with the chunk it starts and the headings under it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    heading: str
    """Heading text (untrusted repository text)."""
    chunk_id: str | None
    """The chunk that holds this heading, for `read_chunk`; null when no chunk records it."""
    anchor: str | None
    """The heading's own anchor in the article; null when `chunk_id` is."""
    starts_chunk: bool | None
    """True when the chunk starts with this heading; false when the library's chunking merged it
    into a chunk that starts earlier (`read_chunk` then returns that whole chunk); null when
    `chunk_id` is."""
    children: list[OutlineSectionOut]
    """The headings directly under it, in document order."""

    @classmethod
    def from_model(cls, node: OutlineNode) -> Self:
        """Map an outline node and everything under it.

        Args:
            node: The node to map.

        Returns:
            The node as a DTO.
        """
        entry = node.entry
        return cls(
            heading=node.heading,
            chunk_id=entry.chunk_id if entry else None,
            anchor=entry.anchor if entry else None,
            starts_chunk=entry.starts_chunk if entry else None,
            children=[cls.from_model(child) for child in node.children],
        )


class ArticleOutlineOut(_Dto):
    """An article's heading tree with a chunk ID per heading, and no body text."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the fields below."""
    library: str
    """Library ID, `/owner/repo`."""
    version: str
    """The exact ref that answered (the default version when none was asked)."""
    commit_sha: str
    """The commit the version was imported at."""
    manifest_id: str
    """The version's active manifest, the one `read_article` reads at the same moment."""
    article_path: str
    """The article's path in the version."""
    source_url: str | None
    """Link to the article at the commit; null when the host is unknown."""
    chunks: int
    """How many chunks the article has, the preamble's included: fewer than its headings when the
    library's chunking merges sections (headings with `starts_chunk` false)."""
    preamble_chunk_id: str | None
    """The chunk of the text before the first heading, if it is one; null otherwise."""
    sections: list[OutlineSectionOut]
    """The top-level headings, in document order."""

    @classmethod
    def from_model(
        cls, version: SearchableVersion, article_path: str, found: Outline, chunks: int
    ) -> Self:
        """Map the outline of an article of the active manifest of ``version``.

        Args:
            version: The version that answered.
            article_path: The article's path.
            found: Its heading tree.
            chunks: How many chunks the article has.

        Returns:
            The outline as a DTO.
        """
        return cls(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            manifest_id=version.manifest_id,
            article_path=article_path,
            source_url=source_link(version, article_path, ""),
            chunks=chunks,
            preamble_chunk_id=found.preamble.chunk_id if found.preamble else None,
            sections=[OutlineSectionOut.from_model(node) for node in found.sections],
        )


class ResolveLibraryIdQuery(_Dto):
    """A library name as an agent writes it, and what the agent is trying to do."""

    library_name: str = Field(min_length=1, max_length=MAX_NAME)
    """Library name, e.g. 'Next.js'; matched against IDs, titles and descriptions."""
    query: str = Field(min_length=1, max_length=MAX_QUERY)
    """What the agent wants to look up; libraries documenting it rank higher."""


class LibraryMatchOut(_Dto):
    """A matching library. Title and description are untrusted repository text."""

    id: str
    title: str
    description: str
    source_url: str
    default_version: str
    versions: list[str]
    """At most 50 refs; see `version_count`."""
    version_count: int
    last_imported_at: datetime | None = Field(default=None)
    """When any version was last imported."""
    articles: int
    """Articles of the default version."""
    chunks: int
    """Chunks of the default version."""
    query_hits: int
    """Chunks of the default version matching the query (capped)."""

    @classmethod
    def from_candidate(cls, candidate: Candidate, articles: int, chunks: int) -> Self:
        """Map a ranked candidate and its default version's counts."""
        lib = candidate.library
        return cls(
            id=lib.id,
            title=lib.title,
            description=lib.description,
            source_url=lib.source_url,
            default_version=lib.default_version or "",
            versions=list(lib.versions),
            version_count=lib.version_count,
            last_imported_at=lib.last_imported_at,
            articles=articles,
            chunks=chunks,
            query_hits=candidate.hits,
        )


class ResolveLibraryIdResult(_Dto):
    """Matching libraries, best first; empty when nothing matches."""

    matches: list[LibraryMatchOut]


class QueryDocsQuery(_Dto):
    """What an agent asks of one library version, as context7's `query-docs` does."""

    library_id: str = Field(
        # `LIBRARY_ID_PATTERN` (`/owner/repo`) plus an optional `/<ref>`: change them together.
        pattern=r"^/[^/]+/[^/]+(/.+)?$",
        max_length=3 * MAX_NAME,
        description=(
            "`/owner/repo` for the default version or `/owner/repo/<ref>` for exactly that ref."
        ),
    )
    query: str = Field(min_length=1, max_length=MAX_QUERY)
    language: str | None = Field(default=None, max_length=MAX_NAME)
    """Programming language; chunks with code in it come first."""

    @field_validator("language", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class DocSectionOut(_Dto):
    """One whole chunk of documentation, verbatim. Every field is untrusted repository text."""

    chunk_id: str
    article_path: str
    heading_path: list[str]
    source_url: str | None
    """Link to the section at the commit; null when the host is unknown."""
    code_languages: list[str]
    content: str
    """Empty for a pointer (`too_large`)."""
    too_large: bool = Field(default=False)
    """The chunk alone exceeds the budget: read it with `read_chunk`."""

    @property
    def title(self) -> str:
        """The heading path, or the article path when there is none."""
        return " > ".join(self.heading_path) or self.article_path

    @property
    def source(self) -> str:
        """The section link, or the article path when the host is unknown."""
        return self.source_url or self.article_path

    @classmethod
    def from_stored(cls, version: SearchableVersion, stored: StoredChunk) -> Self:
        """Map a stored chunk of the active manifest of ``version``."""
        row, chunk = stored.row, stored.chunk
        return cls(
            chunk_id=row.chunk_id,
            article_path=row.article_path,
            heading_path=list(chunk.heading_path),
            source_url=source_link(version, row.article_path, chunk.anchor),
            code_languages=list(chunk.code_languages),
            content=chunk.content,
        )

    def as_pointer(self) -> Self:
        """Return the section without its text, for a chunk that cannot fit the budget."""
        return self.model_copy(update={"content": "", "too_large": True})


class QueryDocsResult(_Dto):
    """Whole chunks of one exact version, best first, that fit the size budget."""

    library: str
    version: str
    commit_sha: str
    retrieval_mode: RetrievalMode
    reranked: bool = False
    """A reranker reordered the candidates."""
    fallback_reason: FallbackReason | None = None
    """Set when a cheaper mode answered than the one that would have: says why."""
    sections: list[DocSectionOut]
    omitted: int
    """Matching chunks neither shown nor pointed to: the budget was used up."""
    budget_chars: int
    rules: list[str] = Field(default_factory=list)
    """The library's `context7.json` rules that fit the budget, shown before the sections. Untrusted
    repository text.
    """


class GetLibraryRetrievalQuery(_Dto):
    """Which library's retrieval setting to read."""

    library: str = Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """`/owner/repo`, any letter case."""


class SetLibraryRetrievalCommand(_Dto):
    """Set (or clear, with no ``mode``) the retrieval mode a library's searches use by default."""

    library: str = Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """`/owner/repo`, any letter case."""
    mode: str | None = Field(default=None, max_length=MAX_NAME)
    """`bm25`, `hybrid`, `hybrid_hyde` or `agentic`; it must be available now. Empty: use the
    instance's mode.
    """

    ai_enabled: bool = True
    """False: nothing of the library is ever sent to an AI provider, and its searches are BM25."""
    llm: str | None = Field(default=None, max_length=MAX_MODEL_REF)
    """The library's own LLM, `<profile>:<model>`; empty: the instance's `llm` role."""
    judge: str | None = Field(default=None, max_length=MAX_MODEL_REF)
    """The library's own judge, `<profile>:<model>`; empty: the instance's (else the LLM)."""
    reranker: str | None = Field(default=None, max_length=MAX_MODEL_REF)
    """The library's own reranker, `<profile>:<model>`; empty: the instance's `reranker` role."""

    @field_validator("mode", "llm", "judge", "reranker", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Treat a blank mode or model as none.

        Args:
            value: The raw mode or model.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class LibraryRetrievalOut(_Dto):
    """A library's retrieval setting and the mode its searches use now when a call names none."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    library: str
    """`/owner/repo` as the catalog spells it."""
    mode: RetrievalMode | None
    """The library's own setting; null: the instance's mode applies."""
    instance_mode: RetrievalMode | None
    """The instance's setting (`EXACTDOCS_AI__MODE`); null: the best mode configured."""
    effective_mode: RetrievalMode
    """The mode a search without `mode` runs in now."""
    fallback_reason: FallbackReason | None = Field(default=None)
    """Set when a setting cannot run now and was skipped: a role it needs is not configured
    (`mode_unavailable`), or the vector store cannot be loaded (`vector_store_unavailable`)."""
    available_modes: list[RetrievalMode]
    """The modes a call or a setting may name now."""
    configured_roles: list[ModelRole]
    """The model roles this library's searches may use now (none with AI off)."""
    ai_enabled: bool = True
    """False: nothing of the library is sent to an AI provider; its searches are BM25."""
    llm: str | None = None
    """The library's own LLM (`<profile>:<model>`); null: the instance's."""
    judge: str | None = None
    """The library's own judge (`<profile>:<model>`); null: the instance's, else the LLM."""
    reranker: str | None = None
    """The library's own reranker (`<profile>:<model>`); null: the instance's."""


class ForgetLibraryCommand(_Dto):
    """A library was removed: drop what retrieval stores for it (its mode and AI overrides)."""

    library: str = Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """`/owner/repo`, any letter case."""


class ProviderNameQuery(_Dto):
    """Which provider profile."""

    name: str = Field(pattern=PROFILE_NAME_PATTERN)
    """The profile's name: lower case, digits, `_` and `-`."""


class SaveProviderCommand(_Dto):
    """Create (``create``) or replace a provider profile managed over the REST API."""

    name: str = Field(pattern=PROFILE_NAME_PATTERN)
    """The profile's name, used in roles as `<name>:<model>`: lower case, digits, `_`, `-`."""
    create: bool = False
    """True: fail with `provider_exists` when it exists; false: replace it (or create it)."""
    kind: str = Field(max_length=MAX_NAME)
    """`openai-compatible`, `openai`, `openrouter`, `anthropic`, `azure`, `google-vertex`,
    `google`, `ollama`, `vllm`, `litellm`, `local`, or one of pydantic-ai's OpenAI-API providers
    (`deepseek`, `together`, `fireworks`, `cerebras`, `github`, `vercel`, `moonshotai`, `heroku`,
    `nebius`, `ovhcloud`, `sambanova`, `alibaba`).
    """
    base_url: str | None = Field(default=None, max_length=MAX_URL)
    """The endpoint; required for `openai-compatible`, `ollama`, `vllm`, `litellm` and `azure`."""
    api_key: SecretStr | None = Field(default=None, max_length=MAX_KEY)
    """The key, sealed with the instance's secret key and never returned. Omitted: keep the stored
    key (see `keep_key`); a profile without a key sends the placeholder `unused`.
    """
    keep_key: bool = True
    """When `api_key` is omitted, keep the key stored before; false removes it."""
    headers: dict[str, str] = Field(default_factory=dict)
    """Extra headers of every call (never returned or logged). No credentials: `Authorization`,
    `Cookie`, `*-key`, `*-token` and the like are refused; the key goes in `api_key`.
    """
    proxy: str | None = Field(default=None, max_length=MAX_URL)
    """An HTTP(S) proxy for this profile only."""
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    """Overall timeout of one call, in seconds."""
    max_retries: int = DEFAULT_RETRIES
    """Retries of one call."""
    api_version: str | None = Field(default=None, max_length=MAX_NAME)
    """Azure OpenAI's API version."""
    project: str | None = Field(default=None, max_length=MAX_NAME)
    """Google Cloud project (`google-vertex`, `anthropic` on `vertex`)."""
    location: str | None = Field(default=None, max_length=MAX_NAME)
    """Google Cloud location, or the AWS region of Claude on Bedrock."""
    credentials_file: str | None = Field(default=None, max_length=MAX_PATH)
    """Refused here (422 `invalid_provider`): the server's own cloud identity is configured in
    the environment or the configuration file only.
    """
    credentials: Literal["adc"] | None = None
    """Refused here, as `credentials_file`: configuration only."""
    platform: AnthropicPlatform | None = None
    """`anthropic` only: `api` (default), `vertex`, `foundry` or `bedrock` (needs boto3)."""
    auth: AzureAuth | None = None
    """`key` (the default); `entra` (Entra ID) is refused here: configuration only."""
    resource: str | None = Field(default=None, max_length=MAX_NAME)
    """Azure OpenAI or Claude on Azure AI Foundry: the resource name, instead of `base_url`."""

    @field_validator("base_url", "proxy", "api_version", "project", "location", mode="before")
    @classmethod
    def _blank_text_is_none(cls, value: object) -> object:
        """Treat blank text as unset.

        Args:
            value: The raw field.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class ProviderOut(_Dto):
    """A provider profile as the REST API shows it: never its key or its header values."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    """Used in roles as `<name>:<model>`."""
    kind: ProviderKind
    """What it talks to."""
    origin: ProfileOrigin
    """`configuration` (the environment or the TOML file: read-only here) or `api`."""
    read_only: bool
    """Changed only where it is configured."""
    base_url: str | None
    """The endpoint; null: the platform's own."""
    key: KeySource
    """Where its key comes from (`none`, `sealed`, `file`, `environment`); never the key."""
    header_names: list[str]
    """The extra headers it sends; their values are never shown."""
    proxy: str | None
    """Its proxy, any password masked."""
    request_timeout: float
    """Overall timeout of one call, in seconds."""
    max_retries: int
    """Retries of one call."""
    api_version: str | None
    """Azure OpenAI's API version."""
    project: str | None
    """Google Cloud project."""
    location: str | None
    """Google Cloud location or AWS region."""
    credentials_file: str | None
    """Google service-account file."""
    credentials: Literal["adc"] | None
    """`adc` when Application Default Credentials are used."""
    platform: AnthropicPlatform | None
    """Where an `anthropic` profile reaches Claude."""
    auth: AzureAuth | None
    """How an Azure profile signs its calls."""
    resource: str | None
    """Azure AI Foundry resource."""
    roles: list[ModelRole]
    """The instance roles set to one of its models."""
    unsupported: str | None
    """Why this installation cannot call it (an extra or an SDK to install); null when it can."""

    @classmethod
    def from_model(
        cls, profile: ProviderProfile, roles: list[ModelRole], unsupported: str | None
    ) -> Self:
        """Describe a profile.

        Args:
            profile: The profile.
            roles: The instance roles that use it.
            unsupported: Why it cannot be called here, if it cannot.

        Returns:
            The description, without secrets.
        """
        return cls(
            name=profile.name,
            kind=profile.kind,
            origin=profile.origin,
            read_only=profile.read_only,
            base_url=profile.base_url,
            key=profile.key,
            header_names=list(profile.header_names),
            proxy=profile.shown_proxy,
            request_timeout=profile.request_timeout,
            max_retries=profile.max_retries,
            api_version=profile.api_version,
            project=profile.project,
            location=profile.location,
            credentials_file=profile.credentials_file,
            credentials="adc" if profile.adc else None,
            platform=profile.platform,
            auth=profile.auth,
            resource=profile.resource,
            roles=roles,
            unsupported=unsupported,
        )


class ProviderListOut(_Dto):
    """Every provider profile: the configured ones first, then those stored over the API."""

    providers: list[ProviderOut]
    """The profiles."""


class RoleOut(_Dto):
    """One instance role and the model it uses."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    role: ModelRole
    """`embedding`, `reranker`, `llm` or `judge`."""
    model: str | None
    """`<profile>:<model>`; null when the role is not set."""
    source: RoleSource | None
    """`instance`, or `llm` for a judge that defaults to the LLM; null when not set."""
    profile_exists: bool
    """False when the role names a profile that does not exist (the role is then not usable)."""


class RoleListOut(_Dto):
    """The instance's roles (set in the environment or the TOML file)."""

    roles: list[RoleOut]
    """One per role."""


class CheckProviderCommand(_Dto):
    """Check one profile: the roles that use it, or a model named here."""

    name: str = Field(pattern=PROFILE_NAME_PATTERN)
    """The profile."""
    role: ModelRole | None = None
    """How to call `model`: `llm`/`judge` (a chat turn), `embedding` or `reranker`."""
    model: str | None = Field(default=None, max_length=MAX_MODEL_NAME)
    """A model to check instead of the roles' (needs `role`)."""

    @model_validator(mode="after")
    def _model_with_role(self) -> Self:
        """A model is checked as some role.

        Returns:
            The command.

        Raises:
            ValueError: ``model`` without ``role``, or the reverse.
        """
        if (self.model is None) != (self.role is None):
            message = "name both a role and a model, or neither"
            raise ValueError(message)
        return self


class ModelCheckOut(_Dto):
    """One minimal call to a model: whether it answered, how fast, and what."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    role: ModelRole | None
    """The role checked; null for a model named by hand."""
    profile: str
    """The profile called."""
    model: str
    """The model asked for."""
    status: Literal["ok", "error"]
    """`ok` when the call answered as expected."""
    latency_ms: float
    """How long the call took, in milliseconds."""
    served_model: str | None
    """The model the provider says answered."""
    dimensions: int | None
    """An embedding model's vector size."""
    error: str | None
    """Why the call failed; never holds a key."""

    @classmethod
    def from_model(cls, check: ModelCheck) -> Self:
        """Describe a check.

        Args:
            check: The outcome.

        Returns:
            The description.
        """
        return cls(
            role=check.role,
            profile=check.profile,
            model=check.model,
            status="ok" if check.ok else "error",
            latency_ms=round(check.latency_ms, 1),
            served_model=check.served_model,
            dimensions=check.dimensions,
            error=check.error,
        )


class ModelChecksOut(_Dto):
    """The checks of a profile, or of every role (`exactdocs ai check`)."""

    checks: list[ModelCheckOut]
    """One per role (or the model named)."""

    @property
    def ok(self) -> bool:
        """Say whether every check passed.

        Returns:
            True when all are `ok` (and there is at least one).
        """
        return bool(self.checks) and all(c.status == "ok" for c in self.checks)


class OpenEmbeddingSpaceCommand(_Dto):
    """The embedding model the instance uses now: find its space, or create one for it."""

    profile_kind: str = Field(min_length=1, max_length=MAX_NAME)
    """The provider profile's kind (`openai`, `local`...)."""
    model: str = Field(min_length=1, max_length=MAX_NAME)
    """The embedding model, as the provider names it."""
    dimensions: int = Field(ge=1, le=MAX_EMBEDDING_DIMENSIONS)
    """How many numbers the model's vectors hold."""
    input_format: int = Field(default=EMBEDDING_INPUT_FORMAT, ge=1)
    """What a chunk's embedding is computed from."""


class EmbeddingSpaceOut(_Dto):
    """An embedding space: the vectors of one model, never compared with another's."""

    id: int
    """The space's ID; its vectors live in `retrieval_vec_<id>`."""
    profile_kind: str
    """The provider profile's kind."""
    model: str
    """The embedding model."""
    dimensions: int
    """How many numbers each vector holds."""
    metric: VectorMetric
    """How vectors are compared."""
    input_format: int
    """What a chunk's embedding is computed from."""
    state: SpaceState
    """`building`, `active` or `retired`."""
    created_at: datetime
    """When the space was created."""
    activated_at: datetime | None
    """When it became the active space, if it did."""
    created: bool
    """True when this call created the space (the model changed); False when it existed."""

    @classmethod
    def from_model(cls, space: EmbeddingSpace, *, created: bool) -> Self:
        """Map the domain entity.

        Args:
            space: The space.
            created: Whether the call created it.

        Returns:
            The DTO.
        """
        return cls(
            id=space.id,
            profile_kind=space.spec.profile_kind,
            model=space.spec.model,
            dimensions=space.spec.dimensions,
            metric=space.spec.metric,
            input_format=space.spec.input_format,
            state=space.state,
            created_at=space.created_at,
            activated_at=space.activated_at,
            created=created,
        )


class EmbedVersionCommand(_Dto):
    """A version to embed with the instance's embedding model (an ``embed`` job)."""

    library: str = Field(min_length=1, max_length=MAX_NAME)
    """The library ID."""
    ref: str = Field(min_length=1, max_length=MAX_NAME)
    """The version."""


class EmbeddingPlanOut(_Dto):
    """What an ``embed`` job of one version is to do: which space, which manifest, how much."""

    space_id: int | None
    """The space the version is embedded into; null when nothing is to be sent."""
    manifest_id: str | None
    """The version's active manifest; null when nothing is to be sent."""
    missing: int
    """Chunks of the manifest without a vector in the space when the plan was made."""
    created: bool
    """This plan created the space: the model changed, so every version needs embedding."""
    skipped: EmbeddingSkip | None
    """Why nothing is to be sent, if nothing is."""


class EmbedBatchCommand(_Dto):
    """One batch of an ``embed`` job: the next chunks of the manifest without a vector."""

    library: str = Field(min_length=1, max_length=MAX_NAME)
    """The library ID (its AI setting is read again)."""
    ref: str = Field(min_length=1, max_length=MAX_NAME)
    """The version (its article titles are part of what is embedded)."""
    manifest_id: str = Field(min_length=1, max_length=MAX_NAME)
    """The manifest the plan named."""
    space_id: int
    """The space the plan named."""


class EmbeddedBatchOut(_Dto):
    """What one batch embedded."""

    embedded: int
    """Vectors stored."""
    input_tokens: int
    """Tokens the provider reported."""
    finished: bool
    """No chunk of the manifest is left to embed (or nothing may be sent any more)."""


class FinishEmbeddingCommand(_Dto):
    """An ``embed`` job finished its version: switch spaces once one covers every version."""

    space_id: int
    """The space the job embedded into."""


class FinishedEmbeddingOut(_Dto):
    """The space after the check, and the spaces it replaced."""

    space_id: int
    """The space."""
    state: SpaceState
    """`active` once it covers every version of every library with AI on."""
    retired: list[int]
    """The spaces retired now that it covers everything (their vectors are dropped)."""


class UnembeddedVersionsQuery(_Dto):
    """Which versions the instance's embedding model has not fully embedded."""

    library: str | None = Field(default=None, max_length=MAX_NAME)
    """Only this library's; every library's when null."""


class VersionRefOut(_Dto):
    """One version of one library."""

    library: str
    """The library ID."""
    ref: str
    """The version."""


class UnembeddedVersionsOut(_Dto):
    """Versions to queue ``embed`` jobs for."""

    versions: list[VersionRefOut]
    """Versions with an active manifest, of libraries with AI on, not covered by the space of
    the configured model; empty when no embedding model is configured."""


class EmbeddingEstimateOut(_Dto):
    """What embedding every version not embedded yet would send and cost, before it runs.

    Counted from characters (4 per token), never with the model's tokenizer, and priced with the
    bundled price list: an estimate, as `note` says.
    """

    model: str | None
    """The embedding role's model, `<profile>:<model>`; null when none is configured."""
    space_id: int | None
    """The space of that model, if it has one yet."""
    versions: int
    """Versions looked at: active ones of libraries with AI on."""
    chunks: int
    """Distinct stored chunks without a vector (a blob shared by versions counts once)."""
    characters: int
    """Characters of their text, heading paths and article titles, as they are embedded."""
    estimated_tokens: int
    """`characters` / 4, rounded up: an estimate."""
    usd_per_million_tokens: float | None
    """The model's input price; null when the price list does not know the model."""
    estimated_usd: float | None
    """The estimated tokens at that price; null without a price."""
    note: str = Field(default=ESTIMATE_NOTE)
    """How the numbers were made."""
