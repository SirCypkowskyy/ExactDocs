"""Driving (primary) ports: what the outside world may ask the catalog to do."""

from typing import Protocol

from exactdocs.catalog.dtos import (
    ActivatedManifest,
    ActivateManifestCommand,
    ActiveManifest,
    ApplyLogoCommand,
    ApplyManualTagsCommand,
    ApplyReadmeCommand,
    Article,
    ArticleList,
    ArticleTitles,
    Asset,
    CollectGarbageCommand,
    CollectionResult,
    CopiedManifest,
    CopyManifestCommand,
    CreateLibraryCommand,
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
    InstructionFiles,
    LibraryDetail,
    LibraryList,
    ListArticlesQuery,
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
    StoredArticles,
    StoredManifest,
    StoreManifestCommand,
    TagList,
    UpdateLibraryCommand,
    VersionList,
    VersionTags,
)


class ListLibraries(Protocol):
    """List a page of libraries and their indexed versions."""

    async def __call__(
        self,
        query: ListLibrariesQuery,
        *,
        only: frozenset[str] | None = None,
        without: frozenset[str] = frozenset(),
    ) -> LibraryList:
        """Run the use case.

        Args:
            query: The page size and the cursor of the previous page.
            only: Case-folded library IDs; when given, no other library is listed.
            without: Case-folded library IDs that are not listed.

        Returns:
            The page of libraries, sorted by ID, with the next cursor.
        """
        ...


class GetLibrary(Protocol):
    """Fetch one library; raises ``LibraryNotFoundError`` when it is missing."""

    async def __call__(self, query: GetLibraryQuery) -> LibraryDetail:
        """Run the use case.

        Args:
            query: The library ID.

        Returns:
            The library with every version and its settings.
        """
        ...


class ResolveVersion(Protocol):
    """Resolve a context7-style ID to the one version it names.

    Raises ``LibraryNotFoundError`` / ``VersionNotFoundError`` for unknown targets and a
    validation error for a malformed ID or an ambiguous short SHA. Never falls back to another
    version.
    """

    async def __call__(self, query: ResolveVersionQuery) -> ResolvedVersion:
        """Run the use case.

        Args:
            query: `/owner/repo` or `/owner/repo/<ref>`.

        Returns:
            The version it names, with its library.
        """
        ...


class StoreManifest(Protocol):
    """Store a version's articles as a pending manifest; nothing changes for readers yet.

    Raises ``LibraryNotFoundError`` for an unknown library and a validation error for a
    malformed ref, SHA or path. Returns the manifest ID that ``ActivateManifest`` takes.
    """

    async def __call__(self, command: StoreManifestCommand) -> StoredManifest:
        """Run the use case.

        Args:
            command: The version, its articles, images, renames and instruction files.

        Returns:
            The pending manifest, for ``ActivateManifest``.
        """
        ...


class ActivateManifest(Protocol):
    """Make a pending manifest what its version serves, all at once.

    Activating the manifest that is already active succeeds without changes (so a replay after
    a crash is safe). Raises ``ManifestNotFoundError``; ``ManifestNotPendingError`` when it was
    superseded; ``ManifestOutdatedError`` when a newer manifest of the version is active. If
    anything fails, the previous manifest stays active.
    """

    async def __call__(self, command: ActivateManifestCommand) -> ActivatedManifest:
        """Run the use case.

        Args:
            command: The pending manifest.

        Returns:
            The manifest and the version it now serves.
        """
        ...


class ListVersions(Protocol):
    """List the versions of a library, filtered, sorted and paged."""

    async def __call__(self, query: ListVersionsQuery) -> VersionList:
        """Run the use case.

        Args:
            query: The library, the filters, the sort and the page.

        Returns:
            The page of versions, with the next cursor and the total.
        """
        ...


class ListArticles(Protocol):
    """List the articles of a version (default version without a ref), sorted by path.

    Raises ``ArticleNotFoundError`` when the version has no active manifest.
    """

    async def __call__(self, query: ListArticlesQuery) -> ArticleList:
        """Run the use case.

        Args:
            query: The version, the filters and the page.

        Returns:
            The page of articles, sorted by path, with the next cursor.
        """
        ...


class ListTags(Protocol):
    """Count the tags of a version's articles (default version without a ref), most used first.

    Raises ``ArticleNotFoundError`` when the version has no active manifest.
    """

    async def __call__(self, query: ListTagsQuery) -> TagList:
        """Run the use case.

        Args:
            query: The version.

        Returns:
            Its most used tags, with their counts.
        """
        ...


class ResolveRenamedPath(Protocol):
    """Follow a path across the renames git detected when the version was imported.

    With ``from_ref``: where is ``path`` of ``from_ref`` in ``ref``? Each version names the one
    it follows (its map was detected against it), and the maps of every version between the
    two are followed hop by hop, whichever was imported first. Versions with no such link
    between them (another branch, a version removed in between) give ``None``.

    Without it, one hop. ``FORWARD``: where did ``path`` of the previous version go in ``ref``?
    ``BACK``: where was ``path`` of ``ref`` in the previous version? ``None`` when the version's
    manifest has no such rename (or none were detected). A tag's map covers the previous
    numeric tag. A branch's map builds up over its syncs: renames are kept, chained (A to B,
    then B to C gives A to C) and dropped when their target is gone.

    Raises ``LibraryNotFoundError`` / ``VersionNotFoundError`` for an unknown target or
    ``from_ref`` and ``ArticleNotFoundError`` when the version has no active manifest.
    """

    async def __call__(self, query: ResolveRenamedPathQuery) -> RenamedPath | None:
        """Run the use case.

        Args:
            query: The version, the path and the direction.

        Returns:
            The move, or ``None`` when git saw none.
        """
        ...


class ListRenames(Protocol):
    """List every rename stored with a version (same errors as ``ResolveRenamedPath``)."""

    async def __call__(self, query: ListRenamesQuery) -> RenameList:
        """Run the use case.

        Args:
            query: The version.

        Returns:
            Its renames, by old path.
        """
        ...


class GetAsset(Protocol):
    """Read one image of a version (default version without a ref).

    Raises ``LibraryNotFoundError``, ``VersionNotFoundError`` or ``AssetNotFoundError`` (the
    version has no active manifest, or the manifest has no image at that path).
    """

    async def __call__(self, query: GetAssetQuery) -> Asset:
        """Run the use case.

        Args:
            query: The version, the image path and the blob SHAs the caller holds.

        Returns:
            The image, or ``unchanged`` without bytes when the caller holds it.
        """
        ...


class GetLogo(Protocol):
    """Read a library's logo (#504).

    Raises ``LibraryNotFoundError`` (also for a library the caller may not read) or
    ``LogoNotFoundError`` (the importer found none in its default version).
    """

    async def __call__(self, query: GetLogoQuery) -> Logo:
        """Run the use case.

        Args:
            query: The library and the logo versions the caller holds.

        Returns:
            The logo, or ``unchanged`` without bytes when the caller holds it.
        """
        ...


class GetArticle(Protocol):
    """Read one article of a version (default version without a ref).

    Raises ``ArticleNotFoundError`` when the version has no active manifest or no such path.
    """

    async def __call__(self, query: GetArticleQuery) -> Article:
        """Run the use case.

        Args:
            query: The version and the article path.

        Returns:
            The article with its text and metadata.
        """
        ...


class DiscardPendingManifests(Protocol):
    """Delete the pending manifests that match the command's filters (never "all")."""

    async def __call__(self, command: DiscardPendingManifestsCommand) -> DiscardedManifests:
        """Run the use case.

        Args:
            command: The filters.

        Returns:
            How many pending manifests were deleted.
        """
        ...


class CollectGarbage(Protocol):
    """Delete manifests superseded longer ago than the grace period, and unused contents."""

    async def __call__(self, command: CollectGarbageCommand) -> CollectionResult:
        """Run the use case.

        Args:
            command: The grace period.

        Returns:
            How many manifests, texts and images were deleted.
        """
        ...


class GetManifestStates(Protocol):
    """Tell whether manifests are pending, active or superseded, for domains that hold their IDs."""

    async def __call__(self, query: GetManifestStatesQuery) -> ManifestStates:
        """Run the use case.

        Args:
            query: The manifest IDs.

        Returns:
            The state of each manifest found.
        """
        ...


class GetArticleTitles(Protocol):
    """Name the titles of some articles of a manifest, for domains that hold its ID (one query)."""

    async def __call__(self, query: GetArticleTitlesQuery) -> ArticleTitles:
        """Run the use case.

        Args:
            query: The manifest and the paths.

        Returns:
            The titles found.
        """
        ...


class GetInstructionFiles(Protocol):
    """Read the instruction files kept with a manifest, for domains that hold its ID (RET-08)."""

    async def __call__(self, query: GetInstructionFilesQuery) -> InstructionFiles:
        """Run the use case.

        Args:
            query: The manifest.

        Returns:
            Its instruction files, sorted by path.
        """
        ...


class GetActiveManifest(Protocol):
    """Name the manifest that serves a version, for domains that hold manifest IDs."""

    async def __call__(self, query: GetActiveManifestQuery) -> ActiveManifest:
        """Run the use case.

        Args:
            query: The version.

        Returns:
            The version's commit and its active manifest, if any.
        """
        ...


class ListDefaultManifests(Protocol):
    """Name the active manifest of every library's default version, in one call.

    Libraries without a default version or without an active manifest are left out. The bulk
    form of ``GetLibrary`` + ``GetActiveManifest`` for domains that search all libraries.
    """

    async def __call__(self) -> DefaultManifests:
        """Run the use case.

        Returns:
            Each library's default version that has an active manifest, by library ID.
        """
        ...


class CreateLibrary(Protocol):
    """Add a library without versions.

    Raises ``LibraryAlreadyExistsError`` or a validation error.
    """

    async def __call__(self, command: CreateLibraryCommand) -> LibraryDetail:
        """Run the use case.

        Args:
            command: The library's ID, source and settings.

        Returns:
            The new library, without versions.
        """
        ...


class DiscardLibrary(Protocol):
    """Remove a library that has no versions yet (the undo of ``CreateLibrary``).

    Does nothing for an unknown ID; raises ``LibraryNotEmptyError`` when it has versions.
    """

    async def __call__(self, command: DiscardLibraryCommand) -> None:
        """Run the use case.

        Args:
            command: The library.
        """
        ...


class UpdateLibrary(Protocol):
    """Set a library's title and/or description by hand; later README imports keep them.

    Raises ``LibraryNotFoundError``.
    """

    async def __call__(self, command: UpdateLibraryCommand) -> LibraryDetail:
        """Run the use case.

        Args:
            command: The library and the fields to change.

        Returns:
            The library as it is now.
        """
        ...


class RemoveVersion(Protocol):
    """Remove a version: it and its manifests are gone at once, in one transaction.

    Texts that no manifest uses any more are freed by ``CollectGarbage``. The default version is
    computed from the versions that remain, so it follows. Raises ``LibraryNotFoundError`` /
    ``VersionNotFoundError``; the ref must match exactly (a short SHA does not).
    """

    async def __call__(self, command: RemoveVersionCommand) -> Removal:
        """Run the use case.

        Args:
            command: The library and the exact ref.

        Returns:
            The manifests removed and the default version now.
        """
        ...


class ApplyReadme(Protocol):
    """Take title and description from the README of a just-imported version.

    Only the default version's README counts, and only for a field no user has edited. Raises
    ``LibraryNotFoundError``.
    """

    async def __call__(self, command: ApplyReadmeCommand) -> None:
        """Run the use case.

        Args:
            command: The version imported and what it says about the library.
        """
        ...


class ApplyLogo(Protocol):
    """Keep the logo a just-imported version has, or remove the library's when it has none.

    Only the default version's logo counts (#504). Raises ``LibraryNotFoundError``.
    """

    async def __call__(self, command: ApplyLogoCommand) -> None:
        """Run the use case.

        Args:
            command: The version imported and its logo, if any.
        """
        ...


class RemoveLibrary(Protocol):
    """Remove a library with all its versions and manifests, in one transaction.

    Raises ``LibraryNotFoundError``. Unlike ``DiscardLibrary`` it takes libraries that have
    versions.
    """

    async def __call__(self, command: RemoveLibraryCommand) -> Removal:
        """Run the use case.

        Args:
            command: The library.

        Returns:
            Every manifest removed.
        """
        ...


class SetManualTags(Protocol):
    """Set the tags a user gives an article path by hand, for every version of the library.

    They replace the path's earlier manual tags (none forgets them) and combine with the imported
    tags of every article at that path, and of every article a rename map traces back to it, in
    the versions imported so far. Listings and tag counts see them at once; the answer names
    the articles whose tags changed, for the copies other domains keep.

    Raises ``LibraryNotFoundError``, and a validation error for a malformed path or a value that
    cannot be a tag.
    """

    async def __call__(self, command: SetManualTagsCommand) -> ManualTagsOut:
        """Run the use case.

        Args:
            command: The library, the path and its tags.

        Returns:
            The path's tags and the manifests whose articles were re-tagged.
        """
        ...


class ApplyManualTags(Protocol):
    """Give a manifest the manual tags its library has now (before it is activated).

    Returns the articles that carry manual tags, or carried some, with their tags now. Raises
    ``ManifestNotFoundError``.
    """

    async def __call__(self, command: ApplyManualTagsCommand) -> RetaggedManifest:
        """Run the use case.

        Args:
            command: The manifest.

        Returns:
            Its articles whose tags changed.
        """
        ...


class ReplaceRenames(Protocol):
    """Replace the rename map of a version's active manifest and re-tag from the new map.

    Every pending and active manifest of the library is re-tagged: a map is followed by the
    versions after it as well. Returns, per manifest, the articles that carry manual tags or
    carried some, with their tags now. Raises ``LibraryNotFoundError`` and
    ``VersionNotFoundError`` (also when the version has no active manifest).
    """

    async def __call__(self, command: ReplaceRenamesCommand) -> RenamesReplaced:
        """Run the use case.

        Args:
            command: The version and its new rename map.

        Returns:
            The manifest and every manifest re-tagged.
        """
        ...


class PinDefaultVersion(Protocol):
    """Pin the library's default version to an imported one, or unpin it (LIB-10).

    A ref is matched exactly (or as a unique short SHA), never approximated. Raises
    ``LibraryNotFoundError`` / ``VersionNotFoundError``. Unpinned, the default follows the
    default-version rule again. Removing the pinned version unpins the library.
    """

    async def __call__(self, command: PinDefaultVersionCommand) -> LibraryDetail:
        """Run the use case.

        Args:
            command: The library and the ref to pin; no ref unpins.

        Returns:
            The library as it is now.
        """
        ...


class SetLibrarySettings(Protocol):
    """Replace a library's paths and tag rules, and its chunking unless it is left out.

    Nothing is re-imported here: the importer re-processes the versions. Raises
    ``LibraryNotFoundError`` and a validation error for a tag rule that cannot be one.
    """

    async def __call__(self, command: SetLibrarySettingsCommand) -> LibraryDetail:
        """Run the use case.

        Args:
            command: The library and its new settings.

        Returns:
            The library as it is now.
        """
        ...


class GetVersionTags(Protocol):
    """Name a version's active manifest with each article's path, front matter and imported tags.

    For the importer, which derives imported tags again when tag rules change. The ref must
    match exactly. Raises ``LibraryNotFoundError`` / ``VersionNotFoundError``.
    """

    async def __call__(self, query: GetVersionTagsQuery) -> VersionTags:
        """Run the use case.

        Args:
            query: The library and the exact ref.

        Returns:
            The active manifest and each article's tag sources; none while it has no manifest.
        """
        ...


class SetImportedTags(Protocol):
    """Replace the imported tags of articles of a manifest in one transaction (manual ones stay).

    Returns every given article the manifest has, changed or not, with every tag it carries
    now, so the copies other domains keep can always be brought in line. Raises
    ``ManifestNotFoundError``.
    """

    async def __call__(self, command: SetImportedTagsCommand) -> RetaggedManifest:
        """Run the use case.

        Args:
            command: The manifest and the new imported tags of some of its articles.

        Returns:
            Those articles with every tag they now carry.
        """
        ...


class FindStoredArticles(Protocol):
    """Return what the library's manifests hold for these files: same path, blob and version.

    For the importer: a file whose path, git blob SHA and content version (the parser version)
    are stored already is not parsed again. Any manifest of the library counts, whatever its
    state. An unknown library holds nothing (no error).
    """

    async def __call__(self, query: FindStoredArticlesQuery) -> StoredArticles:
        """Run the use case.

        Args:
            query: The library, the version imported, the parser version and the files.

        Returns:
            What is stored for the files found.
        """
        ...


class CopyManifest(Protocol):
    """Copy a version's active manifest into a new pending one, with its articles' stored text.

    For the importer, which re-chunks what a version serves after its chunking changed: it
    indexes the copy and activates it (or discards it), and readers see the old manifest until
    then. The ref must match exactly. Raises ``LibraryNotFoundError`` /
    ``VersionNotFoundError`` (also when the version serves nothing) and, copying nothing,
    ``StoredContentOutdatedError`` when the articles were stored by another parser version.
    """

    async def __call__(self, command: CopyManifestCommand) -> CopiedManifest:
        """Run the use case.

        Args:
            command: The version and the parser version its articles must be stored by.

        Returns:
            The pending copy with its articles' texts.
        """
        ...


class IsLibraryIdTaken(Protocol):
    """Check creation ID availability without requiring read access to an existing library."""

    async def __call__(self, query: GetLibraryQuery) -> bool:
        """Check the catalog after verifying instance creation permission.

        Args:
            query: The proposed library ID.

        Returns:
            Whether a library already occupies the ID.
        """
        ...
