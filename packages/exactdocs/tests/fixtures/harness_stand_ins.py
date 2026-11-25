"""Stand-ins for the harness benchmark's quick tests (pytest and behave): no container, no model.

- ``StandInHarness`` is the Claude Code adapter with its CLI replaced by the stand-in CLI
  (``harness_stand_in_cli.py``): the configuration, the command line and the transcript parser
  are Claude Code's own. The stand-in
  writes the reference solution of the task the prompt names when it has a documentation server,
  and the solution for the other version when it has none, so the arms differ.
- ``StandInEndpoints`` serves the agent benchmark's stand-in documentation server over HTTP on
  loopback (FastMCP and uvicorn, in this process) for every arm but ``none``.
- The runs go through ``harness_bench.container.ProcessRunner``: the gate on loopback, the CLI a
  plain process.
"""

import asyncio
import contextlib
import dataclasses
import re
import sys
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import uvicorn

from agent_bench.arms import NONE, Arm
from agent_bench.harness import RetrievalConfig
from agent_bench_stand_ins import docs_server
from coding_tasks.tasks import CodingTask
from harness_bench.claude_code import ClaudeCode
from harness_bench.endpoints import Endpoint, free_port, listed_tools, wait_ready
from harness_bench.harness import CliRelease, HarnessRun, Invocation
from harness_bench.transcript import Transcript

STAND_IN_CLI: Final[Path] = Path(__file__).with_name("harness_stand_in_cli.py")
"""The stand-in CLI."""
VERSION: Final[re.Pattern[str]] = re.compile(r"at version (\S+?)\.(?:\s|$)")
"""The version a prompt names."""
MODEL: Final[str] = "anthropic:claude-stand-in"
"""The stand-in's model name (its provider's key must be set; nothing reaches it)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StandInHarness:
    """Claude Code's adapter, its CLI replaced by the stand-in."""

    solutions: Mapping[str, tuple[Path, Path]] = field(default_factory=dict)
    """By pinned version: the reference solution's folder and the other version's."""
    name: str = "stand-in"
    """Its name."""
    release: CliRelease = field(default_factory=lambda: ClaudeCode().release)
    """Claude Code's pinned release (the stand-in installs nothing)."""
    providers: frozenset[str] = frozenset({"anthropic"})
    """Claude Code's providers."""
    web_tools: str = "the stand-in has none"
    """It has no web tool."""
    limits: str = "none"
    """It takes no limit."""

    def configure(self, run: HarnessRun, executable: Path) -> Invocation:
        """Configure as Claude Code does, then run the stand-in instead.

        Args:
            run: The run.
            executable: Ignored (the stand-in runs with this interpreter).

        Returns:
            The invocation, with the solution to write in ``STAND_IN_SOLUTION``.
        """
        invocation = ClaudeCode().configure(run, executable)
        env = dict(invocation.env)
        version = VERSION.search(run.prompt)
        if version and version[1] in self.solutions:
            reference, other = self.solutions[version[1]]
            env["STAND_IN_SOLUTION"] = str(reference if run.mcp else other)
        argv = (sys.executable, str(STAND_IN_CLI), *invocation.argv[1:])
        return dataclasses.replace(invocation, argv=argv, env=env)

    def parse(self, output: str, run: HarnessRun) -> Transcript:
        """Parse as Claude Code does.

        Args:
            output: The stand-in's transcript.
            run: The run.

        Returns:
            The transcript.
        """
        return ClaudeCode().parse(output, run)


def solutions(tasks: Mapping[str, CodingTask]) -> dict[str, tuple[Path, Path]]:
    """Each stand-in task's solutions, by the version it pins.

    Args:
        tasks: The stand-in tasks.

    Returns:
        ``version -> (reference, other)``.
    """
    return {t.spec.version: (t.reference, t.other_directory) for t in tasks.values()}


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- it records servers
class StandInEndpoints:
    """The stand-in documentation server over HTTP on loopback, for every arm but ``none``."""

    described: dict[str, dict[str, str]] = field(default_factory=dict)
    """What ran for each arm."""

    @contextlib.asynccontextmanager
    async def endpoint(
        self, arm: Arm, config: RetrievalConfig | None
    ) -> AsyncGenerator[Endpoint | None]:
        """Serve the stand-in server for the block.

        Args:
            arm: The arm.
            config: Its configuration (unused).

        Yields:
            The endpoint; ``None`` for ``none``.
        """
        del config
        if arm.name == NONE:
            yield None
            return
        port = free_port()
        app = docs_server().http_app(path="/mcp")
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
        )
        task = asyncio.create_task(server.serve())
        try:
            await wait_ready(f"http://127.0.0.1:{port}/mcp")
            tools = tuple(await listed_tools(f"http://127.0.0.1:{port}/mcp", {}))
            self.described[arm.name] = {"server": "stand-in docs", "tools": ", ".join(tools)}
            yield Endpoint(
                name=arm.name.replace("-", "_"),
                address=("127.0.0.1", port),
                headers={"Authorization": "Bearer stand-in-token"},
                tools=tools,
            )
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
