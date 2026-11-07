"""Run the suite on the fixture docs repository, imported for real into the app's container."""

from collections.abc import Callable, Sequence
from pathlib import Path

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.models import ModelRole
from exactdocs.retrieval.use_cases import NoModelRoles
from fixture_import import LIBRARY, commits, import_fixture
from fixture_repo import DocsRepo
from retrieval_eval.dataset import fingerprint, load_dataset
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


async def run_on_fixture(
    docs_repo: DocsRepo,
    data_dir: Path,
    *,
    build: Callable[[Path], Container] = model_free_container,
    modes: Sequence[EvalMode] = MODES,
    allow_providers: bool = False,
    local_roles: frozenset[ModelRole] = frozenset(),
    comparison: Comparison | None = None,
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

    Returns:
        The judged report.
    """
    dataset = with_evaluators(load_dataset())
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
        comparison or Comparison(),
        fingerprint=fingerprint(dataset),
    )
