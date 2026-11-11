"""RET-05: similar agentic questions are answered from a cache (#100).

The agent is the real one (pydantic-ai, harness Code Mode, Monty) on a scripted ``FunctionModel``
(``scripted_explorer``): no provider is called. ``ScriptedModels.chat_models`` grows by one per
agent run, which tells a cache hit from a run.
"""

import logging
import re
from collections.abc import AsyncIterator, Collection, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from databases import SQL_BACKENDS
from exactdocs.bootstrap.constants import AGENT_CACHE_PURPOSE, HYDE_CACHE_PURPOSE
from exactdocs.bootstrap.container import Container, _agent_cache_key
from exactdocs.bootstrap.secret_box import derived_key
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.ai_explorer import PydanticAiExplorer
from exactdocs.retrieval.adapters.driven.ai_judge import PydanticAiCandidateJudge
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryAgentAnswerCache,
    InMemoryCallRates,
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
    ReadOnlyAgentAnswerCache,
)
from exactdocs.retrieval.adapters.driven.opentelemetry import OpenTelemetrySearchTracer
from exactdocs.retrieval.adapters.driven.sqlite import SqliteAgentAnswerCache
from exactdocs.retrieval.constants import AGENT_CACHE_PER_SCOPE
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    CollectChunksCommand,
    ForgetLibraryCommand,
    IndexManifestCommand,
    QueryDocsQuery,
    SearchDocsQuery,
    SearchDocsResult,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.models import (
    AgentBounds,
    AgentCacheScope,
    BudgetLimit,
    Budgets,
    CachedAgentAnswer,
    CachedPick,
    CachedQuestion,
    CatalogLibrary,
    ChunkId,
    DocTarget,
    EmbeddedTexts,
    EmbeddingTarget,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestStatus,
    ModelCheck,
    ModelRef,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RepoGuidance,
    RerankLimits,
    RerankWith,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    SpendEntry,
    SpendWindow,
    TagFilter,
    TagMatch,
    question_terms,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import AgentAnswerCache, Reranker
from scripted_explorer import ScriptedModels, browsing

LIB = "/acme/payments"
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
KEY = b"k" * 32
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
EXPLORER = ModelRef(profile="corp", model="explorer")
JUDGE = ModelRef(profile="corp", model="judge-mini")
FIRST = "how do I configure retries"
SIMILAR = "how to configure retry behaviour"
OTHER = "how do I rotate the API token"
PARAPHRASE = "what makes failed calls run again"
GUIDE = {
    "resilience": [
        "Configure retries with RetryPolicy: it decides how often a failed call runs again.",
        "Calls that time out are retried after a short pause (backoff).",
    ],
    "auth": ["Rotate the API token without downtime."],
    "paging": ["Use the cursor to read the next page."],
}
OLD_GUIDE = {"resilience": ["Configure retries in v1 with a retry count."]}


@dataclass(slots=True)
class Clock:
    at: datetime = T0

    def now(self) -> datetime:
        return self.at


@dataclass(slots=True)
class Catalog:
    """Each version's active manifest, and its articles' Markdown (``VersionArticles``)."""

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

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        active = {v.manifest_id for v in self.versions.values()}
        return {m: ManifestStatus.ACTIVE for m in manifest_ids if m in active}

    async def active_id(self, target: DocTarget) -> str | None:
        found = self.versions.get(target.version)
        return None if found is None else found.manifest_id

    async def canonical_id(self, library: str) -> str | None:
        return LIB if library.casefold() == LIB else None

    async def all(self) -> Sequence[CatalogLibrary]:
        return ()


@dataclass(slots=True)
class Tracer:
    """A ``SearchTracer`` double: the cache hits counted."""

    cache_hits: list[tuple[str, str]] = field(default_factory=list)

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[_Span]:
        del name, mode, query, attributes
        return nullcontext(_Span())

    def fallback(self, *, mode: str, reason: str) -> None:
        del mode, reason

    def cache_hit(self, *, cache: str, mode: str) -> None:
        self.cache_hits.append((cache, mode))


class _Span:
    def answered_by(self, mode: str) -> None:
        del mode


@dataclass(slots=True)
class Questions:
    """``Embeddings``: a fixed vector per question (unknown ones are orthogonal to all)."""

    owner: QuestionModels
    name: str

    async def dimensions(self) -> int:
        return 3

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        return EmbeddedTexts(
            vectors=tuple((0.0, 0.0, 1.0) for _ in texts), input_tokens=1, requests=1
        )

    async def embed_query(self, text: str) -> EmbeddedTexts:
        self.owner.queries.append(text)
        if self.owner.fail:
            raise RuntimeError(text)  # its message holds the query: it must not be logged
        vector = self.owner.vectors.get(text, (0.0, 0.0, 1.0))
        return EmbeddedTexts(vectors=(vector,), input_tokens=5, requests=1)


@dataclass(slots=True)
class QuestionModels:
    """``EmbeddingModels`` binding ``Questions``; records every question embedded."""

    vectors: dict[str, tuple[float, ...]] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    fail: bool = False

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> Questions:
        del handle, dimensions, batch_size
        return Questions(owner=self, name=name)


@dataclass(slots=True)
class Factory:
    """``ModelFactory``: the scripted chat model, and a marker embedder."""

    scripted: ScriptedModels
    judged: list[str] = field(default_factory=list)
    """Every judge model built: one per judged search."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        if model == JUDGE.model:
            self.judged.append(model)
            return FunctionModel(_judge, model_name=JUDGE.model)
        return await self.scripted.chat_model(profile, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        raise NotImplementedError

    async def release(self, name: str) -> None:
        del name

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


def _judge(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Rate every candidate of the judge's prompt, the later ones higher.

    Args:
        messages: The judge's request.
        info: Its output tool.

    Returns:
        The ratings.
    """
    prompt = next(
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )
    ids = re.findall(r'<candidate id="(c[0-9]+)">', prompt)
    ratings = [{"id": i, "score": min(n + 1, 10)} for n, i in enumerate(ids)]
    tool = info.output_tools[0]
    return ModelResponse(parts=[ToolCallPart(tool.name, {"response": ratings})])


@dataclass(slots=True)
class BrokenCache:
    """An ``AgentAnswerCache`` whose every call fails, its message holding stored text."""

    async def scoped(self, scope: AgentCacheScope) -> Sequence[CachedAgentAnswer]:
        del scope
        raise RuntimeError(FIRST)

    async def put(self, answer: CachedAgentAnswer) -> None:
        del answer
        raise RuntimeError(FIRST)

    async def forget(self, manifest_ids: Collection[str]) -> int:
        del manifest_ids
        raise RuntimeError(FIRST)

    async def forget_library(self, library: str) -> int:
        del library
        raise RuntimeError(FIRST)

    async def prune(
        self, written_before: datetime, keep_models: Collection[str], keep_similarity: str
    ) -> int:
        del written_before, keep_models, keep_similarity
        raise RuntimeError(FIRST)


@dataclass(slots=True)
class World:
    module: RetrievalModule
    catalog: Catalog
    models: ScriptedModels
    cache: AgentAnswerCache
    tracer: Tracer
    ledger: InMemorySpendLedger
    modes: InMemoryLibraryModes
    clock: Clock
    questions: QuestionModels | None
    factory: Factory


async def _world(
    *,
    threshold: float | None = None,
    enabled: bool = True,
    scope: str = "library",
    cache: AgentAnswerCache | None = None,
    budgets: Budgets | None = None,
    embeddings: QuestionModels | None = None,
    bounds: AgentBounds | None = None,
    judge: bool = False,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    models = ScriptedModels(model=browsing())
    store = cache or InMemoryAgentAnswerCache()
    tracer = Tracer()
    ledger = InMemorySpendLedger()
    modes = InMemoryLibraryModes()
    clock = Clock()
    embedding = None if embeddings is None else ModelRef(profile="corp", model="e")
    roles = InstanceRoles(llm=EXPLORER, embedding=embedding, judge=JUDGE if judge else None)
    factory = Factory(scripted=models)
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=catalog,
        defaults=InMemoryDefaultVersions(),
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=[CORP],
        instance_roles=roles,
        models=factory,
        rerank_with=RerankWith.JUDGE if judge else RerankWith.CROSS_ENCODER,
        judge=PydanticAiCandidateJudge(ledger=ledger) if judge else None,
        rerank_limits=RerankLimits(top_n=5),
        clock=clock,
        tracer=tracer,
        spend=ledger,
        budgets=budgets,
        call_rates=InMemoryCallRates(),
        embedding_models=embeddings,
        explorer=PydanticAiExplorer(),
        agent_bounds=bounds,
        agent_answer_cache=store,
        agent_cache_key=KEY,
        agent_cache_enabled=enabled,
        agent_cache_threshold=threshold,
        agent_cache_scope=scope,
        agent_cache_ttl=timedelta(days=7),
    )
    world = World(
        module=module,
        catalog=catalog,
        models=models,
        cache=store,
        tracer=tracer,
        ledger=ledger,
        modes=modes,
        clock=clock,
        questions=embeddings,
        factory=factory,
    )
    await _import(world, "v1", "m1", OLD_GUIDE)
    await _import(world, "v2", "m2", GUIDE)
    return world


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
                    tags=["security"] if blob == "auth" else [],
                    chunks=[
                        ChunkIn(
                            heading_path=[blob.title(), f"S{i}"],
                            occurrence_index=0,
                            content=text,
                            content_hash=f"h-{blob}-{i}-{manifest}",
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


async def _ask(
    world: World,
    question: str,
    *,
    ref: str = "v2",
    tags: Sequence[str] = (),
    limit: int = 3,
    caller: str = "ana",
) -> SearchDocsResult:
    return await world.module.search_docs(
        SearchDocsQuery(
            library=LIB, ref=ref, query=question, mode="agentic", limit=limit, tags=list(tags)
        ),
        caller=caller,
    )


def _runs(world: World) -> int:
    return len(world.models.chat_models)


# ---------------------------------------------------------------- similar questions hit


async def test_a_similar_question_is_answered_from_the_cache_without_the_agent() -> None:
    world = await _world()
    first = await _ask(world, FIRST)
    assert (first.retrieval_mode, first.cache_hit) == (RetrievalMode.AGENTIC, False)
    assert first.results

    again = await _ask(world, SIMILAR)

    assert (again.retrieval_mode, again.cache_hit, again.fallback_reason) == (
        RetrievalMode.AGENTIC,
        True,
        None,
    )
    assert _runs(world) == 1
    assert [r.chunk_id for r in again.results] == [r.chunk_id for r in first.results]
    assert [r.justification for r in again.results] == [r.justification for r in first.results]
    assert [r.explored_path for r in again.results] == [r.explored_path for r in first.results]
    assert world.tracer.cache_hits == [("agentic_answer", "agentic")]


async def test_a_different_question_runs_the_agent() -> None:
    world = await _world()
    await _ask(world, FIRST)

    other = await _ask(world, OTHER)

    assert other.cache_hit is False
    assert _runs(world) == 2
    assert world.tracer.cache_hits == []


@pytest.mark.parametrize(("threshold", "hit"), [(0.95, True), (0.97, False)])
async def test_the_threshold_is_configurable(threshold: float, hit: bool) -> None:
    questions = QuestionModels(
        vectors={FIRST: (1.0, 0.0, 0.0), SIMILAR: (0.96, 0.28, 0.0)}  # cosine 0.96
    )
    world = await _world(embeddings=questions, threshold=threshold)
    await _ask(world, FIRST)

    assert (await _ask(world, SIMILAR)).cache_hit is hit  # the same terms, confirmed or not
    assert (await _ask(world, "  How do i CONFIGURE retries ")).cache_hit is True  # the same


@pytest.mark.parametrize(
    ("asked", "again"),
    [
        ("why is my request not retried", "why is my request retried"),
        ("can I use async with the client", "can I not use async with the client"),
        ("why does the cache not work", "why does the cache work"),
        ("why doesn't the cache work", "why does the cache work"),
        ("I cannot connect to the server", "I can connect to the server"),
        ("retry without backoff", "retry with backoff"),
        (
            "how to migrate the database schema from v1 to v2",
            "how to migrate the database schema from v2 to v3",
        ),
        ("upgrade from v2 to v1", "upgrade from v1 to v2"),
        ("configure retries", "configure retries for uploads"),
        ("enable retries", "disable retries"),
        ("add a webhook", "remove a webhook"),
        ("create the index", "drop the index"),
        ("call it over http", "call it over grpc"),
        ("migrate from postgres to mysql", "migrate from mysql to postgres"),
        ("convert json to yaml", "convert yaml to json"),
        ("copy from the bucket to disk", "copy from disk to the bucket"),
        ("how to enable http", "how to enable https"),
        ("read the news", "read the new"),
        ("set the timeout to -1", "set the timeout to 1"),
        ("when is the cache cleared", "why is the cache cleared"),
        ("where is the config file", "what is the config file"),
        ("use python3", "use python2"),
        ("cant retry uploads", "retry uploads"),
        ("isnt the cache shared", "is the cache shared"),
        ("shouldnt I retry", "should I retry"),
        ("replace requests with httpx", "replace httpx with requests"),
        ("use redis instead of memcached", "use memcached instead of redis"),
        ("is postgres faster than mysql", "is mysql faster than postgres"),
        ("use the client as a server", "use the server as a client"),
        ("does the cache expire before the token", "does the token expire before the cache"),
        ("how to go from v1 to v2", "how to go to v1 from v2"),
        ("upgrade from v2", "upgrade to v2"),
        ("requires python >= 3.8", "requires python < 3.8"),
        ("pin the version ~1.2", "pin the version ^1.2"),
        ("x != 1", "x == 1"),
        ("requires python>=3.8", "requires python<=3.8"),
        ("validate the form", "validate the format"),
        ("logs during the build", "logs duration of the build"),
        ("list the settings", "list the sets"),
        ("build for arm", "build on arm"),
        ("should I use postgres or mysql", "should I use postgres and mysql"),
        ("how to treat warnings", "how to tree warnings"),
        ("when latency > threshold", "when latency < threshold"),
        ("requires python ≥3.8", "requires python ≤3.8"),
        ("does it support python 3.8+", "does it support python 3.8"),
        ("is a < b", "is a > b"),
        ("move it to a from b", "move it to b from a"),
        ("does c++ support it", "does c support it"),
        ("a → b", "a ← b"),
        ("what is the meaning of the score", "what is the mean of the score"),
        ("configure hosting", "configure the host"),
        ("what happens on a cache miss", "what happens on a cache missing"),
        ("how to add a heading", "how to add a head"),
        ("what is a port", "what is ported"),
    ],
)
def test_questions_that_ask_something_else_never_match_by_words(asked: str, again: str) -> None:
    one, two = CachedQuestion.of(asked, key=KEY), CachedQuestion.of(again, key=KEY)

    assert one.similarity(two) == 0
    assert two.similarity(one) == 0


@pytest.mark.parametrize(
    ("asked", "again"),
    [
        (FIRST, SIMILAR),
        ("why doesn't the cache work", "why does not the cache work"),
        ("why can't I connect", "why cannot I connect"),
        ("migrate from v1 to v2", "Migrate from 1 to 2"),
        ("how do I not retry on v2", "how not to retry on v2"),
        ("change the settings", "change the setting"),
        ("dont retry uploads", "do not retry uploads"),
        ("migrate from postgres to mysql", "Migrate from Postgres to MySQL"),
        ("how to configure retries", "how do I configure retries"),
        ("how to connect to postgres", "connect to postgres"),
        ("how do I upgrade to v2", "how to upgrade to v2"),
        ("I want to configure retries", "how do I configure retries"),
        ("requires python>=3.8", "requires python >= 3.8"),
        ("requires python ≥ 3.8", "requires python >= 3.8"),
        ("a → b", "a -> b"),
        ("why is my request retried!", "why is my request retried"),
        ("delete rows", "delete a row"),
        ("enable logs", "enable the log"),
    ],
)
def test_the_same_question_asked_again_matches(asked: str, again: str) -> None:
    one, two = CachedQuestion.of(asked, key=KEY), CachedQuestion.of(again, key=KEY)

    assert one.similarity(two) == 1


@pytest.mark.parametrize(
    ("asked", "again"),
    [
        ("retry configuration", "configure retries"),
        ("check the status of https", "check https status"),
        ("on v2, how not to retry", "how not to retry on v2"),
        ("database migration", "migrate the database"),
        ("how do I upgrade to v2", "upgrading to v2"),
        ("enable logging", "enable logs"),
        ("how to connect to postgres", "connecting to postgres"),
    ],
)
def test_a_re_ask_in_another_order_misses_by_design(asked: str, again: str) -> None:
    one, two = CachedQuestion.of(asked, key=KEY), CachedQuestion.of(again, key=KEY)

    assert one.similarity(two) == 0  # order carries meaning elsewhere: no exception here


@pytest.mark.parametrize(
    ("word", "other"),
    [
        ("rows", "row"),
        ("workflows", "workflow"),
        ("views", "view"),
        ("flows", "flow"),
        ("logs", "log"),
        ("retries", "retry"),
        ("policies", "policy"),
        ("matches", "match"),
        ("boxes", "box"),
        ("classes", "class"),
        ("settings", "setting"),
        ("strings", "string"),
    ],
)
def test_inflections_fold_to_one_term(word: str, other: str) -> None:
    assert question_terms(word) == question_terms(other)


@pytest.mark.parametrize(
    ("word", "other"),
    [
        ("format", "form"),
        ("during", "duration"),
        ("settings", "sets"),
        ("setting", "set"),
        ("form", "formation"),
        ("logging", "log"),
        ("mapping", "map"),
        ("string", "str"),
        ("thing", "th"),
        ("morning", "morn"),
        ("ceiling", "ceil"),
        ("treat", "tree"),
        ("migration", "migrate"),
        ("validation", "validate"),
        ("authentication", "authenticate"),
        ("creation", "create"),
        ("deployment", "deploy"),
        ("configuration", "configure"),
        ("cookies", "cookie"),
        ("added", "add"),
        ("meaning", "mean"),
        ("hosting", "host"),
        ("missing", "miss"),
        ("heading", "head"),
        ("ported", "port"),
        ("united", "unit"),
        ("connecting", "connect"),
        ("called", "call"),
        ("lens", "len"),
        ("pending", "pend"),
    ],
)
def test_the_fold_is_minimal_and_these_stay_apart_on_purpose(word: str, other: str) -> None:
    assert question_terms(word) != question_terms(other)


@pytest.mark.parametrize(
    ("word", "other"),
    [("https", "http"), ("wss", "ws"), ("news", "new"), ("windows", "window")],
)
def test_names_whose_s_is_no_plural_keep_it(word: str, other: str) -> None:
    assert question_terms(word) != question_terms(other)


@pytest.mark.parametrize(
    ("asked", "again"),
    [
        ("how do I enable retries", "how do I disable retries"),
        ("configure timeouts for the client", "configure timeouts for the server"),
        ("how to set the read timeout", "how to set the write timeout"),
        ("how to encrypt a file", "how to decrypt a file"),
        ("how to allow cors", "how to deny cors"),
        ("what is the minimum memory", "what is the maximum memory"),
        ("what is the min memory", "what is the max memory"),
        ("how to log in", "how to log out"),
        ("how to import data", "how to export data"),
        ("use python3", "use python2"),
        ("configure oauth1", "configure oauth2"),
        ("support for ipv4", "support for ipv6"),
        ("what happens on retry error E42", "what happens on retry error E43"),
        ("dont retry failed requests", "retry failed requests"),
        ("configure retries", "configure retries for uploads"),
        ("why is my request not retried", "why is my request retried"),
    ],
)
def test_a_term_apart_never_matches_even_with_identical_embeddings(asked: str, again: str) -> None:
    near = (1.0, 0.0, 0.0)  # a stand-in model that scores the pair as one question
    one = CachedQuestion.of(asked, key=KEY, vector=near)
    two = CachedQuestion.of(again, key=KEY, vector=near)

    assert one.similarity(two) == 0
    assert two.similarity(one) == 0


async def test_a_term_apart_misses_through_the_pipeline_even_with_identical_embeddings() -> None:
    near = (1.0, 0.0, 0.0)
    questions = QuestionModels(
        vectors={"how do I enable retries": near, "how do I disable retries": near}
    )
    world = await _world(embeddings=questions)
    await _ask(world, "how do I enable retries")

    again = await _ask(world, "how do I disable retries")

    assert again.cache_hit is False
    assert _runs(world) == 2


def test_an_embedding_only_confirms_the_same_terms() -> None:
    same = CachedQuestion.of(FIRST, key=KEY, vector=(1.0, 0.0, 0.0))
    far = CachedQuestion.of(SIMILAR, key=KEY, vector=(0.0, 1.0, 0.0))
    near = CachedQuestion.of(SIMILAR, key=KEY, vector=(0.96, 0.28, 0.0))

    assert same.similarity(far) == 0  # the same terms, but the model says otherwise
    assert same.similarity(near) == pytest.approx(0.96)


@pytest.mark.parametrize("embedded", [False, True])
async def test_the_cache_is_off_unless_turned_on(embedded: bool) -> None:
    world = await _world(enabled=False, embeddings=QuestionModels() if embedded else None)
    await _ask(world, FIRST)

    again = await _ask(world, FIRST)

    assert again.cache_hit is False
    assert _runs(world) == 2
    assert not _entries(world)


def test_the_cache_is_opt_in_by_default() -> None:
    assert AiSettings().agentic_cache.enabled is False


async def test_turned_on_with_an_embedding_model_a_re_ask_hits() -> None:
    world = await _world(embeddings=QuestionModels())
    await _ask(world, FIRST)

    assert (await _ask(world, SIMILAR)).cache_hit is True


async def test_with_scope_caller_callers_never_share_answers() -> None:
    world = await _world(scope="caller")
    await _ask(world, FIRST, caller="ana")

    other = await _ask(world, SIMILAR, caller="bob")
    own = await _ask(world, SIMILAR, caller="ana")

    assert (other.cache_hit, own.cache_hit) == (False, True)
    stored = repr(_entries(world))
    assert "ana" not in stored
    assert "bob" not in stored


async def test_with_scope_library_callers_share_answers() -> None:
    world = await _world()
    await _ask(world, FIRST, caller="ana")

    assert (await _ask(world, SIMILAR, caller="bob")).cache_hit is True


async def test_an_empty_scope_embeds_nothing_at_lookup_and_the_answer_at_store() -> None:
    questions = QuestionModels(vectors={FIRST: (1.0, 0.0, 0.0)})
    world = await _world(embeddings=questions)

    await _ask(world, FIRST)

    assert questions.queries == [FIRST]  # once: when the agent's answer was stored
    assert _entries(world)[0].question.vector == (1.0, 0.0, 0.0)


async def test_a_candidate_by_words_is_confirmed_by_its_embedding() -> None:
    questions = QuestionModels()
    world = await _world(embeddings=questions)
    await _ask(world, FIRST)
    questions.queries.clear()

    again = await _ask(world, SIMILAR)

    assert again.cache_hit is True
    assert questions.queries == [SIMILAR]


async def test_a_question_with_other_terms_embeds_nothing() -> None:
    questions = QuestionModels()
    world = await _world(embeddings=questions)
    await _ask(world, FIRST)
    questions.queries.clear()

    other = await _ask(world, PARAPHRASE)

    assert other.cache_hit is False
    assert questions.queries == [PARAPHRASE]  # once: when the agent's answer was stored


async def test_a_used_up_library_budget_embeds_no_question() -> None:
    questions = QuestionModels()
    world = await _world(embeddings=questions)
    await _ask(world, FIRST)
    questions.queries.clear()
    await world.modes.save(
        LIB,
        None,
        LibraryAi(budgets=(BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=1),)),
    )
    await world.ledger.add(
        [
            SpendEntry(
                scope_kind="library",
                scope_id=LIB,
                window=SpendWindow.DAY,
                window_start=T0.date(),
                input_tokens=5,
            )
        ]
    )
    await world.cache.put(_entries(world)[0])  # saving the settings forgot it

    result = await _ask(world, SIMILAR)

    assert result.cache_hit is True  # the words decide when the confirmation cannot be paid
    assert questions.queries == []  # the paid embedding was not made


async def test_query_docs_is_answered_from_the_cache_too() -> None:
    world = await _world()
    await world.modes.save(LIB, RetrievalMode.AGENTIC, LibraryAi())

    first = await world.module.query_docs(QueryDocsQuery(library_id=f"{LIB}/v2", query=FIRST))
    again = await world.module.query_docs(QueryDocsQuery(library_id=f"{LIB}/v2", query=SIMILAR))

    assert (first.cache_hit, again.cache_hit) == (False, True)
    assert _runs(world) == 1


# ---------------------------------------------------------------- scope: version, filter, model


async def test_a_cached_answer_never_answers_another_version() -> None:
    world = await _world()
    await _ask(world, FIRST, ref="v2")

    older = await _ask(world, SIMILAR, ref="v1")

    assert older.cache_hit is False
    assert _runs(world) == 2
    assert {r.commit_sha for r in older.results} == {"1" * 40}


async def test_a_re_sync_is_a_new_manifest_and_runs_the_agent_again() -> None:
    world = await _world()
    await _ask(world, FIRST)
    await _import(world, "v2", "m3", GUIDE)  # the same version at a new commit

    after = await _ask(world, SIMILAR)

    assert after.cache_hit is False
    assert _runs(world) == 2
    assert {r.commit_sha for r in after.results} == {"3" * 40}


async def test_collection_forgets_the_answers_of_removed_manifests() -> None:
    world = await _world()
    await _ask(world, FIRST)
    await _import(world, "v2", "m3", GUIDE)
    world.clock.at = T0 + timedelta(days=1)

    await world.module.collect_chunks(CollectChunksCommand(grace_seconds=0))

    assert not [a for a in _entries(world) if a.scope.manifest_id == "m2"]


async def test_another_tag_filter_is_another_scope() -> None:
    world = await _world()
    await _ask(world, FIRST)

    filtered = await _ask(world, SIMILAR, tags=["security"])

    assert filtered.cache_hit is False
    assert _runs(world) == 2
    assert {r.article_path for r in filtered.results} <= {"docs/auth.md"}


async def test_another_llm_model_is_another_scope() -> None:
    world = await _world()
    await _ask(world, FIRST)
    await world.modes.save(LIB, None, LibraryAi(llm=ModelRef(profile="corp", model="other")))

    after = await _ask(world, SIMILAR)

    assert after.cache_hit is False
    assert world.models.chat_models == ["corp:explorer", "corp:other"]


async def test_another_repo_guidance_is_another_scope() -> None:
    world = await _world()
    await _ask(world, FIRST)
    store = world.cache
    assert isinstance(store, InMemoryAgentAnswerCache)
    kept = list(store.answers.values())
    await world.modes.save(LIB, None, LibraryAi(repo_guidance=RepoGuidance.NOTES))
    for answer in kept:  # as if a run in flight stored it after the settings were saved
        await store.put(answer)

    after = await _ask(world, SIMILAR)

    assert after.cache_hit is False
    assert _runs(world) == 2


async def test_a_hit_rechecks_every_pick_against_the_manifest_and_the_tag_filter() -> None:
    world = await _world()
    first = await _ask(world, OTHER, tags=["security"])
    assert {r.article_path for r in first.results} == {"docs/auth.md"}
    (entry,) = _entries(world)
    foreign = (await _ask(world, "RetryPolicy", ref="v1")).results[0].chunk_id
    unfiltered = (await _bm25(world, "RetryPolicy")).results[0]
    assert unfiltered.article_path == "docs/resilience.md"  # no "security" tag
    planted = replace(
        entry,
        picks=(
            CachedPick(chunk_id=ChunkId(foreign), justification="of v1"),
            CachedPick(chunk_id=ChunkId("0" * 64), justification="made up"),
            CachedPick(chunk_id=ChunkId(unfiltered.chunk_id), justification="tag-excluded"),
            *entry.picks,
        ),
    )
    await world.cache.put(planted)

    again = await _ask(world, "how do I rotate an API token", tags=["security"])

    assert again.cache_hit is True
    assert [r.chunk_id for r in again.results] == [r.chunk_id for r in first.results]
    assert {r.commit_sha for r in again.results} == {"2" * 40}


async def test_a_cached_answer_whose_picks_are_all_gone_is_a_miss() -> None:
    world = await _world()
    await _ask(world, FIRST)
    entry = _entries(world)[0]
    await world.cache.put(
        replace(entry, picks=(CachedPick(chunk_id=ChunkId("0" * 64), justification="gone"),))
    )

    again = await _ask(world, SIMILAR)

    assert again.cache_hit is False
    assert again.results
    assert _runs(world) == 2


async def test_an_answer_asked_for_fewer_chunks_is_not_reused_for_more() -> None:
    world = await _world()
    await _ask(world, FIRST, limit=1)

    more = await _ask(world, SIMILAR, limit=3)
    fewer = await _ask(world, SIMILAR, limit=1)

    assert (more.cache_hit, fewer.cache_hit) == (False, True)
    assert len(fewer.results) == 1


async def test_saving_a_librarys_settings_forgets_its_answers() -> None:
    world = await _world()
    await _ask(world, FIRST)
    assert _entries(world)

    await world.module.set_library_retrieval(SetLibraryRetrievalCommand(library=LIB))

    assert not _entries(world)
    assert (await _ask(world, SIMILAR)).cache_hit is False


async def test_forgetting_a_library_forgets_its_answers() -> None:
    world = await _world()
    await _ask(world, FIRST)

    await world.module.forget_library(ForgetLibraryCommand(library=LIB))

    assert not _entries(world)


async def test_a_library_with_ai_off_looks_nothing_up() -> None:
    world = await _world()
    await _ask(world, FIRST)
    await world.modes.save(LIB, None, LibraryAi(enabled=False))

    result = await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query=SIMILAR, limit=3)
    )

    assert (result.retrieval_mode, result.cache_hit) == (RetrievalMode.BM25, False)


# ---------------------------------------------------------------- cost


async def test_a_cache_hit_costs_no_budget_even_when_it_is_used_up() -> None:
    budgets = Budgets(
        limits=(BudgetLimit(scope_kind="instance", window=SpendWindow.DAY, tokens=10**6),)
    )
    world = await _world(budgets=budgets)
    await _ask(world, FIRST)  # within the budget
    await world.ledger.add(
        [
            SpendEntry(
                scope_kind="instance",
                scope_id="",
                window=SpendWindow.DAY,
                window_start=T0.date(),
                input_tokens=10**6,
            )
        ]
    )
    spent = list(await world.ledger.since(T0.date()))

    again = await _ask(world, SIMILAR)
    blocked = await _ask(world, OTHER)

    assert (again.retrieval_mode, again.cache_hit, again.fallback_reason) == (
        RetrievalMode.AGENTIC,
        True,
        None,
    )
    assert (blocked.retrieval_mode, blocked.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    assert list(await world.ledger.since(T0.date())) == spent  # nothing more was spent
    assert _runs(world) == 1


async def test_a_cache_hit_is_not_held_back_by_the_rate_limit() -> None:
    world = await _world(budgets=Budgets(llm_searches_per_minute=1))
    await _ask(world, FIRST)  # the one LLM search of this minute

    again = await _ask(world, SIMILAR)
    other = await _ask(world, OTHER)

    assert (again.retrieval_mode, again.cache_hit) == (RetrievalMode.AGENTIC, True)
    assert other.fallback_reason == FallbackReason.LLM_RATE_LIMITED


async def test_a_cache_hit_with_the_judge_counts_the_judge_as_one_llm_search() -> None:
    world = await _world(judge=True, budgets=Budgets(llm_searches_per_minute=3))
    first = await _ask(world, FIRST)  # the agent and its judge: one LLM search
    assert (first.cache_hit, first.reranked) == (False, True)

    hit = await _ask(world, SIMILAR)  # no agent; the judge is checked and counted

    assert (hit.retrieval_mode, hit.cache_hit, hit.reranked) == (RetrievalMode.AGENTIC, True, True)
    assert _runs(world) == 1
    assert world.factory.judged == ["judge-mini", "judge-mini"]


async def test_a_cache_hit_whose_judge_is_refused_is_served_unreranked_with_the_reason() -> None:
    world = await _world(judge=True, budgets=Budgets(llm_searches_per_minute=1))
    await _ask(world, FIRST)  # the one LLM search of this minute

    hit = await _ask(world, SIMILAR)

    assert (hit.retrieval_mode, hit.cache_hit, hit.reranked, hit.fallback_reason) == (
        RetrievalMode.AGENTIC,
        True,
        False,
        FallbackReason.LLM_RATE_LIMITED,
    )
    assert hit.results
    assert world.factory.judged == ["judge-mini"]  # the refused judge was never built


# ---------------------------------------------------------------- what is stored


async def test_the_cache_stores_hashes_never_the_question() -> None:
    world = await _world()
    await _ask(world, FIRST)

    (entry,) = _entries(world)

    stored = repr(entry.question) + repr(entry.scope)
    for word in ("configure", "configur", "retries", "retry"):
        assert word not in stored
    assert entry.question.vector is None  # no embedding model: words only
    assert entry.scope.similarity == "bm25"
    assert all(len(t) == 16 and int(t, 16) >= 0 for t in entry.question.terms)


def test_hashes_are_keyed_by_the_instance() -> None:
    one = CachedQuestion.of(FIRST, key=KEY)
    two = CachedQuestion.of(FIRST, key=b"x" * 32)

    assert one.question_hash != two.question_hash
    assert set(one.terms).isdisjoint(two.terms)
    assert one.similarity(CachedQuestion.of(SIMILAR, key=KEY)) == pytest.approx(1)


async def test_a_cache_that_fails_is_a_miss_and_logs_only_the_error_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world(cache=BrokenCache())

    with caplog.at_level(logging.WARNING):
        first = await _ask(world, FIRST)
        again = await _ask(world, SIMILAR)

    assert (first.cache_hit, again.cache_hit) == (False, False)
    assert first.results
    assert _runs(world) == 2
    assert "RuntimeError" in caplog.text
    assert FIRST not in caplog.text


# ---------------------------------------------------------------- hybrid similarity


async def test_with_an_embedding_model_only_the_same_question_asked_again_hits() -> None:
    questions = QuestionModels(
        vectors={
            FIRST: (1.0, 0.0, 0.0),
            SIMILAR: (0.98, 0.2, 0.0),  # the same terms, a close embedding
            PARAPHRASE: (0.96, 0.28, 0.0),  # cosine 0.96, no shared term
        }
    )
    world = await _world(embeddings=questions)
    await _ask(world, FIRST)
    (entry,) = _entries(world)

    again = await _ask(world, SIMILAR)
    paraphrase = await _ask(world, PARAPHRASE)

    assert entry.question.vector == (1.0, 0.0, 0.0)
    assert (
        entry.scope.similarity
        == EmbeddingTarget(profile_kind="openai-compatible", model="e").identity
    )
    assert (again.cache_hit, paraphrase.cache_hit) == (True, False)


async def test_a_failing_question_embedding_compares_words_only_and_logs_no_question(
    caplog: pytest.LogCaptureFixture,
) -> None:
    questions = QuestionModels(fail=True)
    world = await _world(embeddings=questions)

    with caplog.at_level(logging.WARNING):
        await _ask(world, FIRST)
        again = await _ask(world, SIMILAR)

    assert again.cache_hit is True  # the words are similar enough
    assert "RuntimeError" in caplog.text
    assert FIRST not in caplog.text
    assert SIMILAR not in caplog.text


def test_question_terms_fold_plurals_and_verb_endings_and_drop_filler() -> None:
    assert question_terms(FIRST) == ("configure", "retry")
    assert question_terms("Configuring the retry_policy, retried calls") == (
        "configuring",
        "retry",
        "policy",
        "retried",
        "call",
    )
    assert question_terms("how to go from v1 to v2") == ("go", "from", "#1", "to", "#2")


def test_the_scope_fingerprint_covers_the_filter_and_the_limits() -> None:
    version = SearchableVersion(
        library=LIB,
        version="v2",
        manifest_id="m2",
        commit_sha="2" * 40,
        repository_url="https://github.com/acme/payments",
        host=SourceHost.GITHUB,
    )

    def scope(tags: TagFilter, bounds: AgentBounds, similarity: str = "bm25") -> str:
        return AgentCacheScope.of(
            version=version, model=EXPLORER, tag_filter=tags, bounds=bounds, similarity=similarity
        ).fingerprint

    plain = scope(TagFilter(), AgentBounds())
    assert scope(TagFilter(match=TagMatch.ALL), AgentBounds()) == plain  # no tags: match moot
    assert scope(TagFilter(tags=("b", "a")), AgentBounds()) == scope(
        TagFilter(tags=("a", "b", "a")), AgentBounds()
    )
    assert scope(TagFilter(tags=("a",)), AgentBounds()) != plain
    assert scope(TagFilter(tags=("a", "b"), match=TagMatch.ALL), AgentBounds()) != scope(
        TagFilter(tags=("a", "b")), AgentBounds()
    )
    assert scope(TagFilter(), AgentBounds(max_tool_calls=5)) != plain
    assert scope(TagFilter(), AgentBounds(), "local:m:auto:1") != plain
    guided = AgentCacheScope.of(
        version=version,
        model=EXPLORER,
        tag_filter=TagFilter(),
        bounds=AgentBounds(),
        similarity="bm25",
        repo_guidance="notes",
    )
    assert guided.fingerprint != plain


# ---------------------------------------------------------------- pruning and metrics


async def test_the_prune_deletes_old_answers_and_those_of_retired_models_or_spaces() -> None:
    world = await _world()
    await _ask(world, FIRST)
    entry = _entries(world)[0]
    retired = replace(entry, scope=replace(entry.scope, model="corp:retired"))
    other_space = replace(
        entry,
        scope=replace(entry.scope, similarity="x", fingerprint="f"),
    )
    fresh = replace(
        entry, question=CachedQuestion.of(OTHER, key=KEY), created_at=T0 + timedelta(days=6)
    )
    for answer in (retired, other_space, fresh):
        await world.cache.put(answer)
    world.clock.at = T0 + timedelta(days=7, seconds=1)

    pruned = await world.module.prune_hypotheses()

    assert pruned.agentic_answers == 3
    assert _entries(world) == [fresh]


async def test_with_the_cache_off_its_stored_answers_are_still_forgotten_and_pruned() -> None:
    store = InMemoryAgentAnswerCache()
    await store.put(_answer(FIRST, manifest="m2", library=LIB))
    await store.put(_answer(OTHER, manifest="m2", library="/acme/other"))
    world = await _world(enabled=False, cache=store)

    off = await _ask(world, FIRST)
    await world.module.forget_library(ForgetLibraryCommand(library=LIB))
    assert [a.scope.library for a in store.answers.values()] == ["/acme/other"]
    pruned = await world.module.prune_hypotheses()

    assert off.cache_hit is False
    assert pruned.agentic_answers == 1
    assert not store.answers  # off: none is kept


async def test_the_nightly_prune_empties_the_table_when_the_cache_is_off(
    sql_cache_off: Container,
) -> None:
    rows = SqliteAgentAnswerCache(engine=sql_cache_off.engine)
    await rows.put(_answer(FIRST))
    await rows.put(_answer(OTHER, manifest="m2"))

    await sql_cache_off.nightly()

    assert await rows.scoped(_answer(FIRST).scope) == []
    assert await rows.scoped(_answer(OTHER, manifest="m2").scope) == []


@pytest.fixture(params=SQL_BACKENDS)
async def sql_cache_off(request: pytest.FixtureRequest) -> AsyncIterator[Container]:
    """The app on each SQL database with ``[ai.agentic_cache] enabled = false``.

    Yields:
        The running container.
    """
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    ai = AiSettings.model_validate({"agentic_cache": {"enabled": False}})
    container = Container.build(Settings(ai=ai))
    async with container.running(jobs=False):
        yield container


async def test_cache_hits_are_counted_by_cache_and_mode_only() -> None:
    reader = InMemoryMetricReader()
    tracer = OpenTelemetrySearchTracer(meter_provider=MeterProvider(metric_readers=[reader]))

    tracer.cache_hit(cache="agentic_answer", mode="agentic")
    tracer.cache_hit(cache="agentic_answer", mode="agentic")

    data = reader.get_metrics_data()
    assert data is not None
    points = [
        (metric.name, dict(point.attributes or {}), point.value)
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "exactdocs.ai.cache_hits"
        for point in metric.data.data_points
        if isinstance(point, NumberDataPoint)
    ]
    assert points == [
        (
            "exactdocs.ai.cache_hits",
            {"exactdocs.retrieval.mode": "agentic", "exactdocs.cache": "agentic_answer"},
            2,
        )
    ]


# ---------------------------------------------------------------- the cache adapters


def _entries(world: World) -> list[CachedAgentAnswer]:
    store = world.cache
    assert isinstance(store, InMemoryAgentAnswerCache)
    return list(store.answers.values())


async def _bm25(world: World, query: str) -> SearchDocsResult:
    return await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query=query, mode="bm25", limit=10)
    )


def _answer(
    question: str,
    *,
    manifest: str = "m1",
    library: str = "/acme/payments",
    model: str = str(EXPLORER),
    at: datetime = T0,
    vector: tuple[float, ...] | None = None,
    similarity: str = "bm25",
) -> CachedAgentAnswer:
    return CachedAgentAnswer(
        scope=AgentCacheScope(
            library=library,
            manifest_id=manifest,
            model=model,
            fingerprint="f" * 64,
            similarity=similarity,
        ),
        question=CachedQuestion.of(question, key=KEY, vector=vector),
        picks=(
            CachedPick(
                chunk_id=ChunkId("a" * 64),
                justification="It says so.",
                explored_path=("search_docs(retry)",),
            ),
        ),
        limit=5,
        candidates=7,
        complete=True,
        created_at=at,
    )


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def cache(request: pytest.FixtureRequest) -> AsyncIterator[AgentAnswerCache]:
    """Each cache adapter: in memory, and ``retrieval_agentic_answers`` on each SQL database.

    Yields:
        The cache.
    """
    if request.param == "memory":
        yield InMemoryAgentAnswerCache()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield SqliteAgentAnswerCache(engine=container.engine)


async def test_every_cache_stores_reads_a_scope_and_replaces_by_question(
    cache: AgentAnswerCache,
) -> None:
    first = _answer(FIRST, vector=(0.5, -0.25, 1.0))
    newer = replace(first, candidates=9, created_at=T0 + timedelta(hours=1))
    other = _answer(OTHER, at=T0 + timedelta(hours=2))
    elsewhere = _answer(FIRST, manifest="m2")

    for answer in (first, newer, other, elsewhere):
        await cache.put(answer)

    found = await cache.scoped(first.scope)
    assert found == [other, newer]  # newest first; the same question once
    assert found[1].question.vector == (0.5, -0.25, 1.0)
    assert await cache.scoped(replace(first.scope, fingerprint="g" * 64)) == []
    assert await cache.scoped(elsewhere.scope) == [elsewhere]


async def test_every_cache_keeps_the_newest_answers_of_a_scope(cache: AgentAnswerCache) -> None:
    for i in range(AGENT_CACHE_PER_SCOPE + 2):
        await cache.put(_answer(f"question {i}", at=T0 + timedelta(seconds=i)))

    found = await cache.scoped(_answer(FIRST).scope)

    assert len(found) == AGENT_CACHE_PER_SCOPE
    assert found[-1].created_at == T0 + timedelta(seconds=2)


async def test_every_cache_forgets_by_manifest_and_by_library(cache: AgentAnswerCache) -> None:
    await cache.put(_answer(FIRST, manifest="m1"))
    await cache.put(_answer(FIRST, manifest="m2"))
    await cache.put(_answer(FIRST, manifest="m3", library="/acme/other"))

    assert await cache.forget(["m1", "m9"]) == 1
    assert await cache.forget([]) == 0
    assert await cache.forget_library("/ACME/Payments") == 1
    assert await cache.scoped(_answer(FIRST, manifest="m2").scope) == []
    assert len(await cache.scoped(_answer(FIRST, manifest="m3", library="/acme/other").scope)) == 1


async def test_every_cache_prunes_by_age_model_and_space(cache: AgentAnswerCache) -> None:
    old = _answer("old")
    fresh = _answer("fresh", at=T0 + timedelta(days=2))
    retired = _answer("retired", model="corp:retired", at=T0 + timedelta(days=2))
    moved = _answer("moved", similarity="local:m:auto:1", at=T0 + timedelta(days=2))
    moved = replace(moved, scope=replace(moved.scope, fingerprint="e" * 64))
    for answer in (old, fresh, retired, moved):
        await cache.put(answer)

    assert await cache.prune(T0 + timedelta(days=1), {str(EXPLORER)}, "bm25") == 3
    assert await cache.scoped(fresh.scope) == [fresh]
    assert await cache.prune(T0, (), "bm25") == 1  # no model configured: every answer goes


async def test_a_read_only_process_reads_shared_answers_and_keeps_its_own() -> None:
    shared = InMemoryAgentAnswerCache()
    await shared.put(_answer(FIRST))
    cache = ReadOnlyAgentAnswerCache(shared=shared)

    await cache.put(_answer(OTHER, at=T0 + timedelta(hours=1)))
    await cache.put(_answer(FIRST, at=T0 + timedelta(hours=2)))

    found = await cache.scoped(_answer(FIRST).scope)
    assert [a.created_at for a in found] == [T0 + timedelta(hours=2), T0 + timedelta(hours=1)]
    assert len(shared.answers) == 1  # the shared store was not written
    assert await cache.forget_library(LIB) == 2
    assert len(await cache.scoped(_answer(FIRST).scope)) == 1  # the shared one


def test_the_cache_key_is_derived_for_its_own_purpose_and_can_be_turned_off() -> None:
    secret = "a-secret-key-of-enough-characters-0123456789"
    on = Settings(
        secret_key=secret, ai=AiSettings.model_validate({"agentic_cache": {"enabled": True}})
    )
    off = Settings(secret_key=secret)  # off by default

    assert _agent_cache_key(on, create=False) == derived_key(secret, AGENT_CACHE_PURPOSE)
    assert _agent_cache_key(on, create=False) != derived_key(secret, HYDE_CACHE_PURPOSE)
    assert _agent_cache_key(off, create=False) is None
