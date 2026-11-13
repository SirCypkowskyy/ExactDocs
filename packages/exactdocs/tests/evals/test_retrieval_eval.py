"""The retrieval eval suite: its dataset, its metrics, its gates, and BM25 on the real import."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult
from exactdocs.retrieval.models import (
    AgentRead,
    ChunkId,
    LibraryAi,
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    RerankWith,
    RetrievalMode,
    SearchHit,
)
from exactdocs.retrieval.ports.driven import AgentReads
from fake_llm import gateway
from fixture_import import LIBRARY, commits, import_fixture
from fixture_repo import FIXTURE, DocsRepo, git_bytes, headings
from offline_embedding import (
    JUDGE,
    LLM,
    offline_data_container,
    offline_hyde_container,
    offline_judge_container,
)
from retrieval_eval.cli import OFFLINE_NOT_JUDGED, main
from retrieval_eval.dataset import (
    DATASET_FILE,
    Answer,
    Hit,
    Question,
    TracedRead,
    fingerprint,
    load_dataset,
)
from retrieval_eval.fixture import model_free_container, run_on_fixture
from retrieval_eval.suite import (
    BASELINE_FILE,
    MODES,
    Comparison,
    ModeMetrics,
    ModeOutcome,
    StoredBaseline,
    SuiteReport,
    Tier,
    baseline_of,
    compare,
    evaluate_mode,
    judge,
    markdown,
    read_baseline,
    run_modes,
    with_evaluators,
)
from scripted_explorer import ScriptedModels, browsing, scripted_ai

BM25 = next(m for m in MODES if m.mode is RetrievalMode.BM25)
HYBRID = next(m for m in MODES if m.mode is RetrievalMode.HYBRID)
HYBRID_HYDE = next(m for m in MODES if m.mode is RetrievalMode.HYBRID_HYDE)
AGENTIC = next(m for m in MODES if m.mode is RetrievalMode.AGENTIC)


def _expected_queries() -> list[tuple[dict[str, Any], str, dict[str, Any] | None]]:
    table = yaml.safe_load((FIXTURE / "expected-queries.yaml").read_text(encoding="utf-8"))
    return [
        (entry, version, expected)
        for entry in table["queries"]
        for version, expected in entry["expected"].items()
    ]


# ---------------------------------------------------------------- the dataset


def _identifier_name(entry: dict[str, Any], version: str) -> str:
    tags = f" [{','.join(entry['tags'])}]" if "tags" in entry else ""
    return f"{version}: {entry['query']}{tags}"


def test_the_identifier_cases_are_exactly_the_fixture_expected_queries() -> None:
    identifiers = {
        c.name for c in load_dataset().cases if c.metadata and c.metadata.kind == "identifier"
    }

    assert identifiers == {_identifier_name(e, v) for e, v, _ in _expected_queries()}


def test_the_dataset_holds_every_expected_query_of_the_fixture() -> None:
    cases = {c.name: c for c in load_dataset().cases}

    for entry, version, expected in _expected_queries():
        case = cases[_identifier_name(entry, version)]
        assert case.metadata is not None
        assert case.metadata.kind == "identifier"
        assert case.inputs == Question(
            query=entry["query"],
            version=version,
            tags=entry.get("tags", []),
            tags_match=entry.get("tags_match", "any"),
        )
        assert case.expected_output is not None
        hits = [(h.version, h.article, h.heading_path) for h in case.expected_output.hits]
        want = (
            [] if expected is None else [(version, expected["article"], expected["heading_path"])]
        )
        assert hits == want


def test_the_dataset_adds_natural_language_questions_in_every_version() -> None:
    questions = [c for c in load_dataset().cases if c.metadata and c.metadata.kind == "question"]

    assert len(questions) >= 20
    assert {c.inputs.version for c in questions} == {"v1.3.0", "v1.4.0", "next"}
    assert all(c.inputs.query.endswith("?") for c in questions)


@pytest.mark.parametrize("case", load_dataset().cases, ids=lambda c: c.name)
def test_every_expected_section_exists_in_its_version(docs_repo: DocsRepo, case: Any) -> None:
    for hit in case.expected_output.hits:
        assert hit.version == case.inputs.version
        raw = git_bytes("show", f"{hit.version}:{hit.article}", cwd=docs_repo.path)
        text = raw.decode("latin-1") if hit.article.endswith("latin1.md") else raw.decode()
        assert tuple(hit.heading_path) in headings(text)


def test_every_retrieval_mode_has_a_tier_and_only_bm25_gates() -> None:
    assert [m.mode for m in MODES] == list(RetrievalMode)
    assert [m.mode for m in MODES if m.gating] == [RetrievalMode.BM25]
    assert {m.mode: m.tier for m in MODES}[RetrievalMode.HYBRID] is Tier.LOCAL
    assert {m.tier for m in MODES if m.mode.roles & {ModelRole.LLM}} == {Tier.PROVIDER}


# ---------------------------------------------------------------- metrics and gates, with fakes


def _ideal(question: Question) -> list[Hit]:
    case = next(c for c in load_dataset().cases if c.inputs == question)
    assert case.expected_output is not None
    return list(case.expected_output.hits)


@dataclass
class Perfect:
    """Returns the expected section first, plus ``extra`` hits for the questions it names."""

    extra: dict[str, list[Hit]] = field(default_factory=dict)
    commit: str | None = None

    async def answer(self, question: Question) -> Answer:
        hits = _ideal(question) + self.extra.get(f"{question.version}: {question.query}", [])
        return Answer(hits=hits, pinned_commit=self.commit, answered_by="bm25")


@dataclass
class Nothing:
    async def answer(self, question: Question) -> Answer:
        del question
        return Answer(hits=[], answered_by="bm25")


@dataclass
class Broken:
    async def answer(self, question: Question) -> Answer:
        del question
        message = "index unreadable"
        raise RuntimeError(message)


@dataclass
class ModeFellBackAndRerankerFailed:
    """The mode fell back and the reranker failed: only the mode's reason is shown."""

    async def answer(self, question: Question) -> Answer:
        return Answer(
            hits=_ideal(question),
            answered_by="bm25",
            reranked=False,
            fallback_reason="embedding_in_progress",
        )


async def test_a_reranker_failure_counts_even_when_another_fallback_reason_is_shown() -> None:
    dataset = with_evaluators(load_dataset())
    answered = sum(1 for c in dataset.cases if c.expected_output and c.expected_output.hits)

    expected = await evaluate_mode(dataset, BM25, ModeFellBackAndRerankerFailed(), rerank=True)
    not_expected = await evaluate_mode(dataset, BM25, ModeFellBackAndRerankerFailed())

    assert (expected.reranked, expected.rerank_fallbacks) == (0, answered)
    assert not_expected.rerank_fallbacks == 0


V2_HIT = Hit(version="v2.0.0", article="docs/guide/resilience.md", heading_path=["Resilience"])


async def _judged(retriever: Any, baseline: dict[str, float] | None = None) -> ModeOutcome:
    dataset = with_evaluators(load_dataset())
    outcome = await evaluate_mode(dataset, BM25, retriever)
    report = judge(dataset.name, len(dataset.cases), [outcome], Comparison(baseline=baseline or {}))
    return report.modes[0]


async def test_a_perfect_mode_scores_full_recall_and_no_wrong_version() -> None:
    outcome = await _judged(Perfect())

    assert outcome.metrics is not None
    assert outcome.metrics.recall_at_1 == outcome.metrics.recall_at_10 == outcome.metrics.mrr == 1
    assert outcome.metrics.wrong_version_rate == 0
    assert outcome.metrics.questions == len(load_dataset().cases)
    assert outcome.metrics.tokens_per_question == outcome.metrics.usd_per_question == 0
    assert outcome.metrics.latency_p95_ms >= outcome.metrics.latency_p50_ms >= 0
    assert not outcome.misses


async def test_one_result_of_another_version_fails_the_suite_whatever_the_recall() -> None:
    dataset = with_evaluators(load_dataset())
    retriever = Perfect(extra={"v1.4.0: retry_policy": [V2_HIT]})
    outcome = await evaluate_mode(dataset, BM25, retriever)

    report = judge(dataset.name, len(dataset.cases), [outcome], Comparison(baseline={"bm25": 0.5}))

    assert not report.passed
    assert outcome.metrics is not None
    assert outcome.metrics.recall_at_5 == 1
    assert outcome.metrics.wrong_version_rate == pytest.approx(1 / len(dataset.cases), abs=1e-4)
    assert outcome.wrong_version_cases == [
        "v1.4.0: retry_policy: v2.0.0 docs/guide/resilience.md > Resilience"
    ]
    assert "another version" in report.problems[0]


async def test_a_result_read_from_another_commit_is_of_another_version() -> None:
    outcome = await Perfect(commit="a" * 40).answer(Question(query="docker", version="v1.4.0"))
    stray = outcome.model_copy(
        update={"hits": [h.model_copy(update={"commit_sha": "b" * 40}) for h in outcome.hits]}
    )

    @dataclass
    class FromOtherCommit:
        async def answer(self, question: Question) -> Answer:
            if question == Question(query="docker", version="v1.4.0"):
                return stray
            return Answer(hits=_ideal(question))

    judged = await _judged(FromOtherCommit())

    assert judged.wrong_version_cases == [
        "v1.4.0: docker: v1.4.0 docs/guide/install.md > Guide > Install > Docker"
    ]


async def test_an_answer_for_a_version_without_one_must_still_be_of_that_version() -> None:
    hit = Hit(version="v1.4.0", article="docs/guide/resilience.md", heading_path=["Resilience"])

    outcome = await _judged(Perfect(extra={"v1.3.0: retry_policy": [hit]}))

    assert [c.split(":")[0] for c in outcome.wrong_version_cases] == ["v1.3.0"]


async def test_recall_and_mrr_count_only_questions_whose_version_has_an_answer() -> None:
    outcome = await _judged(Nothing())

    assert outcome.metrics is not None
    answerable = sum(
        1 for c in load_dataset().cases if c.expected_output and c.expected_output.hits
    )
    assert outcome.metrics.answerable == answerable
    assert outcome.metrics.recall_at_10 == outcome.metrics.mrr == 0
    assert outcome.metrics.wrong_version_rate == 0
    assert len(outcome.misses) == answerable


async def test_a_question_that_raises_fails_the_suite() -> None:
    dataset = with_evaluators(load_dataset())
    outcome = await evaluate_mode(dataset, BM25, Broken())

    report = judge(dataset.name, len(dataset.cases), [outcome], Comparison())

    assert not report.passed
    assert len(outcome.errors) == len(dataset.cases)
    assert "index unreadable" in outcome.errors[0]


def _ran(mode: Any, recall_at_5: float, *, wrong: list[str] | None = None) -> ModeOutcome:
    metrics = ModeMetrics(
        questions=10, answerable=10, recall_at_1=recall_at_5, recall_at_5=recall_at_5,
        recall_at_10=recall_at_5, mrr=recall_at_5, wrong_version_rate=0.1 if wrong else 0.0,
        latency_p50_ms=1, latency_p95_ms=2, tokens_per_question=0, usd_per_question=0,
    )  # fmt: skip
    return ModeOutcome(
        mode=mode.mode, tier=mode.tier, gating=mode.gating, status="ran", metrics=metrics,
        wrong_version_cases=wrong or [],
    )  # fmt: skip


@pytest.mark.parametrize(
    ("recall_at_5", "passed"), [(0.90, True), (0.88, True), (0.8799, False), (0.95, True)]
)
def test_bm25_recall_at_5_may_drop_at_most_two_points_below_the_baseline(
    recall_at_5: float, passed: bool
) -> None:
    report = judge("retrieval", 10, [_ran(BM25, recall_at_5)], Comparison(baseline={"bm25": 0.90}))

    assert report.passed is passed
    assert report.modes[0].baseline_recall_at_5 == pytest.approx(0.90)
    assert report.modes[0].recall_at_5_delta_points == pytest.approx((recall_at_5 - 0.90) * 100)


def test_a_report_only_mode_that_drops_warns_without_failing() -> None:
    report = judge(
        "retrieval",
        10,
        [_ran(BM25, 0.9), _ran(HYBRID, 0.5)],
        Comparison(baseline={"bm25": 0.9, "hybrid": 0.9}),
    )

    assert report.passed
    assert report.warnings == [
        "hybrid: recall@5 50.0 is 40.0 points below the baseline 90.0 (at most 2.0 allowed)"
    ]


def test_a_report_only_mode_with_a_wrong_version_still_fails() -> None:
    report = judge("retrieval", 10, [_ran(BM25, 0.9), _ran(HYBRID, 1.0, wrong=["x"])], Comparison())

    assert not report.passed
    assert report.modes[1].eligible_as_default is False


@pytest.mark.parametrize(("hybrid", "eligible"), [(0.95, True), (0.9499, False), (0.6, False)])
def test_a_mode_may_become_a_default_only_when_it_beats_bm25_by_five_points(
    hybrid: float, eligible: bool
) -> None:
    report = judge("retrieval", 10, [_ran(BM25, 0.9), _ran(HYBRID, hybrid)], Comparison())

    assert report.modes[0].eligible_as_default is None
    assert report.modes[1].eligible_as_default is eligible


def test_a_gating_mode_without_a_baseline_entry_warns() -> None:
    report = judge("retrieval", 10, [_ran(BM25, 0.9)], Comparison(baseline={"hybrid": 0.5}))

    assert report.passed
    assert report.warnings == ["bm25: no baseline to compare with, so its recall@5 is not gated"]


@pytest.mark.parametrize(
    ("stored", "passed"), [({"bm25": 0.90}, True), ({"bm25": 0.95}, True), ({"bm25": 0.89}, False),
                           ({}, False)],
)  # fmt: skip
def test_the_stored_baseline_may_only_move_up(stored: dict[str, float], passed: bool) -> None:
    comparison = Comparison(baseline={"bm25": 0.90}, ratchet=stored)
    report = judge("retrieval", 10, [_ran(BM25, 0.9)], comparison)

    assert report.passed is passed
    if not passed:
        assert "the baseline only moves up" in report.problems[0]


def test_the_baseline_keeps_ranking_metrics_not_latency(tmp_path: Path) -> None:
    report = judge("retrieval", 10, [_ran(BM25, 0.9)], Comparison(), fingerprint="sha256:abc")
    path = tmp_path / "baseline.json"
    path.write_text(baseline_of(report), encoding="utf-8")

    assert read_baseline(path) == StoredBaseline(
        recall_at_5={"bm25": 0.9}, dataset="sha256:abc", source=str(path)
    )
    assert "latency_p50_ms" not in json.loads(path.read_text(encoding="utf-8"))["modes"]["bm25"]
    assert read_baseline(tmp_path / "missing.json") == StoredBaseline(recall_at_5={})


def test_the_summary_has_a_row_per_mode_and_the_verdict() -> None:
    unavailable = ModeOutcome(
        mode=RetrievalMode.HYBRID, tier=Tier.LOCAL, gating=False, status="unavailable",
        reason="needs the embedding role, not configured",
    )  # fmt: skip
    report = judge(
        "retrieval",
        10,
        [_ran(BM25, 0.9, wrong=["v1.4.0: q: v2.0.0 a > b"]), unavailable],
        Comparison(),
    )

    text = markdown(report)

    assert text.startswith("## Retrieval eval: failed")
    assert "| bm25 | ran | 90 | 90 | 90 | 0.900 | 0.100 |" in text
    assert "| hybrid | unavailable: needs the embedding role, not configured |" in text
    assert "- `bm25` wrong version: v1.4.0: q: v2.0.0 a > b" in text


# ---------------------------------------------------------------- the app, for real


async def test_bm25_on_the_fixture_meets_the_stored_baseline_and_reports_the_rest(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    report = await run_on_fixture(
        docs_repo,
        tmp_path / "data",
        build=model_free_container,
        comparison=Comparison(baseline=read_baseline(BASELINE_FILE).recall_at_5),
    )

    assert report.passed, report.problems
    assert not report.warnings
    bm25, *others = report.modes
    assert bm25.status == "ran"
    assert bm25.metrics is not None
    assert bm25.metrics.wrong_version_rate == 0
    assert bm25.metrics.recall_at_5 >= read_baseline(BASELINE_FILE).recall_at_5["bm25"] - 0.02
    assert bm25.fallbacks == 0
    assert report.search_engine == "fts5"
    assert [(o.mode, o.status, o.reason) for o in others] == [
        (RetrievalMode.HYBRID, "unavailable", "needs the embedding role, not configured"),
        (
            RetrievalMode.HYBRID_HYDE,
            "unavailable",
            "needs the embedding and llm roles, not configured",
        ),
        (RetrievalMode.AGENTIC, "unavailable", "needs the llm role, not configured"),
    ]  # fmt: skip


@dataclass(frozen=True)
class AllRoles:
    async def configured(self, library: str, ai: LibraryAi | None = None) -> frozenset[ModelRole]:
        del library, ai
        return frozenset(ModelRole)


@dataclass
class Silent:
    """A mode that finds nothing: enough to see the suite run a mode beside BM25."""

    mode: RetrievalMode
    calls: list[str] = field(default_factory=list)

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        self.calls.append(request.query)
        return PipelineAnswer(mode=self.mode, hits=(), candidates=0, reranked=0, complete=True)


async def test_a_new_mode_plugs_in_and_hosted_ones_stay_off_without_permission(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    pipelines = {m: Silent(m) for m in RetrievalMode if m is not RetrievalMode.BM25}

    def build(data_dir: Path, *, agent_reads: AgentReads | None = None) -> Container:
        return Container.build(
            Settings(data_dir=data_dir),
            model_roles=AllRoles(),
            pipelines=pipelines,
            agent_reads=agent_reads,
        )

    local = frozenset({ModelRole.EMBEDDING, ModelRole.RERANKER})
    report = await run_on_fixture(docs_repo, tmp_path / "data", build=build, local_roles=local)

    outcomes = {o.mode: o for o in report.modes}
    assert outcomes[RetrievalMode.BM25].status == "ran"
    hybrid = outcomes[RetrievalMode.HYBRID]
    assert hybrid.status == "ran"
    assert hybrid.metrics is not None
    assert hybrid.metrics.recall_at_5 == 0
    assert hybrid.eligible_as_default is False
    assert report.passed  # a report-only mode that finds nothing does not fail the suite
    for hosted in (RetrievalMode.HYBRID_HYDE, RetrievalMode.AGENTIC):
        assert outcomes[hosted].status == "skipped"
        assert "(llm)" in (outcomes[hosted].reason or "")
        assert pipelines[hosted].calls == []


async def test_a_local_tier_mode_on_a_hosted_model_is_skipped_without_permission(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    pipelines = {m: Silent(m) for m in RetrievalMode if m is not RetrievalMode.BM25}

    def build(data_dir: Path, *, agent_reads: AgentReads | None = None) -> Container:
        return Container.build(
            Settings(data_dir=data_dir),
            model_roles=EmbeddingOnly(),
            pipelines=pipelines,
            agent_reads=agent_reads,
        )

    report = await run_on_fixture(docs_repo, tmp_path / "data", build=build)

    hybrid = next(o for o in report.modes if o.mode is RetrievalMode.HYBRID)
    assert hybrid.tier is Tier.LOCAL
    assert hybrid.status == "skipped"
    assert hybrid.reason is not None
    assert hybrid.reason.startswith("would call a hosted model (embedding)")
    assert pipelines[RetrievalMode.HYBRID].calls == []

    allowed = await run_on_fixture(docs_repo, tmp_path / "again", build=build, allow_providers=True)
    assert next(o for o in allowed.modes if o.mode is RetrievalMode.HYBRID).status == "ran"


async def test_a_configured_reranker_is_evaluated_only_with_permission(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    with gateway() as fake:
        ai = AiSettings.model_validate(
            {
                "providers": {"rr": {"kind": "openai-compatible", "base_url": f"{fake.url}/v2"}},
                "reranker": {"model": "rr:rerank-v3.5"},
            }
        )

        def build(data_dir: Path, *, agent_reads: AgentReads | None = None) -> Container:
            return Container.build(Settings(data_dir=data_dir, ai=ai), agent_reads=agent_reads)

        modes = [m for m in MODES if m.mode is RetrievalMode.BM25]
        held = await run_on_fixture(docs_repo, tmp_path / "data", build=build, modes=modes)
        assert not fake.seen
        allowed = await run_on_fixture(
            docs_repo, tmp_path / "again", build=build, modes=modes, allow_providers=True
        )

    (skipped,) = held.modes
    assert (skipped.status, skipped.reason) == (
        "skipped",
        (
            "would call a hosted model (reranker): run by hand with --allow-providers, or pass "
            "--local-roles reranker if it runs on this machine"
        ),
    )
    (bm25,) = allowed.modes
    assert bm25.metrics is not None
    answered = sum(1 for c in load_dataset().cases if c.expected_output and c.expected_output.hits)
    assert bm25.rerank_fallbacks == 0
    assert answered <= bm25.reranked <= bm25.metrics.questions
    assert bm25.metrics.wrong_version_rate == 0
    assert f"`bm25` reranked {bm25.reranked} of {bm25.metrics.questions}" in markdown(allowed)
    assert all(s.path == "/v2/rerank" for s in fake.seen)


@dataclass(frozen=True)
class EmbeddingOnly:
    async def configured(self, library: str, ai: LibraryAi | None = None) -> frozenset[ModelRole]:
        del library, ai
        return frozenset({ModelRole.EMBEDDING})


@dataclass
class LeakingResponses:
    """The real retrieval module, except that one answer carries a chunk of another version.

    It is labelled with the version asked for, as a search that lost its version filter would
    label it: only reading the chunk back shows where it came from.
    """

    inner: Any
    question: Question
    leaked: str

    @property
    def get_library_retrieval(self) -> Any:
        return self.inner.get_library_retrieval

    @property
    def read_chunk(self) -> Any:
        return self.inner.read_chunk

    @property
    def search_docs(self) -> Any:
        async def search(query: SearchDocsQuery) -> SearchDocsResult:
            result = await self.inner.search_docs(query)
            if (query.ref, query.query) != (self.question.version, self.question.query):
                return result
            first, *rest = result.results
            stray = first.model_copy(update={"chunk_id": self.leaked})
            return result.model_copy(update={"results": [stray, *rest]})

        return search


async def test_a_chunk_of_another_version_in_a_real_answer_fails_the_suite(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    container = model_free_container(tmp_path / "data")
    async with container.running(jobs=False):
        await import_fixture(container, docs_repo)
        older = await container.retrieval.search_docs(
            SearchDocsQuery(library=LIBRARY, ref="v1.3.0", query="docker")
        )
        retrieval = LeakingResponses(
            inner=container.retrieval,
            question=Question(query="docker", version="v1.4.0"),
            leaked=older.results[0].chunk_id,
        )
        outcomes = await run_modes(
            with_evaluators(load_dataset()),
            retrieval=retrieval,
            library=LIBRARY,
            commits=commits(docs_repo),
            modes=[BM25],
        )

    report = judge("retrieval", len(load_dataset().cases), outcomes, Comparison())

    assert not report.passed
    assert outcomes[0].wrong_version_cases == [
        "v1.4.0: docker: v1.3.0 docs/guide/setup.md > Guide > Install > Docker"
    ]


@dataclass
class OtherVersionPipeline:
    """A hybrid stand-in that answers every question with one chunk of ``v1.3.0``."""

    leaked: list[str] = field(default_factory=list)

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        del request
        hits = tuple(
            SearchHit(chunk_id=ChunkId(c), score=1.0, snippet="", highlights=())
            for c in self.leaked
        )
        return PipelineAnswer(
            mode=RetrievalMode.HYBRID, hits=hits, candidates=1, reranked=0, complete=True
        )


async def test_the_app_drops_a_pipeline_hit_of_another_version_before_it_is_answered(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    pipeline = OtherVersionPipeline()
    container = Container.build(
        Settings(data_dir=tmp_path / "data"),
        model_roles=EmbeddingOnly(),
        pipelines={RetrievalMode.HYBRID: pipeline},
    )
    async with container.running(jobs=False):
        await import_fixture(container, docs_repo)
        older = await container.retrieval.search_docs(
            SearchDocsQuery(library=LIBRARY, ref="v1.3.0", query="docker", mode="bm25")
        )
        pipeline.leaked.append(older.results[0].chunk_id)
        outcomes = await run_modes(
            with_evaluators(load_dataset()),
            retrieval=container.retrieval,
            library=LIBRARY,
            commits=commits(docs_repo),
            modes=[HYBRID],
            local_roles=frozenset({ModelRole.EMBEDDING}),
        )

    (hybrid,) = outcomes
    assert hybrid.status == "ran"
    assert hybrid.metrics is not None
    # Questions pinned to v1.3.0 get the chunk (it is theirs); every other version gets nothing.
    assert hybrid.wrong_version_cases == []
    assert hybrid.metrics.recall_at_10 > 0


def test_the_command_writes_the_json_report_and_the_job_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")

    code = main([
        "--modes", "bm25", "--report", str(tmp_path / "out" / "retrieval.json"),
        "--summary", str(summary), "--baseline", str(BASELINE_FILE),
    ])  # fmt: skip

    assert code == 0
    report = json.loads((tmp_path / "out" / "retrieval.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert [m["mode"] for m in report["modes"]] == ["bm25"]
    assert set(report["modes"][0]["metrics"]) >= {
        "recall_at_1", "recall_at_5", "recall_at_10", "mrr", "wrong_version_rate",
        "latency_p50_ms", "latency_p95_ms", "tokens_per_question", "usd_per_question",
    }  # fmt: skip
    assert summary.read_text(encoding="utf-8").startswith("earlier step\n## Retrieval eval: passed")


def test_the_command_refuses_an_unknown_mode() -> None:
    assert main(["--modes", "magic"]) == 2


def test_the_command_refuses_a_baseline_it_was_given_that_does_not_exist(tmp_path: Path) -> None:
    assert main(["--baseline", str(tmp_path / "typo.json")]) == 2


def test_the_command_fails_when_the_branch_lowers_the_baseline(tmp_path: Path) -> None:
    higher = tmp_path / "develop.json"
    data = {"dataset": fingerprint(load_dataset()), "modes": {"bm25": {"recall_at_5": 0.99}}}
    higher.write_text(json.dumps(data), encoding="utf-8")

    code = main([
        "--modes", "bm25", "--baseline", str(higher), "--ratchet",
        "--report", str(tmp_path / "r.json"),
    ])  # fmt: skip

    assert code == 1
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert any("the baseline only moves up" in p for p in report["problems"])


def test_the_command_resets_the_baseline_when_develop_measured_another_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    develop = tmp_path / "develop.json"
    data = {"dataset": "sha256:older", "modes": {"bm25": {"recall_at_5": 0.99}}}
    develop.write_text(json.dumps(data), encoding="utf-8")
    summary = tmp_path / "summary.md"

    code = main([
        "--modes", "bm25", "--baseline", str(develop), "--ratchet",
        "--report", str(tmp_path / "r.json"), "--summary", str(summary),
    ])  # fmt: skip

    assert code == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["baseline"] == "packages/exactdocs/evals/retrieval_eval/baseline.json"
    assert report["fingerprint"] == fingerprint(load_dataset())
    assert "**Baseline reset:** the dataset changed (sha256:older to " in summary.read_text(
        encoding="utf-8"
    )
    # A warning annotation, so the reset shows on the pull request's checks too.
    assert "::warning title=Eval baseline reset::the dataset changed" in capsys.readouterr().out


@pytest.mark.parametrize(("develop_recall", "code"), [(0.92, 0), (0.99, 1)])
def test_on_a_reset_the_reference_dataset_is_still_gated_against_the_reference_baseline(
    tmp_path: Path, develop_recall: float, code: int
) -> None:
    develop = tmp_path / "develop.json"
    data = {"dataset": "sha256:older", "modes": {"bm25": {"recall_at_5": develop_recall}}}
    develop.write_text(json.dumps(data), encoding="utf-8")
    summary = tmp_path / "summary.md"

    result = main([
        "--modes", "bm25", "--baseline", str(develop), "--ratchet",
        "--reference-dataset", str(DATASET_FILE),
        "--report", str(tmp_path / "r.json"), "--summary", str(summary),
    ])  # fmt: skip

    assert result == code
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["passed"] is True
    reference = json.loads((tmp_path / "r-reference.json").read_text(encoding="utf-8"))
    assert reference["passed"] is (code == 0)
    assert reference["baseline_reset"] is None
    verdict = "passed" if code == 0 else "failed"
    assert f"## Retrieval eval on the reference dataset: {verdict}" in summary.read_text(
        encoding="utf-8"
    )


def test_the_command_refuses_a_reference_dataset_that_does_not_exist(tmp_path: Path) -> None:
    assert main(["--reference-dataset", str(tmp_path / "typo.yaml")]) == 2


async def test_a_case_the_fixture_cannot_answer_fails_loudly(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    old = tmp_path / "dataset.yaml"
    old.write_text(
        """name: retrieval
cases:
- name: gone version
  inputs: {query: snake_case, version: v0.9.0}
  expected_output: {hits: []}
- name: gone section
  inputs: {query: snake_case, version: v1.4.0}
  expected_output:
    hits:
    - {version: v1.4.0, article: docs/reference/naming.md, heading_path: [Naming conventions, x]}
- name: gone article
  inputs: {query: snake_case, version: v1.4.0}
  expected_output:
    hits:
    - {version: v1.4.0, article: docs/gone.md, heading_path: [Gone]}
""",
        encoding="utf-8",
    )

    report = await run_on_fixture(docs_repo, tmp_path / "data", dataset_file=old)

    assert not report.passed
    assert report.problems[:3] == [
        "gone version: the fixture has no version v0.9.0",
        (
            "gone section: the fixture has no section v1.4.0:docs/reference/naming.md "
            "Naming conventions > x"
        ),
        "gone article: the fixture has no section v1.4.0:docs/gone.md Gone",
    ]


# ---------------------------------------------------------------- the dataset's fingerprint


def test_the_stored_baseline_was_recorded_for_the_dataset_in_the_repository() -> None:
    assert read_baseline(BASELINE_FILE).dataset == fingerprint(load_dataset())


def test_the_fingerprint_follows_questions_and_expectations_not_names_or_order() -> None:
    dataset = load_dataset()
    before = fingerprint(dataset)
    first, second, *rest = dataset.cases
    dataset.cases = [second, replace(first, name="renamed"), *rest]

    assert fingerprint(dataset) == before
    assert before.startswith("sha256:")

    harder = replace(first, inputs=first.inputs.model_copy(update={"query": "x"}))
    dataset.cases = [harder, second, *rest]
    assert fingerprint(dataset) != before

    no_answer = replace(first, expected_output=Answer(hits=[]))
    dataset.cases = [no_answer, second, *rest]
    assert fingerprint(dataset) != before


def test_the_fingerprint_ignores_defaults_and_fields_the_dataset_does_not_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dataset.yaml"
    path.write_text(
        """name: retrieval
cases:
- name: one
  inputs: {query: snake_case, version: v1.4.0}
  expected_output:
    hits:
    - {version: v1.4.0, article: docs/reference/naming.md, heading_path: [Naming conventions]}
- name: two
  inputs: {query: nothing, version: next, tags: [a]}
  expected_output: {hits: []}
""",
        encoding="utf-8",
    )
    dataset = load_dataset(path)
    pinned = fingerprint(dataset)
    one, two = dataset.cases
    assert one.expected_output is not None

    # Pinned: a field added to Question, Answer or Hit with a default must not move it.
    assert pinned == "sha256:5d2cb488a370fc1e"
    dataset.cases = [
        replace(
            one,
            inputs=one.inputs.model_copy(update={"tags_match": "any"}),
            expected_output=one.expected_output.model_copy(
                update={
                    "pinned_commit": "abc",
                    "answered_by": "bm25",
                    "search_ms": 1.0,
                    "hits": [one.expected_output.hits[0].model_copy(update={"commit_sha": "abc"})],
                }
            ),
        ),
        two,
    ]
    assert fingerprint(dataset) == pinned


def _stored(recall: float, dataset: str, source: str) -> StoredBaseline:
    return StoredBaseline(recall_at_5={"bm25": recall}, dataset=dataset, source=source)


def test_on_the_same_dataset_the_drop_gate_and_the_ratchet_use_develops_baseline() -> None:
    comparison = compare(
        "sha256:a", _stored(0.9, "sha256:a", "develop"), _stored(0.8, "sha256:a", "branch"),
        ratchet=True,
    )  # fmt: skip
    report = judge("retrieval", 10, [_ran(BM25, 0.9)], comparison)

    assert comparison.baseline == {"bm25": 0.9}
    assert report.baseline == "develop"
    assert report.baseline_reset is None
    assert report.problems == [
        (
            "bm25: the branch's baseline.json stores recall@5 80.0, below the 90.0 it is compared "
            "with; the baseline only moves up"
        )
    ]


def test_a_changed_dataset_compares_with_the_branchs_baseline_and_says_so() -> None:
    comparison = compare(
        "sha256:b", _stored(0.9, "sha256:a", "develop"), _stored(0.5, "sha256:b", "branch"),
        ratchet=True,
    )  # fmt: skip
    report = judge("retrieval", 10, [_ran(BM25, 0.5)], comparison, fingerprint="sha256:b")

    assert report.passed, report.problems
    assert report.baseline == "branch"
    assert report.modes[0].baseline_recall_at_5 == pytest.approx(0.5)
    assert report.baseline_reset == (
        "the dataset changed (sha256:a to sha256:b): recall@5 is compared with the branch's "
        "`branch` instead of the reference baseline, and the ratchet starts again from it"
    )
    assert "- **Baseline reset:** the dataset changed" in markdown(report)
    assert "(`sha256:b`)" in markdown(report)


def test_a_reference_without_a_fingerprint_counts_as_another_dataset() -> None:
    comparison = compare(
        "sha256:b", StoredBaseline(recall_at_5={"bm25": 0.9}, source="develop"),
        _stored(0.5, "sha256:b", "branch"), ratchet=True,
    )  # fmt: skip

    assert comparison.baseline == {"bm25": 0.5}
    assert comparison.reset is not None
    assert comparison.reset.startswith(
        "the reference baseline has no dataset fingerprint yet (it was written before "
        "fingerprints), so it may measure another dataset than this one (sha256:b)"
    )


def test_the_branch_baseline_must_be_recorded_for_the_dataset_it_is_measured_on() -> None:
    comparison = compare(
        "sha256:c", _stored(0.9, "sha256:a", "develop"), _stored(0.5, "sha256:b", "branch"),
        ratchet=True,
    )  # fmt: skip
    report = judge("retrieval", 10, [_ran(BM25, 0.5)], comparison)

    assert not report.passed
    assert report.problems == [
        (
            "branch was recorded for dataset sha256:b, not this one (sha256:c): run "
            "`just eval --write-baseline`"
        )
    ]
    # Once: no per-mode "no baseline to compare with" on top of it.
    assert report.warnings == [
        (
            "no baseline was recorded for this dataset (sha256:c), so recall@5 is not gated: run "
            "`just eval --write-baseline`"
        )
    ]


def test_without_the_ratchet_a_stale_baseline_only_warns() -> None:
    stale = _stored(0.9, "sha256:a", "baseline.json")
    report = judge("retrieval", 10, [_ran(BM25, 0.5)], compare("sha256:b", stale, stale,
                                                                ratchet=False))  # fmt: skip

    assert report.passed
    assert len(report.warnings) == 1
    assert report.warnings[0].startswith("no baseline was recorded for this dataset (sha256:b)")


@pytest.mark.parametrize(
    ("develop", "dataset", "stored", "measured", "problem"),
    [
        (0.95, "sha256:a", 0.95, 0.94, None),  # kept from develop: the drop gate allows it
        (0.80, "sha256:a", 0.95, 0.94, "above the 94.0"),  # raised: must be measured
        (0.95, "sha256:old", 0.95, 0.94, "above the 94.0"),  # reset: must be measured
        (0.92, "sha256:old", 0.50, 0.70, "below the 70.0"),  # reset: the next bar, not lower
        (0.92, "sha256:old", 0.70, 0.70, None),
    ],
)
def test_a_stored_recall_the_run_does_not_back_up_fails(
    develop: float, dataset: str, stored: float, measured: float, problem: str | None
) -> None:
    comparison = compare(
        "sha256:a", _stored(develop, dataset, "develop"), _stored(stored, "sha256:a", "branch"),
        ratchet=True,
    )  # fmt: skip
    report = judge("retrieval", 10, [_ran(BM25, measured)], comparison)

    assert report.passed is (problem is None), report.problems
    if problem is not None:
        assert report.problems == [
            (
                f"bm25: the branch's baseline.json stores recall@5 {stored * 100:.1f}, {problem} "
                "measured on the same dataset: run `just eval --write-baseline`"
            )
        ]


def test_a_mode_without_any_baseline_gets_no_per_mode_warning() -> None:
    assert judge("retrieval", 10, [_ran(BM25, 0.9)], Comparison()).warnings == []


async def test_another_search_engine_than_the_expected_one_fails_the_suite(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    report = await run_on_fixture(
        docs_repo, tmp_path / "data", build=model_free_container, expect_engine="pg_search"
    )

    assert not report.passed
    assert "the search engine was fts5, not the expected pg_search" in report.problems
    assert "on the `fts5` search engine" in markdown(report)


# ---------------------------------------------------------------- hybrid on the stand-in embedding


async def test_hybrid_is_reported_against_bm25_on_the_offline_embedding(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    report = await run_on_fixture(
        docs_repo,
        tmp_path / "data",
        build=offline_data_container,
        modes=[BM25, HYBRID],
        local_roles=frozenset({ModelRole.EMBEDDING}),
        comparison=Comparison(baseline=read_baseline(BASELINE_FILE).recall_at_5),
        not_judged=OFFLINE_NOT_JUDGED,
    )

    assert report.passed, report.problems
    bm25, hybrid = report.modes
    assert (hybrid.mode, hybrid.status, hybrid.fallbacks) == (RetrievalMode.HYBRID, "ran", 0)
    assert hybrid.metrics is not None
    assert bm25.metrics is not None
    assert hybrid.metrics.wrong_version_rate == 0
    assert hybrid.wrong_version_cases == []
    assert hybrid.errors == []
    # The fusion keeps what BM25 finds: the stand-in may not lower recall@5 below BM25's.
    assert hybrid.metrics.recall_at_5 >= bm25.metrics.recall_at_5
    # The stand-in cannot tell whether hybrid should be a default: never yes or no.
    assert (hybrid.eligible_as_default, hybrid.not_judged) == (None, "offline embedding")
    # Every hybrid question embedded its query; BM25 costs nothing.
    assert hybrid.metrics.tokens_per_question > 0
    assert bm25.metrics.tokens_per_question == 0


def _echo(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """A stand-in LLM whose hypothetical answer restates the question.

    Returns:
        A response restating the question.
    """
    del info
    question = next(
        str(part.content)
        for message in messages
        for part in getattr(message, "parts", ())
        if part.part_kind == "user-prompt"
    )
    return ModelResponse(parts=[TextPart(content=f"The documentation says: {question}")])


@pytest.mark.parametrize(
    "chat",
    [
        pytest.param(lambda: FunctionModel(_echo, model_name=LLM), id="FunctionModel"),
        pytest.param(
            lambda: TestModel(custom_output_text="RetryPolicy", model_name=LLM), id="TestModel"
        ),
    ],
)
async def test_hybrid_hyde_runs_through_the_suite_on_a_stand_in_llm(
    docs_repo: DocsRepo, tmp_path: Path, chat: Callable[[], object]
) -> None:
    report = await run_on_fixture(
        docs_repo,
        tmp_path / "data",
        build=offline_hyde_container(chat),
        modes=[BM25, HYBRID_HYDE],
        local_roles=frozenset({ModelRole.EMBEDDING, ModelRole.LLM}),
        comparison=Comparison(baseline=read_baseline(BASELINE_FILE).recall_at_5),
        not_judged=OFFLINE_NOT_JUDGED,
    )

    assert report.passed, report.problems
    bm25, hyde = report.modes
    assert (hyde.mode, hyde.status, hyde.fallbacks, hyde.errors) == (
        RetrievalMode.HYBRID_HYDE,
        "ran",
        0,
        [],
    )
    assert hyde.metrics is not None
    assert bm25.metrics is not None
    assert hyde.metrics.wrong_version_rate == 0
    assert hyde.wrong_version_cases == []
    # A stand-in LLM cannot tell whether HyDE should be a default.
    assert (hyde.eligible_as_default, hyde.not_judged) == (None, "offline embedding")
    # The LLM step (priced) and the embedding of its answer reach the report; BM25 costs nothing.
    assert hyde.metrics.tokens_per_question > 0
    assert hyde.metrics.usd_per_question > 0
    assert (bm25.metrics.tokens_per_question, bm25.metrics.usd_per_question) == (0, 0)


_CANDIDATE = re.compile(r'<candidate id="(c[0-9]+)">(.*?)</candidate>', re.DOTALL)
_QUERY = re.compile(r"<query>(.*?)</query>", re.DOTALL)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def _lexical_judge(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """A stand-in judge that rates each candidate by the query words it shares (at most 10).

    Returns:
        A response calling the rating tool with the ratings.
    """
    prompt = next(
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )
    query = _words(_QUERY.findall(prompt)[0])
    ratings = [
        {"id": candidate, "score": min(10, len(query & _words(text)))}
        for candidate, text in _CANDIDATE.findall(prompt)
    ]
    tool = info.output_tools[0]
    return ModelResponse(parts=[ToolCallPart(tool.name, {"response": ratings})])


async def test_the_judge_reranker_runs_through_the_suite_on_a_stand_in(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    report = await run_on_fixture(
        docs_repo,
        tmp_path / "data",
        build=offline_judge_container(lambda: FunctionModel(_lexical_judge, model_name=JUDGE)),
        modes=[BM25],
        local_roles=frozenset({ModelRole.JUDGE}),
    )

    (bm25,) = report.modes
    assert (bm25.status, bm25.reranker, bm25.errors) == ("ran", RerankWith.JUDGE, [])
    assert bm25.metrics is not None
    assert bm25.metrics.wrong_version_rate == 0, "the judge only reorders the version's own hits"
    assert bm25.wrong_version_cases == []
    assert bm25.reranked > 0
    assert bm25.rerank_fallbacks == 0, "every judgment was measured"
    # The judge's priced step reaches the report.
    assert bm25.metrics.tokens_per_question > 0
    assert bm25.metrics.usd_per_question > 0
    assert "the LLM judge failed or timed out on 0" in markdown(report)


async def test_a_hosted_judge_is_skipped_unless_allowed(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    report = await run_on_fixture(
        docs_repo,
        tmp_path / "data",
        build=offline_judge_container(lambda: FunctionModel(_lexical_judge, model_name=JUDGE)),
        modes=[BM25],
    )

    (bm25,) = report.modes
    assert bm25.status == "skipped"
    assert bm25.reason is not None
    assert "judge" in bm25.reason


# ---------------------------------------------------------------- agentic on a scripted model


def scripted_agentic_container(
    data_dir: Path, *, agent_reads: AgentReads | None = None
) -> Container:
    """The app with the ``llm`` role on a scripted pydantic-ai ``FunctionModel`` (no provider).

    Args:
        data_dir: The data directory.
        agent_reads: Records the explorer's reads (the suite's trace check).

    Returns:
        The container: ``agentic`` runs its real pipeline, Code Mode and limits.
    """
    ai = AiSettings.model_validate(scripted_ai(mode=None))
    return Container.build(
        Settings(data_dir=data_dir, ai=ai),
        model_factory=ScriptedModels(model=browsing()),
        agent_reads=agent_reads,
    )


async def test_agentic_is_evaluated_on_a_scripted_model_and_stays_in_the_version(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    report = await run_on_fixture(
        docs_repo,
        tmp_path / "data",
        build=scripted_agentic_container,
        modes=[BM25, AGENTIC],
        local_roles=frozenset({ModelRole.LLM}),  # the scripted model runs in this process
        not_judged={RetrievalMode.AGENTIC: "scripted model"},
    )

    assert report.passed, report.problems
    bm25, agentic = report.modes
    assert (agentic.mode, agentic.status, agentic.fallbacks) == (RetrievalMode.AGENTIC, "ran", 0)
    assert agentic.metrics is not None
    assert bm25.metrics is not None
    # Every question ran the agent, and none of its answers left the version asked for.
    assert agentic.metrics.wrong_version_rate == 0
    assert agentic.wrong_version_cases == []
    # Its traces: every run left one, and none read outside the version asked for (#99).
    assert agentic.traced_runs == agentic.metrics.questions
    assert agentic.left_version_cases == []
    assert agentic.errors == []
    assert agentic.metrics.recall_at_10 > 0
    # Its spend went through the harness SpendLimits into the ledger the suite reads.
    assert agentic.metrics.tokens_per_question > 0
    assert (agentic.eligible_as_default, agentic.not_judged) == (None, "scripted model")


def test_the_command_runs_hybrid_offline_and_says_it_is_a_stand_in(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"

    code = main([
        "--offline-embedding", "--modes", "bm25,hybrid", "--report", str(tmp_path / "r.json"),
        "--summary", str(summary), "--baseline", str(BASELINE_FILE),
    ])  # fmt: skip

    assert code == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert [(m["mode"], m["status"]) for m in report["modes"]] == [
        ("bm25", "ran"),
        ("hybrid", "ran"),
    ]
    text = summary.read_text(encoding="utf-8")
    assert "term-hash embedding" in text
    assert "| not judged (offline embedding) |" in text
    assert report["modes"][1]["eligible_as_default"] is None


@pytest.mark.parametrize("other", ["--configured-models", "--write-baseline"])
def test_the_offline_embedding_never_meets_real_models_or_the_baseline(other: str) -> None:
    before = BASELINE_FILE.read_text(encoding="utf-8")

    assert main(["--offline-embedding", other]) == 2
    assert BASELINE_FILE.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------- the agentic runs' traces (#99)


def _read(version: str, *, served: str | None = None, manifest: str = "m-asked") -> TracedRead:
    """A traced read bound to ``version`` that served ``served`` (``version`` by default).

    Returns:
        The traced read.
    """
    return TracedRead(
        tool="read_chunk",
        pinned_version=f"{LIBRARY}/{version}",
        pinned_manifest=manifest,
        served_versions=[f"{LIBRARY}/{served or version}"],
        served_manifests=[manifest],
    )


@dataclass
class Traced:
    """An agentic stand-in: the ideal hits, with a trace that ``stray`` reads leave for one case."""

    stray: list[TracedRead] = field(default_factory=list)
    strays_on: Question = field(default_factory=lambda: Question(query="docker", version="v1.4.0"))

    async def answer(self, question: Question) -> Answer:
        reads = [_read(question.version)]
        if question == self.strays_on:
            reads += self.stray
        return Answer(hits=_ideal(question), answered_by="agentic", library=LIBRARY, reads=reads)


async def _judged_agentic(retriever: Any) -> tuple[ModeOutcome, SuiteReport]:
    dataset = with_evaluators(load_dataset())
    outcome = await evaluate_mode(dataset, AGENTIC, retriever)
    report = judge(dataset.name, len(dataset.cases), [outcome], Comparison())
    return report.modes[0], report


async def test_a_run_that_stayed_in_its_version_passes_the_trace_check() -> None:
    outcome, report = await _judged_agentic(Traced())

    assert report.passed, report.problems
    assert outcome.left_version_cases == []
    assert outcome.traced_runs == len(load_dataset().cases)


@pytest.mark.parametrize(
    ("stray", "named"),
    [
        (_read("v1.3.0"), f"read_chunk read {LIBRARY}/v1.3.0"),
        (_read("v1.4.0", served="v1.3.0"), f"read_chunk read {LIBRARY}/v1.3.0"),
        (_read("v1.4.0", manifest="m-other"), "more than one manifest"),
    ],
    ids=["bound to another version", "served another version", "another manifest"],
)
async def test_a_read_outside_the_asked_version_fails_the_suite_though_every_hit_is_right(
    stray: TracedRead, named: str
) -> None:
    outcome, report = await _judged_agentic(Traced(stray=[stray]))

    assert not report.passed
    assert outcome.wrong_version_cases == []  # the hits are all of the version
    (case,) = outcome.left_version_cases
    assert case.startswith("v1.4.0: docker: ")
    assert named in case
    assert any("read outside the version asked for" in p for p in report.problems)
    assert "read outside its version" in markdown(report)


async def test_an_agentic_answer_without_a_trace_fails_the_suite() -> None:
    @dataclass
    class Untraced:
        async def answer(self, question: Question) -> Answer:
            return Answer(hits=_ideal(question), answered_by="agentic", library=LIBRARY, reads=[])

    outcome, report = await _judged_agentic(Untraced())

    assert not report.passed
    answered = sum(1 for c in load_dataset().cases if c.expected_output and c.expected_output.hits)
    assert len(outcome.left_version_cases) == answered
    assert all("without a trace" in c for c in outcome.left_version_cases)


@dataclass
class StrayingPipeline:
    """An agentic stand-in whose agent was bound to ``v1.3.0`` whatever the question asked, yet
    answers with nothing: only its trace tells."""

    reads: AgentReads

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        self.reads.record(
            AgentRead(
                search=request.search,
                tool="search_docs",
                pinned_version=f"{request.version.library}/v1.3.0",
                pinned_manifest="m-old",
            )
        )
        return PipelineAnswer(
            mode=RetrievalMode.AGENTIC, hits=(), candidates=0, reranked=0, complete=True
        )


async def test_the_suite_reads_the_app_s_trace_of_every_agentic_run(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    def build(data_dir: Path, *, agent_reads: AgentReads | None = None) -> Container:
        assert agent_reads is not None  # the suite always hands the app its recorder
        return Container.build(
            Settings(data_dir=data_dir),
            model_roles=AllRoles(),
            pipelines={RetrievalMode.AGENTIC: StrayingPipeline(reads=agent_reads)},
            agent_reads=agent_reads,
        )

    report = await run_on_fixture(
        docs_repo,
        tmp_path / "data",
        build=build,
        modes=[AGENTIC],
        local_roles=frozenset(ModelRole),  # the stand-ins call nothing
    )

    (agentic,) = report.modes
    assert agentic.status == "ran", agentic.reason
    assert not report.passed
    assert agentic.wrong_version_cases == []
    # Every question not pinned to v1.3.0 shows the stray read in its trace.
    others = sum(1 for c in load_dataset().cases if c.inputs.version != "v1.3.0")
    assert len(agentic.left_version_cases) == others
