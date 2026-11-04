from collections.abc import Collection
from dataclasses import dataclass

import pytest

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryExcerptIndex,
    InMemorySearchIndex,
)
from exactdocs.retrieval.dtos import SearchDocsQuery
from exactdocs.retrieval.errors import VersionNotIndexedError
from exactdocs.retrieval.models import DocTarget, Excerpt, ManifestStatus
from exactdocs.retrieval.module import RetrievalModule

REACT_19 = DocTarget(library="react", version="19.1")
REACT_18 = DocTarget(library="react", version="18.3")


@dataclass(frozen=True, slots=True)
class FakeIndexedVersions:
    """A test double needs no base class: it only has to match the Protocol's shape."""

    indexed: frozenset[DocTarget]

    async def find_indexed(self, target: DocTarget) -> DocTarget | None:
        canonical = DocTarget(library=target.library.lower(), version=target.version)
        return canonical if canonical in self.indexed else None


class NoManifests:
    """Search does not look at manifests."""

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


@pytest.fixture
def retrieval() -> RetrievalModule:
    index = InMemoryExcerptIndex.of(
        [
            Excerpt(
                text="useActionState(action, initial)", source_url="https://r/19", target=REACT_19
            ),
            Excerpt(
                text="useFormState(action, initial)", source_url="https://r/18", target=REACT_18
            ),
        ]
    )
    chunks = InMemoryChunkRepository()
    return RetrievalModule.build(
        versions=FakeIndexedVersions(frozenset({REACT_19})),
        index=index,
        manifests=NoManifests(),
        chunks=chunks,
        search=InMemorySearchIndex(chunks),
    )


async def test_returns_verbatim_excerpts_only_from_the_requested_version(
    retrieval: RetrievalModule,
) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library="react", version="19.1", query="action")
    )

    assert [(e.text, e.version) for e in result.excerpts] == [
        ("useActionState(action, initial)", "19.1")
    ]


async def test_never_falls_back_to_another_version(retrieval: RetrievalModule) -> None:
    with pytest.raises(VersionNotIndexedError):
        await retrieval.search_docs(SearchDocsQuery(library="react", version="18.3", query="x"))


async def test_a_library_spelled_in_another_case_searches_the_same_data(
    retrieval: RetrievalModule,
) -> None:
    exact = await retrieval.search_docs(
        SearchDocsQuery(library="react", version="19.1", query="action")
    )
    mixed = await retrieval.search_docs(
        SearchDocsQuery(library="React", version="19.1", query="action")
    )

    assert mixed == exact
    assert mixed.excerpts
