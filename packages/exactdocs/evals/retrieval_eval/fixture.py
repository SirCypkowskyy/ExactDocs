"""Run the suite on the fixture docs repository, imported for real into the app's container."""

from collections.abc import Callable, Sequence
from pathlib import Path

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from fixture_import import LIBRARY, commits, import_fixture
from fixture_repo import DocsRepo
from retrieval_eval.dataset import load_dataset
from retrieval_eval.suite import MODES, EvalMode, SuiteReport, judge, run_modes, with_evaluators


def default_container(data_dir: Path) -> Container:
    """Build the app's container as an instance with this data directory would.

    Args:
        data_dir: An empty data directory.

    Returns:
        The container; its model roles and modes come from the environment like the app's.
    """
    return Container.build(Settings(data_dir=data_dir))


async def run_on_fixture(
    docs_repo: DocsRepo,
    data_dir: Path,
    *,
    build: Callable[[Path], Container] = default_container,
    modes: Sequence[EvalMode] = MODES,
    allow_providers: bool = False,
    baseline: dict[str, float] | None = None,
) -> SuiteReport:
    """Import every fixture version, run the dataset through each mode and apply the gates.

    Args:
        docs_repo: The built fixture repository.
        data_dir: An empty data directory for the container.
        build: Builds the container (tests pass model roles and pipelines here).
        modes: The modes to try.
        allow_providers: Run modes that call a hosted model.
        baseline: recall@5 per mode to compare with; none: no comparison.

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
        )
    return judge(dataset.name, len(dataset.cases), outcomes, baseline or {})
