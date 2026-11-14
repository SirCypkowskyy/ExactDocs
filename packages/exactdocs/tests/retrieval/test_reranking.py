"""RET-02 (#93): a cross-encoder reranker reorders a search's top N candidates, never failing it.

The reranker comes from the ``ModelFactory`` port for the role the library resolves to; a fake
factory hands out a scripted reranker, so these tests see what it was sent and decide what it
answers (scores, an error, a hang).
"""

import asyncio
import math
from collections.abc import Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field

import httpx2
import pytest

from exactdocs.retrieval.adapters.driven.http_reranker import HttpReranker
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    GetLibraryRetrievalQuery,
    IndexManifestCommand,
    QueryDocsQuery,
    SearchDocsQuery,
    SearchDocsResult,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.errors import ProviderUnsupportedError, RerankerError
from exactdocs.retrieval.models import (
    CatalogLibrary,
    ChunkId,
    DocTarget,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestStatus,
    ModelCheck,
    ModelRef,
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RerankLimits,
    RetrievalMode,
    SearchableVersion,
    SearchHit,
    SourceHost,
    reorder,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import Reranker, RetrievalPipeline
from exactdocs.retrieval.use_cases import AiProviders, Bm25Pipeline
from exactdocs_kernel import SealedTextUnreadableError

LIB = "/acme/payments"
QUERY = "retry"
VERSION = SearchableVersion(
    library=LIB,
    version="v2",
    manifest_id="m2",
    commit_sha="2" * 40,
    repository_url="https://github.com/acme/payments",
    host=SourceHost.GITHUB,
)
RR = ProviderProfile(
    name="rr",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://rerank.example.com/v2",
)
OWN = ProviderProfile(
    name="own",
    kind=ProviderKind.TEI,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="http://tei.internal:8080",
)
ON_CPU = ProviderProfile(name="cpu", kind=ProviderKind.LOCAL, origin=ProfileOrigin.CONFIGURATION)
"""An in-process (``local``) profile a library can rerank with."""
RERANKER = ModelRef(profile="rr", model="rerank-v3.5")
WITH_HYBRID = InstanceRoles(reranker=RERANKER, embedding=ModelRef(profile="rr", model="embed"))
"""Roles under which ``hybrid`` can run (its stand-in pipeline falls back to BM25)."""
SECTIONS = [f"Retry {'retry ' * (8 - i)}section {i}" for i in range(8)]
"""Eight chunks that all match ``retry``; BM25 ranks them in this order (more mentions first)."""


@dataclass(slots=True)
class ScriptedReranker:
    """Records each call; scores the documents with ``score`` (reversed order by default)."""

    calls: list[tuple[str, list[str]]] = field(default_factory=list)
    fail: BaseException | None = None
    hang: bool = False
    scores: list[float] | None = None

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        if self.hang:
            await asyncio.sleep(10)
        if self.fail is not None:
            raise self.fail
        if self.scores is not None:
            return self.scores
        return [float(i) for i in range(len(documents))]  # the last candidate is the best


@dataclass(slots=True)
class FakeFactory:
    """Implements ``ModelFactory``: hands out the scripted reranker, records what it built."""

    reranker_double: ScriptedReranker
    built: list[tuple[str, str]] = field(default_factory=list)
    refuse: bool = False
    fail: Exception | None = None
    """Raised while building, as a key that no longer opens would be."""
    build_seconds: float = 0.0
    instead: Reranker | None = None
    """Handed out instead of the scripted reranker (a real adapter)."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        return (profile.name, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        return (profile.name, model)

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        if self.refuse:
            raise ProviderUnsupportedError(profile.name, "kind has no rerank API")
        if self.fail is not None:
            raise self.fail
        await asyncio.sleep(self.build_seconds)
        if self.instead is not None:
            return self.instead
        self.built.append((profile.name, model))
        return self.reranker_double

    async def release(self, name: str) -> None:
        del name

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


@dataclass(slots=True)
class FakeVersions:
    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        del ref
        return VERSION if library.lower() == LIB else None

    async def active_id(self, target: DocTarget) -> str | None:
        del target

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


@dataclass(slots=True)
class FallingBack:
    """A pipeline that answers with BM25's hits but says a cheaper mode answered."""

    bm25: RetrievalPipeline
    requests: list[PipelineRequest] = field(default_factory=list)
    ghost: bool = False
    """Put first a hit whose chunk is gone (its manifest was collected meanwhile)."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        self.requests.append(request)
        found = await self.bm25.run(request)
        gone = (SearchHit(chunk_id=ChunkId("gone"), score=99.0, snippet="", highlights=()),)
        return PipelineAnswer(
            mode=RetrievalMode.BM25,
            hits=(*gone, *found.hits) if self.ghost else found.hits,
            candidates=found.candidates + 1 if self.ghost else found.candidates,
            reranked=0,
            complete=found.complete,
            fallback_reason=FallbackReason.EMBEDDING_IN_PROGRESS,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Opened:
    name: str
    query: str | None
    attributes: dict[str, str | None]


@dataclass(slots=True)
class _Span:
    def answered_by(self, mode: str) -> None:
        del mode


@dataclass(slots=True)
class RecordingTracer:
    opened: list[Opened] = field(default_factory=list)

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[_Span]:
        del mode
        self.opened.append(Opened(name=name, query=query, attributes=attributes))
        return nullcontext(_Span())

    def fallback(self, *, mode: str, reason: str) -> None:
        del mode, reason

    def cache_hit(self, *, cache: str, mode: str) -> None:
        del cache, mode


@dataclass(slots=True)
class World:
    module: RetrievalModule
    reranker: ScriptedReranker
    factory: FakeFactory
    modes: InMemoryLibraryModes
    tracer: RecordingTracer
    hybrid: FallingBack


async def _world(
    *,
    roles: InstanceRoles | None = None,
    limits: RerankLimits | None = None,
    reranker: ScriptedReranker | None = None,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    hybrid = FallingBack(bm25=Bm25Pipeline(search=index))
    double = reranker or ScriptedReranker()
    factory = FakeFactory(reranker_double=double)
    modes = InMemoryLibraryModes()
    tracer = RecordingTracer()
    versions = FakeVersions()
    library = CatalogLibrary(
        id=LIB,
        title="Payments",
        description="",
        source_url="https://github.com/acme/payments",
        default_version="v2",
        versions=("v2",),
        version_count=1,
    )
    module = RetrievalModule.build(
        searchable=versions,
        libraries=InMemoryLibraries(libraries=[library]),
        defaults=InMemoryDefaultVersions(),
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=(RR, OWN, ON_CPU),
        instance_roles=roles if roles is not None else InstanceRoles(reranker=RERANKER),
        models=factory,
        rerank_limits=limits,
        pipelines={RetrievalMode.HYBRID: hybrid},
        tracer=tracer,
    )
    await module.index_manifest(
        IndexManifestCommand(
            manifest_id="m2",
            library=LIB,
            ref="v2",
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=f"docs/s{i}.md",
                    blob_sha=f"b{i}",
                    chunks=[
                        ChunkIn(
                            heading_path=[f"S{i}"],
                            occurrence_index=0,
                            content=text,
                            content_hash=f"h{i}",
                            anchor=f"s{i}",
                        )
                    ],
                )
                for i, text in enumerate(SECTIONS)
            ],
        )
    )
    return World(
        module=module,
        reranker=double,
        factory=factory,
        modes=modes,
        tracer=tracer,
        hybrid=hybrid,
    )


async def _unreranked(limit: int) -> list[str]:
    world = await _world(roles=InstanceRoles())
    result = await world.module.search_docs(SearchDocsQuery(library=LIB, query=QUERY, limit=limit))
    return [r.chunk_id for r in result.results]


async def _search(world: World, limit: int = 3) -> SearchDocsResult:
    return await world.module.search_docs(SearchDocsQuery(library=LIB, query=QUERY, limit=limit))


# ---------------------------------------------------------------- reordering


async def test_the_top_n_candidates_are_ordered_by_the_reranker_score() -> None:
    world = await _world(limits=RerankLimits(top_n=5))
    found = await _unreranked(8)

    result = await world.module.search_docs(SearchDocsQuery(library=LIB, query=QUERY, limit=3))

    assert result.reranked is True
    assert result.fallback_reason is None
    assert [r.chunk_id for r in result.results] == found[4::-1][:3]
    assert [r.score for r in result.results] == [4.0, 3.0, 2.0]
    assert (result.coverage.reranked, result.coverage.complete) == (5, False)


async def test_the_reranker_gets_the_query_and_the_chunk_text_only() -> None:
    world = await _world(limits=RerankLimits(top_n=4))

    await _search(world)

    ((query, documents),) = world.reranker.calls
    assert query == QUERY
    assert documents == SECTIONS[:4]
    assert world.factory.built == [("rr", "rerank-v3.5")]


async def test_candidates_beyond_the_top_n_keep_their_order_after_the_reranked_ones() -> None:
    world = await _world(limits=RerankLimits(top_n=2))
    found = await _unreranked(8)

    result = await world.module.search_docs(SearchDocsQuery(library=LIB, query=QUERY, limit=5))

    assert [r.chunk_id for r in result.results] == [found[1], found[0], *found[2:5]]
    assert result.coverage.reranked == 2


async def test_the_pipeline_is_asked_for_the_top_n_when_the_limit_is_smaller() -> None:
    world = await _world(roles=WITH_HYBRID, limits=RerankLimits(top_n=6))

    await world.module.search_docs(
        SearchDocsQuery(library=LIB, query=QUERY, limit=2, mode="hybrid")
    )

    (asked,) = world.hybrid.requests
    assert (asked.limit, asked.rerank) == (6, True)


async def test_the_default_top_n_is_32() -> None:
    world = await _world()

    shown = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))

    assert (shown.rerank_top_n, shown.effective_rerank_top_n) == (None, 32)


async def test_a_library_reranks_its_own_number_of_candidates() -> None:
    world = await _world(limits=RerankLimits(top_n=6))

    shown = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, rerank_top_n=2)
    )
    result = await _search(world)

    assert (shown.rerank_top_n, shown.effective_rerank_top_n) == (2, 2)
    assert len(world.reranker.calls[0][1]) == 2
    assert result.coverage.reranked == 2


async def test_a_library_reranker_override_is_the_one_built() -> None:
    world = await _world()
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, reranker="own:bge-reranker-base")
    )

    await _search(world)

    assert world.factory.built == [("own", "bge-reranker-base")]


async def test_query_docs_is_reranked_too() -> None:
    world = await _world(limits=RerankLimits(top_n=3))

    result = await world.module.query_docs(QueryDocsQuery(library_id=LIB, query=QUERY))

    assert result.reranked is True
    assert [s.content for s in result.sections[:3]] == SECTIONS[2::-1]


async def test_a_library_with_ai_off_is_never_sent_to_the_reranker() -> None:
    world = await _world()
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, ai_enabled=False)
    )

    result = await _search(world)

    assert (result.reranked, result.fallback_reason) == (False, None)
    assert not world.reranker.calls
    assert not world.factory.built


async def test_without_a_reranker_role_nothing_is_reranked() -> None:
    world = await _world(roles=InstanceRoles())

    result = await _search(world)

    assert (result.reranked, result.coverage.reranked, result.fallback_reason) == (False, 0, None)
    assert not world.reranker.calls


# ---------------------------------------------------------------- failures never fail a search


async def test_a_reranker_that_times_out_keeps_the_order_and_says_so() -> None:
    world = await _world(
        limits=RerankLimits(top_n=5, timeout=0.05), reranker=ScriptedReranker(hang=True)
    )
    found = await _unreranked(3)

    result = await _search(world)

    assert [r.chunk_id for r in result.results] == found
    assert (result.reranked, result.coverage.reranked) == (False, 0)
    assert result.fallback_reason is FallbackReason.RERANKER_TIMEOUT


@pytest.mark.parametrize(
    "reranker",
    [
        ScriptedReranker(fail=RerankerError("HTTP 503")),
        ScriptedReranker(scores=[1.0]),  # fewer scores than candidates
        ScriptedReranker(scores=[math.nan, 1.0, 2.0, 3.0, 4.0]),
    ],
    ids=["error", "too-few-scores", "not-finite"],
)
async def test_a_failed_reranker_keeps_the_order_and_says_so(reranker: ScriptedReranker) -> None:
    world = await _world(limits=RerankLimits(top_n=5), reranker=reranker)
    found = await _unreranked(3)

    result = await _search(world)

    assert [r.chunk_id for r in result.results] == found
    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_FAILED)


async def test_a_profile_that_cannot_rerank_keeps_the_order_and_says_so() -> None:
    world = await _world()
    world.factory.refuse = True

    result = await _search(world)

    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_FAILED)


async def test_a_failed_reranker_is_logged_without_the_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world(reranker=ScriptedReranker(fail=RerankerError("HTTP 503")))

    await _search(world)

    assert "reranker of /acme/payments failed" in caplog.text
    assert "HTTP 503" in caplog.text
    assert QUERY not in caplog.text.replace("retrieval", "")


async def test_an_earlier_fallback_reason_is_kept_when_reranking_fails_too() -> None:
    world = await _world(
        roles=WITH_HYBRID, reranker=ScriptedReranker(fail=RerankerError("HTTP 503"))
    )

    result = await world.module.search_docs(
        SearchDocsQuery(library=LIB, query=QUERY, mode="hybrid")
    )

    assert result.fallback_reason is FallbackReason.EMBEDDING_IN_PROGRESS
    assert result.reranked is False


async def test_a_reranker_that_cannot_be_built_keeps_the_order_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world(limits=RerankLimits(top_n=5))
    world.factory.fail = SealedTextUnreadableError()  # the secret key changed since it was stored
    found = await _unreranked(3)

    result = await _search(world)

    assert [r.chunk_id for r in result.results] == found
    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_FAILED)
    assert "could not be built (SealedTextUnreadableError)" in caplog.text
    assert not world.reranker.calls


@pytest.mark.parametrize(
    ("limits", "kind", "seconds"),
    [
        (RerankLimits(), "local", 5.0),
        (RerankLimits(), "openai-compatible", 2.0),
        (RerankLimits(), None, 2.0),
        (RerankLimits(timeout=1.5), "local", 1.5),
        (RerankLimits(timeout=1.5), "tei", 1.5),
    ],
)
def test_an_unset_timeout_is_longer_for_a_local_reranker(
    limits: RerankLimits, kind: str | None, seconds: float
) -> None:
    assert limits.timeout_for(kind) == seconds


@pytest.mark.parametrize(
    ("limits", "seconds"),
    [
        (RerankLimits(), 5.0),
        (RerankLimits(local_timeout=0.5), 2.0),
        (RerankLimits(local_timeout=9.0), 9.0),
        (RerankLimits(timeout=1.5), 1.5),
    ],
)
def test_the_profile_read_is_bounded_by_the_longest_timeout_it_could_need(
    limits: RerankLimits, seconds: float
) -> None:
    assert limits.longest == seconds


async def test_a_library_reranking_on_a_local_profile_gets_the_local_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The instance's reranker is an endpoint (2 s); the library's own runs in-process (#284).
    world = await _world(
        limits=RerankLimits(top_n=5, local_timeout=0.05), reranker=ScriptedReranker(hang=True)
    )
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, reranker="cpu:tiny-reranker")
    )

    result = await _search(world)

    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_TIMEOUT)
    assert world.factory.built == [("cpu", "tiny-reranker")]
    assert "did not answer within 0.05s" in caplog.text


async def test_building_the_reranker_counts_toward_its_timeout() -> None:
    world = await _world(limits=RerankLimits(top_n=5, timeout=0.05))
    world.factory.build_seconds = 1.0

    result = await _search(world)

    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_TIMEOUT)


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (RuntimeError("postgresql://ada:s3cret@db/exactdocs is down"), "reranker_failed"),
        (None, "reranker_timeout"),  # the read stalls
    ],
    ids=["fails", "stalls"],
)
async def test_a_reranker_profile_that_cannot_be_read_keeps_the_order_and_says_so(
    failure: Exception | None,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A stored profile is a database read: it is bounded and guarded like the rerank (#284).
    world = await _world(limits=RerankLimits(top_n=5, timeout=0.05))
    found = await _unreranked(3)

    async def unreadable(*args: object) -> None:
        del args
        if failure is not None:
            raise failure
        await asyncio.sleep(10)

    monkeypatch.setattr(AiProviders, "profile_for", unreadable)

    result = await _search(world)

    assert [r.chunk_id for r in result.results] == found
    assert (result.reranked, result.fallback_reason) == (False, FallbackReason(reason))
    assert not world.factory.built
    assert "s3cret" not in caplog.text
    if failure is not None:
        assert "its profile could not be read (RuntimeError)" in caplog.text


async def test_the_reranker_profile_is_read_once_per_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _world(limits=RerankLimits(top_n=5))
    reads: list[ModelRole] = []
    profile_for = AiProviders.profile_for

    async def counting(
        self: AiProviders, role: ModelRole, library: str, ai: LibraryAi | None = None
    ) -> object:
        reads.append(role)
        return await profile_for(self, role, library, ai)

    monkeypatch.setattr(AiProviders, "profile_for", counting)

    result = await _search(world)

    assert result.reranked is True
    assert reads == [ModelRole.RERANKER]


async def test_a_candidate_gone_before_reranking_is_neither_sent_nor_counted() -> None:
    world = await _world(roles=WITH_HYBRID, limits=RerankLimits(top_n=4))
    plain = await world.module.search_docs(
        SearchDocsQuery(library=LIB, query=QUERY, limit=3, mode="hybrid")
    )
    world.hybrid.ghost = True

    result = await world.module.search_docs(
        SearchDocsQuery(library=LIB, query=QUERY, limit=3, mode="hybrid")
    )

    assert result.coverage.candidates == plain.coverage.candidates
    assert "gone" not in [r.chunk_id for r in result.results]
    assert [len(documents) for _, documents in world.reranker.calls] == [4, 3]


async def test_chunks_are_read_once_and_library_settings_once_per_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _world(limits=RerankLimits(top_n=5))
    read: list[list[str]] = []
    settings_read: list[str] = []
    get_many, ai_of = InMemoryChunkRepository.get_many, InMemoryLibraryModes.ai_of

    async def counting_get_many(
        self: InMemoryChunkRepository, manifest_id: str, chunk_ids: Sequence[ChunkId]
    ) -> object:
        read.append(list(chunk_ids))
        return await get_many(self, manifest_id, chunk_ids)

    async def counting_ai_of(self: InMemoryLibraryModes, library: str) -> LibraryAi:
        settings_read.append(library)
        return await ai_of(self, library)

    monkeypatch.setattr(InMemoryChunkRepository, "get_many", counting_get_many)
    monkeypatch.setattr(InMemoryLibraryModes, "ai_of", counting_ai_of)

    result = await _search(world)

    assert len(result.results) == 3
    assert len(read) == 1  # the reranker's read serves the shown results too
    assert len(settings_read) == 1


async def test_a_closed_http_client_keeps_the_order_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world(limits=RerankLimits(top_n=5))
    client = httpx2.AsyncClient()
    await client.aclose()  # the profile was edited or deleted while the search ran
    world.factory.instead = HttpReranker(
        client=client, base_url="https://rerank.example.com/v2", model="rerank-v3.5"
    )
    found = await _unreranked(3)

    result = await _search(world)

    assert [r.chunk_id for r in result.results] == found
    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_FAILED)
    assert "RuntimeError" in caplog.text
    assert QUERY not in caplog.text.replace("retrieval", "")


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (RuntimeError("client closed"), "RuntimeError"),
        (ExceptionGroup("batches", [RuntimeError("client closed")]), "RuntimeError"),
        (KeyError("boom"), "KeyError"),
    ],
    ids=["runtime-error", "exception-group", "anything"],
)
async def test_whatever_a_reranker_raises_keeps_the_order_and_names_only_its_kind(
    failure: Exception, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    world = await _world(reranker=ScriptedReranker(fail=failure))

    result = await _search(world)

    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_FAILED)
    assert f"it failed ({kind})" in caplog.text
    assert "client closed" not in caplog.text


async def test_a_partly_installed_sdk_keeps_the_order_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world()
    world.factory.fail = ImportError("cannot import name 'x' from 'openai'")

    result = await _search(world)

    assert (result.reranked, result.fallback_reason) == (False, FallbackReason.RERANKER_FAILED)
    assert "could not be built (ImportError)" in caplog.text
    assert "openai" not in caplog.text


async def test_a_cancelled_search_stays_cancelled() -> None:
    world = await _world(reranker=ScriptedReranker(fail=asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await _search(world)


# ---------------------------------------------------------------- tracing


async def test_rerank_is_a_stage_of_its_own_without_the_query_or_any_text() -> None:
    world = await _world()

    await _search(world)
    await world.module.query_docs(QueryDocsQuery(library_id=LIB, query=QUERY))

    names = [o.name for o in world.tracer.opened]
    assert names.index("search_docs.rank") < names.index("search_docs.rerank")
    assert names.index("search_docs.rerank") < names.index("search_docs.chunks")
    assert "query_docs.rerank" in names
    for opened in world.tracer.opened:
        if opened.name.endswith(".rerank"):
            assert (opened.query, opened.attributes) == (None, {})


async def test_no_rerank_stage_without_a_reranker() -> None:
    world = await _world(roles=InstanceRoles())

    await _search(world)

    assert "search_docs.rerank" not in [o.name for o in world.tracer.opened]


# ---------------------------------------------------------------- the model


def _hit(name: str, score: float) -> SearchHit:
    return SearchHit(chunk_id=ChunkId(name), score=score, snippet=name, highlights=())


def test_reorder_sorts_the_scored_head_and_keeps_the_tail() -> None:
    hits = [_hit("a", 9), _hit("b", 8), _hit("c", 7), _hit("d", 6)]

    reordered = reorder(hits, [0.1, 0.7, 0.4])

    assert [(h.chunk_id, h.score) for h in reordered] == [
        ("b", 0.7),
        ("c", 0.4),
        ("a", 0.1),
        ("d", 6),
    ]


def test_reorder_keeps_the_mode_order_on_ties() -> None:
    hits = [_hit("a", 3), _hit("b", 2), _hit("c", 1)]

    assert [h.chunk_id for h in reorder(hits, [0.5, 0.5, 0.5])] == ["a", "b", "c"]


def test_a_library_top_n_is_an_override() -> None:
    assert not LibraryAi(rerank_top_n=4).is_default
    assert LibraryAi().is_default
