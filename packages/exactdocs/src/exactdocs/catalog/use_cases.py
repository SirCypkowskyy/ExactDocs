"""Catalog use cases. Each one satisfies a driving port structurally, without inheriting it."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, timedelta
from uuid import uuid4

from exactdocs.catalog.constants import (
    ARTICLE_SORT_FIELDS,
    LIBRARY_SORT_FIELDS,
    MAX_RENAME_HOPS,
    MAX_RENAMES,
    MAX_SIMILARITY,
    MAX_SUGGESTION_SCAN,
    MAX_TAG_FACETS,
    TAG_SOURCE_PAGE,
    VERSION_SORT_FIELDS,
)
from exactdocs.catalog.dtos import (
    ActivatedManifest,
    ActivateManifestCommand,
    ActiveManifest,
    ApplyLogoCommand,
    ApplyManualTagsCommand,
    ApplyReadmeCommand,
    Article,
    ArticleInfo,
    ArticleList,
    ArticleSummary,
    ArticleTagSource,
    ArticleTitles,
    Asset,
    CollectGarbageCommand,
    CollectionResult,
    CopiedArticle,
    CopiedManifest,
    CopyManifestCommand,
    CreateLibraryCommand,
    DefaultManifest,
    DefaultManifests,
    DiscardedManifests,
    DiscardLibraryCommand,
    DiscardPendingManifestsCommand,
    FindStoredArticlesQuery,
    GetActiveManifestQuery,
    GetArticleQuery,
    GetArticleTitlesQuery,
    GetAssetQuery,
    GetInstructionFilesQuery,
    GetLibraryQuery,
    GetLogoQuery,
    GetManifestStatesQuery,
    GetVersionTagsQuery,
    InstructionFileOut,
    InstructionFiles,
    LibraryDetail,
    LibraryList,
    ListArticlesQuery,
    ListedVersion,
    ListLibrariesQuery,
    ListRenamesQuery,
    ListTagsQuery,
    ListVersionsQuery,
    Logo,
    ManifestStates,
    ManualTagsOut,
    PinDefaultVersionCommand,
    Removal,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RenamedPath,
    RenameIn,
    RenameList,
    RenamesReplaced,
    ReplaceRenamesCommand,
    ResolvedVersion,
    ResolveRenamedPathQuery,
    ResolveVersionQuery,
    RetaggedManifest,
    SetImportedTagsCommand,
    SetLibrarySettingsCommand,
    SetManualTagsCommand,
    StoredArticleOut,
    StoredArticles,
    StoredManifest,
    StoreManifestCommand,
    TagCount,
    TagList,
    UpdateLibraryCommand,
    VersionList,
    VersionTags,
)
from exactdocs.catalog.errors import (
    ArticleNotFoundError,
    AssetNotFoundError,
    ConflictingContentError,
    ConflictingImageError,
    LibraryAccessDeniedError,
    LibraryCreationDeniedError,
    LibraryNotEmptyError,
    LibraryNotFoundError,
    LogoNotFoundError,
    ManifestNotFoundError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    Access,
    ChunkingConfig,
    ContentKey,
    HostKind,
    ImportedTags,
    Library,
    LibraryId,
    LibraryLogo,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestImage,
    ManifestInstruction,
    ManifestRename,
    ManifestState,
    ManualTags,
    ParsedId,
    RenameDirection,
    StoredImage,
    TagRule,
    TagSelection,
    Version,
    VersionRef,
    close_paths,
)
from exactdocs.catalog.ports.driven import (
    AccessPolicy,
    ArticleCounts,
    ArticleTitleFinder,
    EntrySearch,
    ImportedTagWriter,
    InstructionFileReader,
    LibraryLogos,
    LibraryRepository,
    ManifestCopier,
    ManifestRepository,
    StoredArticleFinder,
)
from exactdocs_kernel import (
    Clock,
    decode_sort_cursor,
    encode_sort_cursor,
    page_offset,
    parse_sort,
    respelled_note,
    section_link,
    sorted_page,
)


async def _find_version(
    repository: LibraryRepository, library_id: LibraryId, ref: VersionRef | None
) -> tuple[Library, Version]:
    """Find the version a ref names (the default one without a ref); never any other version.

    The exact lookup of ``_read_version``: a stored ref (the active manifest, renames, removal)
    is never read as another spelling. Its errors are ``_read_version``'s.

    Args:
        repository: Where the library is read.
        library_id: The library.
        ref: The ref, or a short commit SHA; None for the default version.

    Returns:
        The library and the version.
    """
    library, version, _ = await _read_version(repository, library_id, ref, respell=False)
    return library, version


async def _read_version(
    repository: LibraryRepository,
    library_id: LibraryId,
    ref: VersionRef | None,
    *,
    respell: bool = True,
) -> tuple[Library, Version, list[str]]:
    """Find the version a reader's ref names, forgiving only a leading ``v`` (#605).

    Exactly ``ref`` (or the commit a short SHA names; the default version without a ref), else,
    when ``respell``, the one version ``ref`` names but for a leading ``v`` or ``V``, with a note
    saying so. Only reader-facing use cases respell; lookups of a stored ref stay exact.

    Args:
        repository: Where the library is read.
        library_id: The library.
        ref: The ref, or a short commit SHA; None for the default version.
        respell: Whether a ref may name a version spelled with or without a leading ``v``.

    Returns:
        The library, the version and the notes on how the ref was read (none when as given).

    Raises:
        LibraryNotFoundError: The library is not in the catalog.
        VersionNotFoundError: The ref names no version, or the library has none; it names the
            library's versions, newest first, and its default.
    """
    library = await repository.get(library_id)
    if library is None:
        raise LibraryNotFoundError(str(library_id))
    if ref is None:
        version = library.default_version()
    else:
        version = library.find_version(ref)
        if version is None and respell and (other := library.respelled_version(ref)) is not None:
            return library, other, [respelled_note(ref.value, other.ref.value)]
    if version is None:
        default = library.default_version()
        raise VersionNotFoundError(
            str(library.id),
            None if ref is None else str(ref),
            versions=[str(v.ref) for v in library.newest_first()],
            default=None if default is None else str(default.ref),
        )
    return library, version, []


async def _require(access: AccessPolicy, library: str, needed: Access) -> None:
    """Refuse unless the caller holds the role ``needed`` on the library.

    Args:
        access: Library roles.
        library: The library ID, any case.
        needed: The role the action needs.

    Raises:
        LibraryNotFoundError: The library is hidden from this caller.
        LibraryAccessDeniedError: The caller's role on the library is lower.
    """
    if not await access.allows(library, Access.READ):
        raise LibraryNotFoundError(library)
    if needed is not Access.READ and not await access.allows(library, needed):
        raise LibraryAccessDeniedError(library, needed.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListLibrariesUseCase:
    """Implements ``ports.driving.ListLibraries``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    articles: ArticleCounts
    """Counts the articles of the page's default versions, in one query."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(
        self,
        query: ListLibrariesQuery,
        *,
        only: frozenset[str] | None = None,
        without: frozenset[str] = frozenset(),
    ) -> LibraryList:
        """List a page of the libraries the caller may read, filtered and sorted.

        Permissions apply first: a hidden library is in no page and in no count.

        Args:
            query: The filters, the sort, the page size and the cursor of the previous page.
            only: Case-folded library IDs; when given, no other library is listed.
            without: Case-folded library IDs that are not listed. The caller resolves what
                the catalog does not know (the AI switch, say) into these two sets.

        Returns:
            The page of libraries with the next cursor and the count of every match.
        """
        sort = parse_sort(query.sort, allowed=LIBRARY_SORT_FIELDS, default="id")
        every = await self.repository.list_all()
        readable = await self.access.readable([lib.id.value for lib in every])
        libraries = [lib for lib in every if lib.id.value in readable]
        libraries = [
            lib
            for lib in libraries
            if lib.id.value.lower() not in without
            and (only is None or lib.id.value.lower() in only)
        ]
        libraries = [lib for lib in libraries if _library_matches(lib, query)]
        page = sorted_page(
            libraries,
            sort=sort,
            key_field="id",
            values={
                "id": lambda lib: lib.id.value,
                "title": lambda lib: lib.title.lower(),
                "last_imported_at": _last_imported,
                "version_count": lambda lib: len(lib.versions),
            },
            key=lambda lib: lib.id.value,
            limit=query.limit,
            cursor=query.cursor,
            offset=query.offset,
        )
        defaults = [(lib.id, d.ref) for lib in page.items if (d := lib.default_version())]
        counts = await self.articles.count_articles(defaults) if defaults else {}
        return LibraryList.from_page(
            page, article_counts={lib.value: n for (lib, _), n in counts.items()}
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListVersionsUseCase:
    """Implements ``ports.driving.ListVersions``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    articles: ArticleCounts
    """Counts the articles of the page's versions, in one query."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ListVersionsQuery) -> VersionList:
        """List a page of a library's versions, filtered and sorted.

        Args:
            query: The library, the filters, the sort and the page.

        Returns:
            The page, the next cursor and the count of every match. Each version carries its
            article count; its chunk counts are the search index's, which the caller adds.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        await _require(self.access, query.id, Access.READ)
        sort = parse_sort(query.sort, allowed=VERSION_SORT_FIELDS, default="ref")
        library = await self.repository.get(LibraryId(query.id))
        if library is None:
            raise LibraryNotFoundError(query.id)
        default = library.default_version()
        needle = query.q.lower() if query.q else None
        kinds, origins = set(query.kind or ()), set(query.origin or ())
        found = [
            v
            for v in library.versions
            if (needle is None or needle in str(v.ref).lower() or needle in v.commit_sha.lower())
            and (not kinds or v.kind in kinds)
            and (not origins or v.origin in origins)
            and (query.imported_after is None or v.imported_at >= query.imported_after)
            and (query.imported_before is None or v.imported_at < query.imported_before)
        ]
        page = sorted_page(
            found,
            sort=sort,
            key_field="ref",
            values={
                "ref": lambda v: str(v.ref),
                "kind": lambda v: v.kind.value,
                "imported_at": lambda v: v.imported_at.astimezone(UTC).isoformat(),
                "origin": lambda v: v.origin.value,
            },
            key=lambda v: str(v.ref),
            limit=query.limit,
            cursor=query.cursor,
            offset=query.offset,
        )
        counts = (
            await self.articles.count_articles([(library.id, v.ref) for v in page.items])
            if page.items
            else {}
        )
        return VersionList(
            library=str(library.id),
            versions=[
                ListedVersion.listed(
                    v, is_default=v == default, articles=counts.get((library.id, v.ref), 0)
                )
                for v in page.items
            ],
            next_cursor=page.next_cursor,
            total=len(found),
        )


def _last_imported(library: Library) -> str:
    """Return when a library was last imported as sortable text.

    Args:
        library: The library.

    Returns:
        An ISO 8601 UTC timestamp; empty while no version is imported (it sorts first).
    """
    latest = max((v.imported_at for v in library.versions), default=None)
    return "" if latest is None else latest.astimezone(UTC).isoformat()


def _library_matches(library: Library, query: ListLibrariesQuery) -> bool:
    """Tell whether a library passes the list's text, version and date filters.

    Args:
        library: The library.
        query: The filters.

    Returns:
        Whether it matches every filter that is set.
    """
    if query.q:
        needle = query.q.lower()
        if not any(
            needle in text.lower()
            for text in (library.id.value, library.title, library.description)
        ):
            return False
    if query.has_versions is not None and bool(library.versions) is not query.has_versions:
        return False
    latest = max((v.imported_at for v in library.versions), default=None)
    if query.updated_after is not None and (latest is None or latest < query.updated_after):
        return False
    return not (
        query.updated_before is not None and (latest is None or latest >= query.updated_before)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateLibraryUseCase:
    """Implements ``ports.driving.CreateLibrary``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: CreateLibraryCommand) -> LibraryDetail:
        """Store a new library without versions; the repository refuses a taken ID.

        Args:
            command: The library's ID, source and settings.

        Returns:
            The new library, without versions.

        Raises:
            LibraryCreationDeniedError: The caller lacks instance creation permission.
        """
        if not await self.access.can_create(command.id):
            raise LibraryCreationDeniedError
        library = Library(
            id=LibraryId(command.id),
            title=command.title,
            source_url=command.source_url,
            host=HostKind(command.host),
            default_branch=VersionRef(command.default_branch) if command.default_branch else None,
            settings=LibrarySettings(
                include_paths=tuple(command.include_paths),
                exclude_paths=tuple(command.exclude_paths),
                tag_rules=tuple(TagRule(pattern=r.pattern, tag=r.tag) for r in command.tag_rules),
                chunking=ChunkingConfig()
                if (wanted := command.chunking) is None
                else ChunkingConfig(
                    split_level=wanted.split_level,
                    min_chars=wanted.min_chars,
                    max_chars=wanted.max_chars,
                    chunker=wanted.chunker,
                ),
            ),
        )
        await self.repository.add(library)
        await self.access.claim(library.id.value)
        return LibraryDetail.from_model(library)


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateLibraryUseCase:
    """Implements ``ports.driving.UpdateLibrary``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: UpdateLibraryCommand) -> LibraryDetail:
        """Change the given fields and remember that a user chose them.

        Args:
            command: The library and the fields to change.

        Returns:
            The library as it is now.

        Raises:
            LibraryNotFoundError: The library is not in the catalog, or was removed meanwhile.
        """
        await _require(self.access, command.id, Access.ADMINISTER)
        library = await self.repository.get(LibraryId(command.id))
        if library is None:
            raise LibraryNotFoundError(command.id)
        await self.repository.set_text(
            library.id, title=command.title, description=command.description
        )
        updated = await self.repository.get(library.id)
        if updated is None:  # deleted in between
            raise LibraryNotFoundError(command.id)
        return LibraryDetail.from_model(updated)


@dataclass(frozen=True, slots=True, kw_only=True)
class SetLibrarySettingsUseCase:
    """Implements ``ports.driving.SetLibrarySettings``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: SetLibrarySettingsCommand) -> LibraryDetail:
        """Replace paths and tag rules; the chunking too unless it is left out.

        Args:
            command: The library and its new settings.

        Returns:
            The library as it is now.

        Raises:
            LibraryNotFoundError: The library is not in the catalog, or was removed meanwhile.
        """
        await _require(self.access, command.id, Access.ADMINISTER)
        library = await self.repository.get(LibraryId(command.id))
        if library is None:
            raise LibraryNotFoundError(command.id)
        wanted = command.chunking
        settings = replace(
            library.settings,
            include_paths=tuple(command.include_paths),
            exclude_paths=tuple(command.exclude_paths),
            tag_rules=tuple(TagRule(pattern=r.pattern, tag=r.tag) for r in command.tag_rules),
            chunking=library.settings.chunking
            if wanted is None
            else ChunkingConfig(
                split_level=wanted.split_level,
                min_chars=wanted.min_chars,
                max_chars=wanted.max_chars,
                chunker=wanted.chunker,
            ),
        )
        await self.repository.set_settings(library.id, settings)
        updated = await self.repository.get(library.id)
        if updated is None:  # deleted in between
            raise LibraryNotFoundError(command.id)
        return LibraryDetail.from_model(updated)


@dataclass(frozen=True, slots=True, kw_only=True)
class PinDefaultVersionUseCase:
    """Implements ``ports.driving.PinDefaultVersion``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: PinDefaultVersionCommand) -> LibraryDetail:
        """Pin the version the ref names (stored by its exact ref), or unpin without a ref.

        Args:
            command: The library and the ref to pin; no ref unpins.

        Returns:
            The library as it is now.

        Raises:
            LibraryNotFoundError: The library is not in the catalog, or was removed meanwhile.
            VersionNotFoundError: The ref names no imported version, or it was removed meanwhile.
        """
        await _require(self.access, command.library, Access.ADMINISTER)
        library_id = LibraryId(command.library)
        library = await self.repository.get(library_id)
        if library is None:
            raise LibraryNotFoundError(command.library)
        ref = None
        if command.ref is not None:
            version = library.find_version(VersionRef(command.ref))
            if version is None:
                raise VersionNotFoundError(str(library.id), command.ref)
            ref = version.ref
        if not await self.repository.pin_default(library.id, ref):  # removed in between
            if ref is None or await self.repository.get(library.id) is None:
                raise LibraryNotFoundError(command.library)
            raise VersionNotFoundError(str(library.id), command.ref)
        updated = await self.repository.get(library.id)
        if updated is None:  # deleted in between
            raise LibraryNotFoundError(command.library)
        return LibraryDetail.from_model(updated)


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyReadmeUseCase:
    """Implements ``ports.driving.ApplyReadme``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""

    async def __call__(self, command: ApplyReadmeCommand) -> None:
        """Follow the default version's text for every field a user has not edited, and its rules.

        The text of any other version is ignored. No title means the repository name, no
        description means none, so a field never keeps text a version dropped; the same goes
        for the rules (there is no user edit of them).

        Only the two text columns and the rules are written, in one statement that keeps edited
        fields, so a concurrent user edit survives. The caller does not retry: if this fails the
        library keeps its old text and rules until the default version is imported again.

        Args:
            command: The version imported and what it says about the library.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        library = await self.repository.get(LibraryId(command.library))
        if library is None:
            raise LibraryNotFoundError(command.library)
        default = library.default_version()
        if default is None or default.ref != VersionRef(command.ref):
            return
        await self.repository.follow_readme(
            library.id,
            title=command.title or library.id.value.rsplit("/", 1)[-1],
            description=command.description or "",
            rules=tuple(command.rules),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyLogoUseCase:
    """Implements ``ports.driving.ApplyLogo``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    logos: LibraryLogos
    """Keeps each library's logo."""

    async def __call__(self, command: ApplyLogoCommand) -> None:
        """Follow the default version's logo: keep it, or remove the library's when it has none.

        The logo of any other version is ignored, as its README is (``ApplyReadme``), so a
        library shows the logo of the version its ID resolves to, and the newest import of an old
        tag never replaces it. The same bytes are not written again (a branch synced often).
        The caller does not retry: if this fails the library keeps its logo until the default
        version is imported again.

        Args:
            command: The version imported and its logo, if any.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        library = await self.repository.get(LibraryId(command.library))
        if library is None:
            raise LibraryNotFoundError(command.library)
        default = library.default_version()
        if default is None or default.ref != VersionRef(command.ref):
            return
        if command.logo is None:
            if library.logo is not None:
                await self.logos.remove(library.id)
            return
        logo = LibraryLogo(
            content_type=command.logo.content_type,
            data=command.logo.data,
            path=command.logo.path,
            ref=default.ref,
        )
        if logo.digest != library.logo:
            await self.logos.put(library.id, logo)


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscardLibraryUseCase:
    """Implements ``ports.driving.DiscardLibrary``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: DiscardLibraryCommand) -> None:
        """Remove the library if it exists and has no versions.

        Args:
            command: The library.

        Raises:
            LibraryNotEmptyError: The library has imported versions.
        """
        library = await self.repository.get(LibraryId(command.id))
        if library is None:
            return
        if library.versions:
            raise LibraryNotEmptyError(str(library.id))
        await self.repository.delete(library.id)
        await self.access.forget(library.id.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetLibraryUseCase:
    """Implements ``ports.driving.GetLibrary``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: GetLibraryQuery) -> LibraryDetail:
        """Fetch one library by ID.

        Args:
            query: The library ID.

        Returns:
            The library with every version and its settings.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        await _require(self.access, query.id, Access.READ)
        library = await self.repository.get(LibraryId(query.id))
        if library is None:
            raise LibraryNotFoundError(query.id)
        return LibraryDetail.from_model(library)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveVersionUseCase:
    """Implements ``ports.driving.ResolveVersion``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ResolveVersionQuery) -> ResolvedVersion:
        """Resolve `/owner/repo[/ref]` to exactly one version.

        Args:
            query: `/owner/repo` or `/owner/repo/<ref>`.

        Returns:
            The version it names, with its library.
        """
        await _require(self.access, ParsedId.parse(query.id).library.value, Access.READ)
        target = ParsedId.parse(query.id)
        library, version, notes = await _read_version(self.repository, target.library, target.ref)
        return ResolvedVersion.from_library(library, version, notes=notes)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreManifestUseCase:
    """Implements ``ports.driving.StoreManifest``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    clock: Clock
    """Tells the time that stamps what is stored and when the grace periods end."""

    async def __call__(self, command: StoreManifestCommand) -> StoredManifest:
        """Store the articles as a pending manifest, invisible until it is activated.

        Args:
            command: The version, its articles, images, renames and instruction files.

        Returns:
            The pending manifest, for ``ActivateManifest``.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        library_id = LibraryId(command.library)
        if await self.repository.get(library_id) is None:
            raise LibraryNotFoundError(command.library)
        manifest, contents, images = await asyncio.to_thread(self._build, command, library_id)
        await self.manifests.add(
            manifest, contents, images=images, version_must_exist=command.must_exist
        )
        return StoredManifest.from_model(manifest)

    def _build(
        self, command: StoreManifestCommand, library_id: LibraryId
    ) -> tuple[Manifest, dict[ContentKey, str], dict[str, StoredImage]]:
        """Build the manifest and its texts: CPU-bound for a big version, so run in a thread.

        Args:
            command: What to store.
            library_id: The library, checked to exist.

        Returns:
            The pending manifest, its texts by content key and its images by blob SHA.

        Raises:
            ConflictingContentError: Two articles of one blob and content version differ in text.
            ConflictingImageError: Two images of one blob SHA differ in type or bytes.
        """
        manifest = Manifest(
            id=ManifestId(uuid4().hex),
            library=library_id,
            ref=VersionRef(command.ref),
            kind=command.kind,
            commit_sha=command.commit_sha,
            created_at=self.clock.now(),
            origin=command.origin,
            renames=tuple(
                ManifestRename(
                    from_ref=VersionRef(r.from_ref),
                    old_path=r.old_path,
                    new_path=r.new_path,
                    similarity=r.similarity,
                )
                for r in command.renames
            ),
            renamed_from=_renamed_from(command.renamed_from, command.renames),
            entries=tuple(
                sorted(
                    (
                        ManifestEntry(
                            path=a.path,
                            blob_sha=a.blob_sha,
                            content_version=a.content_version,
                            title=a.title,
                            tags=tuple(a.tags),
                            sources=None if a.tag_sources is None else a.tag_sources.to_model(),
                            front_matter=a.front_matter,
                            size=len(a.content.encode()),
                        )
                        for a in command.articles
                    ),
                    key=lambda entry: entry.path,
                )
            ),
            images=tuple(
                sorted(
                    (
                        ManifestImage(
                            path=i.path,
                            blob_sha=i.blob_sha,
                            content_type=i.content_type,
                            size=len(i.data),
                        )
                        for i in command.images
                    ),
                    key=lambda image: image.path,
                )
            ),
            instructions=tuple(
                ManifestInstruction(path=i.path, content=i.content)
                for i in sorted(command.instructions, key=lambda i: i.path)
            ),
        )
        contents: dict[ContentKey, str] = {}
        for a in command.articles:
            if contents.setdefault((a.blob_sha, a.content_version), a.content) != a.content:
                raise ConflictingContentError(a.blob_sha)
        images: dict[str, StoredImage] = {}
        for i in command.images:
            stored = StoredImage(blob_sha=i.blob_sha, content_type=i.content_type, data=i.data)
            if images.setdefault(i.blob_sha, stored) != stored:
                raise ConflictingImageError(i.blob_sha)
        return manifest, contents, images


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualTagger:
    """Brings a manifest's manual tags in line with the ones users set for its library."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""

    async def apply(
        self, manifest: Manifest, by_path: Mapping[str, tuple[str, ...]]
    ) -> RetaggedManifest:
        """Give the manifest's entries the manual tags that reach them (see ``ManualTags``).

        Args:
            manifest: The manifest to re-tag.
            by_path: The library's manual tags, by the path they were set on.

        Returns:
            The manifest's articles whose tags changed, with every tag they carry now.
        """
        origins = await self._origins(manifest) if by_path else {}
        wanted = ManualTags.reaching(origins, by_path)
        touched = await self.manifests.set_manual_tags(manifest.id, wanted)
        return RetaggedManifest.of(manifest.id, touched)

    async def _origins(self, manifest: Manifest) -> dict[str, set[str]]:
        """Map each path git saw renamed into ``manifest`` to every older path it came from.

        A rename names the version it came from; that version's own rename map is followed in
        turn, so a path is traced back across several versions (each step at most once).

        Args:
            manifest: The manifest whose renamed paths are traced.

        Returns:
            Each renamed path of the manifest with every older path it came from.
        """
        into: dict[ManifestId, dict[str, list[ManifestRename]]] = {}
        previous: dict[VersionRef, Manifest | None] = {}

        async def renamed_into(m: Manifest) -> dict[str, list[ManifestRename]]:
            """Read a manifest's renames once, by new path.

            Args:
                m: The manifest.

            Returns:
                Its renames, by the path they lead to.
            """
            if m.id not in into:
                by_new: dict[str, list[ManifestRename]] = {}
                for r in await self.manifests.list_renames(m.id, limit=MAX_RENAMES):
                    by_new.setdefault(r.new_path, []).append(r)
                into[m.id] = by_new
            return into[m.id]

        found: dict[str, set[str]] = {}
        for new, renames in (await renamed_into(manifest)).items():
            olds: set[str] = set()
            todo = [(manifest, r) for r in renames]
            seen: set[tuple[VersionRef, str]] = set()
            while todo:
                at, rename = todo.pop()
                olds.add(rename.old_path)
                step = (rename.from_ref, rename.old_path)
                # A branch's map is already chained over its syncs: it names the branch itself.
                if rename.from_ref == at.ref or step in seen:
                    continue
                seen.add(step)
                if rename.from_ref not in previous:
                    previous[rename.from_ref] = await self.manifests.get_active(
                        manifest.library, rename.from_ref
                    )
                if (before := previous[rename.from_ref]) is not None:
                    earlier = (await renamed_into(before)).get(rename.old_path, [])
                    todo += [(before, r) for r in earlier]
            found[new] = olds
        return found


@dataclass(frozen=True, slots=True, kw_only=True)
class SetManualTagsUseCase:
    """Implements ``ports.driving.SetManualTags``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    tagger: ManualTagger
    """Re-tags manifests from their library's manual tags."""

    async def __call__(self, command: SetManualTagsCommand) -> ManualTagsOut:
        """Store the path's tags, then re-tag every pending and active manifest of the library.

        Args:
            command: The library, the path and its tags.

        Returns:
            The path's tags and the manifests whose articles were re-tagged.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        library = await self.repository.get(LibraryId(command.library))
        if library is None:
            raise LibraryNotFoundError(command.library)
        tags = ManualTags.of(command.path, command.tags)
        await self.repository.set_manual_tags(library.id, tags)
        by_path = await self.repository.get_manual_tags(library.id)
        retagged = [
            await self.tagger.apply(manifest, by_path)
            for manifest in await self.tagger.manifests.list_live(library.id)
        ]
        return ManualTagsOut(
            library=str(library.id),
            path=tags.path,
            tags=list(tags.tags),
            retagged=[r for r in retagged if r.articles],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetVersionTagsUseCase:
    """Implements ``ports.driving.GetVersionTags``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""

    async def __call__(self, query: GetVersionTagsQuery) -> VersionTags:
        """Read every entry of the version's active manifest, page by page.

        Args:
            query: The library and the exact ref.

        Returns:
            The active manifest and each article's tag sources; none while it has no manifest.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
            VersionNotFoundError: The library has no version of exactly this ref.
        """
        library = await self.repository.get(LibraryId(query.library))
        if library is None:
            raise LibraryNotFoundError(query.library)
        version = next((v for v in library.versions if v.ref == VersionRef(query.ref)), None)
        if version is None:
            raise VersionNotFoundError(str(library.id), query.ref)
        manifest = await self.manifests.get_active(library.id, version.ref)
        articles: list[ArticleTagSource] = []
        after: str | None = None
        while manifest is not None:
            page = await self.manifests.list_entries(
                manifest.id, prefix="", tags=TagSelection(), after=after, limit=TAG_SOURCE_PAGE
            )
            articles += [
                ArticleTagSource(path=e.path, front_matter=e.front_matter, tags=list(e.tags))
                for e in page
            ]
            if len(page) < TAG_SOURCE_PAGE:
                break
            after = page[-1].path
        return VersionTags(
            library=str(library.id),
            ref=str(version.ref),
            manifest_id=None if manifest is None else manifest.id,
            articles=articles,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FindStoredArticlesUseCase:
    """Implements ``ports.driving.FindStoredArticles``."""

    finder: StoredArticleFinder
    """Finds what earlier imports stored for a file."""

    async def __call__(self, query: FindStoredArticlesQuery) -> StoredArticles:
        """Look the files up in every manifest of the library.

        Args:
            query: The library, the version imported, the parser version and the files.

        Returns:
            What is stored for the files found.
        """
        files = {(f.path, f.blob_sha) for f in query.files}
        found = await self.finder.find_articles(
            LibraryId(query.library),
            None if query.ref is None else VersionRef(query.ref),
            query.content_version,
            files,
        )
        return StoredArticles(
            articles=[
                StoredArticleOut(
                    path=a.entry.path,
                    blob_sha=a.entry.blob_sha,
                    title=a.entry.title,
                    front_matter=a.entry.front_matter,
                    content=a.content,
                )
                for a in found
            ]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SetImportedTagsUseCase:
    """Implements ``ports.driving.SetImportedTags``."""

    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    writer: ImportedTagWriter
    """Writes the imported tags of a manifest's articles."""

    async def __call__(self, command: SetImportedTagsCommand) -> RetaggedManifest:
        """Write the new imported tags; report every given article with every tag it carries.

        Args:
            command: The manifest and the new imported tags of some of its articles.

        Returns:
            Those articles with every tag they now carry.

        Raises:
            ManifestNotFoundError: No manifest has this ID.
        """
        manifest_id = ManifestId(command.manifest_id)
        if await self.manifests.get(manifest_id) is None:
            raise ManifestNotFoundError(command.manifest_id)
        tags = {
            a.path: ImportedTags(
                tags=tuple(dict.fromkeys(a.tags)),
                sources=None if a.tag_sources is None else a.tag_sources.to_model(),
            )
            for a in command.articles
        }
        touched = await self.writer.set_imported_tags(manifest_id, tags)
        return RetaggedManifest.of(command.manifest_id, touched)


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyManualTagsUseCase:
    """Implements ``ports.driving.ApplyManualTags``."""

    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    tagger: ManualTagger
    """Re-tags manifests from their library's manual tags."""

    async def __call__(self, command: ApplyManualTagsCommand) -> RetaggedManifest:
        """Re-tag the manifest from its library's manual tags as they are now.

        Args:
            command: The manifest.

        Returns:
            Its articles whose tags changed.

        Raises:
            ManifestNotFoundError: No manifest has this ID.
        """
        manifest = await self.manifests.get(ManifestId(command.manifest_id))
        if manifest is None:
            raise ManifestNotFoundError(command.manifest_id)
        by_path = await self.tagger.repository.get_manual_tags(manifest.library)
        return await self.tagger.apply(manifest, by_path)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaceRenamesUseCase:
    """Implements ``ports.driving.ReplaceRenames``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    tagger: ManualTagger
    """Re-tags manifests from their library's manual tags."""

    async def __call__(self, command: ReplaceRenamesCommand) -> RenamesReplaced:
        """Store the new map with the active manifest, then let manual tags follow it.

        Tags reach an article through the maps of every version before it, so each pending and
        active manifest of the library is re-tagged, not only this one (``v1.5.0`` gets a tag
        through ``v1.4.0``'s new map too).

        Args:
            command: The version and its new rename map.

        Returns:
            The manifest and every manifest re-tagged.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
            VersionNotFoundError: The version has no active manifest.
        """
        library_id = LibraryId(command.library)
        if await self.repository.get(library_id) is None:
            raise LibraryNotFoundError(command.library)
        manifest = await self.manifests.get_active(library_id, VersionRef(command.ref))
        if manifest is None:
            raise VersionNotFoundError(str(library_id), command.ref)
        # Checked as the manifest would be stored with it, before anything is written: a tag's
        # own renames (SelfRenameError), a rename of another version than the link
        # (RenameLinkMismatchError).
        checked = replace(
            manifest,
            renames=tuple(
                ManifestRename(
                    from_ref=VersionRef(r.from_ref),
                    old_path=r.old_path,
                    new_path=r.new_path,
                    similarity=r.similarity,
                )
                for r in command.renames
            ),
            renamed_from=_renamed_from(command.renamed_from, command.renames),
        )
        await self.manifests.replace_renames(
            manifest.id, checked.renames, renamed_from=checked.renamed_from
        )
        by_path = await self.repository.get_manual_tags(library_id)
        retagged = [
            await self.tagger.apply(live, by_path)
            for live in await self.manifests.list_live(library_id)
        ]
        return RenamesReplaced(
            manifest_id=manifest.id, retagged=[r for r in retagged if r.articles]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivateManifestUseCase:
    """Implements ``ports.driving.ActivateManifest``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    clock: Clock
    """Tells the time that stamps what is stored and when the grace periods end."""

    async def __call__(self, command: ActivateManifestCommand) -> ActivatedManifest:
        """Flip the version to the manifest in one transaction (see the driven port).

        Args:
            command: The pending manifest.

        Returns:
            The manifest and the version it now serves.

        Raises:
            ManifestNotFoundError: No manifest has this ID.
            LibraryNotFoundError: Its library was removed.
        """
        manifest_id = ManifestId(command.manifest_id)
        manifest = await self.manifests.get(manifest_id)
        if manifest is None:
            raise ManifestNotFoundError(command.manifest_id)
        library = await self.repository.get(manifest.library)
        if library is None:
            raise LibraryNotFoundError(str(manifest.library))
        version = await self.manifests.activate(manifest_id, at=self.clock.now())
        moved = replace(
            library,
            versions=frozenset({v for v in library.versions if v.ref != version.ref} | {version}),
        )
        return ActivatedManifest(
            manifest_id=command.manifest_id,
            version=ResolvedVersion.from_library(moved, version),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListArticlesUseCase:
    """Implements ``ports.driving.ListArticles``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    entries: EntrySearch
    """Filters, sorts and pages a manifest's entries."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ListArticlesQuery) -> ArticleList:
        """List a page of the active manifest's articles inside a directory, sorted by path.

        The prefix is a directory: ``guide`` matches ``guide`` itself and everything under
        ``guide/``, not ``guide-old/``.

        Args:
            query: The version, the filters and the page.

        Returns:
            The page of articles, sorted by path, with the next cursor.

        Raises:
            ArticleNotFoundError: The version has no active manifest.
        """
        await _require(self.access, query.library, Access.READ)
        ref = VersionRef(query.ref) if query.ref else None
        library, version, notes = await _read_version(
            self.repository, LibraryId(query.library), ref
        )
        manifest = await self.manifests.get_active(library.id, version.ref)
        if manifest is None:
            raise ArticleNotFoundError(str(library.id), str(version.ref), None)
        sort = parse_sort(query.sort, allowed=ARTICLE_SORT_FIELDS, default="path")
        skip = page_offset(cursor=query.cursor, offset=query.offset)
        after = (
            decode_sort_cursor(query.cursor, sort, key_field="path")
            if query.cursor is not None
            else None
        )
        prefix = query.path_prefix.strip("/")
        tags = query.tag_filter.selection()
        entries = await self.entries.search(
            manifest.id,
            prefix=prefix,
            tags=tags,
            text=query.q,
            sort=sort,
            after=after,
            offset=skip,
            limit=query.limit + 1,  # one more than asked tells whether another page follows
        )
        page = entries[: query.limit]
        more = len(entries) > query.limit
        return ArticleList(
            library=str(library.id),
            ref=str(version.ref),
            commit_sha=manifest.commit_sha,
            manifest_id=manifest.id,
            articles=[ArticleSummary.from_model(e) for e in page],
            next_cursor=(
                encode_sort_cursor(
                    sort,
                    key_field="path",
                    value=_entry_value(page[-1], sort.field),
                    key=page[-1].path,
                )
                if more
                else None
            ),
            total=await self.entries.count(manifest.id, prefix=prefix, tags=tags, text=query.q),
            notes=notes,
        )


def _entry_value(entry: ManifestEntry, field: str) -> str | int:
    """Return an entry's value of a sort field, as the store compares it.

    Args:
        entry: The article's entry.
        field: `path`, `title` or `size`.

    Returns:
        The path, the lower-cased title or the size.
    """
    return {"path": entry.path, "title": entry.title.lower(), "size": entry.size}[field]


async def _renames_manifest(
    repository: LibraryRepository, manifests: ManifestRepository, library: str, ref: str | None
) -> tuple[str, str, ManifestId]:
    """Return ``(library, ref, manifest ID)`` of the version whose renames are asked for.

    Args:
        repository: Where the library is read.
        manifests: Where the active manifest is read.
        library: The library ID, any letter case.
        ref: The exact ref; ``None`` for the default version.

    Returns:
        The library ID, the version's ref and its active manifest's ID.

    Raises:
        ArticleNotFoundError: The version has no active manifest.
    """
    found, version = await _find_version(
        repository, LibraryId(library), VersionRef(ref) if ref else None
    )
    manifest = await manifests.get_active(found.id, version.ref)
    if manifest is None:
        raise ArticleNotFoundError(str(found.id), str(version.ref), None)
    return str(found.id), str(version.ref), manifest.id


def _renamed_from(given: str | None, renames: Sequence[RenameIn]) -> VersionRef | None:
    """Return the version a rename map was detected against.

    Args:
        given: The version the caller named, if any.
        renames: The map; each rename names the version it came from.

    Returns:
        ``given``, else the version of the first rename, else ``None``.
    """
    if given is not None:
        return VersionRef(given)
    return VersionRef(renames[0].from_ref) if renames else None


def _chain(
    active: Mapping[VersionRef, Manifest], *, newer: VersionRef, older: VersionRef
) -> list[Manifest] | None:
    """Follow the links from ``newer`` back to ``older``: the manifests whose maps are crossed.

    Each manifest names the version it follows (``Manifest.renamed_from``). The walk stops at a
    manifest without a link, at a branch (its link is itself), at a version that has no active
    manifest any more, and after ``MAX_RENAME_HOPS`` links (which also ends any cycle).

    Args:
        active: The library's active manifests, by ref.
        newer: The version the walk starts from.
        older: The version it must reach.

    Returns:
        The manifests from ``newer`` on, newest first, each linked to the next; ``None`` when
        ``older`` is not reached.
    """
    hops: list[Manifest] = []
    at = active.get(newer)
    while at is not None and len(hops) < MAX_RENAME_HOPS:
        link = at.renamed_from
        if link is None or link == at.ref:
            return None
        hops.append(at)
        if link == older:
            return hops
        at = active.get(link)
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveRenamedPathUseCase:
    """Implements ``ports.driving.ResolveRenamedPath``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    titles: ArticleTitleFinder
    """Confirms the path a chain ends at is an article of the version asked for."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ResolveRenamedPathQuery) -> RenamedPath | None:
        """Look the path up in the renames stored with the version's active manifest.

        With ``from_ref``, every map between that version and ``ref`` is followed instead.

        Args:
            query: The version, the path and the direction or the version the path is from.

        Returns:
            The move, or ``None`` when git saw none.
        """
        await _require(self.access, query.library, Access.READ)
        library, ref, manifest = await _renames_manifest(
            self.repository, self.manifests, query.library, query.ref
        )
        if query.from_ref is not None:
            _, start = await _find_version(
                self.repository, LibraryId(library), VersionRef(query.from_ref)
            )
            return await self._across(library, VersionRef(ref), manifest, start.ref, query.path)
        rename = await self.manifests.find_rename(manifest, query.path, query.direction)
        return None if rename is None else RenamedPath.from_model(library, ref, rename)

    async def _across(
        self, library: str, to: VersionRef, target: ManifestId, start: VersionRef, path: str
    ) -> RenamedPath | None:
        """Follow ``path`` of ``start`` to ``to`` along the links between them, either way.

        The library's active manifests are read in one query; then one rename lookup per
        version crossed, at most ``MAX_RENAME_HOPS``, and one lookup that the path found is an
        article of ``to``. Versions not linked (another branch, a version removed in between, a
        chain too long), a rename recorded against another version than the link, and a path
        ``to`` does not have (renamed, then dropped) give ``None``: the answer is never a path
        of another version.

        Args:
            library: The library ID.
            to: The version the path is wanted in.
            target: The active manifest of ``to``.
            start: The version the path is from.
            path: The path in ``start``.

        Returns:
            The move from ``start`` to ``to``, or ``None`` when the path did not move.
        """
        if start == to:
            return None
        active = {
            m.ref: m
            for m in await self.manifests.list_live(LibraryId(library))
            if m.state is ManifestState.ACTIVE
        }
        hops = _chain(active, newer=to, older=start)
        direction = RenameDirection.FORWARD
        if hops is None:
            hops = _chain(active, newer=start, older=to)
            direction = RenameDirection.BACK
        if hops is None:
            return None
        if direction is RenameDirection.FORWARD:
            hops.reverse()  # oldest first: the path moves forward through each newer map
        at, similarity = path, MAX_SIMILARITY
        for manifest in hops:
            rename = await self.manifests.find_rename(manifest.id, at, direction)
            if rename is None:
                continue  # nothing moved at this hop
            if rename.from_ref != manifest.renamed_from:
                return None  # stored before the link was checked: the chain is broken
            at = rename.new_path if direction is RenameDirection.FORWARD else rename.old_path
            similarity = min(similarity, rename.similarity)
        if at == path or at not in await self.titles.titles(target, [at]):
            return None  # did not move, or moved and then dropped: not a path of ``to``
        return RenamedPath(
            library=library,
            ref=str(to),
            from_ref=str(start),
            old_path=path,
            new_path=at,
            similarity=similarity,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListRenamesUseCase:
    """Implements ``ports.driving.ListRenames``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ListRenamesQuery) -> RenameList:
        """List the renames stored with the version's active manifest.

        Args:
            query: The version.

        Returns:
            Its renames, by old path.
        """
        await _require(self.access, query.library, Access.READ)
        library, ref, manifest = await _renames_manifest(
            self.repository, self.manifests, query.library, query.ref
        )
        renames = await self.manifests.list_renames(manifest, limit=MAX_RENAMES)
        return RenameList(renames=[RenamedPath.from_model(library, ref, r) for r in renames])


@dataclass(frozen=True, slots=True, kw_only=True)
class GetArticleUseCase:
    """Implements ``ports.driving.GetArticle``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: GetArticleQuery) -> Article:
        """Read one article of the version's active manifest.

        Args:
            query: The version and the article path.

        Returns:
            The article with its text and metadata.

        Raises:
            ArticleNotFoundError: The version has no such article; the error names close matches.
        """
        await _require(self.access, query.library, Access.READ)
        ref = VersionRef(query.ref) if query.ref else None
        library, version, notes = await _read_version(
            self.repository, LibraryId(query.library), ref
        )
        stored = await self.manifests.get_article(library.id, version.ref, query.path)
        if stored is None:
            raise ArticleNotFoundError(
                str(library.id),
                str(version.ref),
                query.path,
                await self._close(library, version, query.path),
            )
        link = section_link(
            library.host.value, library.source_url, stored.commit_sha, stored.entry.path
        )
        info = ArticleInfo.from_stored(str(library.id), str(version.ref), stored, link)
        return Article.with_content(info, stored.content, notes=notes)

    async def _close(self, library: Library, version: Version, path: str) -> list[str]:
        """Paths of this version an agent may have meant (only looked up on a miss).

        Args:
            library: The library.
            version: The version.
            path: The path asked for.

        Returns:
            The close paths, best first; none when the version has no active manifest.
        """
        manifest = await self.manifests.get_active(library.id, version.ref)
        if manifest is None:
            return []
        paths = await self.manifests.list_paths(manifest.id, limit=MAX_SUGGESTION_SCAN)
        # difflib is CPU-bound: keep it off the event loop so a miss cannot stall other requests.
        return await asyncio.to_thread(close_paths, path, paths)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetAssetUseCase:
    """Implements ``ports.driving.GetAsset``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: GetAssetQuery) -> Asset:
        """Read one image of the version's active manifest.

        Args:
            query: The version, the image path and the blob SHAs the caller holds.

        Returns:
            The image, or ``unchanged`` without bytes when the caller holds it.

        Raises:
            AssetNotFoundError: The version has no image at this path.
        """
        await _require(self.access, query.library, Access.READ)
        ref = VersionRef(query.ref) if query.ref else None
        library, version, _ = await _read_version(self.repository, LibraryId(query.library), ref)
        known = bool(query.known_blob_shas)
        image = await self.manifests.get_image(
            library.id, version.ref, query.path, with_data=not known
        )
        if image is not None and known and image.blob_sha in query.known_blob_shas:
            return Asset(
                blob_sha=image.blob_sha, content_type=image.content_type, data=b"", unchanged=True
            )
        if image is not None and known:  # a miss: now read the bytes
            image = await self.manifests.get_image(library.id, version.ref, query.path)
        if image is None:
            raise AssetNotFoundError(str(library.id), str(version.ref), query.path)
        return Asset(blob_sha=image.blob_sha, content_type=image.content_type, data=image.data)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetLogoUseCase:
    """Implements ``ports.driving.GetLogo``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    logos: LibraryLogos
    """Keeps each library's logo."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: GetLogoQuery) -> Logo:
        """Read the library's logo, or only say the caller's copy is current.

        Args:
            query: The library and the logo versions the caller holds.

        Returns:
            The logo, or ``unchanged`` without bytes when its version is one the caller holds.

        Raises:
            LibraryNotFoundError: The library is not in the catalog (or hidden from the caller).
            LogoNotFoundError: The library has no logo.
        """
        await _require(self.access, query.library, Access.READ)
        library_id = LibraryId(query.library)
        logo = await self.logos.get(library_id)
        if logo is None:
            if await self.repository.get(library_id) is None:
                raise LibraryNotFoundError(query.library)
            raise LogoNotFoundError(str(library_id))
        if logo.digest in query.known_digests:
            return Logo(
                digest=logo.digest, content_type=logo.content_type, data=b"", unchanged=True
            )
        return Logo(digest=logo.digest, content_type=logo.content_type, data=logo.data)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListTagsUseCase:
    """Implements ``ports.driving.ListTags``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ListTagsQuery) -> TagList:
        """Count the tags of the version's active manifest.

        Args:
            query: The version.

        Returns:
            Its most used tags, with their counts.

        Raises:
            ArticleNotFoundError: The version has no active manifest.
        """
        await _require(self.access, query.library, Access.READ)
        ref = VersionRef(query.ref) if query.ref else None
        library, version, notes = await _read_version(
            self.repository, LibraryId(query.library), ref
        )
        manifest = await self.manifests.get_active(library.id, version.ref)
        if manifest is None:
            raise ArticleNotFoundError(str(library.id), str(version.ref), None)
        # One more than shown tells whether tags were left out.
        counted = await self.manifests.count_tags(manifest.id, limit=MAX_TAG_FACETS + 1)
        return TagList(
            library=str(library.id),
            ref=str(version.ref),
            commit_sha=manifest.commit_sha,
            tags=[TagCount(tag=tag, count=count) for tag, count in counted[:MAX_TAG_FACETS]],
            truncated=len(counted) > MAX_TAG_FACETS,
            notes=notes,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscardPendingManifestsUseCase:
    """Implements ``ports.driving.DiscardPendingManifests``."""

    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    clock: Clock
    """Tells the time that stamps what is stored and when the grace periods end."""

    async def __call__(self, command: DiscardPendingManifestsCommand) -> DiscardedManifests:
        """Delete the pending manifest(s); active and superseded ones are never touched.

        Args:
            command: The filters.

        Returns:
            How many pending manifests were deleted.
        """
        older = command.older_than_seconds
        count = await self.manifests.discard_pending(
            manifest_id=None if command.manifest_id is None else ManifestId(command.manifest_id),
            library_id=None if command.library is None else LibraryId(command.library),
            created_before=None if older is None else self.clock.now() - timedelta(seconds=older),
        )
        return DiscardedManifests(count=count)


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectGarbageUseCase:
    """Implements ``ports.driving.CollectGarbage``."""

    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    clock: Clock
    """Tells the time that stamps what is stored and when the grace periods end."""

    async def __call__(self, command: CollectGarbageCommand) -> CollectionResult:
        """Delete manifests superseded before the grace period, then contents nobody uses.

        Args:
            command: The grace period.

        Returns:
            How many manifests, texts and images were deleted.
        """
        cutoff = self.clock.now() - timedelta(seconds=command.grace_seconds)
        collected = await self.manifests.collect_garbage(superseded_before=cutoff)
        return CollectionResult.from_model(collected)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetManifestStatesUseCase:
    """Implements ``ports.driving.GetManifestStates``."""

    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""

    async def __call__(self, query: GetManifestStatesQuery) -> ManifestStates:
        """Look each ID up; unknown ones are left out.

        Args:
            query: The manifest IDs.

        Returns:
            The state of each manifest found.
        """
        found = await self.manifests.get_many(
            [ManifestId(i) for i in dict.fromkeys(query.manifest_ids)]
        )
        return ManifestStates(states={i: m.state for i, m in found.items()})


@dataclass(frozen=True, slots=True, kw_only=True)
class GetArticleTitlesUseCase:
    """Implements ``ports.driving.GetArticleTitles``."""

    titles: ArticleTitleFinder
    """Reads the manifest's entries."""

    async def __call__(self, query: GetArticleTitlesQuery) -> ArticleTitles:
        """Look the paths up in the manifest's entries.

        Args:
            query: The manifest and the paths.

        Returns:
            The titles found.
        """
        titles = await self.titles.titles(ManifestId(query.manifest_id), query.paths)
        return ArticleTitles(titles=dict(titles))


@dataclass(frozen=True, slots=True, kw_only=True)
class GetInstructionFilesUseCase:
    """Implements ``ports.driving.GetInstructionFiles``."""

    reader: InstructionFileReader
    """Reads the manifest's instruction files."""

    async def __call__(self, query: GetInstructionFilesQuery) -> InstructionFiles:
        """Read the files kept with the manifest.

        Args:
            query: The manifest.

        Returns:
            Its files, sorted by path; none for an unknown manifest.
        """
        found = await self.reader.list_instructions(ManifestId(query.manifest_id))
        return InstructionFiles(
            files=[
                InstructionFileOut(path=f.path, content=f.content)
                for f in sorted(found, key=lambda f: f.path)
            ]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetActiveManifestUseCase:
    """Implements ``ports.driving.GetActiveManifest``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""

    async def __call__(self, query: GetActiveManifestQuery) -> ActiveManifest:
        """Name the version's active manifest; unknown library or version raise not-found.

        Args:
            query: The version.

        Returns:
            The version's commit and its active manifest, if any.
        """
        ref = VersionRef(query.ref) if query.ref else None
        library, version = await _find_version(self.repository, LibraryId(query.library), ref)
        manifest = await self.manifests.get_active(library.id, version.ref)
        return ActiveManifest(
            library=str(library.id),
            ref=str(version.ref),
            commit_sha=version.commit_sha if manifest is None else manifest.commit_sha,
            manifest_id=None if manifest is None else manifest.id,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListDefaultManifestsUseCase:
    """Implements ``ports.driving.ListDefaultManifests``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""

    async def __call__(self) -> DefaultManifests:
        """Take every library's default version (one read) and its active manifest (batched).

        Returns:
            Each library's default version that has an active manifest, by library ID.
        """
        defaults = [
            (library, version)
            for library in await self.repository.list_all()
            if (version := library.default_version()) is not None
        ]
        active = await self.manifests.get_active_many([(lib.id, v.ref) for lib, v in defaults])
        return DefaultManifests(
            manifests=[
                DefaultManifest(
                    library=str(library.id),
                    ref=str(version.ref),
                    commit_sha=manifest.commit_sha,
                    manifest_id=manifest.id,
                    source_url=library.source_url,
                    host=library.host,
                )
                for library, version in sorted(defaults, key=lambda d: d[0].id.value)
                if (manifest := active.get((library.id, version.ref))) is not None
            ]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveVersionUseCase:
    """Implements ``ports.driving.RemoveVersion``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: RemoveVersionCommand) -> Removal:
        """Delete the version and its manifests; report which version is the default now.

        Args:
            command: The library and the exact ref.

        Returns:
            The manifests removed and the default version now.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
            VersionNotFoundError: The library has no version of exactly this ref.
        """
        await _require(self.access, command.library, Access.ADMINISTER)
        library_id, ref = LibraryId(command.library), VersionRef(command.ref)
        library = await self.repository.get(library_id)
        if library is None:
            raise LibraryNotFoundError(command.library)
        if all(v.ref != ref for v in library.versions):  # exact: a short SHA removes nothing
            raise VersionNotFoundError(str(library.id), str(ref))
        removed = await self.manifests.remove_version(library.id, ref)
        remaining = replace(
            library, versions=frozenset(v for v in library.versions if v.ref != ref)
        )
        default = remaining.default_version()
        return Removal(
            library=str(library.id),
            ref=str(ref),
            manifest_ids=list(removed),
            default_ref=None if default is None else str(default.ref),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveLibraryUseCase:
    """Implements ``ports.driving.RemoveLibrary``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    manifests: ManifestRepository
    """Stores the manifests with their articles, images and renames."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: RemoveLibraryCommand) -> Removal:
        """Delete the library with its versions and manifests.

        Args:
            command: The library.

        Returns:
            Every manifest removed.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        await _require(self.access, command.library, Access.OWN)
        library = await self.repository.get(LibraryId(command.library))
        if library is None:
            raise LibraryNotFoundError(command.library)
        removed = await self.manifests.remove_library(library.id)
        await self.access.forget(library.id.value)
        return Removal(
            library=str(library.id), ref=None, manifest_ids=list(removed), default_ref=None
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CopyManifestUseCase:
    """Implements ``ports.driving.CopyManifest``."""

    repository: LibraryRepository
    """Stores the libraries, their versions, settings and manual tags."""
    copier: ManifestCopier
    """Copies a version's active manifest."""
    clock: Clock
    """Tells the time that stamps what is stored and when the grace periods end."""

    async def __call__(self, command: CopyManifestCommand) -> CopiedManifest:
        """Copy the active manifest of the version as a pending one, created now.

        Args:
            command: The version and the parser version its articles must be stored by.

        Returns:
            The pending copy with its articles' texts.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
            VersionNotFoundError: The version is not imported, has no active manifest, or its texts
                are of another parser version.
        """
        library = await self.repository.get(LibraryId(command.library))
        if library is None:
            raise LibraryNotFoundError(command.library)
        ref = VersionRef(command.ref)
        if all(v.ref != ref for v in library.versions):
            raise VersionNotFoundError(str(library.id), command.ref)
        copied = await self.copier.copy_active(
            library.id,
            ref,
            ManifestId(uuid4().hex),
            at=self.clock.now(),
            content_version=command.content_version,
        )
        if copied is None:
            raise VersionNotFoundError(str(library.id), command.ref)
        manifest, articles = copied
        return CopiedManifest(
            manifest_id=manifest.id,
            library=str(library.id),
            ref=str(ref),
            kind=manifest.kind,
            commit_sha=manifest.commit_sha,
            articles=[
                CopiedArticle(
                    path=a.entry.path,
                    blob_sha=a.entry.blob_sha,
                    title=a.entry.title,
                    front_matter=a.entry.front_matter,
                    tags=list(a.entry.tags),
                    content=a.content,
                )
                for a in articles
            ],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class IsLibraryIdTakenUseCase:
    """Implements ``ports.driving.IsLibraryIdTaken`` for authorized creators."""

    repository: LibraryRepository
    """The catalog's libraries."""
    access: AccessPolicy
    """Instance creation permission."""

    async def __call__(self, query: GetLibraryQuery) -> bool:
        """Check an ID without granting the caller read access to its existing library.

        Args:
            query: The proposed ID.

        Returns:
            Whether the ID is occupied.

        Raises:
            LibraryCreationDeniedError: The caller lacks creation permission.
        """
        if not await self.access.can_create(query.id):
            raise LibraryCreationDeniedError
        return await self.repository.get(LibraryId(query.id)) is not None
