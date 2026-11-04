"""Catalog use cases. Each one satisfies a driving port structurally, without inheriting it."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from exactdocs.catalog.dtos import (
    ActivatedManifest,
    ActivateManifestCommand,
    Article,
    ArticleList,
    ArticleSummary,
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
from exactdocs.catalog.errors import (
    ArticleNotFoundError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    Library,
    LibraryId,
    Manifest,
    ManifestEntry,
    ManifestId,
    ParsedId,
    Version,
    VersionRef,
)
from exactdocs.catalog.ports.driven import LibraryRepository, ManifestRepository
from exactdocs_kernel import Clock, paginate


async def _find_version(
    repository: LibraryRepository, library_id: LibraryId, ref: VersionRef | None
) -> tuple[Library, Version]:
    """Find the version a ref names (the default one without a ref); never any other version."""
    library = await repository.get(library_id)
    if library is None:
        raise LibraryNotFoundError(str(library_id))
    version = library.find_version(ref) if ref else library.default_version()
    if version is None:
        raise VersionNotFoundError(str(library.id), None if ref is None else str(ref))
    return library, version


@dataclass(frozen=True, slots=True)
class ListLibrariesUseCase:
    """Implements ``ports.driving.ListLibraries``."""

    repository: LibraryRepository

    async def __call__(self, query: ListLibrariesQuery) -> LibraryList:
        """List a page of libraries, sorted by ID."""
        libraries = sorted(await self.repository.list_all(), key=lambda lib: lib.id.value)
        page = paginate(
            libraries, key=lambda lib: lib.id.value, limit=query.limit, cursor=query.cursor
        )
        return LibraryList.from_page(page)


@dataclass(frozen=True, slots=True)
class GetLibraryUseCase:
    """Implements ``ports.driving.GetLibrary``."""

    repository: LibraryRepository

    async def __call__(self, query: GetLibraryQuery) -> LibraryDetail:
        """Fetch one library by ID."""
        library = await self.repository.get(LibraryId(query.id))
        if library is None:
            raise LibraryNotFoundError(query.id)
        return LibraryDetail.from_model(library)


@dataclass(frozen=True, slots=True)
class ResolveVersionUseCase:
    """Implements ``ports.driving.ResolveVersion``."""

    repository: LibraryRepository

    async def __call__(self, query: ResolveVersionQuery) -> ResolvedVersion:
        """Resolve `/owner/repo[/ref]` to exactly one version."""
        target = ParsedId.parse(query.id)
        library, version = await _find_version(self.repository, target.library, target.ref)
        return ResolvedVersion.from_library(library, version)


@dataclass(frozen=True, slots=True)
class StoreManifestUseCase:
    """Implements ``ports.driving.StoreManifest``."""

    repository: LibraryRepository
    manifests: ManifestRepository
    clock: Clock

    async def __call__(self, command: StoreManifestCommand) -> StoredManifest:
        """Store the articles as a pending manifest, invisible until it is activated."""
        library_id = LibraryId(command.library)
        if await self.repository.get(library_id) is None:
            raise LibraryNotFoundError(command.library)
        manifest = Manifest(
            id=ManifestId(uuid4().hex),
            library=library_id,
            ref=VersionRef(command.ref),
            kind=command.kind,
            commit_sha=command.commit_sha,
            created_at=self.clock.now(),
            entries=tuple(
                sorted(
                    (
                        ManifestEntry(
                            path=a.path,
                            blob_sha=a.blob_sha,
                            title=a.title,
                            tags=tuple(a.tags),
                            front_matter=a.front_matter,
                            size=len(a.content.encode()),
                        )
                        for a in command.articles
                    ),
                    key=lambda entry: entry.path,
                )
            ),
        )
        await self.manifests.add(manifest, {a.blob_sha: a.content for a in command.articles})
        return StoredManifest.from_model(manifest)


@dataclass(frozen=True, slots=True)
class ActivateManifestUseCase:
    """Implements ``ports.driving.ActivateManifest``."""

    repository: LibraryRepository
    manifests: ManifestRepository
    clock: Clock

    async def __call__(self, command: ActivateManifestCommand) -> ActivatedManifest:
        """Flip the version to the manifest in one transaction (see the driven port)."""
        manifest_id = ManifestId(command.manifest_id)
        manifest = await self.manifests.get(manifest_id)
        if manifest is None:
            raise ManifestNotFoundError(command.manifest_id)
        version = await self.manifests.activate(manifest_id, at=self.clock.now())
        library = await self.repository.get(manifest.library)
        if library is None:  # a manifest cannot outlive its library
            raise LibraryNotFoundError(str(manifest.library))
        return ActivatedManifest(
            manifest_id=command.manifest_id,
            version=ResolvedVersion.from_library(library, version),
        )


@dataclass(frozen=True, slots=True)
class ListArticlesUseCase:
    """Implements ``ports.driving.ListArticles``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, query: ListArticlesQuery) -> ArticleList:
        """List a page of the active manifest's articles whose path starts with the prefix."""
        ref = VersionRef(query.ref) if query.ref else None
        library, version = await _find_version(self.repository, LibraryId(query.library), ref)
        manifest = await self.manifests.get_active(library.id, version.ref)
        if manifest is None:
            raise ArticleNotFoundError(str(library.id), str(version.ref), None)
        # ponytail: pages are cut in memory; push `path > :after LIMIT :n` into SQL if manifests
        # grow past a few thousand articles.
        entries = [e for e in manifest.entries if e.path.startswith(query.path_prefix)]
        page = paginate(entries, key=lambda e: e.path, limit=query.limit, cursor=query.cursor)
        return ArticleList(
            library=str(library.id),
            ref=str(version.ref),
            commit_sha=manifest.commit_sha,
            manifest_id=manifest.id,
            articles=[ArticleSummary.from_model(e) for e in page.items],
            next_cursor=page.next_cursor,
        )


@dataclass(frozen=True, slots=True)
class GetArticleUseCase:
    """Implements ``ports.driving.GetArticle``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, query: GetArticleQuery) -> Article:
        """Read one article of the version's active manifest."""
        ref = VersionRef(query.ref) if query.ref else None
        library, version = await _find_version(self.repository, LibraryId(query.library), ref)
        stored = await self.manifests.get_article(library.id, version.ref, query.path)
        if stored is None:
            raise ArticleNotFoundError(str(library.id), str(version.ref), query.path)
        return Article.from_stored(str(library.id), str(version.ref), stored)


@dataclass(frozen=True, slots=True)
class DiscardPendingManifestsUseCase:
    """Implements ``ports.driving.DiscardPendingManifests``."""

    manifests: ManifestRepository

    async def __call__(self, command: DiscardPendingManifestsCommand) -> DiscardedManifests:
        """Delete the pending manifest(s); active and superseded ones are never touched."""
        manifest_id = None if command.manifest_id is None else ManifestId(command.manifest_id)
        return DiscardedManifests(count=await self.manifests.discard_pending(manifest_id))


@dataclass(frozen=True, slots=True)
class CollectGarbageUseCase:
    """Implements ``ports.driving.CollectGarbage``."""

    manifests: ManifestRepository
    clock: Clock

    async def __call__(self, command: CollectGarbageCommand) -> CollectionResult:
        """Delete manifests superseded before the grace period, then contents nobody uses."""
        cutoff = self.clock.now() - timedelta(seconds=command.grace_seconds)
        collected = await self.manifests.collect_garbage(superseded_before=cutoff)
        return CollectionResult.from_model(collected)
