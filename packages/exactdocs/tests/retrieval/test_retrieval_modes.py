"""RET-06 / MCP-05: the retrieval mode is chosen per call, library and instance, from what is
configured, and a mode that cannot run fails clearly (or falls back, when nobody asked for it).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemoryVectorIndex,
    StaticModelRoles,
)
from exactdocs.retrieval.adapters.driven.sqlite import SqliteLibraryModes
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    ForgetLibraryCommand,
    GetLibraryRetrievalQuery,
    IndexManifestCommand,
    QueryDocsQuery,
    SearchDocsQuery,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.errors import UnavailableModeError, UnknownLibraryError
from exactdocs.retrieval.models import (
    CatalogLibrary,
    DocTarget,
    FallbackReason,
    LibraryAi,
    ManifestStatus,
    ModelRole,
    ModeRegistry,
    PipelineAnswer,
    PipelineRequest,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import LibraryModes, RetrievalPipeline
from exactdocs.retrieval.use_cases import Bm25Pipeline

LIB = "/acme/payments"
EMBEDDING, RERANKER, LLM = ModelRole.EMBEDDING, ModelRole.RERANKER, ModelRole.LLM
BM25, HYBRID, HYDE, AGENTIC = (
    RetrievalMode.BM25,
    RetrievalMode.HYBRID,
    RetrievalMode.HYBRID_HYDE,
    RetrievalMode.AGENTIC,
)
EVERY_PIPELINE = frozenset(RetrievalMode)


def _version(ref: str, manifest: str) -> SearchableVersion:
    return SearchableVersion(
        library=LIB,
        version=ref,
        manifest_id=manifest,
        commit_sha=manifest[-1] * 40,
        repository_url="https://github.com/acme/payments",
        host=SourceHost.GITHUB,
    )


@dataclass(slots=True)
class FakeVersions:
    by_ref: dict[str, SearchableVersion]

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        if library.lower() != LIB:
            return None
        return self.by_ref.get(ref or "v2")

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


@dataclass(slots=True)
class FakePipeline:
    """Answers as ``mode`` with the BM25 hits of the requested version, and records requests."""

    mode: RetrievalMode
    bm25: RetrievalPipeline
    requests: list[PipelineRequest] = field(default_factory=list)
    falls_back: FallbackReason | None = None

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        self.requests.append(request)
        found = await self.bm25.run(request)
        return PipelineAnswer(
            mode=BM25 if self.falls_back else self.mode,
            hits=found.hits,
            candidates=found.candidates,
            reranked=len(found.hits) if request.rerank else 0,
            complete=found.complete,
            fallback_reason=self.falls_back,
        )


@dataclass(slots=True)
class MutableRoles:
    """Roles the test changes while the module runs, as the provider configuration does.

    A library in ``ai_off`` gets no role at all, as a library with AI off does.
    """

    roles: set[ModelRole]
    ai_off: set[str] = field(default_factory=set)

    async def configured(self, library: str, ai: LibraryAi | None = None) -> frozenset[ModelRole]:
        off = library.casefold() in self.ai_off or (ai is not None and not ai.enabled)
        return frozenset() if off else frozenset(self.roles)


@dataclass(slots=True)
class World:
    module: RetrievalModule
    roles: set[ModelRole]
    ai_off: set[str]
    """Case-folded IDs of libraries with AI off."""
    pipelines: dict[RetrievalMode, FakePipeline]


def _chunk(heading: str, content: str) -> ChunkIn:
    return ChunkIn(
        heading_path=[heading],
        occurrence_index=0,
        content=content,
        content_hash=f"h-{heading}",
        anchor=heading.lower(),
    )


async def _build(
    *roles: ModelRole,
    instance: RetrievalMode | None = None,
    library_modes: LibraryModes | None = None,
    vector_store: bool | None = None,
) -> World:
    """Build the module; ``vector_store`` adds a vector index that can (or cannot) search."""
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    fakes = {
        m: FakePipeline(mode=m, bm25=Bm25Pipeline(search=index)) for m in (HYBRID, HYDE, AGENTIC)
    }
    versions = FakeVersions({"v1": _version("v1", "m1"), "v2": _version("v2", "m2")})
    configured = set(roles)
    ai_off: set[str] = set()
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(
            libraries=[
                CatalogLibrary(
                    id=LIB,
                    title="Payments",
                    description="",
                    source_url="https://github.com/acme/payments",
                    default_version="v2",
                    versions=("v1", "v2"),
                    version_count=2,
                )
            ]
        ),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=library_modes or InMemoryLibraryModes(),
        roles=MutableRoles(configured, ai_off),
        instance_mode=instance,
        pipelines=fakes,
        vectors=None
        if vector_store is None
        else InMemoryVectorIndex(chunks=chunks, can_search=vector_store),
    )
    for manifest, ref, text in [("m1", "v1", "retry_policy is old"), ("m2", "v2", "Use a token.")]:
        await module.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest,
                library=LIB,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(
                        path="docs/guide.md", blob_sha=f"b-{ref}", chunks=[_chunk("Guide", text)]
                    )
                ],
            )
        )
    return World(module=module, roles=configured, ai_off=ai_off, pipelines=fakes)


async def _mode_of(world: World, mode: str | None = None, ref: str | None = None) -> object:
    result = await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref=ref, query="token", mode=mode)
    )
    return result.retrieval_mode, result.fallback_reason


# ---------------------------------------------------------------- the registry


@pytest.mark.parametrize(
    ("roles", "available"),
    [
        (set(), [BM25]),
        ({RERANKER}, [BM25]),
        ({LLM}, [BM25, AGENTIC]),
        ({EMBEDDING}, [BM25, HYBRID]),
        ({EMBEDDING, LLM}, [BM25, HYBRID, HYDE, AGENTIC]),
    ],
)
def test_the_configured_roles_decide_which_modes_are_available(
    roles: set[ModelRole], available: list[RetrievalMode]
) -> None:
    registry = ModeRegistry(roles=frozenset(roles), pipelines=EVERY_PIPELINE)

    assert list(registry.available()) == available


@pytest.mark.parametrize(
    ("roles", "best"),
    [(set(), BM25), ({LLM}, BM25), ({EMBEDDING}, HYBRID), ({EMBEDDING, LLM, RERANKER}, HYDE)],
)
def test_the_default_is_the_best_available_and_never_agentic(
    roles: set[ModelRole], best: RetrievalMode
) -> None:
    registry = ModeRegistry(roles=frozenset(roles), pipelines=EVERY_PIPELINE)

    assert registry.best() is best


def test_reranking_is_a_flag_on_top_of_any_mode() -> None:
    registry = ModeRegistry(roles=frozenset({RERANKER}), pipelines=EVERY_PIPELINE)

    choice = registry.choose(asked=None, library=None, instance=None)

    assert (choice.mode, choice.rerank) == (BM25, True)


def test_a_mode_without_a_pipeline_is_not_available_even_with_its_roles() -> None:
    registry = ModeRegistry(roles=frozenset({EMBEDDING}), pipelines=frozenset({BM25}))

    with pytest.raises(UnavailableModeError) as error:
        registry.check("hybrid")

    assert (registry.available(), error.value.missing_roles) == ((BM25,), [])


def test_hyde_names_every_missing_role() -> None:
    registry = ModeRegistry(roles=frozenset(), pipelines=EVERY_PIPELINE)

    with pytest.raises(UnavailableModeError, match="embedding and llm roles") as error:
        registry.check("hybrid_hyde")

    assert error.value.missing_roles == ["embedding", "llm"]


# ---------------------------------------------------------------- precedence


async def test_the_call_wins_over_the_library_and_the_instance() -> None:
    world = await _build(EMBEDDING, LLM, instance=HYDE)
    await world.module.set_library_retrieval(SetLibraryRetrievalCommand(library=LIB, mode="hybrid"))

    assert await _mode_of(world, "bm25") == (BM25, None)


async def test_the_library_wins_over_the_instance() -> None:
    world = await _build(EMBEDDING, LLM, instance=BM25)
    await world.module.set_library_retrieval(SetLibraryRetrievalCommand(library=LIB, mode="hybrid"))

    assert await _mode_of(world) == (HYBRID, None)


async def test_the_instance_wins_over_the_best_available() -> None:
    world = await _build(EMBEDDING, LLM, instance=BM25)

    assert await _mode_of(world) == (BM25, None)


async def test_with_nothing_set_the_best_available_mode_answers() -> None:
    world = await _build(EMBEDDING)

    assert await _mode_of(world) == (HYBRID, None)


async def test_with_nothing_configured_it_is_bm25() -> None:
    world = await _build()

    assert await _mode_of(world) == (BM25, None)


async def test_the_mode_is_asked_in_any_letter_case() -> None:
    world = await _build(LLM)

    assert await _mode_of(world, " Agentic ") == (AGENTIC, None)


# ---------------------------------------------------------------- unavailable modes


async def test_asking_for_an_unavailable_mode_fails_naming_the_missing_role() -> None:
    world = await _build()

    with pytest.raises(UnavailableModeError) as error:
        await _mode_of(world, "hybrid")

    assert error.value.code == "mode_unavailable"
    assert error.value.missing_roles == ["embedding"]
    assert "needs the embedding role" in str(error.value)
    assert "available modes: bm25" in str(error.value)


async def test_asking_for_an_unknown_mode_fails_listing_the_available_ones() -> None:
    world = await _build(EMBEDDING)

    with pytest.raises(UnavailableModeError, match="available modes: bm25, hybrid") as error:
        await _mode_of(world, "semantic")

    assert error.value.missing_roles == []


async def test_a_library_mode_whose_role_was_removed_falls_back_and_says_why() -> None:
    world = await _build(EMBEDDING, instance=BM25)
    await world.module.set_library_retrieval(SetLibraryRetrievalCommand(library=LIB, mode="hybrid"))
    world.roles.clear()  # the operator removed the embedding model

    assert await _mode_of(world) == (BM25, FallbackReason.MODE_UNAVAILABLE)


async def test_an_instance_mode_that_cannot_run_falls_back_to_the_best_and_says_why() -> None:
    world = await _build(instance=HYBRID)

    assert await _mode_of(world) == (BM25, FallbackReason.MODE_UNAVAILABLE)


async def test_a_pipeline_that_answers_with_a_cheaper_mode_says_why() -> None:
    world = await _build(EMBEDDING)
    world.pipelines[HYBRID].falls_back = FallbackReason.EMBEDDING_IN_PROGRESS

    assert await _mode_of(world) == (BM25, FallbackReason.EMBEDDING_IN_PROGRESS)


# ---------------------------------------------------------------- what the result reports


async def test_a_reranked_search_says_so_in_the_result_and_its_coverage() -> None:
    world = await _build(EMBEDDING, RERANKER)

    result = await world.module.search_docs(SearchDocsQuery(library=LIB, query="token"))

    assert (result.retrieval_mode, result.reranked) == (HYBRID, True)
    assert result.coverage.reranked == len(result.results) == 1


async def test_every_mode_gets_the_one_version_asked_for_and_nothing_from_another() -> None:
    world = await _build(EMBEDDING, LLM)

    result = await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query="retry_policy", mode="hybrid_hyde")
    )

    asked = world.pipelines[HYDE].requests
    assert [r.version.version for r in asked] == ["v2"]
    assert (result.version, result.results) == ("v2", [])


async def test_query_docs_uses_the_library_mode() -> None:
    world = await _build(LLM)
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, mode="agentic")
    )

    result = await world.module.query_docs(QueryDocsQuery(library_id=LIB, query="token"))

    assert result.retrieval_mode is AGENTIC
    assert [r.version.version for r in world.pipelines[AGENTIC].requests] == ["v2"]


# ---------------------------------------------------------------- the library setting


async def test_a_library_mode_is_validated_against_what_is_configured() -> None:
    world = await _build()

    with pytest.raises(UnavailableModeError, match="needs the embedding role"):
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library=LIB, mode="hybrid")
        )

    shown = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))
    assert shown.mode is None


async def test_a_library_mode_is_shown_with_the_mode_searches_use_now() -> None:
    world = await _build(EMBEDDING, RERANKER, instance=BM25)

    shown = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library="/ACME/Payments", mode="HYBRID")
    )

    assert shown.library == LIB
    assert (shown.mode, shown.instance_mode, shown.effective_mode) == (HYBRID, BM25, HYBRID)
    assert shown.available_modes == [BM25, HYBRID]
    assert shown.configured_roles == [EMBEDDING, RERANKER]


async def test_clearing_a_library_mode_gives_the_instance_mode_back() -> None:
    world = await _build(EMBEDDING, instance=BM25)
    await world.module.set_library_retrieval(SetLibraryRetrievalCommand(library=LIB, mode="hybrid"))

    shown = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, mode="")
    )

    assert (shown.mode, shown.effective_mode) == (None, BM25)
    assert await _mode_of(world) == (BM25, None)


async def test_a_library_that_does_not_exist_has_no_setting() -> None:
    world = await _build()

    with pytest.raises(UnknownLibraryError):
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library="/acme/nothing", mode="bm25")
        )
    with pytest.raises(UnknownLibraryError):
        await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library="/acme/nothing"))


# ---------------------------------------------------------------- the store (adapter contract)


@pytest.fixture(params=["memory", "sqlite"])
async def library_modes(request: pytest.FixtureRequest) -> AsyncIterator[LibraryModes]:
    if request.param == "memory":
        yield InMemoryLibraryModes()
        return
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield SqliteLibraryModes(engine=container.engine)


async def test_a_stored_mode_is_found_in_any_letter_case(library_modes: LibraryModes) -> None:
    await library_modes.save("/Acme/Payments", HYBRID, LibraryAi())

    assert await library_modes.mode_of("/acme/PAYMENTS") is HYBRID
    assert await library_modes.mode_of("/acme/other") is None


async def test_a_stored_mode_is_replaced_and_removed(library_modes: LibraryModes) -> None:
    await library_modes.save(LIB, HYBRID, LibraryAi())
    await library_modes.save(LIB, AGENTIC, LibraryAi())
    assert await library_modes.mode_of(LIB) is AGENTIC

    await library_modes.save(LIB, None, LibraryAi())

    assert await library_modes.mode_of(LIB) is None


async def test_the_static_roles_are_what_the_test_set() -> None:
    assert await StaticModelRoles(roles=frozenset({LLM})).configured(LIB) == {LLM}


async def test_a_forgotten_library_has_no_mode(library_modes: LibraryModes) -> None:
    await library_modes.save("/Acme/Payments", HYBRID, LibraryAi())
    await library_modes.save("/acme/other", AGENTIC, LibraryAi())

    await library_modes.forget("/acme/PAYMENTS")
    await library_modes.forget("/acme/never-set")  # nothing stored: nothing happens

    assert await library_modes.mode_of(LIB) is None
    assert await library_modes.mode_of("/acme/other") is AGENTIC


async def test_forgetting_a_removed_library_drops_its_mode() -> None:
    world = await _build(EMBEDDING)
    await world.module.set_library_retrieval(SetLibraryRetrievalCommand(library=LIB, mode="bm25"))

    await world.module.forget_library(ForgetLibraryCommand(library=LIB))

    shown = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))
    assert (shown.mode, shown.effective_mode) == (None, HYBRID)


# ---------------------------------------------------------------- roles per library


async def test_a_library_with_ai_off_searches_with_bm25_and_no_reranker() -> None:
    world = await _build(EMBEDDING, LLM, RERANKER)
    world.ai_off.add(LIB)

    result = await world.module.search_docs(SearchDocsQuery(library=LIB, query="token"))

    assert (result.retrieval_mode, result.reranked) == (BM25, False)
    assert not world.pipelines[HYDE].requests


async def test_a_library_with_ai_off_cannot_be_given_an_ai_mode_or_ask_for_one() -> None:
    world = await _build(EMBEDDING)
    world.ai_off.add(LIB)

    with pytest.raises(UnavailableModeError, match="needs the embedding role"):
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library=LIB, mode="hybrid")
        )
    with pytest.raises(UnavailableModeError, match="needs the embedding role"):
        await _mode_of(world, "hybrid")
    shown = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))
    assert (shown.available_modes, shown.configured_roles) == ([BM25], [])


# ---------------------------------------------------------------- the vector store


def test_without_the_vector_store_no_hybrid_mode_is_available() -> None:
    registry = ModeRegistry(
        roles=frozenset({EMBEDDING, LLM}), pipelines=EVERY_PIPELINE, vector_store=False
    )

    with pytest.raises(UnavailableModeError, match="vector store is unavailable") as error:
        registry.check("hybrid")

    assert registry.available() == (BM25, AGENTIC)
    assert (error.value.missing_roles, error.value.vector_store) == ([], False)


async def test_a_hybrid_setting_falls_back_to_bm25_when_sqlite_vec_cannot_load() -> None:
    up = await _build(EMBEDDING, instance=HYBRID, vector_store=True)
    down = await _build(EMBEDDING, instance=HYBRID, vector_store=False)

    assert await _mode_of(up) == (HYBRID, None)
    assert await _mode_of(down) == (BM25, FallbackReason.VECTOR_STORE_UNAVAILABLE)


async def test_the_best_mode_says_when_the_vector_store_kept_hybrid_out() -> None:
    world = await _build(EMBEDDING, vector_store=False)

    assert await _mode_of(world) == (BM25, FallbackReason.VECTOR_STORE_UNAVAILABLE)
    shown = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))
    assert (shown.effective_mode, shown.fallback_reason) == (
        BM25,
        FallbackReason.VECTOR_STORE_UNAVAILABLE,
    )
    assert shown.available_modes == [BM25]


async def test_asking_for_hybrid_without_the_vector_store_fails_clearly() -> None:
    world = await _build(EMBEDDING, vector_store=False)

    with pytest.raises(UnavailableModeError, match="sqlite-vec cannot be loaded"):
        await _mode_of(world, "hybrid")
