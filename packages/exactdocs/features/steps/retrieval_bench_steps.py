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
from retrieval_eval.retrieval_bench import Budget, markdown
from retrieval_eval.retrieval_bench_cli import bench, matrix


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
            CONFIGURATIONS[:2],
            matrix(["BAAI/bge-small-en-v1.5"]),
            hosted=context.hosted,
            models_dir=tmp / "models",
            allow_providers=True,
            build=stand_in_container,
        )
    )
    context.ran = [r for r in context.report.results if r.metrics is not None]


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
