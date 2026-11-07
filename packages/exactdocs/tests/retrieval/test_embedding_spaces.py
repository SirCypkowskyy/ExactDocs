"""RET-01: a new embedding model gets its own space; the same model keeps the one it has."""

from datetime import UTC, datetime

import pytest

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemoryVectorIndex,
)
from exactdocs.retrieval.dtos import OpenEmbeddingSpaceCommand
from exactdocs.retrieval.errors import VectorStoreUnavailableError
from exactdocs.retrieval.models import (
    DocTarget,
    EmbeddingSpaceId,
    ManifestStatus,
    SearchableVersion,
    SpaceState,
)
from exactdocs.retrieval.module import RetrievalModule

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
A_384 = OpenEmbeddingSpaceCommand(profile_kind="openai", model="a", dimensions=384)


class Nothing:
    """A catalog with no versions."""

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        del library, ref
        return None

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


class Clock:
    def now(self) -> datetime:
        return T0


def _module(vectors: InMemoryVectorIndex | None) -> RetrievalModule:
    chunks = InMemoryChunkRepository()
    search = InMemorySearchIndex(chunks=chunks)
    return RetrievalModule.build(
        searchable=Nothing(),
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=Nothing(),
        chunks=chunks,
        search=search,
        maintenance=search,
        library_modes=InMemoryLibraryModes(),
        clock=Clock(),
        vectors=vectors,
    )


@pytest.fixture
def vectors() -> InMemoryVectorIndex:
    return InMemoryVectorIndex(chunks=InMemoryChunkRepository())


async def test_the_first_model_gets_a_building_space(vectors: InMemoryVectorIndex) -> None:
    space = await _module(vectors).open_embedding_space(A_384)

    assert (space.model, space.dimensions, space.state, space.created) == (
        "a",
        384,
        SpaceState.BUILDING,
        True,
    )
    assert (space.metric, space.input_format, space.created_at) == ("cosine", 1, T0)


async def test_the_same_model_keeps_its_space(vectors: InMemoryVectorIndex) -> None:
    module = _module(vectors)
    first = await module.open_embedding_space(A_384)
    await vectors.activate_space(EmbeddingSpaceId(first.id), T0)

    again = await module.open_embedding_space(A_384)

    assert (again.id, again.state, again.created) == (first.id, SpaceState.ACTIVE, False)


@pytest.mark.parametrize(
    "changed",
    [
        OpenEmbeddingSpaceCommand(profile_kind="openai", model="b", dimensions=1024),
        OpenEmbeddingSpaceCommand(profile_kind="openai", model="a", dimensions=256),
        OpenEmbeddingSpaceCommand(profile_kind="local", model="a", dimensions=384),
        OpenEmbeddingSpaceCommand(profile_kind="openai", model="a", dimensions=384, input_format=2),
    ],
)
async def test_a_new_model_gets_a_new_space_and_the_old_one_stays(
    vectors: InMemoryVectorIndex, changed: OpenEmbeddingSpaceCommand
) -> None:
    module = _module(vectors)
    old = await module.open_embedding_space(A_384)

    new = await module.open_embedding_space(changed)

    assert new.created
    assert new.id != old.id
    assert [(s.id, s.state) for s in await vectors.spaces()] == [
        (old.id, SpaceState.BUILDING),
        (new.id, SpaceState.BUILDING),
    ]


async def test_a_retired_space_is_never_reopened(vectors: InMemoryVectorIndex) -> None:
    module = _module(vectors)
    old = await module.open_embedding_space(A_384)
    await vectors.retire_space(EmbeddingSpaceId(old.id))

    again = await module.open_embedding_space(A_384)

    assert (again.created, again.id != old.id) == (True, True)


async def test_without_a_vector_store_there_is_no_space() -> None:
    with pytest.raises(VectorStoreUnavailableError):
        await _module(None).open_embedding_space(A_384)
