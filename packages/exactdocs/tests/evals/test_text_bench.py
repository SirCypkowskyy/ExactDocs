"""Scoring text results (#491): rows, metrics, facts, tokens, the calibration and its command.

The scoring runs over ``text_corpus``'s guide at two versions; the command at the bottom imports
the retrieval benchmark's tiny corpus and runs BM25 over it, as ``just text-bench`` does.
"""

import math
from pathlib import Path

import pytest
from pydantic_evals import Case

from retrieval_bench_stand_ins import tiny_corpus
from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.golden_run import held_match
from retrieval_eval.ingestion import tokens
from retrieval_eval.retrieval_bench import metrics_of
from retrieval_eval.text_bench import (
    MIN_AGREEMENT,
    TextAnswer,
    TextResult,
    TextScorerReport,
    agreement,
    calibrate,
    fact_terms,
    facts_found,
    markdown,
    plain_text,
    problems,
    results_table,
    scorer_settings,
    text_metrics,
    text_row,
)
from retrieval_eval.text_bench_cli import main
from text_corpus import CONFIGURE_V1, CONFIGURE_V2, INSTALL, LIFESPAN, two_version_index

INDEX = two_version_index()
GUIDE = "docs/guide.md"
UNRELATED = "Kubernetes operators reconcile custom resources against the desired cluster state."


def _expected(version: str, *path: str) -> Hit:
    return Hit(version=version, article=GUIDE, heading_path=["Guide", *path])


def _case(
    version: str = "v2",
    expected: list[Hit] | None = None,
    facts: list[str] | None = None,
    *,
    kind: str = "how-to",
    name: str = "case",
) -> Case[Question, Answer, CaseInfo]:
    hits = [_expected(version, "Lifespan")] if expected is None else expected
    return Case(
        name=name,
        inputs=Question(query="q", version=version, project="demo"),
        metadata=CaseInfo.model_validate({"kind": kind if hits else "unanswerable"}),
        expected_output=Answer(
            hits=hits,
            reference="r",
            facts=(["the client closes every pooled connection"] if facts is None else facts)
            if hits
            else [],
        ),
    )


# ---------------------------------------------------------------- one case


def test_the_first_result_that_holds_the_section_is_the_hit() -> None:
    row = text_row(_case(), TextAnswer(texts=[UNRELATED, INSTALL, LIFESPAN, LIFESPAN]), INDEX)

    assert row.row.rank == 3
    assert row.row.section_ranks == (3,)
    assert row.row.ndcg == pytest.approx(0.5)  # 1 / log2(3 + 1)
    assert (row.row.answerable, row.row.empty, row.row.wrong_version) == (True, False, False)
    assert (row.results, row.neutral, row.unmatched) == (4, 1, 1)  # Install is in both versions


def test_a_result_only_in_another_version_makes_the_case_wrong_version() -> None:
    row = text_row(_case(), TextAnswer(texts=[LIFESPAN, CONFIGURE_V1]), INDEX)

    assert row.row.rank == 1
    assert row.row.wrong_version


def test_text_shared_by_both_versions_is_neutral_not_wrong() -> None:
    row = text_row(_case("v1", [_expected("v1", "Install")]), TextAnswer(texts=[INSTALL]), INDEX)

    assert (row.row.rank, row.neutral, row.row.wrong_version) == (1, 1, False)


def test_a_section_past_the_tenth_result_is_a_miss() -> None:
    row = text_row(_case(), TextAnswer(texts=[UNRELATED] * 10 + [LIFESPAN]), INDEX)

    assert row.row.rank is None
    assert row.tokens_to_hit is None


def test_context_tokens_count_every_result_and_the_hit_costs_those_up_to_it() -> None:
    texts = [CONFIGURE_V2, LIFESPAN, UNRELATED]

    row = text_row(_case(), TextAnswer(texts=texts), INDEX)

    assert row.context_tokens == sum(tokens(t) for t in texts)
    assert row.tokens_to_hit == tokens(CONFIGURE_V2) + tokens(LIFESPAN)


def test_an_unanswerable_case_with_nothing_back_signals_no_answer() -> None:
    row = text_row(_case(expected=[]), TextAnswer(texts=[]), INDEX)

    assert (row.row.answerable, row.row.empty, row.row.rank, row.facts) == (False, True, None, 0)


def test_a_cross_page_case_scores_every_section_it_finds() -> None:
    case = _case(expected=[_expected("v2", "Lifespan"), _expected("v2", "Configure")])

    row = text_row(case, TextAnswer(texts=[CONFIGURE_V2, UNRELATED, LIFESPAN]), INDEX)

    assert row.row.rank == 1  # recall counts a hit on any section the case lists (#501)
    assert row.row.section_ranks == (1, 3)


def test_an_alternative_section_is_a_hit_and_answers_its_part() -> None:
    either = [
        _expected("v2", "Lifespan"),
        _expected("v2", "Configure").model_copy(update={"alternative": True}),
    ]

    row = text_row(_case(expected=either), TextAnswer(texts=[UNRELATED, CONFIGURE_V2]), INDEX)

    assert (row.row.rank, row.row.sections, row.row.section_ranks) == (2, 1, (2,))
    assert row.row.ndcg == pytest.approx(1 / math.log2(3))
    assert row.tokens_to_hit == tokens(UNRELATED) + tokens(CONFIGURE_V2)


# ---------------------------------------------------------------- facts


def test_a_fact_is_found_when_most_of_its_content_words_are_in_the_text() -> None:
    facts = [
        "the client closes every pooled connection on exit",  # all its words, plural cut
        "it connects on entry",
        "the client retries forever",  # "retries", "forever" missing: under three quarters
    ]

    assert facts_found(facts, LIFESPAN) == 2
    assert fact_terms("The queries are cached") == frozenset({"query", "cached"})


def test_the_facts_found_go_into_the_row() -> None:
    case = _case(facts=["it connects on entry", "the deadline is counted in milliseconds"])

    assert text_row(case, TextAnswer(texts=[LIFESPAN]), INDEX).facts_found == 1
    assert text_row(case, TextAnswer(texts=[LIFESPAN, CONFIGURE_V2]), INDEX).facts_found == 2


# ---------------------------------------------------------------- metrics


def test_metrics_are_the_benchmarks_plus_what_only_text_tells() -> None:
    rows = [
        text_row(_case(name="a"), TextAnswer(texts=[LIFESPAN, INSTALL]), INDEX),
        text_row(_case(name="b"), TextAnswer(texts=[CONFIGURE_V1, UNRELATED]), INDEX),
        text_row(_case(expected=[], name="c"), TextAnswer(texts=[]), INDEX),
    ]

    m = text_metrics(rows)

    assert m.metrics == metrics_of([r.row for r in rows])
    assert (m.metrics.recall_at_1, m.metrics.wrong_version_rate) == (0.5, round(1 / 3, 4))
    assert m.metrics.no_answer_rate == 1
    assert m.version_neutral_share == pytest.approx(0.25)  # Install, of four results
    assert m.unmatched_share == pytest.approx(0.25)  # the unrelated text
    assert m.results_per_question == pytest.approx(4 / 3, abs=0.01)
    assert m.tokens_to_first_hit == tokens(LIFESPAN)
    assert m.facts_found_rate == pytest.approx(0.5)
    assert m.context_tokens_per_question > 0


def test_a_result_breaks_down_by_kind_and_project() -> None:
    rows = [
        text_row(_case(name="a"), TextAnswer(texts=[LIFESPAN]), INDEX),
        text_row(_case(expected=[], name="b"), TextAnswer(texts=[CONFIGURE_V1]), INDEX),
    ]

    result = TextResult.of("some tool", rows)

    assert sorted(result.by_kind) == ["how-to", "unanswerable"]
    assert list(result.by_project) == ["demo"]
    assert result.wrong_version_cases == ["b"]
    (header, _, line) = results_table([result])
    assert header.startswith("| tool | recall@1")
    assert line.startswith("| some tool | 100.0%")


# ---------------------------------------------------------------- calibration


def test_plain_text_drops_the_markup_and_keeps_the_text() -> None:
    assert plain_text("## Title\n\nSome *bold* `code` and [a link](x.md).") == (
        "Title Some bold code and a link ."
    )


def test_agreement_counts_the_same_rank_and_hit_or_miss_apart() -> None:
    result = agreement([(1, 1), (None, None), (2, 1), (None, 3)])

    assert (result.decisions, result.agreed, result.rate, result.hit_miss_rate) == (4, 2, 0.5, 0.75)
    assert agreement([]).rate == 1


def _chunk(version: str, *path: str, article: str = GUIDE) -> Hit:
    return Hit(version=version, article=article, heading_path=["Guide", *path])


def test_calibration_compares_chunk_id_and_text_decisions() -> None:
    copy = "docs/copy.md"  # another article with the same text as Lifespan
    cases = [
        _case(name="found"),
        _case(name="copied"),
        _case("v1", [_expected("v1", "Install")], ["it needs Python 3.12"], name="shared"),
        _case(expected=[], name="unanswerable"),
    ]
    results = {
        "found": (Answer(hits=[_chunk("v2", "Lifespan")]), [LIFESPAN]),
        "copied": (
            Answer(hits=[_chunk("v2", "Lifespan", article=copy), _chunk("v2", "Lifespan")]),
            [LIFESPAN, LIFESPAN],
        ),
        "shared": (Answer(hits=[_chunk("v1", "Install")]), [INSTALL]),
        "unanswerable": (Answer(hits=[]), []),
    }
    c = calibrate("default", cases, results, {"demo": INDEX}, matches=held_match({}))

    assert (c.agreement.decisions, c.agreement.agreed) == (3, 2)
    assert c.agreement.hit_miss_rate == 1
    (d,) = c.disagreements
    assert (d.case, d.chunk_id_rank, d.text_rank) == ("copied", 2, 1)
    assert "another article or version" in d.why
    assert c.wrong_version_agreement == 1
    assert [p.threshold for p in c.sweep] == [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    assert c.chunk_id.recall_at_1 == pytest.approx(2 / 3, abs=1e-4)
    assert c.text.metrics.recall_at_1 == 1
    assert c.facts_in_expected_sections == 1
    assert not c.passed

    report = TextScorerReport(
        golden="sha256:x",
        cases=4,
        projects=["demo"],
        corpus=[],
        environment={},
        scorer=scorer_settings(),
        calibrations=[c],
    )
    (problem,) = problems(report)
    assert problem == (
        "default: the text scorer agrees with chunk-ID scoring on 66.7% of 3 decisions, "
        f"under {MIN_AGREEMENT * 100:.1f}%"
    )
    summary = markdown(report)
    assert "| `default` | 3 | 66.7% | 100.0% |" in summary
    assert "| 0.8 (chosen) |" in summary
    assert "copied: v2 docs/guide.md [Guide > Lifespan]: chunk ID 2, text 1" in summary


# ---------------------------------------------------------------- the command


def test_the_command_calibrates_on_exactdocs_own_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = tiny_corpus(tmp_path)[:6]  # corpus, cases, cache (no models)
    out = tmp_path / "out"

    assert main([*args, "--chunkings", "default,h2", "--out", str(out)]) == 0

    report = TextScorerReport.model_validate_json((out / "text-scorer.json").read_text("utf-8"))
    assert [c.chunking for c in report.calibrations] == ["default", "h2"]
    for c in report.calibrations:
        assert (c.agreement.decisions, c.agreement.rate) == (1, 1)
        assert c.text.metrics.recall_at_1 == c.chunk_id.recall_at_1 == 1
        assert c.text.metrics.wrong_version_rate == 0
        assert c.text.unmatched_share == 0
    assert report.scorer["threshold"] == pytest.approx(0.8)
    assert report.environment["exactdocs_commit"]
    assert (out / "text-scorer.md").read_text("utf-8") in capsys.readouterr().out


def test_the_command_refuses_an_unknown_chunking(tmp_path: Path) -> None:
    args = tiny_corpus(tmp_path)[:6]

    assert main([*args, "--chunkings", "h9", "--out", str(tmp_path / "out")]) == 2
