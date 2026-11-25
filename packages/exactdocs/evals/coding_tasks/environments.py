"""The pinned environments of the coding tasks: one lockfile per library version, installed once.

An environment is a directory under ``evals/coding/environments/<name>/`` with an
``environment.yaml`` (the ecosystem, the pinned package and version, its release date, the APIs
that must not appear for it) and a lockfile:

- **python**: ``requirements.txt`` compiled with hashes (``uv pip compile --generate-hashes``,
  from ``requirements.in``); installed with ``uv venv`` and ``uv pip sync --require-hashes`` into
  a virtual environment;
- **node**: ``package.json`` with exact versions and ``package-lock.json``; installed with
  ``npm ci --ignore-scripts``.

Each is installed once into a cache directory named after the lockfile's hash, so a changed
lockfile is a new install and CI can cache the directory by the hashes of the lockfiles. The
tasks' code then runs in the sandbox against that install, which has no network: nothing can be
added while a task runs.

A test fixture may instead give a *stand-in* environment: a ``lib/`` directory of plain modules
put on ``PYTHONPATH`` of the interpreter running the suite (``stand_in``), so the plumbing is
tested without a download.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

type Ecosystem = Literal["python", "node"]
"""How an environment is installed and its tests run."""

CODING_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "coding"
"""The coding tasks' data: ``environments/``, ``scaffold/`` and ``tasks/``."""
ENVIRONMENTS_DIR: Final[Path] = CODING_DIR / "environments"
"""One directory per pinned environment."""
ENVIRONMENT_FILE: Final[str] = "environment.yaml"
"""The description of an environment, in its directory."""
PYTHON_LOCK: Final[str] = "requirements.txt"
"""A Python environment's lockfile (with hashes)."""
PYTHON_INPUT: Final[str] = "requirements.in"
"""What a Python lockfile was compiled from."""
NODE_MANIFEST: Final[str] = "package.json"
"""A Node environment's manifest (exact versions)."""
NODE_LOCK: Final[str] = "package-lock.json"
"""A Node environment's lockfile."""
STAND_IN_LIB: Final[str] = "lib"
"""A stand-in environment's modules, put on ``PYTHONPATH``."""
PREPARED_MARKER: Final[str] = ".prepared.json"
"""Written in an install directory once its install finished: what was installed."""
INSTALL_TIMEOUT: Final[float] = 900.0
"""Seconds one install may take (a cold cache downloads every package)."""
HASH_CHARS: Final[int] = 12
"""Characters of the lockfile hash in an install directory's name."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class Forbidden(_Model):
    """An API that must not appear in code for a version: it does not exist there, or is removed."""

    api: str = Field(min_length=1)
    """The API's name, as the report shows it (``field_validator``, ``z.ipv4()``)."""
    pattern: str = Field(min_length=1)
    """A regular expression (Python syntax) matched against each changed file, comments removed."""
    reason: str = Field(min_length=1)
    """Why it must not appear: when it was added, removed or deprecated."""


class EnvironmentSpec(_Model):
    """``environment.yaml``: what an environment pins."""

    ecosystem: Ecosystem
    """``python`` or ``node``."""
    package: str = Field(min_length=1)
    """The pinned dependency the tasks are about (``pydantic``, ``@tanstack/query-core``)."""
    version: str = Field(min_length=1)
    """Its exact version, as the lockfile pins it."""
    released: date
    """The day that version was published (PyPI, npm)."""
    python: str | None = None
    """The Python version of a ``python`` environment (``uv venv --python``)."""
    forbidden: list[Forbidden] = Field(default_factory=list)
    """APIs that must not appear in code for this version, whatever the task."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    """One pinned environment: its description and its directory."""

    name: str
    """The directory's name (``pydantic-1.10.22``)."""
    spec: EnvironmentSpec
    """What it pins."""
    directory: Path
    """Its directory: ``environment.yaml`` and the lockfile."""

    @property
    def lockfiles(self) -> tuple[str, ...]:
        """The files that pin it, copied into every workspace of a task on it.

        Returns:
            ``requirements.txt`` (and ``requirements.in``), or ``package.json`` and
            ``package-lock.json``; ``()`` for a stand-in.
        """
        if self.stand_in:
            return ()
        if self.spec.ecosystem == "python":
            return tuple(n for n in (PYTHON_INPUT, PYTHON_LOCK) if (self.directory / n).exists())
        return (NODE_MANIFEST, NODE_LOCK)

    @property
    def stand_in(self) -> bool:
        """Whether this is a test fixture's stand-in (modules in ``lib/``, no lockfile).

        Returns:
            True for a stand-in.
        """
        return (self.directory / STAND_IN_LIB).is_dir() and not (
            (self.directory / PYTHON_LOCK).exists() or (self.directory / NODE_LOCK).exists()
        )

    def digest(self) -> str:
        """Hash what decides the install: the lockfiles, the ecosystem and the Python version.

        Returns:
            The first ``HASH_CHARS`` hex digits of their SHA-256 (the forbidden APIs and the
            release date do not change an install, so they are left out).
        """
        sha = hashlib.sha256(f"{self.spec.ecosystem} {self.spec.python}".encode())
        for name in self.lockfiles:
            sha.update(name.encode())
            sha.update((self.directory / name).read_bytes())
        return sha.hexdigest()[:HASH_CHARS]


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedEnvironment:
    """An installed environment: what a sandboxed command runs with."""

    environment: Environment
    """What it pins."""
    root: Path
    """The install directory (a virtual environment's parent, or ``node_modules``' parent)."""
    python: Path | None = None
    """The interpreter of a ``python`` environment."""
    node: Path | None = None
    """The ``node`` executable of a ``node`` environment."""
    node_modules: Path | None = None
    """The installed ``node_modules`` of a ``node`` environment."""
    pythonpath: tuple[Path, ...] = ()
    """Directories put on ``PYTHONPATH`` (a stand-in's modules)."""
    mounts: tuple[tuple[Path, Path], ...] = field(default=())
    """``(source, target)`` directories a container needs read-only: the install and the runtime
    (the Python installation behind the virtual environment, Node's installation)."""

    @property
    def bin_dirs(self) -> tuple[Path, ...]:
        """The directories put first on ``PATH`` inside the sandbox.

        Returns:
            The interpreter's and ``node``'s directories.
        """
        return tuple(p.parent for p in (self.python, self.node) if p is not None)


def load_environments(root: Path = ENVIRONMENTS_DIR) -> tuple[dict[str, Environment], list[str]]:
    """Read every environment under a directory.

    Args:
        root: The environments' directory.

    Returns:
        The environments by name, and the problems found (an invalid description, a lockfile that
        is missing or pins another version).
    """
    found: dict[str, Environment] = {}
    problems: list[str] = []
    for path in sorted(root.glob(f"*/{ENVIRONMENT_FILE}")):
        name = path.parent.name
        try:
            spec = EnvironmentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as error:
            problems.append(f"environment {name}: {error}")
            continue
        environment = Environment(name=name, spec=spec, directory=path.parent)
        problems.extend(f"environment {name}: {p}" for p in lock_problems(environment))
        for forbidden in spec.forbidden:
            try:
                re.compile(forbidden.pattern)
            except re.error as error:
                problems.append(f"environment {name}: forbidden {forbidden.api}: {error}")
        found[name] = environment
    return found, problems


def lock_problems(environment: Environment) -> list[str]:
    """Check that an environment's lockfile pins exactly the version it names.

    Args:
        environment: The environment.

    Returns:
        The problems; none for a stand-in.
    """
    spec, directory = environment.spec, environment.directory
    if environment.stand_in:
        return []
    if spec.ecosystem == "python":
        lock = directory / PYTHON_LOCK
        if not lock.exists():
            return [f"no {PYTHON_LOCK}"]
        text = lock.read_text(encoding="utf-8")
        pinned = f"\n{spec.package}=={spec.version} "
        problems = [] if pinned in f"\n{text}" else [f"{PYTHON_LOCK} does not pin {pinned.strip()}"]
        if "--hash=sha256:" not in text:
            problems.append(f"{PYTHON_LOCK} has no hashes")
        if spec.python is None:
            problems.append("a python environment names its Python version (`python`)")
        return problems
    problems = [f"no {n}" for n in (NODE_MANIFEST, NODE_LOCK) if not (directory / n).exists()]
    if problems:
        return problems
    manifest = json.loads((directory / NODE_MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("dependencies", {}).get(spec.package) != spec.version:
        problems.append(f"{NODE_MANIFEST} does not pin {spec.package} {spec.version} exactly")
    lock = json.loads((directory / NODE_LOCK).read_text(encoding="utf-8"))
    locked = lock.get("packages", {}).get(f"node_modules/{spec.package}", {})
    if locked.get("version") != spec.version or not locked.get("integrity"):
        problems.append(f"{NODE_LOCK} does not lock {spec.package} {spec.version} with integrity")
    return problems


def default_cache_dir() -> Path:
    """Where environments are installed: ``$XDG_CACHE_HOME/exactdocs/coding-tasks`` (``~/.cache``).

    Returns:
        The directory (it may not exist yet).
    """
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "exactdocs" / "coding-tasks"


def stand_in(environment: Environment) -> PreparedEnvironment:
    """Prepare a test fixture's stand-in: its modules on the suite's own interpreter.

    Args:
        environment: A stand-in environment (``lib/``, no lockfile).

    Returns:
        The interpreter running this process, with ``lib/`` on ``PYTHONPATH``.

    Raises:
        ValueError: The environment is not a Python stand-in.
    """
    if not environment.stand_in or environment.spec.ecosystem != "python":
        message = f"environment {environment.name} is not a Python stand-in"
        raise ValueError(message)
    python = Path(sys.executable)
    lib = environment.directory / STAND_IN_LIB
    return PreparedEnvironment(
        environment=environment,
        root=environment.directory,
        python=python,
        pythonpath=(lib,),
        mounts=((lib, lib), *_runtime_mounts(python)),
    )


async def prepare(environment: Environment, cache_dir: Path) -> PreparedEnvironment:
    """Install an environment from its lockfile, once per lockfile hash.

    Args:
        environment: The environment.
        cache_dir: Where installs are kept (``default_cache_dir``).

    Returns:
        The installed environment; an install made earlier from the same lockfile is reused.

    Raises:
        RuntimeError: The installer (``uv``, ``npm``) is missing or failed.
    """
    if environment.stand_in:
        return stand_in(environment)
    root = cache_dir / f"{environment.name}-{environment.digest()}"
    if not (root / PREPARED_MARKER).exists():
        await _install(environment, root)
    return _prepared(environment, root)


def _prepared(environment: Environment, root: Path) -> PreparedEnvironment:
    """Describe a finished install.

    Args:
        environment: The environment.
        root: Its install directory.

    Returns:
        The prepared environment.

    Raises:
        RuntimeError: ``node`` is not on ``PATH`` (a Node environment).
    """
    if environment.spec.ecosystem == "python":
        python = root / ".venv" / "bin" / "python"
        return PreparedEnvironment(
            environment=environment,
            root=root,
            python=python,
            mounts=((root, root), *_runtime_mounts(python)),
        )
    node = _which("node")
    return PreparedEnvironment(
        environment=environment,
        root=root,
        node=node,
        node_modules=root / "node_modules",
        mounts=((root, root), *_runtime_mounts(node)),
    )


def _runtime_mounts(executable: Path) -> tuple[tuple[Path, Path], ...]:
    """The directories an interpreter needs inside a container, at the paths it expects.

    A virtual environment's ``python`` is a link to the installation named in ``pyvenv.cfg``
    (``home``), itself often a link (uv's ``cpython-3.12-...`` to ``cpython-3.12.13-...``), so
    the installation is mounted at both paths.

    Args:
        executable: A ``python`` (of a virtual environment or not) or ``node``.

    Returns:
        ``(source, target)`` pairs: the installation's directory, at its real path and at the
        path the executable reaches it by.
    """
    real = executable.resolve().parent.parent
    targets = {real}
    config = executable.parent.parent / "pyvenv.cfg"
    if config.exists():
        for line in config.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home":
                targets.add(Path(value.strip()).parent)
    return tuple((real, target) for target in sorted(targets))


async def _install(environment: Environment, root: Path) -> None:
    """Install an environment into a new directory, then move it into place.

    Args:
        environment: The environment.
        root: The install directory to create.

    Raises:
        RuntimeError: An installer is missing or failed.
    """
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{environment.name}-", dir=root.parent))
    try:
        if environment.spec.ecosystem == "python":
            uv = _which("uv")
            venv = staging / ".venv"
            python = environment.spec.python or ""
            await _run([str(uv), "venv", "--quiet", "--python", python, str(venv)])
            lock = environment.directory / PYTHON_LOCK
            await _run(
                [
                    *(str(uv), "pip", "sync", "--quiet", "--require-hashes"),
                    *("--python", str(venv / "bin" / "python"), str(lock)),
                ]
            )
        else:
            npm = _which("npm")
            for name in (NODE_MANIFEST, NODE_LOCK):
                shutil.copy2(environment.directory / name, staging / name)
            await _run(
                [str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--loglevel=error"],
                cwd=staging,
            )
        marker = {"environment": environment.name, "digest": environment.digest()}
        (staging / PREPARED_MARKER).write_text(json.dumps(marker) + "\n", encoding="utf-8")
        if root.exists():  # another process finished the same install first
            shutil.rmtree(staging, ignore_errors=True)
            return
        staging.rename(root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


async def _run(command: Sequence[str], cwd: Path | None = None) -> None:
    """Run an installer.

    Args:
        command: The command, its executable an absolute path.
        cwd: Its working directory.

    Raises:
        RuntimeError: It failed or took longer than ``INSTALL_TIMEOUT``.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), INSTALL_TIMEOUT)
    except TimeoutError:
        process.kill()
        await process.wait()
        message = f"{Path(command[0]).name} took longer than {INSTALL_TIMEOUT:.0f} s"
        raise RuntimeError(message) from None
    if process.returncode != 0:
        text = output.decode(errors="replace")[-2000:]
        message = f"{' '.join(Path(c).name if i == 0 else c for i, c in enumerate(command))}: {text}"
        raise RuntimeError(message)


def _which(name: str) -> Path:
    """Find an executable on ``PATH``.

    Args:
        name: Its name.

    Returns:
        Its absolute path.

    Raises:
        RuntimeError: It is not on ``PATH``.
    """
    found = shutil.which(name)
    if found is None:
        message = f"`{name}` is not on PATH; the coding tasks need it to install and run"
        raise RuntimeError(message)
    return Path(found).absolute()
