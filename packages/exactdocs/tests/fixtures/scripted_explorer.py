"""Stand-in LLMs for the agentic mode (pytest, behave and the eval suite): no provider is called.

Each is a pydantic-ai ``FunctionModel`` that drives harness Code Mode as an agent would: it calls
``run_code`` with a snippet that uses the read functions, then answers with chunk IDs taken from
what the snippet returned. ``ScriptedModels`` is a ``ModelFactory`` whose chat model is one of
them, so a container built with it runs the real ``agentic`` pipeline end to end.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from exactdocs.retrieval.errors import ProviderUnsupportedError
from exactdocs.retrieval.models import ModelCheck, ModelRole, ProviderProfile
from exactdocs.retrieval.ports.driven import Reranker

RUN_CODE = "run_code"
"""Code Mode's one model-visible tool."""

type Script = Callable[[list[ModelMessage], AgentInfo], ModelResponse]
"""What a ``FunctionModel`` calls for each model request."""


def question(messages: Sequence[ModelMessage]) -> str:
    """Read the question: the run's user prompt.

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


def code_results(messages: Sequence[ModelMessage]) -> list[Any]:
    """Collect what each ``run_code`` call returned, in order.

    Args:
        messages: The run's messages so far.

    Returns:
        The snippets' values (JSON already parsed).
    """
    found = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart) and part.tool_name == RUN_CODE:
                    content = part.content
                    found.append(json.loads(content) if isinstance(content, str) else content)
    return found


def run_code(code: str) -> ModelResponse:
    """Ask Code Mode to run a snippet.

    Args:
        code: The Python snippet.

    Returns:
        The model's response.
    """
    return ModelResponse(parts=[ToolCallPart(RUN_CODE, {"code": code})])


def answer(info: AgentInfo, picks: Sequence[dict[str, str]]) -> ModelResponse:
    """Answer with picks through the output tool.

    Args:
        info: The agent's tools.
        picks: ``chunk_id`` and ``justification`` of each pick.

    Returns:
        The model's final response.
    """
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"picks": list(picks)})])


BROWSE = """\
hits = await search_docs(query={query!r}, limit={limit})
articles = await list_articles()
seen = []
for hit in hits:
    if hit["article_path"] not in seen:
        seen.append(hit["article_path"])
outlines = [await article_outline(path=path) for path in seen[:2]]
first = await read_chunk(chunk_id=hits[0]["chunk_id"]) if hits else None
hits
"""
"""What ``browsing``'s agent runs: a search, the article list, two outlines and one chunk."""


def browsing(*, picks: int = 3, extra: Sequence[str] = ()) -> FunctionModel:
    """An agent that searches, reads the tree, then answers with the best search hits.

    Args:
        picks: How many hits it answers with.
        extra: Chunk IDs it adds to its answer, as if it had made them up (another version's,
            or none at all); the pipeline must drop them.

    Returns:
        The model.
    """

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Browse first, then answer.

        Args:
            messages: The run so far.
            info: The agent's tools.

        Returns:
            The next response.
        """
        results = code_results(messages)
        if not results:
            return run_code(BROWSE.format(query=question(messages), limit=max(picks, 5)))
        hits = results[-1] if isinstance(results[-1], list) else []
        chosen = [
            {
                "chunk_id": hit["chunk_id"],
                "justification": f"Its section {' > '.join(hit['heading_path'])} answers it.",
            }
            for hit in hits[:picks]
        ]
        chosen += [{"chunk_id": c, "justification": "A guess."} for c in extra]
        return answer(info, chosen)

    return FunctionModel(script, model_name="scripted-browser")


def greedy(calls: int) -> FunctionModel:
    """An agent that searches ``calls`` times in one snippet: past any small tool-call limit.

    Each search asks for other words, so it is never taken for a loop.

    Args:
        calls: How many searches it asks for.

    Returns:
        The model.
    """

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Search too often, then answer nothing.

        Args:
            messages: The run so far.
            info: The agent's tools.

        Returns:
            The next response.
        """
        if code_results(messages):
            return answer(info, [])
        snippet = (
            f"for i in range({calls}):\n    await search_docs(query='retry ' + str(i))\n'done'"
        )
        return run_code(snippet)

    return FunctionModel(script, model_name="scripted-greedy")


LOOP_IN_ONE_SNIPPET = """\
hits = []
for i in range({times}):
    hits = await search_docs(query='retry', limit=5)
hits
"""
"""What ``looping``'s agent runs in one snippet: the same search ``times`` times."""
LOOP_SNIPPET = "await search_docs(query='retry', limit=5)"
"""What ``looping``'s agent runs again and again, one snippet per request."""


def looping(times: int, *, in_one_snippet: bool = True) -> FunctionModel:
    """An agent stuck in a loop: it makes the same call with the same arguments ``times`` times.

    Args:
        times: How many times it repeats the call.
        in_one_snippet: Repeat the read call inside one ``run_code`` snippet; else send the same
            ``run_code`` snippet once per model request.

    Returns:
        The model; once done it answers with the first hit it got.
    """

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Repeat the call, then answer.

        Args:
            messages: The run so far.
            info: The agent's tools.

        Returns:
            The next response.
        """
        results = code_results(messages)
        if in_one_snippet and not results:
            return run_code(LOOP_IN_ONE_SNIPPET.format(times=times))
        if not in_one_snippet and len(results) < times:
            return run_code(LOOP_SNIPPET)
        hits = next((r for r in results if isinstance(r, list) and r), [])
        return answer(info, [{"chunk_id": h["chunk_id"], "justification": "It."} for h in hits[:1]])

    return FunctionModel(script, model_name="scripted-loop")


def sandbox_hog(
    code: str, requests: list[int] | None = None, *, vary: bool = False
) -> FunctionModel:
    """An agent whose every snippet is ``code`` (one that trips a Monty limit).

    Args:
        code: The snippet.
        requests: Gets a 1 appended for every model request, when given.
        vary: Make each snippet differ (a comment numbers it), so running it again is no loop.

    Returns:
        The model.
    """

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Run the snippet again and again.

        Args:
            messages: The run so far.
            info: The agent's tools.

        Returns:
            The next response.
        """
        del info
        if requests is not None:
            requests.append(1)
        return run_code(f"{code}  # request {len(messages)}" if vary else code)

    return FunctionModel(script, model_name="scripted-hog")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScriptedModels:
    """Implements retrieval's ``ModelFactory`` with a scripted chat model; nothing is called.

    ``chat_models`` lists the profiles' chat models it built, so a test can tell the factory
    was asked.
    """

    model: Model
    """The chat model every ``llm`` role gets (a ``FunctionModel``, maybe instrumented)."""
    chat_models: list[str] = field(default_factory=list)
    """``<profile>:<model>`` of every chat model built."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        """Say every profile can be called.

        Args:
            profile: The profile.

        Returns:
            None.
        """
        del profile
        return None

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        """Hand out the scripted model.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            The ``FunctionModel``.
        """
        self.chat_models.append(f"{profile.name}:{model}")
        return self.model

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        """Refuse: no embedding model here.

        Args:
            profile: The profile.
            model: The model.

        Raises:
            ProviderUnsupportedError: Always.
        """
        raise ProviderUnsupportedError(profile.name, model)

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        """Refuse: no reranker here.

        Args:
            profile: The profile.
            model: The model.

        Raises:
            ProviderUnsupportedError: Always.
        """
        raise ProviderUnsupportedError(profile.name, model)

    async def release(self, name: str) -> None:
        """Release nothing.

        Args:
            name: The profile.
        """
        del name

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        """Report the stand-in as working.

        Args:
            profile: The profile.
            model: The model.
            role: The role.

        Returns:
            A passed check.
        """
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


def scripted_ai(mode: str | None = "agentic", agentic: dict[str, Any] | None = None) -> dict:
    """The ``ai`` settings of an instance whose ``llm`` role is the scripted model.

    Args:
        mode: The instance's retrieval mode.
        agentic: The agentic limits, if any.

    Returns:
        The settings, as ``AiSettings.model_validate`` takes them.
    """
    return {
        "mode": mode,
        "providers": {"corp": {"kind": "openai-compatible", "base_url": "http://127.0.0.1:9/v1"}},
        "llm": {"model": "corp:explorer"},
        "agentic": agentic or {},
    }
