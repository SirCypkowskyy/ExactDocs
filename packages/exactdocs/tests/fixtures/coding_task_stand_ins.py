"""Stand-in coding tasks for the quick tests (pytest and behave): no download, no model.

A tiny library ``demo`` in two versions (``coding_tasks/environments/demo-v1`` and ``demo-v2``,
plain modules put on ``PYTHONPATH`` of the suite's own interpreter) renames its validator
decorator the way Pydantic 2 did, and a version pair of tasks (``demo-validator-v1`` and
``-v2``) asks for one. The corpus is the agent benchmark's stand-in (project ``demo``, versions
``v1`` and ``v2``), so the stand-in documentation tools serve both arms.
"""

from pathlib import Path
from typing import Final

from agent_bench_stand_ins import golden
from coding_tasks.environments import PreparedEnvironment, stand_in
from coding_tasks.tasks import CodingTask, load_tasks
from retrieval_eval.golden import Corpus

STAND_INS: Final[Path] = Path(__file__).parent / "coding_tasks"
"""The stand-in tasks and environments."""
V1: Final[str] = "demo-validator-v1"
"""The task that pins demo 1.0."""
V2: Final[str] = "demo-validator-v2"
"""The task that pins demo 2.0."""


def stand_in_tasks() -> tuple[dict[str, CodingTask], Corpus]:
    """Read the stand-in tasks.

    Returns:
        The tasks by ID, and the stand-in corpus.
    """
    corpus, _ = golden()
    tasks, problems = load_tasks(STAND_INS / "tasks", STAND_INS / "environments", corpus)
    assert not problems, problems
    return {t.id: t for t in tasks}, corpus


def prepared(tasks: dict[str, CodingTask]) -> dict[str, PreparedEnvironment]:
    """Prepare the stand-in environments (nothing to install).

    Args:
        tasks: The stand-in tasks.

    Returns:
        Each environment, by name.
    """
    return {t.environment.name: stand_in(t.environment) for t in tasks.values()}
