"""Run the suite on the fixture docs repository, imported for real into the app's container."""

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.models import ModelRole
from exactdocs.retrieval.use_cases import NoModelRoles
from fixture_import import LIBRARY, commits, import_fixture
from fixture_repo import DocsRepo, git_bytes, headings
from retrieval_eval.dataset import DATASET_FILE, RetrievalDataset, fingerprint, load_dataset
from retrieval_eval.suite import (
    MODES,
    Comparison,
    EvalMode,
    SuiteReport,
    judge,
    run_modes,
    with_evaluators,
)


def configured_container(data_dir: Path) -> Container:
    """Build the app's container as an instance with this data directory would.

    Args:
        data_dir: An empty data directory.

    Returns:
        The container; its model roles come from the environment (``EXACTDOCS_AI__...``).
    """
    return Container.build(Settings(data_dir=data_dir))


def model_free_container(data_dir: Path) -> Container:
    """Build the app's container with no model role, whatever the environment configures.

    Args:
        data_dir: An empty data directory.

    Returns:
        The container: only BM25 can run, and nothing can call a model.
    """
    return Container.build(Settings(data_dir=data_dir), model_roles=NoModelRoles())


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
    build: Callable[[Path], Container] = model_free_container,
    modes: Sequence[EvalMode] = MODES,
    allow_providers: bool = False,
    local_roles: frozenset[ModelRole] = frozenset(),
    comparison: Comparison | None = None,
    dataset_file: Path = DATASET_FILE,
) -> SuiteReport:
    """Import every fixture version, run the dataset through each mode and apply the gates.

    Args:
        docs_repo: The built fixture repository.
        data_dir: An empty data directory for the container.
        build: Builds the container: model-free by default; ``configured_container`` uses the
            environment's models, tests pass model roles and pipelines.
        modes: The modes to try.
        allow_providers: Run modes that call a hosted model.
        local_roles: The configured roles whose model runs on this machine.
        comparison: What to compare with (``compare``); none: no comparison.
        dataset_file: The dataset to run: the repository's by default; CI also runs
            ``develop``'s when the dataset changed.

    Returns:
        The judged report.
    """
    dataset = with_evaluators(load_dataset(dataset_file))
    missing = missing_sections(dataset, docs_repo)
    comparison = comparison or Comparison()
    comparison = dataclasses.replace(comparison, problems=(*missing, *comparison.problems))
    container = build(data_dir)
    async with container.running(jobs=False):
        await import_fixture(container, docs_repo)
        outcomes = await run_modes(
            dataset,
            retrieval=container.retrieval,
            library=LIBRARY,
            commits=commits(docs_repo),
            modes=modes,
            allow_providers=allow_providers,
            local_roles=local_roles,
        )
    return judge(
        dataset.name,
        len(dataset.cases),
        outcomes,
        comparison,
        fingerprint=fingerprint(dataset),
    )
