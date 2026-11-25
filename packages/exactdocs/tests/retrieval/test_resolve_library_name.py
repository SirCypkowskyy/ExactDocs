"""A library's name where a tool wants its ID (#573): the one library it means, or the candidates."""

from collections.abc import Collection
from dataclasses import dataclass, field

import pytest

from exactdocs.retrieval.adapters.driven.memory import InMemoryLibraries
from exactdocs.retrieval.dtos import ResolveLibraryNameQuery
from exactdocs.retrieval.errors import AmbiguousLibraryNameError, UnknownLibraryNameError
from exactdocs.retrieval.models import Access, Candidate, CatalogLibrary, NameMatch, named_library
from exactdocs.retrieval.use_cases import ResolveLibraryNameUseCase


def lib(id_: str, title: str = "", description: str = "") -> CatalogLibrary:
    return CatalogLibrary(
        id=id_,
        title=title or id_.rsplit("/", 1)[-1],
        description=description,
        source_url="https://github.com/x/y",
        default_version="v1",
        versions=("v1",),
        version_count=1,
    )


def candidate(id_: str, match: NameMatch) -> Candidate:
    return Candidate(library=lib(id_), match=match)


def test_the_only_library_at_the_best_match_is_picked() -> None:
    picked = named_library(
        "react",
        [
            candidate("/acme/preact", NameMatch.PART),
            candidate("/facebook/react", NameMatch.EXACT),
            candidate("/acme/react-hooks", NameMatch.PREFIX),
        ],
    )

    assert picked.id == "/facebook/react"


def test_a_lone_match_is_picked_however_it_matched() -> None:
    assert named_library("x", [candidate("/acme/only", NameMatch.DESCRIPTION)]).id == "/acme/only"


def test_equal_best_matches_are_ambiguous_and_listed_best_first() -> None:
    with pytest.raises(AmbiguousLibraryNameError) as ambiguous:
        named_library(
            "docs",
            [
                candidate("/b/docs", NameMatch.EXACT),
                candidate("/c/docs-site", NameMatch.PREFIX),
                candidate("/a/docs", NameMatch.EXACT),
            ],
        )

    assert ambiguous.value.candidates == ("/a/docs", "/b/docs", "/c/docs-site")
    assert ambiguous.value.code == "ambiguous_library"


def test_a_description_match_never_picks_one_of_several() -> None:
    with pytest.raises(AmbiguousLibraryNameError):
        named_library(
            "retries",
            [
                candidate("/acme/client", NameMatch.DESCRIPTION),
                candidate("/acme/server", NameMatch.DESCRIPTION),
            ],
        )


def test_no_match_is_not_found() -> None:
    with pytest.raises(UnknownLibraryNameError, match="no library matches the name 'kafka'"):
        named_library("kafka", [])


@dataclass(slots=True)
class Readable:
    """Library roles: the caller reads every library but ``hidden``."""

    hidden: set[str] = field(default_factory=set)

    async def allows(self, library: str, access: Access) -> bool:
        del access
        return library.casefold() not in self.hidden

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        return frozenset(lib.casefold() for lib in libraries if lib.casefold() not in self.hidden)


def resolver(*libraries: CatalogLibrary, hidden: set[str] | None = None) -> ResolveLibraryNameUseCase:
    return ResolveLibraryNameUseCase(
        libraries=InMemoryLibraries(libraries=list(libraries)), access=Readable(hidden or set())
    )


@pytest.mark.parametrize(
    "name", ["TanStack Query", "tanstack query", "Query", "tanstack/query", "/TanStack/Query"]
)
async def test_a_name_resolves_as_resolve_library_id_matches_it(name: str) -> None:
    resolve = resolver(lib("/tanstack/query", "TanStack Query"), lib("/tanstack/router"))

    found = await resolve(ResolveLibraryNameQuery(name=name))

    assert (found.id, found.name) == ("/tanstack/query", name)


async def test_a_library_the_caller_cannot_read_is_neither_picked_nor_listed() -> None:
    resolve = resolver(lib("/acme/payments"), lib("/secret/payments"), hidden={"/secret/payments"})

    found = await resolve(ResolveLibraryNameQuery(name="payments"))
    with pytest.raises(UnknownLibraryNameError):
        await resolve(ResolveLibraryNameQuery(name="secret"))

    assert found.id == "/acme/payments"  # alone once the hidden one is left out


async def test_an_ambiguous_name_lists_only_readable_candidates() -> None:
    resolve = resolver(
        lib("/a/payments"), lib("/b/payments"), lib("/c/payments"), hidden={"/c/payments"}
    )

    with pytest.raises(AmbiguousLibraryNameError) as ambiguous:
        await resolve(ResolveLibraryNameQuery(name="payments"))

    assert ambiguous.value.candidates == ("/a/payments", "/b/payments")
