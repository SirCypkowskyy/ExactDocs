"""``just golden-review``: draw the review sample, run the whole-set checks, summarize the review.

See docs/evals.md#reviewing-the-golden-set.
"""

import argparse
import datetime
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Final

import yaml

from retrieval_eval.dataset import fingerprint
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    default_cache_dir,
    fetch,
    load_cases,
    load_corpus,
    load_golden,
)
from retrieval_eval.golden_cli import selected
from retrieval_eval.golden_review import (
    REVIEW_FILE,
    Section,
    checks_markdown,
    draw_sample,
    load_review,
    review_block,
    run_checks,
    sheet_markdown,
    version_sections,
)

REPORT_DIR: Final[Path] = Path("reports/golden-review")
"""Where the sheet and the checks go, by default."""
DEFAULT_SEED: Final[int] = 490
"""The seed of the recorded review's sample (#490)."""
DEFAULT_PER_STRATUM: Final[int] = 3
"""Cases per kind and project: 90 over five projects and six kinds."""


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="golden-review",
        description="Review the golden set: a seeded sample, whole-set checks (docs/evals.md).",
    )
    parser.add_argument("command", choices=["sample", "checks", "summary"])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="sample: the random seed")
    parser.add_argument(
        "--per-stratum",
        type=int,
        default=DEFAULT_PER_STRATUM,
        help="sample: cases per kind and project (default: %(default)s)",
    )
    parser.add_argument(
        "--no-text",
        action="store_true",
        help="sample: link the sections only; do not quote them from the cache",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="where the fetched projects are kept (default: %(default)s)",
    )
    parser.add_argument("--offline", action="store_true", help="fetch nothing; use the cache")
    parser.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    parser.add_argument(
        "--out", type=Path, default=REPORT_DIR, help="where the files go (default: %(default)s)"
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--review", type=Path, default=REVIEW_FILE, help=argparse.SUPPRESS)
    return parser


def _draft(sample: Sequence[tuple[str, object]], seed: int, per_stratum: int, drawn: str) -> str:
    """A review file to fill in: one entry per sampled case, the verdict left blank.

    Args:
        sample: The sampled ``(project, case)`` pairs.
        seed: The seed.
        per_stratum: Cases per stratum.
        drawn: The golden set's fingerprint.

    Returns:
        The YAML.
    """
    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    entries = [
        {
            "case": getattr(case, "name", ""),
            "project": project,
            "kind": getattr(getattr(case, "metadata", None), "kind", ""),
            "verdict": "",
            "problems": [],
            "reviewer": "",
            "date": today,
            "note": "",
        }
        for project, case in sample
    ]
    data = {
        "sample": {"seed": seed, "per_stratum": per_stratum, "drawn_from": drawn},
        "entries": entries,
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code: 1 when the corpus cannot be fetched or a case file does not load.
    """
    args = _parser().parse_args(argv)
    if args.command == "summary":
        sys.stdout.write(review_block(load_review(args.review)) + "\n")
        return 0
    corpus = load_corpus(args.corpus)
    projects = selected(corpus, args.projects)
    cases, problems = load_cases(args.cases)
    if problems:
        sys.stderr.write("\n".join(problems) + "\n")
        return 1
    wanted = {p.id for p in projects}
    cases = [(p, c) for p, c in cases if p in wanted]
    needs_cache = args.command == "checks" or not args.no_text
    try:
        repos = (
            {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
            if needs_cache
            else {}
        )
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "checks":
        checks = run_checks(cases, corpus, repos)
        (args.out / "checks.json").write_text(
            json.dumps(asdict(checks), indent=2) + "\n", encoding="utf-8"
        )
        report = checks_markdown(checks)
        (args.out / "checks.md").write_text(report, encoding="utf-8")
        sys.stdout.write(report)
        sys.stdout.write(f"report: {args.out / 'checks.md'}, {args.out / 'checks.json'}\n")
        return 0
    sample = draw_sample(cases, seed=args.seed, per_stratum=args.per_stratum)
    texts: dict[tuple[str, str], list[Section]] | None = None
    if not args.no_text:
        texts = {
            (p.id, v.name): version_sections(repos[p.id], v.commit, p)
            for p in projects
            for v in p.versions
        }
    sheet = sheet_markdown(sample, corpus, texts, seed=args.seed)
    (args.out / "sheet.md").write_text(sheet, encoding="utf-8")
    drawn = fingerprint(load_golden(args.cases))
    (args.out / "review-draft.yaml").write_text(
        _draft(sample, args.seed, args.per_stratum, drawn), encoding="utf-8"
    )
    sys.stdout.write(
        f"{len(sample)} cases (seed {args.seed}, {args.per_stratum} per kind and project) from "
        f"golden set {drawn}: {args.out / 'sheet.md'}, {args.out / 'review-draft.yaml'}\n"
    )
    return 0
