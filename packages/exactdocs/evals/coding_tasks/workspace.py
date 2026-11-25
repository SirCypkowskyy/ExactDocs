"""The agent's workspace tools: list, read and write the workspace's files, and run its tests.

Every path is relative to the workspace and must stay inside it; the environment link
(``node_modules``), the sandbox's home and the lockfile are off limits: the dependencies are
pinned and installed, nothing can be added. ``run_tests`` runs the workspace's own tests (not the
hidden ones) in the same sandbox, with the same limits, as the grading. Each call is recorded in
the run's ``Recorder`` like the documentation tools' calls.
"""

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset

from agent_bench.harness import ARGS_SHOWN, Recorder, ToolCall
from coding_tasks.grading import IGNORED, Runner, workspace_files
from coding_tasks.tasks import CodingTask

LIST_FILES: Final[str] = "list_files"
"""Lists the workspace's files."""
READ_FILE: Final[str] = "read_file"
"""Reads one file."""
WRITE_FILE: Final[str] = "write_file"
"""Writes one whole file."""
RUN_TESTS: Final[str] = "run_tests"
"""Runs the workspace's own tests in the sandbox."""
WORKSPACE_TOOLS: Final[tuple[str, ...]] = (LIST_FILES, READ_FILE, WRITE_FILE, RUN_TESTS)
"""Every workspace tool."""
READ_LIMIT: Final[int] = 60_000
"""Characters of a file ``read_file`` returns."""
WRITE_LIMIT: Final[int] = 200_000
"""The longest file ``write_file`` writes."""
OUTPUT_SHOWN: Final[int] = 6_000
"""Characters of the test output ``run_tests`` returns (the end)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Workspace:
    """One task's workspace, as the agent sees it."""

    root: Path
    """The workspace directory."""
    task: CodingTask
    """The task."""
    runner: Runner
    """Runs its tests in the sandbox."""

    @property
    def protected(self) -> frozenset[str]:
        """Files the agent may read but not write: the lockfiles.

        Returns:
            Their relative paths.
        """
        return frozenset(self.task.environment.lockfiles)

    def resolve(self, path: str) -> tuple[str, Path]:
        """Turn a path the model gave into a workspace file.

        Args:
            path: Relative to the workspace (a leading ``./`` or ``/`` is dropped).

        Returns:
            The normalized relative path and the file.

        Raises:
            ModelRetry: The path leaves the workspace or names what the tools do not show.
        """
        relative = path.strip().removeprefix("./").lstrip("/")
        target = (self.root / relative).resolve()
        root = self.root.resolve()
        if not relative or (target != root and root not in target.parents):
            message = f"{path!r} is not a file inside the workspace"
            raise ModelRetry(message)
        parts = target.relative_to(root).parts
        if IGNORED & set(parts):
            message = f"{path!r} is not part of the workspace's code"
            raise ModelRetry(message)
        return target.relative_to(root).as_posix(), target

    def toolset(self) -> FunctionToolset[Recorder]:
        """The workspace tools, recording each call.

        Returns:
            ``list_files``, ``read_file``, ``write_file`` and ``run_tests``.
        """

        async def list_files(ctx: RunContext[Recorder]) -> list[str]:
            """List every file of the project's workspace, by path.

            Args:
                ctx: The run.

            Returns:
                The paths, relative to the workspace.
            """
            return await _recorded(ctx, LIST_FILES, {}, lambda: _list(self))

        async def read_file(ctx: RunContext[Recorder], path: str) -> str:
            """Read one file of the workspace.

            Args:
                ctx: The run.
                path: The file's path, relative to the workspace (from `list_files`).

            Returns:
                The file's content.
            """
            return await _recorded(ctx, READ_FILE, {"path": path}, lambda: _read(self, path))

        async def write_file(ctx: RunContext[Recorder], path: str, content: str) -> str:
            """Write one whole file of the workspace, creating or replacing it.

            Args:
                ctx: The run.
                path: The file's path, relative to the workspace.
                content: The file's complete new content.

            Returns:
                What was written.
            """
            args = {"path": path, "content": content}
            return await _recorded(ctx, WRITE_FILE, args, lambda: _write(self, path, content))

        async def run_tests(ctx: RunContext[Recorder]) -> str:
            """Run the project's own tests (and, for TypeScript, its type check) in a sandbox.

            Args:
                ctx: The run.

            Returns:
                Whether they passed, and the end of their output.
            """
            return await _recorded(ctx, RUN_TESTS, {}, lambda: _test(self))

        return FunctionToolset[Recorder](
            [list_files, read_file, write_file, run_tests], id="workspace"
        )


async def _recorded[T](
    ctx: RunContext[Recorder],
    name: str,
    args: dict[str, str],
    call: Callable[[], Awaitable[T]],
) -> T:
    """Run a tool and record the call in the run's deps.

    Args:
        ctx: The run.
        name: The tool.
        args: Its arguments.
        call: Runs it.

    Returns:
        What the tool returned.
    """
    shown = json.dumps(args, ensure_ascii=False, sort_keys=True)[:ARGS_SHOWN]
    started = time.perf_counter()
    try:
        result = await call()
    except ModelRetry as error:
        seconds = round(time.perf_counter() - started, 3)
        ctx.deps.calls.append(ToolCall(name=name, args=shown, seconds=seconds, error=str(error)))
        raise
    seconds = round(time.perf_counter() - started, 3)
    ctx.deps.calls.append(ToolCall(name=name, args=shown, seconds=seconds))
    return result


async def _list(workspace: Workspace) -> list[str]:
    """List the workspace's files.

    Args:
        workspace: The workspace.

    Returns:
        Their relative paths.
    """
    return list(workspace_files(workspace.root))


async def _read(workspace: Workspace, path: str) -> str:
    """Read a file.

    Args:
        workspace: The workspace.
        path: The file.

    Returns:
        Its content, cut at ``READ_LIMIT`` characters.

    Raises:
        ModelRetry: It is not a file of the workspace.
    """
    relative, target = workspace.resolve(path)
    if not target.is_file():
        message = f"there is no file {relative}; `list_files` lists them"
        raise ModelRetry(message)
    text = target.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= READ_LIMIT else text[:READ_LIMIT] + "\n[... cut]"


async def _write(workspace: Workspace, path: str, content: str) -> str:
    """Write a file.

    Args:
        workspace: The workspace.
        path: The file.
        content: Its new content.

    Returns:
        What was written.

    Raises:
        ModelRetry: The file is protected or outside the workspace, or the content too long.
    """
    relative, target = workspace.resolve(path)
    if relative in workspace.protected:
        message = f"{relative} pins the project's dependencies and cannot be changed"
        raise ModelRetry(message)
    if len(content) > WRITE_LIMIT:
        message = f"a file may hold at most {WRITE_LIMIT} characters"
        raise ModelRetry(message)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {relative} ({len(content.encode())} bytes)"


async def _test(workspace: Workspace) -> str:
    """Run the workspace's own tests.

    Args:
        workspace: The workspace.

    Returns:
        ``passed`` or ``failed`` with the counts, then the end of the output.
    """
    outcome = await workspace.runner.run_tests(workspace.root, hidden=False)
    if outcome.timed_out:
        head = "failed: killed at the time limit"
    elif outcome.passed:
        head = f"passed: {outcome.tests} tests"
    else:
        head = f"failed: {outcome.failed} of {outcome.tests} tests failed"
        if outcome.typecheck is False:
            head += "; the type check failed"
    return f"{head}\n\n{outcome.output[-OUTPUT_SHOWN:]}"
