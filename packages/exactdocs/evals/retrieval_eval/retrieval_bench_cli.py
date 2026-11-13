"""``just retrieval-bench``: every retrieval configuration on the golden set, per chunking (#347).

The matrix crosses BM25, hybrid (each local embedding model and the hosted one), HyDE and agentic
with no reranking, the local cross-encoder and the LLM judge. Each chunking configuration of the
ingestion benchmark imports the corpus once into its own data directory; every configuration then
runs on it in a container of its own, built with only the model roles it needs, so local and
hosted runs differ by nothing else. Hosted configurations run only with ``--allow-providers``
(the manual real-providers workflow), never in CI. See docs/evals.md#the-retrieval-benchmark.
"""

import argparse
import asyncio
import fnmatch
import os
import platform
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final, Protocol

from exactdocs.bootstrap.constants import (
    DEFAULT_LOCAL_EMBEDDING,
    DEFAULT_LOCAL_RERANKER,
    LOCAL_PROFILE,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.local_models import model_folder, read_marker
from exactdocs.bootstrap.settings import (
    AiSettings,
    EmbeddingRoleSettings,
    JudgeSettings,
    ProviderSettings,
    RerankerSettings,
    RoleSettings,
    Settings,
)
from exactdocs.retrieval.dtos import GetLibraryRetrievalQuery
from exactdocs.retrieval.models import RerankWith, RetrievalMode
from exactdocs.retrieval.ports.driven import AgentReads
from fixture_import import embed_fixture
from fixture_repo import git
from retrieval_eval.dataset import Answer, Hit, Question, RetrievalDataset, fingerprint
from retrieval_eval.evaluators import SectionMatch
from retrieval_eval.fixture import instance_spend, model_free_container
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Corpus,
    Project,
    default_cache_dir,
    fetch,
    load_corpus,
    load_golden,
)
from retrieval_eval.golden_cli import import_corpus, selected
from retrieval_eval.golden_run import golden_retriever, nested_match, run_golden
from retrieval_eval.ingestion_cli import CONFIGURATIONS, Configuration, stored_chunks
from retrieval_eval.retrieval_bench import (
    Budget,
    ConfigResult,
    IndexCost,
    ModelInfo,
    RetrievalBenchReport,
    check,
    markdown,
    recommend,
    row_of,
    run_problems,
)
from retrieval_eval.retrievers import RecordedReads, Retriever
from retrieval_eval.suite import MODES

REPORT_DIR: Final[Path] = Path("reports/evals")
"""Where ``retrieval.json`` and ``retrieval.md`` are written, by default."""
RESULTS_DIR: Final[Path] = Path(__file__).parents[1] / "results"
"""The recorded run in the repository, which ``--check`` compares with by default."""
HOSTED: Final[str] = "hosted"
"""Stands for the embedding model the environment configures (``EXACTDOCS_AI__EMBEDDING__...``)."""
LOCAL_EMBEDDINGS: Final[tuple[str, ...]] = (
    DEFAULT_LOCAL_EMBEDDING,
    "snowflake/snowflake-arctic-embed-s",
    "BAAI/bge-base-en-v1.5",
)
"""The local embedding models compared by default: the default, one of another family of the
same size, and a larger one of the default's family (``exactdocs models pull`` each)."""
RERANKER_TIMEOUT: Final[float] = 30.0
"""Seconds a local cross-encoder may take, as in the release's eval job, so every rerank counts."""
_PACKAGES: Final[tuple[str, ...]] = (
    "exactdocs",
    "fastembed",
    "onnxruntime",
    "pydantic-ai-slim",
    "pydantic-evals",
)
"""The libraries whose versions a result depends on."""
_SETTINGS: Final[set[str]] = {
    "embedding",
    "reranker",
    "llm",
    "judge",
    "rerank_with",
    "hyde",
    "agentic",
}
"""The ``ai`` settings a result records (no provider keys, budgets or prices)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchConfig:
    """A retrieval configuration of the matrix."""

    name: str
    """Its name in the report."""
    budget: Budget
    """What it needs: no model, local models only, or a hosted model."""
    mode: RetrievalMode
    """The mode its searches ask for."""
    embedding: str | None = None
    """A local embedding model's name, ``HOSTED``, or None."""
    rerank: RerankWith | None = None
    """What reranks it: the local cross-encoder, the LLM judge (hosted), or nothing."""


def _short(model: str) -> str:
    return model.rsplit("/", 1)[-1]


def matrix(local_embeddings: Sequence[str]) -> list[BenchConfig]:
    """Every configuration: each base with no reranker, the cross-encoder and the judge.

    Args:
        local_embeddings: The local embedding models to compare.

    Returns:
        The configurations, cheapest first.
    """
    bases = [("bm25", RetrievalMode.BM25, None, Budget.NONE)]
    bases += [
        (f"hybrid:{_short(m)}", RetrievalMode.HYBRID, m, Budget.LOCAL) for m in local_embeddings
    ]
    bases.append((f"hybrid:{HOSTED}", RetrievalMode.HYBRID, HOSTED, Budget.HOSTED))
    configs = []
    for name, mode, embedding, budget in bases:
        configs += [
            BenchConfig(name=name, budget=budget, mode=mode, embedding=embedding),
            BenchConfig(
                name=f"{name}+ce",
                budget=Budget.LOCAL if budget is Budget.NONE else budget,
                mode=mode,
                embedding=embedding,
                rerank=RerankWith.CROSS_ENCODER,
            ),
            BenchConfig(
                name=f"{name}+judge",
                budget=Budget.HOSTED,
                mode=mode,
                embedding=embedding,
                rerank=RerankWith.JUDGE,
            ),
        ]
    configs += [
        BenchConfig(
            name=f"hyde:{HOSTED}",
            budget=Budget.HOSTED,
            mode=RetrievalMode.HYBRID_HYDE,
            embedding=HOSTED,
        ),
        BenchConfig(name=f"agentic:{HOSTED}", budget=Budget.HOSTED, mode=RetrievalMode.AGENTIC),
    ]
    return configs


@dataclass(frozen=True, slots=True, kw_only=True)
class Models:
    """Where the models of a run come from."""

    hosted: AiSettings
    """The environment's ``ai`` settings: the hosted profiles, roles and prices."""
    models_dir: Path
    """Where ``exactdocs models pull`` put the local models."""
    local_reranker: str
    """The local cross-encoder."""


def _local(model: str, models: Models) -> str | None:
    """Say why a local model cannot run.

    Args:
        model: Its name.
        models: Where models come from.

    Returns:
        The reason, or None when it is pulled.
    """
    marker = read_marker(model_folder(models.models_dir, model))
    if marker is None or marker.model != model:
        return f"{model} is not in {models.models_dir}: run `exactdocs models pull {model}`"
    return None


def ai_for(config: BenchConfig, models: Models) -> AiSettings | str:
    """Build the ``ai`` settings of one configuration: only the roles it calls.

    Args:
        config: The configuration.
        models: Where models come from.

    Returns:
        The settings, or why the configuration cannot run.
    """
    hosted = models.hosted
    providers = dict(hosted.providers)
    embedding, llm = EmbeddingRoleSettings(), RoleSettings()
    reranker, judge = RerankerSettings(), JudgeSettings()
    needs: list[str] = []
    local: list[str] = []
    if config.embedding == HOSTED:
        embedding = hosted.embedding
        needs += [] if embedding.model else ["EXACTDOCS_AI__EMBEDDING__MODEL"]
    elif config.embedding is not None:
        local.append(config.embedding)
        embedding = EmbeddingRoleSettings(model=f"{LOCAL_PROFILE}:{config.embedding}")
    if config.mode in {RetrievalMode.HYBRID_HYDE, RetrievalMode.AGENTIC}:
        llm = hosted.llm
        needs += [] if llm.model else ["EXACTDOCS_AI__LLM__MODEL"]
    if config.rerank is RerankWith.CROSS_ENCODER:
        local.append(models.local_reranker)
        reranker = RerankerSettings(
            model=f"{LOCAL_PROFILE}:{models.local_reranker}", timeout=RERANKER_TIMEOUT
        )
    elif config.rerank is RerankWith.JUDGE:
        judge, llm = hosted.judge, hosted.llm if llm.model is None else llm
        needs += [] if judge.model or llm.model else ["EXACTDOCS_AI__JUDGE__MODEL"]
    if needs:
        return f"needs a hosted model: {', '.join(needs)} is not set"
    if missing := [why for m in local if (why := _local(m, models)) is not None]:
        return "; ".join(missing)
    if local:
        providers[LOCAL_PROFILE] = ProviderSettings(kind=LOCAL_PROFILE)
    return AiSettings(
        providers=providers,
        embedding=embedding,
        reranker=reranker,
        llm=llm,
        judge=judge,
        rerank_with=config.rerank or RerankWith.CROSS_ENCODER,
        hyde=hosted.hyde,
        agentic=hosted.agentic,
        prices=hosted.prices,
    )


def model_infos(ai: AiSettings, models: Models) -> list[ModelInfo]:
    """Name every model a configuration calls, with its Hub commit when it is local.

    Args:
        ai: The configuration's settings.
        models: Where models come from.

    Returns:
        One entry per configured role.
    """
    roles: list[tuple[str, str | None, int | None]] = [
        ("embedding", ai.embedding.model, ai.embedding.dimensions),
        ("reranker", ai.reranker.model, None),
        ("llm", ai.llm.model, None),
        ("judge", ai.judge.model if ai.rerank_with is RerankWith.JUDGE else None, None),
    ]
    infos = []
    for role, name, dimensions in roles:
        if name is None:
            continue
        profile, _, model = name.partition(":")
        settings = ai.providers.get(profile)
        info = ModelInfo(
            role=role,
            model=name,
            kind=settings.kind if settings else None,
            base_url=settings.base_url if settings else None,
            dimensions=dimensions,
        )
        marker = read_marker(model_folder(models.models_dir, model))
        if profile == LOCAL_PROFILE and marker is not None:
            info = info.model_copy(
                update={"revision": marker.revision, "dimensions": marker.dimensions}
            )
        infos.append(info)
    return infos


class Builder(Protocol):
    """Builds the app's container for one configuration (tests: with stand-in models)."""

    def __call__(self, settings: Settings, *, agent_reads: AgentReads | None = None) -> Container:
        """Build the container.

        Args:
            settings: The settings, with the configuration's ``ai`` section.
            agent_reads: Records the agentic explorer's reads.

        Returns:
            The container.
        """
        ...


def _build(settings: Settings, *, agent_reads: AgentReads | None = None) -> Container:
    """Build the app's container as an instance with these settings would.

    Args:
        settings: The settings.
        agent_reads: Records the agentic explorer's reads.

    Returns:
        The container.
    """
    return Container.build(settings, agent_reads=agent_reads)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Recording:
    """Implements ``Retriever``: keeps every answer, so the rows can be scored after the run."""

    inner: Retriever
    """The retriever asked."""
    answers: dict[str, Answer]
    """Each answer, by its question's JSON."""

    async def answer(self, question: Question) -> Answer:
        """Ask the inner retriever and keep its answer.

        Args:
            question: The question.

        Returns:
            Its answer.
        """
        found = await self.inner.answer(question)
        self.answers[question.model_dump_json()] = found
        return found


type _Held = dict[tuple[str, str, tuple[str, ...]], set[tuple[str, ...]]]
"""The heading paths each ``(commit, article, heading path)``'s chunks hold."""


async def _held(container: Container, projects: Sequence[Project]) -> _Held:
    """Read which headings each stored chunk holds, for the nested match rule.

    Args:
        container: The container, running, with the corpus imported.
        projects: The projects.

    Returns:
        The heading paths by chunk.
    """
    held: _Held = {}
    for project in projects:
        for pinned in project.versions:
            stored = await stored_chunks(container.engine, project.library, pinned.name)
            for path, cut in stored.items():
                for chunk in cut:
                    key = (pinned.commit, path, chunk.heading_path)
                    held.setdefault(key, set()).update((chunk.heading_path, *chunk.headings))
    return held


@dataclass(frozen=True, slots=True, kw_only=True)
class _Run:
    """What every configuration of one chunking shares."""

    projects: Sequence[Project]
    dataset: RetrievalDataset
    chunking: Configuration
    data_dir: Path
    models: Models
    allow_providers: bool
    build: Builder
    matches: SectionMatch
    """When a hit answers an expected section, at this chunking's depth."""
    indexes: dict[str, IndexCost]
    """The cost of embedding the corpus, by embedding model, once per chunking."""


async def _index(container: Container) -> IndexCost:
    """Embed every version the container's embedding model does not cover yet, and time it.

    Args:
        container: The container, running.

    Returns:
        What it took: seconds, and the tokens and USD the spend ledger grew by.
    """
    tokens, usd = await instance_spend(container.engine)
    started = time.perf_counter()
    await embed_fixture(container)  # every version, as the embed jobs would
    after = await instance_spend(container.engine)
    return IndexCost(
        seconds=round(time.perf_counter() - started, 1),
        tokens=after[0] - tokens,
        usd=round(after[1] - usd, 6),
    )


def _matcher(held: _Held) -> SectionMatch:
    """The nested match rule over the chunks a chunking stored.

    Args:
        held: The heading paths each chunk holds.

    Returns:
        The rule (``golden_run.nested_match``).
    """

    def holds(hit: Hit) -> frozenset[tuple[str, ...]]:
        """The heading paths a hit's chunk holds.

        Args:
            hit: A returned hit.

        Returns:
            Every heading path of the chunk with its commit, article and heading path.
        """
        return frozenset(held.get((hit.commit_sha or "", hit.article, tuple(hit.heading_path)), ()))

    return nested_match(holds)


async def _run_config(config: BenchConfig, run: _Run) -> ConfigResult:
    """Run one configuration on an imported corpus.

    Args:
        config: The configuration.
        run: The chunking's shared state.

    Returns:
        Its result, or why it did not run.
    """
    result = ConfigResult(
        configuration=config.name,
        chunking=run.chunking.name,
        budget=config.budget,
        mode=config.mode.value,
        rerank=None if config.rerank is None else config.rerank.value,
        status="ran",
    )
    if config.budget is Budget.HOSTED and not run.allow_providers:
        reason = "needs a real-providers run (--allow-providers, eval-providers.yml)"
        return result.model_copy(update={"status": "skipped", "reason": reason})
    ai = ai_for(config, run.models)
    if isinstance(ai, str):
        return result.model_copy(update={"status": "unavailable", "reason": ai})
    result = result.model_copy(
        update={
            "models": model_infos(ai, run.models),
            "settings": ai.model_dump(mode="json", include=_SETTINGS),
        }
    )
    reads = RecordedReads()
    settings = Settings(data_dir=run.data_dir, models_dir=run.models.models_dir, ai=ai)
    container = run.build(settings, agent_reads=reads)
    async with container.running(jobs=False):
        status = await container.retrieval.get_library_retrieval(
            GetLibraryRetrievalQuery(library=run.projects[0].library)
        )
        if config.mode not in status.available_modes or status.effective_reranker != config.rerank:
            reason = (
                f"the app offers {', '.join(m.value for m in status.available_modes)}, "
                f"reranked by {status.effective_reranker}"
            )
            return result.model_copy(update={"status": "unavailable", "reason": reason})
        spent = partial(instance_spend, container.engine)
        if config.embedding is not None and config.embedding not in run.indexes:
            run.indexes[config.embedding] = await _index(container)
        answers: dict[str, Answer] = {}
        retriever = _Recording(
            inner=golden_retriever(
                container.retrieval,
                Corpus(projects=list(run.projects)),
                config.mode.value,
                spent=spent,
                reads=reads,
            ),
            answers=answers,
        )

        mode = next(m for m in MODES if m.mode is config.mode)
        outcome = await run_golden(
            run.dataset, retriever, mode=mode, matches=run.matches, reranker=config.rerank
        )
    rows = [
        row_of(case, found, run.matches)
        for case in run.dataset.cases
        if (found := answers.get(case.inputs.model_dump_json())) is not None
    ]
    return result.model_copy(
        update={
            "index": run.indexes.get(config.embedding or ""),
            "fallbacks": outcome.fallbacks,
            "reranked": outcome.reranked,
            "rerank_fallbacks": outcome.rerank_fallbacks,
            "misses": len(outcome.misses),
            "errors": outcome.errors,
            "wrong_version_cases": outcome.wrong_version_cases,
            "left_version_cases": outcome.left_version_cases,
        }
    ).with_breakdowns(rows)


def environment() -> dict[str, str]:
    """Record what a result depends on besides its settings and the corpus.

    Returns:
        The ExactDocs commit (``-dirty`` with uncommitted changes), Python, platform, CPU count
        and the versions of the libraries that run the models.
    """
    repo = Path(__file__).resolve().parents[4]
    commit = git("rev-parse", "HEAD", cwd=repo)
    dirty = git("status", "--porcelain", "--untracked-files=no", cwd=repo)
    info = {
        "exactdocs_commit": commit + ("-dirty" if dirty else ""),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "cpus": str(os.cpu_count()),
    }
    for package in _PACKAGES:
        try:
            info[package] = version(package)
        except PackageNotFoundError:
            info[package] = "not installed"
    return info


def picked(patterns: Sequence[str], config: str, chunking: str) -> bool:
    """Tell whether a configuration runs at a chunking configuration.

    Args:
        patterns: Shell patterns of configuration names (``hybrid:*``), or of
            ``<configuration>@<chunking>`` (``*+ce@default``) to run one at some chunkings only.
        config: The configuration's name.
        chunking: The chunking configuration's name.

    Returns:
        True when a pattern matches.
    """
    return any(
        fnmatch.fnmatchcase(f"{config}@{chunking}" if "@" in p else config, p) for p in patterns
    )


async def bench(
    projects: Sequence[Project],
    repos: Mapping[str, Path],
    dataset: RetrievalDataset,
    chunkings: Sequence[Configuration],
    configs: Sequence[BenchConfig],
    *,
    hosted: AiSettings,
    models_dir: Path,
    local_reranker: str = DEFAULT_LOCAL_RERANKER,
    allow_providers: bool = False,
    build: Builder = _build,
    only: Sequence[str] = ("*",),
) -> RetrievalBenchReport:
    """Run every configuration at every chunking configuration.

    Args:
        projects: The projects.
        repos: The cached repository of each.
        dataset: The golden set, restricted to ``projects``.
        chunkings: The chunking configurations.
        configs: The retrieval configurations.
        hosted: The environment's ``ai`` settings (hosted profiles, roles and prices).
        models_dir: Where the local models were pulled.
        local_reranker: The local cross-encoder.
        allow_providers: Run the hosted configurations (by hand only).
        build: Builds a configuration's container.
        only: Which configurations run at which chunking (``picked``).

    Returns:
        The report.

    Raises:
        RuntimeError: A version was not imported at its pinned commit.
    """
    models = Models(hosted=hosted, models_dir=models_dir, local_reranker=local_reranker)
    results: list[ConfigResult] = []
    for chunking in chunkings:
        with tempfile.TemporaryDirectory(prefix="exactdocs-retrieval-bench-") as tmp:
            data_dir = Path(tmp) / "data"
            importer = model_free_container(data_dir)
            async with importer.running(jobs=False):
                records = await import_corpus(importer, projects, dict(repos), chunking.chunking)
                if wrong := [r for r in records if r.imported_commit != r.pinned_commit]:
                    names = ", ".join(f"{r.project} {r.version}" for r in wrong)
                    message = f"not imported at the pinned commit: {names}"
                    raise RuntimeError(message)
                held = await _held(importer, projects)
            run = _Run(
                projects=projects,
                dataset=dataset,
                chunking=chunking,
                data_dir=data_dir,
                models=models,
                allow_providers=allow_providers,
                build=build,
                matches=_matcher(held),
                indexes={},
            )
            for config in configs:
                if not picked(only, config.name, chunking.name):
                    continue
                started = time.perf_counter()
                results.append(await _run_config(config, run))
                sys.stderr.write(
                    f"{chunking.name} {config.name}: {results[-1].status} "
                    f"({time.perf_counter() - started:.0f} s)\n"
                )
    return RetrievalBenchReport(
        golden=fingerprint(dataset),
        cases=len(dataset.cases),
        projects=[p.id for p in projects],
        corpus=[
            {"project": p.id, "version": v.name, "commit": v.commit}
            for p in projects
            for v in p.versions
        ],
        environment=environment(),
        chunkings=[
            {"name": c.name, "about": c.about, **c.chunking.model_dump(mode="json")}
            for c in chunkings
        ],
        results=results,
        recommendations=recommend(results),
    )


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="retrieval-bench",
        description="Retrieval configurations measured on the golden set (docs/evals.md).",
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
        "--chunkings",
        default="",
        help=f"comma-separated chunking configurations (default: all: "
        f"{', '.join(c.name for c in CONFIGURATIONS)})",
    )
    parser.add_argument(
        "--configs",
        default="*",
        help="comma-separated configuration names or patterns, e.g. 'bm25*,hybrid:bge-small*'; "
        "<pattern>@<chunking> runs one at some chunkings only, e.g. '*+ce@default' "
        "(default: every one; those that cannot run are reported)",
    )
    parser.add_argument(
        "--local-embeddings",
        default=",".join(LOCAL_EMBEDDINGS),
        help="comma-separated local embedding models (default: %(default)s)",
    )
    parser.add_argument(
        "--local-reranker",
        default=DEFAULT_LOCAL_RERANKER,
        help="the local cross-encoder (default: %(default)s)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="where `exactdocs models pull` put the local models (default: EXACTDOCS_MODELS_DIR, "
        "else the data directory's models/)",
    )
    parser.add_argument(
        "--allow-providers",
        action="store_true",
        help="run the hosted configurations with the models EXACTDOCS_AI__... configures "
        "(manual runs only, never in CI)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_DIR,
        help="the directory retrieval.json and retrieval.md go to (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        nargs="?",
        type=Path,
        const=RESULTS_DIR / "retrieval.json",
        help="fail when a result got worse than in this recorded report "
        "(default: the one in the repository)",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    return parser


def _names(text: str) -> list[str]:
    return [name.strip() for name in text.split(",") if name.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code: 1 when the corpus cannot be fetched, a result has a wrong version or an
        error, or ``--check`` finds a regression; 2 for an unknown chunking configuration.
    """
    args = _parser().parse_args(argv)
    corpus = load_corpus(args.corpus)
    projects = selected(corpus, args.projects)
    wanted = set(_names(args.chunkings))
    if unknown := wanted - {c.name for c in CONFIGURATIONS}:
        sys.stderr.write(f"unknown chunking configurations: {', '.join(sorted(unknown))}\n")
        return 2
    chunkings = [c for c in CONFIGURATIONS if not wanted or c.name in wanted]
    try:
        repos = {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    golden = load_golden(args.cases)
    golden.cases = [c for c in golden.cases if c.inputs.project in {p.id for p in projects}]
    environment_settings = Settings()
    report = asyncio.run(
        bench(
            projects,
            repos,
            golden,
            chunkings,
            matrix(_names(args.local_embeddings)),
            hosted=environment_settings.ai,
            models_dir=args.models_dir or environment_settings.effective_models_dir,
            local_reranker=args.local_reranker,
            allow_providers=args.allow_providers,
            only=_names(args.configs),
        )
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "retrieval.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    summary = markdown(report)
    (args.out / "retrieval.md").write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as out:
            out.write(summary)
    sys.stdout.write(f"report: {args.out / 'retrieval.json'}, {args.out / 'retrieval.md'}\n")
    problems = run_problems(report)
    if args.check is not None:
        recorded = RetrievalBenchReport.model_validate_json(args.check.read_text(encoding="utf-8"))
        problems = check(report, recorded)
    for problem in problems:
        sys.stderr.write(f"problem: {problem}\n")
    return 1 if problems else 0
