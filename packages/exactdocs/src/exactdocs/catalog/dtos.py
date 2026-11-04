"""Data crossing the catalog boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from exactdocs.catalog.models import (
    GarbageCollected,
    HostKind,
    Library,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestState,
    RefKind,
    StoredArticle,
    Version,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, Page


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _FromModel(BaseModel):
    """Boundary copy of a domain value object with the same field names."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)


class TagRuleOut(_FromModel):
    """Articles whose path matches `pattern` get `tag`."""

    pattern: str
    tag: str


class ChunkingOut(_FromModel):
    """How articles are cut into chunks."""

    split_level: int
    min_chars: int
    max_chars: int | None


class LibrarySettingsOut(_FromModel):
    """A library's import settings."""

    include_paths: list[str]
    exclude_paths: list[str]
    tag_rules: list[TagRuleOut]
    chunking: ChunkingOut

    @classmethod
    def from_model(cls, settings: LibrarySettings) -> Self:
        """Map the domain value object."""
        return cls.model_validate(settings)


class VersionOut(_Dto):
    """One imported version: the ref, what kind of ref it is, and the commit it stands for."""

    ref: str
    kind: RefKind
    commit_sha: str
    imported_at: datetime
    is_default: bool = Field(description="True for the version `/owner/repo` resolves to.")

    @classmethod
    def from_model(cls, version: Version, *, is_default: bool) -> Self:
        """Map a domain entity."""
        return cls(
            ref=str(version.ref),
            kind=version.kind,
            commit_sha=version.commit_sha,
            imported_at=version.imported_at,
            is_default=is_default,
        )


class ResolvedVersion(VersionOut):
    """The version an ID resolved to; always states which one was used."""

    library: str

    @classmethod
    def from_library(cls, library: Library, version: Version) -> Self:
        """Map the library and the chosen version."""
        found = VersionOut.from_model(version, is_default=version == library.default_version())
        return cls(library=str(library.id), **found.model_dump())


class LibrarySummary(_Dto):
    """A library and its version refs, sorted."""

    id: str
    title: str
    description: str
    versions: list[str]
    default_version: str | None

    @classmethod
    def from_model(cls, library: Library) -> Self:
        """Map a domain entity to its boundary representation."""
        default = library.default_version()
        return cls(
            id=str(library.id),
            title=library.title,
            description=library.description,
            versions=sorted(str(v.ref) for v in library.versions),
            default_version=str(default.ref) if default else None,
        )


class LibraryDetail(_Dto):
    """Everything known about one library."""

    id: str
    title: str
    description: str
    source_url: str
    host: HostKind
    default_branch: str | None
    settings: LibrarySettingsOut
    versions: list[VersionOut]
    default_version: str | None

    @classmethod
    def from_model(cls, library: Library) -> Self:
        """Map a domain entity to its boundary representation."""
        default = library.default_version()
        return cls(
            id=str(library.id),
            title=library.title,
            description=library.description,
            source_url=library.source_url,
            host=library.host,
            default_branch=str(library.default_branch) if library.default_branch else None,
            settings=LibrarySettingsOut.from_model(library.settings),
            versions=[
                VersionOut.from_model(v, is_default=v == default)
                for v in sorted(library.versions, key=lambda v: v.ref.value)
            ],
            default_version=str(default.ref) if default else None,
        )


Limit = Annotated[int, Field(ge=1, le=MAX_LIMIT)]


class ListLibrariesQuery(_Dto):
    """One page of libraries: ``limit`` items after the opaque ``cursor`` of the previous page."""

    limit: Limit = DEFAULT_LIMIT
    cursor: str | None = None


class LibraryList(_Dto):
    """A page of the libraries visible to the caller, sorted by ID."""

    libraries: list[LibrarySummary]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )

    @classmethod
    def from_page(cls, page: Page[Library]) -> Self:
        """Map a page of domain entities."""
        return cls(
            libraries=[LibrarySummary.from_model(lib) for lib in page.items],
            next_cursor=page.next_cursor,
        )


class GetLibraryQuery(_Dto):
    """Look up one library by ID (`/owner/repo`, any letter case)."""

    id: str = Field(min_length=1)


class ResolveVersionQuery(_Dto):
    """Resolve `/owner/repo` (its default version) or `/owner/repo/<ref>` (exactly that ref)."""

    id: str = Field(min_length=1)


class ArticleIn(_Dto):
    """One article to store: where it lives, its git blob SHA, its metadata and its Markdown."""

    path: str = Field(min_length=1, description="Repository-relative, `/`-separated.")
    blob_sha: str = Field(description="Git blob SHA of the file.")
    content_version: int = Field(
        ge=0,
        description=(
            "Opaque version of the text derived from the blob (the importer's parser version). "
            "Articles with the same blob SHA and content version share one stored text."
        ),
    )
    title: str
    tags: list[str] = []
    front_matter: dict[str, Any] = {}
    content: str


class StoreManifestCommand(_Dto):
    """Store the articles of `ref` at `commit_sha` as a new, pending manifest."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str = Field(min_length=1)
    kind: RefKind
    commit_sha: str
    articles: list[ArticleIn]


class StoredManifest(_Dto):
    """A stored manifest; pass `manifest_id` to `ActivateManifest`."""

    manifest_id: str
    library: str
    ref: str
    commit_sha: str
    state: ManifestState
    article_count: int

    @classmethod
    def from_model(cls, manifest: Manifest) -> Self:
        """Map a domain entity."""
        return cls(
            manifest_id=manifest.id,
            library=str(manifest.library),
            ref=str(manifest.ref),
            commit_sha=manifest.commit_sha,
            state=manifest.state,
            article_count=len(manifest.entries),
        )


class ActivateManifestCommand(_Dto):
    """Make this pending manifest what its version serves."""

    manifest_id: str = Field(min_length=1)


class ActivatedManifest(_Dto):
    """The version after the swap: its commit is the manifest's commit."""

    manifest_id: str
    version: ResolvedVersion


class DiscardPendingManifestsCommand(_Dto):
    """Discard the pending manifests that match every filter given; at least one is required.

    Never discard "all": another import may sit between storing and activating its manifest.
    At startup, before any import runs, `older_than_seconds=0` clears what a crash left behind.
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


class DiscardedManifests(_Dto):
    """How many pending manifests were deleted."""

    count: int


DEFAULT_GRACE_SECONDS = 7 * 24 * 3600


class CollectGarbageCommand(_Dto):
    """Collect manifests superseded more than `grace_seconds` ago and the contents left unused."""

    grace_seconds: int = Field(default=DEFAULT_GRACE_SECONDS, ge=0)


class CollectionResult(_Dto):
    """What a garbage collection deleted."""

    manifests: int
    contents: int

    @classmethod
    def from_model(cls, collected: GarbageCollected) -> Self:
        """Map the domain value object."""
        return cls(manifests=collected.manifests, contents=collected.contents)


class ListArticlesQuery(_Dto):
    """One page of a version's articles; no `ref` means the default version."""

    library: str = Field(min_length=1)
    ref: str | None = None
    path_prefix: str = Field(
        default="",
        description=(
            "Only paths inside this directory: `guide` matches `guide/install.md`, "
            "not `guide-old/x.md`. Empty lists everything."
        ),
    )
    limit: Limit = DEFAULT_LIMIT
    cursor: str | None = None


class ArticleSummary(_Dto):
    """An article as listed in a tree: no content."""

    path: str
    title: str
    tags: list[str]
    size: int

    @classmethod
    def from_model(cls, entry: ManifestEntry) -> Self:
        """Map a manifest entry."""
        return cls(path=entry.path, title=entry.title, tags=list(entry.tags), size=entry.size)


class ArticleList(_Dto):
    """A page of articles of one manifest, sorted by path."""

    library: str
    ref: str
    commit_sha: str
    manifest_id: str
    articles: list[ArticleSummary]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )


class GetArticleQuery(_Dto):
    """Read the article at `path` of a version; no `ref` means the default version."""

    library: str = Field(min_length=1)
    ref: str | None = None
    path: str = Field(min_length=1)


class Article(ArticleSummary):
    """One article with its Markdown and the commit it comes from."""

    library: str
    ref: str
    commit_sha: str
    manifest_id: str
    front_matter: dict[str, Any]
    content: str

    @classmethod
    def from_stored(cls, library: str, ref: str, stored: StoredArticle) -> Self:
        """Map a stored article of the given version."""
        return cls(
            library=library,
            ref=ref,
            commit_sha=stored.commit_sha,
            manifest_id=stored.manifest_id,
            front_matter=stored.entry.front_matter,
            content=stored.content,
            **ArticleSummary.from_model(stored.entry).model_dump(),
        )


class GetManifestStatesQuery(_Dto):
    """Ask for the state of manifests by ID."""

    manifest_ids: list[str]


class GetActiveManifestQuery(_Dto):
    """Ask which manifest serves a version (the library's default one without a ref)."""

    library: str = Field(min_length=1)
    ref: str | None = None


class ActiveManifest(_Dto):
    """The manifest serving a version, or ``None`` while it has none."""

    library: str
    ref: str
    commit_sha: str = Field(description="The commit of the manifest, else of the version.")
    manifest_id: str | None


class ManifestStates(_Dto):
    """Manifest state by ID; IDs the catalog does not know are left out."""

    states: dict[str, ManifestState]


class CreateLibraryCommand(_Dto):
    """Add an empty library; its versions arrive with imports."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    host: HostKind
    default_branch: str | None = None
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)


class DiscardLibraryCommand(_Dto):
    """Undo ``CreateLibrary`` for a library that has no versions."""

    id: str = Field(min_length=1)
