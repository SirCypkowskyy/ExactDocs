"""Stand-in models that run the whole benchmark with no provider (pydantic-ai ``FunctionModel``).

They prove the plumbing, not answer quality: the agents drive the real MCP tools the way a
careful agent would (find the library, search the asked version, read the top section), or, with
no tools (the ``none`` arm), say they do not know; ``offline:think`` also returns thinking, as a
thinking model does. The judge grades by word overlap with the facts.
``just agent-bench run --offline`` uses them.
"""

import json
import re
from collections.abc import Sequence
from typing import Any, Final

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionDef, FunctionModel

from agent_bench.judge import PROMPT_HEAD, Verdict

OFFLINE_THINKING: Final[str] = "offline:think"
"""The stand-in agent that thinks before each step (then reads, as ``offline:read``)."""
OFFLINE_AGENTS: Final[tuple[str, ...]] = ("offline:search", "offline:read", OFFLINE_THINKING)
"""The stand-in agents: answer from the search snippets, read the top section first, or think
and read; with no tools, each says it does not know."""
THOUGHT: Final[str] = "Find the library, then search the version the project uses. " * 4
"""The stand-in thinking text: its output tokens hold it, as a thinking model's do on Ollama."""
OFFLINE_JUDGE: Final[str] = "offline"
"""The stand-in judge."""
SEARCH_LIMIT: Final[int] = 3
"""Results the stand-in agents ask for."""
ANSWER_CHARS: Final[int] = 1500
"""The most characters of documentation a stand-in answer quotes."""
NOT_COVERED: Final[str] = "The documentation of {version} does not cover this."
"""A stand-in agent's answer when the search finds nothing."""
DO_NOT_KNOW: Final[str] = "I do not know what {title} {version} does here."
"""A stand-in agent's answer with no tools (the ``none`` arm)."""
REFUSALS: Final[re.Pattern[str]] = re.compile(
    r"does not cover|doesn't cover|not documented|no documentation|does not (?:say|mention)"
    r"|(?:do not|don't) know",
    re.IGNORECASE,
)
"""What the stand-in judge takes as an answer saying the documentation does not cover it."""
WORD: Final[re.Pattern[str]] = re.compile(r"[\w.]{4,}")
"""A word the stand-in judge looks for (four characters or more)."""
PROMPT_LINE: Final[re.Pattern[str]] = re.compile(
    r"uses (?P<title>.+) at version (?P<version>\S+)\."
)
"""The dependency line of ``harness.PROMPT``."""


def _prompt(messages: Sequence[ModelMessage]) -> str:
    """Read the run's user prompt.

    Args:
        messages: The run's messages so far.

    Returns:
        The prompt text.
    """
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    return ""


def _returns(messages: Sequence[ModelMessage]) -> dict[str, Any]:
    """The latest result of each tool in the run.

    Args:
        messages: The run's messages so far.

    Returns:
        Tool name to its content.
    """
    return {
        part.tool_name: part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }


def _step(messages: list[ModelMessage], info: AgentInfo, *, read: bool) -> TextPart | ToolCallPart:
    """Take a stand-in agent's next step from what the tools returned so far.

    Args:
        messages: The run so far.
        info: The run's tools.
        read: Read the top section with ``read_chunk`` before answering.

    Returns:
        A tool call, or the answer; with no tools, that it does not know.
    """
    prompt = _prompt(messages)
    asked = PROMPT_LINE.search(prompt)
    title, version = (asked["title"], asked["version"]) if asked else ("", "")
    if not info.function_tools:
        return TextPart(DO_NOT_KNOW.format(title=title, version=version))
    query = prompt.split("\n\n", 1)[-1]
    returns = _returns(messages)
    if "list_libraries" not in returns:
        return ToolCallPart("list_libraries", {})
    libraries = returns["list_libraries"].get("libraries", [])
    library = next((x["id"] for x in libraries if x["title"].casefold() == title.casefold()), "")
    if "search_docs" not in returns:
        args = {"library": library, "ref": version, "query": query, "limit": SEARCH_LIMIT}
        return ToolCallPart("search_docs", args)
    results = returns["search_docs"].get("results", [])
    if not results:
        return TextPart(NOT_COVERED.format(version=version))
    if read and "read_chunk" not in returns:
        return ToolCallPart("read_chunk", {"chunk_id": results[0]["chunk_id"]})
    text = returns["read_chunk"]["content"] if read else "\n\n".join(r["snippet"] for r in results)
    return TextPart(text[:ANSWER_CHARS])


def _agent(*, read: bool, think: bool) -> FunctionDef:
    """Build a stand-in agent's script.

    Args:
        read: Read the top section with ``read_chunk`` before answering.
        think: Return a thinking part before each step, as a thinking model does.

    Returns:
        The ``FunctionModel`` function.
    """

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Take the next step.

        Args:
            messages: The run so far.
            info: The run's tools.

        Returns:
            The step, after the thinking when the stand-in thinks.
        """
        step = _step(messages, info, read=read)
        return ModelResponse(parts=[ThinkingPart(THOUGHT), step] if think else [step])

    return script


def offline_agent(name: str) -> FunctionModel:
    """Build a stand-in agent model.

    Args:
        name: One of ``OFFLINE_AGENTS``.

    Returns:
        The model.

    Raises:
        ValueError: Not a stand-in agent's name.
    """
    if name not in OFFLINE_AGENTS:
        message = f"{name!r} is not one of {', '.join(OFFLINE_AGENTS)}"
        raise ValueError(message)
    think = name == OFFLINE_THINKING
    return FunctionModel(_agent(read=think or name.endswith(":read"), think=think), model_name=name)


def _words(text: str) -> set[str]:
    """The words the stand-in judge compares.

    Args:
        text: An answer or a fact.

    Returns:
        Its words of four characters or more, lowercased, without the dots that end a sentence.
    """
    return {w.strip(".").lower() for w in WORD.findall(text)}


def offline_verdict(case: dict[str, Any]) -> Verdict:
    """Grade by word overlap: the share of the facts most of whose words the answer contains.

    Args:
        case: What ``judge.judge_prompt`` sends, parsed.

    Returns:
        The verdict: an answer saying the documentation does not cover it is refused (right for
        an unanswerable case), and an unanswerable case answered anyway is wrong.
    """
    answer = case["answer"]
    refused = bool(REFUSALS.search(answer))
    if not case["facts"]:
        grade = "refused" if refused else "wrong"
        return Verdict(grade=grade, wrong_version=False, reason="stand-in: unanswerable case")
    if refused:
        return Verdict(grade="refused", wrong_version=False, reason="stand-in: says not covered")
    words = _words(answer)
    found = 0
    for fact in case["facts"]:
        wanted = _words(fact)
        found += bool(wanted) and len(wanted & words) * 2 >= len(wanted)
    grade = "correct" if found == len(case["facts"]) else "partially_correct" if found else "wrong"
    reason = f"stand-in: {found} of {len(case['facts'])} facts found by word overlap"
    return Verdict(grade=grade, wrong_version=False, reason=reason)


def offline_judge() -> FunctionModel:
    """Build the stand-in judge model: it answers through the output tool with ``offline_verdict``.

    Returns:
        The model.
    """

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Grade the answer in the prompt.

        Args:
            messages: The run: the judge's prompt.
            info: The run's output tool.

        Returns:
            The call of the output tool with the verdict.
        """
        case = json.loads(_prompt(messages).removeprefix(PROMPT_HEAD))
        verdict = offline_verdict(case).model_dump(mode="json")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, verdict)])

    return FunctionModel(script, model_name=OFFLINE_JUDGE)
