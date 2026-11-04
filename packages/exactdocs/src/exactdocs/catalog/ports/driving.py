"""Driving (primary) ports: what the outside world may ask the catalog to do."""

from typing import Protocol

from exactdocs.catalog.dtos import (
    ActivatedManifest,
    ActivateManifestCommand,
    ActiveManifest,
    Article,
    ArticleList,
    CollectGarbageCommand,
    CollectionResult,
    DiscardedManifests,
    DiscardPendingManifestsCommand,
    GetActiveManifestQuery,
    GetArticleQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
    LibraryDetail,
    LibraryList,
    ListArticlesQuery,
    ListLibrariesQuery,
    ManifestStates,
    ResolvedVersion,
    ResolveVersionQuery,
    StoredManifest,
    StoreManifestCommand,
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
