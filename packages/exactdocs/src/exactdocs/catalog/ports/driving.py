"""Driving (primary) ports: what the outside world may ask the catalog to do."""

from typing import Protocol

from exactdocs.catalog.dtos import (
    ActivatedManifest,
    ActivateManifestCommand,
    Article,
    ArticleList,
    CollectGarbageCommand,
    CollectionResult,
    DiscardedManifests,
    DiscardPendingManifestsCommand,
    GetArticleQuery,
    GetLibraryQuery,
    LibraryDetail,
    LibraryList,
    ListArticlesQuery,
    ListLibrariesQuery,
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

    Raises ``ManifestNotFoundError``, or ``ManifestNotPendingError`` when it was activated
    before. If anything fails, the previous manifest stays active.
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
    """Delete pending manifests: one by ID, or all of them (recovery after a crash)."""

    async def __call__(self, command: DiscardPendingManifestsCommand) -> DiscardedManifests:
        """Run the use case."""
        ...


class CollectGarbage(Protocol):
    """Delete manifests superseded longer ago than the grace period, and unused contents."""

    async def __call__(self, command: CollectGarbageCommand) -> CollectionResult:
        """Run the use case."""
        ...
