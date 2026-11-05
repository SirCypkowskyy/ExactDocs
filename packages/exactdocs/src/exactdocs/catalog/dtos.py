"""Data crossing the catalog boundary (into and out of driving ports). Immutable, validated."""

import unicodedata
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from exactdocs.catalog.models import (
    MAX_LIBRARY_RULE_CHARS,
    MAX_LIBRARY_RULES,
    GarbageCollected,
    HostKind,
    Library,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestRename,
    ManifestState,
    RefKind,
    StoredArticle,
    TagMatch,
    TagSelection,
    Version,
)
from exactdocs_kernel import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_NAME,
    MAX_PATH,
    MAX_TAG_INPUT,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    NOTICE,
    Page,
)


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


MAX_SUMMARY_REFS = 50
_PINNED = (
    "True when an owner pinned `default_version`; false when it follows the default-version rule "
    "(highest stable semver tag, else the default branch, else the newest import)."
)


class LibrarySummary(_Dto):
    """A library and its imported versions."""

    id: str
    title: str
    description: str
    default_version: str | None
    default_pinned: bool = Field(description=_PINNED)
    source_url: str
    refs: list[VersionOut] = Field(
        description=(
            "The imported versions with kind, commit SHA and default flag: the default one, then "
            f"the most recently imported, at most {MAX_SUMMARY_REFS}, sorted by ref. "
            "Pass any ref as `ref` to `list_articles` or `search_docs`."
        )
    )
    version_count: int = Field(description="How many versions are imported; `refs` may hold fewer.")
    tags: list[str] = Field(description="The tags the library's tag rules give its articles.")
    last_imported_at: datetime | None = Field(
        description="When any version was last imported; null while none is."
    )

    @classmethod
    def from_model(cls, library: Library) -> Self:
        """Map a domain entity to its boundary representation."""
        default = library.default_version()
        newest = sorted(library.versions, key=lambda v: v.imported_at, reverse=True)
        shown = ([default] if default else []) + [v for v in newest if v != default]
        return cls(
            id=str(library.id),
            title=library.title,
            description=library.description,
            default_version=str(default.ref) if default else None,
            default_pinned=library.default_is_pinned(),
            source_url=library.source_url,
            refs=[
                VersionOut.from_model(v, is_default=v == default)
                for v in sorted(shown[:MAX_SUMMARY_REFS], key=lambda v: v.ref.value)
            ],
            version_count=len(library.versions),
            tags=sorted({rule.tag for rule in library.settings.tag_rules}),
            last_imported_at=max((v.imported_at for v in library.versions), default=None),
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
    default_pinned: bool = Field(description=_PINNED)
    rules: list[str] = Field(
        default_factory=list,
        description="The rules of the default version's `context7.json`, shown to agents with "
        "every `query-docs` answer. Untrusted repository text.",
    )

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
            default_pinned=library.default_is_pinned(),
            rules=list(library.rules),
        )


Limit = Annotated[int, Field(ge=1, le=MAX_LIMIT)]


class ListLibrariesQuery(_Dto):
    """One page of libraries: ``limit`` items after the opaque ``cursor`` of the previous page."""

    limit: Limit = DEFAULT_LIMIT
    cursor: str | None = None


class LibraryList(_Dto):
    """A page of the libraries visible to the caller, sorted by ID."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the fields below."
    )

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


class RenameIn(_Dto):
    """A file git saw moved: in version `from_ref`, `old_path` became `new_path` (an article)."""

    from_ref: str = Field(min_length=1)
    old_path: str = Field(min_length=1, max_length=MAX_PATH)
    new_path: str = Field(min_length=1, max_length=MAX_PATH)
    similarity: int = Field(ge=1, le=100, description="Percent of the content kept.")


class ImageIn(_Dto):
    """One image to store: the repository path articles reference, and its bytes."""

    path: str = Field(min_length=1, max_length=MAX_PATH, description="Repository-relative.")
    blob_sha: str = Field(description="Git blob SHA of the file; equal SHAs share one copy.")
    content_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]
    data: bytes = Field(repr=False)


class StoreManifestCommand(_Dto):
    """Store the articles of `ref` at `commit_sha` as a new, pending manifest."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str = Field(min_length=1)
    kind: RefKind
    commit_sha: str
    articles: list[ArticleIn]
    images: list[ImageIn] = []
    must_exist: bool = Field(
        default=False,
        description="Refuse (VersionNotFoundError) unless the library already has this version.",
    )
    renames: list[RenameIn] = Field(
        default=[],
        description="Files moved since an earlier version; kept and replaced with the manifest.",
    )


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
    images: int = 0

    @classmethod
    def from_model(cls, collected: GarbageCollected) -> Self:
        """Map the domain value object."""
        return cls(
            manifests=collected.manifests, contents=collected.contents, images=collected.images
        )


class TagFilter(_Dto):
    """Keep articles tagged with any (default) or all of `tags`; no tags keeps every article.

    Values are normalized like tags (case, trimmed); a value that is no tag is refused.
    """

    tags: list[str] = Field(default_factory=list)
    match: TagMatch = TagMatch.ANY

    def selection(self) -> TagSelection:
        """Return the domain filter; raises `InvalidTagFilterError` for bad values."""
        return TagSelection.of(self.tags, self.match)


class ListArticlesQuery(_Dto):
    """One page of a version's articles; no `ref` means the default version."""

    library: str = Field(min_length=1)
    ref: str | None = None
    path_prefix: str = Field(
        default="",
        max_length=MAX_NAME,
        description=(
            "Only paths inside this directory: `guide` matches `guide/install.md`, "
            "not `guide-old/x.md`. Matched literally against stored paths; empty lists everything."
        ),
    )
    tag_filter: TagFilter = Field(default_factory=TagFilter, description="Applied before paging.")
    limit: Limit = DEFAULT_LIMIT
    cursor: str | None = Field(default=None, description="Opaque: only ever a `next_cursor`.")

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("path_prefix")
    @classmethod
    def _clean_path_prefix(cls, value: str) -> str:
        """Drop `.` and empty segments (`./guide//x`); refuse `..` and backslashes."""
        segments = [s for s in value.split("/") if s not in {"", "."}]
        if ".." in segments or "\\" in value:
            message = "path_prefix must be a plain `/`-separated directory"
            raise ValueError(message)
        return "/".join(segments)


class ArticleSummary(_Dto):
    """An article as listed in a tree: no content."""

    path: str
    title: str
    tags: list[str]
    size: int

    @classmethod
    def from_model(cls, entry: ManifestEntry) -> Self:
        """Map a manifest entry."""
        return cls(path=entry.path, title=entry.title, tags=list(entry.all_tags), size=entry.size)


class ArticleList(_Dto):
    """A page of articles of one manifest, sorted by path."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the fields below."
    )

    library: str
    ref: str
    commit_sha: str
    manifest_id: str
    articles: list[ArticleSummary]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )


class ListTagsQuery(_Dto):
    """The tags of a version's articles; no `ref` means the default version."""

    library: str = Field(min_length=1)
    ref: str | None = None

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class TagCount(_Dto):
    """A tag and how many articles of the version carry it."""

    tag: str
    count: int


class TagList(_Dto):
    """The most used tags of one manifest, for a tag filter."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the fields below."
    )

    library: str
    ref: str
    commit_sha: str
    tags: list[TagCount] = Field(description="Most used first, then by name; at most 100.")
    truncated: bool = Field(description="True when the version has more tags than are listed.")


class GetArticleQuery(_Dto):
    """Read the article at `path` of a version; no `ref` means the default version."""

    library: str = Field(min_length=1)
    ref: str | None = None
    path: str = Field(min_length=1, max_length=MAX_PATH)

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class RenameDirection(StrEnum):
    """Which way a path is followed across the rename map of a version."""

    FORWARD = "forward"
    """`path` is from the version imported before `ref`; the answer is its path in `ref`."""
    BACK = "back"
    """`path` is an article of `ref`; the answer is its path in the version before."""


class ResolveRenamedPathQuery(_Dto):
    """Follow `path` across the renames of `ref` (default version without one) by `direction`.

    One hop: the map covers the previous version only (a branch: its syncs so far). To follow a
    file across several versions, ask once per version and chain the answers.
    """

    library: str = Field(min_length=1)
    ref: str | None = None
    path: str = Field(min_length=1, max_length=MAX_PATH)
    direction: RenameDirection = RenameDirection.FORWARD

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class RenamedPath(_Dto):
    """`old_path` of version `from_ref` is `new_path` in `ref`, as git saw it."""

    library: str
    ref: str
    from_ref: str
    old_path: str
    new_path: str
    similarity: int = Field(description="Percent of the content kept; 100 is a move unchanged.")

    @classmethod
    def from_model(cls, library: str, ref: str, rename: ManifestRename) -> Self:
        """Map a domain value object."""
        return cls(
            library=library,
            ref=ref,
            from_ref=str(rename.from_ref),
            old_path=rename.old_path,
            new_path=rename.new_path,
            similarity=rename.similarity,
        )


class RenameAnswer(_Dto):
    """The answer to a rename lookup: `renamed` is `null` when git saw no move of that path."""

    renamed: RenamedPath | None


class ListRenamesQuery(_Dto):
    """List the renames stored with the active manifest of `ref` (default version without one)."""

    library: str = Field(min_length=1)
    ref: str | None = None

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class RenameList(_Dto):
    """Every rename of a version, by old path."""

    renames: list[RenamedPath]


class ManualTagInfo(_Dto):
    """A tag set by hand, and the article path it was set on."""

    tag: str
    path: str = Field(
        description=(
            "Where the tag was set: this article's path, or an older one it was renamed from. "
            "Change or remove the tag on this path."
        )
    )


class ArticleInfo(_Dto):
    """Where an article comes from and its metadata: everything but the text."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the fields below."
    )
    library: str
    ref: str
    commit_sha: str
    manifest_id: str
    path: str
    title: str
    tags: list[str] = Field(description="Every tag: from front matter, path rules and by hand.")
    manual_tags: list[ManualTagInfo] = Field(
        description=(
            "The tags among `tags` set by hand, each with the path it was set on: this one or "
            "one it was renamed from. A tag set on both is listed for each."
        )
    )
    size: int
    front_matter: dict[str, Any]
    source_url: str | None = Field(
        description="Link to the file at the commit; null when the host is unknown."
    )

    @classmethod
    def from_stored(
        cls, library: str, ref: str, stored: StoredArticle, source_url: str | None
    ) -> Self:
        """Map a stored article of the given version."""
        entry = stored.entry
        return cls(
            library=library,
            ref=ref,
            commit_sha=stored.commit_sha,
            manifest_id=stored.manifest_id,
            path=entry.path,
            title=entry.title,
            tags=list(entry.all_tags),
            manual_tags=[ManualTagInfo(tag=t.tag, path=t.path) for t in entry.manual_tags],
            size=entry.size,
            front_matter=entry.front_matter,
            source_url=source_url,
        )


class Article(ArticleInfo):
    """One article with its Markdown, verbatim as imported."""

    content: str

    @classmethod
    def with_content(cls, info: ArticleInfo, content: str) -> Self:
        """Add the text to an article's metadata."""
        return cls(**dict(info), content=content)


class ManualTagsIn(_Dto):
    """The tags to set by hand on an article path; they replace its earlier manual tags."""

    tags: list[Annotated[str, StringConstraints(max_length=MAX_TAG_INPUT)]] = Field(
        max_length=MAX_TAGS,
        description="Normalized like every tag (lower-case, trimmed, deduplicated). Empty: none.",
    )


class SetManualTagsCommand(ManualTagsIn):
    """Set the manual tags of `path` for every version of `library`."""

    library: str = Field(min_length=1)
    path: str = Field(min_length=1, max_length=MAX_PATH)


class ArticleTags(_Dto):
    """Every tag an article carries now (`ManifestEntry.all_tags`)."""

    path: str
    tags: list[str]


class RetaggedManifest(_Dto):
    """The articles of a manifest that have manual tags, or had some before: their tags now.

    Other domains keep copies of article tags (search filters by them) and refresh these.
    """

    manifest_id: str
    articles: list[ArticleTags]

    @classmethod
    def of(cls, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> Self:
        """Map what the repository reports."""
        return cls(
            manifest_id=manifest_id,
            articles=[ArticleTags(path=p, tags=list(t)) for p, t in sorted(tags.items())],
        )


class ManualTagsOut(_Dto):
    """The manual tags of a path, as stored: every version's article at that path gets them."""

    library: str
    path: str
    tags: list[str]
    retagged: list[RetaggedManifest] = Field(
        description="The pending and active manifests whose articles' tags are touched."
    )


class ApplyManualTagsCommand(_Dto):
    """Give a (pending) manifest the manual tags its library has now."""

    manifest_id: str = Field(min_length=1)


class ReplaceRenamesCommand(_Dto):
    """Give the active manifest of `ref` a new rename map, then its library's manual tags again.

    For a newer version whose previous version was imported after it: its renames are then
    detected against that one. Renames into a path that is not an article of the manifest are
    left out.
    """

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str = Field(min_length=1)
    renames: list[RenameIn]


class GetAssetQuery(_Dto):
    """Read the image at repository path `path` of a version; no `ref` means the default version."""

    library: str = Field(min_length=1)
    ref: str | None = None
    path: str = Field(min_length=1, max_length=MAX_PATH)
    known_blob_shas: list[str] = Field(
        default=[], description="Blob SHAs the caller holds; a match answers `unchanged`."
    )

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class Asset(_Dto):
    """An image of a version: its bytes and the type sniffed from them when it was imported."""

    blob_sha: str
    content_type: str
    data: bytes = Field(repr=False)
    unchanged: bool = Field(
        default=False, description="The blob is one of `known_blob_shas`; `data` is empty."
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


class DefaultManifest(_Dto):
    """A library's default version and the manifest serving it, with where its source lives."""

    library: str
    ref: str
    commit_sha: str = Field(description="The commit of the manifest.")
    manifest_id: str
    source_url: str
    host: HostKind


class DefaultManifests(_Dto):
    """The default versions that have an active manifest, by library ID."""

    manifests: list[DefaultManifest]


class ManifestStates(_Dto):
    """Manifest state by ID; IDs the catalog does not know are left out."""

    states: dict[str, ManifestState]


MAX_TAG_RULES = 64


class TagRuleIn(_Dto):
    """Articles whose path matches `pattern` get `tag` (already normalized by the importer)."""

    pattern: str = Field(min_length=1, max_length=256)
    tag: str = Field(min_length=1, max_length=MAX_TAG_LENGTH)


class CreateLibraryCommand(_Dto):
    """Add an empty library; its versions arrive with imports."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    host: HostKind
    default_branch: str | None = None
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    tag_rules: list[TagRuleIn] = Field(default_factory=list, max_length=MAX_TAG_RULES)


MAX_TITLE = 200
MAX_DESCRIPTION = 1000
_Title = Annotated[str, Field(min_length=1, max_length=MAX_TITLE)]
_Description = Annotated[str, Field(max_length=MAX_DESCRIPTION)]
_Rule = Annotated[str, Field(min_length=1, max_length=MAX_LIBRARY_RULE_CHARS)]


def _clean(text: str) -> str:
    r"""Drop control and format characters (zero-width, bidi, tags, escapes); keep \n and \t."""
    return "".join(
        c for c in text if c in "\n\t" or unicodedata.category(c) not in {"Cc", "Cf", "Co", "Cs"}
    )


class LibraryPatch(_Dto):
    """The fields a user may change; at least one must be given."""

    title: Annotated[str, StringConstraints(min_length=1, max_length=MAX_TITLE)] | None = Field(
        default=None, description="A single line of text. Null or absent: unchanged."
    )
    description: Annotated[str, StringConstraints(max_length=MAX_DESCRIPTION)] | None = Field(
        default=None,
        description="Empty is allowed: no description. Null or absent: unchanged.",
    )

    @field_validator("title")
    @classmethod
    def _single_line(cls, title: str | None) -> str | None:
        if title is None:
            return None
        if any(unicodedata.category(c) in {"Zl", "Zp"} or c in "\n\r\v\f\x85" for c in title):
            message = "the title must be a single line"
            raise ValueError(message)
        title = " ".join(_clean(title).split())
        if not title:
            message = "the title must have visible text"
            raise ValueError(message)
        return title

    @field_validator("description")
    @classmethod
    def _plain(cls, description: str | None) -> str | None:
        return None if description is None else _clean(description).strip()

    @model_validator(mode="after")
    def _says_something(self) -> Self:
        if self.title is None and self.description is None:
            message = "give a title or a description"
            raise ValueError(message)
        return self


class UpdateLibraryCommand(LibraryPatch):
    """Set the title and/or description of a library by hand; they are then kept for good."""

    id: str = Field(min_length=1)


class DefaultVersionPin(_Dto):
    """The version to pin as a library's default."""

    ref: str = Field(
        min_length=1,
        max_length=MAX_NAME,
        description="An imported ref, exactly as listed (case-sensitive), or a unique short SHA.",
    )


class PinDefaultVersionCommand(_Dto):
    """Pin the version `ref` names as the library's default; no `ref` unpins it."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)


class ApplyReadmeCommand(_Dto):
    """What an imported version says about its library; used only if it is the default version.

    Title and description come from its ``context7.json``, else its root README. A missing value
    means: the repository name as title, no description. ``rules`` replace the library's rules
    (empty: the version has none).
    """

    library: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    title: _Title | None = None
    description: _Description | None = None
    rules: list[_Rule] = Field(default_factory=list, max_length=MAX_LIBRARY_RULES)


class DiscardLibraryCommand(_Dto):
    """Undo ``CreateLibrary`` for a library that has no versions."""

    id: str = Field(min_length=1)


class RemoveVersionCommand(_Dto):
    """Remove one version of a library, with every manifest it ever had."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str = Field(min_length=1)


class RemoveLibraryCommand(_Dto):
    """Remove a library, all its versions and every manifest."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")


class Removal(_Dto):
    """What a removal took out of the catalog.

    `manifest_ids` lets other domains drop what they hold under those IDs. `default_ref` is the
    version `/owner/repo` means after the removal (`None`: the library has no version left; always
    `None` after `RemoveLibrary`).
    """

    library: str
    ref: str | None
    manifest_ids: list[str]
    default_ref: str | None
