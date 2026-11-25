"""Run a configured CLI headless: in a container of its own, behind the gate (``DockerRunner``).

Each run gets an internal Docker network of its own (no route out), the gate on that network's
gateway (``gate``: the model provider's host through its proxy, the arm's MCP server through a
forward, nothing else) and a throwaway container:

- the pinned slim image the coding tasks' sandbox uses (``coding_tasks.sandbox.DOCKER_IMAGE``);
- the CLI's install, Node.js, the task's prepared environment and the host's CA certificates
  mounted read-only at the paths they have here; the workspace and the run's own home writable;
- a read-only root, no capabilities, ``no-new-privileges``, CPU, memory and process limits, and a
  wall limit after which the container is killed;
- its environment: what the harness asks, the proxy, and the provider's key passed by name;
- the gate's forwards under one host name, ``SERVICES_HOST``, which the container resolves to
  the gateway (the ExactDocs server is told to answer that name).

The network's gateway is this machine, so a service on this machine that listens on every
interface could be reached from the run too: the runner should run nothing else that listens so.
``ProcessRunner`` runs the CLI as a plain process with the same gate and environment, without a
container: for tests and stand-in CLIs only, and its isolation says so.
"""

import asyncio
import contextlib
import os
import shutil
import signal
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field

from coding_tasks.sandbox import DOCKER_IMAGE
from harness_bench.gate import OpenGate, opened
from harness_bench.harness import Invocation

OUTPUT_LIMIT: Final[int] = 64 * 1024 * 1024
"""The most standard output (a transcript) or error kept from one run."""
STDERR_KEPT: Final[int] = 20_000
"""Characters of standard error kept in the record (its end)."""
CERTIFICATES: Final[Path] = Path("/etc/ssl/certs")
"""The host's CA certificates, mounted read-only (a TLS-intercepting proxy's CA among them)."""
CA_BUNDLE: Final[str] = "ca-certificates.crt"
"""The bundle in ``CERTIFICATES`` the CLIs are pointed at."""
LABEL: Final[str] = "exactdocs.harness-bench=1"
"""The label of every network and container a run creates."""
SERVICES_HOST: Final[str] = "services.harness.internal"
"""The host name a container reaches the gate's forwards by (the gateway's address)."""
CONTAINER_TMP: Final[Path] = Path("/") / "tmp"
"""The container's own temporary folder, a small tmpfs."""
REAP_SECONDS: Final[float] = 20.0
"""How long a killed run, and its output pipes, may take to close."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunLimits:
    """What one CLI run may use."""

    wall_seconds: float = 900.0
    """Elapsed time before it is killed."""
    cpus: float = 2.0
    """CPUs of its container."""
    memory_mb: int = 4096
    """Memory of its container, swap included."""
    processes: int = 1024
    """Processes and threads of its container."""


class CliRun(_Model):
    """How one CLI run ended."""

    exit_code: int | None
    """Its exit status; ``None`` when it was killed at the wall limit."""
    output: str
    """Its standard output: the transcript."""
    stderr: str = ""
    """The end of its standard error."""
    seconds: float
    """Its wall time, container start included."""
    timed_out: bool = False
    """It was killed at the wall limit."""
    tunnels: dict[str, int] = Field(default_factory=dict)
    """Tunnels the gate opened, by ``host:port``."""
    denied: dict[str, int] = Field(default_factory=dict)
    """What the gate refused, by ``host:port``: hosts the CLI tried to reach besides the
    provider's (telemetry, updates, a package registry, a web tool)."""
    forwarded: dict[str, int] = Field(default_factory=dict)
    """Connections forwarded to each service (the arm's MCP server)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Placement:
    """Where a run's files are and what its container sees."""

    workspace: Path
    """The workspace (writable)."""
    home: Path
    """The run's home (writable)."""
    readable: Sequence[tuple[Path, Path]] = ()
    """``(source, target)`` directories mounted read-only: the CLI, Node.js, the environment."""
    path: Sequence[Path] = ()
    """Directories put first on ``PATH``."""


class RunNetwork(Protocol):
    """A run's network: the gate, and a way to run the CLI behind it."""

    @property
    def gate(self) -> OpenGate:
        """The gate: the proxy and what went through it."""
        ...

    def url(self, service: str, path: str = "") -> str:
        """A forwarded service's URL, as the run reaches it.

        Args:
            service: The service's name.
            path: The path on it.

        Returns:
            ``http://<host>:<port><path>``.
        """
        ...

    async def run(self, invocation: Invocation, placement: Placement, limits: RunLimits) -> CliRun:
        """Run the CLI to its end or its wall limit.

        Args:
            invocation: Its command line and environment.
            placement: Its files and mounts.
            limits: Its limits.

        Returns:
            How it ended, with its transcript and what the gate saw.
        """
        ...


class HarnessRunner(Protocol):
    """Gives each run a network of its own and runs the CLI in it."""

    @property
    def isolation(self) -> str:
        """How runs are isolated, for the report."""
        ...

    def network(
        self, *, allowed: Sequence[tuple[str, int]], forwards: Mapping[str, tuple[str, int]]
    ) -> AbstractAsyncContextManager[RunNetwork]:
        """Open a run's network for the block.

        Args:
            allowed: The hosts the gate's proxy tunnels to (the provider's).
            forwards: The services forwarded (the arm's MCP server), by name.

        Returns:
            The network's context.
        """
        ...


def environment(
    invocation: Invocation,
    placement: Placement,
    gate: OpenGate,
    *,
    certificates: bool,
    temporary: Path = CONTAINER_TMP,
) -> dict[str, str]:
    """A run's environment, without the secrets.

    Args:
        invocation: What the harness asks.
        placement: The run's home and ``PATH``.
        gate: The gate (its proxy; its address and ``SERVICES_HOST`` kept off the proxy).
        certificates: The host's CA bundle is mounted.
        temporary: ``TMPDIR``.

    Returns:
        The variables: ``HOME``, ``PATH``, the proxy, the CA bundle, the harness's own.
    """
    gateway = gate.proxy.removeprefix("http://").rpartition(":")[0]
    keep_off = f"{gateway},{SERVICES_HOST},localhost,127.0.0.1"
    env = {
        "HOME": str(placement.home),
        "TMPDIR": str(temporary),
        "PATH": os.pathsep.join(
            [*(str(p) for p in placement.path), "/usr/local/bin:/usr/bin:/bin"]
        ),
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "CI": "1",
        "HTTPS_PROXY": gate.proxy,
        "https_proxy": gate.proxy,
        "NO_PROXY": keep_off,
        "no_proxy": keep_off,
    }
    if certificates:
        bundle = str(CERTIFICATES / CA_BUNDLE)
        env |= {"SSL_CERT_FILE": bundle, "NODE_EXTRA_CA_CERTS": bundle}
    return env | dict(invocation.env)


def secrets_of(invocation: Invocation) -> dict[str, str]:
    """Read the secrets a run passes through from this process's environment.

    Args:
        invocation: The invocation.

    Returns:
        Each secret's value.

    Raises:
        RuntimeError: One is not set.
    """
    missing = [name for name in invocation.secrets if not os.environ.get(name)]
    if missing:
        message = f"{', '.join(missing)} is not set: the run needs the provider's API key"
        raise RuntimeError(message)
    return {name: os.environ[name] for name in invocation.secrets}


def _tail(data: bytes, keep: int) -> str:
    """Decode the end of some output.

    Args:
        data: The output.
        keep: Characters kept.

    Returns:
        The last ``keep`` characters.
    """
    text = data.decode(errors="replace")
    return text if len(text) <= keep else "[...]\n" + text[-keep:]


async def docker(*args: str) -> str:
    """Run a ``docker`` command and return what it printed.

    Args:
        args: Its arguments.

    Returns:
        Its standard output, stripped.

    Raises:
        RuntimeError: It failed, or ``docker`` is not on ``PATH``.
    """
    found = shutil.which("docker")
    if found is None:
        message = "`docker` is not on PATH: each harness run needs a container"
        raise RuntimeError(message)
    process = await asyncio.create_subprocess_exec(
        found, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await process.communicate()
    if process.returncode:
        message = f"docker {' '.join(args[:2])} failed: {err.decode(errors='replace')[-500:]}"
        raise RuntimeError(message)
    return out.decode().strip()


async def _supervise(
    process: asyncio.subprocess.Process, wall_seconds: float, kill: Callable[[], Awaitable[None]]
) -> tuple[bytes, bytes, bool]:
    """Wait for a run to end or reach its wall limit.

    Args:
        process: The run, its output on pipes.
        wall_seconds: The wall limit.
        kill: Kills the run at the wall limit.

    Returns:
        Its standard output and error, and whether it was killed.
    """
    out, err = bytearray(), bytearray()

    async def read(stream: asyncio.StreamReader | None, into: bytearray) -> None:
        """Keep a stream's bytes, up to ``OUTPUT_LIMIT``.

        Args:
            stream: The stream.
            into: Where they go.
        """
        if stream is None:
            return
        while chunk := await stream.read(65536):
            if len(into) < OUTPUT_LIMIT:
                into.extend(chunk[: OUTPUT_LIMIT - len(into)])

    readers = asyncio.gather(read(process.stdout, out), read(process.stderr, err))
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), wall_seconds)
    except TimeoutError:
        timed_out = True
        await kill()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), REAP_SECONDS)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(readers, REAP_SECONDS)
    return bytes(out), bytes(err), timed_out


def _finished(
    gate: OpenGate,
    out: bytes,
    err: bytes,
    *,
    exit_code: int | None,
    started: float,
    timed_out: bool,
) -> CliRun:
    """Record how a run ended.

    Args:
        gate: The gate, with what it saw.
        out: Standard output.
        err: Standard error.
        exit_code: The exit status.
        started: When it started (``time.perf_counter``).
        timed_out: It was killed at the wall limit.

    Returns:
        The run.
    """
    return CliRun(
        exit_code=None if timed_out else exit_code,
        output=out.decode(errors="replace"),
        stderr=_tail(err, STDERR_KEPT),
        seconds=round(time.perf_counter() - started, 3),
        timed_out=timed_out,
        tunnels=dict(gate.log.allowed),
        denied=dict(gate.log.denied),
        forwarded=dict(gate.log.forwarded),
    )


def _identity(home: Path) -> Path:
    """Write the ``passwd`` and ``group`` files a run's container sees: its user, at its home.

    Some CLIs look the user up (Node's ``os.userInfo``); this process's user may have no entry in
    the image.

    Args:
        home: The run's home.

    Returns:
        The folder (next to the home) that holds both files.
    """
    uid, gid = os.getuid(), os.getgid()
    folder = home.parent / f"{home.name}.identity"
    folder.mkdir(parents=True, exist_ok=True)
    name = "root" if uid == 0 else "agent"
    users = [f"{name}:x:{uid}:{gid}:{name}:{home}:/bin/bash"]
    if uid != 0:
        users.insert(0, "root:x:0:0:root:/root:/bin/bash")
    groups = [f"{name}:x:{gid}:"] + ([] if gid == 0 else ["root:x:0:"])
    (folder / "passwd").write_text("\n".join(users) + "\n", encoding="utf-8")
    (folder / "group").write_text("\n".join(groups) + "\n", encoding="utf-8")
    return folder


@dataclass(frozen=True, slots=True, kw_only=True)
class _DockerNetwork:
    """An internal Docker network with the gate on its gateway."""

    name: str
    """The network."""
    gateway: str
    """Its gateway's address, where the gate listens."""
    gate: OpenGate
    """The gate."""
    image: str
    """The container image."""

    def url(self, service: str, path: str = "") -> str:
        """A forwarded service's URL, under ``SERVICES_HOST``.

        Args:
            service: The service's name.
            path: The path on it.

        Returns:
            ``http://services.harness.internal:<port><path>``.
        """
        return f"http://{SERVICES_HOST}:{self.gate.forwards[service][1]}{path}"

    def _command(
        self, invocation: Invocation, placement: Placement, limits: RunLimits, container: str
    ) -> list[str]:
        """The ``docker run`` arguments of a run.

        Args:
            invocation: Its command line and environment.
            placement: Its files and mounts.
            limits: Its limits.
            container: The container's name.

        Returns:
            The arguments (the secrets by name only).
        """
        certificates = (CERTIFICATES / CA_BUNDLE).exists()
        env = environment(invocation, placement, self.gate, certificates=certificates)
        identity = _identity(placement.home)
        mounts = [
            f"--volume={placement.workspace}:{placement.workspace}:rw",
            f"--volume={placement.home}:{placement.home}:rw",
            f"--volume={identity / 'passwd'}:/etc/passwd:ro",
            f"--volume={identity / 'group'}:/etc/group:ro",
        ]
        if certificates:
            mounts.append(f"--volume={CERTIFICATES}:{CERTIFICATES}:ro")
        mounts += [f"--volume={s}:{t}:ro" for s, t in dict.fromkeys(placement.readable)]
        return [
            "run",
            "--rm",
            f"--name={container}",
            f"--label={LABEL}",
            f"--network={self.name}",
            f"--add-host={SERVICES_HOST}:{self.gateway}",
            f"--cpus={limits.cpus}",
            f"--memory={limits.memory_mb}m",
            f"--memory-swap={limits.memory_mb}m",
            f"--pids-limit={limits.processes}",
            "--read-only",
            f"--tmpfs={CONTAINER_TMP}:rw,exec,size=512m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--user={os.getuid()}:{os.getgid()}",
            f"--workdir={placement.workspace}",
            *mounts,
            *(f"--env={key}={value}" for key, value in env.items()),
            *(f"--env={name}" for name in invocation.secrets),  # the value from docker's env
            self.image,
            *invocation.argv,
        ]

    async def run(self, invocation: Invocation, placement: Placement, limits: RunLimits) -> CliRun:
        """Run the CLI in a new container on the network.

        Args:
            invocation: Its command line and environment.
            placement: Its files and mounts.
            limits: Its limits.

        Returns:
            How it ended.
        """
        secrets = secrets_of(invocation)
        container = f"exactdocs-harness-{uuid.uuid4().hex[:12]}"
        argv = self._command(invocation, placement, limits, container)
        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            shutil.which("docker") or "docker",
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **secrets},
        )

        async def kill() -> None:
            """Kill the container."""
            with contextlib.suppress(RuntimeError):
                await docker("kill", container)

        out, err, timed_out = await _supervise(process, limits.wall_seconds, kill)
        return _finished(
            self.gate, out, err, exit_code=process.returncode, started=started, timed_out=timed_out
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DockerRunner:
    """Each run in a container of its own, on an internal network of its own, behind the gate."""

    image: str = DOCKER_IMAGE
    """The container image (pinned by digest)."""

    @property
    def isolation(self) -> str:
        """How runs are isolated.

        Returns:
            The description.
        """
        return (
            "a container per run (read-only root, no capabilities, CPU, memory and process "
            "limits) on an internal Docker network of its own; the only way out is the gate: the "
            "model provider's host through its proxy and the arm's MCP server through a forward"
        )

    @contextlib.asynccontextmanager
    async def network(
        self, *, allowed: Sequence[tuple[str, int]], forwards: Mapping[str, tuple[str, int]]
    ) -> AsyncGenerator[RunNetwork]:
        """Create an internal network, open the gate on its gateway, remove both after the block.

        Args:
            allowed: The hosts the gate's proxy tunnels to.
            forwards: The services forwarded, by name.

        Yields:
            The network.
        """
        name = f"exactdocs-harness-{uuid.uuid4().hex[:12]}"
        await docker("network", "create", "--internal", f"--label={LABEL}", name)
        try:
            gateway = await docker(
                "network", "inspect", "--format", "{{(index .IPAM.Config 0).Gateway}}", name
            )
            async with opened(gateway, allowed=allowed, forwards=forwards) as gate:
                yield _DockerNetwork(name=name, gateway=gateway, gate=gate, image=self.image)
        finally:
            with contextlib.suppress(RuntimeError):
                await docker("network", "rm", name)


@dataclass(frozen=True, slots=True, kw_only=True)
class _ProcessNetwork:
    """The gate on loopback, and the CLI as a plain process."""

    gate: OpenGate
    """The gate."""
    inherit: tuple[str, ...] = ()
    """Variables of this process passed on (a stand-in CLI's interpreter needs its own)."""

    def url(self, service: str, path: str = "") -> str:
        """A forwarded service's URL, on loopback.

        Args:
            service: The service's name.
            path: The path on it.

        Returns:
            ``http://127.0.0.1:<port><path>``.
        """
        host, port = self.gate.forwards[service]
        return f"http://{host}:{port}{path}"

    async def run(self, invocation: Invocation, placement: Placement, limits: RunLimits) -> CliRun:
        """Run the CLI as a process in its own process group.

        Args:
            invocation: Its command line and environment.
            placement: Its files.
            limits: Its limits (only the wall limit applies).

        Returns:
            How it ended.
        """
        secrets = secrets_of(invocation)
        env = environment(
            invocation, placement, self.gate, certificates=False, temporary=placement.home
        )
        env |= {k: os.environ[k] for k in self.inherit if k in os.environ}
        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            *invocation.argv,
            cwd=placement.workspace,
            env=env | secrets,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        async def kill() -> None:
            """Kill the process group."""
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

        out, err, timed_out = await _supervise(process, limits.wall_seconds, kill)
        return _finished(
            self.gate, out, err, exit_code=process.returncode, started=started, timed_out=timed_out
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessRunner:
    """Runs a CLI as a plain process behind the gate on loopback: tests and stand-ins only."""

    inherit: tuple[str, ...] = field(default=("PYTHONPATH", "VIRTUAL_ENV"))
    """Variables of this process passed on."""

    @property
    def isolation(self) -> str:
        """How runs are isolated.

        Returns:
            The description: not isolated.
        """
        return "not isolated: a plain process behind the gate on loopback (tests only)"

    @contextlib.asynccontextmanager
    async def network(
        self, *, allowed: Sequence[tuple[str, int]], forwards: Mapping[str, tuple[str, int]]
    ) -> AsyncGenerator[RunNetwork]:
        """Open the gate on loopback for the block.

        Args:
            allowed: The hosts the gate's proxy tunnels to.
            forwards: The services forwarded, by name.

        Yields:
            The network.
        """
        async with opened("127.0.0.1", allowed=allowed, forwards=forwards) as gate:
            yield _ProcessNetwork(gate=gate, inherit=self.inherit)


def node_home() -> Path | None:
    """Find the Node.js installation the CLIs run with (Gemini CLI is a Node script).

    Returns:
        The installation's root (the parent of its ``bin``), or ``None`` without Node.js.
    """
    node = shutil.which("node")
    if node is None:
        return None
    return Path(node).resolve().parent.parent
