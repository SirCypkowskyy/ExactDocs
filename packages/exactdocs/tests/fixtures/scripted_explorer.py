"""Stand-in LLMs for the agentic mode (pytest, behave and the eval suite): no provider is called.

Each is a pydantic-ai ``FunctionModel`` that drives harness Code Mode as an agent would: it calls
``run_code`` with a snippet that uses the read functions, then answers with chunk IDs taken from
what the snippet returned. ``ScriptedModels`` is a ``ModelFactory`` whose chat model is one of
them, so a container built with it runs the real ``agentic`` pipeline end to end.
"""

import json
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import (
    CompletedStreamedResponse,
    Model,
    ModelRequestParameters,
    StreamedResponse,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

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
        return run_code(f"for i in range({calls}):\n    await search_docs(query='retry')\n'done'")

    return FunctionModel(script, model_name="scripted-greedy")


def sandbox_hog(code: str, requests: list[int] | None = None) -> FunctionModel:
    """An agent whose every snippet is ``code`` (one that trips a Monty limit).

    Args:
        code: The snippet.
        requests: Gets a 1 appended for every model request, when given.

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
        del messages, info
        if requests is not None:
            requests.append(1)
        return run_code(code)

    return FunctionModel(script, model_name="scripted-hog")


class Billed(WrapperModel):
    """A scripted model that streams and bills its input, as a provider does (#101).

    Harness ``RepoContext`` (repo guidance) listens to the run's events, so the agent then
    streams every model request. A ``FunctionModel``'s stream reports output tokens only; this
    one answers each streamed request with the wrapped model's complete response, whose usage
    counts the request's text (instructions, notes, tool results) the way a provider bills it.
    """

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        """Answer with the complete response, its parts replayed as stream events.

        Args:
            messages: The request.
            model_settings: Its settings.
            model_request_parameters: Its tools and output.
            run_context: The run.

        Yields:
            The response as a stream.
        """
        del run_context
        response = await self.wrapped.request(messages, model_settings, model_request_parameters)
        yield CompletedStreamedResponse(
            response, model_request_parameters=model_request_parameters, replay_events=True
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Request:
    """What one model request of a run carried, as a provider would receive it."""

    instructions: str
    """The system instructions."""
    system: list[str]
    """Every system-prompt part of the messages."""
    user: list[str]
    """Every user-prompt part of the messages (the question, then any user-channel note)."""
    tools: list[str]
    """The tools the model may call (the output tool aside)."""


def _texts(
    messages: Sequence[ModelMessage], kind: type[UserPromptPart | SystemPromptPart]
) -> list[str]:
    """Collect the text of every request part of one kind.

    Args:
        messages: The run's messages so far.
        kind: ``UserPromptPart`` or ``SystemPromptPart``.

    Returns:
        Their contents, in order.
    """
    found: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            parts = [p for p in message.parts if isinstance(p, kind)]
            found.extend(p.content for p in parts if isinstance(p.content, str))
    return found


def guided(code: str, seen: list[Request], *, picks: int = 2, after: str | None = None) -> Billed:
    """An agent that runs ``code`` (it opens folders), then answers with its search hits.

    It records every request (``seen``), so a test can tell which channel an instruction
    file reached it on. It streams, as runs with repo guidance need.

    Args:
        code: The first snippet; the value it ends with is a list of search hits.
        seen: Gets each request appended.
        picks: How many hits it answers with.
        after: A second snippet it runs once it has seen the first one's result (as a model
            that does what a note told it to would), before answering.

    Returns:
        The model.
    """

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Run the snippets, then answer.

        Args:
            messages: The run so far.
            info: The agent's tools.

        Returns:
            The next response.
        """
        seen.append(
            Request(
                instructions=info.instructions or "",
                system=_texts(messages, SystemPromptPart),
                user=_texts(messages, UserPromptPart),
                tools=[tool.name for tool in info.function_tools],
            )
        )
        results = code_results(messages)
        if not results:
            return run_code(code)
        if after is not None and len(results) == 1:
            return run_code(after)
        hits = results[0] if isinstance(results[0], list) else []
        chosen = [{"chunk_id": h["chunk_id"], "justification": "It answers it."} for h in hits]
        followed = results[-1] if after is not None and isinstance(results[-1], list) else []
        told = [
            {"chunk_id": h["chunk_id"], "justification": "The note said so."}
            for h in followed
            if isinstance(h, dict) and "chunk_id" in h
        ]
        return answer(info, [*told, *chosen[:picks]])

    return Billed(FunctionModel(script, model_name="scripted-guided"))


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
