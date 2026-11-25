"""The task format: a workspace, a prompt, hidden tests, forbidden APIs and two solutions.

A task is a directory ``evals/coding/tasks/<project>/<task>/``:

- ``task.yaml``: the golden-corpus project and version it is for, the environment that pins that
  version (``environments.py``), the prompt, the files the agent is expected to change, the APIs
  that must not appear for this version (on top of the environment's own), and how it relates to
  another version: ``other_version`` and, for a version pair, ``pair`` and ``other_from`` (the
  other task of the pair, whose reference is this task's other-version solution);
- ``workspace/``: the template the agent starts from. Every workspace also gets the
  ecosystem's scaffold (``evals/coding/scaffold/<ecosystem>/``: the test configuration, warnings as
  errors) and the environment's lockfile;
- ``hidden/``: the tests that decide whether the task passes; the agent never sees them;
- ``reference/``: the files of a correct solution for the pinned version, laid over the workspace;
- ``other/``: a solution written for ``other_version`` (unless ``other_from`` names the task whose
  reference it is). It must fail here, and hit at least one forbidden API, so the report names the
  API that does not exist in the pinned version.

Each task becomes one Pydantic Evals case (``task_dataset`` in ``evaluators``).
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from coding_tasks.environments import (
    CODING_DIR,
    ENVIRONMENTS_DIR,
    Environment,
    Forbidden,
    load_environments,
)
from retrieval_eval.golden import Corpus

TASKS_DIR: Final[Path] = CODING_DIR / "tasks"
"""One directory per project, one per task in it."""
SCAFFOLD_DIR: Final[Path] = CODING_DIR / "scaffold"
"""Files every workspace of an ecosystem starts with (``python/``, ``node/``)."""
TASK_FILE: Final[str] = "task.yaml"
"""A task's description, in its directory."""
WORKSPACE: Final[str] = "workspace"
"""A task's template directory."""
HIDDEN: Final[str] = "hidden"
"""A task's hidden tests."""
REFERENCE: Final[str] = "reference"
"""A task's reference solution."""
OTHER: Final[str] = "other"
"""A task's solution for the other version, when it is not its pair's reference."""
DEFAULT_CUTOFF: Final[date] = date(2024, 6, 30)
"""The training cutoff tasks are counted against by default: gpt-oss:120b's model card gives
June 2024 (the end of that month is taken)."""
TASK_ID: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]*$")
"""A task's ID: its directory's name."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class ApiSince(_Model):
    """The release that introduced, removed or deprecated the API the task hinges on."""

    version: str
    """Its version."""
    released: date
    """Its release date."""


class TaskSpec(_Model):
    """``task.yaml``."""

    project: str = Field(min_length=1)
    """The golden-corpus project (``pydantic``, ``zod``)."""
    version: str = Field(min_length=1)
    """The golden-corpus version the project pins (``v1.10.22``): the documentation arms serve it."""
    environment: str = Field(min_length=1)
    """The environment that installs it."""
    title: str = Field(min_length=1)
    """A short title."""
    prompt: str = Field(min_length=1)
    """What the agent is asked to do, as a developer would ask it."""
    files: list[str] = Field(min_length=1)
    """The workspace files the task expects to change."""
    other_version: str = Field(min_length=1)
    """The version the other-version solution is written for."""
    pair: str | None = None
    """The version pair this task belongs to: the same request where the right code differs."""
    other_from: str | None = None
    """The task of the pair whose reference solution is this task's other-version solution."""
    api_since: ApiSince | None = None
    """The release behind the trap (an API added, removed, renamed or deprecated)."""
    forbidden: list[Forbidden] = Field(default_factory=list)
    """APIs that must not appear for this task, on top of the environment's."""
    notes: str = ""
    """What the trap is, for a reader of the task."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingTask:
    """One task, read from its directory."""

    id: str
    """Its directory's name, unique over every project."""
    spec: TaskSpec
    """``task.yaml``."""
    directory: Path
    """Its directory."""
    environment: Environment
    """The environment that pins its version."""
    other_directory: Path
    """The other-version solution's files: ``other/``, or the reference of ``other_from``."""

    @property
    def workspace(self) -> Path:
        """The template directory.

        Returns:
            ``workspace/``.
        """
        return self.directory / WORKSPACE

    @property
    def hidden(self) -> Path:
        """The hidden tests' directory.

        Returns:
            ``hidden/``.
        """
        return self.directory / HIDDEN

    @property
    def reference(self) -> Path:
        """The reference solution's directory.

        Returns:
            ``reference/``.
        """
        return self.directory / REFERENCE

    @property
    def forbidden(self) -> list[Forbidden]:
        """Every API that must not appear for this task.

        Returns:
            The environment's, then the task's own.
        """
        return [*self.environment.spec.forbidden, *self.spec.forbidden]

    @property
    def released(self) -> date:
        """The release date of the pinned version.

        Returns:
            The environment's ``released``.
        """
        return self.environment.spec.released

    def post_cutoff(self, cutoff: date = DEFAULT_CUTOFF) -> bool:
        """Tell whether the pinned version was released after a training cutoff.

        Args:
            cutoff: The cutoff.

        Returns:
            True when it was released after it.
        """
        return self.released > cutoff

    def api_post_cutoff(self, cutoff: date = DEFAULT_CUTOFF) -> bool:
        """Tell whether the change the task hinges on was released after a training cutoff.

        Args:
            cutoff: The cutoff.

        Returns:
            True when ``api_since`` was released after it; False without ``api_since``.
        """
        return self.spec.api_since is not None and self.spec.api_since.released > cutoff


def files_of(directory: Path) -> dict[str, Path]:
    """List the files under a directory by their relative POSIX path.

    Args:
        directory: The directory (missing is empty).

    Returns:
        ``relative path -> file``, sorted.
    """
    if not directory.is_dir():
        return {}
    return {
        p.relative_to(directory).as_posix(): p
        for p in sorted(directory.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def load_tasks(
    root: Path = TASKS_DIR,
    environments_dir: Path = ENVIRONMENTS_DIR,
    corpus: Corpus | None = None,
) -> tuple[list[CodingTask], list[str]]:
    """Read and check every task.

    Args:
        root: The tasks' directory (``<project>/<task>/task.yaml``).
        environments_dir: The environments' directory.
        corpus: The golden corpus, to check each task's project and version; not checked when
            ``None``.

    Returns:
        The valid tasks, by ID, and every problem found.
    """
    environments, problems = load_environments(environments_dir)
    specs: dict[str, tuple[TaskSpec, Path]] = {}
    for path in sorted(root.glob(f"*/*/{TASK_FILE}")):
        task_id = path.parent.name
        try:
            spec = TaskSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as error:
            problems.append(f"task {task_id}: {error}")
            continue
        if task_id in specs:
            problems.append(f"task {task_id}: the ID is used twice")
            continue
        specs[task_id] = (spec, path.parent)
    tasks = []
    for task_id, (spec, directory) in specs.items():
        found = _problems(task_id, spec, directory, specs, environments, corpus)
        if found:
            problems.extend(f"task {task_id}: {p}" for p in found)
            continue
        other = (
            specs[spec.other_from][1] / REFERENCE if spec.other_from else directory / OTHER
        )
        tasks.append(
            CodingTask(
                id=task_id,
                spec=spec,
                directory=directory,
                environment=environments[spec.environment],
                other_directory=other,
            )
        )
    return tasks, problems


def _problems(
    task_id: str,
    spec: TaskSpec,
    directory: Path,
    specs: dict[str, tuple[TaskSpec, Path]],
    environments: dict[str, Environment],
    corpus: Corpus | None,
) -> list[str]:
    """Check one task against the others, its environment and the corpus.

    Args:
        task_id: Its ID.
        spec: Its description.
        directory: Its directory.
        specs: Every task's description and directory, by ID.
        environments: Every environment, by name.
        corpus: The golden corpus, or ``None``.

    Returns:
        The problems.
    """
    problems = []
    if not TASK_ID.match(task_id):
        problems.append("the ID is not lowercase words joined by '-'")
    if directory.parent.name != spec.project:
        problems.append(f"it is under {directory.parent.name}/ but names project {spec.project}")
    environment = environments.get(spec.environment)
    if environment is None:
        problems.append(f"unknown environment {spec.environment}")
    elif spec.version.removeprefix("v") != environment.spec.version and not environment.stand_in:
        problems.append(f"version {spec.version} but {spec.environment} pins another")
    if corpus is not None:
        project = corpus.project(spec.project)
        if project is None:
            problems.append(f"project {spec.project} is not in the golden corpus")
        elif project.commit(spec.version) is None:
            problems.append(f"version {spec.version} is not a pinned version of {spec.project}")
    for name in (WORKSPACE, HIDDEN, REFERENCE):
        if not files_of(directory / name):
            problems.append(f"{name}/ is missing or empty")
    if spec.other_from is not None:
        partner = specs.get(spec.other_from)
        if partner is None:
            problems.append(f"other_from names an unknown task {spec.other_from}")
        elif spec.pair is None or partner[0].pair != spec.pair:
            problems.append(f"other_from {spec.other_from} is not in the same pair")
        elif partner[0].version != spec.other_version:
            problems.append(f"other_version {spec.other_version} but {spec.other_from} pins another")
    elif not files_of(directory / OTHER):
        problems.append("no other-version solution: give other/ or other_from")
    for forbidden in spec.forbidden:
        try:
            re.compile(forbidden.pattern)
        except re.error as error:
            problems.append(f"forbidden {forbidden.api}: {error}")
    workspace = files_of(directory / WORKSPACE)
    reference = files_of(directory / REFERENCE)
    problems.extend(
        f"files names {name}, which neither the workspace nor the reference has"
        for name in spec.files
        if name not in workspace and name not in reference
    )
    return problems
