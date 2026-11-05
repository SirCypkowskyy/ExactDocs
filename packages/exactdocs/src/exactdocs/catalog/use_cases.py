"""Catalog use cases. Each one satisfies a driving port structurally, without inheriting it."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import uuid4

from exactdocs.catalog.dtos import (
    ActivatedManifest,
    ActivateManifestCommand,
    ActiveManifest,
    ApplyManualTagsCommand,
    ApplyReadmeCommand,
    Article,
    ArticleInfo,
    ArticleList,
    ArticleSummary,
    Asset,
    CollectGarbageCommand,
    CollectionResult,
    CreateLibraryCommand,
    DefaultManifest,
    DefaultManifests,
    DiscardedManifests,
    DiscardLibraryCommand,
    DiscardPendingManifestsCommand,
    GetActiveManifestQuery,
    GetArticleQuery,
    GetAssetQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
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
    RenameDirection,
    RenamedPath,
    RenameList,
    ResolvedVersion,
    ResolveRenamedPathQuery,
    ResolveVersionQuery,
    RetaggedManifest,
    SetManualTagsCommand,
    StoredManifest,
    StoreManifestCommand,
    TagCount,
    TagList,
    UpdateLibraryCommand,
)
from exactdocs.catalog.errors import (
    ArticleNotFoundError,
    AssetNotFoundError,
    ConflictingContentError,
    ConflictingImageError,
    LibraryNotEmptyError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    MAX_RENAMES,
    ContentKey,
    HostKind,
    Library,
    LibraryId,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestImage,
    ManifestRename,
    ManualTags,
    ParsedId,
    StoredImage,
    TagRule,
    Version,
    VersionRef,
    close_paths,
)
from exactdocs.catalog.ports.driven import LibraryRepository, ManifestRepository
from exactdocs_kernel import Clock, decode_cursor, encode_cursor, paginate, section_link

# A missing article lists at most this many paths to look for close matches.
MAX_SUGGESTION_SCAN = 10_000


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
class CreateLibraryUseCase:
    """Implements ``ports.driving.CreateLibrary``."""

    repository: LibraryRepository

    async def __call__(self, command: CreateLibraryCommand) -> LibraryDetail:
        """Store a new library without versions; the repository refuses a taken ID."""
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
            ),
        )
        await self.repository.add(library)
        return LibraryDetail.from_model(library)


@dataclass(frozen=True, slots=True)
class UpdateLibraryUseCase:
    """Implements ``ports.driving.UpdateLibrary``."""

    repository: LibraryRepository

    async def __call__(self, command: UpdateLibraryCommand) -> LibraryDetail:
        """Change the given fields and remember that a user chose them."""
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


@dataclass(frozen=True, slots=True)
class PinDefaultVersionUseCase:
    """Implements ``ports.driving.PinDefaultVersion``."""

    repository: LibraryRepository

    async def __call__(self, command: PinDefaultVersionCommand) -> LibraryDetail:
        """Pin the version the ref names (stored by its exact ref), or unpin without a ref."""
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


@dataclass(frozen=True, slots=True)
class ApplyReadmeUseCase:
    """Implements ``ports.driving.ApplyReadme``."""

    repository: LibraryRepository

    async def __call__(self, command: ApplyReadmeCommand) -> None:
        """Follow the default version's README for every field a user has not edited.

        The README of any other version is ignored. No heading means the repository name as
        title, no paragraph means no description, so a field never keeps text a README dropped.

        Only the two text columns are written, in one statement that keeps edited fields, so a
        concurrent user edit survives. The caller does not retry: if this fails the library keeps
        its old text until the default version is imported again.
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
        )


@dataclass(frozen=True, slots=True)
class DiscardLibraryUseCase:
    """Implements ``ports.driving.DiscardLibrary``."""

    repository: LibraryRepository

    async def __call__(self, command: DiscardLibraryCommand) -> None:
        """Remove the library if it exists and has no versions."""
        library = await self.repository.get(LibraryId(command.id))
        if library is None:
            return
        if library.versions:
            raise LibraryNotEmptyError(str(library.id))
        await self.repository.delete(library.id)


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
        manifest, contents, images = await asyncio.to_thread(self._build, command, library_id)
        await self.manifests.add(
            manifest, contents, images=images, version_must_exist=command.must_exist
        )
        return StoredManifest.from_model(manifest)

    def _build(
        self, command: StoreManifestCommand, library_id: LibraryId
    ) -> tuple[Manifest, dict[ContentKey, str], dict[str, StoredImage]]:
        """Build the manifest and its texts: CPU-bound for a big version, so run in a thread."""
        manifest = Manifest(
            id=ManifestId(uuid4().hex),
            library=library_id,
            ref=VersionRef(command.ref),
            kind=command.kind,
            commit_sha=command.commit_sha,
            created_at=self.clock.now(),
            renames=tuple(
                ManifestRename(
                    from_ref=VersionRef(r.from_ref),
                    old_path=r.old_path,
                    new_path=r.new_path,
                    similarity=r.similarity,
                )
                for r in command.renames
            ),
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


@dataclass(frozen=True, slots=True)
class ManualTagger:
    """Brings a manifest's manual tags in line with the ones users set for its library."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def apply(
        self, manifest: Manifest, by_path: Mapping[str, tuple[str, ...]]
    ) -> RetaggedManifest:
        """Give the manifest's entries the manual tags that reach them (see ``ManualTags``)."""
        origins = await self._origins(manifest) if by_path else {}
        wanted = ManualTags.reaching(origins, by_path)
        touched = await self.manifests.set_manual_tags(manifest.id, wanted)
        return RetaggedManifest.of(manifest.id, touched)

    async def _origins(self, manifest: Manifest) -> dict[str, set[str]]:
        """Map each path git saw renamed into ``manifest`` to every older path it came from.

        A rename names the version it came from; that version's own rename map is followed in
        turn, so a path is traced back across several versions (each step at most once).
        """
        into: dict[ManifestId, dict[str, list[ManifestRename]]] = {}
        previous: dict[VersionRef, Manifest | None] = {}

        async def renamed_into(m: Manifest) -> dict[str, list[ManifestRename]]:
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


@dataclass(frozen=True, slots=True)
class SetManualTagsUseCase:
    """Implements ``ports.driving.SetManualTags``."""

    repository: LibraryRepository
    tagger: ManualTagger

    async def __call__(self, command: SetManualTagsCommand) -> ManualTagsOut:
        """Store the path's tags, then re-tag every pending and active manifest of the library."""
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


@dataclass(frozen=True, slots=True)
class ApplyManualTagsUseCase:
    """Implements ``ports.driving.ApplyManualTags``."""

    manifests: ManifestRepository
    tagger: ManualTagger

    async def __call__(self, command: ApplyManualTagsCommand) -> RetaggedManifest:
        """Re-tag the manifest from its library's manual tags as they are now."""
        manifest = await self.manifests.get(ManifestId(command.manifest_id))
        if manifest is None:
            raise ManifestNotFoundError(command.manifest_id)
        by_path = await self.tagger.repository.get_manual_tags(manifest.library)
        return await self.tagger.apply(manifest, by_path)


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
            tags=query.tag_filter.selection(),
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


async def _renames_manifest(
    repository: LibraryRepository, manifests: ManifestRepository, library: str, ref: str | None
) -> tuple[str, str, ManifestId]:
    """Return ``(library, ref, manifest ID)`` of the version whose renames are asked for."""
    found, version = await _find_version(
        repository, LibraryId(library), VersionRef(ref) if ref else None
    )
    manifest = await manifests.get_active(found.id, version.ref)
    if manifest is None:
        raise ArticleNotFoundError(str(found.id), str(version.ref), None)
    return str(found.id), str(version.ref), manifest.id


@dataclass(frozen=True, slots=True)
class ResolveRenamedPathUseCase:
    """Implements ``ports.driving.ResolveRenamedPath``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, query: ResolveRenamedPathQuery) -> RenamedPath | None:
        """Look the path up in the renames stored with the version's active manifest."""
        library, ref, manifest = await _renames_manifest(
            self.repository, self.manifests, query.library, query.ref
        )
        find = (
            self.manifests.find_rename_to
            if query.direction is RenameDirection.BACK
            else self.manifests.find_rename
        )
        rename = await find(manifest, query.path)
        return None if rename is None else RenamedPath.from_model(library, ref, rename)


@dataclass(frozen=True, slots=True)
class ListRenamesUseCase:
    """Implements ``ports.driving.ListRenames``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, query: ListRenamesQuery) -> RenameList:
        """List the renames stored with the version's active manifest."""
        library, ref, manifest = await _renames_manifest(
            self.repository, self.manifests, query.library, query.ref
        )
        renames = await self.manifests.list_renames(manifest, limit=MAX_RENAMES)
        return RenameList(renames=[RenamedPath.from_model(library, ref, r) for r in renames])


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
        return Article.with_content(info, stored.content)

    async def _close(self, library: Library, version: Version, path: str) -> list[str]:
        """Paths of this version an agent may have meant (only looked up on a miss)."""
        manifest = await self.manifests.get_active(library.id, version.ref)
        if manifest is None:
            return []
        paths = await self.manifests.list_paths(manifest.id, limit=MAX_SUGGESTION_SCAN)
        # difflib is CPU-bound: keep it off the event loop so a miss cannot stall other requests.
        return await asyncio.to_thread(close_paths, path, paths)


@dataclass(frozen=True, slots=True)
class GetAssetUseCase:
    """Implements ``ports.driving.GetAsset``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, query: GetAssetQuery) -> Asset:
        """Read one image of the version's active manifest."""
        ref = VersionRef(query.ref) if query.ref else None
        library, version = await _find_version(self.repository, LibraryId(query.library), ref)
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


MAX_TAG_FACETS = 100


@dataclass(frozen=True, slots=True)
class ListTagsUseCase:
    """Implements ``ports.driving.ListTags``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, query: ListTagsQuery) -> TagList:
        """Count the tags of the version's active manifest."""
        ref = VersionRef(query.ref) if query.ref else None
        library, version = await _find_version(self.repository, LibraryId(query.library), ref)
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
        )


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


@dataclass(frozen=True, slots=True)
class GetManifestStatesUseCase:
    """Implements ``ports.driving.GetManifestStates``."""

    manifests: ManifestRepository

    async def __call__(self, query: GetManifestStatesQuery) -> ManifestStates:
        """Look each ID up; unknown ones are left out."""
        found = await self.manifests.get_many(
            [ManifestId(i) for i in dict.fromkeys(query.manifest_ids)]
        )
        return ManifestStates(states={i: m.state for i, m in found.items()})
        return ManifestStates(states={m.id: m.state for m in found if m is not None})


@dataclass(frozen=True, slots=True)
class GetActiveManifestUseCase:
    """Implements ``ports.driving.GetActiveManifest``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, query: GetActiveManifestQuery) -> ActiveManifest:
        """Name the version's active manifest; unknown library or version raise not-found."""
        ref = VersionRef(query.ref) if query.ref else None
        library, version = await _find_version(self.repository, LibraryId(query.library), ref)
        manifest = await self.manifests.get_active(library.id, version.ref)
        return ActiveManifest(
            library=str(library.id),
            ref=str(version.ref),
            commit_sha=version.commit_sha if manifest is None else manifest.commit_sha,
            manifest_id=None if manifest is None else manifest.id,
        )


@dataclass(frozen=True, slots=True)
class ListDefaultManifestsUseCase:
    """Implements ``ports.driving.ListDefaultManifests``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self) -> DefaultManifests:
        """Take every library's default version (one read) and its active manifest (batched)."""
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


@dataclass(frozen=True, slots=True)
class RemoveVersionUseCase:
    """Implements ``ports.driving.RemoveVersion``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, command: RemoveVersionCommand) -> Removal:
        """Delete the version and its manifests; report which version is the default now."""
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


@dataclass(frozen=True, slots=True)
class RemoveLibraryUseCase:
    """Implements ``ports.driving.RemoveLibrary``."""

    repository: LibraryRepository
    manifests: ManifestRepository

    async def __call__(self, command: RemoveLibraryCommand) -> Removal:
        """Delete the library with its versions and manifests."""
        library = await self.repository.get(LibraryId(command.library))
        if library is None:
            raise LibraryNotFoundError(command.library)
        removed = await self.manifests.remove_library(library.id)
        return Removal(
            library=str(library.id), ref=None, manifest_ids=list(removed), default_ref=None
        )
