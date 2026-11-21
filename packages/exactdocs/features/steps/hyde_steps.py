"""Steps for HyDE (#94): the LLM on a fake gateway through pydantic-ai, an in-process embedding.

The ``llm`` role is an OpenAI-compatible profile on the fake gateway, built by the real
pydantic-ai factory, so the request it sends (path, headers) is the one a provider would get.
The ``embedding`` role is a ``local`` profile served by the term-hash stand-in: in-process and
free, so an exhausted budget stops the LLM step and leaves hybrid search answering.
"""

import json
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.ai_models import PydanticAiModels
from exactdocs.bootstrap.constants import MODEL_MARKER
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.local_models import model_folder
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.adapters.driven.memory import HashEmbeddingModels
from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.errors import ProviderUnsupportedError
from exactdocs.retrieval.models import (
    ModelCheck,
    ModelRole,
    ProviderKind,
    ProviderProfile,
    SpendEntry,
    SpendWindow,
    ThinkingLevel,
)
from exactdocs.retrieval.ports.driven import Reranker
from fake_llm import FakeGateway, gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.search_steps import LIBRARY

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
DIMENSIONS = 256
DAILY_TOKENS = 10_000_000
"""The instance's daily token budget: far more than embedding the fixture takes."""
HEADERS = {"X-Team": "docs"}
STAND_IN = "stand-in/term-hash"
"""The in-process embedding model's name on the ``local`` profile."""


@dataclass(slots=True)
class GatewayChatLocalEmbeddings:
    """``ModelFactory``: pydantic-ai's chat models; a marker for the ``local`` stand-in."""

    real: PydanticAiModels = field(default_factory=PydanticAiModels)

    def unsupported(self, profile: ProviderProfile) -> str | None:
        if profile.kind is ProviderKind.LOCAL:
            return None
        return self.real.unsupported(profile)

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        return await self.real.chat_model(profile, model, thinking=thinking)

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        return await self.real.thinking_unsupported(profile, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()  # the term-hash stand-in ignores it

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        raise ProviderUnsupportedError(profile.name, model)

    async def release(self, name: str) -> None:
        await self.real.release(name)

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        del thinking
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


def chat_calls(endpoint: FakeGateway) -> list[dict[str, str]]:
    """The headers of every chat completion the gateway received.

    Args:
        endpoint: The fake gateway.

    Returns:
        One header map per call, in order.
    """
    return [s.headers for s in endpoint.seen if s.path.endswith("/chat/completions")]


def serve_with_llm(
    context: Context,
    *,
    mode: str,
    providers: dict[str, Any],
    llm: dict[str, Any],
) -> None:
    """Serve the fixture with the local embedding stand-in and an ``llm`` role on a gateway.

    Args:
        context: The behave context; ``context.endpoint`` must be the running gateway.
        mode: The instance's retrieval mode.
        providers: The profiles besides the ``local`` one (``box``).
        llm: The ``[ai.llm]`` section.
    """
    context.search_ref = "v1.4.0"
    ai = AiSettings.model_validate(
        {
            "mode": mode,
            "providers": {**providers, "box": {"kind": "local"}},
            "embedding": {"model": f"box:{STAND_IN}", "dimensions": DIMENSIONS},
            "llm": llm,
            "budgets": {"daily_tokens": DAILY_TOKENS},
        }
    )
    context.client.__exit__(None, None, None)  # one job worker per process
    settings = context.settings.model_copy(update={"ai": ai})
    # A `local` role needs its model pulled (#245): the stand-in's marker, as a pull writes it.
    folder = model_folder(settings.effective_models_dir, STAND_IN)
    folder.mkdir(parents=True, exist_ok=True)
    marker = {"model": STAND_IN, "role": "embedding", "dimensions": DIMENSIONS}
    (folder / MODEL_MARKER).write_text(json.dumps(marker), encoding="utf-8")
    container = Container.build(
        settings,
        model_factory=GatewayChatLocalEmbeddings(),
        embedding_models=HashEmbeddingModels(size=DIMENSIONS, by_terms=True),
    )
    context.container = container
    context.hyde = True
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given(
    'an embedding model and an LLM are configured, and the operator chose retrieval mode "{mode}"'
)
def step_hyde_instance(context: Context, mode: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.endpoint = stack.enter_context(gateway())
    providers = {
        "corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1, "headers": HEADERS}
    }
    serve_with_llm(context, mode=mode, providers=providers, llm={"model": "corp:writer"})


def use_up_the_daily_budget(context: Context) -> None:
    """Record today's instance spend at the daily token budget, as earlier calls would have.

    Args:
        context: The behave context of a HyDE scenario.
    """
    now = datetime.now(UTC)
    entry = SpendEntry(
        scope_kind="instance",
        scope_id="",
        window=SpendWindow.DAY,
        window_start=SpendWindow.DAY.start(now),
        input_tokens=DAILY_TOKENS,
        requests=1,
    )
    ledger = SqliteSpendLedger(engine=context.container.engine)
    context.client.portal.call(ledger.add, [entry])


@given("the LLM endpoint refuses every call")
def step_llm_refuses(context: Context) -> None:
    context.endpoint.chat_broken.set()


@when('an agent searches in "{mode}" mode')
def step_search_in_mode(context: Context, mode: str) -> None:
    context.response = context.client.get(
        SEARCH, params={"q": "retry_policy", "ref": context.search_ref, "mode": mode}
    )


@then('the result says retrieval mode "{mode}" with fallback reason "{reason}"')
def step_mode_and_reason(context: Context, mode: str, reason: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, reason), body
    assert body["results"], body


@then("a repeated query for the same version reuses the cached hypothetical answer")
def step_cached(context: Context) -> None:
    assert len(chat_calls(context.endpoint)) == 1, context.endpoint.seen
    again = context.client.get(SEARCH, params={"q": "  RETRY_POLICY "})
    assert again.status_code == HTTPStatus.OK, again.text
    assert again.json()["retrieval_mode"] == "hybrid_hyde", again.json()
    assert len(chat_calls(context.endpoint)) == 1, "no second LLM call"


@then("every call to the LLM carried the profile's headers")
def step_headers(context: Context) -> None:
    calls = chat_calls(context.endpoint)
    assert calls
    for name, value in HEADERS.items():
        assert all(headers.get(name.lower()) == value for headers in calls), calls


@then("the LLM was not called")
def step_llm_not_called(context: Context) -> None:
    assert chat_calls(context.endpoint) == [], context.endpoint.seen
