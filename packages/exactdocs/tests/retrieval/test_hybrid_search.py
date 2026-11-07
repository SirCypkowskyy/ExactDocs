"""RET-01: hybrid search fuses BM25 and vectors (RRF), within the pinned version only.

The embedding model is in process (``ConceptModels`` below): words of one concept share a
dimension, so "repeat" is near "retry" the way a real model makes paraphrases near, and no
provider is ever called. Versions are embedded as the ``embed`` job does: plan, batches, finish.
"""

import asyncio
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
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    TagFilter,
    identifier_tokens,
    reciprocal_rank_fusion,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import RetrievalPipeline
from exactdocs.retrieval.use_cases import SearchDocsUseCase

LIB = "/acme/payments"
T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
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

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[Span]:
        self.opened.append(Opened(name=name, mode=mode, query=query, attributes=attributes))
        return nullcontext(Span())

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
        if self.owner.behaviour == "fail":
            raise EmbeddingFailedError(self.name, "APIConnectionError")
        if self.owner.behaviour == "hang":
            await asyncio.sleep(10)
        if self.owner.behaviour == "unsupported":
            reason = "it built no embedding model"
            raise ProviderUnsupportedError(CORP.name, reason)
        return EmbeddedTexts(vectors=(_concept_vector(text),), input_tokens=7, requests=1)


@dataclass(slots=True)
class ConceptModels:
    """``EmbeddingModels`` binding ``ConceptEmbeddings``; records every query embedded."""

    behaviour: str = "ok"
    queries: list[str] = field(default_factory=list)

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> ConceptEmbeddings:
        del handle, dimensions, batch_size
        return ConceptEmbeddings(owner=self, name=name)


class Factory:
    """``ModelFactory`` whose embedder handle is a marker (the bound models ignore it)."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        raise ProviderUnsupportedError(profile.name, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> object:
        raise ProviderUnsupportedError(profile.name, model)

    async def release(self, name: str) -> None:
        del name

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
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


def _world(
    *,
    instance: RetrievalMode | None = RetrievalMode.HYBRID,
    embedding: str | None = "concepts",
    wait: float = 5.0,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    models = ConceptModels()
    vectors = InMemoryVectorIndex(chunks=chunks)
    modes = InMemoryLibraryModes()
    ledger = InMemorySpendLedger()
    tracer = RecordingTracer()
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=[CORP],
        instance_roles=InstanceRoles(
            embedding=None if embedding is None else ModelRef(profile="corp", model=embedding)
        ),
        models=Factory(),
        instance_mode=instance,
        clock=Clock(),
        tracer=tracer,
        vectors=vectors,
        embedding_models=models,
        article_titles=catalog,
        spend=ledger,
        query_embedding_timeout=wait,
    )
    return World(
        module=module,
        catalog=catalog,
        models=models,
        vectors=vectors,
        modes=modes,
        ledger=ledger,
        tracer=tracer,
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
    *, instance: RetrievalMode | None = RetrievalMode.HYBRID, wait: float = 5.0
) -> World:
    world = _world(instance=instance, wait=wait)
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


async def test_an_identifier_the_version_lacks_stays_an_explicit_empty_answer() -> None:
    world = await _embedded_world()

    result = await _search(world, "podman")

    assert (result.retrieval_mode, result.results) == (RetrievalMode.HYBRID, [])
    assert (result.coverage.candidates, result.coverage.complete) == (0, True)
    assert world.models.queries == []


async def test_coverage_counts_the_chunks_of_both_halves_once() -> None:
    world = await _embedded_world()

    result = await _search(world, "token", limit=1)

    # BM25 matches 1 chunk; the vectors rank all 5 of the version; the union is 5.
    assert (result.coverage.candidates, result.coverage.complete) == (5, False)
    assert len(result.results) == 1


async def test_the_tag_filter_applies_to_both_halves() -> None:
    world = await _embedded_world()

    result = await _search(world, "retry", tags=["nothing-has-this"])

    assert result.results == []
    assert result.retrieval_mode is RetrievalMode.HYBRID


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
    assert after - before == 7 * 4  # instance and library rows, per day and month


@pytest.mark.parametrize("behaviour", ["fail", "hang", "unsupported"])
async def test_a_failing_or_slow_embedding_answers_bm25_never_fails(behaviour: str) -> None:
    world = await _embedded_world(wait=0.05)
    world.models.behaviour = behaviour

    result = await _search(world, "RetryPolicy")

    assert result.retrieval_mode is RetrievalMode.BM25
    assert result.fallback_reason is FallbackReason.EMBEDDING_UNAVAILABLE
    assert _texts(result)[0] == "Resilience/S0"


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
