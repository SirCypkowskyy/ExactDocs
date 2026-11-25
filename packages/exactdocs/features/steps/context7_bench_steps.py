"""Steps for the Context7 run (packages/exactdocs/evals): ``just context7-bench`` in-process.

Context7 is ``context7_stand_in``, which answers ``/v2/context`` in its documented shape; nothing
reaches the network. The corpus is the retrieval benchmark's tiny one (its step makes it).
"""

from behave import given, then, when
from behave.runner import Context

from context7_stand_in import DATE, OTHER_RELEASE, StandInContext7
from retrieval_eval.context7 import (
    LATEST_ONLY,
    NOT_SERVED,
    PINNED,
    SERVED,
    UNVERIFIED,
    Context7Report,
    markdown,
)
from retrieval_eval.context7_cli import main
from retrieval_eval.grounded_docs import TEXT_BASELINE

_SHOWN = ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "wrong_version_rate")


@given("a stand-in for Context7 that serves the pinned version")
def step_pinned(context: Context) -> None:
    context.context7 = StandInContext7(serves="pinned")


@given("a stand-in for Context7 that serves another release in place of the pinned version")
def step_other_release(context: Context) -> None:
    context.context7 = StandInContext7(serves="other release")


@given("a stand-in for Context7 that serves only the library's current documentation")
def step_current_only(context: Context) -> None:
    context.context7 = StandInContext7(serves="current only")


def _run(context: Context, *extra: str) -> None:
    tmp = context.bench_dir
    context.exit_code = main(
        [
            "--corpus", str(tmp / "corpus.yaml"), "--cases", str(tmp / "cases"),
            "--cache-dir", str(tmp / "cache"), "--responses", str(tmp / "responses"),
            "--out", str(tmp / "out"), "--recorded", str(tmp / "none.json"), *extra,
        ],
        tool=lambda: context.context7,
    )  # fmt: skip
    path = tmp / "out" / "context7.json"
    context.report = Context7Report.model_validate_json(path.read_text("utf-8"))


@when("the run resolves each pinned version in Context7 and asks its questions")
@given("the run resolved each pinned version in Context7 and asked its questions")
def step_run(context: Context) -> None:
    _run(context)
    context.first_report = context.report


@when("the run is repeated from its cache of Context7's responses")
def step_rerun(context: Context) -> None:
    context.calls_before = len(context.context7.calls)
    _run(context, "--from-cache")


def _coverage(context: Context):
    assert context.exit_code == 0
    (coverage,) = context.report.coverage
    assert (coverage.project, coverage.version) == ("demo", "v1")
    return coverage


@then("the report states that Context7 serves the version unverified")
def step_unverified(context: Context) -> None:
    assert _coverage(context).status == UNVERIFIED
    assert f"| demo | v1 | {UNVERIFIED} |" in markdown(context.report)


@then("the coverage names the library ID Context7 resolved, the release it served and the date")
def step_named(context: Context) -> None:
    coverage = _coverage(context)
    assert coverage.resolved_id.endswith(f"/{OTHER_RELEASE}")
    assert coverage.served == OTHER_RELEASE
    assert coverage.date == DATE
    (group,) = context.report.groups
    assert group.name == UNVERIFIED


@then("every question went to Context7 with the library and the pinned version")
def step_asked(context: Context) -> None:
    assert _coverage(context).status == SERVED
    library = context.report.coverage[0].requested_id
    assert library.endswith("/v1")
    assert {q for _, q in context.context7.calls} == {
        "install demo package pip",
        "kubernetes operator crd",
    }
    assert {lib for lib, _ in context.context7.calls} == {library}


@then(
    "the results are scored with the text scorer next to ExactDocs' configurations, with intervals"
)
def step_scored(context: Context) -> None:
    report = context.report
    (group,) = report.groups
    assert group.name == PINNED
    answerable = next(r for r in group.rows if r.row.answerable)
    assert answerable.row.rank == 1  # the Install section's text
    assert group.baseline.tool == TEXT_BASELINE
    base, mine = group.baseline.metrics.metrics, group.result.metrics.metrics
    assert set(base.intervals) == set(mine.intervals)
    assert all(name in mine.intervals for name in _SHOWN)
    assert {v.against for v in group.versus} == {TEXT_BASELINE}
    assert report.scorer["threshold"] > 0
    summary = markdown(report)
    assert f"| {TEXT_BASELINE} |" in summary
    assert "| Context7 pinned |" in summary
    assert "### Paired tests against ExactDocs" in summary


@then("the report states that Context7 does not serve the version")
def step_not_served(context: Context) -> None:
    coverage = _coverage(context)
    assert coverage.status == NOT_SERVED
    assert coverage.served is None


@then(
    "its questions are asked without a version and reported as latest only, apart from the "
    "pinned numbers"
)
def step_latest_only(context: Context) -> None:
    (group,) = context.report.groups
    assert group.name == LATEST_ONLY
    unpinned = context.report.coverage[0].requested_id.removesuffix("/v1")
    asked = {lib for lib, q in context.context7.calls if q == "kubernetes operator crd"}
    assert asked == {unpinned}
    assert "| Context7 latest only |" in markdown(context.report)
    assert "| Context7 pinned |" not in markdown(context.report)


@then("Context7 is not called again")
def step_not_called(context: Context) -> None:
    assert context.exit_code == 0
    assert len(context.context7.calls) == context.calls_before


@then("the results are the same")
def step_same(context: Context) -> None:
    before, after = context.first_report, context.report
    assert before.coverage == after.coverage
    assert [g.rows for g in before.groups] == [g.rows for g in after.groups]
