from dataclasses import dataclass
from typing import Self

from exactdocs.retrieval.ports.driven import ExcerptIndex, IndexedVersions
from exactdocs.retrieval.ports.driving import SearchDocs
from exactdocs.retrieval.use_cases import SearchDocsUseCase


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalModule:
    """Retrieval's driving ports, ready to be exposed by driving adapters."""

    search_docs: SearchDocs

    @classmethod
    def build(cls, *, versions: IndexedVersions, index: ExcerptIndex) -> Self:
        """Assemble the use cases around the given driven adapters."""
        return cls(search_docs=SearchDocsUseCase(versions, index))
