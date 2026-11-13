"""Steps for the retrieval eval suite (packages/exactdocs/evals): run in-process, like CI runs it.

The suite is development tooling, not an endpoint: these scenarios call it directly, the way
`just eval` does, on the fixture repository the behave hooks built.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from retrieval_eval.dataset import Answer, Question, fingerprint, load_dataset
from retrieval_eval.fixture import run_on_fixture
from retrieval_eval.suite import (
    BASELINE_FILE,
    MODES,
    Comparison,
    compare,
    evaluate_mode,
    judge,
    markdown,
    read_baseline,
    with_evaluators,
)


@when("the eval suite runs with only BM25 available")
def step_run_with_bm25(context: Context) -> None:
    with tempfile.TemporaryDirectory(prefix="exactdocs-eval-") as tmp:
        context.eval_report = asyncio.run(
            run_on_fixture(
                context.fixture_repo,
                Path(tmp) / "data",
                comparison=compare(
                    fingerprint(load_dataset()),
                    read_baseline(BASELINE_FILE),
                    read_baseline(BASELINE_FILE),
                    ratchet=False,
                ),
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
        dataset.name,
        len(dataset.cases),
        [outcome],
        Comparison(baseline=read_baseline(BASELINE_FILE).recall_at_5),
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


# ---------------------------------------------------------------- the baseline and the dataset

_DEVELOP_RECALL = 0.92
"""What develop's baseline stores for BM25 in these scenarios."""


class _AnswersNothing:
    """A mode that finds nothing: recall@5 0 on any dataset, and never a wrong version."""

    async def answer(self, question: Question) -> Answer:
        del question
        return Answer(hits=[])


def _fingerprint_of(context: Context, label: str) -> str:
    """The branch's dataset label stands for the real dataset; any other label for another one.

    Returns:
        The fingerprint the label stands for.
    """
    if label == context.eval_branch_dataset:
        return fingerprint(load_dataset())
    return f"sha256:{label}"


@given('develop\'s baseline was recorded for dataset fingerprint "{label}"')
def step_develop_baseline(context: Context, label: str) -> None:
    context.eval_develop_dataset = label


@given(
    'the branch changes the dataset to fingerprint "{label}" and stores a new baseline for '
    '"{stored}"'
)
def step_branch_changes_dataset(context: Context, label: str, stored: str) -> None:
    context.eval_branch_dataset = label
    context.eval_branch_stored = (stored, 0.0)  # the harder questions measure lower


@given("develop's baseline and the branch use the same dataset fingerprint")
def step_same_dataset(context: Context) -> None:
    context.eval_develop_dataset = context.eval_branch_dataset = "B"


@when("the branch stores a lower recall@5")
def step_branch_lowers(context: Context) -> None:
    context.eval_branch_stored = ("B", _DEVELOP_RECALL - 0.1)
    step_runs_in_ci(context)


@when("the eval runs in CI")
def step_runs_in_ci(context: Context) -> None:
    stored_label, stored_recall = context.eval_branch_stored
    with tempfile.TemporaryDirectory(prefix="exactdocs-eval-") as tmp:
        develop, branch = Path(tmp) / "develop.json", Path(tmp) / "baseline.json"
        for path, label, recall in (
            (develop, context.eval_develop_dataset, _DEVELOP_RECALL),
            (branch, stored_label, stored_recall),
        ):
            data = {
                "dataset": _fingerprint_of(context, label),
                "modes": {"bm25": {"recall_at_5": recall}},
            }
            path.write_text(json.dumps(data), encoding="utf-8")
        dataset = with_evaluators(load_dataset())
        comparison = compare(
            fingerprint(dataset), read_baseline(develop), read_baseline(branch), ratchet=True
        )
        outcome = asyncio.run(evaluate_mode(dataset, MODES[0], _AnswersNothing()))
        context.eval_report = judge(dataset.name, len(dataset.cases), [outcome], comparison)
        context.eval_branch_file = str(branch)


@then('the drop gate and the ratchet compare against the branch\'s baseline for "{label}"')
def step_compared_with_branch(context: Context, label: str) -> None:
    report = context.eval_report
    assert report.passed, report.problems
    assert report.baseline == context.eval_branch_file
    assert report.modes[0].baseline_recall_at_5 == context.eval_branch_stored[1]
    assert context.eval_branch_stored[0] == label


@then("the summary says the baseline was reset because the dataset changed")
def step_summary_says_reset(context: Context) -> None:
    summary = markdown(context.eval_report)
    assert "**Baseline reset:** the dataset changed" in summary, summary


@then('CI fails with "{text}"')
def step_ci_fails_with(context: Context, text: str) -> None:
    report = context.eval_report
    assert not report.passed
    assert any(text in p for p in report.problems), report.problems
