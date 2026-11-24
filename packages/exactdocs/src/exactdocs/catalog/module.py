"""Wiring of the catalog domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Self

from exactdocs.catalog.constants import SCAN_PAGE
from exactdocs.catalog.models import (
    Access,
    LibraryId,
    ManifestEntry,
    ManifestId,
    ManifestInstruction,
    TagSelection,
    VersionRef,
)
from exactdocs.catalog.ports.driven import (
    AccessPolicy,
    ArticleCounts,
    ArticleTitleFinder,
    EntrySearch,
    ImportedTagWriter,
    InstructionFileReader,
    LibraryRepository,
    ManifestCopier,
    ManifestRepository,
    StoredArticleFinder,
)
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
    GetAsset,
    GetInstructionFiles,
    GetLibrary,
    GetManifestStates,
    GetVersionTags,
    IsLibraryIdTaken,
    ListArticles,
    ListDefaultManifests,
    ListLibraries,
    ListRenames,
    ListTags,
    ListVersions,
    PinDefaultVersion,
    RemoveLibrary,
    RemoveVersion,
    ReplaceRenames,
    ResolveRenamedPath,
    ResolveVersion,
    SetImportedTags,
    SetLibrarySettings,
    SetManualTags,
    StoreManifest,
    UpdateLibrary,
)
from exactdocs.catalog.use_cases import (
    ActivateManifestUseCase,
    ApplyManualTagsUseCase,
    ApplyReadmeUseCase,
    CollectGarbageUseCase,
    CopyManifestUseCase,
    CreateLibraryUseCase,
    DiscardLibraryUseCase,
    DiscardPendingManifestsUseCase,
    FindStoredArticlesUseCase,
    GetActiveManifestUseCase,
    GetArticleTitlesUseCase,
    GetArticleUseCase,
    GetAssetUseCase,
    GetInstructionFilesUseCase,
    GetLibraryUseCase,
    GetManifestStatesUseCase,
    GetVersionTagsUseCase,
    IsLibraryIdTakenUseCase,
    ListArticlesUseCase,
    ListDefaultManifestsUseCase,
    ListLibrariesUseCase,
    ListRenamesUseCase,
    ListTagsUseCase,
    ListVersionsUseCase,
    ManualTagger,
    PinDefaultVersionUseCase,
    RemoveLibraryUseCase,
    RemoveVersionUseCase,
    ReplaceRenamesUseCase,
    ResolveRenamedPathUseCase,
    ResolveVersionUseCase,
    SetImportedTagsUseCase,
    SetLibrarySettingsUseCase,
    SetManualTagsUseCase,
    StoreManifestUseCase,
    UpdateLibraryUseCase,
)
from exactdocs_kernel import Clock, Sort, SortValue, SystemClock, is_after


class _NoInstructions:
    """The default ``instruction_files`` of ``build``: no manifest keeps any."""

    async def list_instructions(self, manifest_id: ManifestId) -> Sequence[ManifestInstruction]:
        """Keep none.

        Args:
            manifest_id: The manifest.

        Returns:
            Nothing.
        """
        del manifest_id
        return ()


class _EveryoneMayDoAnything:
    """The default ``access`` of ``build``: no roles, as in a local process the owner runs."""

    async def can_create(self, library: str | None = None) -> bool:
        """Allow creation by internal callers.

        Args:
            library: The proposed ID, if known.

        Returns:
            Always True.
        """
        del library
        return True

    async def allows(self, library: str, access: Access) -> bool:
        """Allow everything.

        Args:
            library: The library.
            access: The role the action needs.

        Returns:
            Always ``True``.
        """
        del library, access
        return True

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        """Allow reading every library.

        Args:
            libraries: Library IDs.

        Returns:
            All of them, lower-case.
        """
        return frozenset(library.casefold() for library in libraries)

    async def claim(self, library: str) -> None:
        """Record nobody as the creator.

        Args:
            library: The library ID.
        """
        del library

    async def forget(self, library: str) -> None:
        """Forget nothing: nothing was recorded.

        Args:
            library: The library ID.
        """
        del library


@dataclass(frozen=True, slots=True, kw_only=True)
class _ScannedArticleCounts:
    """The default ``article_counts`` of ``build``: reads each version's entries (for tests)."""

    manifests: ManifestRepository
    """Where the entries are read from."""

    async def count_articles(
        self, versions: Sequence[tuple[LibraryId, VersionRef]]
    ) -> Mapping[tuple[LibraryId, VersionRef], int]:
        """Count the entries of these versions' active manifests, one version at a time.

        Args:
            versions: The versions, as ``(library, ref)``.

        Returns:
            The number of entries of each version's active manifest.
        """
        found: dict[tuple[LibraryId, VersionRef], int] = {}
        entries = _ScannedEntries(manifests=self.manifests)
        for version, manifest in (await self.manifests.get_active_many(versions)).items():
            found[version] = await entries.count(
                manifest.id, prefix="", tags=TagSelection(), text=None
            )
        return found


@dataclass(frozen=True, slots=True, kw_only=True)
class _ScannedEntries:
    """The default ``entry_search`` of ``build``: reads every entry and sorts them in memory."""

    manifests: ManifestRepository
    """Where the entries are read from."""

    async def _all(
        self, manifest_id: ManifestId, prefix: str, tags: TagSelection, text: str | None
    ) -> list[ManifestEntry]:
        """Read the entries that pass the filters.

        Args:
            manifest_id: The manifest.
            prefix: Only paths inside this directory; empty: every path.
            tags: Only entries that pass this filter.
            text: Only entries whose path or title contains this text, any case.

        Returns:
            The entries, sorted by path.
        """
        found: list[ManifestEntry] = []
        after: str | None = None
        needle = text.lower() if text else None
        while page := await self.manifests.list_entries(
            manifest_id, prefix=prefix, tags=tags, after=after, limit=SCAN_PAGE
        ):
            found += [
                e
                for e in page
                if needle is None or needle in e.path.lower() or needle in e.title.lower()
            ]
            after = page[-1].path
        return found

    async def search(
        self,
        manifest_id: ManifestId,
        *,
        prefix: str,
        tags: TagSelection,
        text: str | None,
        sort: Sort,
        after: tuple[SortValue, str] | None,
        limit: int,
    ) -> Sequence[ManifestEntry]:
        """Return up to ``limit`` filtered entries in ``sort`` order, after the ``after`` key.

        Args:
            manifest_id: The manifest.
            prefix: Only paths inside this directory; empty: every path.
            tags: Only entries that pass this filter.
            text: Only entries whose path or title contains this text, any case.
            sort: The order.
            after: The sort value and path of the last entry of the previous page.
            limit: The most entries returned.

        Returns:
            The entries in order.
        """

        def value(entry: ManifestEntry) -> SortValue:
            """Return the entry's value of the sort field.

            Args:
                entry: The entry.

            Returns:
                Its path, lower-cased title or size.
            """
            return {"path": entry.path, "title": entry.title.lower(), "size": entry.size}[
                sort.field
            ]

        ordered = sorted(
            await self._all(manifest_id, prefix, tags, text),
            key=lambda e: (value(e), e.path),
            reverse=sort.descending,
        )
        if after is not None:
            ordered = [e for e in ordered if is_after((value(e), e.path), after, sort=sort)]
        return ordered[:limit]

    async def count(
        self, manifest_id: ManifestId, *, prefix: str, tags: TagSelection, text: str | None
    ) -> int:
        """Count the entries that ``search`` pages over.

        Args:
            manifest_id: The manifest.
            prefix: Only paths inside this directory; empty: every path.
            tags: Only entries that pass this filter.
            text: Only entries whose path or title contains this text, any case.

        Returns:
            How many entries match.
        """
        return len(await self._all(manifest_id, prefix, tags, text))


class _NoTitles:
    """The default ``article_titles`` of ``build``: no title is known."""

    async def titles(self, manifest_id: str, paths: Collection[str]) -> Mapping[str, str]:
        """Know no title.

        Args:
            manifest_id: The manifest.
            paths: The article paths.

        Returns:
            Nothing.
        """
        del manifest_id, paths
        return {}


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogModule:
    """The catalog's driving ports, ready to be exposed by driving adapters."""

    list_libraries: ListLibraries
    """List a page of libraries and their indexed versions."""
    create_library: CreateLibrary
    """Add a library without versions."""
    discard_library: DiscardLibrary
    """Remove a library that has no versions yet (the undo of ``CreateLibrary``)."""
    is_library_id_taken: IsLibraryIdTaken
    """Probe a proposed ID for an authorized creator without granting read access."""
    get_library: GetLibrary
    """Fetch one library; raises ``LibraryNotFoundError`` when it is missing."""
    resolve_version: ResolveVersion
    """Resolve a context7-style ID to the one version it names."""
    resolve_renamed_path: ResolveRenamedPath
    """Follow a path across the renames git detected when the version was imported."""
    list_renames: ListRenames
    """List every rename stored with a version (same errors as ``ResolveRenamedPath``)."""
    store_manifest: StoreManifest
    """Store a version's articles as a pending manifest; nothing changes for readers yet."""
    activate_manifest: ActivateManifest
    """Make a pending manifest what its version serves, all at once."""
    list_versions: ListVersions
    """Lists a library's versions, filtered and sorted."""
    list_articles: ListArticles
    """List the articles of a version (default version without a ref), sorted by path."""
    list_tags: ListTags
    """Count the tags of a version's articles (default version without a ref), most used first."""
    get_article: GetArticle
    """Read one article of a version (default version without a ref)."""
    get_asset: GetAsset
    """Read one image of a version (default version without a ref)."""
    discard_pending_manifests: DiscardPendingManifests
    """Delete the pending manifests that match the command's filters (never "all")."""
    collect_garbage: CollectGarbage
    """Delete manifests superseded longer ago than the grace period, and unused contents."""
    get_manifest_states: GetManifestStates
    """Tell whether manifests are pending, active or superseded, for domains that hold their IDs."""
    get_article_titles: GetArticleTitles
    """Titles of a manifest's articles by path, for other domains (embedding input)."""
    get_active_manifest: GetActiveManifest
    """Name the manifest that serves a version, for domains that hold manifest IDs."""
    get_instruction_files: GetInstructionFiles
    """The instruction files kept with a manifest, for other domains (agentic retrieval)."""
    list_default_manifests: ListDefaultManifests
    """Name the active manifest of every library's default version, in one call."""
    update_library: UpdateLibrary
    """Set a library's title and/or description by hand; later README imports keep them."""
    pin_default_version: PinDefaultVersion
    """Pin the library's default version to an imported one, or unpin it (LIB-10)."""
    apply_readme: ApplyReadme
    """Take title and description from the README of a just-imported version."""
    remove_version: RemoveVersion
    """Remove a version: it and its manifests are gone at once, in one transaction."""
    remove_library: RemoveLibrary
    """Remove a library with all its versions and manifests, in one transaction."""
    set_manual_tags: SetManualTags
    """Set the tags a user gives an article path by hand, for every version of the library."""
    apply_manual_tags: ApplyManualTags
    """Give a manifest the manual tags its library has now (before it is activated)."""
    set_library_settings: SetLibrarySettings
    """Replace a library's paths and tag rules, and its chunking unless it is left out."""
    get_version_tags: GetVersionTags
    """Name a version's active manifest with each article's path, front matter and imported tags."""
    set_imported_tags: SetImportedTags
    """Replace the imported tags of articles of a manifest in one transaction (manual ones stay)."""
    find_stored_articles: FindStoredArticles
    """Return what the library's manifests hold for these files: same path, blob and version."""
    replace_renames: ReplaceRenames
    """Replace the rename map of a version's active manifest and re-tag from the new map."""
    copy_manifest: CopyManifest
    """Copy a version's active manifest into a new pending one, with its articles' stored text."""

    @classmethod
    def build(
        cls,
        *,
        repository: LibraryRepository,
        manifests: ManifestRepository,
        imported_tags: ImportedTagWriter,
        stored_articles: StoredArticleFinder,
        copier: ManifestCopier,
        clock: Clock | None = None,
        article_titles: ArticleTitleFinder | None = None,
        instruction_files: InstructionFileReader | None = None,
        access: AccessPolicy | None = None,
        entry_search: EntrySearch | None = None,
        article_counts: ArticleCounts | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        ``imported_tags`` rewrites the imported tags of the manifests ``manifests`` stores,
        ``copier`` copies them and ``stored_articles`` finds their articles by what they were
        imported from. ``article_titles`` looks titles up by path for other domains and
        confirms a path followed across versions; without it none are known (and no such path
        is confirmed). ``instruction_files`` reads the instruction files ``manifests``
        stores; without it none are read.

        Args:
            repository: Stores the libraries, their versions, settings and manual tags.
            manifests: Stores the manifests with their articles, images and renames.
            imported_tags: Rewrites the imported tags of stored manifests.
            stored_articles: Finds stored articles by path and blob SHA.
            copier: Copies a version's active manifest.
            clock: Tells the time; the system clock by default.
            article_titles: Looks article titles up by path; none are known without it.
            instruction_files: Reads the instruction files kept with a manifest; none without it.
            access: Library roles: what the caller may do with a library; everything without it.
            entry_search: Filters, sorts and pages entries in the store; without it every entry is
                read through ``manifests`` and sorted in memory (for tests).
            article_counts: Counts many versions' articles at once; without it each version's
                entries are read through ``manifests`` (for tests).

        Returns:
            The module, every driving port wired.
        """
        clock = clock or SystemClock()
        access = access or _EveryoneMayDoAnything()
        titles = article_titles or _NoTitles()
        tagger = ManualTagger(repository=repository, manifests=manifests)
        counts = article_counts or _ScannedArticleCounts(manifests=manifests)
        return cls(
            list_libraries=ListLibrariesUseCase(
                repository=repository, articles=counts, access=access
            ),
            create_library=CreateLibraryUseCase(repository=repository, access=access),
            discard_library=DiscardLibraryUseCase(repository=repository, access=access),
            is_library_id_taken=IsLibraryIdTakenUseCase(repository=repository, access=access),
            get_library=GetLibraryUseCase(repository=repository, access=access),
            resolve_version=ResolveVersionUseCase(repository=repository, access=access),
            resolve_renamed_path=ResolveRenamedPathUseCase(
                repository=repository,
                manifests=manifests,
                titles=titles,
                access=access,
            ),
            list_renames=ListRenamesUseCase(
                repository=repository, manifests=manifests, access=access
            ),
            store_manifest=StoreManifestUseCase(
                repository=repository, manifests=manifests, clock=clock
            ),
            activate_manifest=ActivateManifestUseCase(
                repository=repository, manifests=manifests, clock=clock
            ),
            list_versions=ListVersionsUseCase(
                repository=repository, articles=counts, access=access
            ),
            list_articles=ListArticlesUseCase(
                repository=repository,
                manifests=manifests,
                entries=entry_search or _ScannedEntries(manifests=manifests),
                access=access,
            ),
            list_tags=ListTagsUseCase(repository=repository, manifests=manifests, access=access),
            get_article=GetArticleUseCase(
                repository=repository, manifests=manifests, access=access
            ),
            get_asset=GetAssetUseCase(repository=repository, manifests=manifests, access=access),
            discard_pending_manifests=DiscardPendingManifestsUseCase(
                manifests=manifests, clock=clock
            ),
            collect_garbage=CollectGarbageUseCase(manifests=manifests, clock=clock),
            get_manifest_states=GetManifestStatesUseCase(manifests=manifests),
            get_article_titles=GetArticleTitlesUseCase(titles=titles),
            get_active_manifest=GetActiveManifestUseCase(
                repository=repository, manifests=manifests
            ),
            get_instruction_files=GetInstructionFilesUseCase(
                reader=instruction_files or _NoInstructions()
            ),
            list_default_manifests=ListDefaultManifestsUseCase(
                repository=repository, manifests=manifests
            ),
            update_library=UpdateLibraryUseCase(repository=repository, access=access),
            pin_default_version=PinDefaultVersionUseCase(repository=repository, access=access),
            apply_readme=ApplyReadmeUseCase(repository=repository),
            remove_version=RemoveVersionUseCase(
                repository=repository, manifests=manifests, access=access
            ),
            remove_library=RemoveLibraryUseCase(
                repository=repository, manifests=manifests, access=access
            ),
            set_manual_tags=SetManualTagsUseCase(repository=repository, tagger=tagger),
            apply_manual_tags=ApplyManualTagsUseCase(manifests=manifests, tagger=tagger),
            set_library_settings=SetLibrarySettingsUseCase(repository=repository, access=access),
            get_version_tags=GetVersionTagsUseCase(repository=repository, manifests=manifests),
            set_imported_tags=SetImportedTagsUseCase(manifests=manifests, writer=imported_tags),
            find_stored_articles=FindStoredArticlesUseCase(finder=stored_articles),
            replace_renames=ReplaceRenamesUseCase(
                repository=repository, manifests=manifests, tagger=tagger
            ),
            copy_manifest=CopyManifestUseCase(repository=repository, copier=copier, clock=clock),
        )
