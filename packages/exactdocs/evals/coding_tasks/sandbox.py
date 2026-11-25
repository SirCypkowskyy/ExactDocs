"""Run a task's commands with no network and with CPU, memory and time limits.

Two sandboxes, the same limits (``Limits``), each saying how it enforced them (``Isolation``):

- ``DockerSandbox`` (``--sandbox docker``, what agent runs use): a throwaway container of a
  pinned slim image with ``--network none``, ``--cpus``, ``--memory`` (swap included),
  ``--pids-limit``, ``--ulimit cpu`` and ``fsize``, a read-only root, no capabilities and
  ``no-new-privileges``. Only the workspace is writable; the prepared environment and its runtime
  are mounted read-only at the paths they were installed at. A command that outlives the wall
  limit is killed with its container.
- ``ProcessSandbox`` (``--sandbox process``, CI's check of the reference solutions): the command
  runs in a new network namespace (``unshare -n``, or ``unshare -rn`` without root) where only an
  unconfigured loopback exists, under ``setrlimit`` limits (CPU seconds, data segment, file size,
  open files), in its own process group, killed at the
  wall limit, with an environment that holds no credential or proxy. It does not hide the host's
  files. Where no network namespace can be made (some CI kernels), it says so (``network: not
  isolated``) and ``require_network_isolation`` refuses to run.
"""

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

MB: Final[int] = 1024 * 1024
"""Bytes in a mebibyte."""
OUTPUT_KEPT: Final[int] = 20_000
"""Characters of a command's output kept (its end)."""
REAP_SECONDS: Final[float] = 10.0
"""How long a killed command, and its output pipe, may take to close."""
DOCKER_IMAGE: Final[str] = (
    "debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0"
)
"""The container image: a slim glibc base (2.41, enough for Node 22's official build), pinned by
digest. The interpreters come from the host's install, mounted read-only."""
SAFE_VARIABLES: Final[tuple[str, ...]] = ("LANG", "LC_ALL", "TZ")
"""Variables of this process passed on; nothing else (no key, no proxy) reaches a command."""
LIMITS_WRAPPER: Final[str] = """\
import os, resource, sys
cpu, data, fsize, nofile = (int(v) for v in sys.argv[1:5])
for which, value in ((resource.RLIMIT_CPU, cpu), (resource.RLIMIT_DATA, data),
                     (resource.RLIMIT_FSIZE, fsize), (resource.RLIMIT_NOFILE, nofile)):
    resource.setrlimit(which, (value, value))
os.execv(sys.argv[6], sys.argv[6:])
"""
"""Sets the limits and replaces itself with the command (``python -c WRAPPER limits -- cmd``),
so no ``preexec_fn`` runs in this threaded process."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class Limits:
    """What one sandboxed command may use."""

    wall_seconds: float = 180.0
    """Elapsed time before it is killed."""
    cpu_seconds: int = 180
    """CPU time of each process (``RLIMIT_CPU``; ``--ulimit cpu`` in a container)."""
    memory_mb: int = 1536
    """Memory: the container's limit (swap included), or each process's data segment."""
    cpus: float = 1.0
    """CPUs of a container (``--cpus``); a process sandbox does not limit cores."""
    processes: int = 256
    """Processes and threads of a container (``--pids-limit``). A process sandbox does not limit
    them: ``RLIMIT_NPROC`` counts every process of the user, not the command's."""
    file_size_mb: int = 64
    """The largest file it may write."""
    open_files: int = 1024
    """Open files per process."""


class Isolation(_Model):
    """How a sandbox enforced each limit, for the report."""

    sandbox: str
    """``process`` or ``docker``."""
    network: str
    """How the network was cut off, or ``not isolated``."""
    cpu: str
    """How CPU was limited."""
    memory: str
    """How memory was limited."""
    time: str
    """How the wall time was limited."""
    filesystem: str
    """What the command could write."""


class SandboxRun(_Model):
    """How one sandboxed command ended."""

    exit_code: int | None
    """Its exit status; ``None`` when it was killed at the wall limit; negative for a signal."""
    output: str
    """Its standard output and error, interleaved, the last ``OUTPUT_KEPT`` characters."""
    seconds: float
    """Elapsed time."""
    timed_out: bool = False
    """It was killed at the wall limit."""


class Sandbox(Protocol):
    """Runs a command in isolation."""

    @property
    def isolation(self) -> Isolation:
        """How it enforces the limits."""
        ...

    async def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        writable: Path,
        readable: Sequence[tuple[Path, Path]],
        env: Mapping[str, str],
        limits: Limits,
    ) -> SandboxRun:
        """Run a command to its end or its wall limit.

        Args:
            command: The command; its executable an absolute path valid inside the sandbox.
            cwd: Its working directory (inside ``writable``).
            writable: The one directory it may write (the workspace).
            readable: ``(source, target)`` directories it may read (the environment, a runtime).
            env: Its whole environment.
            limits: Its limits.

        Returns:
            How it ended.
        """
        ...


def sandbox_environment(
    *, home: Path, path: Sequence[Path], extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The environment of a sandboxed command: a few safe variables, never a key or a proxy.

    Args:
        home: ``HOME`` and ``TMPDIR`` (inside the writable directory).
        path: Directories put first on ``PATH``.
        extra: More variables (``PYTHONPATH``).

    Returns:
        The variables.
    """
    env = {name: os.environ[name] for name in SAFE_VARIABLES if name in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    env |= {
        "PATH": os.pathsep.join([*(str(p) for p in path), "/usr/local/bin", "/usr/bin", "/bin"]),
        "HOME": str(home),
        "TMPDIR": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        "NODE_OPTIONS": "",
        "npm_config_offline": "true",
    }
    return env | dict(extra or {})


def _tail(data: bytes) -> str:
    """Keep the end of a command's output.

    Args:
        data: The output.

    Returns:
        Its last ``OUTPUT_KEPT`` characters, decoded.
    """
    text = data.decode(errors="replace")
    return text if len(text) <= OUTPUT_KEPT else "[...]\n" + text[-OUTPUT_KEPT:]


@cache
def network_namespace() -> tuple[str, ...] | None:
    """Find how this machine lets a process start in a network namespace of its own.

    Returns:
        ``("unshare", "-n")`` for root, ``("unshare", "-rn")`` (a user namespace too) otherwise,
        with ``unshare``'s absolute path; ``None`` when neither works here.
    """
    unshare = shutil.which("unshare")
    if unshare is None:
        return None
    for flags in ("-n", "-rn"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            done = subprocess.run(
                [unshare, flags, "true"], capture_output=True, timeout=10, check=False
            )
            if done.returncode == 0:
                return (unshare, flags)
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessSandbox:
    """A process in a network namespace of its own, under ``setrlimit`` limits and a wall limit."""

    require_network_isolation: bool = False
    """Refuse to run where no network namespace can be made, rather than run with the network."""
    namespace: tuple[str, ...] | None = field(default_factory=network_namespace)
    """The ``unshare`` prefix (``network_namespace``); ``None`` where none can be made."""

    @property
    def isolation(self) -> Isolation:
        """How it enforces the limits.

        Returns:
            The description.
        """
        return Isolation(
            sandbox="process",
            network=(
                f"none: a new network namespace (unshare {self.namespace[1]})"
                if self.namespace
                else "not isolated: no network namespace can be made on this machine"
            ),
            cpu="RLIMIT_CPU per process; cores not limited",
            memory="RLIMIT_DATA per process; processes not limited",
            time="wall limit; the process group is killed",
            filesystem="not hidden; HOME and TMPDIR inside the workspace",
        )

    async def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        writable: Path,
        readable: Sequence[tuple[Path, Path]],
        env: Mapping[str, str],
        limits: Limits,
    ) -> SandboxRun:
        """Run a command in a new network namespace under the limits.

        Args:
            command: The command.
            cwd: Its working directory.
            writable: The directory it is meant to write (not enforced here).
            readable: The directories it reads (not enforced here).
            env: Its whole environment.
            limits: Its limits.

        Returns:
            How it ended.

        Raises:
            RuntimeError: ``require_network_isolation`` and no network namespace can be made.
        """
        del writable, readable  # a process sandbox does not hide the filesystem
        if self.namespace is None and self.require_network_isolation:
            message = "no network namespace can be made here; use --sandbox docker"
            raise RuntimeError(message)
        bounded = [
            sys.executable,
            "-I",
            "-c",
            LIMITS_WRAPPER,
            str(limits.cpu_seconds),
            str(limits.memory_mb * MB),
            str(limits.file_size_mb * MB),
            str(limits.open_files),
            "--",
            *command,
        ]
        full = [*(self.namespace or ()), *bounded]
        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            *full,
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )

        async def kill() -> None:
            """Kill the command's whole process group."""
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

        return await _supervise(process, limits.wall_seconds, kill, started)


async def _supervise(
    process: asyncio.subprocess.Process,
    wall_seconds: float,
    kill: Callable[[], Awaitable[None]],
    started: float,
) -> SandboxRun:
    """Wait for a command to end or reach its wall limit, keeping what it printed either way.

    Args:
        process: The command, its output on a pipe.
        wall_seconds: The wall limit.
        kill: Kills it (and what it started).
        started: When it started (``time.perf_counter``).

    Returns:
        How it ended, with the end of its output.
    """
    kept = bytearray()

    async def read() -> None:
        """Keep the end of the output as it comes."""
        if process.stdout is None:
            return
        while chunk := await process.stdout.read(65536):
            kept.extend(chunk)
            del kept[: max(0, len(kept) - 4 * OUTPUT_KEPT)]

    reader = asyncio.create_task(read())
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), wall_seconds)
    except TimeoutError:
        timed_out = True
        await kill()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), REAP_SECONDS)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(asyncio.shield(reader), REAP_SECONDS)
    reader.cancel()
    return SandboxRun(
        exit_code=None if timed_out else process.returncode,
        output=_tail(bytes(kept)),
        seconds=round(time.perf_counter() - started, 3),
        timed_out=timed_out,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DockerSandbox:
    """A throwaway container with no network, a read-only root and cgroup limits."""

    image: str = DOCKER_IMAGE
    """The image (pinned by digest)."""
    docker: str = "docker"
    """The ``docker`` executable."""

    @property
    def isolation(self) -> Isolation:
        """How it enforces the limits.

        Returns:
            The description.
        """
        return Isolation(
            sandbox="docker",
            network="none: --network none",
            cpu="--cpus and --ulimit cpu",
            memory="--memory, swap included (cgroup)",
            time="wall limit; the container is killed",
            filesystem="read-only root; only the workspace writable; environment read-only",
        )

    async def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        writable: Path,
        readable: Sequence[tuple[Path, Path]],
        env: Mapping[str, str],
        limits: Limits,
    ) -> SandboxRun:
        """Run a command in a new container.

        Args:
            command: The command, its executable at the path it was installed at.
            cwd: Its working directory.
            writable: The workspace, mounted read-write at its own path.
            readable: The environment and the runtime, mounted read-only.
            env: Its whole environment.
            limits: Its limits.

        Returns:
            How it ended.

        Raises:
            RuntimeError: ``docker`` is not on ``PATH``.
        """
        docker = shutil.which(self.docker)
        if docker is None:
            message = "`docker` is not on PATH; use --sandbox process"
            raise RuntimeError(message)
        name = f"exactdocs-coding-task-{uuid.uuid4().hex[:12]}"
        mounts = [f"--volume={writable}:{writable}:rw"]
        mounts += [f"--volume={source}:{target}:ro" for source, target in dict.fromkeys(readable)]
        variables = [f"--env={key}={value}" for key, value in env.items()]
        full = [
            docker,
            "run",
            "--rm",
            f"--name={name}",
            "--network=none",
            f"--cpus={limits.cpus}",
            f"--memory={limits.memory_mb}m",
            f"--memory-swap={limits.memory_mb}m",
            f"--pids-limit={limits.processes}",
            f"--ulimit=cpu={limits.cpu_seconds}",
            f"--ulimit=fsize={limits.file_size_mb * MB}",
            f"--ulimit=nofile={limits.open_files}",
            "--read-only",
            "--tmpfs=/tmp:rw,size=64m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--user={os.getuid()}:{os.getgid()}",
            f"--workdir={cwd}",
            *mounts,
            *variables,
            self.image,
            *command,
        ]
        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            *full,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def kill() -> None:
            """Kill the container."""
            killer = await asyncio.create_subprocess_exec(
                docker,
                "kill",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()

        return await _supervise(process, limits.wall_seconds, kill, started)


def sandbox_named(name: str, *, require_network_isolation: bool) -> Sandbox:
    """Build a sandbox from its name on the command line.

    Args:
        name: ``docker`` or ``process``.
        require_network_isolation: A process sandbox refuses to run where it cannot cut off the
            network.

    Returns:
        The sandbox.

    Raises:
        ValueError: An unknown name.
    """
    if name == "docker":
        return DockerSandbox()
    if name == "process":
        return ProcessSandbox(require_network_isolation=require_network_isolation)
    message = f"unknown sandbox {name!r}; use docker or process"
    raise ValueError(message)
