"""Wiring of the catalog domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Self

from exactdocs.catalog.models import ManifestId, ManifestInstruction
from exactdocs.catalog.ports.driven import (
    ArticleTitleFinder,
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
    ListArticles,
    ListDefaultManifests,
    ListLibraries,
    ListRenames,
    ListTags,
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
    ListArticlesUseCase,
    ListDefaultManifestsUseCase,
    ListLibrariesUseCase,
    ListRenamesUseCase,
    ListTagsUseCase,
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
from exactdocs_kernel import Clock, SystemClock


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
    create_library: CreateLibrary
    discard_library: DiscardLibrary
    get_library: GetLibrary
    resolve_version: ResolveVersion
    resolve_renamed_path: ResolveRenamedPath
    list_renames: ListRenames
    store_manifest: StoreManifest
    activate_manifest: ActivateManifest
    list_articles: ListArticles
    list_tags: ListTags
    get_article: GetArticle
    get_asset: GetAsset
    discard_pending_manifests: DiscardPendingManifests
    collect_garbage: CollectGarbage
    get_manifest_states: GetManifestStates
    get_article_titles: GetArticleTitles
    """Titles of a manifest's articles by path, for other domains (embedding input)."""
    get_active_manifest: GetActiveManifest
    get_instruction_files: GetInstructionFiles
    """The instruction files kept with a manifest, for other domains (agentic retrieval)."""
    list_default_manifests: ListDefaultManifests
    update_library: UpdateLibrary
    pin_default_version: PinDefaultVersion
    apply_readme: ApplyReadme
    remove_version: RemoveVersion
    remove_library: RemoveLibrary
    set_manual_tags: SetManualTags
    apply_manual_tags: ApplyManualTags
    set_library_settings: SetLibrarySettings
    get_version_tags: GetVersionTags
    set_imported_tags: SetImportedTags
    find_stored_articles: FindStoredArticles
    replace_renames: ReplaceRenames
    copy_manifest: CopyManifest

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
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        ``imported_tags`` rewrites the imported tags of the manifests ``manifests`` stores,
        ``copier`` copies them and ``stored_articles`` finds their articles by what they were
        imported from. ``article_titles`` looks titles up by path for other domains; without
        it none are known. ``instruction_files`` reads the instruction files ``manifests``
        stores; without it none are read.
        """
        clock = clock or SystemClock()
        tagger = ManualTagger(repository=repository, manifests=manifests)
        return cls(
            list_libraries=ListLibrariesUseCase(repository=repository),
            create_library=CreateLibraryUseCase(repository=repository),
            discard_library=DiscardLibraryUseCase(repository=repository),
            get_library=GetLibraryUseCase(repository=repository),
            resolve_version=ResolveVersionUseCase(repository=repository),
            resolve_renamed_path=ResolveRenamedPathUseCase(
                repository=repository, manifests=manifests
            ),
            list_renames=ListRenamesUseCase(repository=repository, manifests=manifests),
            store_manifest=StoreManifestUseCase(
                repository=repository, manifests=manifests, clock=clock
            ),
            activate_manifest=ActivateManifestUseCase(
                repository=repository, manifests=manifests, clock=clock
            ),
            list_articles=ListArticlesUseCase(repository=repository, manifests=manifests),
            list_tags=ListTagsUseCase(repository=repository, manifests=manifests),
            get_article=GetArticleUseCase(repository=repository, manifests=manifests),
            get_asset=GetAssetUseCase(repository=repository, manifests=manifests),
            discard_pending_manifests=DiscardPendingManifestsUseCase(
                manifests=manifests, clock=clock
            ),
            collect_garbage=CollectGarbageUseCase(manifests=manifests, clock=clock),
            get_manifest_states=GetManifestStatesUseCase(manifests=manifests),
            get_article_titles=GetArticleTitlesUseCase(titles=article_titles or _NoTitles()),
            get_active_manifest=GetActiveManifestUseCase(
                repository=repository, manifests=manifests
            ),
            get_instruction_files=GetInstructionFilesUseCase(
                reader=instruction_files or _NoInstructions()
            ),
            list_default_manifests=ListDefaultManifestsUseCase(
                repository=repository, manifests=manifests
            ),
            update_library=UpdateLibraryUseCase(repository=repository),
            pin_default_version=PinDefaultVersionUseCase(repository=repository),
            apply_readme=ApplyReadmeUseCase(repository=repository),
            remove_version=RemoveVersionUseCase(repository=repository, manifests=manifests),
            remove_library=RemoveLibraryUseCase(repository=repository, manifests=manifests),
            set_manual_tags=SetManualTagsUseCase(repository=repository, tagger=tagger),
            apply_manual_tags=ApplyManualTagsUseCase(manifests=manifests, tagger=tagger),
            set_library_settings=SetLibrarySettingsUseCase(repository=repository),
            get_version_tags=GetVersionTagsUseCase(repository=repository, manifests=manifests),
            set_imported_tags=SetImportedTagsUseCase(manifests=manifests, writer=imported_tags),
            find_stored_articles=FindStoredArticlesUseCase(finder=stored_articles),
            replace_renames=ReplaceRenamesUseCase(
                repository=repository, manifests=manifests, tagger=tagger
            ),
            copy_manifest=CopyManifestUseCase(repository=repository, copier=copier, clock=clock),
        )
