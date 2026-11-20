"""#428: the vector-only mode, and BM25, vector and hybrid search across chosen libraries.

The embedding model is in process (concept vectors: words of one concept share a dimension), so
"repeat" is near "retry" and no provider is ever called. Versions are embedded as the ``embed``
job does: plan, batches, finish.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
    InMemoryVectorIndex,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    EmbedBatchCommand,
    EmbedVersionCommand,
    FinishEmbeddingCommand,
    IndexManifestCommand,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
)
from exactdocs.retrieval.errors import (
    EmbeddingFailedError,
    UnavailableModeError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    Access,
    ChunkId,
    DocTarget,
    EmbeddedTexts,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestPaths,
    ManifestStatus,
    ModelCheck,
    ModelRef,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    fuse_across_manifests,
    identifier_tokens,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import Reranker

PAYMENTS = "/acme/payments"
BILLING = "/acme/billing"
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
CONCEPTS = {"retry": 1, "retries": 1, "repeat": 1, "again": 1, "backoff": 1, "token": 2, "key": 2}
SIZE = 4
PAYMENTS_DOCS = {
    "resilience": [
        "RetryPolicy decides how often a failed call runs again.",
        "Calls that time out are sent once more after a short pause (backoff).",
    ],
    "auth": ["Rotate the API token without downtime."],
}
BILLING_DOCS = {
    "invoices": ["Invoices are sent again when a payment fails: backoff applies."],
    "keys": ["Each key belongs to one account."],
}
OLD_DOCS = {"legacy": ["Retries were manual in v1: repeat the call yourself."]}


class Clock:
    def now(self) -> datetime:
        return T0


def _vector(text: str) -> tuple[float, ...]:
    values = [0.01] + [0.0] * (SIZE - 1)
    for term in identifier_tokens(text).split():
        values[CONCEPTS.get(term, SIZE - 1)] += 1.0 if term in CONCEPTS else 0.1
    return tuple(values)


@dataclass(slots=True)
class Embeddings:
    owner: Models
    name: str = "corp:concepts"

    async def dimensions(self) -> int:
        return SIZE

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        return EmbeddedTexts(vectors=tuple(_vector(t) for t in texts), input_tokens=1, requests=1)

    async def embed_query(self, text: str) -> EmbeddedTexts:
        self.owner.queries.append(text)
        if self.owner.failing:
            model, why = "corp:concepts", "APIConnectionError"
            raise EmbeddingFailedError(model, why)
        return EmbeddedTexts(vectors=(_vector(text),), input_tokens=5, requests=1)


@dataclass(slots=True)
class Models:
    """``EmbeddingModels`` binding the concept model; records every query embedded."""

    failing: bool = False
    queries: list[str] = field(default_factory=list)

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> Embeddings:
        del handle, name, dimensions, batch_size
        return Embeddings(owner=self)


class Factory:
    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        raise NotImplementedError(profile.name + model)

    async def release(self, name: str) -> None:
        del name

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


@dataclass(slots=True)
class Catalog:
    """Every library's versions and its default one (the last imported)."""

    versions: dict[tuple[str, str], SearchableVersion] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)

    def add(self, library: str, ref: str, manifest: str, *, default: bool) -> None:
        self.versions[library, ref] = SearchableVersion(
            library=library,
            version=ref,
            manifest_id=manifest,
            commit_sha=manifest[-1] * 40,
            repository_url=f"https://github.com{library}",
            host=SourceHost.GITHUB,
        )
        if default:
            self.defaults[library] = ref

    def default_versions(self) -> list[SearchableVersion]:
        return [self.versions[lib, ref] for lib, ref in self.defaults.items()]

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        key = next((lib for lib in self.defaults if lib.casefold() == library.casefold()), None)
        if key is None:
            return None
        return self.versions.get((key, ref or self.defaults[key]))

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        return dict.fromkeys(manifest_ids, ManifestStatus.ACTIVE)

    async def titles(self, articles: ManifestPaths) -> Mapping[str, str]:
        return {p: p for p in articles.paths}


@dataclass(slots=True)
class Defaults:
    catalog: Catalog

    async def all(self) -> Sequence[SearchableVersion]:
        return await InMemoryDefaultVersions(versions=self.catalog.default_versions()).all()


@dataclass(slots=True)
class Readable:
    """Library roles: the caller reads every library but ``hidden``."""

    hidden: set[str] = field(default_factory=set)

    async def allows(self, library: str, access: Access) -> bool:
        del access
        return library.casefold() not in self.hidden

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        return frozenset(lib.casefold() for lib in libraries if lib.casefold() not in self.hidden)


@dataclass(slots=True)
class World:
    module: RetrievalModule
    models: Models
    modes: InMemoryLibraryModes
    ledger: InMemorySpendLedger
    access: Readable


async def _import(
    world: World,
    catalog: Catalog,
    library: str,
    ref: str,
    manifest: str,
    docs: dict,
    *,
    default: bool,
) -> None:
    await world.module.index_manifest(
        IndexManifestCommand(
            manifest_id=manifest,
            library=library,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=f"docs/{blob}.md",
                    blob_sha=f"{blob}-{library}-{ref}",
                    tags=[],
                    chunks=[
                        ChunkIn(
                            heading_path=[blob.title(), f"S{i}"],
                            occurrence_index=0,
                            content=text,
                            content_hash=f"h-{blob}-{i}",
                            anchor=f"s{i}",
                        )
                        for i, text in enumerate(texts)
                    ],
                )
                for blob, texts in docs.items()
            ],
        )
    )
    catalog.add(library, ref, manifest, default=default)


async def _embed(world: World, library: str, ref: str) -> None:
    module = world.module
    plan = await module.plan_embedding(EmbedVersionCommand(library=library, ref=ref))
    assert plan.space_id is not None, plan
    assert plan.manifest_id is not None, plan
    for _ in range(100):
        batch = await module.embed_batch(
            EmbedBatchCommand(
                library=library, ref=ref, manifest_id=plan.manifest_id, space_id=plan.space_id
            )
        )
        if batch.finished:
            break
    await module.finish_embedding(FinishEmbeddingCommand(space_id=plan.space_id))


async def _world(
    *, embedding: bool = True, embed: Sequence[str] = (PAYMENTS, BILLING), ai_off: str | None = None
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    models = Models()
    modes = InMemoryLibraryModes()
    if ai_off is not None:
        modes.overrides[ai_off.casefold()] = LibraryAi(enabled=False)
    ledger = InMemorySpendLedger()
    access = Readable()
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=InMemoryLibraries(),
        defaults=Defaults(catalog=catalog),
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=[CORP],
        instance_roles=InstanceRoles(
            embedding=ModelRef(profile="corp", model="concepts") if embedding else None
        ),
        models=Factory(),
        clock=Clock(),
        vectors=InMemoryVectorIndex(chunks=chunks),
        embedding_models=models,
        article_titles=catalog,
        spend=ledger,
        access=access,
    )
    world = World(module=module, models=models, modes=modes, ledger=ledger, access=access)
    await _import(world, catalog, PAYMENTS, "v1", "m1", OLD_DOCS, default=False)
    await _import(world, catalog, PAYMENTS, "v2", "m2", PAYMENTS_DOCS, default=True)
    await _import(world, catalog, BILLING, "v5", "m5", BILLING_DOCS, default=True)
    if embedding:
        for library, ref in [(PAYMENTS, "v1"), (PAYMENTS, "v2"), (BILLING, "v5")]:
            if library in embed and library != ai_off:
                await _embed(world, library, ref)
    return world


async def _across(
    world: World, query: str, mode: str | None, *libraries: str, caller: str | None = "u1"
) -> SearchAllResult:
    return await world.module.search_all_libraries(
        SearchAllQuery(query=query, mode=mode, libraries=list(libraries), limit=10), caller=caller
    )


def _where(result: SearchAllResult) -> set[tuple[str, str]]:
    return {(r.library, r.version) for r in result.results}


# ---------------------------------------------------------------- fusion across manifests


def test_the_same_chunk_in_two_manifests_is_two_fused_results() -> None:
    same = ChunkId("c")

    fused = fuse_across_manifests([("m1", same), ("m2", same)], [("m2", same)])

    assert [(f.manifest_id, f.chunk_id) for f in fused] == [("m2", same), ("m1", same)]
    assert (fused[0].bm25_rank, fused[0].vector_rank) == (2, 1)
    assert (fused[1].bm25_rank, fused[1].vector_rank) == (1, None)


# ---------------------------------------------------------------- vector mode, one version


async def test_vector_mode_ranks_one_version_by_its_vectors_alone() -> None:
    world = await _world()

    result = await world.module.search_docs(
        SearchDocsQuery(library=PAYMENTS, ref="v2", query="repeat the request", mode="vector")
    )

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.VECTOR, None)
    assert result.version == "v2"
    # No word of the query is in the backoff section: only the vectors find it.
    assert {tuple(r.heading_path) for r in result.results[:2]} == {
        ("Resilience", "S0"),
        ("Resilience", "S1"),
    }
    scores = [r.score for r in result.results]
    assert scores == sorted(scores, reverse=True)


async def test_vector_mode_needs_an_embedding_model() -> None:
    world = await _world(embedding=False)

    with pytest.raises(UnavailableModeError) as refused:
        await world.module.search_docs(
            SearchDocsQuery(library=PAYMENTS, query="retry", mode="vector")
        )

    assert "embedding" in str(refused.value)


async def test_vector_mode_answers_bm25_for_a_version_not_embedded_yet() -> None:
    world = await _world(embed=[BILLING])

    result = await world.module.search_docs(
        SearchDocsQuery(library=PAYMENTS, ref="v2", query="RetryPolicy", mode="vector")
    )

    assert result.retrieval_mode is RetrievalMode.BM25
    assert result.fallback_reason is FallbackReason.EMBEDDING_IN_PROGRESS


# ---------------------------------------------------------------- across libraries


async def test_bm25_across_libraries_ranks_each_result() -> None:
    world = await _world()

    result = await _across(world, "backoff", None)

    assert result.retrieval_mode is RetrievalMode.BM25
    assert _where(result) == {(PAYMENTS, "v2"), (BILLING, "v5")}
    assert [r.bm25_rank for r in result.results] == list(range(1, len(result.results) + 1))
    assert all(r.vector_rank is None for r in result.results)
    assert world.models.queries == [], "BM25 embeds nothing"


async def test_vector_mode_ranks_the_default_versions_of_every_library_together() -> None:
    world = await _world()

    result = await _across(world, "repeat the request", "vector")

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.VECTOR, None)
    assert _where(result) == {(PAYMENTS, "v2"), (BILLING, "v5")}, "never v1, not a default"
    assert [r.vector_rank for r in result.results] == list(range(1, len(result.results) + 1))
    assert all(r.bm25_rank is None for r in result.results)
    scores = [r.score for r in result.results]
    assert scores == sorted(scores, reverse=True)
    assert world.models.queries == ["repeat the request"], "the query is embedded once"


async def test_hybrid_mode_fuses_both_rankings_across_libraries() -> None:
    world = await _world()

    result = await _across(world, "RetryPolicy backoff", "hybrid")

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID, None)
    assert result.results[0].bm25_rank == 1, "an exact identifier stays first"
    assert any(r.vector_rank is not None and r.bm25_rank is None for r in result.results)
    assert _where(result) <= {(PAYMENTS, "v2"), (BILLING, "v5")}


async def test_chosen_libraries_narrow_the_ranking_but_not_the_counts() -> None:
    world = await _world()

    result = await _across(world, "backoff again", "hybrid", BILLING)

    assert _where(result) == {(BILLING, "v5")}
    assert {f.library for f in result.libraries} == {PAYMENTS, BILLING}


async def test_a_library_the_caller_may_not_read_is_never_searched() -> None:
    world = await _world()
    world.access.hidden.add(BILLING.casefold())

    everything = await _across(world, "backoff", "vector")
    with pytest.raises(VersionNotIndexedError):
        await _across(world, "backoff", "vector", BILLING)

    assert _where(everything) == {(PAYMENTS, "v2")}


async def test_a_library_with_ai_off_is_left_out_of_the_vectors_and_named() -> None:
    world = await _world(ai_off=BILLING)

    result = await _across(world, "backoff again", "vector")

    assert result.retrieval_mode is RetrievalMode.VECTOR
    assert result.libraries_without_vectors == [BILLING]
    assert _where(result) == {(PAYMENTS, "v2")}


async def test_nothing_embedded_answers_bm25_with_the_reason_and_embeds_nothing() -> None:
    world = await _world(embed=[])

    result = await _across(world, "backoff", "hybrid")

    assert result.retrieval_mode is RetrievalMode.BM25
    assert result.fallback_reason is FallbackReason.EMBEDDING_IN_PROGRESS
    assert result.results
    assert world.models.queries == []


async def test_a_failing_query_embedding_answers_bm25_never_fails() -> None:
    world = await _world()
    world.models.failing = True

    result = await _across(world, "backoff", "vector")

    assert result.retrieval_mode is RetrievalMode.BM25
    assert result.fallback_reason is FallbackReason.EMBEDDING_UNAVAILABLE
    assert [r.bm25_rank for r in result.results] == list(range(1, len(result.results) + 1))


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
async def test_the_vector_modes_need_an_embedding_model_across_libraries(mode: str) -> None:
    world = await _world(embedding=False)

    with pytest.raises(UnavailableModeError) as refused:
        await _across(world, "backoff", mode)

    assert "embedding" in str(refused.value)


@pytest.mark.parametrize("mode", ["hybrid_hyde", "agentic", "nonsense"])
async def test_modes_that_cannot_rank_across_libraries_are_refused(mode: str) -> None:
    world = await _world()

    with pytest.raises(UnavailableModeError):
        await _across(world, "backoff", mode)


async def test_the_query_embedding_counts_to_the_instance_and_the_caller_not_a_library() -> None:
    world = await _world()
    before = dict(world.ledger.rows)

    await _across(world, "backoff", "vector", caller="u1")

    changed = {
        (key.scope_kind, key.scope_id)
        for key, row in world.ledger.rows.items()
        if before.get(key) != row
    }
    assert changed == {("user", "u1"), ("instance", ""), ("embedding", "")}
