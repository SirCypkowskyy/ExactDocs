"""The time an agent run loses to provider retries, measured with HTTP client event hooks.

The OpenAI client retries a request answered 408, 409, 429 or 5xx with backoff (``Retry-After``
honoured). A client built with ``HOOKS`` (``models.ollama_model``) adds up, in the run's
``RetryLog``, the failed requests and the time from each one's start to its retry's start: the
failed request and the backoff. Each run sets its own log (``harness.asker``); the requests of the
run see it through the context variable. A lost connection is retried too but not counted (no
response reaches the hooks).
"""

import contextvars
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import httpx2

RETRIED_STATUS: Final[frozenset[int]] = frozenset({408, 409, 429})
"""Statuses below 500 the OpenAI client retries."""
SERVER_ERROR: Final[int] = 500
"""The first status of a server error, which the OpenAI client retries."""
_STARTED: Final[str] = "agent_bench_started"
"""The request extension holding when the request started."""


@dataclass(slots=True)  # conventions: allow-mutable-dataclass -- the hooks fill it
class RetryLog:
    """What one agent run lost to provider retries."""

    failed: int = 0
    """Requests answered with a status the client retries."""
    seconds: float = 0.0
    """From each failed request's start to its retry's start (the request and the backoff)."""
    pending: float | None = None
    """When the last failed request started, until its retry starts."""


RETRIES: Final[contextvars.ContextVar[RetryLog | None]] = contextvars.ContextVar(
    "agent_bench_retries", default=None
)
"""The current run's log."""


async def on_request(request: httpx2.Request) -> None:
    """Note when a request starts; a retry closes its failed request's wait.

    Args:
        request: The outgoing request.
    """
    now = time.perf_counter()
    request.extensions[_STARTED] = now
    log = RETRIES.get()
    if log is not None and log.pending is not None:
        log.seconds += now - log.pending
        log.pending = None


async def on_response(response: httpx2.Response) -> None:
    """Count a response the client will retry, and start its wait.

    Args:
        response: The response.
    """
    status = response.status_code
    log = RETRIES.get()
    if log is not None and (status in RETRIED_STATUS or status >= SERVER_ERROR):
        log.failed += 1
        log.pending = response.request.extensions.get(_STARTED, time.perf_counter())


HOOKS: Final[dict[str, list[Callable[..., Awaitable[None]]]]] = {
    "request": [on_request],
    "response": [on_response],
}
"""The event hooks of an HTTP client whose retries are measured."""
