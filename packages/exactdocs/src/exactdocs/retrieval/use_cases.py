from dataclasses import dataclass

from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult
from exactdocs.retrieval.errors import VersionNotIndexedError
from exactdocs.retrieval.models import DocTarget, SearchText
from exactdocs.retrieval.ports.driven import ExcerptIndex, IndexedVersions


@dataclass(frozen=True, slots=True)
class SearchDocsUseCase:
    """Implements ``ports.driving.SearchDocs``."""

    versions: IndexedVersions
    index: ExcerptIndex

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
        """Search one exact version; never fall back to another version."""
        target = DocTarget(library=query.library, version=query.version)
        if not await self.versions.is_indexed(target):
            raise VersionNotIndexedError(target.library, target.version)
        excerpts = await self.index.search(target, SearchText(value=query.query), query.limit)
        return SearchDocsResult.from_models(excerpts)
