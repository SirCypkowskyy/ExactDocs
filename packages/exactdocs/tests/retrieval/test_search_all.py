"""SearchAllLibraries: one ranking over every library's default version, with counts per library."""

from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemorySearchIndex,
)
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand, SearchAllQuery
from exactdocs.retrieval.errors import EmptySearchTextError, VersionNotIndexedError
from exactdocs.retrieval.models import (
    CatalogLibrary,
    DocTarget,
    ManifestStatus,
    SearchableVersion,
    SourceHost,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.use_cases import LOOKUP_BATCH, MAX_SEARCHED_LIBRARIES


@dataclass(slots=True)
class Versions:
    """``find(library, None)`` is the default version, ``find(library, ref)`` any of them."""

    known: dict[tuple[str, str], SearchableVersion] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)
    calls: int = 0

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        self.calls += 1
        ref = ref or self.defaults.get(library)
        return self.known.get((library, ref or ""))


def lib(id_: str, default: str | None = "v1") -> CatalogLibrary:
    return CatalogLibrary(
        id=id_,
        title=id_,
        description="",
        source_url="https://github.com/x/y",
        default_version=default,
        versions=(default,) if default else (),
        version_count=1 if default else 0,
    )


def chunk(heading: str, content: str) -> ChunkIn:
    return ChunkIn(
        heading_path=["Guide", heading],
        occurrence_index=0,
        content=content,
        content_hash=f"h-{heading}",
        anchor=heading.lower(),
    )


@dataclass(slots=True)
class Fixture:
    retrieval: RetrievalModule
    versions: Versions
    libraries: list[CatalogLibrary]

    async def add(
        self, library: str, ref: str, articles: dict[str, list[ChunkIn]], *, default: bool = True
    ) -> None:
        manifest = f"{library}@{ref}"
        sha = f"{len(self.versions.known):040d}"
        self.versions.known[library, ref] = SearchableVersion(
            library=library,
            version=ref,
            manifest_id=manifest,
            commit_sha=sha,
            repository_url="https://github.com/x/y",
            host=SourceHost.GITHUB,
        )
        if default:
            self.versions.defaults[library] = ref
            if not any(item.id == library for item in self.libraries):
                self.libraries.append(lib(library, ref))
        await self.retrieval.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest,
                library=library,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(path=path, blob_sha=f"blob-{path}-{ref}", chunks=chunks)
                    for path, chunks in articles.items()
                ],
            )
        )


@pytest.fixture
def world() -> Fixture:
    chunks = InMemoryChunkRepository()
    versions = Versions()
    libraries = list[CatalogLibrary]()

    class Live:
        async def all(self) -> list[CatalogLibrary]:
            return list(libraries)

    module = RetrievalModule.build(
        libraries=Live(),
        searchable=versions,
        manifests=_Manifests(),
        chunks=chunks,
        search=InMemorySearchIndex(chunks),
    )
    return Fixture(module, versions, libraries)


class _Manifests:
    async def active_id(self, target: DocTarget) -> None:
        del target

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


async def test_results_name_their_library_and_version_with_counts_per_library(
    world: Fixture,
) -> None:
    await world.add("/a/one", "v2", {"a.md": [chunk("Tokens", "A token expires.")]})
    await world.add(
        "/b/two", "v1", {"b.md": [chunk("Auth", "Send the token."), chunk("X", "token")]}
    )

    found = await world.retrieval.search_all_libraries(SearchAllQuery(query="token"))

    assert {(r.library, r.version) for r in found.results} == {("/a/one", "v2"), ("/b/two", "v1")}
    assert [(f.library, f.version, f.matches) for f in found.libraries] == [
        ("/b/two", "v1", 2),
        ("/a/one", "v2", 1),
    ]
    assert (found.libraries_searched, found.libraries_omitted) == (2, 0)
    assert found.coverage.complete
    assert all(
        r.commit_sha == world.versions.known[r.library, r.version].commit_sha for r in found.results
    )


async def test_a_version_that_is_not_the_default_never_answers(world: Fixture) -> None:
    await world.add(
        "/a/one", "v1", {"a.md": [chunk("Old", "Only the legacy_flag is old.")]}, default=False
    )
    await world.add("/a/one", "v2", {"a.md": [chunk("New", "Nothing about it.")]})

    found = await world.retrieval.search_all_libraries(SearchAllQuery(query="legacy_flag"))

    assert (found.results, found.libraries) == ([], [])


async def test_library_narrows_the_results_but_not_the_counts(world: Fixture) -> None:
    await world.add("/a/one", "v1", {"a.md": [chunk("T", "token token")]})
    await world.add("/b/two", "v1", {"b.md": [chunk("T", "token")]})

    found = await world.retrieval.search_all_libraries(
        SearchAllQuery(query="token", library="/b/two")
    )

    assert {r.library for r in found.results} == {"/b/two"}
    assert {f.library for f in found.libraries} == {"/a/one", "/b/two"}


async def test_an_unknown_library_is_not_found_never_a_wider_search(world: Fixture) -> None:
    await world.add("/a/one", "v1", {"a.md": [chunk("T", "token")]})

    with pytest.raises(VersionNotIndexedError):
        await world.retrieval.search_all_libraries(SearchAllQuery(query="token", library="/x/y"))


async def test_content_shared_by_two_libraries_answers_for_both(world: Fixture) -> None:
    same = {"a.md": [chunk("T", "token")]}
    await world.add("/a/one", "v1", same)
    await world.add("/b/two", "v1", same)

    found = await world.retrieval.search_all_libraries(SearchAllQuery(query="token"))

    assert sorted(r.library for r in found.results) == ["/a/one", "/b/two"]
    assert found.results[0].score == found.results[1].score
    assert len({r.chunk_id for r in found.results}) == 2  # each library has its own chunk IDs


async def test_the_limit_cuts_the_results_not_the_counts(world: Fixture) -> None:
    await world.add("/a/one", "v1", {f"{i}.md": [chunk(f"T{i}", "token")] for i in range(5)})

    found = await world.retrieval.search_all_libraries(SearchAllQuery(query="token", limit=2))

    assert len(found.results) == 2
    assert not found.coverage.complete
    assert found.libraries[0].matches == 5


async def test_libraries_without_a_readable_default_are_skipped(world: Fixture) -> None:
    await world.add("/a/one", "v1", {"a.md": [chunk("T", "token")]})
    world.libraries.append(lib("/ghost/lib"))  # the catalog lists it, no active manifest

    found = await world.retrieval.search_all_libraries(SearchAllQuery(query="token"))

    assert found.libraries_searched == 1


async def test_many_libraries_are_looked_up_in_batches_and_capped(world: Fixture) -> None:
    world.libraries.extend(lib(f"/o/l{i:04d}") for i in range(MAX_SEARCHED_LIBRARIES + 3))

    found = await world.retrieval.search_all_libraries(SearchAllQuery(query="token"))

    assert world.versions.calls == MAX_SEARCHED_LIBRARIES
    assert found.libraries_omitted == 3
    assert MAX_SEARCHED_LIBRARIES % LOOKUP_BATCH == 0


async def test_blank_text_and_bad_input_are_refused(world: Fixture) -> None:
    with pytest.raises(EmptySearchTextError):
        await world.retrieval.search_all_libraries(SearchAllQuery(query="   "))
    with pytest.raises(ValidationError):
        SearchAllQuery(query="x", library="not an id")
    assert SearchAllQuery(query="x", library=" ").library is None


async def test_a_library_beyond_the_cap_is_searched_and_no_longer_counted_as_omitted(
    world: Fixture,
) -> None:
    last = f"/o/l{MAX_SEARCHED_LIBRARIES + 2:04d}"
    world.libraries.extend(lib(f"/o/l{i:04d}") for i in range(1, MAX_SEARCHED_LIBRARIES + 2))
    for library in ("/o/l0000", last):
        await world.add(library, "v1", {"a.md": [chunk("T", "token")]})

    found = await world.retrieval.search_all_libraries(SearchAllQuery(query="token", library=last))

    assert [r.library for r in found.results] == [last]
    assert {f.library for f in found.libraries} == {"/o/l0000", last}
    assert (found.libraries_searched, found.libraries_omitted) == (2, 2)
