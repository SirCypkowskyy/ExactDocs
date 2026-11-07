"""Adapters that connect one domain's driven port to another domain's driving port.

This is how domains talk to each other without importing each other: the consumer declares a
port in its own language, and a bridge here translates to the provider's public use case.
"""

import asyncio
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from exactdocs.bootstrap.constants import STATUSES
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ApplyManualTagsCommand,
    ApplyReadmeCommand,
    ArticleIn,
    CollectGarbageCommand,
    CopyManifestCommand,
    CreateLibraryCommand,
    DiscardLibraryCommand,
    DiscardPendingManifestsCommand,
    FindStoredArticlesQuery,
    GetActiveManifestQuery,
    GetArticleQuery,
    GetArticleTitlesQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
    GetVersionTagsQuery,
    HostKind,
    ImageIn,
    ListLibrariesQuery,
    ListRenamesQuery,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RenameIn,
    ReplaceRenamesCommand,
    ResolveRenamedPathQuery,
    SetImportedTagsCommand,
    SetLibrarySettingsCommand,
    SetManualTagsCommand,
    StoredFileIn,
    StoreManifestCommand,
    TagRuleIn,
)
from exactdocs.catalog.dtos import (
    ArticleTags as CatalogArticleTags,
)
from exactdocs.catalog.dtos import (
    ChunkingIn as CatalogChunkingIn,
)
from exactdocs.catalog.dtos import (
    RefKind as CatalogRefKind,
)
from exactdocs.catalog.dtos import (
    Removal as CatalogRemoval,
)
from exactdocs.catalog.dtos import (
    VersionOrigin as CatalogVersionOrigin,
)
from exactdocs.catalog.errors import ArticleNotFoundError as CatalogArticleNotFoundError
from exactdocs.catalog.errors import StoredContentOutdatedError
from exactdocs.catalog.ports.driving import (
    ActivateManifest,
    ApplyManualTags,
    ApplyReadme,
    CollectGarbage,
    CopyManifest,
    CreateLibrary,
    DiscardLibrary,
    DiscardPendingManifests,
    FindStoredArticles,
    GetActiveManifest,
    GetArticle,
    GetArticleTitles,
    GetLibrary,
    GetManifestStates,
    GetVersionTags,
    ListDefaultManifests,
    ListLibraries,
    ListRenames,
    RemoveLibrary,
    RemoveVersion,
    ReplaceRenames,
    ResolveRenamedPath,
    SetImportedTags,
    SetLibrarySettings,
    SetManualTags,
    StoreManifest,
)
from exactdocs.ingestion.constants import PARSER_VERSION
from exactdocs.ingestion.errors import EmbeddingUnavailableError, StoredTextOutdatedError
from exactdocs.ingestion.models import (
    ArticleChunk,
    ChunkHeading,
    ChunkingConfig,
    Collected,
    CopiedArticle,
    CopiedVersion,
    EmbeddedBatch,
    EmbedPlan,
    GitRename,
    ImportedRef,
    ImportedVersion,
    ImportSource,
    NewLibrary,
    PathSelection,
    ProposedId,
    RefKind,
    Removed,
    RepositoryUrl,
    StoredArticle,
    StoredArticleTags,
    StoredTags,
    TaggedPath,
    TagRule,
    VersionOrigin,
    VersionToEmbed,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ArticleTagsIn,
    ChunkHeadingIn,
    ChunkIn,
    CollectChunksCommand,
    DiscardPendingChunksCommand,
    EmbedBatchCommand,
    EmbedVersionCommand,
    FinishEmbeddingCommand,
    ForgetLibraryCommand,
    GetChunkSetsQuery,
    IndexManifestCommand,
    RemoveChunksCommand,
    RetagArticlesCommand,
    UnembeddedVersionsQuery,
)
from exactdocs.retrieval.errors import EmbeddingFailedError
from exactdocs.retrieval.models import (
    CatalogLibrary,
    DocTarget,
    ManifestPaths,
    ManifestStatus,
    SearchableVersion,
    SourceHost,
)
from exactdocs.retrieval.ports.driving import (
    CollectChunks,
    DiscardPendingChunks,
    EmbedBatch,
    FinishEmbedding,
    ForgetLibrary,
    GetChunkSets,
    IndexManifest,
    ListUnembeddedVersions,
    PlanEmbedding,
    RemoveChunks,
    RetagArticles,
)
from exactdocs_kernel import MAX_LIMIT, NotFoundError, ValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogSearchableVersions:
    """Implements ``retrieval.ports.driven.SearchableVersions`` using the catalog."""

    get_library: GetLibrary
    get_active_manifest: GetActiveManifest

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        """Resolve the exact ref (the default version without one) and name its active manifest.

        The manifest answer carries the commit, so the ref, the manifest and the commit come
        from one catalog call and cannot disagree.
        """
        try:
            active = await self.get_active_manifest(
                GetActiveManifestQuery(library=library, ref=ref)
            )
            if ref is not None and active.ref != ref:  # a short SHA does not count
                return None
            detail = await self.get_library(GetLibraryQuery(id=active.library))
        except NotFoundError, ValidationError:  # e.g. a ref git would not accept
            return None
        if active.manifest_id is None:
            return None
        return SearchableVersion(
            library=active.library,
            version=active.ref,
            manifest_id=active.manifest_id,
            commit_sha=active.commit_sha,
            repository_url=detail.source_url,
            host=SourceHost(detail.host.value),
            rules=tuple(detail.rules),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogDefaultVersions:
    """Implements ``retrieval.ports.driven.DefaultVersions`` using the catalog."""

    list_default_manifests: ListDefaultManifests

    async def all(self) -> Sequence[SearchableVersion]:
        """Name every library's default version with an active manifest, in one catalog call."""
        found = await self.list_default_manifests()
        return [
            SearchableVersion(
                library=m.library,
                version=m.ref,
                manifest_id=m.manifest_id,
                commit_sha=m.commit_sha,
                repository_url=m.source_url,
                host=SourceHost(m.host.value),
            )
            for m in found.manifests
        ]


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLibraries:
    """Implements ``retrieval.ports.driven.Libraries`` using the catalog."""

    list_libraries: ListLibraries
    get_library: GetLibrary
    """Spells a library ID as the catalog stores it."""

    async def canonical_id(self, library: str) -> str | None:
        """Ask the catalog for the library.

        Args:
            library: The ID in any letter case.

        Returns:
            The ID as the catalog spells it, or ``None`` when it has no such library.
        """
        try:
            return (await self.get_library(GetLibraryQuery(id=library))).id
        except NotFoundError, ValidationError:
            return None

    async def all(self) -> Sequence[CatalogLibrary]:
        """Read every page of the catalog's list, skipping libraries with no default version."""
        found: list[CatalogLibrary] = []
        cursor = None
        while True:
            page = await self.list_libraries(ListLibrariesQuery(limit=MAX_LIMIT, cursor=cursor))
            found += [
                CatalogLibrary(
                    id=lib.id,
                    title=lib.title,
                    description=lib.description,
                    source_url=lib.source_url,
                    default_version=lib.default_version,
                    versions=tuple(r.ref for r in lib.refs),
                    version_count=lib.version_count,
                    last_imported_at=lib.last_imported_at,
                )
                for lib in page.libraries
                if lib.default_version is not None
            ]
            cursor = page.next_cursor
            if cursor is None:
                return found


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLibraryIds:
    """Implements ``ingestion.ports.driven.LibraryIds`` using the catalog."""

    get_library: GetLibrary

    async def is_taken(self, library_id: ProposedId) -> bool:
        """Tell whether a library with this ID is in the catalog."""
        try:
            await self.get_library(GetLibraryQuery(id=library_id))
        except NotFoundError:
            return False
        return True


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogActiveManifests:
    """Implements ``retrieval.ports.driven.ActiveManifests`` using the catalog."""

    get_active_manifest: GetActiveManifest
    get_manifest_states: GetManifestStates

    async def active_id(self, target: DocTarget) -> str | None:
        """Return the manifest the catalog serves for this version, or ``None`` when it has none."""
        try:
            found = await self.get_active_manifest(
                GetActiveManifestQuery(library=target.library, ref=target.version)
            )
        except NotFoundError:
            return None
        return found.manifest_id

    async def statuses(self, manifest_ids: Collection[str]) -> Mapping[str, ManifestStatus]:
        """Ask the catalog; IDs it does not know are left out."""
        found = await self.get_manifest_states(
            GetManifestStatesQuery(manifest_ids=list(manifest_ids))
        )
        return {i: STATUSES.get(state, ManifestStatus.OTHER) for i, state in found.states.items()}


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogRenamedPaths:
    """Implements ``retrieval.ports.driven.RenamedPaths`` using the catalog."""

    resolve_renamed_path: ResolveRenamedPath

    async def new_path(self, target: DocTarget, old_path: str) -> str | None:
        """Follow the rename map of the active manifest; ``None`` when nothing is known."""
        try:
            found = await self.resolve_renamed_path(
                ResolveRenamedPathQuery(library=target.library, ref=target.version, path=old_path)
            )
        except NotFoundError:
            return None
        return None if found is None else found.new_path


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogArticleSuggestions:
    """Implements ``retrieval.ports.driven.ArticleSuggestions`` with ``read_article``'s matches."""

    get_article: GetArticle
    """The catalog's article read; its miss carries the close paths."""

    async def close_to(self, target: DocTarget, path: str) -> Sequence[str]:
        """Ask the catalog for the article and keep the close matches of its miss.

        Args:
            target: The exact library version.
            path: The path retrieval has no chunks for.

        Returns:
            The catalog's close matches; empty when it finds the article or knows nothing.
        """
        try:
            await self.get_article(
                GetArticleQuery(library=target.library, ref=target.version, path=path)
            )
        except CatalogArticleNotFoundError as missing:
            return missing.close_matches
        except NotFoundError:
            return ()
        return ()  # the catalog has it but retrieval has no chunks: no path to suggest


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogNewLibraries:
    """Implements ``ingestion.ports.driven.NewLibraries`` using the catalog."""

    create_library: CreateLibrary
    discard_library: DiscardLibrary

    async def add(self, library: NewLibrary) -> str:
        """Create the library in the catalog; return its canonical ID."""
        created = await self.create_library(
            CreateLibraryCommand(
                id=library.library_id,
                title=library.title,
                source_url=library.source_url,
                host=HostKind(library.host.value),
                default_branch=library.default_branch,
                include_paths=list(library.selection.include),
                exclude_paths=list(library.selection.exclude),
                tag_rules=[TagRuleIn(pattern=r.pattern, tag=r.tag) for r in library.tag_rules],
            )
        )
        return created.id

    async def discard(self, library_id: str) -> None:
        """Remove the library from the catalog again."""
        await self.discard_library(DiscardLibraryCommand(id=library_id))


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLibrarySources:
    """Implements ``ingestion.ports.driven.LibrarySources`` using the catalog."""

    get_library: GetLibrary
    list_renames: ListRenames

    async def renames_of(self, library: str, ref: str) -> list[GitRename]:
        """Return the rename map the version serves; empty when it has none or is unknown."""
        try:
            found = await self.list_renames(ListRenamesQuery(library=library, ref=ref))
        except NotFoundError:
            return []
        return [
            GitRename(old_path=r.old_path, new_path=r.new_path, similarity=r.similarity)
            for r in found.renames
        ]

    async def get(self, library: str) -> ImportSource:
        """Read the library's repository, selection and tag rules; ``NotFoundError`` if unknown."""
        detail = await self.get_library(GetLibraryQuery(id=library))
        settings = detail.settings
        chunking = settings.chunking
        return ImportSource(
            url=RepositoryUrl.parse(detail.source_url),
            selection=PathSelection.of(settings.include_paths, settings.exclude_paths),
            tag_rules=TagRule.many([(r.pattern, r.tag) for r in settings.tag_rules]),
            chunking=ChunkingConfig(
                split_depth=chunking.split_level,
                min_chars=chunking.min_chars,
                max_chars=chunking.max_chars,
                chunker=chunking.chunker,
            ),
        )

    async def imported_versions(self, library: str) -> list[ImportedRef]:
        """Return the versions: kind, commit, origin and whether it is the pinned default."""
        detail = await self.get_library(GetLibraryQuery(id=library))
        return [
            ImportedRef(
                ref=v.ref,
                kind=RefKind(v.kind.value),
                commit_sha=v.commit_sha,
                origin=VersionOrigin(v.origin.value),
                pinned=detail.default_pinned and v.is_default,
            )
            for v in detail.versions
        ]


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogVersionPublisher:
    """Implements ``ingestion.ports.driven.VersionPublisher`` using the catalog."""

    store_manifest: StoreManifest
    activate_manifest: ActivateManifest
    discard_pending_manifests: DiscardPendingManifests
    apply_readme: ApplyReadme
    apply_manual_tags_to: ApplyManualTags
    replace_renames_of: ReplaceRenames

    async def store(self, version: ImportedVersion) -> str:
        """Store the articles as a pending manifest."""
        command = await asyncio.to_thread(_store_command, version)
        stored = await self.store_manifest(command)
        return stored.manifest_id

    async def activate(self, manifest_id: str) -> None:
        """Make the manifest what its version serves."""
        await self.activate_manifest(ActivateManifestCommand(manifest_id=manifest_id))

    async def apply_manual_tags(self, manifest_id: str) -> dict[str, tuple[str, ...]]:
        """Give the pending manifest its library's manual tags."""
        found = await self.apply_manual_tags_to(ApplyManualTagsCommand(manifest_id=manifest_id))
        return {a.path: tuple(a.tags) for a in found.articles}

    async def replace_renames(
        self, library: str, ref: str, *, from_ref: str, renames: Sequence[GitRename]
    ) -> dict[str, dict[str, tuple[str, ...]]]:
        """Give the version's active manifest the new map; empty when it serves none."""
        try:
            found = await self.replace_renames_of(
                ReplaceRenamesCommand(
                    library=library,
                    ref=ref,
                    renames=[
                        RenameIn(
                            from_ref=from_ref,
                            old_path=r.old_path,
                            new_path=r.new_path,
                            similarity=r.similarity,
                        )
                        for r in renames
                    ],
                )
            )
        except NotFoundError:
            return {}
        return {m.manifest_id: {a.path: tuple(a.tags) for a in m.articles} for m in found.retagged}

    async def describe(
        self,
        *,
        library: str,
        ref: str,
        title: str | None,
        description: str | None,
        rules: Sequence[str],
    ) -> None:
        """Offer the version's text and rules to the catalog, which decides whether they apply."""
        await self.apply_readme(
            ApplyReadmeCommand(
                library=library, ref=ref, title=title, description=description, rules=list(rules)
            )
        )

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete one pending manifest, or the library's pending manifests."""
        await self.discard_pending_manifests(
            DiscardPendingManifestsCommand(
                manifest_id=manifest_id, library=None if manifest_id else library
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalChunkIndex:
    """Implements ``ingestion.ports.driven.ChunkIndex`` using retrieval."""

    index_manifest: IndexManifest
    get_chunk_sets: GetChunkSets
    discard_pending_chunks: DiscardPendingChunks
    remove_chunks: RemoveChunks
    retag_articles: RetagArticles

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        """Read back the chunks stored for these blobs."""
        found = await self.get_chunk_sets(
            GetChunkSetsQuery(config_hash=config_hash, blob_shas=list(blob_shas))
        )
        return {
            sha: tuple(
                ArticleChunk(
                    heading_path=tuple(c.heading_path),
                    occurrence_index=c.occurrence_index,
                    position=position,
                    content=c.content,
                    content_hash=c.content_hash,
                    anchor=c.anchor,
                    code_languages=tuple(c.code_languages),
                    headings=None
                    if c.headings is None
                    else tuple(
                        ChunkHeading(
                            heading_path=tuple(h.heading_path),
                            anchor=h.anchor,
                            starts_chunk=h.starts_chunk,
                        )
                        for h in c.headings
                    ),
                )
                for position, c in enumerate(chunks)
            )
            for sha, chunks in found.chunks.items()
        }

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        """Store and index the chunks of the pending manifest."""
        command = await asyncio.to_thread(_index_command, manifest_id, version)
        await self.index_manifest(command)

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete one pending manifest's chunks, or the library's pending chunks."""
        await self.discard_pending_chunks(
            DiscardPendingChunksCommand(
                manifest_id=manifest_id, library=None if manifest_id else library
            )
        )

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        """Delete the chunks of manifests the catalog has just deleted."""
        await self.remove_chunks(RemoveChunksCommand(manifest_ids=list(manifest_ids)))

    async def retag(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> None:
        """Copy the articles' tags onto their chunk rows."""
        await self.retag_articles(
            RetagArticlesCommand(
                manifest_id=manifest_id,
                articles=[ArticleTagsIn(path=p, tags=list(t)) for p, t in tags.items()],
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalVersionEmbedder:
    """Implements ``ingestion.ports.driven.VersionEmbedder`` using retrieval."""

    plan_embedding: PlanEmbedding
    """Retrieval's plan of a version's embedding."""
    embed_batch_of: EmbedBatch
    """Retrieval's batch of a version's embedding."""
    finish_embedding: FinishEmbedding
    """Retrieval's switch of spaces."""
    list_unembedded_versions: ListUnembeddedVersions
    """Retrieval's list of versions not fully embedded."""

    async def plan(self, library: str, ref: str) -> EmbedPlan:
        """Pick the version's space and count what is missing.

        Args:
            library: The library ID.
            ref: The version.

        Returns:
            The plan.
        """
        plan = await self.plan_embedding(EmbedVersionCommand(library=library, ref=ref))
        return EmbedPlan(
            space_id=plan.space_id,
            manifest_id=plan.manifest_id,
            missing=plan.missing,
            created=plan.created,
            skipped=None if plan.skipped is None else plan.skipped.value,
        )

    async def embed_batch(self, library: str, ref: str, plan: EmbedPlan) -> EmbeddedBatch:
        """Embed the next batch of the plan's manifest.

        Args:
            library: The library ID.
            ref: The version.
            plan: The job's plan.

        Returns:
            What the batch embedded.
        """
        if plan.space_id is None or plan.manifest_id is None:
            return EmbeddedBatch(embedded=0, finished=True)
        command = EmbedBatchCommand(
            library=library, ref=ref, manifest_id=plan.manifest_id, space_id=plan.space_id
        )
        try:
            batch = await self.embed_batch_of(command)
        except EmbeddingFailedError as error:
            if error.transient:  # the job tries the batch again, after a wait
                raise EmbeddingUnavailableError(str(error)) from error
            raise
        return EmbeddedBatch(embedded=batch.embedded, finished=batch.finished)

    async def finish(self, plan: EmbedPlan) -> None:
        """Switch to the plan's space once it covers every version.

        Args:
            plan: The job's plan.
        """
        if plan.space_id is not None:
            await self.finish_embedding(FinishEmbeddingCommand(space_id=plan.space_id))

    async def unembedded(self, library: str | None) -> Sequence[VersionToEmbed]:
        """Name the versions not fully embedded.

        Args:
            library: Only this library's; every library's when ``None``.

        Returns:
            The versions.
        """
        found = await self.list_unembedded_versions(UnembeddedVersionsQuery(library=library))
        return [VersionToEmbed(library=v.library, ref=v.ref) for v in found.versions]


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogManualTags:
    """Implements ``ingestion.ports.driven.ManualTagStore`` using the catalog."""

    set_manual_tags: SetManualTags

    async def set_tags(self, library: str, path: str, tags: Sequence[str]) -> TaggedPath:
        """Store the path's manual tags; the catalog re-tags its manifests and says which."""
        done = await self.set_manual_tags(
            SetManualTagsCommand(library=library, path=path, tags=list(tags))
        )
        return TaggedPath(
            library=done.library,
            path=done.path,
            tags=tuple(done.tags),
            retagged={
                m.manifest_id: {a.path: tuple(a.tags) for a in m.articles} for m in done.retagged
            },
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLibrarySettings:
    """Implements ``ingestion.ports.driven.LibrarySettingsStore`` using the catalog."""

    set_library_settings: SetLibrarySettings

    async def save(
        self,
        library: str,
        selection: PathSelection,
        tag_rules: Sequence[TagRule],
        chunking: ChunkingConfig,
    ) -> None:
        """Store the paths, tag rules and chunking on the library."""
        await self.set_library_settings(
            SetLibrarySettingsCommand(
                id=library,
                include_paths=list(selection.include),
                exclude_paths=list(selection.exclude),
                tag_rules=[TagRuleIn(pattern=r.pattern, tag=r.tag) for r in tag_rules],
                chunking=CatalogChunkingIn(
                    split_level=chunking.split_depth,
                    min_chars=chunking.min_chars,
                    max_chars=chunking.max_chars,
                    chunker=chunking.chunker,
                ),
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogVersionCopier:
    """Implements ``ingestion.ports.driven.VersionCopier`` using the catalog."""

    copy_manifest: CopyManifest

    async def copy(self, library: str, ref: str, *, content_version: int) -> CopiedVersion | None:
        """Copy the version's active manifest; ``None`` for an unknown or empty version."""
        try:
            copied = await self.copy_manifest(
                CopyManifestCommand(library=library, ref=ref, content_version=content_version)
            )
        except StoredContentOutdatedError as error:
            raise StoredTextOutdatedError(library, ref) from error
        except NotFoundError:
            return None
        return CopiedVersion(
            manifest_id=copied.manifest_id,
            kind=RefKind(copied.kind.value),
            commit_sha=copied.commit_sha,
            articles=tuple(
                CopiedArticle(
                    path=a.path,
                    blob_sha=a.blob_sha,
                    title=a.title,
                    front_matter=a.front_matter,
                    tags=tuple(a.tags),
                    content=a.content,
                )
                for a in copied.articles
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogImportedTags:
    """Implements ``ingestion.ports.driven.ImportedTagStore`` using the catalog."""

    get_version_tags: GetVersionTags
    set_imported_tags_of: SetImportedTags

    async def stored_tags(self, library: str, ref: str) -> StoredTags | None:
        """Read the active manifest's tag sources; ``None`` for an unknown or empty version."""
        try:
            found = await self.get_version_tags(GetVersionTagsQuery(library=library, ref=ref))
        except NotFoundError:
            return None
        if found.manifest_id is None:
            return None
        return StoredTags(
            manifest_id=found.manifest_id,
            articles=tuple(
                StoredArticleTags(path=a.path, front_matter=a.front_matter, tags=tuple(a.tags))
                for a in found.articles
            ),
        )

    async def set_imported_tags(
        self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        """Write the imported tags; return every tag of the articles that changed."""
        done = await self.set_imported_tags_of(
            SetImportedTagsCommand(
                manifest_id=manifest_id,
                articles=[CatalogArticleTags(path=p, tags=list(t)) for p, t in tags.items()],
            )
        )
        return {a.path: tuple(a.tags) for a in done.articles}


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogStoredArticles:
    """Implements ``ingestion.ports.driven.StoredArticleSource`` using the catalog."""

    find_stored_articles: FindStoredArticles

    async def find(
        self, library: str, ref: str, parser_version: int, files: Sequence[tuple[str, str]]
    ) -> list[StoredArticle]:
        """Ask the catalog; the parser version is its content version (see ``_store_command``)."""
        found = await self.find_stored_articles(
            FindStoredArticlesQuery(
                library=library,
                ref=ref,
                content_version=parser_version,
                files=[StoredFileIn(path=path, blob_sha=sha) for path, sha in files],
            )
        )
        return [
            StoredArticle(
                path=a.path,
                blob_sha=a.blob_sha,
                title=a.title,
                front_matter=a.front_matter,
                content=a.content,
            )
            for a in found.articles
        ]


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogRemovals:
    """Implements ``ingestion.ports.driven.Removals`` using the catalog (and retrieval)."""

    version_remover: RemoveVersion
    library_remover: RemoveLibrary
    forget_library: ForgetLibrary
    """Drops retrieval's per-library settings once the catalog has removed the library."""

    async def remove_version(self, library: str, ref: str) -> Removed:
        """Remove the version from the catalog."""
        return _removed(await self.version_remover(RemoveVersionCommand(library=library, ref=ref)))

    async def remove_library(self, library: str) -> Removed:
        """Remove the library from the catalog, then retrieval's settings of it (its mode).

        Retrieval goes second: if it failed, the library would be gone and its leftover row
        harmless until the same ID is added again, never the other way round.

        Args:
            library: The library ID.

        Returns:
            What the catalog removed.
        """
        removed = await self.library_remover(RemoveLibraryCommand(library=library))
        await self.forget_library(ForgetLibraryCommand(library=removed.library))
        return _removed(removed)


def _removed(result: CatalogRemoval) -> Removed:
    return Removed(
        library=result.library,
        ref=result.ref,
        manifest_ids=tuple(result.manifest_ids),
        default_ref=result.default_ref,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogCollector:
    """Implements ``ingestion.ports.driven.Collector`` using the catalog."""

    collect_garbage: CollectGarbage

    async def collect(self, *, grace_seconds: int) -> Collected:
        """Delete superseded manifests past the grace period and the texts nothing uses."""
        done = await self.collect_garbage(CollectGarbageCommand(grace_seconds=grace_seconds))
        return Collected(deleted=done.manifests + done.contents + done.images)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalCollector:
    """Implements ``ingestion.ports.driven.Collector`` using retrieval."""

    collect_chunks: CollectChunks

    async def collect(self, *, grace_seconds: int) -> Collected:
        """Delete chunk rows of manifests the catalog no longer knows, and unused chunk sets.

        The job's grace period keeps superseded *catalog* manifests; the catalog is already
        done with them, so retrieval asks for none beyond its own five minutes of doubt about
        a manifest the catalog has not answered for yet. That also sweeps the rows of a removal
        whose ``RemoveChunks`` failed.
        """
        del grace_seconds
        done = await self.collect_chunks(CollectChunksCommand(grace_seconds=0))
        return Collected(deleted=done.manifests + done.chunk_sets)


def _store_command(version: ImportedVersion) -> StoreManifestCommand:
    """Build the catalog's command (validates every article: off the event loop)."""
    return StoreManifestCommand(
        library=version.library,
        ref=version.ref,
        kind=CatalogRefKind(version.kind.value),
        commit_sha=version.commit_sha,
        must_exist=version.refresh,
        origin=CatalogVersionOrigin(version.origin.value),
        renames=[
            RenameIn(
                from_ref=version.renamed_from,
                old_path=r.old_path,
                new_path=r.new_path,
                similarity=r.similarity,
            )
            for r in version.renames
            if version.renamed_from is not None
        ],
        articles=[
            ArticleIn(
                path=a.path,
                blob_sha=a.blob_sha,
                content_version=PARSER_VERSION,
                title=a.title,
                tags=list(a.tags),
                front_matter=a.front_matter,
                content=a.content,
            )
            for a in version.articles
        ],
        images=[
            ImageIn(path=i.path, blob_sha=i.blob_sha, content_type=i.content_type, data=i.data)  # ty: ignore[invalid-argument-type]
            for i in version.images
        ],
    )


def _index_command(manifest_id: str, version: ImportedVersion) -> IndexManifestCommand:
    """Build retrieval's command (validates every chunk: off the event loop)."""
    return IndexManifestCommand(
        manifest_id=manifest_id,
        library=version.library,
        ref=version.ref,
        config_hash=version.config_hash,
        articles=[
            ArticleChunksIn(
                path=a.path,
                blob_sha=a.blob_sha,
                tags=list(a.tags),
                chunks=[
                    ChunkIn(
                        heading_path=list(c.heading_path),
                        occurrence_index=c.occurrence_index,
                        content=c.content,
                        content_hash=c.content_hash,
                        anchor=c.anchor,
                        code_languages=list(c.code_languages),
                        headings=None
                        if c.headings is None
                        else [
                            ChunkHeadingIn(
                                heading_path=list(h.heading_path),
                                anchor=h.anchor,
                                starts_chunk=h.starts_chunk,
                            )
                            for h in c.headings
                        ],
                    )
                    for c in a.chunks
                ],
            )
            for a in version.articles
        ],
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogArticleTitles:
    """Implements ``retrieval.ports.driven.ArticleTitles`` using the catalog (one query)."""

    get_article_titles: GetArticleTitles
    """The catalog's titles of a manifest's articles, by path."""

    async def titles(self, articles: ManifestPaths) -> Mapping[str, str]:
        """Look the paths up in the manifest's entries.

        Args:
            articles: The manifest and the article paths.

        Returns:
            The titles found (none for a manifest collected meanwhile).
        """
        found = await self.get_article_titles(
            GetArticleTitlesQuery(manifest_id=articles.manifest_id, paths=list(articles.paths))
        )
        return found.titles
