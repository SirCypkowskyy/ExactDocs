"""Data crossing the retrieval boundary. Immutable, validated."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from exactdocs.retrieval.constants import DEFAULT_GRACE_SECONDS, MAX_QUERY, MAX_TAG, MAX_TAGS
from exactdocs.retrieval.models import (
    Candidate,
    FallbackReason,
    ModelRole,
    Outline,
    OutlineNode,
    RebuiltIndex,
    Removed,
    RetrievalMode,
    SearchableVersion,
    SearchHit,
    SearchIndexState,
    StoredChunk,
    TagMatch,
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
    """Lower bound: matching chunks the search looked at, at most `limit` + 1."""
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


class ChunkIn(_Dto):
    """One chunk as the chunker produced it."""

    heading_path: list[str]
    occurrence_index: int = Field(ge=0)
    content: str
    content_hash: str = Field(min_length=1)
    anchor: str
    code_languages: list[str] = Field(default_factory=list)


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
    """The chunk this heading starts, for `read_chunk`; null when only deeper headings start one."""
    anchor: str | None
    """The heading's anchor in the article; null when `chunk_id` is."""
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
        return cls(
            heading=node.heading,
            chunk_id=node.section.chunk_id if node.section else None,
            anchor=node.section.anchor if node.section else None,
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
    """How many chunks the article has, the preamble's included."""
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

    @field_validator("mode", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Treat a blank mode as none.

        Args:
            value: The raw mode.

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
    """Set when a setting cannot run now (a role it needs is not configured) and was skipped."""
    available_modes: list[RetrievalMode]
    """The modes a call or a setting may name now."""
    configured_roles: list[ModelRole]
    """The model roles configured on this instance (`embedding`, `reranker`, `llm`)."""


class ForgetLibraryCommand(_Dto):
    """A library was removed: drop what retrieval stores for it (its retrieval mode)."""

    library: str = Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """`/owner/repo`, any letter case."""
