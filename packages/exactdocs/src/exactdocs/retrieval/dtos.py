"""Data crossing the retrieval boundary. Immutable, validated."""

from collections.abc import Iterable
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exactdocs.retrieval.models import Excerpt, Removed, StoredChunk


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SearchDocsQuery(_Dto):
    """Search within exactly one library version."""

    library: str = Field(min_length=1)
    version: str = Field(min_length=1)
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class ExcerptOut(_Dto):
    """One verbatim excerpt with its provenance."""

    text: str
    source_url: str
    library: str
    version: str
    commit_sha: str | None

    @classmethod
    def from_model(cls, excerpt: Excerpt) -> Self:
        """Map a domain value object to its boundary representation."""
        return cls(
            text=excerpt.text,
            source_url=excerpt.source_url,
            library=excerpt.target.library,
            version=excerpt.target.version,
            commit_sha=excerpt.commit_sha,
        )


class SearchDocsResult(_Dto):
    """Excerpts ordered from most to least relevant."""

    excerpts: list[ExcerptOut]

    @classmethod
    def from_models(cls, excerpts: Iterable[Excerpt]) -> Self:
        """Map domain value objects, keeping their order."""
        return cls(excerpts=[ExcerptOut.from_model(e) for e in excerpts])


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
