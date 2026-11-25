"""``just context7-bench``: Context7 on the golden set, where it serves the pinned versions (#493).

For every pinned version of the golden corpus, the first of its questions goes to Context7's
``/v2/context`` with ``/owner/repo/<version>``; the ``version`` note of the response says whether
Context7 serves that version (``context7.coverage_of``). The other questions of a served or
unverified version are asked the same way; those of a version it does not serve are asked with
``/owner/repo`` alone, its current docs, as an agent gets them there. Each response is cut at the
``query-docs`` budget and scored with the text scorer, per coverage group, next to ExactDocs' BM25
at ``default`` asked and scored the same way in the run (as the Grounded Docs run does).

Every raw response is kept in ``--responses`` (one JSON file per request), so ``--from-cache``
scores again without calling Context7. Calling it needs ``CONTEXT7_API_KEY``: the run refuses to
go out without one. CI never runs this: the quick tests use a stand-in. See docs/evals/context7.md.
"""

import argparse
import asyncio
import datetime as dt
import hashlib
import os
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from http import HTTPStatus
from pathlib import Path
from typing import Any, Final, Protocol

import httpx

from retrieval_eval.context7 import (
    API_BASE,
    API_KEY_VARIABLE,
    API_VERSION,
    CONTEXT_PATH,
    ERROR,
    GROUP_OF,
    GROUPS,
    LATEST_ONLY,
    TOKEN_BUDGET,
    Context7Report,
    Coverage,
    Fetched,
    Group,
    coverage_of,
    markdown,
    problems,
    results_of,
    within_budget,
)
from retrieval_eval.dataset import RetrievalDataset, fingerprint
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    GoldenCase,
    Project,
    default_cache_dir,
    fetch,
    load_corpus,
    load_golden,
)
from retrieval_eval.golden_cli import selected
from retrieval_eval.grounded_docs import TEXT_BASELINE, Baseline, Recorded, paired, tokens_interval
from retrieval_eval.grounded_docs_cli import RESULTS_DIR, exactdocs_baseline, recorded_results
from retrieval_eval.retrieval_bench_cli import environment
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS
from retrieval_eval.text_bench import TextAnswer, TextResult, TextRow, scorer_settings, text_row
from retrieval_eval.text_match import SectionIndex

REPORT_DIR: Final[Path] = Path("reports/evals")
"""Where the report goes by default."""
REPORT_NAME: Final[str] = "context7"
"""The report's file name, without extension."""
RESPONSES_DIR: Final[Path] = REPORT_DIR / "context7-responses"
"""Where the raw responses are kept by default: a workflow artifact, never committed."""
TIMEOUT_SECONDS: Final[float] = 60.0
"""How long one request may take."""
RATE_LIMIT_RETRIES: Final[int] = 5
"""How many times a rate-limited request (429) is sent again."""
MAX_WAIT_SECONDS: Final[float] = 60.0
"""The longest wait honoured from ``Retry-After``."""


class Context7(Protocol):
    """Context7's documentation endpoint (the real API, or a stand-in in tests)."""

    def describe(self) -> dict[str, str]:
        """Say what answers.

        Returns:
            Fields for the report's ``tool``.
        """
        ...

    async def context(self, library_id: str, query: str) -> Fetched:
        """Ask ``/v2/context``.

        Args:
            library_id: ``/owner/repo`` or ``/owner/repo/<version>``.
            query: The question.

        Returns:
            The raw response.
        """
        ...


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


class HttpContext7:
    """Context7's REST API over HTTP, with the API key."""

    def __init__(self, key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Keep the key.

        Args:
            key: The API key (``CONTEXT7_API_KEY``).
            transport: The HTTP transport (tests: a mock); the network by default.
        """
        self._key = key
        self._transport = transport

    def describe(self) -> dict[str, str]:
        """Say what answers.

        Returns:
            The client.
        """
        return {"client": f"httpx {httpx.__version__}"}

    async def context(self, library_id: str, query: str) -> Fetched:
        """Ask ``/v2/context`` for JSON, waiting out rate limits.

        Args:
            library_id: ``/owner/repo`` or ``/owner/repo/<version>``.
            query: The question.

        Returns:
            The raw response (the last one when the rate limit never lifted).
        """
        params = {"libraryId": library_id, "query": query, "type": "json"}
        headers = {"Authorization": f"Bearer {self._key}"}
        async with httpx.AsyncClient(
            base_url=API_BASE, timeout=TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            attempt = 0
            while True:
                started = time.perf_counter()
                response = await client.get(CONTEXT_PATH, params=params, headers=headers)
                elapsed = round((time.perf_counter() - started) * 1000, 3)
                limited = response.status_code == HTTPStatus.TOO_MANY_REQUESTS
                if not limited or attempt == RATE_LIMIT_RETRIES:
                    return Fetched(
                        status=response.status_code, body=response.text, date=_now(), ms=elapsed
                    )
                attempt += 1
                try:
                    wait = float(response.headers.get("Retry-After", "1"))
                except ValueError:
                    wait = 1.0
                await asyncio.sleep(min(max(wait, 0.0), MAX_WAIT_SECONDS))


class CachedContext7:
    """Context7 behind a cache of its raw responses, one JSON file per request."""

    def __init__(self, directory: Path, inner: Context7 | None) -> None:
        """Keep the cache and what fills it.

        Args:
            directory: The cache.
            inner: Context7; None to answer from the cache only (``--from-cache``).
        """
        self._directory = directory
        self._inner = inner

    def describe(self) -> dict[str, str]:
        """Say what answers.

        Returns:
            Context7's description, or that the cache answered.
        """
        return self._inner.describe() if self._inner else {"client": "cache"}

    def _path(self, library_id: str, query: str) -> Path:
        digest = hashlib.sha256(f"{library_id}\n{query}".encode()).hexdigest()[:32]
        return self._directory / f"{digest}.json"

    async def context(self, library_id: str, query: str) -> Fetched:
        """Answer from the cache, or ask Context7 and keep a successful answer.

        Args:
            library_id: ``/owner/repo`` or ``/owner/repo/<version>``.
            query: The question.

        Returns:
            The raw response.

        Raises:
            RuntimeError: From the cache only, and the request is not in it.
        """
        path = self._path(library_id, query)
        if path.exists():
            return Fetched.model_validate_json(path.read_text(encoding="utf-8"))
        if self._inner is None:
            message = f"not in the cache: {library_id} {query!r}"
            raise RuntimeError(message)
        fetched = await self._inner.context(library_id, query)
        if fetched.status in {
            HTTPStatus.OK,
            HTTPStatus.NOT_FOUND,
        }:  # an answer; a failure is asked again next run
            self._directory.mkdir(parents=True, exist_ok=True)
            path.write_text(fetched.model_dump_json(), encoding="utf-8")
        return fetched


def _answer(fetched: Fetched) -> TextAnswer:
    """Context7's results for one question, cut at the budget.

    Args:
        fetched: The response.

    Returns:
        The answer.
    """
    return TextAnswer(texts=within_budget(results_of(fetched)), search_ms=fetched.ms)


async def ask_context7(
    tool: Context7, projects: Sequence[Project], dataset: RetrievalDataset
) -> tuple[list[Coverage], dict[str, tuple[str, Fetched]], list[str]]:
    """Resolve every pinned version and ask each of its questions.

    Args:
        tool: Context7.
        projects: The projects.
        dataset: The golden set.

    Returns:
        The coverage, each case's group and response by name, and the failed questions.
    """
    coverage: list[Coverage] = []
    asked: dict[str, tuple[str, Fetched]] = {}
    errors: list[str] = []
    for project in projects:
        for pinned in project.versions:
            cases = [
                c
                for c in dataset.cases
                if (c.inputs.project, c.inputs.version) == (project.id, pinned.name)
            ]
            requested = f"{project.library}/{pinned.name}"
            probe = await tool.context(requested, cases[0].inputs.query if cases else "docs")
            decided = coverage_of(probe, pinned.name)
            status, resolved, served = decided or (ERROR, "", None)
            coverage.append(
                Coverage(
                    project=project.id,
                    version=pinned.name,
                    requested_id=requested,
                    status=status,
                    resolved_id=resolved,
                    served=served,
                    date=probe.date,
                )
            )
            if status == ERROR:
                errors.extend(f"{c.name}: HTTP {probe.status}" for c in cases)
                continue
            group = GROUP_OF[status]
            library = project.library if group == LATEST_ONLY else requested
            for i, case in enumerate(cases):
                fetched = probe if i == 0 and library == requested else None
                fetched = fetched or await tool.context(library, case.inputs.query)
                if fetched.status != HTTPStatus.OK:
                    errors.append(f"{case.name}: HTTP {fetched.status}")
                asked[case.name or ""] = (group, fetched)
    return coverage, asked, errors


def _group(
    name: str,
    answers: Mapping[str, tuple[GoldenCase, Fetched]],
    baseline: Mapping[str, TextRow],
    indexes: Mapping[str, SectionIndex],
    recorded: Sequence[tuple[Recorded, list[Any]]],
) -> Group:
    """Score one coverage group's answers and test them against ExactDocs on its cases.

    Args:
        name: The group.
        answers: Each case and Context7's response, by case name.
        baseline: ExactDocs' BM25 row of every case, by name.
        indexes: Each project's sections.
        recorded: ExactDocs configurations of the recorded run, with their rows.

    Returns:
        The group.
    """
    rows = [
        text_row(case, _answer(fetched), indexes[case.inputs.project or ""])
        for case, fetched in answers.values()
    ]
    theirs = [baseline[n] for n in answers]
    mine = [r.row for r in rows]
    versus = [paired(TEXT_BASELINE, "text", [r.row for r in theirs], mine)]
    versus.extend(
        paired(f"ExactDocs {r.configuration} @ {r.chunking}", "chunk ID", recorded_rows, mine)
        for r, recorded_rows in recorded
    )
    return Group(
        name=name,
        about=GROUPS[name],
        versions=sorted({f"{c.inputs.project} {c.inputs.version}" for c, _ in answers.values()}),
        result=TextResult.of(f"Context7 {name}", rows),
        context_tokens_interval=tokens_interval(rows),
        rows=rows,
        baseline=TextResult.of(TEXT_BASELINE, theirs),
        versus=versus,
    )


async def bench(
    tool: Context7,
    projects: Sequence[Project],
    repos: Mapping[str, Path],
    dataset: RetrievalDataset,
    recorded_path: Path,
) -> Context7Report:
    """Ask Context7 and ExactDocs' baseline every question, and compare them per group.

    Args:
        tool: Context7.
        projects: The projects.
        repos: The cached repository of each.
        dataset: The golden set, restricted to ``projects``.
        recorded_path: The recorded retrieval benchmark run.

    Returns:
        The report.
    """
    machine = environment()
    indexes = {p.id: SectionIndex.of_project(p, repos[p.id]) for p in projects}
    coverage, asked, errors = await ask_context7(tool, projects, dataset)
    with tempfile.TemporaryDirectory(prefix="exactdocs-context7-bench-") as tmp:
        base_rows = await exactdocs_baseline(projects, repos, dataset, indexes, Path(tmp) / "data")
    golden = fingerprint(dataset)
    recorded = recorded_results(recorded_path, golden, [p.id for p in projects])
    by_case = {c.name or "": c for c in dataset.cases}
    base_by_case = {r.case: r for r in base_rows}
    groups = []
    for name in GROUPS:
        names = sorted(case for case, (group, _) in asked.items() if group == name)
        if names:
            answers = {n: (by_case[n], asked[n][1]) for n in names}
            groups.append(_group(name, answers, base_by_case, indexes, recorded))
    return Context7Report(
        golden=golden,
        cases=len(dataset.cases),
        projects=[p.id for p in projects],
        corpus=[
            {"project": p.id, "version": v.name, "commit": v.commit}
            for p in projects
            for v in p.versions
        ],
        date=_now(),
        tool={
            "name": "Context7",
            "api": API_BASE,
            "api_version": API_VERSION,
            "endpoint": f"GET {CONTEXT_PATH}?type=json",
            "token_budget": str(TOKEN_BUDGET),
            **tool.describe(),
        },
        environment=machine,
        scorer=scorer_settings(),
        statistics=DEFAULT_STATS,
        coverage=coverage,
        baseline=Baseline(
            name=TEXT_BASELINE,
            result=TextResult.of(TEXT_BASELINE, base_rows),
            context_tokens_interval=tokens_interval(base_rows),
            rows=sorted(base_rows, key=lambda r: r.case),
        ),
        recorded=[r for r, _ in recorded],
        groups=groups,
        errors=errors,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="context7-bench",
        description="Context7 on the golden set, next to ExactDocs (docs/evals/context7.md).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="where the fetched projects are kept (default: %(default)s)",
    )
    parser.add_argument("--offline", action="store_true", help="fetch no project")
    parser.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    parser.add_argument(
        "--responses",
        type=Path,
        default=RESPONSES_DIR,
        help="where Context7's raw responses are kept (default: %(default)s)",
    )
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="score the kept responses again; never call Context7",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_DIR,
        help=f"the directory {REPORT_NAME}.json and {REPORT_NAME}.md go to (default: %(default)s)",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    parser.add_argument(
        "--recorded", type=Path, default=RESULTS_DIR / "retrieval.json", help=argparse.SUPPRESS
    )
    return parser


def main(argv: Sequence[str] | None = None, tool: Callable[[], Context7] | None = None) -> int:
    """Run the benchmark.

    Args:
        argv: The arguments; ``sys.argv`` by default.
        tool: Builds Context7 (tests: a stand-in); the REST API with ``CONTEXT7_API_KEY`` by
            default.

    Returns:
        The exit code: 1 when the corpus cannot be fetched, a response is not cached with
        ``--from-cache``, or the run has problems (``context7.problems``); 2 when Context7
        would be called without an API key.
    """
    args = _parser().parse_args(argv)
    inner: Context7 | None = None
    if not args.from_cache:
        if tool is not None:
            inner = tool()
        elif key := os.environ.get(API_KEY_VARIABLE, "").strip():
            inner = HttpContext7(key)
        else:
            sys.stderr.write(f"{API_KEY_VARIABLE} is not set (or pass --from-cache)\n")
            return 2
    corpus = load_corpus(args.corpus)
    projects = selected(corpus, args.projects)
    golden = load_golden(args.cases)
    golden.cases = [c for c in golden.cases if c.inputs.project in {p.id for p in projects}]
    try:
        repos = {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
        report = asyncio.run(
            bench(CachedContext7(args.responses, inner), projects, repos, golden, args.recorded)
        )
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{REPORT_NAME}.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    summary = markdown(report)
    (args.out / f"{REPORT_NAME}.md").write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as out:
            out.write(summary)
    found = problems(report)
    for problem in found:
        sys.stderr.write(f"problem: {problem}\n")
    return 1 if found else 0
