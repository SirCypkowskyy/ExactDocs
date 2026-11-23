"""RET-01: hybrid search fuses BM25 and vectors (RRF), within the pinned version only.

The embedding model is in process (``ConceptModels`` below): words of one concept share a
dimension, so "repeat" is near "retry" the way a real model makes paraphrases near, and no
provider is ever called. Versions are embedded as the ``embed`` job does: plan, batches, finish.
"""

import asyncio
import logging
from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from exactdocs.retrieval.adapters.driven.memory import (
    HashEmbeddingModels,
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
    InMemoryVectorIndex,
)
from exactdocs.retrieval.adapters.driven.memory_index import InMemoryVectorBackend
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    EmbedBatchCommand,
    EmbedVersionCommand,
    FinishEmbeddingCommand,
    IndexManifestCommand,
    QueryDocsQuery,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.errors import EmbeddingFailedError, ProviderUnsupportedError
from exactdocs.retrieval.models import (
    BackendHit,
    BudgetLimit,
    Budgets,
    ChunkId,
    DocTarget,
    EmbeddedTexts,
    EmbeddingSpec,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestPaths,
    ManifestStatus,
    ModelCheck,
    ModelRef,
    ModelRole,
    NativeRanking,
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    SpendEntry,
    SpendWindow,
    TagFilter,
    ThinkingLevel,
    identifier_tokens,
    reciprocal_rank_fusion,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import (
    NativeHybrid,
    NativeRerank,
    Reranker,
    RetrievalPipeline,
    VectorBackend,
)
from exactdocs.retrieval.use_cases import SearchDocsUseCase

LIB = "/acme/payments"
T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
LOCAL_CORP = ProviderProfile(
    name="corp", kind=ProviderKind.LOCAL, origin=ProfileOrigin.CONFIGURATION
)
"""The same roles on an in-process (``local``) profile: free, so no budget is checked."""
CONCEPTS = {
    "retry": 1,
    "retries": 1,
    "repeat": 1,
    "again": 1,
    "backoff": 1,
    "token": 2,
    "tokens": 2,
    "key": 2,
    "credential": 2,
    "page": 3,
    "pages": 3,
    "cursor": 3,
}
"""Words of one concept share a dimension; other words share the last one."""
SIZE = 5
GUIDE = {
    "resilience": [
        "RetryPolicy decides how often a failed call runs again.",
        "Calls that time out are sent once more after a short pause (backoff).",
    ],
    "auth": ["Rotate the API token without downtime.", "Store credentials in the vault."],
    "paging": ["Use the cursor to read the next page."],
}
OLD_GUIDE = {"resilience-old": ["Failed calls are retried three times in v1."]}


class Clock:
    def now(self) -> datetime:
        return T0


@dataclass(frozen=True, slots=True, kw_only=True)
class Opened:
    name: str
    mode: str
    query: str | None
    attributes: dict[str, str | None]


class Span:
    def answered_by(self, mode: str) -> None:
        del mode


@dataclass(slots=True)
class RecordingTracer:
    """A test double of ``SearchTracer``: what was opened, in order."""

    opened: list[Opened] = field(default_factory=list)
    fallbacks: list[tuple[str, str]] = field(default_factory=list)
    cache_hits: list[tuple[str, str]] = field(default_factory=list)

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[Span]:
        self.opened.append(Opened(name=name, mode=mode, query=query, attributes=attributes))
        return nullcontext(Span())

    def fallback(self, *, mode: str, reason: str) -> None:
        self.fallbacks.append((mode, reason))

    def cache_hit(self, *, cache: str, mode: str) -> None:
        self.cache_hits.append((cache, mode))

    @property
    def names(self) -> list[str]:
        return [o.name for o in self.opened]


def _concept_vector(text: str) -> tuple[float, ...]:
    values = [0.0] * SIZE
    values[0] = 0.01
    for term in identifier_tokens(text).split():
        values[CONCEPTS.get(term, SIZE - 1)] += 1.0 if term in CONCEPTS else 0.1
    return tuple(values)


@dataclass(slots=True)
class ConceptEmbeddings:
    """``Embeddings`` from ``CONCEPTS``; ``behaviour`` makes the query call fail or hang."""

    owner: ConceptModels
    name: str

    async def dimensions(self) -> int:
        return SIZE

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        return EmbeddedTexts(
            vectors=tuple(_concept_vector(t) for t in texts), input_tokens=len(texts), requests=1
        )

    async def embed_query(self, text: str) -> EmbeddedTexts:
        self.owner.queries.append(text)
        self.owner.asked.set()
        if self.owner.behaviour == "fail":
            raise EmbeddingFailedError(self.name, "APIConnectionError")
        if self.owner.behaviour == "hang":
            await asyncio.sleep(10)
        if self.owner.behaviour == "boom":
            raise IndexError(text)  # an adapter bug; its message must not escape
        if self.owner.behaviour == "unsupported":
            reason = "it built no embedding model"
            raise ProviderUnsupportedError(CORP.name, reason)
        return EmbeddedTexts(vectors=(_concept_vector(text),), input_tokens=7, requests=1)


@dataclass(slots=True)
class ConceptModels:
    """``EmbeddingModels`` binding ``ConceptEmbeddings``; records every query embedded."""

    behaviour: str = "ok"
    queries: list[str] = field(default_factory=list)
    asked: asyncio.Event = field(default_factory=asyncio.Event)

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> ConceptEmbeddings:
        del handle, dimensions, batch_size
        return ConceptEmbeddings(owner=self, name=name)


@dataclass(slots=True)
class ReversingReranker:
    """``Reranker`` that scores the documents in reverse of the order it got them; records them."""

    seen: list[list[str]] = field(default_factory=list)

    async def rerank(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        del query
        self.seen.append(list(documents))
        return [float(i) for i in range(len(documents))]


class SealedKeyError(Exception):
    """What a secret box raises for a key it cannot open (not a domain error)."""


@dataclass(slots=True)
class Factory:
    """``ModelFactory`` whose embedder handle is a marker (the bound models ignore it).

    With ``unsealable`` the profile's key cannot be opened, as after a secret key change.
    """

    unsealable: bool = False
    cross_encoder: ReversingReranker = field(default_factory=ReversingReranker)

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        """Know of no model that cannot think.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            ``None``.
        """
        del profile, model
        return None

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        del thinking
        raise ProviderUnsupportedError(profile.name, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        if self.unsealable:
            message = "sk-secret-in-the-message"
            raise SealedKeyError(message)
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        del profile, model
        return self.cross_encoder

    async def release(self, name: str) -> None:
        del name

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        del thinking
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


@dataclass(slots=True)
class Catalog:
    """The catalog: each version's active manifest."""

    versions: dict[str, SearchableVersion] = field(default_factory=dict)

    def add(self, ref: str, manifest: str) -> None:
        self.versions[ref] = SearchableVersion(
            library=LIB,
            version=ref,
            manifest_id=manifest,
            commit_sha=manifest[-1] * 40,
            repository_url="https://github.com/acme/payments",
            host=SourceHost.GITHUB,
        )

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        return self.versions.get(ref or "v2") if library == LIB else None

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        active = {v.manifest_id for v in self.versions.values()}
        return {
            m: ManifestStatus.ACTIVE if m in active else ManifestStatus.SUPERSEDED
            for m in manifest_ids
        }

    async def titles(self, articles: ManifestPaths) -> Mapping[str, str]:
        return {p: p.removeprefix("docs/").removesuffix(".md").title() for p in articles.paths}


@dataclass(slots=True)
class World:
    module: RetrievalModule
    catalog: Catalog
    models: ConceptModels
    vectors: InMemoryVectorIndex
    modes: InMemoryLibraryModes
    ledger: InMemorySpendLedger
    tracer: RecordingTracer
    factory: Factory


def _world(
    *,
    instance: RetrievalMode | None = RetrievalMode.HYBRID,
    embedding: str | None = "concepts",
    wait: float = 5.0,
    reranker: bool = False,
    budgets: Budgets | None = None,
    local: bool = False,
    vector_backend: VectorBackend | None = None,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    models = ConceptModels()
    vectors = InMemoryVectorIndex(chunks=chunks)
    modes = InMemoryLibraryModes()
    ledger = InMemorySpendLedger()
    tracer = RecordingTracer()
    factory = Factory()
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=[LOCAL_CORP if local else CORP],
        instance_roles=InstanceRoles(
            embedding=None if embedding is None else ModelRef(profile="corp", model=embedding),
            reranker=ModelRef(profile="corp", model="cross") if reranker else None,
        ),
        models=factory,
        instance_mode=instance,
        clock=Clock(),
        tracer=tracer,
        vectors=vectors,
        embedding_models=models,
        article_titles=catalog,
        spend=ledger,
        budgets=budgets,
        query_embedding_timeout=wait,
        vector_backend=vector_backend,
        stored_vectors=vectors if vector_backend is not None else None,
    )
    return World(
        module=module,
        catalog=catalog,
        models=models,
        vectors=vectors,
        modes=modes,
        ledger=ledger,
        tracer=tracer,
        factory=factory,
    )


async def _import(world: World, ref: str, manifest: str, blobs: dict[str, list[str]]) -> None:
    await world.module.index_manifest(
        IndexManifestCommand(
            manifest_id=manifest,
            library=LIB,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=f"docs/{blob}.md",
                    blob_sha=f"{blob}-{ref}",
                    tags=["security"] if blob == "auth" else [],
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
                for blob, texts in blobs.items()
            ],
        )
    )
    world.catalog.add(ref, manifest)


async def _embed(world: World, ref: str) -> None:
    """Run an ``embed`` job of one version as ingestion does."""
    module = world.module
    plan = await module.plan_embedding(EmbedVersionCommand(library=LIB, ref=ref))
    assert plan.space_id is not None, plan
    assert plan.manifest_id is not None, plan
    for _ in range(100):
        batch = await module.embed_batch(
            EmbedBatchCommand(
                library=LIB, ref=ref, manifest_id=plan.manifest_id, space_id=plan.space_id
            )
        )
        if batch.finished:
            break
    await module.finish_embedding(FinishEmbeddingCommand(space_id=plan.space_id))


async def _embedded_world(
    *,
    instance: RetrievalMode | None = RetrievalMode.HYBRID,
    wait: float = 5.0,
    reranker: bool = False,
    budgets: Budgets | None = None,
    vector_backend: VectorBackend | None = None,
) -> World:
    world = _world(
        instance=instance,
        wait=wait,
        reranker=reranker,
        budgets=budgets,
        vector_backend=vector_backend,
    )
    await _import(world, "v1", "m1", OLD_GUIDE)
    await _import(world, "v2", "m2", GUIDE)
    await _embed(world, "v1")
    await _embed(world, "v2")
    return world


async def _search(
    world: World,
    query: str,
    *,
    mode: str | None = None,
    limit: int = 5,
    tags: Sequence[str] = (),
) -> SearchDocsResult:
    return await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query=query, mode=mode, limit=limit, tags=list(tags))
    )


def _hybrid(world: World) -> RetrievalPipeline:
    use_case = world.module.search_docs
    assert isinstance(use_case, SearchDocsUseCase)
    return use_case.modes.pipelines[RetrievalMode.HYBRID]


def _texts(result: SearchDocsResult) -> list[str]:
    return [r.heading_path[0] + "/" + r.heading_path[1] for r in result.results]


# ---------------------------------------------------------------- fusion


def test_rrf_scores_each_half_by_rank_with_k_60() -> None:
    a, b, c = ChunkId("a"), ChunkId("b"), ChunkId("c")

    fused = reciprocal_rank_fusion([a, b], [b, c])

    assert [f.chunk_id for f in fused] == [b, a, c]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1].score == pytest.approx(1 / 61)
    assert (fused[2].bm25_rank, fused[2].vector_rank) == (None, 2)


def test_rrf_ties_go_to_bm25_first() -> None:
    a, b = ChunkId("z-bm25"), ChunkId("a-vectors")

    fused = reciprocal_rank_fusion([a], [b])

    assert [f.chunk_id for f in fused] == [a, b]


# ---------------------------------------------------------------- hybrid answers


async def test_a_paraphrase_only_the_vectors_find_is_returned() -> None:
    world = await _embedded_world()

    result = await _search(world, "repeat failed requests")

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID, None)
    # "backoff" shares no word with the query: only the vectors could bring it in.
    assert "Resilience/S1" in _texts(result)[:3]
    backoff = next(r for r in result.results if r.heading_path[1] == "S1")
    assert backoff.snippet == GUIDE["resilience"][1]


async def test_an_exact_identifier_still_ranks_first() -> None:
    world = await _embedded_world()
    bm25 = await _search(world, "RetryPolicy", mode="bm25")

    hybrid = await _search(world, "RetryPolicy")

    assert hybrid.retrieval_mode is RetrievalMode.HYBRID
    assert _texts(hybrid)[0] == _texts(bm25)[0] == "Resilience/S0"
    assert hybrid.results[0].highlights, "the BM25 hit keeps its marked snippet"


async def test_no_chunk_of_another_version_is_returned() -> None:
    world = await _embedded_world()

    result = await _search(world, "how do I retry failed calls", limit=50)

    assert result.version == "v2"
    assert {r.commit_sha for r in result.results} == {"2" * 40}
    assert all(r.article_path != "docs/resilience-old.md" for r in result.results)


async def test_a_synonym_no_chunk_shares_a_word_with_is_found_by_the_vectors() -> None:
    world = await _embedded_world()
    assert (await _search(world, "repeat", mode="bm25")).results == []

    result = await _search(world, "repeat")

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID, None)
    assert _texts(result)[:2] == ["Resilience/S0", "Resilience/S1"]
    assert result.results[0].highlights == []  # nothing to mark: only the vectors matched
    assert world.models.queries == ["repeat"]


async def test_an_identifier_the_version_lacks_gets_only_chunks_of_the_version() -> None:
    world = await _embedded_world()

    result = await _search(world, "podman")

    # No similarity floor: the nearest chunks come back, but only ever the version's.
    assert result.retrieval_mode is RetrievalMode.HYBRID
    assert result.results
    assert {r.commit_sha for r in result.results} == {"2" * 40}
    assert world.models.queries == ["podman"]


async def test_coverage_counts_the_chunks_of_both_halves_once() -> None:
    world = await _embedded_world()

    result = await _search(world, "token", limit=1)

    # BM25 matches 1 chunk; the vectors rank all 5 of the version; the union is 5.
    assert (result.coverage.candidates, result.coverage.complete) == (5, False)
    assert len(result.results) == 1


async def test_the_tag_filter_applies_to_both_halves() -> None:
    world = await _embedded_world()

    result = await _search(world, "token", tags=["security"])

    assert result.retrieval_mode is RetrievalMode.HYBRID
    assert all(r.tags == ["security"] for r in result.results)
    # "Store credentials in the vault" has no "token": only the vector half could return it.
    assert _texts(result) == ["Auth/S0", "Auth/S1"]


async def test_a_tag_no_chunk_has_answers_nothing_in_both_halves() -> None:
    world = await _embedded_world()

    result = await _search(world, "retry", tags=["nothing-has-this"])

    assert (result.retrieval_mode, result.results) == (RetrievalMode.HYBRID, [])


async def test_a_reranker_reorders_the_fused_candidates_after_the_hybrid_pipeline() -> None:
    world = await _embedded_world(reranker=True)
    fused = await _search(world, "repeat failed requests")  # reranked already: read its input
    sent = world.factory.cross_encoder.seen[-1]

    result = await _search(world, "repeat failed requests")

    assert (result.retrieval_mode, result.reranked, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        True,
        None,
    )
    # The reranker got the fused candidates (vector-only ones included) and reversed them.
    assert world.factory.cross_encoder.seen[-1] == sent
    assert "Calls that time out are sent once more after a short pause (backoff)." in sent
    assert [r.snippet for r in result.results] == list(reversed(sent))[: len(result.results)]
    assert result.coverage.reranked == len(sent)
    assert {r.commit_sha for r in result.results} == {"2" * 40}
    assert fused.results == result.results
    names = world.tracer.names
    assert names.index("search_docs.embed_query") < names.index("search_docs.rerank")


async def test_query_docs_runs_the_same_pipeline() -> None:
    world = await _embedded_world()

    result = await world.module.query_docs(
        QueryDocsQuery(library_id=f"{LIB}/v2", query="repeat failed requests")
    )

    assert result.retrieval_mode is RetrievalMode.HYBRID
    assert "query_docs.embed_query" in world.tracer.names


# ---------------------------------------------------------------- the query's embedding


async def test_the_query_embedding_is_a_span_without_the_query_text() -> None:
    world = await _embedded_world()

    await _search(world, "repeat failed requests")

    (stage,) = [o for o in world.tracer.opened if o.name == "search_docs.embed_query"]
    assert (stage.mode, stage.query, stage.attributes) == ("hybrid", None, {})


async def test_the_query_embedding_is_recorded_in_the_spend_ledger() -> None:
    world = await _embedded_world()
    before = sum(r.input_tokens for r in world.ledger.rows.values())

    await _search(world, "repeat failed requests")

    after = sum(r.input_tokens for r in world.ledger.rows.values())
    # Recorded once (by the pipeline, through the budgets' ledger): 7 tokens in each of the
    # embedding, instance and library scopes (no user: a direct call), per day and per month.
    assert after - before == 7 * 3 * 2
    scopes = {(r.scope_kind, r.scope_id) for r in world.ledger.rows.values()}
    assert {("embedding", ""), ("instance", ""), ("library", LIB)} <= scopes


@pytest.mark.parametrize("behaviour", ["fail", "hang", "unsupported", "boom"])
async def test_a_failing_or_slow_embedding_answers_bm25_never_fails(behaviour: str) -> None:
    world = await _embedded_world(wait=0.05)
    world.models.behaviour = behaviour

    result = await _search(world, "RetryPolicy")

    assert result.retrieval_mode is RetrievalMode.BM25
    assert result.fallback_reason is FallbackReason.EMBEDDING_UNAVAILABLE
    assert _texts(result)[0] == "Resilience/S0"


async def test_cancelling_a_search_while_the_query_is_embedded_cancels_it() -> None:
    world = await _embedded_world(wait=30.0)
    world.models.behaviour = "hang"
    search = asyncio.create_task(_search(world, "RetryPolicy"))
    await world.models.asked.wait()

    search.cancel()

    with pytest.raises(asyncio.CancelledError):
        await search


async def test_a_key_that_cannot_be_opened_answers_bm25_and_logs_only_the_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _embedded_world()
    world.factory.unsealable = True

    with caplog.at_level(logging.WARNING, logger="exactdocs.retrieval.use_cases"):
        result = await _search(world, "RetryPolicy")

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.EMBEDDING_UNAVAILABLE,
    )
    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    message = record.getMessage()
    assert "SealedKeyError" in message
    assert "sk-secret-in-the-message" not in message  # the exception's text never
    assert "RetryPolicy" not in message  # nor the query


@pytest.mark.parametrize("scope_kind", ["embedding", "instance", "library"])
async def test_a_used_up_budget_answers_bm25_without_embedding_the_query(scope_kind: str) -> None:
    limit = BudgetLimit(scope_kind=scope_kind, window=SpendWindow.DAY, tokens=10_000)
    world = await _embedded_world(budgets=Budgets(limits=(limit,)))
    scope_id = LIB if scope_kind == "library" else ""
    used = SpendEntry(
        scope_kind=scope_kind,
        scope_id=scope_id,
        window=SpendWindow.DAY,
        window_start=T0.date(),
        input_tokens=10_000,
    )
    await world.ledger.add([used])  # what other searches spent today

    result = await _search(world, "RetryPolicy")

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    assert world.models.queries == []
    assert _texts(result)[0] == "Resilience/S0"  # BM25 still answers


async def test_a_local_query_embedding_runs_under_a_used_up_token_budget() -> None:
    # #284: local models cost nothing, so their tokens are recorded but count toward no token
    # budget, and a budget paid calls used up never refuses a local query embedding (or job).
    limit = BudgetLimit(scope_kind="instance", window=SpendWindow.DAY, tokens=10_000)
    world = _world(budgets=Budgets(limits=(limit,)), local=True)
    used = SpendEntry(
        scope_kind="instance",
        scope_id="",
        window=SpendWindow.DAY,
        window_start=T0.date(),
        input_tokens=10_000,
    )
    await world.ledger.add([used])  # what paid calls spent today
    await _import(world, "v2", "m2", GUIDE)
    await _embed(world, "v2")  # the embedding job is never stopped either

    result = await _search(world, "repeat failed requests")

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID, None)
    assert world.models.queries == ["repeat failed requests"]
    (today,) = [
        r
        for k, r in world.ledger.rows.items()
        if (k.scope_kind, k.window) == ("instance", SpendWindow.DAY)
    ]
    assert today.local_tokens > 0  # the job's and the query's tokens are recorded
    assert today.input_tokens == 10_000 + today.local_tokens
    assert today.tokens == 10_000  # but only the paid ones count toward the budget


async def test_a_budget_not_reached_lets_the_query_be_embedded() -> None:
    limit = BudgetLimit(scope_kind="instance", window=SpendWindow.DAY, tokens=1_000_000)
    world = await _embedded_world(budgets=Budgets(limits=(limit,)))

    result = await _search(world, "RetryPolicy")

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID, None)


async def test_a_version_not_embedded_yet_answers_bm25_without_embedding_the_query() -> None:
    world = _world()
    await _import(world, "v2", "m2", GUIDE)

    result = await _search(world, "RetryPolicy")

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.EMBEDDING_IN_PROGRESS,
    )
    assert world.models.queries == []


async def test_a_space_of_another_model_is_never_searched_with_this_models_query() -> None:
    world = await _embedded_world()
    (space,) = await world.vectors.spaces()
    other = await world.vectors.create_space(
        EmbeddingSpec(profile_kind="openai-compatible", model="other", dimensions=SIZE), T0
    )
    pipeline = _hybrid(world)
    request = PipelineRequest(
        version=world.catalog.versions["v2"],
        query="retry",
        tag_filter=TagFilter(),
        limit=5,
        rerank=False,
        space=other,
    )

    answer = await pipeline.run(request)

    assert (answer.mode, answer.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.EMBEDDING_IN_PROGRESS,
    )
    assert world.models.queries == []
    assert space.id != other.id


async def test_a_library_with_ai_off_never_sends_its_query() -> None:
    world = await _embedded_world()
    (space,) = await world.vectors.spaces()
    await world.modes.save(LIB, None, LibraryAi(enabled=False))
    pipeline = _hybrid(world)

    answer = await pipeline.run(
        PipelineRequest(
            version=world.catalog.versions["v2"],
            query="retry",
            tag_filter=TagFilter(),
            limit=5,
            rerank=False,
            space=space,
        )
    )

    assert answer.mode is RetrievalMode.BM25
    assert world.models.queries == []


# ---------------------------------------------------------------- not a default yet


async def test_hybrid_is_not_the_default_until_the_eval_makes_it_one() -> None:
    world = await _embedded_world(instance=None)

    result = await _search(world, "RetryPolicy")

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.BM25, None)
    assert world.models.queries == []


async def test_the_term_hash_stand_in_puts_texts_sharing_terms_near() -> None:
    models = HashEmbeddingModels(size=64, by_terms=True)
    model = models.bind(object(), name="t:t", dimensions=None, batch_size=8)

    retry, again, token = (await model.embed_documents(["retryPolicy", "retry", "token"])).vectors

    def cosine(x: Sequence[float], y: Sequence[float]) -> float:
        return sum(a * b for a, b in zip(x, y, strict=True)) / (
            sum(a * a for a in x) ** 0.5 * sum(b * b for b in y) ** 0.5
        )

    assert cosine(retry, again) > cosine(retry, token)


# ---------------------------------------------------------------- external vector backends (#352)


@dataclass(slots=True)
class FusedHere:
    """A ``VectorBackend`` without ``NativeHybrid``: ExactDocs fuses its results itself."""

    inner: InMemoryVectorBackend = field(default_factory=InMemoryVectorBackend)
    name: str = "plain"

    async def open(self) -> None:
        await self.inner.open()

    async def close(self) -> None:
        await self.inner.close()

    async def put(self, space, manifest, entries) -> None:
        await self.inner.put(space, manifest, entries)

    async def remove(self, space_id, manifest_id, chunk_ids) -> None:
        await self.inner.remove(space_id, manifest_id, chunk_ids)

    async def delete(self, manifest_ids) -> None:
        await self.inner.delete(manifest_ids)

    async def drop_space(self, space_id) -> None:
        await self.inner.drop_space(space_id)

    async def held(self, space_id, library):
        return await self.inner.held(space_id, library)

    async def nearest(self, space, manifest_ids, query, tag_filter, limit):
        return await self.inner.nearest(space, manifest_ids, query, tag_filter, limit)


async def test_a_vector_backend_answers_with_the_same_results_for_the_same_scores() -> None:
    database = await _embedded_world()
    external = await _embedded_world(vector_backend=FusedHere())

    for query in ["repeat failed requests", "RetryPolicy", "token"]:
        for mode in ["vector", "hybrid"]:
            here = await _search(database, query, mode=mode)
            there = await _search(external, query, mode=mode)
            assert there.retrieval_mode.value == mode, there
            assert [r.chunk_id for r in there.results] == [r.chunk_id for r in here.results]
            assert [r.score for r in there.results] == pytest.approx(
                [r.score for r in here.results], abs=1e-6
            )


async def test_a_native_hybrid_backend_ranks_the_hybrid_search_itself() -> None:
    backend = InMemoryVectorBackend()
    world = await _embedded_world(vector_backend=backend)

    result = await _search(world, "repeat failed requests", limit=50)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID, None)
    assert "Resilience/S1" in _texts(result)[:3]  # found by its vector alone, as with RRF
    assert {r.commit_sha for r in result.results} == {"2" * 40}  # never the other version


async def test_a_vector_backend_that_does_not_answer_falls_back_to_bm25() -> None:
    backend = InMemoryVectorBackend()
    world = await _embedded_world(vector_backend=backend)
    backend.unavailable = True

    for mode in ["hybrid", "vector"]:
        result = await _search(world, "RetryPolicy", mode=mode)
        assert (result.retrieval_mode, result.fallback_reason) == (
            RetrievalMode.BM25,
            FallbackReason.VECTOR_STORE_UNAVAILABLE,
        )
        assert _texts(result)[0] == "Resilience/S0"


# ---------------------------------------------------------------- a backend's own reranker (#473)


@dataclass(slots=True)
class RerankingHere:
    """A ``NativeHybrid`` backend with ``NativeRerank``: its ranker reverses its hybrid order.

    With ``partial`` its ranker cannot rerank (the hybrid order, ``reranked`` 0), as Azure AI
    Search answers when its semantic ranker is over capacity; ``stray`` adds a hit of another
    version, which the domain must drop.
    """

    inner: InMemoryVectorBackend = field(default_factory=InMemoryVectorBackend)
    name: str = "reranking"
    partial: bool = False
    stray: BackendHit | None = None
    asked: list[str] = field(default_factory=list)

    async def open(self) -> None:
        await self.inner.open()

    async def close(self) -> None:
        await self.inner.close()

    async def put(self, space, manifest, entries) -> None:
        await self.inner.put(space, manifest, entries)

    async def remove(self, space_id, manifest_id, chunk_ids) -> None:
        await self.inner.remove(space_id, manifest_id, chunk_ids)

    async def delete(self, manifest_ids) -> None:
        await self.inner.delete(manifest_ids)

    async def drop_space(self, space_id) -> None:
        await self.inner.drop_space(space_id)

    async def held(self, space_id, library):
        return await self.inner.held(space_id, library)

    async def nearest(self, space, manifest_ids, query, tag_filter, limit):
        return await self.inner.nearest(space, manifest_ids, query, tag_filter, limit)

    async def hybrid(self, space, manifest_ids, query, vector, tag_filter, limit):
        self.asked.append("hybrid")
        return await self.inner.hybrid(space, manifest_ids, query, vector, tag_filter, limit)

    async def hybrid_reranked(
        self, space, manifest_ids, query, vector, tag_filter, limit
    ) -> NativeRanking:
        self.asked.append(f"reranked:{query.text}")
        hits = list(await self.inner.hybrid(space, manifest_ids, query, vector, tag_filter, limit))
        if self.stray is not None:
            hits.insert(0, self.stray)
        if self.partial:
            return NativeRanking(hits=tuple(hits), reranked=0)
        reranked = [
            BackendHit(manifest_id=h.manifest_id, chunk_id=h.chunk_id, score=float(i))
            for i, h in enumerate(hits, start=1)
        ]
        return NativeRanking(hits=tuple(reversed(reranked)), reranked=len(hits))


def test_the_reranking_stand_in_is_a_native_hybrid_backend_that_reranks() -> None:
    backend = RerankingHere()
    assert isinstance(backend, NativeHybrid)
    assert isinstance(backend, NativeRerank)
    assert not isinstance(InMemoryVectorBackend(), NativeRerank)  # the others keep today's way


async def test_a_reranked_hybrid_search_is_reranked_by_the_backends_own_ranker() -> None:
    backend = RerankingHere()
    world = await _embedded_world(vector_backend=backend, reranker=True)
    plain = await _embedded_world(vector_backend=InMemoryVectorBackend())
    hybrid = await _search(plain, "repeat failed requests", limit=50)

    result = await _search(world, "repeat failed requests", limit=50)

    assert (result.retrieval_mode, result.reranked, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        True,
        None,
    )
    assert backend.asked == ["reranked:repeat failed requests"]  # one request, the query's text
    assert _texts(result) == list(reversed(_texts(hybrid)))  # the backend's ranker's order
    assert result.coverage.reranked == len(result.results)
    assert world.factory.cross_encoder.seen == []  # ExactDocs' reranker did not rerank again
    assert {r.commit_sha for r in result.results} == {"2" * 40}  # never the other version


async def test_a_search_that_does_not_ask_for_reranking_is_not_reranked_by_the_backend() -> None:
    backend = RerankingHere()
    world = await _embedded_world(vector_backend=backend)  # no reranker: the flag is off

    result = await _search(world, "repeat failed requests")

    assert (result.retrieval_mode, result.reranked) == (RetrievalMode.HYBRID, False)
    assert backend.asked == ["hybrid"]


async def test_an_answer_the_backend_could_not_rerank_is_reranked_by_exactdocs() -> None:
    backend = RerankingHere(partial=True)
    world = await _embedded_world(vector_backend=backend, reranker=True)

    result = await _search(world, "repeat failed requests")

    assert (result.retrieval_mode, result.reranked, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        True,
        None,
    )
    assert backend.asked == ["reranked:repeat failed requests"]
    assert world.factory.cross_encoder.seen  # ExactDocs' own reranker, as without the capability


async def test_a_backend_without_its_own_ranker_leaves_reranking_to_exactdocs() -> None:
    world = await _embedded_world(vector_backend=InMemoryVectorBackend(), reranker=True)

    result = await _search(world, "repeat failed requests")

    assert (result.retrieval_mode, result.reranked) == (RetrievalMode.HYBRID, True)
    assert world.factory.cross_encoder.seen  # today's behaviour


async def test_a_hit_of_another_version_the_ranker_returns_is_dropped() -> None:
    backend = RerankingHere(stray=BackendHit(manifest_id="m1", chunk_id=ChunkId("x"), score=9))
    world = await _embedded_world(vector_backend=backend, reranker=True)

    result = await _search(world, "repeat failed requests", limit=50)

    assert result.reranked
    assert {r.commit_sha for r in result.results} == {"2" * 40}
    assert "x" not in {r.chunk_id for r in result.results}
    assert result.coverage.reranked == len(result.results)


async def test_a_backend_ranker_that_does_not_answer_falls_back_to_bm25() -> None:
    backend = RerankingHere()
    world = await _embedded_world(vector_backend=backend, reranker=True)
    backend.inner.unavailable = True

    result = await _search(world, "RetryPolicy")

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.VECTOR_STORE_UNAVAILABLE,
    )
