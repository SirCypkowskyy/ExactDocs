"""Driving (primary) ports: what the outside world may ask the catalog to do."""

from typing import Protocol

from exactdocs.catalog.dtos import (
    ActivatedManifest,
    ActivateManifestCommand,
    ActiveManifest,
    ApplyManualTagsCommand,
    ApplyReadmeCommand,
    Article,
    ArticleList,
    Asset,
    CollectGarbageCommand,
    CollectionResult,
    CreateLibraryCommand,
    DefaultManifests,
    DiscardedManifests,
    DiscardLibraryCommand,
    DiscardPendingManifestsCommand,
    GetActiveManifestQuery,
    GetArticleQuery,
    GetAssetQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
    GetVersionTagsQuery,
    LibraryDetail,
    LibraryList,
    ListArticlesQuery,
    ListLibrariesQuery,
    ListRenamesQuery,
    ListTagsQuery,
    ManifestStates,
    ManualTagsOut,
    PinDefaultVersionCommand,
    Removal,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RenamedPath,
    RenameList,
    ResolvedVersion,
    ResolveRenamedPathQuery,
    ResolveVersionQuery,
    RetaggedManifest,
    SetImportedTagsCommand,
    SetLibrarySettingsCommand,
    SetManualTagsCommand,
    StoredManifest,
    StoreManifestCommand,
    TagList,
    UpdateLibraryCommand,
    VersionTags,
)


class ListLibraries(Protocol):
    """List a page of libraries and their indexed versions."""

    async def __call__(self, query: ListLibrariesQuery) -> LibraryList:
        """Run the use case."""
        ...


class GetLibrary(Protocol):
    """Fetch one library; raises ``LibraryNotFoundError`` when it is missing."""

    async def __call__(self, query: GetLibraryQuery) -> LibraryDetail:
        """Run the use case."""
        ...


class ResolveVersion(Protocol):
    """Resolve a context7-style ID to the one version it names.

    Raises ``LibraryNotFoundError`` / ``VersionNotFoundError`` for unknown targets and a
    validation error for a malformed ID or an ambiguous short SHA. Never falls back to another
    version.
    """

    async def __call__(self, query: ResolveVersionQuery) -> ResolvedVersion:
        """Run the use case."""
        ...


class StoreManifest(Protocol):
    """Store a version's articles as a pending manifest; nothing changes for readers yet.

    Raises ``LibraryNotFoundError`` for an unknown library and a validation error for a
    malformed ref, SHA or path. Returns the manifest ID that ``ActivateManifest`` takes.
    """

    async def __call__(self, command: StoreManifestCommand) -> StoredManifest:
        """Run the use case."""
        ...


class ActivateManifest(Protocol):
    """Make a pending manifest what its version serves, all at once.

    Activating the manifest that is already active succeeds without changes (so a replay after
    a crash is safe). Raises ``ManifestNotFoundError``; ``ManifestNotPendingError`` when it was
    superseded; ``ManifestOutdatedError`` when a newer manifest of the version is active. If
    anything fails, the previous manifest stays active.
    """

    async def __call__(self, command: ActivateManifestCommand) -> ActivatedManifest:
        """Run the use case."""
        ...


class ListArticles(Protocol):
    """List the articles of a version (default version without a ref), sorted by path.

    Raises ``ArticleNotFoundError`` when the version has no active manifest.
    """

    async def __call__(self, query: ListArticlesQuery) -> ArticleList:
        """Run the use case."""
        ...


class ListTags(Protocol):
    """Count the tags of a version's articles (default version without a ref), most used first.

    Raises ``ArticleNotFoundError`` when the version has no active manifest.
    """

    async def __call__(self, query: ListTagsQuery) -> TagList:
        """Run the use case."""
        ...


class ResolveRenamedPath(Protocol):
    """Follow a path across the renames git detected when the version was imported.

    ``FORWARD``: where did ``path`` of the previous version go in ``ref``? ``BACK``: where was
    ``path`` of ``ref`` in the previous version? ``None`` when the version's manifest has no
    such rename (or none were detected). It is one hop: callers follow a file across several
    versions by asking once per version and chaining the answers (a version that was never
    imported breaks the chain). A tag's map covers the previous numeric tag. A branch's map
    builds up over its syncs: renames are kept, chained (A to B, then B to C gives A to C) and
    dropped when their target is gone.

    Raises ``LibraryNotFoundError`` / ``VersionNotFoundError`` for an unknown target and
    ``ArticleNotFoundError`` when the version has no active manifest.
    """

    async def __call__(self, query: ResolveRenamedPathQuery) -> RenamedPath | None:
        """Run the use case."""
        ...


class ListRenames(Protocol):
    """List every rename stored with a version (same errors as ``ResolveRenamedPath``)."""

    async def __call__(self, query: ListRenamesQuery) -> RenameList:
        """Run the use case."""
        ...


class GetAsset(Protocol):
    """Read one image of a version (default version without a ref).

    Raises ``LibraryNotFoundError``, ``VersionNotFoundError`` or ``AssetNotFoundError`` (the
    version has no active manifest, or the manifest has no image at that path).
    """

    async def __call__(self, query: GetAssetQuery) -> Asset:
        """Run the use case."""
        ...


class GetArticle(Protocol):
    """Read one article of a version (default version without a ref).

    Raises ``ArticleNotFoundError`` when the version has no active manifest or no such path.
    """

    async def __call__(self, query: GetArticleQuery) -> Article:
        """Run the use case."""
        ...


class DiscardPendingManifests(Protocol):
    """Delete the pending manifests that match the command's filters (never "all")."""

    async def __call__(self, command: DiscardPendingManifestsCommand) -> DiscardedManifests:
        """Run the use case."""
        ...


class CollectGarbage(Protocol):
    """Delete manifests superseded longer ago than the grace period, and unused contents."""

    async def __call__(self, command: CollectGarbageCommand) -> CollectionResult:
        """Run the use case."""
        ...


class GetManifestStates(Protocol):
    """Tell whether manifests are pending, active or superseded, for domains that hold their IDs."""

    async def __call__(self, query: GetManifestStatesQuery) -> ManifestStates:
        """Run the use case."""
        ...


class GetActiveManifest(Protocol):
    """Name the manifest that serves a version, for domains that hold manifest IDs."""

    async def __call__(self, query: GetActiveManifestQuery) -> ActiveManifest:
        """Run the use case."""
        ...


class ListDefaultManifests(Protocol):
    """Name the active manifest of every library's default version, in one call.

    Libraries without a default version or without an active manifest are left out. The bulk
    form of ``GetLibrary`` + ``GetActiveManifest`` for domains that search all libraries.
    """

    async def __call__(self) -> DefaultManifests:
        """Run the use case."""
        ...


class CreateLibrary(Protocol):
    """Add a library without versions.

    Raises ``LibraryAlreadyExistsError`` or a validation error.
    """

    async def __call__(self, command: CreateLibraryCommand) -> LibraryDetail:
        """Run the use case."""
        ...


class DiscardLibrary(Protocol):
    """Remove a library that has no versions yet (the undo of ``CreateLibrary``).

    Does nothing for an unknown ID; raises ``LibraryNotEmptyError`` when it has versions.
    """

    async def __call__(self, command: DiscardLibraryCommand) -> None:
        """Run the use case."""
        ...


class UpdateLibrary(Protocol):
    """Set a library's title and/or description by hand; later README imports keep them.

    Raises ``LibraryNotFoundError``.
    """

    async def __call__(self, command: UpdateLibraryCommand) -> LibraryDetail:
        """Run the use case."""
        ...


class RemoveVersion(Protocol):
    """Remove a version: it and its manifests are gone at once, in one transaction.

    Texts that no manifest uses any more are freed by ``CollectGarbage``. The default version is
    computed from the versions that remain, so it follows. Raises ``LibraryNotFoundError`` /
    ``VersionNotFoundError``; the ref must match exactly (a short SHA does not).
    """

    async def __call__(self, command: RemoveVersionCommand) -> Removal:
        """Run the use case."""
        ...


class ApplyReadme(Protocol):
    """Take title and description from the README of a just-imported version.

    Only the default version's README counts, and only for a field no user has edited. Raises
    ``LibraryNotFoundError``.
    """

    async def __call__(self, command: ApplyReadmeCommand) -> None:
        """Run the use case."""
        ...


class RemoveLibrary(Protocol):
    """Remove a library with all its versions and manifests, in one transaction.

    Raises ``LibraryNotFoundError``. Unlike ``DiscardLibrary`` it takes libraries that have
    versions.
    """

    async def __call__(self, command: RemoveLibraryCommand) -> Removal:
        """Run the use case."""
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
        """Run the use case."""
        ...


class ApplyManualTags(Protocol):
    """Give a manifest the manual tags its library has now (before it is activated).

    Returns the articles that carry manual tags, or carried some, with their tags now. Raises
    ``ManifestNotFoundError``.
    """

    async def __call__(self, command: ApplyManualTagsCommand) -> RetaggedManifest:
        """Run the use case."""
        ...


class PinDefaultVersion(Protocol):
    """Pin the library's default version to an imported one, or unpin it (LIB-10).

    A ref is matched exactly (or as a unique short SHA), never approximated. Raises
    ``LibraryNotFoundError`` / ``VersionNotFoundError``. Unpinned, the default follows the
    default-version rule again. Removing the pinned version unpins the library.
    """

    async def __call__(self, command: PinDefaultVersionCommand) -> LibraryDetail:
        """Run the use case."""
        ...


class SetLibrarySettings(Protocol):
    """Replace a library's paths and tag rules; its chunking settings stay.

    Nothing is re-imported here: the importer re-processes the versions. Raises
    ``LibraryNotFoundError`` and a validation error for a tag rule that cannot be one.
    """

    async def __call__(self, command: SetLibrarySettingsCommand) -> LibraryDetail:
        """Run the use case."""
        ...


class GetVersionTags(Protocol):
    """Name a version's active manifest with each article's path, front matter and imported tags.

    For the importer, which derives imported tags again when tag rules change. The ref must
    match exactly. Raises ``LibraryNotFoundError`` / ``VersionNotFoundError``.
    """

    async def __call__(self, query: GetVersionTagsQuery) -> VersionTags:
        """Run the use case."""
        ...


class SetImportedTags(Protocol):
    """Replace the imported tags of articles of a manifest in one transaction (manual ones stay).

    Returns the articles whose tags changed, with every tag they carry now, for the copies
    other domains keep. Raises ``ManifestNotFoundError``.
    """

    async def __call__(self, command: SetImportedTagsCommand) -> RetaggedManifest:
        """Run the use case."""
        ...
