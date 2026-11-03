from dataclasses import dataclass
from typing import Self

from exactdocs.bootstrap.bridges import CatalogIndexedVersions
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.adapters.driven.memory import InMemoryLibraryRepository
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.adapters.driven.memory import InMemoryExcerptIndex


@dataclass(frozen=True, slots=True, kw_only=True)
class Container:
    """Every domain module, wired. Built once per process."""

    settings: Settings
    catalog: CatalogModule
    retrieval: RetrievalModule

    @classmethod
    def build(cls, settings: Settings) -> Self:
        """Choose driven adapters and connect domains through bridges."""
        catalog = CatalogModule.build(repository=InMemoryLibraryRepository.demo())
        retrieval = RetrievalModule.build(
            versions=CatalogIndexedVersions(catalog.get_library),
            index=InMemoryExcerptIndex(),
        )
        return cls(settings=settings, catalog=catalog, retrieval=retrieval)
