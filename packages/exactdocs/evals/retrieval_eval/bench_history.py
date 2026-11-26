"""Every recorded benchmark run, kept as one row per result in ``results/history.json`` (#616).

A recorded report under ``evals/results/`` is overwritten by the next run, so the earlier runs
live on only here. ``just bench-pages`` adds the rows of the current reports that the history
does not hold yet (dated today unless the report says when it ran) and fills each family's
``<!-- bench:history-<family> -->`` block with a table of all of them, newest first;
docs/javascripts/bench-history.js makes that table sortable and filterable in the browser.

The rows are read from the reports as plain JSON, not through their models, so a report of an
older schema (read back from git history) gives rows too; a field it lacks is left empty.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from operator import itemgetter
from pathlib import Path
from typing import Any, Final

from agent_bench.arms import CONTEXT7

type Row = dict[str, Any]
type Report = Mapping[str, Any]

COMMIT_URL: Final[str] = "https://github.com/SirCypkowskyy/ExactDocs/commit/"

# (key, header, format) per family; "date" comes first in every family. The formats:
# text, code, commit, golden, pct (a share), score (0 to 1), int, num (one decimal).
COLUMNS: Final[dict[str, list[tuple[str, str, str]]]] = {
    "ingestion": [
        ("date", "Date", "text"),
        ("chunking", "Chunking", "code"),
        ("golden", "Golden", "golden"),
        ("chunks", "Chunks", "int"),
        ("coverage", "Coverage", "pct"),
        ("tokens_p50", "Tokens p50", "int"),
        ("tokens_p95", "Tokens p95", "int"),
        ("small_share", "Small chunks", "pct"),
        ("wrong_heading_paths", "Wrong heading paths", "int"),
        ("bm25_recall_at_5", "BM25 recall@5", "pct"),
        ("bm25_mrr", "BM25 MRR", "score"),
    ],
    "retrieval": [
        ("date", "Date", "text"),
        ("report", "Report", "text"),
        ("configuration", "Configuration", "code"),
        ("chunking", "Chunking", "code"),
        ("budget", "Budget", "text"),
        ("mode", "Mode", "text"),
        ("golden", "Golden", "golden"),
        ("commit", "Commit", "commit"),
        ("recall_at_1", "recall@1", "pct"),
        ("recall_at_5", "recall@5", "pct"),
        ("recall_at_10", "recall@10", "pct"),
        ("mrr", "MRR", "score"),
        ("ndcg_at_10", "nDCG@10", "score"),
        ("wrong_version_rate", "Wrong version", "pct"),
        ("context_tokens", "Context tokens", "num"),
    ],
    "agent": [
        ("date", "Date", "text"),
        ("agent_model", "Agent model", "code"),
        ("arm", "Arm", "code"),
        ("retrieval", "Retrieval", "code"),
        ("judge", "Judge", "code"),
        ("commit", "Commit", "commit"),
        ("questions", "Questions", "int"),
        ("accuracy", "Accuracy", "pct"),
        ("wrong_version_share", "Wrong version", "pct"),
        ("grounded_share", "Read the answer", "pct"),
        ("tool_calls", "Tool calls / question", "num"),
        ("tokens", "Tokens / question", "num"),
    ],
    "comparison": [
        ("date", "Date", "text"),
        ("tool", "Tool", "text"),
        ("configuration", "Configuration", "code"),
        ("golden", "Golden", "golden"),
        ("commit", "Commit", "commit"),
        ("recall_at_1", "recall@1", "pct"),
        ("recall_at_5", "recall@5", "pct"),
        ("recall_at_10", "recall@10", "pct"),
        ("mrr", "MRR", "score"),
        ("ndcg_at_10", "nDCG@10", "score"),
        ("context_tokens", "Context tokens", "num"),
        ("facts_found", "Facts found", "pct"),
    ],
}


def _day(value: str | None) -> str | None:
    """An ISO day from a report's date (``2026-11-25T22:04:39+00:00`` or ``25 November 2026``).

    Returns:
        ``YYYY-MM-DD``, or ``None`` for no date.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return datetime.strptime(f"{value} +0000", "%d %B %Y %z").date().isoformat()


def ingestion(report: Report, _name: str) -> list[Row]:
    """One row per chunking configuration of an ingestion report.

    Returns:
        The rows.
    """
    rows = []
    for c in report.get("configurations", []):
        totals, bm25 = c.get("totals", {}), c.get("bm25") or {}
        rows.append(
            {
                "family": "ingestion",
                "chunking": c.get("name"),
                "golden": report.get("golden"),
                "chunks": totals.get("chunks"),
                "coverage": totals.get("coverage"),
                "tokens_p50": totals.get("tokens_p50"),
                "tokens_p95": totals.get("tokens_p95"),
                "small_share": totals.get("small_share"),
                "wrong_heading_paths": totals.get("wrong_heading_paths"),
                "bm25_recall_at_5": bm25.get("recall_at_5"),
                "bm25_mrr": bm25.get("mrr"),
            }
        )
    return rows


def retrieval(report: Report, name: str) -> list[Row]:
    """One row per result that ran, of a retrieval benchmark or grid report.

    Returns:
        The rows.
    """
    bench = report.get("bench", report)  # a grid report holds the benchmark's report
    env = bench.get("environment", {})
    rows = []
    for r in bench.get("results", []):
        m = r.get("metrics")
        if r.get("status", "ran") != "ran" or not m:
            continue
        by = r.get("recorded_by") or {}
        rows.append(
            {
                "family": "retrieval",
                "date": _day(by.get("date")),
                "report": name,
                "configuration": r.get("configuration"),
                "chunking": r.get("chunking"),
                "budget": r.get("budget"),
                "mode": r.get("mode"),
                "golden": bench.get("golden"),
                "commit": by.get("exactdocs_commit") or env.get("exactdocs_commit"),
                **{k: m.get(k) for k in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr")},
                "ndcg_at_10": m.get("ndcg_at_10"),
                "wrong_version_rate": m.get("wrong_version_rate"),
                "context_tokens": m.get("context_tokens_per_question"),
            }
        )
    return rows


def agent(report: Report, _name: str) -> list[Row]:
    """One row per agent model and arm of an agent benchmark report; never a ``context7`` one.

    Returns:
        The rows.
    """
    meta = report.get("meta", {})
    return [
        {
            "family": "agent",
            "date": _day(meta.get("started_at")),
            "agent_model": c.get("agent_model"),
            "arm": c.get("arm"),
            "retrieval": c.get("retrieval"),
            "judge": meta.get("judge_model"),
            "commit": meta.get("git_commit"),
            "questions": c.get("questions"),
            "accuracy": c.get("accuracy"),
            "wrong_version_share": c.get("wrong_version_share"),
            "grounded_share": c.get("grounded_share"),
            "tool_calls": c.get("tool_calls_per_question"),
            "tokens": c.get("tokens_per_question"),
        }
        for c in report.get("cells", [])
        # Context7's terms forbid publishing its numbers (docs/evals/context7.md#terms-of-service)
        if c.get("arm") != CONTEXT7
    ]


def comparison(report: Report, _name: str) -> list[Row]:
    """One row per configuration of another tool, and ExactDocs' baseline, scored from the text.

    Returns:
        The rows.
    """
    tool = report.get("tool", {})
    named = f"{tool.get('name', '?')} {tool.get('version', '')}".strip()
    scored = [
        (named, r.get("configuration"), r.get("result") or {}) for r in report.get("runs", [])
    ]
    baseline = report.get("baseline") or {}
    if baseline:
        scored.append(("ExactDocs", baseline.get("name"), baseline.get("result") or {}))
    rows = []
    for name, configuration, result in scored:
        text = result.get("metrics") or {}
        m = text.get("metrics") or {}
        rows.append(
            {
                "family": "comparison",
                "date": _day(report.get("date")),
                "tool": name,
                "configuration": configuration,
                "golden": report.get("golden"),
                "commit": report.get("environment", {}).get("exactdocs_commit"),
                **{k: m.get(k) for k in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr")},
                "ndcg_at_10": m.get("ndcg_at_10"),
                "context_tokens": text.get("context_tokens_per_question"),
                "facts_found": text.get("facts_found_rate"),
            }
        )
    return rows


REPORTS: Final[dict[str, Callable[[Report, str], list[Row]]]] = {
    "ingestion": ingestion,
    "retrieval": retrieval,
    "retrieval-grid-rank1": retrieval,
    "retrieval-grid-grouped": retrieval,
    "agent": agent,
    "grounded-docs": comparison,
}
"""The reports that make history, by file name in ``results/`` without ``.json``."""


def rows_of(results: Path) -> list[Row]:
    """The rows of every report in ``results`` that exists.

    Returns:
        The rows, in the order of ``REPORTS``.
    """
    rows = []
    for name, read in REPORTS.items():
        path = results / f"{name}.json"
        if path.exists():
            rows += read(json.loads(path.read_text("utf-8")), name)
    return rows


def _key(row: Row) -> str:
    return json.dumps({k: v for k, v in row.items() if k not in {"date", "commit"}}, sort_keys=True)


def merge(history: Iterable[Row], rows: Iterable[Row], today: date) -> list[Row]:
    """The history with the rows it does not hold yet, a row without a date dated ``today``.

    A row counts as held when every field but the date and the commit is the same, so a result
    a report keeps from an earlier run (``--resume``, ``recorded_by``) is not added again, and a
    row keeps the date and commit of the run that first gave it.

    Returns:
        Every row, ordered by family, then date; rows of one day keep their order.
    """
    merged = list(history)
    held = {_key(r) for r in merged}
    for row in rows:
        if _key(row) not in held:
            held.add(_key(row))
            merged.append({**row, "date": row.get("date") or today.isoformat()})
    families = list(COLUMNS)
    return sorted(merged, key=lambda r: (families.index(r["family"]), r["date"]))


def dumps(history: Iterable[Row]) -> str:
    """The history as JSON, one row per line, so that a new run is a diff of new lines.

    Returns:
        The file's text.
    """
    lines = (json.dumps({"date": r["date"], **r}, ensure_ascii=False) for r in history)
    return "[\n" + ",\n".join(lines) + "\n]\n"


def _cell(value: object, kind: str) -> str:
    if value in {None, ""}:
        return ""
    match kind:
        case "pct":
            text = f"{float(str(value)):.1%}"
        case "score":
            text = f"{float(str(value)):.3f}"
        case "int":
            text = f"{int(str(value)):,}"
        case "num":
            text = f"{float(str(value)):,.1f}"
        case "code":
            text = f"`{value}`"
        case "golden":
            text = f"`{str(value).removeprefix('sha256:')[:8]}`"
        case "commit":
            text = f"[`{str(value)[:7]}`]({COMMIT_URL}{value})"
        case _:
            text = str(value)
    return re.sub(r"(?<!\\)\|", r"\|", text)


def table(history: Iterable[Row], family: str) -> str:
    """A family's rows as a Markdown table, newest first, in the block the page script enhances.

    Returns:
        The Markdown.
    """
    columns = COLUMNS[family]
    rows = sorted(
        (r for r in history if r["family"] == family), key=itemgetter("date"), reverse=True
    )
    lines = [
        '<div class="bench-history" markdown>',
        "",
        "| " + " | ".join(header for _, header, _ in columns) + " |",
        "|" + "---|" * len(columns),
        *("| " + " | ".join(_cell(r.get(k), kind) for k, _, kind in columns) + " |" for r in rows),
        "",
        "</div>",
    ]
    return "\n".join(lines)


def today() -> date:
    """Today in UTC, the date of a run whose report does not say when it ran.

    Returns:
        The day.
    """
    return datetime.now(UTC).date()
