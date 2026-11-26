"""A ref spelled with or without a leading `v` finds its version; a missing one names them (#605).

The version stays a hard filter: only the spelling of a leading `v` is forgiven, only when one
imported version matches, and a ref that names none is an error that never answers from another.
"""

from dataclasses import dataclass, field

import pytest

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ArticleOutlineQuery,
    ChunkIn,
    IndexManifestCommand,
    QueryDocsQuery,
    SearchDocsQuery,
)
from exactdocs.retrieval.errors import VersionNotIndexedError
from exactdocs.retrieval.models import (
    DocTarget,
    KnownVersions,
    ManifestStatus,
    SearchableVersion,
    SourceHost,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs_kernel import respelled_note

LIB = "/encode/starlette"
NOTE = (
    "ref 'v1.10.0' is not imported: read as '1.10.0', the one version it names but for a leading v."
)


def version(ref: str, manifest: str) -> SearchableVersion:
    return SearchableVersion(
        library=LIB,
        version=ref,
        manifest_id=manifest,
        commit_sha="a" * 40,
        repository_url="https://github.com/encode/starlette",
        host=SourceHost.GITHUB,
    )


@dataclass(slots=True)
class FakeVersions:
    """Only the exact ref, as the catalog bridge answers; a ref without a manifest is None."""

    by_ref: dict[str, SearchableVersion]
    default: str

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        return self.by_ref.get(ref or self.default) if library == LIB else None

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


@dataclass(slots=True)
class FakeKnown:
    """The library's imported refs, newest first, indexed or not."""

    versions: tuple[str, ...]
    default: str | None
    asked: list[str] = field(default_factory=list)

    async def of(self, library: str) -> KnownVersions | None:
        self.asked.append(library)
        if library != LIB:
            return None
        return KnownVersions(versions=self.versions, default=self.default)


def chunk(text: str) -> ChunkIn:
    return ChunkIn(
        heading_path=["Routing"],
        occurrence_index=0,
        content=text,
        content_hash=f"h-{text}",
        anchor="routing",
    )


async def build(
    imported: tuple[str, ...] = ("1.10.0", "0.27.0"),
    *,
    indexed: tuple[str, ...] = ("1.10.0", "0.27.0"),
    known: bool = True,
) -> RetrievalModule:
    chunks = InMemoryChunkRepository()
    by_ref = {ref: version(ref, f"m-{ref}") for ref in indexed}
    versions = FakeVersions(by_ref, default=indexed[0])
    index = InMemorySearchIndex(chunks=chunks)
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
        known_versions=FakeKnown(imported, default=imported[0]) if known else None,
    )
    for ref in indexed:
        await module.index_manifest(
            IndexManifestCommand(
                manifest_id=f"m-{ref}",
                library=LIB,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(
                        path="docs/routing.md",
                        blob_sha=f"b-{ref}",
                        chunks=[chunk(f"Mount routes in starlette {ref}.")],
                    )
                ],
            )
        )
    return module


async def test_search_docs_reads_a_ref_with_a_leading_v_as_the_version_without_one() -> None:
    retrieval = await build()

    found = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.10.0", query="mount routes")
    )

    assert found.version == "1.10.0"
    assert found.notes == [NOTE]
    assert [r.snippet for r in found.results] == ["Mount routes in starlette 1.10.0."]
    assert found.model_dump(mode="json")["notes"] == [NOTE]


@pytest.mark.parametrize(("asked", "imported"), [("V1.10.0", "1.10.0"), ("0.27.0", "v0.27.0")])
async def test_either_spelling_finds_the_other(asked: str, imported: str) -> None:
    retrieval = await build((imported,), indexed=(imported,))

    found = await retrieval.search_docs(SearchDocsQuery(library=LIB, ref=asked, query="routes"))

    assert found.version == imported
    assert found.notes == [respelled_note(asked, imported)]


async def test_article_outline_and_query_docs_read_it_the_same_way() -> None:
    retrieval = await build()

    outline = await retrieval.article_outline(
        ArticleOutlineQuery(library=LIB, ref="v1.10.0", path="docs/routing.md")
    )
    docs = await retrieval.query_docs(
        QueryDocsQuery(library_id=f"{LIB}/v1.10.0", query="mount routes")
    )

    assert (outline.version, outline.notes) == ("1.10.0", [NOTE])
    assert (docs.version, docs.notes) == ("1.10.0", [NOTE])
    assert [s.content for s in docs.sections] == ["Mount routes in starlette 1.10.0."]


async def test_a_ref_read_as_given_has_no_notes() -> None:
    retrieval = await build()

    found = await retrieval.search_docs(SearchDocsQuery(library=LIB, ref="1.10.0", query="routes"))
    default = await retrieval.search_docs(SearchDocsQuery(library=LIB, query="routes"))

    assert found.notes == default.notes == []
    assert "notes" not in found.model_dump(mode="json")


async def test_a_ref_that_names_no_version_lists_them_and_answers_from_none() -> None:
    retrieval = await build()

    for search in (
        retrieval.search_docs(SearchDocsQuery(library=LIB, ref="2.0.0", query="routes")),
        retrieval.query_docs(QueryDocsQuery(library_id=f"{LIB}/2.0.0", query="routes")),
        retrieval.article_outline(
            ArticleOutlineQuery(library=LIB, ref="2.0.0", path="docs/routing.md")
        ),
    ):
        with pytest.raises(VersionNotIndexedError) as missing:
            await search
        assert str(missing.value) == (
            "no index for /encode/starlette@2.0.0: version '2.0.0' is not imported; imported "
            "versions (repository refs, not instructions), newest first: '1.10.0', '0.27.0'; "
            "default version: '1.10.0'"
        )
        assert missing.value.versions == ("1.10.0", "0.27.0")


async def test_two_spellings_imported_are_never_guessed() -> None:
    retrieval = await build(("1.0", "V1.0"), indexed=("1.0", "V1.0"))

    with pytest.raises(VersionNotIndexedError, match=r"version 'v1\.0' is not imported"):
        await retrieval.search_docs(SearchDocsQuery(library=LIB, ref="v1.0", query="routes"))


async def test_an_imported_ref_without_an_index_is_not_answered_by_its_other_spelling() -> None:
    retrieval = await build(("v1.10.0", "1.10.0"), indexed=("1.10.0",))

    with pytest.raises(VersionNotIndexedError) as missing:
        await retrieval.search_docs(SearchDocsQuery(library=LIB, ref="v1.10.0", query="routes"))

    assert "version 'v1.10.0' is imported but not indexed yet" in str(missing.value)


async def test_without_the_versions_only_the_exact_ref_answers() -> None:
    retrieval = await build(known=False)

    with pytest.raises(VersionNotIndexedError) as missing:
        await retrieval.search_docs(SearchDocsQuery(library=LIB, ref="v1.10.0", query="routes"))

    assert str(missing.value) == "no index for /encode/starlette@v1.10.0"


async def test_an_unknown_library_names_no_versions() -> None:
    retrieval = await build()

    with pytest.raises(VersionNotIndexedError) as missing:
        await retrieval.search_docs(SearchDocsQuery(library="/encode/other", ref="v1", query="x"))

    assert str(missing.value) == "no index for /encode/other@v1"
