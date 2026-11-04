"""Wiring of the catalog domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from dataclasses import dataclass
from typing import Self

from exactdocs.catalog.ports.driven import LibraryRepository, ManifestRepository
from exactdocs.catalog.ports.driving import (
    ActivateManifest,
    ApplyReadme,
    CollectGarbage,
    CreateLibrary,
    DiscardLibrary,
    DiscardPendingManifests,
    GetActiveManifest,
    GetArticle,
    GetLibrary,
    GetManifestStates,
    ListArticles,
    ListLibraries,
    ListTags,
    RemoveLibrary,
    RemoveVersion,
    ResolveRenamedPath,
    ResolveVersion,
    StoreManifest,
    UpdateLibrary,
)
from exactdocs.catalog.use_cases import (
    ActivateManifestUseCase,
    ApplyReadmeUseCase,
    CollectGarbageUseCase,
    CreateLibraryUseCase,
    DiscardLibraryUseCase,
    DiscardPendingManifestsUseCase,
    GetActiveManifestUseCase,
    GetArticleUseCase,
    GetLibraryUseCase,
    GetManifestStatesUseCase,
    ListArticlesUseCase,
    ListLibrariesUseCase,
    ListTagsUseCase,
    RemoveLibraryUseCase,
    RemoveVersionUseCase,
    ResolveRenamedPathUseCase,
    ResolveVersionUseCase,
    StoreManifestUseCase,
    UpdateLibraryUseCase,
)
from exactdocs_kernel import Clock, SystemClock


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogModule:
    """The catalog's driving ports, ready to be exposed by driving adapters."""

    list_libraries: ListLibraries
    create_library: CreateLibrary
    discard_library: DiscardLibrary
    get_library: GetLibrary
    resolve_version: ResolveVersion
    resolve_renamed_path: ResolveRenamedPath
    store_manifest: StoreManifest
    activate_manifest: ActivateManifest
    list_articles: ListArticles
    list_tags: ListTags
    get_article: GetArticle
    discard_pending_manifests: DiscardPendingManifests
    collect_garbage: CollectGarbage
    get_manifest_states: GetManifestStates
    get_active_manifest: GetActiveManifest
    update_library: UpdateLibrary
    apply_readme: ApplyReadme
    remove_version: RemoveVersion
    remove_library: RemoveLibrary

    @classmethod
    def build(
        cls,
        *,
        repository: LibraryRepository,
        manifests: ManifestRepository,
        clock: Clock | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters."""
        clock = clock or SystemClock()
        return cls(
            list_libraries=ListLibrariesUseCase(repository),
            create_library=CreateLibraryUseCase(repository),
            discard_library=DiscardLibraryUseCase(repository),
            get_library=GetLibraryUseCase(repository),
            resolve_version=ResolveVersionUseCase(repository),
            resolve_renamed_path=ResolveRenamedPathUseCase(repository, manifests),
            store_manifest=StoreManifestUseCase(repository, manifests, clock),
            activate_manifest=ActivateManifestUseCase(repository, manifests, clock),
            list_articles=ListArticlesUseCase(repository, manifests),
            list_tags=ListTagsUseCase(repository, manifests),
            get_article=GetArticleUseCase(repository, manifests),
            discard_pending_manifests=DiscardPendingManifestsUseCase(manifests, clock),
            collect_garbage=CollectGarbageUseCase(manifests, clock),
            get_manifest_states=GetManifestStatesUseCase(manifests),
            get_active_manifest=GetActiveManifestUseCase(repository, manifests),
            update_library=UpdateLibraryUseCase(repository),
            apply_readme=ApplyReadmeUseCase(repository),
            remove_version=RemoveVersionUseCase(repository, manifests),
            remove_library=RemoveLibraryUseCase(repository, manifests),
        )
