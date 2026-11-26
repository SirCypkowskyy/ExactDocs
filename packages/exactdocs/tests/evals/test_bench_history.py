"""The history of recorded benchmark runs (#616): rows from the reports, merged and rendered."""

import json
from datetime import date

from retrieval_eval.bench_history import COLUMNS, agent, dumps, merge, retrieval, rows_of, table
from retrieval_eval.bench_pages import RESULTS

TODAY = date(2026, 12, 1)


def _retrieval_report(recall: float, commit: str = "c1") -> dict[str, object]:
    return {
        "golden": "sha256:a00997851150e3b0",
        "environment": {"exactdocs_commit": commit},
        "results": [
            {
                "configuration": "bm25",
                "chunking": "default",
                "budget": "none",
                "mode": "bm25",
                "status": "ran",
                "metrics": {"recall_at_5": recall, "mrr": 0.79},
            },
            {
                "configuration": "hybrid:x",
                "chunking": "default",
                "status": "skipped",
                "metrics": None,
            },
        ],
    }


def test_every_family_has_rows_from_the_recorded_reports() -> None:
    families = {row["family"] for row in rows_of(RESULTS)}

    assert families == set(COLUMNS)


def test_a_new_run_is_added_dated_today_and_an_unchanged_result_is_not() -> None:
    first = merge([], retrieval(_retrieval_report(0.91), "retrieval"), date(2026, 11, 24))
    # the same result again from a later commit, then a changed one
    again = merge(first, retrieval(_retrieval_report(0.91, "c2"), "retrieval"), TODAY)
    changed = merge(again, retrieval(_retrieval_report(0.92, "c3"), "retrieval"), TODAY)

    assert len(first) == 1, "a result that did not run is not history"
    assert again == first
    assert [(r["date"], r["commit"], r["recall_at_5"]) for r in changed] == [
        ("2026-11-24", "c1", 0.91),
        ("2026-12-01", "c3", 0.92),
    ]


def test_a_row_keeps_the_date_its_report_gives() -> None:
    report = {"meta": {"started_at": "2026-11-25T22:04:39+00:00"}, "cells": [{"arm": "none"}]}

    assert merge([], agent(report, "agent"), TODAY)[0]["date"] == "2026-11-25"


def test_an_older_report_without_a_field_gives_an_empty_cell() -> None:
    report = {"results": [{"configuration": "bm25", "metrics": {"recall_at_5": 0.8}}]}
    rows = merge([], retrieval(report, "retrieval"), TODAY)

    line = table(rows, "retrieval").splitlines()[4]
    assert line.startswith("| 2026-12-01 | retrieval | `bm25` |  |")
    assert "| 80.0% |" in line


def test_a_context7_cell_never_enters_the_history() -> None:
    report = {"meta": {}, "cells": [{"arm": "context7"}, {"arm": "exactdocs"}]}

    assert [r["arm"] for r in agent(report, "agent")] == ["exactdocs"]


def test_the_table_lists_the_newest_run_first_with_formatted_cells() -> None:
    rows = merge(
        [],
        retrieval(_retrieval_report(0.9101, "8e789e67177adf95"), "retrieval"),
        date(2026, 11, 24),
    )
    rows = merge(rows, retrieval(_retrieval_report(0.5, "c2"), "a|b"), TODAY)

    lines = table(rows, "retrieval").splitlines()
    assert lines[0] == '<div class="bench-history" markdown>'
    assert lines[4].startswith("| 2026-12-01 | a\\|b |")
    assert "| `a0099785` |" in lines[5]
    assert (
        "[`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf95)"
        in lines[5]
    )
    assert "| 91.0% |" in lines[5]
    assert "| 0.790 |" in lines[5]
    assert lines[-1] == "</div>"


def test_the_history_file_is_one_row_per_line_and_reads_back() -> None:
    rows = merge([], retrieval(_retrieval_report(0.9), "retrieval"), TODAY)

    text = dumps(rows)
    assert text.splitlines()[1].startswith('{"date": "2026-12-01", "family": "retrieval"')
    assert json.loads(text) == rows
