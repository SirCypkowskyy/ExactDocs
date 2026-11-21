"""RET-03: HyDE writes a hypothetical answer with the ``llm`` role; its embedding searches vectors.

The LLM is pydantic-ai's ``FunctionModel`` behind the real HyDE writer (``Agent(output_type=str)``
inside the harness ``SpendLimits`` over the ledger), so no provider is ever called. The embedding
model is in process: words of one concept share a dimension, so a hypothetical answer that names
the docs' terms lands near their chunks while the question's words do not.
"""

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Collection, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.ai_hyde import PydanticAiHypotheticalAnswers
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryCallRates,
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryHypothesisCache,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
    InMemoryVectorIndex,
    ReadOnlyHypothesisCache,
)
from exactdocs.retrieval.adapters.driven.sqlite import SqliteHypothesisCache, SqliteLibraryModes
from exactdocs.retrieval.constants import HYDE_INSTRUCTIONS, HYDE_MAX_TOKENS
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    CollectChunksCommand,
    EmbedBatchCommand,
    EmbedVersionCommand,
    FinishEmbeddingCommand,
    IndexManifestCommand,
    RemoveChunksCommand,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.errors import LlmBudgetReachedError, LlmFailedError
from exactdocs.retrieval.models import (
    AiCaller,
    BudgetLimit,
    Budgets,
    DocTarget,
    EmbeddedTexts,
    FallbackReason,
    HydeKey,
    HypotheticalAnswer,
    InstanceRoles,
    LibraryAi,
    LlmStep,
    ManifestPaths,
    ManifestStatus,
    ModelCheck,
    ModelPrice,
    ModelRef,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    SpendEntry,
    SpendWindow,
    ThinkingLevel,
    identifier_tokens,
    normalized_query,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import (
    HypotheticalAnswerCache,
    HypotheticalAnswers,
    Reranker,
)

LIB = "/acme/payments"
T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
BOX = ProviderProfile(name="box", kind=ProviderKind.LOCAL, origin=ProfileOrigin.CONFIGURATION)
"""An in-process profile: its models cost nothing, so no budget ever stops them."""
WRITER = ModelRef(profile="corp", model="writer")
CONCEPTS = {"retry": 1, "retrypolicy": 1, "backoff": 1, "token": 2, "rotate": 2, "cursor": 3}
"""Words of one concept share a dimension; other words share the last one."""
SIZE = 5
GUIDE = {
    "resilience": [
        "RetryPolicy decides how often a failed call runs again.",
        "Calls that time out are sent once more after a short pause (backoff).",
    ],
    "auth": ["Rotate the API token without downtime."],
    "paging": ["Use the cursor to read the next page."],
}
OLD_GUIDE = {"resilience-old": ["RetryPolicy retries three times in v1."]}
QUESTION = "what happens when my network is flaky"
"""Shares no word with any chunk: BM25 finds nothing, the question's own embedding nothing near."""
HYPOTHESIS = "The RetryPolicy retries a failed call with backoff."


KEY = b"k" * 32
"""The instance's HyDE cache key in these tests."""


@dataclass(slots=True)
class Clock:
    at: datetime = T0

    def now(self) -> datetime:
        return self.at


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

    def fallback(self, *, mode: str, reason: str) -> None:
        del mode, reason

    def cache_hit(self, *, cache: str, mode: str) -> None:
        del cache, mode


def _concept_vector(text: str) -> tuple[float, ...]:
    values = [0.0] * SIZE
    values[0] = 0.01
    for term in identifier_tokens(text).split():
        values[CONCEPTS.get(term, SIZE - 1)] += 1.0 if term in CONCEPTS else 0.01
    return tuple(values)


@dataclass(slots=True)
class ConceptEmbeddings:
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
        return EmbeddedTexts(vectors=(_concept_vector(text),), input_tokens=7, requests=1)


@dataclass(slots=True)
class ConceptModels:
    """``EmbeddingModels`` binding ``ConceptEmbeddings``; records every text embedded at search."""

    queries: list[str] = field(default_factory=list)

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> ConceptEmbeddings:
        del handle, dimensions, batch_size
        return ConceptEmbeddings(owner=self, name=name)


@dataclass(slots=True)
class Llm:
    """The ``llm`` role: a ``FunctionModel`` answering ``answer``, or failing as ``behaviour`` says.

    Records the prompts and the settings of every call.
    """

    answer: str = HYPOTHESIS
    behaviour: str = "ok"
    prompts: list[str] = field(default_factory=list)
    instructions: list[str | None] = field(default_factory=list)
    settings: list[Mapping[str, Any] | None] = field(default_factory=list)

    async def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.prompts.extend(
            str(part.content)
            for message in messages
            for part in getattr(message, "parts", ())
            if part.part_kind == "user-prompt"
        )
        self.instructions.append(info.instructions)
        self.settings.append(dict(info.model_settings or {}))
        if self.behaviour == "fail":
            message = f"provider echoed {self.prompts[-1]} and sk-secret"
            raise RuntimeError(message)
        if self.behaviour == "hang":
            await asyncio.sleep(10)
        return ModelResponse(parts=[TextPart(content=self.answer)])

    def model(self) -> FunctionModel:
        return FunctionModel(self.respond, model_name="writer")


@dataclass(slots=True)
class Factory:
    """``ModelFactory``: the chat model is the ``Llm``'s; the embedder a marker."""

    llm: Llm

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
        del profile, model
        return self.llm.model()

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        raise NotImplementedError

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
        return {m: ManifestStatus.ACTIVE for m in manifest_ids if m in active}

    async def titles(self, articles: ManifestPaths) -> Mapping[str, str]:
        return {p: p for p in articles.paths}


@dataclass(slots=True)
class SlowWriter:
    """A ``HypotheticalAnswers`` that never answers in time."""

    async def write(self, model: object, query: str, *, step: LlmStep) -> HypotheticalAnswer:
        del model, query, step
        await asyncio.sleep(10)
        return HypotheticalAnswer(text=HYPOTHESIS)


@dataclass(slots=True)
class BrokenCache:
    """A ``HypotheticalAnswerCache`` whose database fails, with a message holding stored text."""

    answers: dict[HydeKey, str] = field(default_factory=dict)
    reads: int = 0

    async def get(self, key: HydeKey) -> str | None:
        del key
        self.reads += 1
        message = f"database is locked while reading {HYPOTHESIS}"
        raise OSError(message)

    async def put(self, key: HydeKey, answer: str, at: datetime) -> None:
        del key, at
        message = f"database is locked while writing {answer}"
        raise OSError(message)

    async def forget(self, manifest_ids: Collection[str]) -> int:
        del manifest_ids
        return 0

    async def prune(self, written_before: datetime, keep_models: Collection[str]) -> int:
        del written_before, keep_models
        return 0


@dataclass(slots=True)
class RefusingWriter:
    """A ``HypotheticalAnswers`` whose budget check refuses at the request (``SpendLimits``)."""

    async def write(self, model: object, query: str, *, step: LlmStep) -> HypotheticalAnswer:
        del model, query, step
        raise LlmBudgetReachedError(str(WRITER))


@dataclass(slots=True)
class World:
    module: RetrievalModule
    catalog: Catalog
    models: ConceptModels
    llm: Llm
    ledger: InMemorySpendLedger
    cache: InMemoryHypothesisCache | BrokenCache | CountingCache
    tracer: RecordingTracer
    modes: InMemoryLibraryModes


def _world(
    *,
    instance: RetrievalMode | None = RetrievalMode.HYBRID_HYDE,
    llm: Llm | None = None,
    writer: HypotheticalAnswers | None = None,
    budgets: Budgets | None = None,
    hyde_timeout: float = 5.0,
    embedding_profile: str = "corp",
    cache: BrokenCache | CountingCache | None = None,
    clock: Clock | None = None,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    models = ConceptModels()
    llm = llm or Llm()
    ledger = InMemorySpendLedger()
    store: InMemoryHypothesisCache | BrokenCache | CountingCache = (
        cache or InMemoryHypothesisCache()
    )
    clock = clock or Clock()
    tracer = RecordingTracer()
    modes = InMemoryLibraryModes()
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=[CORP, BOX],
        instance_roles=InstanceRoles(
            embedding=ModelRef(profile=embedding_profile, model="e"), llm=WRITER
        ),
        models=Factory(llm=llm),
        instance_mode=instance,
        clock=clock,
        tracer=tracer,
        vectors=InMemoryVectorIndex(chunks=chunks),
        embedding_models=models,
        article_titles=catalog,
        spend=ledger,
        price_overrides={str(WRITER): ModelPrice(input_usd_per_million=1.0)},
        budgets=budgets,
        call_rates=InMemoryCallRates(),
        hypotheses=writer or PydanticAiHypotheticalAnswers(ledger=ledger),
        hypothesis_cache=store,
        hyde_timeout=hyde_timeout,
        hyde_cache_key=KEY,
        hyde_cache_ttl=timedelta(days=30),
    )
    return World(
        module=module,
        catalog=catalog,
        models=models,
        llm=llm,
        ledger=ledger,
        cache=store,
        tracer=tracer,
        modes=modes,
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
                    blob_sha=f"{blob}-{manifest}",
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
                for blob, texts in blobs.items()
            ],
        )
    )
    world.catalog.add(ref, manifest)
    plan = await world.module.plan_embedding(EmbedVersionCommand(library=LIB, ref=ref))
    assert plan.space_id is not None, plan
    assert plan.manifest_id is not None, plan
    for _ in range(100):
        batch = await world.module.embed_batch(
            EmbedBatchCommand(
                library=LIB, ref=ref, manifest_id=plan.manifest_id, space_id=plan.space_id
            )
        )
        if batch.finished:
            break
    await world.module.finish_embedding(FinishEmbeddingCommand(space_id=plan.space_id))


async def _ready(**kwargs: Any) -> World:
    world = _world(**kwargs)
    await _import(world, "v1", "m1", OLD_GUIDE)
    await _import(world, "v2", "m2", GUIDE)
    world.models.queries.clear()
    return world


async def _search(
    world: World, query: str = QUESTION, *, ref: str = "v2", mode: str | None = None
) -> SearchDocsResult:
    return await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref=ref, query=query, mode=mode, limit=3)
    )


def _texts(result: SearchDocsResult) -> list[str]:
    return [r.heading_path[0] + "/" + r.heading_path[1] for r in result.results]


# ---------------------------------------------------------------- the hypothetical answer


async def test_the_hypothetical_answer_searches_the_vectors_and_bm25_keeps_the_query() -> None:
    world = await _ready()
    plain = await _search(world, mode="hybrid")
    world.models.queries.clear()

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID_HYDE, None)
    assert _texts(result)[:2] == ["Resilience/S0", "Resilience/S1"]
    assert _texts(plain)[:2] != _texts(result)[:2], "the question alone finds no resilience"
    assert world.models.queries == [HYPOTHESIS]  # the answer is embedded, not the question
    assert world.llm.prompts == [QUESTION]  # the LLM gets the query and nothing else


async def test_the_llm_runs_with_the_fixed_instructions_and_a_token_cap() -> None:
    world = await _ready()

    await _search(world)

    assert world.llm.instructions == [HYDE_INSTRUCTIONS]
    assert world.llm.settings[0] is not None
    assert world.llm.settings[0]["max_tokens"] == HYDE_MAX_TOKENS


async def test_no_chunk_of_another_version_is_returned() -> None:
    world = await _ready()

    result = await _search(world, "RetryPolicy retries")

    assert result.retrieval_mode is RetrievalMode.HYBRID_HYDE
    assert {r.commit_sha for r in result.results} == {"2" * 40}
    assert all(r.article_path != "docs/resilience-old.md" for r in result.results)


async def test_hyde_is_no_default_until_the_eval_suite_makes_it_one() -> None:
    world = await _ready(instance=None)

    result = await _search(world)

    assert result.retrieval_mode is RetrievalMode.BM25
    assert world.llm.prompts == []


async def test_the_step_is_a_span_of_its_own_without_the_query() -> None:
    world = await _ready()

    await _search(world)

    hyde = [o for o in world.tracer.opened if o.name == "search_docs.hyde"]
    assert [(o.mode, o.query) for o in hyde] == [("hybrid_hyde", None)]
    assert all(QUESTION not in str(o.attributes) for o in world.tracer.opened)


# ---------------------------------------------------------------- the cache


async def test_a_repeated_query_of_the_version_reuses_the_hypothetical_answer() -> None:
    world = await _ready()

    first = await _search(world)
    again = await _search(world, f"  {QUESTION.upper()} ")

    assert world.llm.prompts == [QUESTION]
    assert again.retrieval_mode is RetrievalMode.HYBRID_HYDE
    assert _texts(again) == _texts(first)
    assert world.models.queries == [HYPOTHESIS, HYPOTHESIS]


async def test_the_cache_holds_a_hash_of_the_query_never_its_text() -> None:
    world = await _ready()

    await _search(world)

    (key,) = world.cache.answers
    assert key == HydeKey.of("m2", WRITER, QUESTION, key=KEY)
    assert QUESTION not in repr(key)
    assert world.cache.answers[key] == HYPOTHESIS


async def test_another_version_or_model_gets_its_own_answer() -> None:
    world = await _ready()

    await _search(world, ref="v2")
    await _search(world, ref="v1")
    await world.modes.save(LIB, None, LibraryAi(llm=ModelRef(profile="corp", model="other")))
    await _search(world, ref="v2")

    assert world.llm.prompts == [QUESTION] * 3
    assert {k.model for k in world.cache.answers} == {"corp:writer", "corp:other"}


async def test_a_new_manifest_of_the_version_invalidates_and_collection_deletes() -> None:
    world = await _ready()
    await _search(world)

    await _import(world, "v2", "m3", GUIDE)  # a new commit of v2
    await _search(world)
    assert world.llm.prompts == [QUESTION, QUESTION]

    removed = await world.module.remove_chunks(RemoveChunksCommand(manifest_ids=["m2"]))

    assert removed.manifests == 1
    assert {k.manifest_id for k in world.cache.answers} == {"m3"}


def test_queries_are_normalized_by_case_and_whitespace() -> None:
    assert normalized_query("  How   do I\tRETRY ") == "how do i retry"
    assert HydeKey.of("m", WRITER, "Retry  calls", key=KEY) == HydeKey.of(
        "m", WRITER, "retry calls", key=KEY
    )


async def test_a_read_only_process_reads_shared_answers_and_keeps_its_own() -> None:
    shared = InMemoryHypothesisCache()
    key = HydeKey.of("m", WRITER, "q", key=KEY)
    other = HydeKey.of("m", WRITER, "r", key=KEY)
    await shared.put(key, "shared", T0)
    cache = ReadOnlyHypothesisCache(shared=shared)

    await cache.put(other, "mine", T0)

    assert (await cache.get(key), await cache.get(other)) == ("shared", "mine")
    assert other not in shared.answers
    assert await cache.forget(["m"]) == 1
    assert key in shared.answers


async def test_a_cache_that_cannot_be_read_is_a_miss_and_logs_only_the_error_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = BrokenCache()
    world = await _ready(cache=broken)

    with caplog.at_level(logging.DEBUG):
        result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.HYBRID_HYDE, None)
    assert broken.reads >= 1
    assert world.llm.prompts == [QUESTION]  # asked instead, and the write failing is no error
    assert "OSError" in caplog.text
    assert HYPOTHESIS not in caplog.text
    assert QUESTION not in caplog.text


def test_the_query_hash_is_keyed_by_the_instance() -> None:
    mine = HydeKey.of("m", WRITER, QUESTION, key=KEY)
    other = HydeKey.of("m", WRITER, QUESTION, key=b"x" * 32)

    assert mine.query_hash != other.query_hash
    assert mine.query_hash != hashlib.sha256(normalized_query(QUESTION).encode()).hexdigest()


async def test_the_in_memory_cache_keeps_the_most_recently_used_answers() -> None:
    cache = InMemoryHypothesisCache(max_entries=2)
    a, b, c = (HydeKey.of("m", WRITER, q, key=KEY) for q in ("a", "b", "c"))
    await cache.put(a, "A", T0)
    await cache.put(b, "B", T0)
    assert await cache.get(a) == "A"  # a is now the most recently used

    await cache.put(c, "C", T0)

    assert (await cache.get(a), await cache.get(b), await cache.get(c)) == ("A", None, "C")


async def test_collection_prunes_old_answers_and_those_of_models_no_longer_configured() -> None:
    clock = Clock()
    world = await _ready(clock=clock)
    await _search(world)  # corp:writer, at T0
    await world.modes.save(LIB, None, LibraryAi(llm=ModelRef(profile="corp", model="other")))
    await _search(world)  # corp:other
    await world.modes.save(LIB, None, LibraryAi(llm=ModelRef(profile="gone", model="x")))
    stale = HydeKey.of("m2", ModelRef(profile="gone", model="x"), QUESTION, key=KEY)
    await world.cache.put(stale, "orphan", T0)
    await world.modes.save(LIB, None, LibraryAi())  # back to the instance's model
    assert len(world.cache.answers) == 3

    await world.module.collect_chunks(CollectChunksCommand(grace_seconds=0))

    # corp:other is no library's model any more, and profile "gone" does not exist.
    assert {k.model for k in world.cache.answers} == {"corp:writer"}

    clock.at = T0 + timedelta(days=31)
    await world.module.collect_chunks(CollectChunksCommand(grace_seconds=0))

    assert world.cache.answers == {}


async def test_a_library_override_keeps_its_answers_through_collection() -> None:
    world = await _ready()
    await world.modes.save(LIB, None, LibraryAi(llm=ModelRef(profile="corp", model="other")))
    await _search(world)

    await world.module.collect_chunks(CollectChunksCommand(grace_seconds=0))

    assert {k.model for k in world.cache.answers} == {"corp:other"}


async def test_cancelling_a_search_while_the_llm_writes_propagates_and_caches_nothing() -> None:
    started = asyncio.Event()

    @dataclass(slots=True)
    class Waiting(Llm):
        async def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            del messages, info
            started.set()
            await asyncio.sleep(10)
            return ModelResponse(parts=[TextPart(content=HYPOTHESIS)])

    world = await _ready(llm=Waiting())
    task = asyncio.create_task(_search(world))
    await asyncio.wait_for(started.wait(), timeout=5)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert world.cache.answers == {}


# ---------------------------------------------------------------- budgets and failures


async def test_the_step_counts_to_the_callers_budgets_in_the_ledger() -> None:
    world = await _ready()
    world.ledger.rows.clear()  # what embedding the versions cost

    await _search(world)

    rows = {(k.scope_kind, k.window): row for k, row in world.ledger.rows.items()}
    assert {kind for kind, _ in rows} == {"embedding", "instance", "library"}
    day = rows["instance", SpendWindow.DAY]
    # The embedding of the hypothetical answer (7 tokens, unpriced) and the LLM step (priced)
    # both count.
    assert day.requests == 2
    assert day.input_tokens > 7
    assert day.usd_micros > 0
    assert rows["library", SpendWindow.DAY].requests == 2


async def test_a_used_up_budget_answers_hybrid_without_calling_the_llm() -> None:
    budgets = Budgets(
        limits=(BudgetLimit(scope_kind="instance", window=SpendWindow.DAY, tokens=10),)
    )
    # The query's embedding is in process (free), so the budget stops the LLM step only.
    world = await _ready(budgets=budgets, embedding_profile="box")
    await world.ledger.add(
        [
            SpendEntry(
                scope_kind="instance",
                scope_id="",
                window=SpendWindow.DAY,
                window_start=T0.date(),
                input_tokens=10,
            )
        ]
    )

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    assert world.llm.prompts == []
    assert world.models.queries == [QUESTION]


async def test_a_cached_answer_still_answers_hyde_when_the_budget_is_used_up() -> None:
    budgets = Budgets(
        limits=(BudgetLimit(scope_kind="instance", window=SpendWindow.DAY, tokens=10),)
    )
    world = await _ready(budgets=budgets, embedding_profile="box")
    world.ledger.rows.clear()
    await _search(world)  # written within the budget, which it then uses up
    assert world.llm.prompts == [QUESTION]
    await world.ledger.add(
        [
            SpendEntry(
                scope_kind="instance",
                scope_id="",
                window=SpendWindow.DAY,
                window_start=T0.date(),
                input_tokens=10,
            )
        ]
    )

    again = await _search(world)

    assert (again.retrieval_mode, again.fallback_reason) == (RetrievalMode.HYBRID_HYDE, None)
    assert world.llm.prompts == [QUESTION]  # no second call
    other = await _search(world, "something else entirely")
    assert (other.retrieval_mode, other.fallback_reason) == (
        RetrievalMode.HYBRID,
        FallbackReason.LLM_BUDGET_REACHED,
    )


async def test_a_cache_hit_is_not_counted_against_the_rate_limit() -> None:
    world = await _ready(budgets=Budgets(llm_searches_per_minute=1))
    query = SearchDocsQuery(library=LIB, ref="v2", query=QUESTION, limit=3)

    results = [await world.module.search_docs(query, caller="ada") for _ in range(3)]

    assert [r.retrieval_mode for r in results] == [RetrievalMode.HYBRID_HYDE] * 3
    assert world.llm.prompts == [QUESTION]
    fresh = SearchDocsQuery(library=LIB, ref="v2", query="another question", limit=3)
    limited = await world.module.search_docs(fresh, caller="ada")
    assert limited.fallback_reason is FallbackReason.LLM_RATE_LIMITED


async def test_a_librarys_own_tighter_budget_stops_the_llm_step() -> None:
    world = await _ready(embedding_profile="box")  # no instance budget at all
    own = BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=10)
    await world.modes.save(LIB, None, LibraryAi(budgets=(own,)))
    await world.ledger.add(
        [
            SpendEntry(
                scope_kind="library",
                scope_id=LIB,
                window=SpendWindow.DAY,
                window_start=T0.date(),
                input_tokens=10,
            )
        ]
    )

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    assert world.llm.prompts == []


@dataclass(slots=True)
class RecordingWriter:
    """A ``HypotheticalAnswers`` that keeps the step it was given."""

    steps: list[LlmStep] = field(default_factory=list)

    async def write(self, model: object, query: str, *, step: LlmStep) -> HypotheticalAnswer:
        del model, query
        self.steps.append(step)
        return HypotheticalAnswer(text=HYPOTHESIS)


async def test_the_agent_runs_within_the_librarys_merged_budgets() -> None:
    instance = BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=1_000_000)
    own = BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=500)
    writer = RecordingWriter()
    world = await _ready(writer=writer, budgets=Budgets(limits=(instance,)))
    await world.modes.save(LIB, None, LibraryAi(budgets=(own,)))

    await _search(world)

    (step,) = writer.steps
    library_day = [
        limit
        for limit in step.budgets.limits
        if limit.scope_kind == "library" and limit.window is SpendWindow.DAY
    ]
    assert [limit.tokens for limit in library_day] == [500]  # the tighter one


async def test_a_budget_refusing_the_request_itself_answers_hybrid() -> None:
    world = await _ready(writer=RefusingWriter())

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    assert world.cache.answers == {}


async def test_a_used_up_budget_also_stops_a_paid_query_embedding() -> None:
    budgets = Budgets(
        limits=(BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=1_000_000),)
    )
    world = await _ready(budgets=budgets)
    await world.ledger.add(
        [
            SpendEntry(
                scope_kind="library",
                scope_id=LIB,
                window=SpendWindow.DAY,
                window_start=T0.date(),
                input_tokens=1_000_000,
            )
        ]
    )

    result = await _search(world)

    # Hybrid is what answers without the LLM step; its own embedding is paid and over budget too.
    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    assert world.llm.prompts == []
    assert world.models.queries == []


async def test_the_rate_limit_answers_hybrid() -> None:
    world = await _ready(budgets=Budgets(llm_searches_per_minute=1))
    use_case = world.module.search_docs
    query = SearchDocsQuery(library=LIB, ref="v2", query=QUESTION, limit=3)

    first = await use_case(query, caller="ada")
    second = await use_case(query.model_copy(update={"query": "another question"}), caller="ada")

    assert first.retrieval_mode is RetrievalMode.HYBRID_HYDE
    assert (second.retrieval_mode, second.fallback_reason) == (
        RetrievalMode.HYBRID,
        FallbackReason.LLM_RATE_LIMITED,
    )


@pytest.mark.parametrize("behaviour", ["fail", "empty"])
async def test_an_llm_failure_answers_hybrid_and_logs_neither_query_nor_key(
    behaviour: str, caplog: pytest.LogCaptureFixture
) -> None:
    llm = Llm(answer="   " if behaviour == "empty" else HYPOTHESIS, behaviour=behaviour)
    world = await _ready(llm=llm)

    with caplog.at_level(logging.DEBUG):
        result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        FallbackReason.LLM_UNAVAILABLE,
    )
    assert world.models.queries == [QUESTION]  # hybrid on the query itself
    assert world.cache.answers == {}
    assert QUESTION not in caplog.text
    assert "sk-secret" not in caplog.text


async def test_an_llm_that_does_not_answer_in_time_answers_hybrid() -> None:
    world = await _ready(writer=SlowWriter(), hyde_timeout=0.05)

    result = await asyncio.wait_for(_search(world), timeout=5)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.HYBRID,
        FallbackReason.LLM_UNAVAILABLE,
    )


async def test_a_library_with_ai_off_cannot_run_hyde() -> None:
    world = await _ready()
    await world.modes.save(LIB, None, LibraryAi(enabled=False))

    result = await _search(world)

    assert result.retrieval_mode is RetrievalMode.BM25
    assert world.llm.prompts == []


# ---------------------------------------------------------------- the writer adapter


def _step(ledger: InMemorySpendLedger, budgets: Budgets) -> LlmStep:
    del ledger
    return LlmStep(
        caller=AiCaller(library=LIB, user="ada"),
        budgets=budgets,
        price=ModelPrice(input_usd_per_million=1.0),
        clock=lambda: T0,
    )


async def test_the_writer_returns_the_answer_and_records_its_usage() -> None:
    ledger = InMemorySpendLedger()
    writer = PydanticAiHypotheticalAnswers(ledger=ledger)

    written = await writer.write(
        TestModel(custom_output_text="a passage"), "q", step=_step(ledger, Budgets())
    )

    assert written.text == "a passage"
    assert written.input_tokens > 0
    assert written.output_tokens > 0
    assert {(k.scope_kind, k.scope_id) for k in ledger.rows} == {
        ("instance", ""),
        ("library", LIB),
        ("user", "ada"),
    }


async def test_the_writer_refuses_once_a_budget_is_used_up() -> None:
    ledger = InMemorySpendLedger()
    writer = PydanticAiHypotheticalAnswers(ledger=ledger)
    budgets = Budgets(limits=(BudgetLimit(scope_kind="user", window=SpendWindow.DAY, tokens=1),))
    await writer.write(TestModel(), "q", step=_step(ledger, budgets))

    with pytest.raises(LlmBudgetReachedError):
        await writer.write(TestModel(), "q", step=_step(ledger, budgets))


async def test_the_writer_refuses_a_handle_that_is_no_chat_model() -> None:
    writer = PydanticAiHypotheticalAnswers(ledger=InMemorySpendLedger())

    with pytest.raises(LlmFailedError):
        await writer.write(object(), "q", step=_step(InMemorySpendLedger(), Budgets()))


# ---------------------------------------------------------------- the cache adapters


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def cache(request: pytest.FixtureRequest) -> AsyncIterator[HypotheticalAnswerCache]:
    """Each cache adapter: in memory, and ``retrieval_hyde_answers`` on each SQL database.

    Yields:
        The cache.
    """
    if request.param == "memory":
        yield InMemoryHypothesisCache()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield SqliteHypothesisCache(engine=container.engine)


async def test_every_cache_stores_replaces_and_forgets_by_manifest(
    cache: HypotheticalAnswerCache,
) -> None:
    first = HydeKey.of("m1", WRITER, "how do I retry", key=KEY)
    other_model = HydeKey.of(
        "m1", ModelRef(profile="corp", model="other"), "how do I retry", key=KEY
    )
    second = HydeKey.of("m2", WRITER, "how do I retry", key=KEY)

    assert await cache.get(first) is None
    await cache.put(first, "draft", T0)
    await cache.put(first, "passage", T0)
    await cache.put(other_model, "another", T0)
    await cache.put(second, "newer", T0)

    assert await cache.get(first) == "passage"
    assert await cache.get(HydeKey.of("m1", WRITER, " HOW do i  RETRY", key=KEY)) == "passage"
    assert await cache.get(other_model) == "another"
    assert await cache.forget(["m1", "m9"]) == 2
    assert await cache.forget([]) == 0
    assert (await cache.get(first), await cache.get(second)) == (None, "newer")


async def test_every_cache_prunes_by_age_and_by_model(cache: HypotheticalAnswerCache) -> None:
    old = HydeKey.of("m1", WRITER, "old", key=KEY)
    fresh = HydeKey.of("m1", WRITER, "fresh", key=KEY)
    retired = HydeKey.of("m1", ModelRef(profile="corp", model="retired"), "fresh", key=KEY)
    await cache.put(old, "old", T0)
    await cache.put(fresh, "fresh", T0 + timedelta(days=2))
    await cache.put(retired, "retired", T0 + timedelta(days=2))

    pruned = await cache.prune(T0 + timedelta(days=1), {str(WRITER)})

    assert pruned == 2
    assert (await cache.get(old), await cache.get(fresh), await cache.get(retired)) == (
        None,
        "fresh",
        None,
    )
    assert await cache.prune(T0, ()) == 1  # no model configured: every answer goes
    assert await cache.get(fresh) is None


# ---------------------------------------------------------------- pruning on the real composition


@pytest.fixture(params=SQL_BACKENDS)
async def sql_container(request: pytest.FixtureRequest) -> AsyncIterator[Container]:
    """The app on each SQL database, with an ``llm`` role (never called here).

    Yields:
        The running container.
    """
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    ai = AiSettings.model_validate(
        {
            "providers": {
                "corp": {"kind": "openai-compatible", "base_url": "http://127.0.0.1:9/v1"}
            },
            "llm": {"model": str(WRITER)},
        }
    )
    container = Container.build(Settings(ai=ai))
    async with container.running(jobs=False):
        yield container


async def test_every_sql_library_store_names_each_llm_override_once(
    sql_container: Container,
) -> None:
    modes = SqliteLibraryModes(engine=sql_container.engine)
    other = ModelRef(profile="corp", model="other")
    await modes.save("/acme/a", None, LibraryAi(llm=other))
    await modes.save("/acme/b", None, LibraryAi(llm=other))
    await modes.save("/acme/c", RetrievalMode.BM25, LibraryAi())

    assert await modes.llm_overrides() == frozenset({"corp:other"})


async def test_collection_on_sql_prunes_answers_past_the_ttl_and_of_retired_models(
    sql_container: Container,
) -> None:
    cache = SqliteHypothesisCache(engine=sql_container.engine)
    now = datetime.now(UTC)
    old = HydeKey.of("m1", WRITER, "old", key=KEY)
    fresh = HydeKey.of("m1", WRITER, "fresh", key=KEY)
    retired = HydeKey.of("m1", ModelRef(profile="corp", model="retired"), "fresh", key=KEY)
    await cache.put(old, "old", now - timedelta(days=40))
    await cache.put(fresh, "fresh", now)
    await cache.put(retired, "retired", now)

    await sql_container.retrieval.collect_chunks(CollectChunksCommand(grace_seconds=0))

    assert (await cache.get(old), await cache.get(fresh), await cache.get(retired)) == (
        None,
        "fresh",
        None,
    )


async def test_the_nightly_upkeep_prunes_the_cache(sql_container: Container) -> None:
    cache = SqliteHypothesisCache(engine=sql_container.engine)
    old = HydeKey.of("m1", WRITER, "old", key=KEY)
    await cache.put(old, "old", datetime.now(UTC) - timedelta(days=40))

    await sql_container.nightly()

    assert await cache.get(old) is None


@dataclass(slots=True)
class CountingCache:
    """An in-memory cache that counts its reads."""

    inner: InMemoryHypothesisCache = field(default_factory=InMemoryHypothesisCache)
    reads: int = 0

    @property
    def answers(self) -> Mapping[HydeKey, str]:
        return self.inner.answers

    async def get(self, key: HydeKey) -> str | None:
        self.reads += 1
        return await self.inner.get(key)

    async def put(self, key: HydeKey, answer: str, at: datetime) -> None:
        await self.inner.put(key, answer, at)

    async def forget(self, manifest_ids: Collection[str]) -> int:
        return await self.inner.forget(manifest_ids)

    async def prune(self, written_before: datetime, keep_models: Collection[str]) -> int:
        return await self.inner.prune(written_before, keep_models)


async def test_a_search_reads_the_cache_once() -> None:
    counting = CountingCache()
    world = await _ready(cache=counting)
    await _search(world)  # a miss: written
    counting.reads = 0

    again = await _search(world)

    assert again.retrieval_mode is RetrievalMode.HYBRID_HYDE
    assert counting.reads == 1
    assert world.llm.prompts == [QUESTION]
