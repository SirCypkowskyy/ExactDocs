"""Steps for the Grounded Docs run (packages/exactdocs/evals): ``just grounded-bench`` in-process.

Grounded Docs is ``grounded_docs_stand_in``: its real ``search_docs`` responses on the tiny corpus,
recorded, replayed; the embedding model is a stand-in served by the run's real endpoint. The
corpus is the retrieval benchmark's (its step makes it).
"""

from behave import given, then, when
from behave.runner import Context

from grounded_docs_stand_in import ReplayingGroundedDocs, stand_in_embedding
from retrieval_eval.grounded_docs import (
    INTEGRITY,
    TEXT_BASELINE,
    TOP_K,
    VERSION,
    GroundedDocsReport,
    markdown,
)
from retrieval_eval.grounded_docs_cli import main
from retrieval_eval.retrieval_bench import CUT_BUDGETS, TOKEN_BUDGETS

_SHOWN = ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "wrong_version_rate")
_ARTICLE = "docs/guide.md"


@given("a stand-in for Grounded Docs that replays its recorded responses")
def step_stand_in(context: Context) -> None:
    context.grounded = ReplayingGroundedDocs()


@given(
    "Grounded Docs at a pinned release has indexed every golden-corpus version from the same "
    "checkouts ExactDocs imports"
)
def step_pinned(context: Context) -> None:
    context.grounded_args = ["--configs", "full-text,bge-small-en-v1.5"]


@given("Grounded Docs leaves out an article a case expects")
def step_left_out(context: Context) -> None:
    context.grounded = ReplayingGroundedDocs(leave_out=frozenset({_ARTICLE}))
    context.grounded_args = ["--configs", "full-text"]


@when("each golden-set question is sent to its search for that library and version")
def step_run(context: Context) -> None:
    tmp = context.bench_dir
    context.exit_code = main(
        [
            "--corpus", str(tmp / "corpus.yaml"), "--cases", str(tmp / "cases"),
            "--cache-dir", str(tmp / "cache"), "--home", str(tmp / "home"),
            "--out", str(tmp / "out"), "--recorded", str(tmp / "none.json"),
            *context.grounded_args,
        ],
        tool=lambda _home, _offline: context.grounded,
        embedder=stand_in_embedding,
    )  # fmt: skip
    path = tmp / "out" / "grounded-docs.json"
    context.report = GroundedDocsReport.model_validate_json(path.read_text("utf-8"))


@then("the results are scored with the text scorer")
def step_scored(context: Context) -> None:
    assert context.exit_code == 0
    indexed = {(library, version) for library, version, _ in context.grounded.indexed}
    assert indexed == {("demo", "v1")}
    for run in context.report.runs:
        assert run.indexing[0].offered == run.indexing[0].indexed == 1
        answerable = next(r for r in run.rows if r.row.answerable)
        assert answerable.row.rank == 1  # the recorded result holds the Install section
        assert answerable.results <= TOP_K
    assert context.report.scorer["threshold"] > 0


@then(
    "the report lists Grounded Docs next to ExactDocs' configurations with the same metrics and "
    "intervals"
)
def step_side_by_side(context: Context) -> None:
    report = context.report
    assert report.baseline.name == TEXT_BASELINE
    base = report.baseline.result.metrics.metrics
    for run in report.runs:
        mine = run.result.metrics.metrics
        assert set(base.intervals) == set(mine.intervals)
        assert all(name in mine.intervals for name in _SHOWN)
        assert {v.against for v in run.versus} == {TEXT_BASELINE}
        assert run.context_tokens_interval is not None
    summary = markdown(report)
    assert f"| {TEXT_BASELINE} | text |" in summary
    assert "| Grounded Docs full-text | text |" in summary
    assert "| Grounded Docs bge-small-en-v1.5 | text |" in summary
    assert "### Paired tests against ExactDocs" in summary


@then("the report records Grounded Docs' version, its settings and the date")
def step_recorded(context: Context) -> None:
    report = context.report
    assert (report.tool["version"], report.tool["integrity"]) == (VERSION, INTEGRITY)
    assert report.date
    full_text, vector = report.runs
    assert full_text.settings["app"]["embeddingModel"] == "text-embedding-3-small"
    assert vector.settings["app"]["embeddingModel"] == "BAAI/bge-small-en-v1.5"
    assert vector.embedding is not None
    assert vector.embedding.indexing.texts == 1


@then(
    "the report gives recall within the first 1,000, 2,000 and 4,000 tokens of the text "
    "returned, for Grounded Docs and for ExactDocs"
)
def step_budgets(context: Context) -> None:
    assert context.exit_code == 0
    report = context.report
    for m in (
        report.baseline.result.metrics.metrics,
        *(r.result.metrics.metrics for r in report.runs),
    ):
        for name in TOKEN_BUDGETS:
            assert getattr(m, name) is not None
            assert name in m.intervals
        assert m.context_tokens_per_question is not None
    summary = markdown(report)
    assert "### Within a token budget" in summary
    assert "| within 1,000, whole results | within 2,000, whole results |" in summary


@then("each budget is read whole and cut at the budget, with a paired test against ExactDocs")
def step_budget_tests(context: Context) -> None:
    for run in context.report.runs:
        m = run.result.metrics.metrics
        for whole, cut in zip(TOKEN_BUDGETS, CUT_BUDGETS, strict=True):
            assert getattr(m, cut) is not None
            assert getattr(m, cut) >= getattr(m, whole)  # a cut text holds every whole result
        (versus,) = run.versus
        assert {*TOKEN_BUDGETS, *CUT_BUDGETS} <= set(versus.tests)
    assert "### Paired tests within a token budget" in markdown(context.report)


@then("the report names the article and the case")
def step_named(context: Context) -> None:
    (run,) = context.report.runs
    assert run.indexing[0].not_indexed == [_ARTICLE]
    assert run.cases_not_indexed == ["demo v1: How do I install the demo package?"]
    assert f"`{_ARTICLE}`" in markdown(context.report)
    assert context.exit_code == 1  # nothing of the version was indexed
