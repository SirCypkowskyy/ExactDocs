"""The versions list gets retrieval's chunk counts for the whole page in one call (#513)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from exactdocs.bootstrap.version_counts import ListVersionsWithChunks
from exactdocs.catalog.dtos import ListedVersion, ListVersionsQuery, VersionList
from exactdocs.catalog.models import RefKind
from exactdocs.retrieval.dtos import CountVersionChunksQuery, VersionChunkCounts, VersionChunksOut

LIBRARY = "/acme/payments"


def _version(ref: str, articles: int) -> ListedVersion:
    return ListedVersion(
        ref=ref,
        kind=RefKind.TAG,
        commit_sha="a" * 40,
        imported_at=datetime(2026, 11, 24, tzinfo=UTC),
        is_default=False,
        articles=articles,
    )


@dataclass
class _Catalog:
    versions: list[ListedVersion]

    async def __call__(self, query: ListVersionsQuery) -> VersionList:
        return VersionList(
            library=query.id.lower(), versions=self.versions, next_cursor=None, total=99
        )


@dataclass
class _Retrieval:
    counts: dict[str, VersionChunksOut]
    asked: list[CountVersionChunksQuery] = field(default_factory=list)

    async def __call__(self, query: CountVersionChunksQuery) -> VersionChunkCounts:
        self.asked.append(query)
        return VersionChunkCounts(
            versions={r: c for r, c in self.counts.items() if r in query.refs}
        )


async def test_the_page_gets_every_versions_chunk_counts_in_one_call() -> None:
    page = [_version(f"v{n}", n) for n in range(1, 31)]
    retrieval = _Retrieval(
        {f"v{n}": VersionChunksOut(chunks=2 * n, embedded_chunks=n) for n in range(1, 31)}
    )
    listed = await ListVersionsWithChunks(
        list_versions=_Catalog(page), count_version_chunks=retrieval
    )(ListVersionsQuery(id="/Acme/Payments"))

    assert [q.model_dump() for q in retrieval.asked] == [
        {"library": LIBRARY, "refs": [f"v{n}" for n in range(1, 31)]}
    ]
    assert [(v.ref, v.articles, v.chunks, v.embedded_chunks) for v in listed.versions][:2] == [
        ("v1", 1, 2, 1),
        ("v2", 2, 4, 2),
    ]
    assert (listed.library, listed.total) == (LIBRARY, 99)


async def test_a_version_retrieval_does_not_answer_for_keeps_no_chunk() -> None:
    retrieval = _Retrieval({"v1": VersionChunksOut(chunks=4, embedded_chunks=0)})
    listed = await ListVersionsWithChunks(
        list_versions=_Catalog([_version("v1", 2), _version("v2", 1)]),
        count_version_chunks=retrieval,
    )(ListVersionsQuery(id=LIBRARY))

    assert [(v.ref, v.chunks, v.embedded_chunks) for v in listed.versions] == [
        ("v1", 4, 0),
        ("v2", 0, 0),
    ]


async def test_an_empty_page_asks_retrieval_nothing() -> None:
    retrieval = _Retrieval({})
    listed = await ListVersionsWithChunks(
        list_versions=_Catalog([]), count_version_chunks=retrieval
    )(ListVersionsQuery(id=LIBRARY))

    assert (listed.versions, retrieval.asked) == ([], [])
