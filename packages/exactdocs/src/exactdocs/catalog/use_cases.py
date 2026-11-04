"""Catalog use cases. Each one satisfies a driving port structurally, without inheriting it."""

from dataclasses import dataclass, replace
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
    ConflictingContentError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    ContentKey,
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
from exactdocs_kernel import Clock, decode_cursor, encode_cursor, paginate


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
                            content_version=a.content_version,
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
        contents: dict[ContentKey, str] = {}
        for a in command.articles:
            if contents.setdefault((a.blob_sha, a.content_version), a.content) != a.content:
                raise ConflictingContentError(a.blob_sha)
        await self.manifests.add(manifest, contents)
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
        after = decode_cursor(query.cursor) if query.cursor is not None else None
        entries = await self.manifests.list_entries(
            manifest.id,
            prefix=query.path_prefix.strip("/"),
            after=after,
            limit=query.limit + 1,  # one more than asked tells whether another page follows
        )
        page = entries[: query.limit]
        return ArticleList(
            library=str(library.id),
            ref=str(version.ref),
            commit_sha=manifest.commit_sha,
            manifest_id=manifest.id,
            articles=[ArticleSummary.from_model(e) for e in page],
            next_cursor=encode_cursor(page[-1].path) if len(entries) > query.limit else None,
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
    clock: Clock

    async def __call__(self, command: DiscardPendingManifestsCommand) -> DiscardedManifests:
        """Delete the pending manifest(s); active and superseded ones are never touched."""
        older = command.older_than_seconds
        count = await self.manifests.discard_pending(
            manifest_id=None if command.manifest_id is None else ManifestId(command.manifest_id),
            library_id=None if command.library is None else LibraryId(command.library),
            created_before=None if older is None else self.clock.now() - timedelta(seconds=older),
        )
        return DiscardedManifests(count=count)


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
