"""``just eval``: build the fixture, run the suite, write the JSON report and the job summary."""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from exactdocs.retrieval.models import ModelRole
from fixture_repo import DocsRepo, build
from retrieval_eval.dataset import DATASET_FILE, fingerprint, load_dataset
from retrieval_eval.fixture import configured_container, model_free_container, run_on_fixture
from retrieval_eval.suite import (
    BASELINE_FILE,
    MODES,
    Comparison,
    baseline_of,
    compare,
    markdown,
    read_baseline,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="just eval",
        description="Compare retrieval modes on the fixture docs repository (docs/evals.md).",
    )
    parser.add_argument(
        "--modes",
        default=",".join(m.mode.value for m in MODES),
        help="comma-separated modes to try (default: all; those that cannot run are reported)",
    )
    parser.add_argument(
        "--configured-models",
        action="store_true",
        help="use the models EXACTDOCS_AI__... configures (default: none, so only BM25 runs)",
    )
    parser.add_argument(
        "--local-roles",
        default="",
        help="comma-separated configured roles whose model runs on this machine (embedding, "
        "reranker, llm); any other configured role counts as a hosted provider",
    )
    parser.add_argument(
        "--allow-providers",
        action="store_true",
        help="also run modes that call a hosted model (manual runs only, never in PR jobs)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=f"baseline JSON to compare recall@5 with (default: {BASELINE_FILE.name}; CI passes "
        "the copy on develop); a path given here must exist",
    )
    parser.add_argument(
        "--ratchet",
        action="store_true",
        help=f"fail when this branch's {BASELINE_FILE.name} stores a lower recall@5 for a gating "
        "mode than --baseline (CI: the baseline only moves up), or was recorded for another "
        "dataset; when --baseline was recorded for another dataset, the branch's is the bar",
    )
    parser.add_argument(
        "--reference-dataset",
        type=Path,
        default=None,
        help="the dataset --baseline was measured on (CI: the copy on develop); when the dataset "
        "changed, it is run too and gated against --baseline, so old questions still catch a "
        "ranking regression",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/evals/retrieval.json"),
        help="where to write the JSON report",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(os.environ["GITHUB_STEP_SUMMARY"])
        if os.environ.get("GITHUB_STEP_SUMMARY")
        else None,
        help="append the Markdown summary here (default: $GITHUB_STEP_SUMMARY when set)",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=f"store this run's ranking metrics and the dataset's fingerprint as the baseline "
        f"({BASELINE_FILE.name})",
    )
    return parser


def _names(text: str) -> set[str]:
    return {name.strip().lower() for name in text.split(",") if name.strip()}


def main(argv: list[str] | None = None) -> int:
    """Run the suite.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        0 when every gate passed, 1 otherwise, 2 for a usage error.
    """
    args = _parser().parse_args(argv)
    wanted = _names(args.modes)
    unknown = wanted - {m.mode.value for m in MODES}
    if unknown:
        sys.stderr.write(f"unknown mode(s): {', '.join(sorted(unknown))}\n")
        return 2
    roles = _names(args.local_roles)
    if roles - {r.value for r in ModelRole}:
        sys.stderr.write(f"unknown role(s): {', '.join(sorted(roles))}\n")
        return 2
    if args.baseline is not None and not args.baseline.is_file():
        sys.stderr.write(f"baseline not found: {args.baseline}\n")
        return 2
    if args.reference_dataset is not None and not args.reference_dataset.is_file():
        sys.stderr.write(f"reference dataset not found: {args.reference_dataset}\n")
        return 2
    reference = read_baseline(args.baseline or BASELINE_FILE)
    comparison = compare(
        fingerprint(load_dataset()), reference, read_baseline(BASELINE_FILE), ratchet=args.ratchet
    )
    runs = [("Retrieval eval", args.report, comparison, DATASET_FILE)]
    if comparison.reset is not None:
        # The annotation shows on the pull request's checks, where a reviewer looks.
        sys.stdout.write(f"::warning title=Eval baseline reset::{comparison.reset}\n")
        if args.reference_dataset is not None:
            runs.append(
                (
                    "Retrieval eval on the reference dataset",
                    args.report.with_name(f"{args.report.stem}-reference{args.report.suffix}"),
                    Comparison(baseline=reference.recall_at_5, source=reference.source),
                    args.reference_dataset,
                )
            )
    passed = True
    with tempfile.TemporaryDirectory(prefix="exactdocs-eval-") as tmp:
        repo = build(Path(tmp) / "fixture" / "docs-repo")
        for index, (title, report_file, against, dataset_file) in enumerate(runs):
            report = asyncio.run(
                run_on_fixture(
                    DocsRepo(repo, repo.as_uri(), ""),
                    Path(tmp) / f"data-{index}",
                    build=configured_container if args.configured_models else model_free_container,
                    modes=[m for m in MODES if m.mode.value in wanted],
                    allow_providers=args.allow_providers,
                    local_roles=frozenset(ModelRole(r) for r in roles),
                    comparison=against,
                    dataset_file=dataset_file,
                )
            )
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
            summary = markdown(report, title=title)
            sys.stdout.write(summary)
            if args.summary is not None:
                with args.summary.open("a", encoding="utf-8") as out:
                    out.write(summary)
            if args.write_baseline and index == 0:
                BASELINE_FILE.write_text(baseline_of(report), encoding="utf-8")
            passed = passed and report.passed
    return 0 if passed else 1
