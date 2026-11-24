"""The retrieval benchmark (#347): its metrics, breakdowns, recommendation and check.

The metrics are pure functions of a case and what a configuration returned for it; the runs at
the bottom import a tiny local corpus (the stand-in run is marked ``eval``).
"""

import json
import math
from pathlib import Path
from typing import Literal

import pytest
from pydantic_evals import Case

from exactdocs.retrieval.models import RerankWith
from retrieval_bench_stand_ins import HOSTED, stand_in_container, tiny_corpus
from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.golden import fetch, load_corpus, load_golden
from retrieval_eval.ingestion_cli import CONFIGURATIONS
from retrieval_eval.retrieval_bench import (
    BenchMetrics,
    Budget,
    ConfigResult,
    RetrievalBenchReport,
    Row,
    against_defaults,
    check,
    markdown,
    metrics_of,
    ndcg_at,
    paired_tests,
    recommend,
    row_of,
    run_problems,
)
from retrieval_eval.retrieval_bench_cli import HOSTED as HOSTED_EMBEDDING
from retrieval_eval.retrieval_bench_cli import bench, main, matrix, picked
from retrieval_eval.stats import StatsMethod

# ---------------------------------------------------------------- nDCG@10


def _hit(article: str, *path: str, version: str = "v1") -> Hit:
    return Hit(version=version, article=article, heading_path=list(path))


A, B, C = _hit("a.md", "A"), _hit("b.md", "B"), _hit("c.md", "C")


@pytest.mark.parametrize(
    ("expected", "hits", "score"),
    [
        ([A], [A], 1.0),
        ([A], [B, A], 1 / math.log2(3)),
        ([A, B], [A, C, B], (1 + 1 / 2) / (1 + 1 / math.log2(3))),
        ([A, B], [B, A], 1.0),  # the order of the expected sections does not matter
        ([A], [A, A], 1.0),  # a section found twice counts once
        ([A], [C], 0.0),
        ([A], [], 0.0),
        ([A], [C] * 10 + [A], 0.0),  # rank 11 is past the cut-off
    ],
    ids=["first", "second", "two of two", "swapped", "twice", "missing", "empty", "rank 11"],
)
def test_ndcg_is_binary_over_the_expected_sections(
    expected: list[Hit], hits: list[Hit], score: float
) -> None:
    assert ndcg_at(expected, hits) == pytest.approx(score)


def test_ndcg_uses_the_match_rule_given() -> None:
    finer = _hit("a.md", "A", "Deeper")

    assert ndcg_at([A], [finer]) == 0
    assert ndcg_at([A], [finer], matches=lambda e, h: h.article == e.article) == 1


# ---------------------------------------------------------------- rows and metrics


def _case(
    kind: str = "how-to", *, project: str = "p", expected: list[Hit] | None = None
) -> Case[Question, Answer, CaseInfo]:
    hits = [A] if expected is None else expected
    return Case(
        name=f"{project} {kind} {len(hits)}",
        inputs=Question(query="q", version="v1", project=project),
        metadata=CaseInfo.model_validate({"kind": kind}),
        expected_output=Answer(hits=hits),
    )


def test_a_row_keeps_the_rank_the_version_and_whether_anything_came_back() -> None:
    answer = Answer(hits=[B, A, _hit("x.md", "X", version="v0")], search_ms=12.5, tokens=7, usd=0.1)

    row = row_of(_case(), answer)

    assert (row.kind, row.project, row.answerable, row.rank) == ("how-to", "p", True, 2)
    assert (row.wrong_version, row.empty, row.search_ms, row.tokens, row.usd) == (
        True,
        False,
        12.5,
        7,
        0.1,
    )
    assert row.ndcg == pytest.approx(1 / math.log2(3))
    unanswerable = row_of(_case("unanswerable", expected=[]), Answer(hits=[]))
    assert (unanswerable.answerable, unanswerable.empty, unanswerable.rank) == (False, True, None)


def test_a_cross_page_case_scores_the_share_of_its_sections_found() -> None:
    case = _case("cross-page", expected=[A, B])
    rows = [
        row_of(case, Answer(hits=[A, C, C, C, C, B])),  # A at 1, B at 6
        row_of(case, Answer(hits=[C, B])),  # only B, at 2
    ]

    assert [r.section_ranks for r in rows] == [(1, 6), (2,)]
    m = metrics_of(rows)
    # recall@k follows the first expected section only (the suite's rule)
    assert (m.recall_at_5, m.recall_at_10) == (0.5, 0.5)
    # section recall: the share of the two sections found, averaged over the cases
    assert m.section_recall_at_5 == pytest.approx((1 / 2 + 1 / 2) / 2)
    assert m.section_recall_at_10 == pytest.approx((2 / 2 + 1 / 2) / 2)


def _row(
    *,
    case: str = "",
    rank: int | None = 1,
    kind: str = "how-to",
    project: str = "p",
    answerable: bool = True,
    empty: bool = False,
    wrong: bool = False,
    ms: float = 10.0,
    usd: float = 0.0,
) -> Row:
    return Row(
        case=case,
        kind=kind,
        project=project,
        answerable=answerable,
        rank=rank if answerable else None,
        ndcg=1 / math.log2(rank + 1) if answerable and rank and rank <= 10 else 0.0,
        sections=1 if answerable else 0,
        section_ranks=(rank,) if answerable and rank and rank <= 10 else (),
        wrong_version=wrong,
        empty=empty,
        search_ms=ms,
        tokens=3,
        usd=usd,
    )


def test_metrics_score_ranks_over_answerable_cases_and_the_version_over_all() -> None:
    rows = [
        _row(rank=1, ms=10),
        _row(rank=4, ms=20),
        _row(rank=None, empty=True, ms=30),
        _row(answerable=False, empty=True, ms=40),
        _row(answerable=False, wrong=True, ms=50, usd=0.5),
    ]

    m = metrics_of(rows)

    assert (m.questions, m.answerable, m.unanswerable) == (5, 3, 2)
    assert (m.recall_at_1, m.recall_at_5, m.recall_at_10) == (0.3333, 0.6667, 0.6667)
    assert m.mrr == round((1 + 1 / 4) / 3, 4)
    assert m.ndcg_at_10 == round((1 + 1 / math.log2(5)) / 3, 4)
    assert m.wrong_version_rate == pytest.approx(0.2)
    # unanswerable: one returned nothing (signalled no answer), one returned another version
    assert (m.unanswerable_clean_rate, m.no_answer_rate) == (0.5, 0.5)
    # an answerable case that came back empty
    assert m.answerable_empty_rate == pytest.approx(0.3333)
    # one expected section each: section recall is recall
    assert (m.section_recall_at_5, m.section_recall_at_10) == (m.recall_at_5, m.recall_at_10)
    assert (m.latency_p50_ms, m.latency_p95_ms) == (30, 50)
    assert (m.tokens_per_question, m.usd_per_question) == (3, 0.1)


def test_metrics_without_unanswerable_cases_leave_their_rates_out() -> None:
    m = metrics_of([_row()])

    assert (m.unanswerable, m.unanswerable_clean_rate, m.no_answer_rate) == (0, None, None)
    assert metrics_of([]).questions == 0


# ---------------------------------------------------------------- results, recommendation


def _result(
    name: str,
    budget: Budget,
    *,
    recall: float = 0.5,
    usd: float = 0.0,
    chunking: str = "default",
    wrong: float = 0.0,
    status: Literal["ran", "unavailable", "skipped"] = "ran",
    rows: list[Row] | None = None,
) -> ConfigResult:
    hits = round(recall * 100)  # the same 100 cases, the first ones found
    rows = rows or [_row(case=f"c{i:03}", rank=1 if i < hits else None) for i in range(100)]
    rows = [*rows, *([_row(case="w", answerable=False, wrong=True)] if wrong else [])]
    metrics = metrics_of(rows) if status == "ran" else None
    if metrics is not None:
        metrics = metrics.model_copy(update={"usd_per_question": usd})
    return ConfigResult(
        configuration=name,
        chunking=chunking,
        budget=budget,
        mode="bm25",
        status=status,
        reason=None if status == "ran" else "needs a real-providers run",
        metrics=metrics,
        wrong_version_cases=["x: v0 a.md"] if wrong else [],
        rows=rows if status == "ran" else [],
    )


def test_breakdowns_are_by_question_kind_and_by_project() -> None:
    rows = [
        _row(kind="how-to", project="zod", rank=1),
        _row(kind="how-to", project="zod", rank=None),
        _row(kind="conceptual", project="electron", rank=1),
    ]
    result = _result("bm25", Budget.NONE, rows=rows).with_breakdowns(rows)

    assert result.by_kind["how-to"].recall_at_5 == pytest.approx(0.5)
    assert result.by_kind["conceptual"].recall_at_5 == 1
    assert sorted(result.by_project) == ["electron", "zod"]
    assert result.by_project["zod"].questions == 2


def test_each_budget_gets_the_best_configuration_that_pays_for_itself() -> None:
    results = [
        _result("bm25", Budget.NONE, recall=0.6),
        _result("bm25", Budget.NONE, recall=0.62, chunking="h2"),
        _result("hybrid:small", Budget.LOCAL, recall=0.7),
        _result("hybrid:big", Budget.LOCAL, recall=0.9, wrong=0.01),  # never: a wrong version
        _result("hybrid:hosted", Budget.HOSTED, status="skipped"),
    ]

    none, local, hosted = recommend(results)

    assert (none.budget, none.configuration, none.chunking) == (Budget.NONE, "bm25", "h2")
    assert none.usd_per_1000_questions == 0
    assert (local.configuration, local.chunking) == ("hybrid:small", "default")
    assert any("+8.0 points" in reason for reason in local.reasons), local.reasons
    assert (hosted.configuration, hosted.usd_per_1000_questions) == (None, None)
    assert hosted.reasons == ["not measured yet: needs a real-providers run"]


def test_a_dearer_configuration_under_the_margin_keeps_the_cheaper_one() -> None:
    results = [
        _result("bm25", Budget.NONE, recall=0.6),
        _result("hybrid:small", Budget.LOCAL, recall=0.63),
        _result("hybrid:hosted", Budget.HOSTED, recall=0.64, usd=0.0002),
    ]

    none, local, hosted = recommend(results)

    assert local.configuration == "bm25"
    why = " ".join(local.reasons)
    assert "`hybrid:small`" in why
    assert "+3.0 points" in why
    assert "under the 5-point margin" in why
    assert (hosted.configuration, hosted.usd_per_1000_questions) == ("bm25", 0)
    assert none.configuration == "bm25"


# ---------------------------------------------------------------- intervals and paired tests (#489)


def test_every_rate_and_mean_comes_with_an_interval() -> None:
    rows = [_row(case=f"c{i}", rank=1 + i % 12, kind=("a", "b")[i % 2]) for i in range(60)]
    rows += [_row(case=f"u{i}", answerable=False, empty=i % 2 == 0) for i in range(10)]

    result = _result("bm25", Budget.NONE, rows=rows).with_breakdowns(rows)

    m = result.metrics
    assert m is not None
    for name in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
        spread = m.intervals[name]
        assert spread.low < getattr(m, name) < spread.high, name
    # every rate and mean: each float metric but the latency percentiles
    fields = BenchMetrics.model_fields.items()
    means = {name for name, f in fields if f.annotation in {float, float | None}}
    assert set(m.intervals) == means - {"latency_p50_ms", "latency_p95_ms"}
    assert {"recall_at_5", "mrr", "ndcg_at_10", "no_answer_rate"} <= set(m.intervals)
    assert (m.intervals["wrong_version_rate"].low, m.intervals["wrong_version_rate"].high) == (0, 0)
    # a kind's interval, on half the cases, is wider than the whole set's
    whole, kind = m.intervals["recall_at_5"], result.by_kind["a"].intervals["recall_at_5"]
    assert kind.high - kind.low > whole.high - whole.low
    assert [r.case for r in result.rows] == sorted(r.case for r in rows)


def test_the_same_cases_in_any_order_give_the_same_intervals() -> None:
    rows = [_row(case=f"c{i:02}", rank=1 + i % 7) for i in range(40)]

    assert metrics_of(rows) == metrics_of(list(reversed(rows)))


def _named(hits: int, cases: int = 100) -> list[Row]:
    return [_row(case=f"c{i:03}", rank=1 if i < hits else None) for i in range(cases)]


def test_a_dearer_default_needs_a_significant_gain() -> None:
    # +10 points of recall@5, over the margin, but from 2 cases of 20: McNemar mid-p 0.25
    cheap = _result("bm25", Budget.NONE, rows=_named(10, 20))
    dear = _result("hybrid:small", Budget.LOCAL, rows=_named(12, 20))

    test = paired_tests(cheap, dear)["recall_at_5"]
    assert (test.gained, test.lost, test.significant) == (2, 0, False)

    _, local, _ = recommend([cheap, dear])

    assert local.configuration == "bm25"
    why = " ".join(local.reasons)
    assert "+10.0 points" in why
    assert "not significant (McNemar mid-p 0.25" in why
    assert local.test == test


def test_a_significant_gain_over_the_margin_changes_the_default() -> None:
    cheap = _result("bm25", Budget.NONE, rows=_named(60))
    dear = _result("hybrid:small", Budget.LOCAL, rows=_named(70))

    _, local, _ = recommend([cheap, dear])

    assert local.configuration == "hybrid:small"
    assert local.test is not None
    assert local.test.significant
    assert "significant, McNemar mid-p" in local.reasons[-1]


def test_without_per_case_outcomes_a_dearer_default_is_not_taken() -> None:
    cheap = _result("bm25", Budget.NONE, rows=_named(60))
    dear = _result("hybrid:small", Budget.LOCAL, rows=_named(70)).model_copy(update={"rows": []})

    _, local, _ = recommend([cheap, dear])

    assert local.configuration == "bm25"
    assert "not tested for significance" in local.reasons[-1]
    assert local.test is None


def test_identical_results_are_not_significantly_different() -> None:
    a = _result("bm25", Budget.NONE, rows=_named(60))
    b = _result("bm25", Budget.NONE, rows=_named(60), chunking="h6")

    tests = paired_tests(a, b)

    assert set(tests) == {"recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"}
    assert all(t.p_value == 1 and not t.significant for t in tests.values())
    assert {tests["mrr"].test, tests["recall_at_5"].test} == {"permutation", "mcnemar-mid-p"}


def test_each_result_is_tested_against_its_budgets_default() -> None:
    results = [
        _result("bm25", Budget.NONE, rows=_named(60)),
        _result("bm25", Budget.NONE, rows=_named(58), chunking="h6"),
        _result("hybrid:small", Budget.LOCAL, rows=_named(62)),
        _result("hybrid:big", Budget.LOCAL, recall=0.7).model_copy(update={"rows": []}),
    ]
    picks = recommend(results)

    tested = {
        (r.configuration, r.chunking): r.versus_default for r in against_defaults(results, picks)
    }

    assert tested["bm25", "default"] is None  # the default itself
    h6 = tested["bm25", "h6"]
    assert h6 is not None
    assert (h6.configuration, h6.chunking) == ("bm25", "default")
    assert h6.tests["recall_at_5"].lost == 2
    small = tested["hybrid:small", "default"]  # the local default is still bm25
    assert small is not None
    assert small.configuration == "bm25"
    assert tested["hybrid:big", "default"] is None  # no rows to pair


def test_the_summary_shows_the_intervals_and_the_paired_tests() -> None:
    results = [
        _result("bm25", Budget.NONE, rows=_named(60)),
        _result("bm25", Budget.NONE, rows=_named(30), chunking="h2"),
        _result("hybrid:old", Budget.LOCAL, recall=0.5).model_copy(update={"rows": []}),
    ]
    picks = recommend(results)
    report = _report(*against_defaults(results, picks)).model_copy(
        update={"statistics": StatsMethod(), "recommendations": picks}
    )

    text = markdown(report)

    assert "| 60.0% [" in text
    assert "10,000 resamples, seed 489" in text
    assert "## Against the budget's default" in text
    assert "| `bm25` | `h2` | none | `bm25` at `default` | **-30.0** [" in text
    assert "p < 0.001" in text
    assert "Not tested, recorded without per-case outcomes: `hybrid:old` at `default`." in text
    assert RetrievalBenchReport.model_validate_json(report.model_dump_json()) == report


def _report(*results: ConfigResult, golden: str = "sha256:a") -> RetrievalBenchReport:
    return RetrievalBenchReport(
        golden=golden,
        cases=100,
        projects=["p"],
        corpus=[{"project": "p", "version": "v1", "commit": "c1"}],
        environment={"exactdocs_commit": "abc"},
        chunkings=[],
        results=list(results),
        recommendations=recommend(list(results)),
    )


def test_a_run_fails_on_a_wrong_version_and_the_check_on_a_drop() -> None:
    clean = _report(_result("bm25", Budget.NONE, recall=0.6))
    worse = _report(_result("bm25", Budget.NONE, recall=0.55, wrong=0.01))

    assert run_problems(clean) == []
    assert run_problems(worse) == ["bm25 @ default: 1 question(s) got a result of another version"]
    assert check(clean, clean) == []
    problems = check(worse, clean)
    assert any("recall@5 dropped 5.0 points" in p for p in problems), problems
    assert check(clean, _report(golden="sha256:b")) != []


def test_the_summary_names_the_defaults_and_every_configuration() -> None:
    rows = [_row(kind="how-to"), _row(answerable=False, kind="unanswerable", empty=True)]
    report = _report(
        _result("bm25", Budget.NONE, rows=rows).with_breakdowns(rows),
        _result("hybrid:hosted", Budget.HOSTED, status="skipped"),
    )

    text = markdown(report)

    assert "## Recommended defaults" in text
    assert "| none | `bm25` | `default` |" in text
    assert "| hosted | not measured yet: needs a real-providers run |" in text
    assert "| `bm25` | `default` | none | ran |" in text
    assert "## By question kind" in text
    assert "`hybrid:hosted`: skipped (needs a real-providers run)" in text
    assert json.loads(report.model_dump_json())["schema_version"] == 1


# ---------------------------------------------------------------- the matrix


def test_the_matrix_covers_every_mode_reranker_and_budget() -> None:
    names = {c.name: c for c in matrix(["BAAI/bge-small-en-v1.5", "BAAI/bge-base-en-v1.5"])}

    assert {"bm25", "bm25+ce", "bm25+judge"} <= set(names)
    for embedding in ("bge-small-en-v1.5", "bge-base-en-v1.5", "hosted"):
        for suffix in ("", "+ce", "+judge"):
            assert f"hybrid:{embedding}{suffix}" in names
    assert {"hyde:hosted", "agentic:hosted"} <= set(names)
    budgets = {name: config.budget for name, config in names.items()}
    assert budgets["bm25"] is Budget.NONE
    assert budgets["hybrid:bge-small-en-v1.5+ce"] is Budget.LOCAL
    assert budgets["hybrid:bge-small-en-v1.5+judge"] is Budget.HOSTED  # the judge is an LLM
    assert names["hybrid:hosted+ce"].embedding == HOSTED_EMBEDDING


# ---------------------------------------------------------------- runs on a tiny corpus


def test_the_command_runs_the_model_free_part_and_checks_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = tiny_corpus(tmp_path)
    out = tmp_path / "out"

    assert main([*args, "--chunkings", "default,h2", "--out", str(out)]) == 0

    report = RetrievalBenchReport.model_validate_json((out / "retrieval.json").read_text("utf-8"))
    ran = [r for r in report.results if r.status == "ran"]
    assert [(r.configuration, r.chunking) for r in ran] == [("bm25", "default"), ("bm25", "h2")]
    bm25 = ran[0]
    assert bm25.metrics is not None
    assert (bm25.metrics.recall_at_5, bm25.metrics.wrong_version_rate) == (1, 0)
    assert bm25.metrics.no_answer_rate == 1  # BM25 matched no term of the unanswerable question
    assert sorted(bm25.by_kind) == ["how-to", "unanswerable"]
    assert list(bm25.by_project) == ["demo"]
    # every case's outcome is kept, so the intervals and tests can be recomputed (#489)
    assert sorted(row.answerable for row in bm25.rows) == [False, True]
    assert "recall_at_5" in bm25.metrics.intervals
    assert report.statistics is not None
    assert report.statistics.seed == 489
    # one chunking is the default (the faster one, as recall ties): the other is tested against it
    (other,) = [r for r in ran if r.versus_default is not None]
    versus = other.versus_default
    assert versus is not None
    assert (versus.configuration, versus.chunking) == (
        report.recommendations[0].configuration,
        report.recommendations[0].chunking,
    )
    assert versus.tests["recall_at_5"].p_value == 1  # the same answer at both chunkings
    # a local model that was not pulled is reported, with how to pull it
    local = next(r for r in report.results if r.configuration == "bm25+ce")
    assert local.status == "unavailable"
    assert local.reason is not None
    assert "exactdocs models pull" in local.reason
    hosted = next(r for r in report.results if r.configuration == "agentic:hosted")
    assert hosted.status == "skipped"
    (pinned,) = load_corpus(tmp_path / "corpus.yaml").projects[0].versions
    assert report.corpus == [{"project": "demo", "version": "v1", "commit": pinned.commit}]
    assert report.environment["exactdocs_commit"]
    none, _, hosted_pick = report.recommendations
    assert (none.configuration, hosted_pick.configuration) == ("bm25", None)
    assert (out / "retrieval.md").read_text("utf-8") in capsys.readouterr().out

    assert main([*args, "--chunkings", "default,h2", "--out", str(out), "--check",
                 str(out / "retrieval.json")]) == 0  # fmt: skip


# ---------------------------------------------------------------- stand-ins (plumbing only)


@pytest.mark.eval
async def test_the_hosted_part_runs_end_to_end_on_stand_ins(tmp_path: Path) -> None:
    tiny_corpus(tmp_path)
    corpus = load_corpus(tmp_path / "corpus.yaml")
    repos = {p.id: fetch(p, tmp_path / "cache", offline=False) for p in corpus.projects}
    # no cross-encoder stand-in exists: the local runs measure it for real
    configs = [c for c in matrix([]) if c.rerank is not RerankWith.CROSS_ENCODER]

    report = await bench(
        corpus.projects,
        repos,
        load_golden(tmp_path / "cases"),
        [CONFIGURATIONS[0]],
        configs,
        hosted=HOSTED,
        models_dir=tmp_path / "models",
        local_reranker="unused",
        allow_providers=True,
        build=stand_in_container,
    )

    assert run_problems(report) == []
    results = {r.configuration: r for r in report.results}
    assert {n for n, r in results.items() if r.status != "ran"} == set(), [
        (n, r.reason) for n, r in results.items() if r.status != "ran"
    ]
    for name in ("hybrid:hosted+judge", "bm25+judge"):
        assert results[name].reranked > 0, name
        assert results[name].rerank_fallbacks == 0, name
    for name in ("hybrid:hosted+judge", "hyde:hosted", "agentic:hosted"):
        metrics = results[name].metrics
        assert metrics is not None
        assert metrics.usd_per_question > 0, name  # priced stand-in: the ledger reached the row
    assert results["hybrid:hosted"].index is not None
    assert results["hybrid:hosted"].index.tokens > 0
    assert any(m.role == "llm" for m in results["agentic:hosted"].models)
    assert results["agentic:hosted"].left_version_cases == []


@pytest.mark.parametrize(
    ("patterns", "config", "chunking", "expected"),
    [
        (["*"], "bm25", "h2", True),
        (["bm25"], "bm25+ce", "default", False),
        (["hybrid:*"], "hybrid:bge-small-en-v1.5", "h2", True),
        (["*+ce@default"], "bm25+ce", "default", True),
        (["*+ce@default"], "bm25+ce", "h2", False),
        (["bm25", "*+ce@h2"], "bm25", "merge-400", True),
    ],
)
def test_a_pattern_picks_configurations_and_maybe_chunkings(
    patterns: list[str], config: str, chunking: str, expected: bool
) -> None:
    assert picked(patterns, config, chunking) is expected
