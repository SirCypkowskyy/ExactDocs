"""A tiny golden set and stand-in documentation tools for the agent benchmark (pytest and behave).

The documentation tools are a small in-process MCP server (FastMCP) with the three ExactDocs tools
the stand-in agents call (``list_libraries``, ``search_docs``, ``read_chunk``) over two versions of
one library, so every arm runs end to end in a fraction of a second, with the stand-in models of
``agent_bench.offline``, no ExactDocs server and no provider. Their numbers mean nothing; they
prove the plumbing.
"""

import contextlib
import re
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fastmcp import FastMCP
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import AbstractToolset
from pydantic_evals import Case

from agent_bench.arms import NONE, Arm
from agent_bench.harness import Recorder, RetrievalConfig, record_tool_call
from agent_bench.models import chat_model
from agent_bench.offline import OFFLINE_JUDGE
from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.golden import Corpus, GoldenCase, PinnedVersion, Project

LIBRARY: Final[str] = "/acme/demo"
"""The stand-in library's ID."""
CHUNKS: Final[tuple[dict[str, Any], ...]] = (
    {
        "library": LIBRARY,
        "version": "v1",
        "article_path": "docs/guide.md",
        "heading_path": ["Guide", "Install"],
        "chunk_id": "v1-install",
        "content": "Install the package with pip install demo, then import it.",
    },
    {
        "library": LIBRARY,
        "version": "v2",
        "article_path": "docs/start.md",
        "heading_path": ["Guide", "Setup"],
        "chunk_id": "v2-setup",
        "content": "Install the package with uv add demo; pip is no longer documented.",
    },
)
"""The library's sections, one per version."""
WORD: Final[re.Pattern[str]] = re.compile(r"\w{4,}")
"""A word the stand-in search matches."""


def _words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text)}


def docs_server() -> FastMCP:
    """The stand-in documentation server.

    Returns:
        A FastMCP server with ``list_libraries``, ``search_docs`` and ``read_chunk``.
    """
    server = FastMCP("stand-in docs")

    @server.tool
    def list_libraries() -> dict[str, Any]:
        """List the libraries."""
        return {"libraries": [{"id": LIBRARY, "title": "Demo"}]}

    @server.tool
    def search_docs(library: str, ref: str, query: str, limit: int = 3) -> dict[str, Any]:
        """Search one version of a library."""
        found = [
            {"chunk_id": c["chunk_id"], "snippet": c["content"]}
            for c in CHUNKS
            if c["library"] == library
            and c["version"] == ref
            and _words(query) & _words(c["content"])
        ]
        return {"retrieval_mode": "bm25", "fallback_reason": None, "results": found[:limit]}

    @server.tool
    def read_chunk(chunk_id: str) -> dict[str, Any]:
        """Read one section in full."""
        return next(c for c in CHUNKS if c["chunk_id"] == chunk_id)

    return server


@contextlib.asynccontextmanager
async def stand_in_tools(
    arm: Arm, config: RetrievalConfig | None
) -> AsyncGenerator[Sequence[AbstractToolset[Recorder]]]:
    """Give an arm its stand-in tools: none for ``none``, the stand-in server for any other.

    Args:
        arm: The arm.
        config: Its retrieval configuration (unused: the stand-in has one).

    Yields:
        The toolsets.
    """
    del config
    if arm.name == NONE:
        yield []
        return
    async with MCPToolset(docs_server(), process_tool_call=record_tool_call, id=arm.name) as tools:
        yield [tools]


def _case(name: str, version: str, kind: str, hits: list[Hit], facts: list[str]) -> GoldenCase:
    return Case(
        name=name,
        inputs=Question(query=name.split(": ", 1)[1], version=version, project="demo"),
        metadata=CaseInfo(kind=kind),  # ty: ignore[invalid-argument-type]
        expected_output=Answer(hits=hits, reference=f"reference of {name}", facts=facts),
    )


def golden() -> tuple[Corpus, list[tuple[str, GoldenCase]]]:
    """The stand-in golden set: one project, two versions, three cases.

    Returns:
        The corpus and its ``(project, case)`` pairs: a how-to and a version change answered by
        the stand-in docs, and an unanswerable question.
    """
    corpus = Corpus(
        projects=[
            Project(
                id="demo",
                title="Demo",
                repository="https://example.com/acme/demo",
                include=["docs/"],
                licence="MIT",
                attribution="Copyright (c) A",
                versions=[
                    PinnedVersion(name="v1", commit="1" * 40),
                    PinnedVersion(name="v2", commit="2" * 40),
                ],
            )
        ]
    )
    install = Hit(version="v1", article="docs/guide.md", heading_path=["Guide", "Install"])
    setup = Hit(version="v2", article="docs/start.md", heading_path=["Guide", "Setup"])
    cases = [
        _case(
            "demo v1: How do I install the package?",
            "v1",
            "how-to",
            [install],
            ["install the package with pip install demo"],
        ),
        _case(
            "demo v2: How do I install the package now?",
            "v2",
            "version-change",
            [setup],
            ["install the package with uv add demo"],
        ),
        _case("demo v2: Which file holds the settings?", "v2", "unanswerable", [], []),
    ]
    return corpus, [("demo", c) for c in cases]


@dataclass(slots=True)  # conventions: allow-mutable-dataclass -- a test heals it between runs
class FlakyProvider:
    """Resolves model names to the stand-ins, whose provider is rate limited on some questions.

    Pass it to ``run_bench(models=...)``. While ``failing``, every agent request whose prompt
    holds ``on`` is answered 429 after the client's retries; the judge never fails.
    """

    on: str
    """A part of the questions the provider fails on."""
    failing: bool = True
    """Whether it still fails (set it to False before a resumed run)."""

    def __call__(self, name: str) -> Model | str:
        """Resolve one model name.

        Args:
            name: A stand-in's name.

        Returns:
            The stand-in; an agent's is rate limited on the questions holding ``on``.
        """
        model = chat_model(name)
        if name == OFFLINE_JUDGE or not isinstance(model, FunctionModel):
            return model
        script = model.function
        if script is None:
            return model

        def flaky(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            """Answer, or fail as a rate-limited provider does.

            Args:
                messages: The run so far.
                info: The run's tools.

            Returns:
                The stand-in's step.

            Raises:
                ModelHTTPError: 429, while failing on this question.
            """
            asked = " ".join(str(getattr(part, "content", "")) for part in messages[0].parts)
            if self.failing and self.on in asked:
                raise ModelHTTPError(429, name, body="rate limited")
            step = script(messages, info)
            assert isinstance(step, ModelResponse)  # the stand-ins answer synchronously
            return step

        return FunctionModel(flaky, model_name=name)
