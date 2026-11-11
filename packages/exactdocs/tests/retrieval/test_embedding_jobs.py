"""RET-01: every version is embedded in the background, one model's space at a time.

The embedding model is the in-process ``HashEmbeddingModels``: no provider is ever called. The
``embed`` job is played here as ingestion runs it: plan, batches until finished, finish.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

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
    StaticPrices,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    EmbedBatchCommand,
    EmbeddingPlanOut,
    EmbedVersionCommand,
    FinishEmbeddingCommand,
    IndexManifestCommand,
    SearchDocsQuery,
    UnembeddedVersionsQuery,
)
from exactdocs.retrieval.errors import ProviderUnsupportedError, VectorStoreUnavailableError
from exactdocs.retrieval.models import (
    DocTarget,
    EmbeddingSkip,
    EmbeddingSource,
    EmbeddingSpace,
    EmbeddingSpec,
    EmbeddingTarget,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestPaths,
    ManifestStatus,
    ModelCheck,
    ModelRef,
    ModelRole,
    PendingChunks,
    PipelineAnswer,
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    SpaceState,
    SpendWindow,
    embedding_spend,
    embedding_text,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports import VectorIndex
from exactdocs.retrieval.ports.driven import Reranker

LIB = "/acme/payments"
SECRET = "/acme/secret"
T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
PRICES = StaticPrices(input_prices={("openai-compatible", "a"): 0.02})


class Clock:
    def now(self) -> datetime:
        return T0


@dataclass(slots=True)
class Catalog:
    """The catalog: versions with their active manifest and their article titles."""

    versions: dict[tuple[str, str], SearchableVersion] = field(default_factory=dict)
    titles_of: dict[str, dict[str, str]] = field(default_factory=dict)
    """Titles by manifest ID, then by path."""
    asked: list[ManifestPaths] = field(default_factory=list)

    def add(self, library: str, ref: str, manifest: str, titles: dict[str, str]) -> None:
        self.versions[library, ref] = SearchableVersion(
            library=library,
            version=ref,
            manifest_id=manifest,
            commit_sha="c" * 40,
            repository_url="https://github.com/acme/x",
            host=SourceHost.GITHUB,
        )
        self.titles_of[manifest] = titles

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        return self.versions.get((library, ref or ""))

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
        self.asked.append(articles)
        known = self.titles_of.get(articles.manifest_id, {})
        return {p: known[p] for p in articles.paths if p in known}


class Factory:
    """``ModelFactory`` whose embedder handle is a marker (the hash models ignore it)."""

    def __init__(self) -> None:
        self.built: list[str] = []

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        raise ProviderUnsupportedError(profile.name, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        self.built.append(f"{profile.name}:{model}")
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        raise ProviderUnsupportedError(profile.name, model)

    async def release(self, name: str) -> None:
        del name

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


@dataclass(slots=True)
class AnswersHybrid:
    """Stand-in hybrid pipeline: answers ``hybrid`` with no hits, noting the space given."""

    spaces: list[EmbeddingSpace | None] = field(default_factory=list)

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        self.spaces.append(request.space)
        return PipelineAnswer(
            mode=RetrievalMode.HYBRID, hits=(), candidates=0, reranked=0, complete=True
        )


@dataclass(slots=True)
class Stores:
    """What survives a restart: chunks, vectors, settings, ledger and catalog."""

    chunks: InMemoryChunkRepository = field(default_factory=InMemoryChunkRepository)
    catalog: Catalog = field(default_factory=Catalog)
    modes: InMemoryLibraryModes = field(default_factory=InMemoryLibraryModes)
    ledger: InMemorySpendLedger = field(default_factory=InMemorySpendLedger)
    models: HashEmbeddingModels = field(default_factory=HashEmbeddingModels)
    hybrid: AnswersHybrid = field(default_factory=AnswersHybrid)
    vectors: InMemoryVectorIndex = field(init=False)

    def __post_init__(self) -> None:
        self.vectors = InMemoryVectorIndex(chunks=self.chunks)


def _module(
    stores: Stores,
    model: str | None = "a",
    *,
    dimensions: int | None = None,
    batch: int = 2,
    vectors: VectorIndex | Literal["stores"] | None = "stores",
) -> RetrievalModule:
    index = InMemorySearchIndex(chunks=stores.chunks)
    return RetrievalModule.build(
        searchable=stores.catalog,
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=stores.catalog,
        chunks=stores.chunks,
        search=index,
        maintenance=index,
        library_modes=stores.modes,
        configured_profiles=[CORP],
        instance_roles=InstanceRoles(
            embedding=None if model is None else ModelRef(profile="corp", model=model)
        ),
        models=Factory(),
        instance_mode=RetrievalMode.HYBRID,
        pipelines={RetrievalMode.HYBRID: stores.hybrid},
        clock=Clock(),
        vectors=stores.vectors if vectors == "stores" else vectors,
        embedding_models=stores.models,
        article_titles=stores.catalog,
        spend=stores.ledger,
        prices=PRICES,
        embedding_dimensions=dimensions,
        embedding_batch_size=batch,
    )


def _chunk(heading: str, text: str) -> ChunkIn:
    return ChunkIn(
        heading_path=["Guide", heading],
        occurrence_index=0,
        content=text,
        content_hash=f"h-{heading}-{text}",
        anchor=heading.lower(),
    )


async def _import(
    stores: Stores, module: RetrievalModule, library: str, ref: str, blobs: dict[str, list[str]]
) -> str:
    """Index a version: each blob is one article (``docs/<blob>.md``) of these chunk texts."""
    manifest = f"{library}@{ref}"
    await module.index_manifest(
        IndexManifestCommand(
            manifest_id=manifest,
            library=library,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=f"docs/{blob}.md",
                    blob_sha=blob,
                    chunks=[_chunk(f"S{i}", t) for i, t in enumerate(texts)],
                )
                for blob, texts in blobs.items()
            ],
        )
    )
    titles = {f"docs/{blob}.md": f"Title {blob}" for blob in blobs}
    stores.catalog.add(library, ref, manifest, titles)
    return manifest


async def _embed(module: RetrievalModule, library: str, ref: str) -> EmbeddingPlanOut:
    """Run an ``embed`` job of one version as ingestion does."""
    plan = await module.plan_embedding(EmbedVersionCommand(library=library, ref=ref))
    if plan.space_id is None or plan.manifest_id is None:
        return plan
    for _ in range(100):
        batch = await module.embed_batch(
            EmbedBatchCommand(
                library=library, ref=ref, manifest_id=plan.manifest_id, space_id=plan.space_id
            )
        )
        if batch.finished:
            break
    await module.finish_embedding(FinishEmbeddingCommand(space_id=plan.space_id))
    return plan


async def _search(module: RetrievalModule, ref: str) -> tuple[RetrievalMode, object]:
    result = await module.search_docs(SearchDocsQuery(library=LIB, ref=ref, query="token"))
    return result.retrieval_mode, result.fallback_reason


@pytest.fixture
def stores() -> Stores:
    return Stores()


async def _two_versions(stores: Stores, module: RetrievalModule) -> None:
    await _import(stores, module, LIB, "v1", {"b1": ["token one", "token two", "three"]})
    await _import(
        stores, module, LIB, "v2", {"b1": ["token one", "token two", "three"], "b2": ["token four"]}
    )


# ---------------------------------------------------------------- what is embedded


def test_a_chunk_is_embedded_with_its_article_title_and_heading_path() -> None:
    source = EmbeddingSource(
        article_path="docs/a.md", heading_path=("Guide", "Retries"), content="Body"
    )

    assert embedding_text("Payments guide", source) == "Payments guide\nGuide > Retries\n\nBody"
    assert embedding_text("", source) == "Guide > Retries\n\nBody"
    bare = EmbeddingSource(article_path="docs/a.md", heading_path=(), content="Body")
    assert embedding_text(" ", bare) == "Body"


async def test_a_version_is_embedded_in_batches_from_title_headings_and_text(
    stores: Stores,
) -> None:
    module = _module(stores, batch=2)
    await _import(stores, module, LIB, "v1", {"b1": ["token one", "token two", "three"]})

    plan = await _embed(module, LIB, "v1")

    assert (plan.missing, plan.created, plan.skipped) == (3, True, None)
    assert "Title b1\nGuide > S0\n\ntoken one" in stores.models.sent
    assert len(stores.models.sent) == 3
    assert stores.models.calls == ["corp:a", "corp:a"]  # two batches of at most 2
    (space,) = await stores.vectors.spaces()
    assert space.spec == EmbeddingSpec(profile_kind="openai-compatible", model="a", dimensions=8)
    assert space.state is SpaceState.ACTIVE  # it covers every version
    assert (await stores.vectors.coverage(space.id, "/acme/payments@v1")).complete


async def test_a_blob_shared_by_two_versions_is_embedded_once(stores: Stores) -> None:
    module = _module(stores)
    await _two_versions(stores, module)

    await _embed(module, LIB, "v1")
    await _embed(module, LIB, "v2")

    assert len(stores.models.sent) == 4  # three chunks of b1, once; one of b2


async def test_configured_dimensions_are_used_without_asking_the_model(stores: Stores) -> None:
    module = _module(stores, dimensions=4)
    await _import(stores, module, LIB, "v1", {"b1": ["token one"]})

    await _embed(module, LIB, "v1")

    (space,) = await stores.vectors.spaces()
    assert space.spec.dimensions == 4


async def test_usage_is_recorded_in_the_spend_ledger_per_day_and_month(stores: Stores) -> None:
    module = _module(stores, batch=10)
    await _import(stores, module, LIB, "v1", {"b1": ["token one", "token two"]})

    await _embed(module, LIB, "v1")

    tokens = sum(-(-len(t) // 4) for t in stores.models.sent)
    # The rows LLM spend uses too (the instance's and the library's) and the embedding budget's,
    # per UTC day and month.
    assert {
        (k.scope_kind, k.scope_id, k.window, k.window_start.isoformat()) for k in stores.ledger.rows
    } == {
        ("embedding", "", SpendWindow.DAY, "2026-11-07"),
        ("embedding", "", SpendWindow.MONTH, "2026-11-01"),
        ("instance", "", SpendWindow.DAY, "2026-11-07"),
        ("instance", "", SpendWindow.MONTH, "2026-11-01"),
        ("library", LIB, SpendWindow.DAY, "2026-11-07"),
        ("library", LIB, SpendWindow.MONTH, "2026-11-01"),
    }
    for row in stores.ledger.rows.values():
        assert (row.input_tokens, row.requests, row.unpriced) == (tokens, 1, 0)
        assert row.usd_micros == round(tokens * 0.02)  # $0.02 per million: micros per token


def test_spend_without_a_price_counts_tokens_and_marks_the_requests_unpriced() -> None:
    entries = embedding_spend(T0, library=LIB, input_tokens=10, requests=2, usd_per_million=None)

    assert [(e.scope_kind, e.scope_id, e.window_start) for e in entries] == [
        ("embedding", "", date(2026, 11, 7)),
        ("embedding", "", date(2026, 11, 1)),
        ("instance", "", date(2026, 11, 7)),
        ("instance", "", date(2026, 11, 1)),
        ("library", LIB, date(2026, 11, 7)),
        ("library", LIB, date(2026, 11, 1)),
    ]
    assert {(e.input_tokens, e.usd_micros, e.unpriced) for e in entries} == {(10, 0, 2)}


# ---------------------------------------------------------------- without a usable vector store


async def test_without_a_vector_store_nothing_is_embedded_queued_or_estimated(
    stores: Stores,
) -> None:
    module = _module(stores, vectors=None)
    await _import(stores, module, LIB, "v1", {"b1": ["token one"]})

    plan = await _embed(module, LIB, "v1")
    listed = await module.list_unembedded_versions(UnembeddedVersionsQuery())

    assert plan.skipped is EmbeddingSkip.VECTOR_STORE_UNAVAILABLE
    assert (listed.versions, stores.models.sent) == ([], [])
    with pytest.raises(VectorStoreUnavailableError, match="no vector store"):
        await module.estimate_embedding()


async def test_a_store_that_cannot_load_is_never_sent_to(stores: Stores) -> None:
    # pgvector's `vector` is not in the PostgreSQL database (or sqlite-vec does not load).
    module = _module(stores, vectors=InMemoryVectorIndex(chunks=stores.chunks, can_search=False))
    await _import(stores, module, LIB, "v1", {"b1": ["token one"]})

    plan = await _embed(module, LIB, "v1")
    estimate = await module.estimate_embedding()

    assert plan.skipped is EmbeddingSkip.VECTOR_STORE_UNAVAILABLE
    assert stores.models.sent == []  # not even the dimensions probe
    assert estimate.chunks == 1  # counting needs no extension


# ---------------------------------------------------------------- opting out


async def test_a_library_with_ai_off_is_never_sent(stores: Stores) -> None:
    module = _module(stores)
    await _import(stores, module, SECRET, "v1", {"s1": ["secret token"]})
    await stores.modes.save(SECRET, None, LibraryAi(enabled=False))

    plan = await _embed(module, SECRET, "v1")
    listed = await module.list_unembedded_versions(UnembeddedVersionsQuery())

    assert plan.skipped is EmbeddingSkip.AI_OFF
    assert stores.models.sent == []
    assert await stores.vectors.spaces() == []  # not even its dimensions were asked
    assert listed.versions == []


async def test_a_library_switched_off_mid_run_stops_sending(stores: Stores) -> None:
    module = _module(stores, batch=1)
    await _import(stores, module, SECRET, "v1", {"s1": ["one", "two", "three"]})
    plan = await module.plan_embedding(EmbedVersionCommand(library=SECRET, ref="v1"))
    assert plan.space_id is not None
    assert plan.manifest_id is not None
    command = EmbedBatchCommand(
        library=SECRET, ref="v1", manifest_id=plan.manifest_id, space_id=plan.space_id
    )
    await module.embed_batch(command)

    await stores.modes.save(SECRET, None, LibraryAi(enabled=False))
    batch = await module.embed_batch(command)

    assert (batch.embedded, batch.finished) == (0, True)
    assert len(stores.models.sent) == 1


async def test_without_an_embedding_model_nothing_is_planned(stores: Stores) -> None:
    module = _module(stores, model=None)
    await _import(stores, module, LIB, "v1", {"b1": ["token"]})

    plan = await _embed(module, LIB, "v1")
    listed = await module.list_unembedded_versions(UnembeddedVersionsQuery())
    estimate = await module.estimate_embedding()

    assert plan.skipped is EmbeddingSkip.NO_MODEL
    assert listed.versions == []
    assert (estimate.model, estimate.chunks) == (None, 0)


async def test_a_version_gone_meanwhile_is_skipped(stores: Stores) -> None:
    module = _module(stores)

    plan = await _embed(module, LIB, "v9")

    assert plan.skipped is EmbeddingSkip.NO_VERSION


# ---------------------------------------------------------------- switching models


async def test_changing_the_model_re_embeds_instead_of_mixing_vectors(stores: Stores) -> None:
    first = _module(stores, model="a")
    await _two_versions(stores, first)
    await _embed(first, LIB, "v1")
    await _embed(first, LIB, "v2")
    assert await _search(first, "v2") == (RetrievalMode.HYBRID, None)

    second = _module(stores, model="b")  # the operator switched models
    listed = await second.list_unembedded_versions(UnembeddedVersionsQuery())
    assert [(v.library, v.ref) for v in listed.versions] == [(LIB, "v1"), (LIB, "v2")]
    assert await _search(second, "v2") == (RetrievalMode.BM25, FallbackReason.EMBEDDING_IN_PROGRESS)

    plan = await _embed(second, LIB, "v1")
    old, new = await stores.vectors.spaces()
    assert plan.created
    assert (old.state, new.state) == (SpaceState.ACTIVE, SpaceState.BUILDING)  # v2 is not covered
    assert await _search(second, "v1") == (RetrievalMode.HYBRID, None)
    assert stores.hybrid.spaces[-1] == new  # the pipeline searches the space the gate checked
    assert await _search(second, "v2") == (RetrievalMode.BM25, FallbackReason.EMBEDDING_IN_PROGRESS)

    await _embed(second, LIB, "v2")
    old, new = await stores.vectors.spaces()
    assert (old.state, new.state) == (SpaceState.RETIRED, SpaceState.ACTIVE)
    assert (new.spec.model, old.spec.model) == ("b", "a")
    assert await _search(second, "v2") == (RetrievalMode.HYBRID, None)
    assert (await second.list_unembedded_versions(UnembeddedVersionsQuery())).versions == []


async def test_switching_back_to_a_model_retires_the_space_left_half_filled(
    stores: Stores,
) -> None:
    first = _module(stores, model="a", batch=1)
    await _two_versions(stores, first)
    await _embed(first, LIB, "v1")
    await _embed(first, LIB, "v2")
    second = _module(stores, model="b", batch=1)
    await _embed(second, LIB, "v1")  # B covers v1 only: it stays building
    a, b = await stores.vectors.spaces()
    assert (a.state, b.state) == (SpaceState.ACTIVE, SpaceState.BUILDING)

    back = _module(stores, model="a", batch=1)  # the operator switched back to A
    await _embed(back, LIB, "v1")

    a, b = await stores.vectors.spaces()
    assert (a.state, b.state) == (SpaceState.ACTIVE, SpaceState.RETIRED)  # newer, yet retired


async def test_titles_are_read_once_per_batch_from_the_plans_manifest(stores: Stores) -> None:
    module = _module(stores, batch=10)
    manifest = await _import(stores, module, LIB, "v1", {"b1": ["one"], "b2": ["two", "three"]})

    await _embed(module, LIB, "v1")

    assert stores.catalog.asked == [
        ManifestPaths(manifest_id=manifest, paths=("docs/b1.md", "docs/b2.md"))
    ]


async def test_a_batch_of_a_model_no_longer_configured_sends_nothing(stores: Stores) -> None:
    first = _module(stores, model="a", batch=1)
    await _import(stores, first, LIB, "v1", {"b1": ["one", "two"]})
    plan = await first.plan_embedding(EmbedVersionCommand(library=LIB, ref="v1"))
    assert plan.space_id is not None
    assert plan.manifest_id is not None
    second = _module(stores, model="b", batch=1)

    batch = await second.embed_batch(
        EmbedBatchCommand(
            library=LIB, ref="v1", manifest_id=plan.manifest_id, space_id=plan.space_id
        )
    )
    finished = await second.finish_embedding(FinishEmbeddingCommand(space_id=plan.space_id))

    assert (batch.embedded, batch.finished) == (0, True)
    assert stores.models.sent == []
    assert (finished.state, finished.retired) == (SpaceState.BUILDING, [])


async def test_a_library_with_ai_off_does_not_hold_back_the_switch(stores: Stores) -> None:
    module = _module(stores)
    await _import(stores, module, LIB, "v1", {"b1": ["token"]})
    await _import(stores, module, SECRET, "v1", {"s1": ["secret"]})
    await stores.modes.save(SECRET, None, LibraryAi(enabled=False))

    await _embed(module, LIB, "v1")

    (space,) = await stores.vectors.spaces()
    assert space.state is SpaceState.ACTIVE


async def test_a_search_without_an_embedding_model_is_left_to_the_pipeline(stores: Stores) -> None:
    module = _module(stores, model=None)
    await _import(stores, module, LIB, "v1", {"b1": ["token"]})

    found = await module.search_docs(
        SearchDocsQuery(library=LIB, ref="v1", query="token", mode="bm25")
    )

    assert found.fallback_reason is None


# ---------------------------------------------------------------- the estimate


async def test_the_estimate_counts_each_chunk_once_and_calls_no_model(stores: Stores) -> None:
    module = _module(stores)
    await _two_versions(stores, module)

    estimate = await module.estimate_embedding()

    texts = ["token one", "token two", "three", "token four"]
    characters = sum(len(t) + len("Guide") + len(f"S{i}") for i, t in enumerate(texts[:3]))
    characters += len("token four") + len("Guide") + len("S0")
    # Each chunk is embedded with its article's title: b1's three once (under v1), b2's one.
    characters += 3 * len("Title b1") + len("Title b2")
    assert (estimate.model, estimate.space_id, estimate.versions) == ("corp:a", None, 2)
    assert (estimate.chunks, estimate.characters) == (4, characters)
    assert estimate.estimated_tokens == -(-characters // 4)
    assert estimate.usd_per_million_tokens == pytest.approx(0.02)
    assert estimate.estimated_usd == pytest.approx(estimate.estimated_tokens * 0.02 / 1_000_000)
    assert "4 characters per token" in estimate.note
    assert stores.models.sent == []


async def test_the_estimate_leaves_out_what_is_embedded_and_libraries_with_ai_off(
    stores: Stores,
) -> None:
    module = _module(stores, model="unpriced")
    await _two_versions(stores, module)
    await _import(stores, module, SECRET, "v1", {"s1": ["secret"]})
    await stores.modes.save(SECRET, None, LibraryAi(enabled=False))
    await _embed(module, LIB, "v1")

    estimate = await module.estimate_embedding()

    assert (estimate.versions, estimate.chunks) == (2, 1)  # b2's one chunk is left
    assert (estimate.usd_per_million_tokens, estimate.estimated_usd) == (None, None)


def test_pending_chunks_round_tokens_up() -> None:
    assert PendingChunks(chunks=1, characters=9).estimated_tokens == 3
    assert PendingChunks(chunks=0, characters=0).estimated_tokens == 0


def test_a_target_matches_its_spaces_whatever_their_size_unless_one_is_configured() -> None:
    spec = EmbeddingSpec(profile_kind="openai", model="a", dimensions=384)

    assert EmbeddingTarget(profile_kind="openai", model="a").matches(spec)
    assert EmbeddingTarget(profile_kind="openai", model="a", dimensions=384).matches(spec)
    assert not EmbeddingTarget(profile_kind="openai", model="a", dimensions=256).matches(spec)
    assert not EmbeddingTarget(profile_kind="azure", model="a").matches(spec)
    assert not EmbeddingTarget(profile_kind="openai", model="a", input_format=2).matches(spec)
