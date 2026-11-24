"""Data crossing the catalog boundary (into and out of driving ports). Immutable, validated."""

import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from exactdocs.catalog.constants import (
    _HEADING_LEVELS,
    _PINNED,
    ARTICLE_SORT_FIELDS,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_MAX_CHARS,
    DEFAULT_SPLIT_LEVEL,
    LIBRARY_SORT_FIELDS,
    MAX_DESCRIPTION,
    MAX_INSTRUCTION_FILE_CHARS,
    MAX_INSTRUCTION_FILES,
    MAX_LIBRARY_RULE_CHARS,
    MAX_LIBRARY_RULES,
    MAX_STORED_ARTICLE_FILES,
    MAX_SUMMARY_REFS,
    MAX_TAG_RULES,
    MAX_TITLE,
    SIMILARITY_DESCRIPTION,
    TAG_LIST_DESCRIPTION,
    VERSION_SORT_FIELDS,
)
from exactdocs.catalog.models import (
    GarbageCollected,
    HostKind,
    Library,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestRename,
    ManifestState,
    RefKind,
    RenameDirection,
    StoredArticle,
    TagMatch,
    TagOrigin,
    TagSelection,
    TagSources,
    Version,
    VersionOrigin,
)
from exactdocs_kernel import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_NAME,
    MAX_OFFSET,
    MAX_PATH,
    MAX_TAG_INPUT,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    NOTICE,
    Page,
)


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class _FromModel(BaseModel):
    """Boundary copy of a domain value object with the same field names."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", from_attributes=True, use_attribute_docstrings=True
    )


class TagRuleOut(_FromModel):
    """Articles whose path matches `pattern` get `tag`."""

    pattern: str
    """Glob over article paths, e.g. `docs/api/**`."""
    tag: str
    """The tag a matching article gets."""


class ChunkingOut(_FromModel):
    """How articles are cut into chunks."""

    split_level: int
    """The deepest heading that starts a chunk: 2 cuts at `#` and `##` only."""
    min_chars: int
    """A chunk shorter than this is merged with the next one, within `max_chars`; 0 merges none."""
    max_chars: int | None
    """A chunk longer than this is cut again at its deeper headings; null: no bound."""
    chunker: str
    """Which chunker cuts, e.g. `markdown`."""


class LibrarySettingsOut(_FromModel):
    """A library's import settings."""

    include_paths: list[str]
    """Folders, files or globs to import; empty: every Markdown file."""
    exclude_paths: list[str]
    """Folders, files or globs to leave out; they win over `include_paths`."""
    tag_rules: list[TagRuleOut]
    """Tags given to articles by path, on top of their front-matter tags."""
    chunking: ChunkingOut
    """How the articles are cut into chunks."""

    @classmethod
    def from_model(cls, settings: LibrarySettings) -> Self:
        """Map the domain value object.

        Args:
            settings: The library's settings.

        Returns:
            The settings at the boundary.
        """
        return cls.model_validate(settings)


class VersionOut(_Dto):
    """One imported version: the ref, what kind of ref it is, and the commit it stands for."""

    ref: str
    """The ref as imported, e.g. `v1.4.0`, `main` or a commit SHA; case-sensitive."""
    kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    commit_sha: str
    """The full commit SHA the ref resolved to at its last import."""
    imported_at: datetime
    """When the version was last imported."""
    is_default: bool
    """True for the version `/owner/repo` resolves to."""
    origin: VersionOrigin = Field(default=VersionOrigin.MANUAL)
    """`auto` when the library's scheduled check imported it (retention may remove it), `manual`
    when someone added it.
    """

    @classmethod
    def from_model(cls, version: Version, *, is_default: bool) -> Self:
        """Map a domain entity.

        Args:
            version: The version.
            is_default: Whether it is the library's default version.

        Returns:
            The version at the boundary.
        """
        return cls(
            ref=str(version.ref),
            kind=version.kind,
            commit_sha=version.commit_sha,
            imported_at=version.imported_at,
            is_default=is_default,
            origin=version.origin,
        )


class ListedVersion(VersionOut):
    """A version as a library's version list shows it: with its size and embedding progress."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    articles: int = Field(default=0, ge=0)
    """The articles the version serves: the entries of its active manifest."""
    chunks: int = Field(default=0, ge=0)
    """The chunks its articles are cut into for search; 0 until it is indexed."""
    embedded_chunks: int = Field(default=0, ge=0)
    """Of `chunks`, those with a vector from the configured embedding model; 0 while no model
    is configured or nothing is embedded yet."""

    @classmethod
    def listed(cls, version: Version, *, is_default: bool, articles: int) -> Self:
        """Map a domain entity and its article count; the search index adds the chunk counts.

        Args:
            version: The version.
            is_default: Whether it is the library's default version.
            articles: The entries of its active manifest.

        Returns:
            The version at the boundary, with no chunk counted yet.
        """
        found = VersionOut.from_model(version, is_default=is_default)
        return cls(articles=articles, **found.model_dump())


class ResolvedVersion(VersionOut):
    """The version an ID resolved to; always states which one was used."""

    library: str
    """Library ID, `/owner/repo`."""

    @classmethod
    def from_library(cls, library: Library, version: Version) -> Self:
        """Map the library and the chosen version.

        Args:
            library: The library.
            version: The version the ID resolved to.

        Returns:
            The version, naming its library.
        """
        found = VersionOut.from_model(version, is_default=version == library.default_version())
        return cls(library=str(library.id), **found.model_dump())


class LibrarySummary(_Dto):
    """A library and its imported versions."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    """Library ID, `/owner/repo`."""
    title: str
    """Display name; untrusted repository text unless an owner typed it."""
    description: str
    """What the library is; untrusted repository text unless an owner typed it."""
    default_version: str | None
    """The ref `/owner/repo` resolves to; null while no version is imported."""
    default_pinned: bool = Field(description=_PINNED)
    """Whether an owner pinned the default version; its schema description is ``_PINNED``."""
    source_url: str
    """The repository's URL."""
    refs: list[VersionOut] = Field(
        description=(
            "The imported versions with kind, commit SHA and default flag: the default one, then "
            f"the most recently imported, at most {MAX_SUMMARY_REFS}, sorted by ref. "
            "Pass any ref as `ref` to `list_articles` or `search_docs`."
        )
    )
    """Some of the imported versions; its schema description names ``MAX_SUMMARY_REFS``."""
    version_count: int
    """How many versions are imported; `refs` may hold fewer."""
    tags: list[str]
    """The tags the library's tag rules give its articles."""
    last_imported_at: datetime | None
    """When any version was last imported; null while none is."""
    article_count: int = Field(default=0, ge=0)
    """The articles of the default version (its active manifest's entries); 0 while none is
    imported."""

    @classmethod
    def from_model(cls, library: Library, *, article_count: int = 0) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            library: The library.
            article_count: The articles of its default version.

        Returns:
            The summary: the default version and the newest ones, at most ``MAX_SUMMARY_REFS``.
        """
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
            article_count=article_count,
        )


class LibraryDetail(_Dto):
    """Everything known about one library."""

    id: str
    """Library ID, `/owner/repo`."""
    title: str
    """Display name; untrusted repository text unless an owner typed it."""
    description: str
    """What the library is; untrusted repository text unless an owner typed it."""
    source_url: str
    """The repository's URL."""
    host: HostKind
    """What kind of server hosts the repository; `git` is any other one."""
    default_branch: str | None
    """The repository's default branch; null until an import finds it."""
    settings: LibrarySettingsOut
    """Import settings, for every version of the library."""
    versions: list[VersionOut]
    """Every imported version, sorted by ref."""
    default_version: str | None
    """The ref `/owner/repo` resolves to; null while no version is imported."""
    default_pinned: bool = Field(description=_PINNED)
    """Whether an owner pinned the default version; its schema description is ``_PINNED``."""
    rules: list[str] = Field(default_factory=list)
    """The rules of the default version's `context7.json`, shown to agents with every `query-docs`
    answer. Untrusted repository text.
    """

    @classmethod
    def from_model(cls, library: Library) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            library: The library.

        Returns:
            Everything known about it, every version included.
        """
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
Offset = Annotated[int, Field(ge=0, le=MAX_OFFSET)]


class ListLibrariesQuery(_Dto):
    """One page of libraries: ``limit`` items after the opaque ``cursor`` of the previous page."""

    limit: Limit = DEFAULT_LIMIT
    """How many libraries per page."""
    cursor: str | None = None
    """Opaque: only ever a `next_cursor`; absent for the first page. It only works with the
    `sort` and filters of the request that returned it."""
    offset: Offset | None = None
    """Jump to a page: skip this many matches, in the order and with the filters of the cursor
    walk. Not with `cursor`; the page's `next_cursor` goes on from it."""
    sort: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description=(
            f"Sort by one of {', '.join(LIBRARY_SORT_FIELDS)}; prefix `-` for descending. "
            "Default: `id`. An unknown field is a 422."
        ),
    )
    """The sort field; its schema description names ``LIBRARY_SORT_FIELDS``."""
    q: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description="Only libraries whose ID, title or description contains this text (any case).",
    )
    """Text filter on the ID, title and description."""
    has_versions: bool | None = None
    """`true`: only libraries with an imported version; `false`: only those without one."""
    ai_enabled: bool | None = None
    """`true`: only libraries that may use AI providers; `false`: only those with AI turned off."""
    updated_after: datetime | None = None
    """Only libraries whose latest import is at or after this time (ISO 8601)."""
    updated_before: datetime | None = None
    """Only libraries whose latest import is before this time (ISO 8601)."""

    @field_validator("updated_after", "updated_before")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        """Read a time without an offset as UTC.

        Args:
            value: The time as sent.

        Returns:
            The time with an offset, or ``None``.
        """
        return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


class VersionListQuery(_Dto):
    """How a library's versions are filtered, sorted and paged."""

    q: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description="Only versions whose ref or commit SHA contains this text (any case).",
    )
    """Text filter on the ref and the commit SHA."""
    kind: list[RefKind] | None = Field(
        default=None, description="Only versions of one of these kinds; repeat for several."
    )
    """Only versions of one of these kinds (`tag`, `branch`, `commit`)."""
    origin: list[VersionOrigin] | None = Field(
        default=None, description="Only versions with one of these origins; repeat for several."
    )
    """Only versions with one of these origins (`manual`, `auto`)."""
    imported_after: datetime | None = None
    """Only versions last imported at or after this time (ISO 8601; no offset means UTC)."""
    imported_before: datetime | None = None
    """Only versions last imported before this time (ISO 8601; no offset means UTC)."""
    sort: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description=(
            f"Sort by one of {', '.join(VERSION_SORT_FIELDS)}; prefix `-` for descending. "
            "Default: `ref`. An unknown field is a 422."
        ),
    )
    """The sort field; its schema description names ``VERSION_SORT_FIELDS``."""
    limit: Limit = DEFAULT_LIMIT
    """How many versions per page."""
    cursor: str | None = None
    """Opaque: only ever a `next_cursor`; it only works with the `sort` and filters of the
    request that returned it."""
    offset: Offset | None = None
    """Jump to a page: skip this many matches, in the order and with the filters of the cursor
    walk. Not with `cursor`; the page's `next_cursor` goes on from it."""

    @field_validator("imported_after", "imported_before")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        """Read a time without an offset as UTC.

        Args:
            value: The time as sent.

        Returns:
            The time with an offset, or ``None``.
        """
        return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


class ListVersionsQuery(VersionListQuery):
    """One page of a library's versions."""

    id: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""


class VersionList(_Dto):
    """A page of a library's versions."""

    library: str
    """Library ID, `/owner/repo`."""
    versions: list[ListedVersion]
    """The versions of this page, in the requested order (by ref by default), each with its
    article, chunk and embedded-chunk counts."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""
    total: int
    """How many of the library's versions match the filters, across every page."""


class LibraryList(_Dto):
    """A page of the libraries visible to the caller, sorted by ID."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the fields below."""

    libraries: list[LibrarySummary]
    """The libraries of this page."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""
    total: int
    """How many libraries match the filters and are visible to the caller, across every page."""

    @classmethod
    def from_page(cls, page: Page[Library], *, article_counts: Mapping[str, int]) -> Self:
        """Map a page of domain entities.

        Args:
            page: The libraries and the cursor of the next page.
            article_counts: The articles of each library's default version, by library ID; a
                library left out counts 0.

        Returns:
            The page at the boundary.
        """
        return cls(
            libraries=[
                LibrarySummary.from_model(lib, article_count=article_counts.get(lib.id.value, 0))
                for lib in page.items
            ],
            next_cursor=page.next_cursor,
            total=len(page.items) if page.total is None else page.total,
        )


class GetLibraryQuery(_Dto):
    """Look up one library by ID (`/owner/repo`, any letter case)."""

    id: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""


class ResolveVersionQuery(_Dto):
    """Resolve `/owner/repo` (its default version) or `/owner/repo/<ref>` (exactly that ref)."""

    id: str = Field(min_length=1)
    """`/owner/repo` (the default version) or `/owner/repo/<ref>`."""


class TagSourcesIn(_Dto):
    """An article's imported tags by source, as the import found them."""

    front_matter: list[str] = []
    """Declared in the front matter, normalized."""
    rules: list[str] = []
    """Given by the library's tag rules that match the article's path."""

    def to_model(self) -> TagSources:
        """Map to the model.

        Returns:
            The sources, duplicates dropped.
        """
        return TagSources(
            front_matter=tuple(dict.fromkeys(self.front_matter)),
            rules=tuple(dict.fromkeys(self.rules)),
        )


class ArticleIn(_Dto):
    """One article to store: where it lives, its git blob SHA, its metadata and its Markdown."""

    path: str = Field(min_length=1)
    """Repository-relative, `/`-separated."""
    blob_sha: str
    """Git blob SHA of the file."""
    content_version: int = Field(ge=0)
    """Opaque version of the text derived from the blob (the importer's parser version). Articles
    with the same blob SHA and content version share one stored text.
    """
    title: str
    """The article's title."""
    tags: list[str] = []
    """Tags from front matter and the library's path rules."""
    tag_sources: TagSourcesIn | None = None
    """Which of `tags` come from the front matter and which from path rules; null: not known."""
    front_matter: dict[str, Any] = {}
    """The parsed front matter; untrusted repository data."""
    content: str
    """The article's Markdown, as it will be served."""


class RenameIn(_Dto):
    """A file git saw moved: in version `from_ref`, `old_path` became `new_path` (an article)."""

    from_ref: str = Field(min_length=1)
    """The version `old_path` is from."""
    old_path: str = Field(min_length=1, max_length=MAX_PATH)
    """The path in `from_ref`."""
    new_path: str = Field(min_length=1, max_length=MAX_PATH)
    """The path in the version being stored: one of its articles."""
    similarity: int = Field(ge=1, le=100)
    """Percent of the content kept."""


class ImageIn(_Dto):
    """One image to store: the repository path articles reference, and its bytes."""

    path: str = Field(min_length=1, max_length=MAX_PATH)
    """Repository-relative."""
    blob_sha: str
    """Git blob SHA of the file; equal SHAs share one copy."""
    content_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]
    """Media type sniffed from the bytes."""
    data: bytes = Field(repr=False)
    """The image's bytes."""


class InstructionFileIn(_Dto):
    """An instruction file of the commit (`AGENTS.md` / `CLAUDE.md`), kept with the manifest."""

    path: str = Field(min_length=1, max_length=MAX_PATH)
    """Repository-relative."""
    content: str = Field(max_length=MAX_INSTRUCTION_FILE_CHARS, repr=False)
    """Its text; untrusted repository content."""


class StoreManifestCommand(_Dto):
    """Store the articles of `ref` at `commit_sha` as a new, pending manifest."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    """The ref imported."""
    kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    commit_sha: str
    """The full commit SHA the ref resolved to."""
    articles: list[ArticleIn]
    """Every article of the version, one per path."""
    images: list[ImageIn] = []
    """The images the articles reference, one per path."""
    must_exist: bool = Field(default=False)
    """Refuse (VersionNotFoundError) unless the library already has this version."""
    renames: list[RenameIn] = Field(default=[])
    """Files moved since an earlier version; kept and replaced with the manifest."""
    renamed_from: str | None = Field(default=None, min_length=1)
    """The version the renames were detected against, also when nothing moved; null: the
    `from_ref` of the renames (none without renames)."""
    origin: VersionOrigin = Field(default=VersionOrigin.MANUAL)
    """Given to the version if this manifest's activation creates it."""
    instructions: list[InstructionFileIn] = Field(default=[], max_length=MAX_INSTRUCTION_FILES)
    """The commit's instruction files, kept for agentic retrieval (only with repo guidance on)."""


class StoredManifest(_Dto):
    """A stored manifest; pass `manifest_id` to `ActivateManifest`."""

    manifest_id: str
    """The new manifest's ID."""
    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The version's ref."""
    commit_sha: str
    """The commit the articles are from."""
    state: ManifestState
    """`pending` until it is activated."""
    article_count: int
    """How many articles it holds."""

    @classmethod
    def from_model(cls, manifest: Manifest) -> Self:
        """Map a domain entity.

        Args:
            manifest: The stored manifest.

        Returns:
            The manifest's ID, version and article count.
        """
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
    """The pending manifest to activate."""


class ActivatedManifest(_Dto):
    """The version after the swap: its commit is the manifest's commit."""

    manifest_id: str
    """The manifest now serving the version."""
    version: ResolvedVersion
    """The version as it is now."""


class DiscardPendingManifestsCommand(_Dto):
    """Discard the pending manifests that match every filter given; at least one is required.

    Never discard "all": another import may sit between storing and activating its manifest.
    At startup, before any import runs, `older_than_seconds=0` clears what a crash left behind.
    """

    manifest_id: str | None = None
    """Only this manifest."""
    library: str | None = Field(default=None)
    """`/owner/repo`, any letter case."""
    older_than_seconds: int | None = Field(default=None, ge=0)
    """Only manifests stored more than this many seconds ago."""

    @model_validator(mode="after")
    def _has_a_filter(self) -> Self:
        """Refuse a command without any filter.

        Returns:
            The command unchanged.

        Raises:
            ValueError: No filter is given.
        """
        if self.manifest_id is None and self.library is None and self.older_than_seconds is None:
            message = "give a manifest_id, a library or older_than_seconds"
            raise ValueError(message)
        return self


class DiscardedManifests(_Dto):
    """How many pending manifests were deleted."""

    count: int
    """Pending manifests deleted."""


class CollectGarbageCommand(_Dto):
    """Collect manifests superseded more than `grace_seconds` ago and the contents left unused."""

    grace_seconds: int = Field(default=DEFAULT_GRACE_SECONDS, ge=0)
    """Keep manifests superseded more recently than this many seconds."""


class CollectionResult(_Dto):
    """What a garbage collection deleted."""

    manifests: int
    """Manifests deleted."""
    contents: int
    """Article texts deleted."""
    images: int = 0
    """Stored images deleted."""

    @classmethod
    def from_model(cls, collected: GarbageCollected) -> Self:
        """Map the domain value object.

        Args:
            collected: What the collection removed.

        Returns:
            The counts at the boundary.
        """
        return cls(
            manifests=collected.manifests, contents=collected.contents, images=collected.images
        )


class TagFilter(_Dto):
    """Keep articles tagged with any (default) or all of `tags`; no tags keeps every article.

    Values are normalized like tags (case, trimmed); a value that is no tag is refused.
    """

    tags: list[str] = Field(default_factory=list)
    """The tags, as typed; normalized when the filter is applied."""
    match: TagMatch = TagMatch.ANY
    """`any`: at least one of `tags`; `all`: every one."""

    def selection(self) -> TagSelection:
        """Return the domain filter; ``TagSelection.of`` refuses a value that is no tag.

        Returns:
            The normalized selection.
        """
        return TagSelection.of(self.tags, self.match)


class ListArticlesQuery(_Dto):
    """One page of a version's articles; no `ref` means the default version."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = None
    """Exact imported ref; null or blank: the default version."""
    path_prefix: str = Field(default="", max_length=MAX_NAME)
    """Only paths inside this directory: `guide` matches `guide/install.md`, not `guide-old/x.md`.
    Matched literally against stored paths; empty lists everything.
    """
    tag_filter: TagFilter = Field(default_factory=TagFilter)
    """Applied before paging."""
    q: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description="Only articles whose path or title contains this text (any case).",
    )
    """Text filter on the path and title, applied before paging."""
    sort: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description=(
            f"Sort by one of {', '.join(ARTICLE_SORT_FIELDS)}; prefix `-` for descending. "
            "Default: `path`. An unknown field is a 422."
        ),
    )
    """The sort field; its schema description names ``ARTICLE_SORT_FIELDS``."""
    limit: Limit = DEFAULT_LIMIT
    """How many articles per page."""
    cursor: str | None = Field(default=None)
    """Opaque: only ever a `next_cursor`. It only works with the `sort` and filters of the
    request that returned it."""
    offset: Offset | None = None
    """Jump to a page: skip this many matches, in the order and with the filters of the cursor
    walk. Not with `cursor`; the page's `next_cursor` goes on from it."""

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        """Treat a blank ref as none: the default version.

        Args:
            value: The raw field.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("path_prefix")
    @classmethod
    def _clean_path_prefix(cls, value: str) -> str:
        """Drop `.` and empty segments (`./guide//x`); refuse `..` and backslashes.

        Args:
            value: The prefix as sent.

        Returns:
            The prefix, its segments joined by `/`.

        Raises:
            ValueError: It holds a `..` segment or a backslash.
        """
        segments = [s for s in value.split("/") if s not in {"", "."}]
        if ".." in segments or "\\" in value:
            message = "path_prefix must be a plain `/`-separated directory"
            raise ValueError(message)
        return "/".join(segments)


class ArticleSummary(_Dto):
    """An article as listed in a tree: no content."""

    path: str
    """Path of the article in the repository, e.g. `docs/guide/auth.md`."""
    title: str
    """The article's title; untrusted repository text."""
    tags: list[str]
    """Every tag: from front matter, path rules and by hand."""
    size: int
    """Bytes of the article's text."""

    @classmethod
    def from_model(cls, entry: ManifestEntry) -> Self:
        """Map a manifest entry.

        Args:
            entry: The article's entry.

        Returns:
            The article without its text, with every tag.
        """
        return cls(path=entry.path, title=entry.title, tags=list(entry.all_tags), size=entry.size)


class ArticleList(_Dto):
    """A page of articles of one manifest, sorted by path."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the fields below."""

    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The exact ref that answered (the default version when none was asked)."""
    commit_sha: str
    """The commit the version was imported at."""
    manifest_id: str
    """ID of the manifest that serves the version."""
    articles: list[ArticleSummary]
    """The articles of this page, in the requested order (by path by default)."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""
    total: int
    """How many articles match the filters (`path_prefix`, `tags`, `q`), across every page."""


class ListTagsQuery(_Dto):
    """The tags of a version's articles; no `ref` means the default version."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = None
    """Exact imported ref; null or blank: the default version."""

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        """Treat a blank ref as none: the default version.

        Args:
            value: The raw field.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class TagCount(_Dto):
    """A tag and how many articles of the version carry it."""

    tag: str
    """The tag in its normal form: case-folded, inner spaces as `-`."""
    count: int
    """How many articles of the version carry it."""


class TagList(_Dto):
    """The most used tags of one manifest, for a tag filter."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the fields below."""

    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The exact ref that answered (the default version when none was asked)."""
    commit_sha: str
    """The commit the version was imported at."""
    tags: list[TagCount] = Field(description=TAG_LIST_DESCRIPTION)
    """The tags and their counts; its schema description is ``TAG_LIST_DESCRIPTION``."""
    truncated: bool
    """True when the version has more tags than are listed."""


class GetArticleQuery(_Dto):
    """Read the article at `path` of a version; no `ref` means the default version."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = None
    """Exact imported ref; null or blank: the default version."""
    path: str = Field(min_length=1, max_length=MAX_PATH)
    """The article's path in the repository."""

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        """Treat a blank ref as none: the default version.

        Args:
            value: The raw field.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class ResolveRenamedPathQuery(_Dto):
    """Follow `path` across renames into `ref` (default version without one).

    With `from_ref`: `path` is from that version, and the rename maps of every version between
    the two are followed hop by hop, whichever of them was imported first. Without it, one hop
    by `direction`: the map of `ref` covers the version before it only (a branch: its syncs so
    far).
    """

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = None
    """Exact imported ref; null or blank: the default version."""
    path: str = Field(min_length=1, max_length=MAX_PATH)
    """With `from_ref`: a path of `from_ref`. Otherwise `forward`: a path of the version before
    `ref`; `back`: an article of `ref`."""
    direction: RenameDirection = RenameDirection.FORWARD
    """`forward`: old to new path; `back`: new to old. Ignored with `from_ref`."""
    from_ref: str | None = None
    """Exact imported ref `path` is from; null or blank: one hop by `direction`."""

    @field_validator("ref", "from_ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        """Treat a blank ref as none: the default version, or no `from_ref`.

        Args:
            value: The raw field.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class RenamedPath(_Dto):
    """`old_path` of version `from_ref` is `new_path` in `ref`, as git saw it.

    Asked with `from`, the move may span several versions, in either order of import:
    `old_path` is the path asked about and `new_path` its path in `ref`.
    """

    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The version whose import saw the move; with `from`, the version asked about."""
    from_ref: str
    """The version `old_path` is from; for a branch, the branch itself."""
    old_path: str
    """The path in `from_ref`."""
    new_path: str
    """The path in `ref`."""
    similarity: int = Field(description=SIMILARITY_DESCRIPTION)
    """How much of the content the move kept; its schema description is ``SIMILARITY_DESCRIPTION``.
    Across several versions, the lowest of their moves.
    """

    @classmethod
    def from_model(cls, library: str, ref: str, rename: ManifestRename) -> Self:
        """Map a domain value object.

        Args:
            library: The library ID.
            ref: The version whose renames hold the move.
            rename: The move.

        Returns:
            The move at the boundary.
        """
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
    """The move; null when git saw none for that path."""


class ListRenamesQuery(_Dto):
    """List the renames stored with the active manifest of `ref` (default version without one)."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = None
    """Exact imported ref; null or blank: the default version."""

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        """Treat a blank ref as none: the default version.

        Args:
            value: The raw field.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class RenameList(_Dto):
    """Every rename of a version, by old path."""

    renames: list[RenamedPath]
    """The renames, sorted by old path."""


class ManualTagInfo(_Dto):
    """A tag set by hand, and the article path it was set on."""

    tag: str
    """The tag in its normal form: case-folded, inner spaces as `-`."""
    path: str
    """Where the tag was set: this article's path, or an older one it was renamed from. Change or
    remove the tag on this path.
    """


class TagOriginsInfo(_Dto):
    """One tag of an article, and every place it comes from."""

    tag: str
    """The tag, as in `tags`."""
    origins: list[TagOrigin]
    """Where it comes from, at least one: `front_matter`, `path_rule`, `imported` (front matter
    or a path rule, not recorded which: a version imported before origins were kept), `manual`
    (set by hand; `manual_tags` says on which path).
    """


class ArticleInfo(_Dto):
    """Where an article comes from and its metadata: everything but the text."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the fields below."""
    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The exact ref that answered (the default version when none was asked)."""
    commit_sha: str
    """The commit the version was imported at."""
    manifest_id: str
    """ID of the manifest that serves the version."""
    path: str
    """Path of the article in the repository, e.g. `docs/guide/auth.md`."""
    title: str
    """The article's title; untrusted repository text."""
    tags: list[str]
    """Every tag: from front matter, path rules and by hand."""
    tag_origins: list[TagOriginsInfo]
    """Every tag of `tags`, in the same order, with where it comes from. A tag can have several
    origins, e.g. a path rule and a hand edit.
    """
    manual_tags: list[ManualTagInfo]
    """The tags among `tags` set by hand, each with the path it was set on: this one or one it was
    renamed from. A tag set on both is listed for each.
    """
    size: int
    """Bytes of the article's text."""
    front_matter: dict[str, Any]
    """The article's front matter, parsed; untrusted repository data."""
    source_url: str | None
    """Link to the file at the commit; null when the host is unknown."""

    @classmethod
    def from_stored(
        cls, library: str, ref: str, stored: StoredArticle, source_url: str | None
    ) -> Self:
        """Map a stored article of the given version.

        Args:
            library: The library ID.
            ref: The version's ref.
            stored: The article with its manifest entry.
            source_url: Link to the file at the commit; ``None`` when the host is unknown.

        Returns:
            The article's metadata, without its text.
        """
        entry = stored.entry
        return cls(
            library=library,
            ref=ref,
            commit_sha=stored.commit_sha,
            manifest_id=stored.manifest_id,
            path=entry.path,
            title=entry.title,
            tags=list(entry.all_tags),
            tag_origins=[
                TagOriginsInfo(tag=tag, origins=list(origins)) for tag, origins in entry.tag_origins
            ],
            manual_tags=[ManualTagInfo(tag=t.tag, path=t.path) for t in entry.manual_tags],
            size=entry.size,
            front_matter=entry.front_matter,
            source_url=source_url,
        )


class Article(ArticleInfo):
    """One article with its Markdown, verbatim as imported."""

    content: str
    """The article's Markdown, verbatim as imported."""

    @classmethod
    def with_content(cls, info: ArticleInfo, content: str) -> Self:
        """Add the text to an article's metadata.

        Args:
            info: The metadata.
            content: The article's Markdown.

        Returns:
            The whole article.
        """
        return cls(**dict(info), content=content)


class ManualTagsIn(_Dto):
    """The tags to set by hand on an article path; they replace its earlier manual tags."""

    tags: list[Annotated[str, StringConstraints(max_length=MAX_TAG_INPUT)]] = Field(
        max_length=MAX_TAGS
    )
    """Normalized like every tag (lower-case, trimmed, deduplicated). Empty: none."""


class SetManualTagsCommand(ManualTagsIn):
    """Set the manual tags of `path` for every version of `library`."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    path: str = Field(min_length=1, max_length=MAX_PATH)
    """The article path to tag; it need not be an article of every version."""


class ArticleTags(_Dto):
    """Every tag an article carries now (`ManifestEntry.all_tags`)."""

    path: str
    """The article's path."""
    tags: list[str]
    """Its tags."""


class RetaggedManifest(_Dto):
    """The articles of a manifest that have manual tags, or had some before: their tags now.

    Other domains keep copies of article tags (search filters by them) and refresh these.
    """

    manifest_id: str
    """The manifest."""
    articles: list[ArticleTags]
    """Its articles whose tags changed or may have, sorted by path."""

    @classmethod
    def of(cls, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> Self:
        """Map what the repository reports.

        Args:
            manifest_id: The manifest.
            tags: The tags of each touched article, by path.

        Returns:
            The manifest's touched articles, sorted by path.
        """
        return cls(
            manifest_id=manifest_id,
            articles=[ArticleTags(path=p, tags=list(t)) for p, t in sorted(tags.items())],
        )


class ManualTagsOut(_Dto):
    """The manual tags of a path, as stored: every version's article at that path gets them."""

    library: str
    """Library ID, `/owner/repo`."""
    path: str
    """The article path tagged."""
    tags: list[str]
    """Its manual tags now, normalized and sorted."""
    retagged: list[RetaggedManifest]
    """The pending and active manifests whose articles' tags are touched."""


class ApplyManualTagsCommand(_Dto):
    """Give a (pending) manifest the manual tags its library has now."""

    manifest_id: str = Field(min_length=1)
    """The manifest to tag."""


class ReplaceRenamesCommand(_Dto):
    """Give the active manifest of `ref` a new rename map, then its library's manual tags again.

    For a newer version whose previous version was imported after it: its renames are then
    detected against that one. Renames into a path that is not an article of the manifest are
    left out.
    """

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    """The version whose active manifest gets the renames."""
    renames: list[RenameIn]
    """The new rename map; it replaces the old one."""
    renamed_from: str | None = Field(default=None, min_length=1)
    """The version the map was detected against, also when nothing moved; null: the `from_ref`
    of the renames (none without renames)."""


class RenamesReplaced(_Dto):
    """The manifest whose renames were replaced, and every manifest whose tags that touched."""

    manifest_id: str
    """The manifest whose renames were replaced."""
    retagged: list[RetaggedManifest]
    """The pending and active manifests whose articles carry or carried manual tags."""


class GetAssetQuery(_Dto):
    """Read the image at repository path `path` of a version; no `ref` means the default version."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = None
    """Exact imported ref; null or blank: the default version."""
    path: str = Field(min_length=1, max_length=MAX_PATH)
    """The image's path in the repository."""
    known_blob_shas: list[str] = Field(default=[])
    """Blob SHAs the caller holds; a match answers `unchanged`."""

    @field_validator("ref", mode="before")
    @classmethod
    def _blank_ref_is_none(cls, value: object) -> object:
        """Treat a blank ref as none: the default version.

        Args:
            value: The raw field.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class Asset(_Dto):
    """An image of a version: its bytes and the type sniffed from them when it was imported."""

    blob_sha: str
    """Git blob SHA of the image: its ETag."""
    content_type: str
    """Media type sniffed when it was imported."""
    data: bytes = Field(repr=False)
    """The image's bytes; empty when `unchanged`."""
    unchanged: bool = Field(default=False)
    """The blob is one of `known_blob_shas`; `data` is empty."""


class GetManifestStatesQuery(_Dto):
    """Ask for the state of manifests by ID."""

    manifest_ids: list[str]
    """The manifests asked about."""


class GetActiveManifestQuery(_Dto):
    """Ask which manifest serves a version (the library's default one without a ref)."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = None
    """Exact imported ref; null: the default version."""


class ActiveManifest(_Dto):
    """The manifest serving a version, or ``None`` while it has none."""

    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The version's ref."""
    commit_sha: str
    """The commit of the manifest, else of the version."""
    manifest_id: str | None
    """The active manifest; null while the version has none."""


class DefaultManifest(_Dto):
    """A library's default version and the manifest serving it, with where its source lives."""

    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The default version's ref."""
    commit_sha: str
    """The commit of the manifest."""
    manifest_id: str
    """The manifest serving it."""
    source_url: str
    """The repository's URL."""
    host: HostKind
    """What kind of server hosts the repository."""


class DefaultManifests(_Dto):
    """The default versions that have an active manifest, by library ID."""

    manifests: list[DefaultManifest]
    """One per library, sorted by library ID."""


class GetArticleTitlesQuery(_Dto):
    """Ask for the titles of some articles of one manifest, by path."""

    manifest_id: str = Field(min_length=1)
    """The manifest (any state)."""
    paths: list[str]
    """The article paths."""


class GetInstructionFilesQuery(_Dto):
    """Ask for the instruction files kept with one manifest."""

    manifest_id: str = Field(min_length=1)
    """The manifest (any state)."""


class InstructionFileOut(_Dto):
    """An instruction file kept with a manifest; untrusted repository text."""

    path: str
    """Repository-relative."""
    content: str = Field(repr=False)
    """Its text."""


class InstructionFiles(_Dto):
    """The instruction files kept with a manifest, by path; none for an unknown manifest."""

    files: list[InstructionFileOut]
    """Sorted by path."""


class ArticleTitles(_Dto):
    """Titles by article path; paths the manifest does not have are left out."""

    titles: dict[str, str]
    """The title of each path found."""


class ManifestStates(_Dto):
    """Manifest state by ID; IDs the catalog does not know are left out."""

    states: dict[str, ManifestState]
    """The state of each manifest found."""


class TagRuleIn(_Dto):
    """Articles whose path matches `pattern` get `tag` (already normalized by the importer)."""

    pattern: str = Field(min_length=1, max_length=256)
    """Glob over article paths, e.g. `docs/api/**`."""
    tag: str = Field(min_length=1, max_length=MAX_TAG_LENGTH)
    """The tag a matching article gets."""


class CreateLibraryCommand(_Dto):
    """Add an empty library; its versions arrive with imports."""

    id: str = Field(min_length=1)
    """Library ID, `/owner/repo`."""
    title: str = Field(min_length=1)
    """Display name."""
    source_url: str = Field(min_length=1)
    """Where the repository is cloned from."""
    host: HostKind
    """What kind of server hosts the repository."""
    default_branch: str | None = None
    """The repository's default branch, when known."""
    include_paths: list[str] = Field(default_factory=list)
    """Folders, files or globs to import; empty: every Markdown file."""
    exclude_paths: list[str] = Field(default_factory=list)
    """Folders, files or globs to leave out; they win."""
    tag_rules: list[TagRuleIn] = Field(default_factory=list, max_length=MAX_TAG_RULES)
    """Tags given to articles by path."""
    chunking: ChunkingIn | None = None
    """How articles are cut; null: the defaults."""


_Title = Annotated[str, Field(min_length=1, max_length=MAX_TITLE)]
_Description = Annotated[str, Field(max_length=MAX_DESCRIPTION)]
_Rule = Annotated[str, Field(min_length=1, max_length=MAX_LIBRARY_RULE_CHARS)]


def _clean(text: str) -> str:
    r"""Drop control and format characters (zero-width, bidi, tags, escapes); keep \n and \t.

    Args:
        text: Text a user typed.

    Returns:
        The text without those characters.
    """
    return "".join(
        c for c in text if c in "\n\t" or unicodedata.category(c) not in {"Cc", "Cf", "Co", "Cs"}
    )


class LibraryPatch(_Dto):
    """The fields a user may change; at least one must be given."""

    title: Annotated[str, StringConstraints(min_length=1, max_length=MAX_TITLE)] | None = Field(
        default=None
    )
    """A single line of text. Null or absent: unchanged."""
    description: Annotated[str, StringConstraints(max_length=MAX_DESCRIPTION)] | None = Field(
        default=None
    )
    """Empty is allowed: no description. Null or absent: unchanged."""

    @field_validator("title")
    @classmethod
    def _single_line(cls, title: str | None) -> str | None:
        """Refuse a title on several lines; drop invisible characters and collapse spaces.

        Args:
            title: The title as sent; ``None`` when absent.

        Returns:
            The cleaned title, or ``None``.

        Raises:
            ValueError: The title has a line break, or no visible text.
        """
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
        """Drop invisible characters and surrounding whitespace from the description.

        Args:
            description: The description as sent; ``None`` when absent.

        Returns:
            The cleaned description, or ``None``.
        """
        return None if description is None else _clean(description).strip()

    @model_validator(mode="after")
    def _says_something(self) -> Self:
        """Refuse a patch that changes nothing.

        Returns:
            The patch unchanged.

        Raises:
            ValueError: Neither a title nor a description is given.
        """
        if self.title is None and self.description is None:
            message = "give a title or a description"
            raise ValueError(message)
        return self


class UpdateLibraryCommand(LibraryPatch):
    """Set the title and/or description of a library by hand; they are then kept for good."""

    id: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""


class DefaultVersionPin(_Dto):
    """The version to pin as a library's default."""

    ref: str = Field(min_length=1, max_length=MAX_NAME)
    """An imported ref, exactly as listed (case-sensitive), or a unique short SHA."""


class PinDefaultVersionCommand(_Dto):
    """Pin the version `ref` names as the library's default; no `ref` unpins it."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""
    ref: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    """An imported ref, or a unique short SHA; null unpins."""


class ApplyReadmeCommand(_Dto):
    """What an imported version says about its library; used only if it is the default version.

    Title and description come from its ``context7.json``, else its root README. A missing value
    means: the repository name as title, no description. ``rules`` replace the library's rules
    (empty: the version has none).
    """

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    """The version imported; nothing changes unless it is the default."""
    title: _Title | None = None
    """The title it gives; null: the repository name."""
    description: _Description | None = None
    """The description it gives; null: none."""
    rules: list[_Rule] = Field(default_factory=list, max_length=MAX_LIBRARY_RULES)
    """Its `context7.json` rules; they replace the library's."""


class DiscardLibraryCommand(_Dto):
    """Undo ``CreateLibrary`` for a library that has no versions."""

    id: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""


class RemoveVersionCommand(_Dto):
    """Remove one version of a library, with every manifest it ever had."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    """The exact ref to remove."""


class RemoveLibraryCommand(_Dto):
    """Remove a library, all its versions and every manifest."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""


class Removal(_Dto):
    """What a removal took out of the catalog.

    `manifest_ids` lets other domains drop what they hold under those IDs. `default_ref` is the
    version `/owner/repo` means after the removal (`None`: the library has no version left; always
    `None` after `RemoveLibrary`).
    """

    library: str
    """Library ID, `/owner/repo`."""
    ref: str | None
    """The version removed; null when the whole library was."""
    manifest_ids: list[str]
    """Every manifest removed, in any state."""
    default_ref: str | None
    """The default version now; null when none is left."""


class ChunkingIn(_Dto):
    """How articles are cut (validated by the importer, which knows the chunkers)."""

    split_level: int = Field(default=DEFAULT_SPLIT_LEVEL, ge=1, le=_HEADING_LEVELS)
    """The deepest heading that starts a chunk."""
    min_chars: int = Field(default=0, ge=0)
    """A chunk shorter than this is merged with the next one."""
    max_chars: int | None = Field(default=DEFAULT_MAX_CHARS, ge=1)
    """A chunk longer than this is cut again; null: no bound."""
    chunker: str = Field(default="markdown", min_length=1, max_length=64)
    """Which chunker cuts."""


class SetLibrarySettingsCommand(_Dto):
    """Replace a library's paths and tag rules, and the chunking unless it is left out (None).

    Validated and normalized by the importer.
    """

    id: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    include_paths: list[str] = Field(default_factory=list)
    """Folders, files or globs to import; empty: every Markdown file."""
    exclude_paths: list[str] = Field(default_factory=list)
    """Folders, files or globs to leave out; they win."""
    tag_rules: list[TagRuleIn] = Field(default_factory=list, max_length=MAX_TAG_RULES)
    """Tags given to articles by path."""
    chunking: ChunkingIn | None = None
    """How articles are cut; null keeps the current chunking."""


class GetVersionTagsQuery(_Dto):
    """Ask for what the imported tags of a version's articles are derived from."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    """The exact ref."""


class ArticleTagSource(_Dto):
    """An article's path, front matter and imported tags (manual ones are kept apart)."""

    path: str
    """The article's path."""
    front_matter: dict[str, Any]
    """Its parsed front matter."""
    tags: list[str]
    """Its imported tags."""


class VersionTags(_Dto):
    """The active manifest of a version and its articles' tag sources (none while it has none)."""

    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The version's ref."""
    manifest_id: str | None
    """The active manifest; null while the version has none."""
    articles: list[ArticleTagSource]
    """Every article of the manifest; empty without one."""


class ImportedArticleTags(_Dto):
    """An article's new imported tags, and where they come from."""

    path: str
    """The article's path."""
    tags: list[str]
    """Its imported tags: path rules and front matter (manual tags are kept apart)."""
    tag_sources: TagSourcesIn | None = None
    """Which of `tags` come from the front matter and which from path rules; null: not known."""


class SetImportedTagsCommand(_Dto):
    """Replace the imported tags of some articles of a manifest."""

    manifest_id: str = Field(min_length=1)
    """The manifest."""
    articles: list[ImportedArticleTags]
    """The articles to retag; the others keep their tags."""


class StoredFileIn(_Dto):
    """A file of a commit, named by its path and git blob SHA."""

    path: str = Field(min_length=1)
    """The file's path in the repository."""
    blob_sha: str = Field(min_length=1)
    """Its git blob SHA."""


class FindStoredArticlesQuery(_Dto):
    """Ask what the catalog stored for these files, so an import need not parse them again."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str | None = Field(default=None)
    """The version being imported: its active manifest is read first."""
    content_version: int
    """The importer's parser version: part of the key."""
    files: list[StoredFileIn] = Field(max_length=MAX_STORED_ARTICLE_FILES)
    """The files of the commit being imported."""


class StoredArticleOut(_Dto):
    """What an import stored for a file: its title, front matter and text (tags are derived)."""

    path: str
    """The file's path, as asked."""
    blob_sha: str
    """Its git blob SHA, as asked."""
    title: str
    """The stored title."""
    front_matter: dict[str, Any]
    """The stored front matter."""
    content: str
    """The stored text."""


class StoredArticles(_Dto):
    """The asked files the catalog holds; the others are left out."""

    articles: list[StoredArticleOut]
    """One per file found."""


class CopyManifestCommand(_Dto):
    """Copy a version's active manifest into a new pending one (to re-chunk what it serves)."""

    library: str = Field(min_length=1)
    """Library ID, `/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    """The version to copy."""
    content_version: int
    """The parser version the articles must be stored by, else nothing is copied."""


class CopiedArticle(_Dto):
    """An article of the copy with its stored text; `tags` are the imported ones."""

    path: str
    """The article's path."""
    blob_sha: str
    """Its git blob SHA."""
    title: str
    """Its title."""
    front_matter: dict[str, Any]
    """Its front matter."""
    tags: list[str]
    """Its imported tags."""
    content: str
    """Its stored text."""


class CopiedManifest(_Dto):
    """The pending copy: activate it with `ActivateManifest`, or discard it."""

    manifest_id: str
    """The pending copy."""
    library: str
    """Library ID, `/owner/repo`."""
    ref: str
    """The version's ref."""
    kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    commit_sha: str
    """The commit the articles are from."""
    articles: list[CopiedArticle]
    """Every article of the copy."""
