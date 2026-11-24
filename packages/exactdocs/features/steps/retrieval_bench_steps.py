"""Steps for the retrieval benchmark (packages/exactdocs/evals): run in-process on a tiny corpus.

The hosted models are stand-ins (``retrieval_bench_stand_ins``), so the hosted part runs as it
would by hand with ``--allow-providers``; no local model is pulled here, so the local
configurations are reported as unavailable.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from retrieval_bench_stand_ins import HOSTED, stand_in_container, tiny_corpus
from retrieval_eval.golden import fetch, load_corpus, load_golden
from retrieval_eval.ingestion_cli import CONFIGURATIONS
from retrieval_eval.retrieval_bench import (
    Budget,
    ConfigResult,
    Row,
    markdown,
    paired_tests,
    recommend,
)
from retrieval_eval.retrieval_bench_cli import bench, matrix
from retrieval_eval.stats import ALPHA
from retrieval_eval.suite import DEFAULT_MARGIN_POINTS

_SHOWN = ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")


@given("a golden corpus with an answerable and an unanswerable question")
def step_corpus(context: Context) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="exactdocs-retrieval-bench-"))
    context.add_cleanup(shutil.rmtree, tmp, ignore_errors=True)
    tiny_corpus(tmp)
    context.bench_dir = tmp


@given("stand-ins for the hosted models")
def step_stand_ins(context: Context) -> None:
    context.hosted = HOSTED


@when("the retrieval benchmark runs every configuration at two chunking configurations")
def step_run(context: Context) -> None:
    tmp = context.bench_dir
    corpus = load_corpus(tmp / "corpus.yaml")
    repos = {p.id: fetch(p, tmp / "cache", offline=False) for p in corpus.projects}
    context.report = asyncio.run(
        bench(
            corpus.projects,
            repos,
            load_golden(tmp / "cases"),
            [c for c in CONFIGURATIONS if c.name in {"default", "h2"}],
            matrix(["BAAI/bge-small-en-v1.5"]),
            hosted=context.hosted,
            models_dir=tmp / "models",
            allow_providers=True,
            build=stand_in_container,
        )
    )
    context.ran = [r for r in context.report.results if r.metrics is not None]


# ---------------------------------------------------------------- held sections (#503)

# The guide's and "Configure"'s texts are long enough to be chunks of their own; "Install" is
# under 400 characters, so merge-400 merges the sections after it into its chunk, which keeps
# the heading path Guide > Install and holds "Upgrade".
SIBLINGS = (
    "# Guide\n\n" + "The demo package reads its settings from one file. " * 10 + "\n\n"
    "## Install\n\nRun pip to install the demo package.\n\n"
    "## Upgrade\n\nPass --upgrade to pip to move to the latest release.\n\n"
    "## Configure\n\n" + "Set the timeout option in the settings file. " * 10 + "\n"
)


@given(
    "a golden case whose expected section a chunking merges into the chunk of the section before it"
)
def step_held_corpus(context: Context) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="exactdocs-retrieval-bench-"))
    context.add_cleanup(shutil.rmtree, tmp, ignore_errors=True)
    upgrade = {"version": "v1", "article": "docs/guide.md", "heading_path": ["Guide", "Upgrade"]}
    case = {
        "name": "demo v1: How do I upgrade the demo package?",
        "inputs": {"query": "upgrade latest release", "version": "v1", "project": "demo"},
        "metadata": {"kind": "how-to"},
        "expected_output": {"hits": [upgrade], "reference": "--upgrade.", "facts": ["upgrade"]},
    }
    tiny_corpus(tmp, guide=SIBLINGS, cases=[case])
    context.bench_dir = tmp
    context.chunking = next(c for c in CONFIGURATIONS if c.name == "merge-400")


@when("the retrieval benchmark runs BM25 at that chunking")
def step_run_bm25(context: Context) -> None:
    tmp = context.bench_dir
    corpus = load_corpus(tmp / "corpus.yaml")
    repos = {p.id: fetch(p, tmp / "cache", offline=False) for p in corpus.projects}
    report = asyncio.run(
        bench(
            corpus.projects,
            repos,
            load_golden(tmp / "cases"),
            [context.chunking],
            matrix([]),
            hosted=context.hosted,
            models_dir=tmp / "models",
            only=["bm25"],
        )
    )
    (context.result,) = report.results


@then("the case counts as a hit at the rank of that chunk")
def step_held_hit(context: Context) -> None:
    (row,) = context.result.rows
    assert row.rank == 1, row  # the chunk Guide > Install, which holds Upgrade
    assert context.result.metrics.recall_at_1 == 1
    assert row.section_ranks == (1,)


@then(
    "each configuration that ran reports recall@1/5/10, MRR, nDCG@10, wrong-version rate, "
    "p50/p95 latency and tokens and USD per question"
)
def step_metrics(context: Context) -> None:
    ran = {(r.configuration, r.chunking) for r in context.ran}
    for name in ("bm25", "bm25+judge", "hybrid:hosted", "hyde:hosted", "agentic:hosted"):
        assert {(name, "default"), (name, "h2")} <= ran, name
    for result in context.ran:
        m = result.metrics
        assert m.wrong_version_rate == 0, result.configuration
        assert 0 <= m.recall_at_1 <= m.recall_at_5 <= m.recall_at_10 <= 1
        assert 0 <= m.mrr <= 1
        assert 0 <= m.ndcg_at_10 <= 1
        assert m.latency_p50_ms <= m.latency_p95_ms
        assert m.tokens_per_question >= 0
        assert m.usd_per_question >= 0
    hyde = next(r for r in context.ran if r.configuration == "hyde:hosted")
    assert hyde.metrics.usd_per_question > 0  # the priced stand-in reached the ledger


@then("each metric is broken down by question kind and by project")
def step_breakdowns(context: Context) -> None:
    for result in context.ran:
        assert sorted(result.by_kind) == ["how-to", "unanswerable"], result.by_kind
        assert list(result.by_project) == ["demo"]


@then(
    "each unanswerable question is scored on returning nothing of another version "
    "and on signalling no answer"
)
def step_unanswerable(context: Context) -> None:
    for result in context.ran:
        m = result.metrics
        assert m.unanswerable == 1
        assert m.unanswerable_clean_rate == 1, result.configuration
        assert m.no_answer_rate in {0, 1}
    bm25 = next(r for r in context.ran if r.configuration == "bm25")
    assert bm25.metrics.no_answer_rate == 1  # no term of the question is in the docs


@then("each result records its models, its settings and the corpus commits")
def step_records(context: Context) -> None:
    report = context.report
    assert report.corpus[0]["commit"]
    assert report.environment["exactdocs_commit"]
    agentic = next(r for r in context.ran if r.configuration == "agentic:hosted")
    assert [m.role for m in agentic.models] == ["llm"]
    assert agentic.settings["llm"]["model"] == "offline:writer"
    local = next(r for r in report.results if r.configuration == "hybrid:bge-small-en-v1.5")
    assert local.status == "unavailable"
    assert "exactdocs models pull BAAI/bge-small-en-v1.5" in (local.reason or "")


@then(
    "the summary names the best configuration with no models, with local models only "
    "and with hosted models"
)
def step_summary(context: Context) -> None:
    picks = context.report.recommendations
    assert [p.budget for p in picks] == [Budget.NONE, Budget.LOCAL, Budget.HOSTED]
    assert picks[0].configuration == "bm25"
    assert picks[1].configuration is None  # no local model is pulled here
    assert picks[2].configuration is not None
    context.summary = markdown(context.report)
    assert "## Recommended defaults" in context.summary


@then("each with its cost per 1000 questions")
def step_cost(context: Context) -> None:
    for pick in context.report.recommendations:
        if pick.configuration is not None:
            assert pick.usd_per_1000_questions is not None
            assert f"${pick.usd_per_1000_questions:.4f}" in context.summary


# ---------------------------------------------------------------- intervals and significance (#489)


@given("a recorded retrieval run on the golden set")
def step_recorded(context: Context) -> None:
    step_run(context)


@when("the report is rendered")
def step_render(context: Context) -> None:
    context.summary = markdown(context.report)


@then("recall@k, MRR and nDCG@10 of each configuration show a 95% confidence interval")
def step_intervals(context: Context) -> None:
    assert f"{context.report.statistics.confidence:.0%}" == "95%"
    assert "the 95% interval" in context.summary
    lines = context.summary.splitlines()
    for result in context.ran:
        m = result.metrics
        for name in _SHOWN:
            spread = m.intervals[name]
            assert spread.low <= getattr(m, name) <= spread.high, (result.configuration, name)
        # its row in the table of every configuration (budget, then status)
        prefix = f"| `{result.configuration}` | `{result.chunking}` | {result.budget} | ran |"
        (line,) = [line for line in lines if line.startswith(prefix)]
        assert line.count(" [") >= len(_SHOWN), line


@then("the report records the seed and the number of resamples")
def step_seed(context: Context) -> None:
    method = context.report.statistics
    assert (method.seed, method.resamples) == (489, 10_000)
    assert "10,000 resamples, seed 489" in context.summary


def _rows(hits: int, cases: int) -> list[Row]:
    return [
        Row(
            case=f"case {i:02}",
            kind="how-to",
            project="demo",
            answerable=True,
            rank=1 if i < hits else None,
            ndcg=1.0 if i < hits else 0.0,
            sections=1,
            section_ranks=(1,) if i < hits else (),
            wrong_version=False,
            empty=False,
            search_ms=1.0,
            tokens=0,
            usd=0.0,
        )
        for i in range(cases)
    ]


def _result(name: str, budget: Budget, rows: list[Row]) -> ConfigResult:
    return ConfigResult(
        configuration=name, chunking="default", budget=budget, mode="bm25", status="ran"
    ).with_breakdowns(rows)


@given("configuration B beats the budget default A by more than the margin on recall@5")
def step_dearer(context: Context) -> None:
    # 20 cases: A finds 10, B the same 10 and 2 more, 10 points of recall@5 above A
    context.cheap = _result("A", Budget.NONE, _rows(10, 20))
    context.dear = _result("B", Budget.LOCAL, _rows(12, 20))
    gain = (context.dear.metrics.recall_at_5 - context.cheap.metrics.recall_at_5) * 100
    assert gain > DEFAULT_MARGIN_POINTS, gain


@given("the paired test of B against A on the same cases is not significant at 5%")
def step_not_significant(context: Context) -> None:
    test = paired_tests(context.cheap, context.dear)["recall_at_5"]
    assert test.p_value >= ALPHA, test
    assert not test.significant


@when("the defaults are chosen")
def step_choose(context: Context) -> None:
    context.picks = recommend([context.cheap, context.dear])


@then("A stays the default and the reason says the difference is not significant")
def step_stays(context: Context) -> None:
    local = next(p for p in context.picks if p.budget is Budget.LOCAL)
    assert local.configuration == "A", local
    assert "the difference is not significant" in " ".join(local.reasons), local.reasons
