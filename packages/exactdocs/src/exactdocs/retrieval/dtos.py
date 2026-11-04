"""Data crossing the retrieval boundary. Immutable, validated."""

from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from exactdocs.retrieval.models import (
    Removed,
    RetrievalMode,
    SearchableVersion,
    SearchHit,
    StoredChunk,
    TagMatch,
    source_link,
)
from exactdocs_kernel import (
    LIBRARY_ID_PATTERN,
    MAX_NAME,
    MAX_TAG_INPUT,
    NOTICE,
    normalize_tag,
)


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


MAX_QUERY = 1000
MAX_TAGS = 20
MAX_TAG = MAX_TAG_INPUT

Tag = Annotated[str, StringConstraints(max_length=MAX_TAG)]


class SearchDocsQuery(_Dto):
    """Search within exactly one library version; no ``ref`` means the default version."""

    library: str = Field(
        pattern=LIBRARY_ID_PATTERN,
        max_length=MAX_NAME,
        description="`/owner/repo`, any letter case; the version goes in `ref`.",
    )
    ref: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description="Exact imported ref; default version if empty.",
    )
    query: str = Field(min_length=1, max_length=MAX_QUERY)
    tags: list[Tag] = Field(
        default_factory=list,
        max_length=MAX_TAGS,
        description="Only chunks of articles so tagged. Case-insensitive; a comma separates tags.",
    )
    tags_match: TagMatch = Field(
        default=TagMatch.ANY, description="`any`: at least one of `tags`; `all`: every one."
    )
    limit: int = Field(default=5, ge=1, le=50)

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: object) -> object:
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
    position: int = Field(description="0-based index of the chunk in its article.")
    total: int = Field(description="Number of chunks of the article.")
    prev_chunk_id: str | None
    next_chunk_id: str | None
    commit_sha: str
    source_url: str | None = Field(
        description="Link to the section at the commit; null when the host is unknown."
    )
    tags: list[str]
    score: float = Field(description="Higher is better; only comparable within one search.")
    snippet: str = Field(description="Verbatim text of the chunk, possibly cut at either end.")
    highlights: list[Span] = Field(description="Offsets into `snippet` of the words that matched.")

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

    candidates: int = Field(
        description="Lower bound: matching chunks the search looked at, at most `limit` + 1."
    )
    # Constant (0) while BM25 is the only mode; the shape is mode-agnostic on purpose.
    reranked: int = Field(description="Of those, how many a reranker reordered.")
    complete: bool = Field(description="False when more matches exist than `limit` allowed.")


class SearchDocsResult(_Dto):
    """Results of one search, best first, with the version and the way they were found."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the results."
    )
    library: str
    version: str
    commit_sha: str
    retrieval_mode: RetrievalMode
    reranked: bool
    coverage: CoverageOut
    # Always null until a mode that can fall back exists.
    fallback_reason: str | None = Field(
        default=None, description="Why a better mode was not used, when one was asked for."
    )
    results: list[SearchResultOut]


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
    blob_sha: str = Field(min_length=1, description="Git blob SHA of the article.")
    tags: list[str] = Field(default_factory=list, description="Copied onto every chunk row.")
    chunks: list[ChunkIn]


class IndexManifestCommand(_Dto):
    """Index the chunks of a catalog manifest; invisible until the catalog activates it."""

    manifest_id: str = Field(min_length=1, description="The catalog's manifest ID.")
    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str = Field(min_length=1)
    config_hash: str = Field(
        min_length=1, description="Chunking-config hash the chunks were made with."
    )
    articles: list[ArticleChunksIn]


class IndexedManifestOut(_Dto):
    """The chunk IDs of every article, and how many chunk sets were new."""

    manifest_id: str
    chunk_ids: dict[str, list[str]] = Field(description="Chunk IDs by article path, in order.")
    chunk_sets_stored: int = Field(description="Chunk sets that were not stored yet.")
    already_indexed: bool = Field(
        default=False, description="True when this manifest ID was indexed before; nothing changed."
    )


class GetChunkSetsQuery(_Dto):
    """The chunk sets of these blobs under this chunking config."""

    config_hash: str = Field(min_length=1)
    blob_shas: list[str]


class ChunkSetsOut(_Dto):
    """The chunks of every requested blob that is stored, in reading order, by blob SHA."""

    chunks: dict[str, list[ChunkIn]]


class DiscardPendingChunksCommand(_Dto):
    """Discard the chunk rows of manifests the catalog still holds as pending.

    A manifest the catalog does not know is discarded only once it is older than a grace period,
    because indexing may legitimately run before the catalog has answered for it.

    At least one filter is required, like the catalog's command.
    """

    manifest_id: str | None = None
    library: str | None = Field(default=None, description="`/owner/repo`, any letter case.")
    older_than_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _has_a_filter(self) -> Self:
        if self.manifest_id is None and self.library is None and self.older_than_seconds is None:
            message = "give a manifest_id, a library or older_than_seconds"
            raise ValueError(message)
        return self


DEFAULT_GRACE_SECONDS = 7 * 24 * 3600


class CollectChunksCommand(_Dto):
    """Collect chunk rows of manifests the catalog no longer knows, and unused chunk sets."""

    grace_seconds: int = Field(default=DEFAULT_GRACE_SECONDS, ge=0)


class RemovedChunks(_Dto):
    """What a discard or collection deleted."""

    manifests: int
    chunk_sets: int

    @classmethod
    def from_model(cls, removed: Removed) -> Self:
        """Map the domain value object."""
        return cls(manifests=removed.manifests, chunk_sets=removed.chunk_sets)


class GetChunkQuery(_Dto):
    """Read one chunk of a version's active manifest."""

    library: str = Field(min_length=1)
    version: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)


class ChunkOut(_Dto):
    """A chunk with its place in the article."""

    chunk_id: str
    library: str
    version: str
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
    def from_stored(cls, library: str, version: str, stored: StoredChunk) -> Self:
        """Map a stored chunk of ``library``@``version``."""
        row, chunk = stored.row, stored.chunk
        return cls(
            chunk_id=row.chunk_id,
            library=library,
            version=version,
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
