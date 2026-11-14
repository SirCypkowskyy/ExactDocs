"""Run the suite on the fixture docs repository, imported for real into the app's container."""

import dataclasses
from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.sqlite import ai_spend
from exactdocs.retrieval.constants import MICROS_PER_USD, SPEND_SCOPE_INSTANCE
from exactdocs.retrieval.models import ModelRole, RetrievalMode, SpendWindow
from exactdocs.retrieval.ports.driven import AgentReads
from exactdocs.retrieval.use_cases import NoModelRoles
from fixture_import import LIBRARY, commits, embed_fixture, import_fixture
from fixture_repo import DocsRepo, git_bytes, headings
from retrieval_eval.dataset import DATASET_FILE, RetrievalDataset, fingerprint, load_dataset
from retrieval_eval.retrievers import RecordedReads
from retrieval_eval.suite import (
    MODES,
    Comparison,
    EvalMode,
    SuiteReport,
    judge,
    run_modes,
    with_evaluators,
)


class ContainerBuilder(Protocol):
    """Builds the app's container the suite runs on."""

    def __call__(self, data_dir: Path, *, agent_reads: AgentReads | None = None) -> Container:
        """Build the container.

        Args:
            data_dir: An empty data directory.
            agent_reads: Records the agentic explorer's reads, so the suite checks each run's
                trace; pass it to ``Container.build``.

        Returns:
            The container.
        """
        ...


def configured_container(data_dir: Path, *, agent_reads: AgentReads | None = None) -> Container:
    """Build the app's container as an instance with this data directory would.

    Args:
        data_dir: An empty data directory.
        agent_reads: Records the agentic explorer's reads.

    Returns:
        The container; its model roles come from the environment (``EXACTDOCS_AI__...``).
    """
    return Container.build(Settings(data_dir=data_dir), agent_reads=agent_reads)


def model_free_container(data_dir: Path, *, agent_reads: AgentReads | None = None) -> Container:
    """Build the app's container with no model role, whatever the environment configures.

    Args:
        data_dir: An empty data directory.
        agent_reads: Records the agentic explorer's reads (none run here).

    Returns:
        The container: only BM25 can run, and nothing can call a model.
    """
    return Container.build(
        Settings(data_dir=data_dir), model_roles=NoModelRoles(), agent_reads=agent_reads
    )


def missing_sections(dataset: RetrievalDataset, docs_repo: DocsRepo) -> list[str]:
    """Cases asking for a version, or expecting a section, that the fixture does not have.

    Such a case would only count as a miss; the suite fails on it instead (an old dataset run on
    a changed fixture, docs/evals.md).

    Args:
        dataset: The cases.
        docs_repo: The built fixture repository.

    Returns:
        One problem per missing version or section.
    """
    problems = []
    for case in dataset.cases:
        version = case.inputs.version
        ref = f"{version}^{{commit}}"
        if not git_bytes("rev-parse", "--verify", "--quiet", ref, cwd=docs_repo.path, check=False):
            problems.append(f"{case.name}: the fixture has no version {version}")
            continue
        for hit in case.expected_output.hits if case.expected_output else []:
            raw = git_bytes("show", f"{hit.version}:{hit.article}", cwd=docs_repo.path, check=False)
            text = raw.decode("latin-1") if hit.article.endswith("latin1.md") else raw.decode()
            if tuple(hit.heading_path) not in headings(text):
                section = " > ".join(hit.heading_path)
                problems.append(
                    f"{case.name}: the fixture has no section {hit.version}:{hit.article} {section}"
                )
    return problems


async def run_on_fixture(
    docs_repo: DocsRepo,
    data_dir: Path,
    *,
    build: ContainerBuilder = model_free_container,
    modes: Sequence[EvalMode] = MODES,
    allow_providers: bool = False,
    local_roles: frozenset[ModelRole] = frozenset(),
    comparison: Comparison | None = None,
    dataset_file: Path = DATASET_FILE,
    not_judged: Mapping[RetrievalMode, str] | None = None,
    expect_engine: str | None = None,
) -> SuiteReport:
    """Import every fixture version, run the dataset through each mode and apply the gates.

    Args:
        docs_repo: The built fixture repository.
        data_dir: An empty data directory for the container.
        build: Builds the container: model-free by default; ``configured_container`` uses the
            environment's models, ``offline_data_container`` the in-process term-hash
            embedding, tests pass model roles and pipelines. It is given the recorder of the
            agentic explorer's reads, so every agentic run's trace is checked.
        modes: The modes to try.
        allow_providers: Run modes that call a hosted model.
        local_roles: The configured roles whose model runs on this machine.
        comparison: What to compare with (``compare``); none: no comparison.
        dataset_file: The dataset to run: the repository's by default;
            ``--reference-dataset`` also runs ``develop``'s when the dataset changed.
        not_judged: Modes whose eligibility as a default the run cannot tell, and why.
        expect_engine: The full-text search engine that must answer (the release: ``pg_search`` on
            ParadeDB); another one fails the suite, so a silent fallback cannot pass.

    Returns:
        The judged report.
    """
    dataset = with_evaluators(load_dataset(dataset_file))
    missing = missing_sections(dataset, docs_repo)
    comparison = comparison or Comparison()
    comparison = dataclasses.replace(comparison, problems=(*missing, *comparison.problems))
    reads = RecordedReads()
    container = build(data_dir, agent_reads=reads)
    async with container.running(jobs=False):
        await import_fixture(container, docs_repo)
        engine = (await container.retrieval.get_search_index_state()).engine
        if expect_engine is not None and engine != expect_engine:
            problem = f"the search engine was {engine}, not the expected {expect_engine}"
            comparison = dataclasses.replace(comparison, problems=(*comparison.problems, problem))
        if ModelRole.EMBEDDING in local_roles or allow_providers:
            await embed_fixture(container)  # as the embed jobs would; a no-op without a model
        outcomes = await run_modes(
            dataset,
            retrieval=container.retrieval,
            library=LIBRARY,
            commits=commits(docs_repo),
            modes=modes,
            allow_providers=allow_providers,
            local_roles=local_roles,
            spent=partial(instance_spend, container.engine),
            reads=reads,
        )
    return judge(
        dataset.name,
        len(dataset.cases),
        outcomes,
        comparison,
        fingerprint=fingerprint(dataset),
        not_judged=not_judged,
        search_engine=engine,
    )


async def instance_spend(engine: AsyncEngine) -> tuple[int, float]:
    """Read what the instance's models have cost so far, from the spend ledger.

    Args:
        engine: The app's database.

    Returns:
        Input tokens and US dollars over the instance's monthly rows.
    """
    statement = select(
        func.coalesce(func.sum(ai_spend.c.input_tokens), 0),
        func.coalesce(func.sum(ai_spend.c.usd_micros), 0),
    ).where(
        ai_spend.c.scope_kind == SPEND_SCOPE_INSTANCE,
        ai_spend.c.window_kind == SpendWindow.MONTH.value,
    )
    async with engine.connect() as connection:
        tokens, micros = (await connection.execute(statement)).one()
    return int(tokens), int(micros) / MICROS_PER_USD
