"""Wiring of the catalog domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from dataclasses import dataclass
from typing import Self

from exactdocs.catalog.ports.driven import LibraryRepository, ManifestRepository
from exactdocs.catalog.ports.driving import (
    ActivateManifest,
    CollectGarbage,
    DiscardPendingManifests,
    GetActiveManifest,
    GetArticle,
    GetLibrary,
    GetManifestStates,
    ListArticles,
    ListLibraries,
    ResolveVersion,
    StoreManifest,
)
from exactdocs.catalog.use_cases import (
    ActivateManifestUseCase,
    CollectGarbageUseCase,
    DiscardPendingManifestsUseCase,
    GetActiveManifestUseCase,
    GetArticleUseCase,
    GetLibraryUseCase,
    GetManifestStatesUseCase,
    ListArticlesUseCase,
    ListLibrariesUseCase,
    ResolveVersionUseCase,
    StoreManifestUseCase,
)
from exactdocs_kernel import Clock, SystemClock


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogModule:
    """The catalog's driving ports, ready to be exposed by driving adapters."""

    list_libraries: ListLibraries
    get_library: GetLibrary
    resolve_version: ResolveVersion
    store_manifest: StoreManifest
    activate_manifest: ActivateManifest
    list_articles: ListArticles
    get_article: GetArticle
    discard_pending_manifests: DiscardPendingManifests
    collect_garbage: CollectGarbage
    get_manifest_states: GetManifestStates
    get_active_manifest: GetActiveManifest

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
            get_library=GetLibraryUseCase(repository),
            resolve_version=ResolveVersionUseCase(repository),
            store_manifest=StoreManifestUseCase(repository, manifests, clock),
            activate_manifest=ActivateManifestUseCase(repository, manifests, clock),
            list_articles=ListArticlesUseCase(repository, manifests),
            get_article=GetArticleUseCase(repository, manifests),
            discard_pending_manifests=DiscardPendingManifestsUseCase(manifests, clock),
            collect_garbage=CollectGarbageUseCase(manifests, clock),
            get_manifest_states=GetManifestStatesUseCase(manifests),
            get_active_manifest=GetActiveManifestUseCase(repository, manifests),
        )
