"""A tiny golden corpus and stand-in models for the retrieval benchmark (pytest and behave).

The corpus is one project, one version and two cases (an answerable how-to and an unanswerable
question). The stand-ins answer every hosted step without a provider: the term-hash embedding,
and one pydantic-ai ``FunctionModel`` that rates candidates as the judge, writes a hypothetical
answer for HyDE and browses as the agent. They prove the plumbing; their numbers mean nothing.
"""

import re
from pathlib import Path

import yaml
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.memory import HashEmbeddingModels
from exactdocs.retrieval.ports.driven import AgentReads
from fixture_repo import git
from offline_embedding import DIMENSIONS, LLM, LLM_PRICE, MODEL, PROFILE, MarkerFactory
from scripted_explorer import browsing

FENCE = "```"
GUIDE = f"""# Guide

Intro.

## Install

Run pip to install the demo package.

{FENCE}sh
pip install demo
{FENCE}

## Configure

Set the timeout option in the settings file.
"""


def tiny_corpus(root: Path, *, guide: str = GUIDE, cases: list[dict] | None = None) -> list[str]:
    """Write the corpus, its cases and an upstream repository under ``root``.

    Args:
        root: Where to write them.
        guide: The text of ``docs/guide.md``, the corpus's only article.
        cases: The golden cases; the default how-to and unanswerable ones when None.

    Returns:
        The benchmark's arguments that point at them (corpus, cases, cache, an empty models dir).
    """
    repo = root / "upstream"
    git("init", "-q", "-b", "main", "--template=", str(repo))
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "guide.md").write_text(guide, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git(
        "commit", "-q", "--no-verify", "-m", "v1", cwd=repo,
        GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@example.com",
    )  # fmt: skip
    project = {
        "id": "demo",
        "title": "Demo",
        "repository": str(repo),
        "include": ["docs/"],
        "licence": "MIT",
        "attribution": "Copyright (c) A",
        "versions": [{"name": "v1", "commit": git("rev-parse", "HEAD", cwd=repo)}],
    }
    (root / "corpus.yaml").write_text(yaml.safe_dump({"projects": [project]}), "utf-8")
    install = {"version": "v1", "article": "docs/guide.md", "heading_path": ["Guide", "Install"]}
    cases = (
        cases
        if cases is not None
        else [
            {
                "name": "demo v1: How do I install the demo package?",
                "inputs": {"query": "install demo package pip", "version": "v1", "project": "demo"},
                "metadata": {"kind": "how-to"},
                "expected_output": {"hits": [install], "reference": "pip.", "facts": ["pip"]},
            },
            {
                "name": "demo v1: Does it support Kubernetes operators?",
                "inputs": {"query": "kubernetes operator crd", "version": "v1", "project": "demo"},
                "metadata": {"kind": "unanswerable"},
                "expected_output": {"hits": [], "reference": "It does not say."},
            },
        ]
    )
    (root / "cases").mkdir()
    (root / "cases" / "demo.yaml").write_text(
        yaml.safe_dump({"name": "demo", "cases": cases}), "utf-8"
    )
    return [
        "--corpus", str(root / "corpus.yaml"), "--cases", str(root / "cases"),
        "--cache-dir", str(root / "cache"), "--models-dir", str(root / "models"),
    ]  # fmt: skip


HOSTED = AiSettings.model_validate(
    {
        "providers": {PROFILE: {"kind": "openai-compatible", "base_url": "http://127.0.0.1:9/v1"}},
        "embedding": {"model": f"{PROFILE}:{MODEL}", "dimensions": DIMENSIONS},
        "llm": {"model": f"{PROFILE}:{LLM}"},
        "judge": {"model": f"{PROFILE}:{LLM}"},
        "prices": {f"{PROFILE}:{LLM}": LLM_PRICE},
    }
)
"""The "hosted" roles, all stand-ins on a closed loopback port, priced so USD is counted."""

_CANDIDATE = re.compile(r'<candidate id="(c[0-9]+)">(.*?)</candidate>', re.DOTALL)
_QUERY = re.compile(r"<query>(.*?)</query>", re.DOTALL)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def _stand_in(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Answer as the agent (it has tools), the judge (an output tool) or HyDE (text)."""
    if info.function_tools:
        script = browsing().function
        assert script is not None
        response = script(messages, info)
        assert isinstance(response, ModelResponse)
        return response
    prompt = "\n".join(
        str(part.content)
        for message in messages
        for part in getattr(message, "parts", ())
        if part.part_kind == "user-prompt"
    )
    if info.output_tools:
        query = _words(next(iter(_QUERY.findall(prompt)), ""))
        ratings = [
            {"id": candidate, "score": min(10, len(query & _words(text)))}
            for candidate, text in _CANDIDATE.findall(prompt)
        ]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"response": ratings})])
    return ModelResponse(parts=[TextPart(content=f"The documentation says: {prompt}")])


def stand_in_container(settings: Settings, *, agent_reads: AgentReads | None = None) -> Container:
    """Build a configuration's container on the stand-ins (the benchmark's ``build``).

    Returns:
        The container: no provider is ever called.
    """
    return Container.build(
        settings,
        model_factory=MarkerFactory(chat=lambda: FunctionModel(_stand_in, model_name=LLM)),
        embedding_models=HashEmbeddingModels(size=DIMENSIONS, by_terms=True),
        agent_reads=agent_reads,
    )
