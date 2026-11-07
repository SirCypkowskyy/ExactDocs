"""Steps for the retrieval eval suite (packages/exactdocs/evals): run in-process, like CI runs it.

The suite is development tooling, not an endpoint: these scenarios call it directly, the way
`just eval` does, on the fixture repository the behave hooks built.
"""

import asyncio
import tempfile
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from retrieval_eval.dataset import Answer, Question, load_dataset
from retrieval_eval.fixture import run_on_fixture
from retrieval_eval.suite import (
    BASELINE_FILE,
    MODES,
    evaluate_mode,
    judge,
    read_baseline,
    with_evaluators,
)


@when("the eval suite runs with only BM25 available")
def step_run_with_bm25(context: Context) -> None:
    with tempfile.TemporaryDirectory(prefix="exactdocs-eval-") as tmp:
        context.eval_report = asyncio.run(
            run_on_fixture(
                context.fixture_repo, Path(tmp) / "data", baseline=read_baseline(BASELINE_FILE)
            )
        )


@then('it reports recall@k, wrong-version rate, cost and latency for "{mode}"')
def step_reports_metrics(context: Context, mode: str) -> None:
    outcome = next(o for o in context.eval_report.modes if o.mode == mode)
    assert outcome.status == "ran", outcome
    metrics = outcome.metrics.model_dump()
    for name in (
        "recall_at_1", "recall_at_5", "recall_at_10", "mrr", "wrong_version_rate",
        "latency_p50_ms", "latency_p95_ms", "tokens_per_question", "usd_per_question",
    ):  # fmt: skip
        assert name in metrics, name
    assert metrics["wrong_version_rate"] == 0
    assert metrics["recall_at_5"] > 0
    assert metrics["latency_p95_ms"] >= metrics["latency_p50_ms"] > 0
    assert context.eval_report.passed, context.eval_report.problems


@then("the modes that need a model are reported as unavailable, with the role they lack")
def step_others_unavailable(context: Context) -> None:
    others = [o for o in context.eval_report.modes if o.mode != "bm25"]
    assert others
    for outcome in others:
        assert outcome.status == "unavailable", outcome
        assert outcome.metrics is None
        assert all(role.value in outcome.reason for role in outcome.mode.roles), outcome.reason


class _OneStrayChunk:
    """Answers every question with its expected section, plus one chunk of another version."""

    def __init__(self, stray_version: str, pinned: str) -> None:
        self.stray_version = stray_version
        self.pinned = pinned
        self.strayed = False

    async def answer(self, question: Question) -> Answer:
        case = next(c for c in load_dataset().cases if c.inputs == question)
        hits = list(case.expected_output.hits) if case.expected_output else []
        if question.version == self.pinned and hits and not self.strayed:
            self.strayed = True
            hits.append(hits[0].model_copy(update={"version": self.stray_version}))
        return Answer(hits=hits)


@given('a mode returns one chunk of "{stray}" for a question pinned to "{pinned}"')
def step_stray_chunk(context: Context, stray: str, pinned: str) -> None:
    context.eval_retriever = _OneStrayChunk(stray, pinned)


@when("the eval suite runs")
def step_run(context: Context) -> None:
    dataset = with_evaluators(load_dataset())
    outcome = asyncio.run(evaluate_mode(dataset, MODES[0], context.eval_retriever))
    context.eval_report = judge(
        dataset.name, len(dataset.cases), [outcome], read_baseline(BASELINE_FILE)
    )


@then("it fails, whatever the recall")
def step_fails(context: Context) -> None:
    report = context.eval_report
    (outcome,) = report.modes
    assert outcome.metrics.recall_at_1 == outcome.metrics.recall_at_5 == 1
    assert not report.passed
    assert len(outcome.wrong_version_cases) == 1
    assert "v2.0.0" in outcome.wrong_version_cases[0]
    assert any("another version" in p for p in report.problems), report.problems
