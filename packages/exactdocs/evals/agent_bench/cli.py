"""``just agent-bench``: run the agent benchmark, export a labelling sample, compute agreement.

See docs/evals.md#the-agent-benchmark.
"""

import argparse
import asyncio
import importlib.metadata
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import yaml
from pydantic_ai import Agent
from pydantic_ai.models import Model

from agent_bench.agreement import LABELLING_HEADER, SAMPLE_SIZE, agreement, sample
from agent_bench.harness import (
    AGENT_INSTRUCTIONS,
    EMBEDDING_VARIABLE,
    PROMPT,
    Recorder,
    RetrievalConfig,
    asker,
    bench_dataset,
    exactdocs_toolset,
    import_golden,
)
from agent_bench.judge import AnswerJudge, judge_agent
from agent_bench.offline import OFFLINE_AGENTS, OFFLINE_JUDGE, offline_agent, offline_judge
from agent_bench.report import (
    BenchReport,
    CorpusCommit,
    QuestionResult,
    RunMeta,
    markdown,
    results_of,
    summarize,
)
from fixture_repo import git
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Corpus,
    GoldenCase,
    default_cache_dir,
    fetch,
    load_cases,
    load_corpus,
)

REPORT: Final[Path] = Path("reports/evals/agent-bench.json")
"""Where ``run`` writes the JSON report by default (the Markdown goes next to it)."""
SAMPLE: Final[Path] = Path("reports/evals/agent-bench-labels.yaml")
"""Where ``sample`` writes the labelling sample by default."""
DEFAULT_RETRIEVAL: Final[tuple[str, ...]] = ("bm25:mode=bm25", "hybrid:mode=hybrid")
"""The retrieval configurations when none is given. Without an embedding model, ``hybrid``
falls back to BM25 (the report shows ``bm25 (mode_unavailable)``)."""
DEFAULT_MAX_REQUESTS: Final[int] = 20
"""Model requests one question may take by default."""


def chat_model(name: str) -> Model | str:
    """Resolve an agent or judge model name.

    Args:
        name: A pydantic-ai model name (``openai:gpt-5-mini``), or a stand-in
            (``offline:search``, ``offline:read``, ``offline`` for the judge).

    Returns:
        The stand-in model, or the name for pydantic-ai to resolve.
    """
    if name in OFFLINE_AGENTS:
        return offline_agent(name)
    if name == OFFLINE_JUDGE:
        return offline_judge()
    return name


def selected_cases(
    cases: Sequence[tuple[str, GoldenCase]],
    *,
    projects: Sequence[str] = (),
    kinds: Sequence[str] = (),
    limit: int | None = None,
) -> list[tuple[str, GoldenCase]]:
    """Pick the cases to ask.

    Args:
        cases: ``(project, case)`` pairs.
        projects: Only these projects (all when empty).
        kinds: Only these kinds (all when empty).
        limit: At most this many per project, in file order.

    Returns:
        The cases, in file order.
    """
    taken: dict[str, int] = {}
    picked = []
    for project, case in cases:
        kind = case.metadata.kind if case.metadata else ""
        if (projects and project not in projects) or (kinds and kind not in kinds):
            continue
        if limit is not None and taken.get(project, 0) >= limit:
            continue
        taken[project] = taken.get(project, 0) + 1
        picked.append((project, case))
    return picked


async def run_bench(
    cases: Sequence[tuple[str, GoldenCase]],
    corpus: Corpus,
    repos: dict[str, Path],
    *,
    agent_models: Sequence[str],
    judge_model: str,
    retrieval: Sequence[RetrievalConfig],
    work_dir: Path,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    concurrency: int = 1,
) -> BenchReport:
    """Run every agent model under every retrieval configuration over the cases.

    For each configuration the corpus is imported (once per embedding model) and ExactDocs is
    started as shipped, ``exactdocs serve --stdio``, with the configuration's settings; each agent
    model then answers every case with only that server's tools, and the judge grades it.

    Args:
        cases: ``(project, case)`` pairs.
        corpus: The corpus manifest.
        repos: Each asked project's cached repository.
        agent_models: The agent models (pydantic-ai names or stand-ins).
        judge_model: The judge's model.
        retrieval: The retrieval configurations.
        work_dir: Where the data directories and the server logs go.
        max_requests: Model requests one question may take.
        concurrency: Questions asked at once.

    Returns:
        The report.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    dataset = bench_dataset(cases, corpus)
    dataset.add_evaluator(AnswerJudge(judge=judge_agent(chat_model(judge_model))))
    projects = [p for p in corpus.projects if p.id in {project for project, _ in cases}]
    titles = {p.id: p.title for p in projects}
    imports: dict[str, Path] = {}
    commits: list[CorpusCommit] = []
    rows: list[QuestionResult] = []
    for config in retrieval:
        embedding = config.env.get(EMBEDDING_VARIABLE, os.environ.get(EMBEDDING_VARIABLE, ""))
        if embedding not in imports:
            imports[embedding] = work_dir / f"data-{len(imports)}"
            records = await import_golden(imports[embedding], projects, repos, config.env)
            commits = commits or [
                CorpusCommit(
                    project=r.project,
                    version=r.version,
                    pinned_commit=r.pinned_commit,
                    imported_commit=r.imported_commit,
                )
                for r in records
            ]
        log_file = work_dir / f"server-{config.name}.log"
        async with exactdocs_toolset(imports[embedding], config.env, log_file) as toolset:
            for name in agent_models:
                agent = Agent[Recorder, str](
                    chat_model(name),
                    deps_type=Recorder,
                    instructions=AGENT_INSTRUCTIONS,
                    toolsets=[toolset],
                )
                task = asker(agent, name, titles, max_requests=max_requests)
                evaluated = await dataset.evaluate(
                    task,
                    name=f"{name} / {config.name}",
                    max_concurrency=concurrency,
                    progress=False,
                )
                rows += results_of(evaluated, name, config.name)
    cells = [
        summarize(
            name,
            config.name,
            [r for r in rows if (r.agent_model, r.retrieval) == (name, config.name)],
        )
        for config in retrieval
        for name in agent_models
    ]
    meta = RunMeta(
        started_at=started_at,
        exactdocs_version=importlib.metadata.version("exactdocs"),
        git_commit=git("rev-parse", "HEAD", cwd=Path(__file__).parent, check=False),
        agent_models=list(agent_models),
        judge_model=judge_model,
        retrieval={c.name: dict(c.env) for c in retrieval},
        max_requests=max_requests,
        concurrency=concurrency,
        cases=len(dataset.cases),
        agent_instructions=AGENT_INSTRUCTIONS,
        prompt=PROMPT,
        corpus=commits,
    )
    return BenchReport(meta=meta, cells=cells, questions=rows)


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="agent-bench",
        description="An agent with only the ExactDocs MCP tools answers the golden set "
        "(docs/evals.md#the-agent-benchmark).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the benchmark and write the report")
    run.add_argument(
        "--agent-model",
        action="append",
        default=[],
        help="pydantic-ai model name, repeat for several (e.g. openai:gpt-5-mini)",
    )
    run.add_argument("--judge-model", help="pydantic-ai model name of the judge")
    run.add_argument(
        "--retrieval",
        action="append",
        default=[],
        help="name[:key=value,...] of EXACTDOCS_AI__ settings, repeat for several "
        f"(default: {' and '.join(DEFAULT_RETRIEVAL)})",
    )
    run.add_argument(
        "--offline",
        action="store_true",
        help=f"stand-in models, no provider: {', '.join(OFFLINE_AGENTS)}, judge {OFFLINE_JUDGE}",
    )
    run.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    run.add_argument("--kinds", default="", help="comma-separated kinds (default: all)")
    run.add_argument("--limit", type=int, help="at most this many cases per project")
    run.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    run.add_argument("--concurrency", type=int, default=1, help="questions asked at once")
    run.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    run.add_argument(
        "--work-dir", type=Path, help="data directories and server logs (default: temporary)"
    )
    run.add_argument(
        "--report", type=Path, default=REPORT, help="the JSON report (Markdown next to it)"
    )
    run.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    run.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    labels = commands.add_parser("sample", help="export answers of a report for hand labelling")
    labels.add_argument("--report", type=Path, default=REPORT)
    labels.add_argument("--out", type=Path, default=SAMPLE)
    labels.add_argument("--size", type=int, default=SAMPLE_SIZE)
    labels.add_argument("--seed", type=int, default=0)
    agree = commands.add_parser("agreement", help="compare hand labels with the judge")
    agree.add_argument("--report", type=Path, default=REPORT)
    agree.add_argument("--labels", type=Path, default=SAMPLE)
    return parser


def _run(args: argparse.Namespace) -> int:
    """Run the benchmark, write the reports and print the Markdown.

    Args:
        args: The parsed ``run`` arguments.

    Returns:
        The exit code: 2 for a usage error, else 0 (the benchmark has no gate).
    """
    agent_models = list(OFFLINE_AGENTS) if args.offline else args.agent_model
    judge_model = OFFLINE_JUDGE if args.offline else args.judge_model
    if not agent_models or not judge_model:
        sys.stderr.write("agent-bench: give --agent-model and --judge-model, or --offline\n")
        return 2
    try:
        retrieval = [RetrievalConfig.parse(t) for t in args.retrieval or DEFAULT_RETRIEVAL]
    except ValueError as error:
        sys.stderr.write(f"agent-bench: {error}\n")
        return 2
    corpus = load_corpus(args.corpus)
    loaded, problems = load_cases(args.cases)
    if problems:
        sys.stderr.write("".join(f"agent-bench: {p}\n" for p in problems))
        return 2
    cases = selected_cases(
        loaded,
        projects=[p for p in args.projects.split(",") if p],
        kinds=[k for k in args.kinds.split(",") if k],
        limit=args.limit,
    )
    if not cases:
        sys.stderr.write("agent-bench: no case matches\n")
        return 2
    asked = {project for project, _ in cases}
    try:
        repos = {p.id: fetch(p, args.cache_dir) for p in corpus.projects if p.id in asked}
    except RuntimeError as error:
        sys.stderr.write(f"agent-bench: {error}\n")
        return 1
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="exactdocs-agent-bench-"))
    report = asyncio.run(
        run_bench(
            cases,
            corpus,
            repos,
            agent_models=agent_models,
            judge_model=judge_model,
            retrieval=retrieval,
            work_dir=work_dir,
            max_requests=args.max_requests,
            concurrency=args.concurrency,
        )
    )
    text = markdown(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    args.report.with_suffix(".md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(text)
    sys.stdout.write(f"\nreport: {args.report}; work dir: {work_dir}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code.
    """
    args = _parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    report = BenchReport.model_validate_json(args.report.read_text(encoding="utf-8"))
    if args.command == "sample":
        entries = sample(report, args.size, args.seed)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=100)
        args.out.write_text(LABELLING_HEADER + text, encoding="utf-8")
        sys.stdout.write(f"{len(entries)} answers to label in {args.out}\n")
        return 0
    labels = yaml.safe_load(args.labels.read_text(encoding="utf-8")) or []
    result = agreement(report, labels)
    sys.stdout.write(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")
    return 0
