"""The retrieval eval suite: its dataset, its metrics, its gates, and BM25 on the real import."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.models import (
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    RetrievalMode,
)
from fixture_repo import FIXTURE, DocsRepo, git_bytes, headings
from retrieval_eval.cli import main
from retrieval_eval.dataset import Answer, Hit, Question, load_dataset
from retrieval_eval.fixture import run_on_fixture
from retrieval_eval.suite import (
    BASELINE_FILE,
    MODES,
    ModeMetrics,
    ModeOutcome,
    Tier,
    baseline_of,
    evaluate_mode,
    judge,
    markdown,
    read_baseline,
    with_evaluators,
)

BM25 = next(m for m in MODES if m.mode is RetrievalMode.BM25)
HYBRID = next(m for m in MODES if m.mode is RetrievalMode.HYBRID)


def _expected_queries() -> list[tuple[dict[str, Any], str, dict[str, Any] | None]]:
    table = yaml.safe_load((FIXTURE / "expected-queries.yaml").read_text(encoding="utf-8"))
    return [
        (entry, version, expected)
        for entry in table["queries"]
        for version, expected in entry["expected"].items()
    ]


# ---------------------------------------------------------------- the dataset


def test_the_dataset_holds_every_expected_query_of_the_fixture() -> None:
    cases = {c.name: c for c in load_dataset().cases}

    for entry, version, expected in _expected_queries():
        tags = f" [{','.join(entry['tags'])}]" if "tags" in entry else ""
        case = cases[f"{version}: {entry['query']}{tags}"]
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


V2_HIT = Hit(version="v2.0.0", article="docs/guide/resilience.md", heading_path=["Resilience"])


async def _judged(retriever: Any, baseline: dict[str, float] | None = None) -> ModeOutcome:
    dataset = with_evaluators(load_dataset())
    outcome = await evaluate_mode(dataset, BM25, retriever)
    report = judge(dataset.name, len(dataset.cases), [outcome], baseline or {})
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

    report = judge(dataset.name, len(dataset.cases), [outcome], {"bm25": 0.5})

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

    report = judge(dataset.name, len(dataset.cases), [outcome], {})

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
    report = judge("retrieval", 10, [_ran(BM25, recall_at_5)], {"bm25": 0.90})

    assert report.passed is passed
    assert report.modes[0].baseline_recall_at_5 == pytest.approx(0.90)
    assert report.modes[0].recall_at_5_delta_points == pytest.approx((recall_at_5 - 0.90) * 100)


def test_a_report_only_mode_that_drops_warns_without_failing() -> None:
    report = judge(
        "retrieval", 10, [_ran(BM25, 0.9), _ran(HYBRID, 0.5)], {"bm25": 0.9, "hybrid": 0.9}
    )

    assert report.passed
    assert report.warnings == [
        "hybrid: recall@5 50.0 is 40.0 points below the baseline 90.0 (at most 2.0 allowed)"
    ]


def test_a_report_only_mode_with_a_wrong_version_still_fails() -> None:
    report = judge("retrieval", 10, [_ran(BM25, 0.9), _ran(HYBRID, 1.0, wrong=["x"])], {})

    assert not report.passed
    assert report.modes[1].eligible_as_default is False


@pytest.mark.parametrize(("hybrid", "eligible"), [(0.95, True), (0.9499, False), (0.6, False)])
def test_a_mode_may_become_a_default_only_when_it_beats_bm25_by_five_points(
    hybrid: float, eligible: bool
) -> None:
    report = judge("retrieval", 10, [_ran(BM25, 0.9), _ran(HYBRID, hybrid)], {})

    assert report.modes[0].eligible_as_default is None
    assert report.modes[1].eligible_as_default is eligible


def test_the_baseline_keeps_ranking_metrics_not_latency(tmp_path: Path) -> None:
    report = judge("retrieval", 10, [_ran(BM25, 0.9)], {})
    path = tmp_path / "baseline.json"
    path.write_text(baseline_of(report), encoding="utf-8")

    assert read_baseline(path) == {"bm25": 0.9}
    assert "latency_p50_ms" not in json.loads(path.read_text(encoding="utf-8"))["modes"]["bm25"]
    assert read_baseline(tmp_path / "missing.json") == {}


def test_the_summary_has_a_row_per_mode_and_the_verdict() -> None:
    unavailable = ModeOutcome(
        mode=RetrievalMode.HYBRID, tier=Tier.LOCAL, gating=False, status="unavailable",
        reason="needs the embedding role, not configured",
    )  # fmt: skip
    report = judge(
        "retrieval", 10, [_ran(BM25, 0.9, wrong=["v1.4.0: q: v2.0.0 a > b"]), unavailable], {}
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
        docs_repo, tmp_path / "data", baseline=read_baseline(BASELINE_FILE)
    )

    assert report.passed, report.problems
    bm25, *others = report.modes
    assert bm25.status == "ran"
    assert bm25.metrics is not None
    assert bm25.metrics.wrong_version_rate == 0
    assert bm25.metrics.recall_at_5 >= read_baseline(BASELINE_FILE)["bm25"] - 0.02
    assert bm25.fallbacks == 0
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
    async def configured(self, library: str) -> frozenset[ModelRole]:
        del library
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

    def build(data_dir: Path) -> Container:
        return Container.build(
            Settings(data_dir=data_dir), model_roles=AllRoles(), pipelines=pipelines
        )

    report = await run_on_fixture(docs_repo, tmp_path / "data", build=build)

    outcomes = {o.mode: o for o in report.modes}
    hybrid = outcomes[RetrievalMode.HYBRID]
    assert hybrid.status == "ran"
    assert hybrid.metrics is not None
    assert hybrid.metrics.recall_at_5 == 0
    assert hybrid.eligible_as_default is False
    assert report.passed  # a report-only mode that finds nothing does not fail the suite
    for hosted in (RetrievalMode.HYBRID_HYDE, RetrievalMode.AGENTIC):
        assert outcomes[hosted].status == "skipped"
        assert pipelines[hosted].calls == []


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
