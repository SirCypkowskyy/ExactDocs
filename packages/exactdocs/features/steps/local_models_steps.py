"""Steps for local models (#245): tiny stand-in models, real fastembed, and no network.

The models directory gets the stand-ins of ``tiny_models`` (as ``exactdocs models pull`` leaves
models); the app is served again with roles on a ``local`` profile. "No network access" is a
socket guard in this process: it refuses, and records, every connection and name lookup that is
not loopback (the fixture repository is already imported, from loopback).
"""

import logging
import socket
import tempfile
from contextlib import ExitStack
from errno import ECONNREFUSED
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

import tiny_models
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.hybrid_search_steps import step_embedded
from steps.reranking_steps import step_agent_searches

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
SEARCH = "/api/v1/libraries/fixture/docs-repo/search"


def _models_dir(context: Context) -> Path:
    """Make an empty models directory for this scenario.

    Args:
        context: The behave context.

    Returns:
        The directory.
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    return Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-models-")))


def _serve(context: Context, ai: AiSettings) -> None:
    """Serve the same data again with these AI settings and the scenario's models directory.

    Args:
        context: The behave context.
        ai: The ``ai`` settings.
    """
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    settings = context.settings.model_copy(update={"ai": ai, "models_dir": context.models_dir})
    context.container = Container.build(settings)
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given(
    'ExactDocs is installed with the "local" extra and its models were pulled into the models '
    "directory"
)
def step_pulled(context: Context) -> None:
    tiny_models.register()
    context.models_dir = tiny_models.install(_models_dir(context))


@given('the embedding role is "{embedding}" and the reranker role is "{reranker}"')
def step_local_roles(context: Context, embedding: str, reranker: str) -> None:
    context.search_ref = "v1.4.0"  # 'an agent searches' (reranking_steps) searches this version
    context.local_ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"local": {"kind": "local"}},
            "embedding": {"model": embedding},
            "reranker": {"model": reranker},
        }
    )
    _serve(context, context.local_ai)


@given('the embedding role is "{embedding}" and the model is not in the models directory')
def step_missing_model(context: Context, embedding: str) -> None:
    context.models_dir = _models_dir(context)
    context.local_ai = AiSettings.model_validate(
        {"providers": {"local": {"kind": "local"}}, "embedding": {"model": embedding}}
    )
    context.missing_model = embedding.partition(":")[2]


type _Address = tuple[Any, ...] | str | bytes | int


@given("the process has no network access")
def step_no_network(context: Context) -> None:
    context.blocked = blocked = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def refused(sock: socket.socket, address: _Address) -> bool:
        name = str(address[0]) if isinstance(address, tuple) else str(address)
        if sock.family in {socket.AF_INET, socket.AF_INET6} and name not in LOOPBACK:
            blocked.append(name)
            return True
        return False

    def connect(self: socket.socket, address: _Address) -> None:
        if refused(self, address):
            message = "refused: this process has no network access"
            raise OSError(message)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: _Address) -> int:
        return ECONNREFUSED if refused(self, address) else real_connect_ex(self, address)

    def getaddrinfo(
        host: bytes | str | None, port: bytes | str | int | None, *args: int, **kwargs: int
    ) -> list[tuple[Any, ...]]:
        if host is not None and str(host) not in LOOPBACK:
            blocked.append(str(host))
            message = "refused: this process has no network access"
            raise socket.gaierror(message)
        return list(real_getaddrinfo(host, port, *args, **kwargs))

    stack = ExitStack()
    context.add_cleanup(stack.close)
    stack.enter_context(patch.object(socket.socket, "connect", connect))
    stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
    stack.enter_context(patch.object(socket, "getaddrinfo", getaddrinfo))


@when('"{ref}" is embedded and an agent searches "{query}"')
def step_embedded_then_search(context: Context, ref: str, query: str) -> None:
    step_embedded(context, ref)
    step_agent_searches(context, query)


@when("ExactDocs starts")
def step_starts(context: Context) -> None:
    messages: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    handler = Keep()
    logger = logging.getLogger("exactdocs")
    logger.addHandler(handler)
    context.add_cleanup(logger.removeHandler, handler)
    context.messages = messages
    _serve(context, context.local_ai)


@then('the result says retrieval mode "hybrid" and "reranked: true"')
def step_hybrid_reranked(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("hybrid", None), body
    assert body["reranked"] is True, body
    assert body["coverage"]["reranked"] > 0, body
    assert body["version"] == "v1.4.0", body
    assert body["results"], body


@then("nothing tried to reach the network")
def step_nothing_blocked(context: Context) -> None:
    assert context.blocked == [], context.blocked


@then('it refuses to enable the role with a message naming "{command}"')
def step_role_refused(context: Context, command: str) -> None:
    refused = [m for m in context.messages if "is off" in m]
    assert refused, context.messages
    assert f"`{command} {context.missing_model}`" in refused[0], refused
    response = context.client.get(SEARCH, params={"q": "retry", "mode": "hybrid"})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert "needs the embedding role" in response.json()["detail"], response.json()


@then("it opens no connection to the Hugging Face Hub")
def step_no_hub(context: Context) -> None:
    assert context.blocked == [], context.blocked
