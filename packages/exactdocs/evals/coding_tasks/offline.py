"""Scripted agent models for the coding tasks: they prove the plumbing, not quality.

Each is a pydantic-ai ``FunctionModel`` built for one task, playing a fixed script with the tools
it is given: it lists the libraries when a documentation tool offers ``list_libraries``, lists the
workspace, writes a fixed solution file by file, runs the tests and ends with a summary.

- ``offline:reference`` writes the task's reference solution (the task passes);
- ``offline:other`` writes the solution for the other version (the task fails, naming the API);
- ``offline:idle`` changes nothing (the task fails).
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from coding_tasks.tasks import CodingTask, files_of
from coding_tasks.workspace import LIST_FILES, RUN_TESTS, WRITE_FILE

REFERENCE: Final[str] = "offline:reference"
"""Writes the reference solution."""
OTHER: Final[str] = "offline:other"
"""Writes the other-version solution."""
IDLE: Final[str] = "offline:idle"
"""Changes nothing."""
OFFLINE_AGENTS: Final[tuple[str, ...]] = (REFERENCE, OTHER, IDLE)
"""Every scripted agent."""
LIST_LIBRARIES: Final[str] = "list_libraries"
"""The documentation tool the script calls first, when the arm has it."""
SUMMARY: Final[str] = "Done: {count} files written."
"""The script's final answer."""
ANSWERS: Final[frozenset[str]] = frozenset({"tool-return", "retry-prompt"})
"""The parts of a request that answer one of the model's tool calls."""


def script(files: Mapping[str, str], tools: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    """The tool calls a scripted agent makes, in order.

    Args:
        files: The files it writes (relative path -> content).
        tools: The names of the tools it has.

    Returns:
        ``(tool, arguments)`` pairs.
    """
    steps: list[tuple[str, dict[str, Any]]] = []
    if LIST_LIBRARIES in tools:
        steps.append((LIST_LIBRARIES, {}))
    steps.append((LIST_FILES, {}))
    steps += [(WRITE_FILE, {"path": path, "content": text}) for path, text in files.items()]
    steps.append((RUN_TESTS, {}))
    return steps


def _answered(messages: Sequence[ModelMessage]) -> int:
    """Count the tool calls already answered in a run.

    Args:
        messages: The run's messages so far.

    Returns:
        Tool returns and retry prompts the model was sent.
    """
    return sum(
        part.part_kind in ANSWERS
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


def scripted(files: Mapping[str, str]) -> FunctionModel:
    """A model that writes `files` into the workspace, then runs the tests.

    Args:
        files: The files (relative path -> content).

    Returns:
        The model.
    """

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Play the next step of the script.

        Args:
            messages: The run so far.
            info: The tools the agent has.

        Returns:
            The next tool call, or the summary once every step was played.
        """
        steps = script(files, [tool.name for tool in info.function_tools])
        done = _answered(messages)
        if done < len(steps):
            name, args = steps[done]
            return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])
        return ModelResponse(parts=[TextPart(content=SUMMARY.format(count=len(files)))])

    return FunctionModel(respond)


def offline_model(name: str, task: CodingTask) -> FunctionModel:
    """The scripted model of a name, for one task.

    Args:
        name: ``offline:reference``, ``offline:other`` or ``offline:idle``.
        task: The task.

    Returns:
        The model.

    Raises:
        ValueError: An unknown name.
    """
    if name == REFERENCE:
        directory = task.reference
    elif name == OTHER:
        directory = task.other_directory
    elif name == IDLE:
        return scripted({})
    else:
        message = f"unknown scripted model {name!r}; the scripted models are {OFFLINE_AGENTS}"
        raise ValueError(message)
    return scripted(
        {path: file.read_text(encoding="utf-8") for path, file in files_of(directory).items()}
    )
