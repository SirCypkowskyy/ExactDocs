"""``just eval``: build the fixture, run the suite, write the JSON report and the job summary."""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from exactdocs.retrieval.models import ModelRole
from fixture_repo import DocsRepo, build
from retrieval_eval.fixture import configured_container, model_free_container, run_on_fixture
from retrieval_eval.suite import BASELINE_FILE, MODES, baseline_of, markdown, read_baseline


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
        "mode than --baseline (CI: the baseline only moves up)",
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
        help=f"store this run's ranking metrics as the baseline ({BASELINE_FILE.name})",
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
    baseline_path = args.baseline or BASELINE_FILE
    with tempfile.TemporaryDirectory(prefix="exactdocs-eval-") as tmp:
        repo = build(Path(tmp) / "fixture" / "docs-repo")
        report = asyncio.run(
            run_on_fixture(
                DocsRepo(repo, repo.as_uri(), ""),
                Path(tmp) / "data",
                build=configured_container if args.configured_models else model_free_container,
                modes=[m for m in MODES if m.mode.value in wanted],
                allow_providers=args.allow_providers,
                local_roles=frozenset(ModelRole(r) for r in roles),
                baseline=read_baseline(baseline_path),
                baseline_source=str(baseline_path) if baseline_path.is_file() else None,
                stored=read_baseline(BASELINE_FILE) if args.ratchet else None,
            )
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    summary = markdown(report)
    sys.stdout.write(summary)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as out:
            out.write(summary)
    if args.write_baseline:
        BASELINE_FILE.write_text(baseline_of(report), encoding="utf-8")
    return 0 if report.passed else 1
