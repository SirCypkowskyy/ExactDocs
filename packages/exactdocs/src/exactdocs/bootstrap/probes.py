"""Liveness and readiness probes for orchestrators, and the Host check that lets them through.

``/healthz`` (alias ``/api/health``) answers while the event loop runs; it gives the database at
most ``LIVENESS_DATABASE_SECONDS`` for its details (schema, search index and engine). ``/readyz``
answers 200 only when the database file exists, answers, and is at this build's schema revision.
Neither connects to a missing database file: SQLite would create an empty one.

Each probe asks the database in a task of its own and waits for it no longer than its budget
(#298). Cancelling the check instead would not work: SQLAlchemy then closes the connection by
waiting, shielded from the cancellation, for the driver, which first finishes the statement. A
check the probe stopped waiting for runs to its end, and the next probe waits for it rather than
starting another: however often it is called, each probe holds at most one connection. When the
app stops, ``Probes.settle`` waits for those checks before the engine is disposed, so none is
left holding a connection of a discarded pool (#291), unless its statement is stuck in the
driver's thread: shutdown waits for that at most twice ``PROBE_SETTLE_SECONDS``, then gives up.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from functools import partial
from http import HTTPStatus
from typing import Any, Literal, Self

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from exactdocs import __version__
from exactdocs.bootstrap.constants import (
    HEALTH_ALIAS_PATH,
    HOST_TRUSTED,
    LIVENESS_DATABASE_SECONDS,
    LIVENESS_PATH,
    PROBE_METHODS,
    PROBE_PATHS,
    PROBE_SETTLE_SECONDS,
    READINESS_PATH,
    READINESS_TIMEOUT_SECONDS,
    READINESS_UNREACHABLE,
    UNTRUSTED_HOST,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import current_revision, database_file_missing, schema_head
from exactdocs.retrieval.models import SearchEngine

logger = logging.getLogger(__name__)


class Alive(BaseModel):
    """Liveness payload for a caller whose ``Host`` is not trusted: nothing but that it is up."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: Literal["ok"]
    """Always `ok`: an answer at all means the process is up."""


class Health(BaseModel):
    """Liveness payload: the process answers. The database details are best effort."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: Literal["ok"]
    """Always `ok`: an answer at all means the process is up."""
    version: str
    """The ExactDocs version serving."""
    database_reachable: bool
    """The database answered within the liveness budget; when false, the fields below are null."""
    schema_revision: str | None
    """Alembic revision the database is at; null before the first migration or when unknown."""
    search_index_format: int | None
    """Format the stored search index was built in; null when none is recorded or unknown."""
    reindex_required: bool | None
    """The index is in an older or unrecorded format: run `exactdocs reindex` (it keeps serving).
    Null when the database could not tell."""
    search_engine: SearchEngine | None
    """The search engine that answers: `fts5` (SQLite), `pg_search` (ParadeDB's BM25 on
    PostgreSQL) or `postgres_fts` (PostgreSQL full-text search, without `pg_search`). Null when the
    database could not tell."""
    vector_store_missing: str | None = None
    """The database extension the vector store needs and cannot load here: `vector` (pgvector)
    on PostgreSQL, `sqlite-vec` on SQLite. Hybrid modes answer with BM25 until it is installed.
    Null when it loads, or when no embedding model is configured (it is not checked then)."""


class Readiness(BaseModel):
    """Readiness payload: whether this instance can serve requests now."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: Literal["ready", "not_ready"]
    """`ready` (HTTP 200) or `not_ready` (HTTP 503)."""
    reason: str | None = None
    """Why it is not ready, as a short sentence; null when ready."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Probes:
    """The probes' router, and the database checks they may leave running."""

    router: APIRouter
    """Serves ``/healthz`` (and its alias ``/api/health``) and ``/readyz``."""
    checks: tuple[_OneCheckAtATime[Any], ...]
    """Each probe's check runner."""

    async def settle(self, grace: float = PROBE_SETTLE_SECONDS) -> None:
        """Wait for the checks still in flight; cancel those that outlast ``grace``.

        Call it before the engine is disposed: a check left running would give its connection
        back to the discarded pool, which never closes it. It returns within about ``2 * grace``
        (the checks settle side by side); see ``_OneCheckAtATime.settle``. (A grace rather than
        an ``asyncio.timeout`` around the call: the bound is the method's own, and cancelling
        ``settle`` only cancels the checks without waiting for them.)

        Args:
            grace: Seconds each check gets to finish before it is cancelled, and again after.
        """
        await asyncio.gather(*(check.settle(grace) for check in self.checks))


def build_probes(container: Container) -> Probes:
    """Liveness and readiness probes, outside ``/api/v1``: no sign-in, no setup guard.

    Args:
        container: The instance whose database the probes ask.

    Returns:
        The router serving ``/healthz`` (and its alias ``/api/health``) and ``/readyz``, and
        what settles their checks when the app stops.
    """
    router = APIRouter(tags=["system"])
    head = schema_head()
    methods = sorted(PROBE_METHODS)
    details = _OneCheckAtATime(
        check=partial(_database_details, container), budget=LIVENESS_DATABASE_SECONDS
    )
    readiness_check = _OneCheckAtATime(
        check=partial(_not_ready_because, container, head), budget=READINESS_TIMEOUT_SECONDS
    )

    @router.api_route(LIVENESS_PATH, methods=methods)
    @router.api_route(HEALTH_ALIAS_PATH, methods=methods)
    async def health(request: Request) -> Health | Alive:
        """Liveness: answers 200 while the process runs, whatever the database does.

        Args:
            request: The request; a probe with an untrusted ``Host`` gets no details.

        Returns:
            The version and what the database says about its schema, search index and vector
            store, or only ``status`` for an untrusted ``Host``.
        """
        if getattr(request.state, UNTRUSTED_HOST, False):
            return Alive(status="ok")
        try:
            return await details()
        except TimeoutError:
            return _unknown()

    @router.api_route(READINESS_PATH, methods=methods, responses={503: {"model": Readiness}})
    async def readiness(response: Response) -> Readiness:
        """Readiness: 200 when the database answers at this build's schema, 503 otherwise.

        Args:
            response: The response, whose status turns 503 when not ready.

        Returns:
            Whether the instance is ready, and why not.
        """
        try:
            reason = await readiness_check()
        except TimeoutError:
            reason = READINESS_UNREACHABLE
        if reason is None:
            return Readiness(status="ready")
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        return Readiness(status="not_ready", reason=reason)

    return Probes(router=router, checks=(details, readiness_check))


def _unknown() -> Health:
    """Liveness when the database gave no details in time, or none at all.

    Returns:
        The payload with the database fields null.
    """
    return Health(
        status="ok",
        version=__version__,
        database_reachable=False,
        schema_revision=None,
        search_index_format=None,
        reindex_required=None,
        search_engine=None,
    )


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- the check in flight
class _OneCheckAtATime[T]:
    """Runs a database check in a task of its own, one at a time, and waits for it a budget long.

    A check still running when the budget is up is left to finish on its own: a later call waits
    for that same check instead of starting a new one, so a stuck database never holds more
    than one connection for it. A call may therefore get the result of a check an earlier call
    started; it is fresh when it arrives. ``settle`` ends the check in flight when the app stops.
    """

    check: Callable[[], Coroutine[object, object, T]]
    """The check; it answers for every error it expects, so the task only fails on a bug."""
    budget: float
    """Seconds a call waits for the check."""
    pending: asyncio.Task[T] | None = field(default=None, init=False)
    """The check in flight, if any: the reference that keeps its task alive until it is done."""

    async def __call__(self) -> T:
        """Wait for the check in flight, or a new one, at most ``budget`` seconds.

        Returns:
            What the check found.

        Raises:
            TimeoutError: The check did not finish within the budget (it goes on running).
        """
        task = self.pending
        if task is None:
            task = asyncio.create_task(self.check())
            task.add_done_callback(self._finished)
            self.pending = task
        await asyncio.wait({task}, timeout=self.budget)
        if not task.done() or task.cancelled():
            raise TimeoutError
        return task.result()

    async def settle(self, grace: float) -> None:
        """Wait for the check in flight at most ``grace`` seconds, then cancel it and wait again.

        Returns within about ``2 * grace``. A cancelled check still waits, shielded, for its
        connection to close, and that waits for the statement: cancellation cannot interrupt a
        statement stuck in the driver's thread. If the check is still running after the second
        ``grace``, it is abandoned with a warning: its connection may then go back to a disposed
        pool and be finalized unclosed later. An exiting process can spare one connection better
        than it can hang its shutdown.

        If ``settle`` itself is cancelled, it cancels the check and re-raises without waiting.

        Args:
            grace: Seconds the check gets to finish on its own, and again once cancelled.

        Raises:
            CancelledError: ``settle`` itself was cancelled (the check is cancelled too).
        """
        task = self.pending
        if task is None:
            return
        try:
            await asyncio.wait({task}, timeout=grace)
            if task.done():
                return
            logger.warning(
                "a probe's database check was still running after %s s at shutdown; cancelling it",
                grace,
            )
            task.cancel()
            await asyncio.wait({task}, timeout=grace)
        except asyncio.CancelledError:
            task.cancel()
            raise
        if not task.done():
            logger.warning(
                "a probe's database check ignored its cancellation for %s s at shutdown; "
                "abandoning it and its connection",
                grace,
            )

    def _finished(self, task: asyncio.Task[T]) -> None:
        """Let the next call start a new check, and log the task's error so none goes unseen.

        Args:
            task: The check that just finished.
        """
        if self.pending is task:
            self.pending = None
        if task.cancelled():
            return
        # The check answers for every error it expects: this is a bug, and the probe may have
        # stopped waiting for it, so it is logged here (and taken, so asyncio does not warn).
        if (error := task.exception()) is not None:
            logger.error("a probe's database check failed", exc_info=error)


async def _database_details(container: Container) -> Health:
    """Liveness with what the database says about its schema, search index and vector store.

    Args:
        container: The instance to describe.

    Returns:
        The liveness payload, unknown details when the database cannot be asked.
    """
    try:
        # A thread: even a stat must not hold up the event loop liveness stands for.
        if await asyncio.to_thread(database_file_missing, container.engine):
            return _unknown()
        revision = await current_revision(container.engine)
        index = await container.retrieval.get_search_index_state()
        vectors = await container.retrieval.get_vector_store_state()
    except SQLAlchemyError, OSError:
        return _unknown()
    return Health(
        status="ok",
        version=__version__,
        database_reachable=True,
        schema_revision=revision,
        search_index_format=index.stored_format,
        reindex_required=index.needs_rebuild,
        search_engine=index.engine,
        vector_store_missing=vectors.missing,
    )


async def _not_ready_because(container: Container, head: str | None) -> str | None:
    """Say why the instance cannot serve, or ``None`` when it can.

    Args:
        container: The instance to check.
        head: The schema revision this build needs.

    Returns:
        A fixed sentence (no paths or error text: the probe needs no sign-in), or ``None``.
    """
    try:
        if await asyncio.to_thread(database_file_missing, container.engine):
            return "the database file is missing"
        revision = await current_revision(container.engine)
    except SQLAlchemyError, OSError:
        return READINESS_UNREACHABLE
    if revision != head:
        return "the database is not at this version's schema"
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeAwareHostCheck:
    """Starlette's Host check for every request, except exact ``GET``/``HEAD`` probe requests.

    A probe from an untrusted ``Host`` (a Kubernetes ``httpGet`` sends the pod IP) is served,
    marked so that liveness answers only ``{"status": "ok"}``: the probes change nothing, read
    no cookies, and give a DNS-rebinding page nothing it could use.
    """

    app: ASGIApp
    """The app behind the check."""
    guarded: ASGIApp
    """``app`` behind Starlette's Host check: where every other request goes."""
    checker: ASGIApp
    """Starlette's Host check in front of a marker: tells whether it accepts a Host."""

    @classmethod
    def wrap(cls, app: ASGIApp, *, trusted_hosts: list[str]) -> Self:
        """Put the check in front of ``app`` (a middleware factory for ``add_middleware``).

        Args:
            app: The app to protect.
            trusted_hosts: Host names (and ``*.domain`` patterns) the app answers to.

        Returns:
            The middleware.
        """
        return cls(
            app=app,
            guarded=TrustedHostMiddleware(app, allowed_hosts=trusted_hosts),
            checker=TrustedHostMiddleware(_mark_trusted, allowed_hosts=trusted_hosts),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve a probe request whatever its Host; check the Host of every other request.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        if not (
            scope["type"] == "http"
            and scope["method"] in PROBE_METHODS
            and scope["path"] in PROBE_PATHS
        ):
            await self.guarded(scope, receive, send)
            return
        probe: Scope = {**scope}
        await self.checker(probe, receive, _discard)
        if not probe.get(HOST_TRUSTED, False):
            scope = {**scope, "state": {**scope.get("state", {}), UNTRUSTED_HOST: True}}
        await self.app(scope, receive, send)


async def _mark_trusted(scope: Scope, receive: Receive, send: Send) -> None:
    """Record that the Host check let the request through (it then sends nothing).

    Args:
        scope: The scope copy the check was given.
        receive: Unused.
        send: Unused.
    """
    del receive, send
    scope[HOST_TRUSTED] = True


async def _discard(message: Message) -> None:
    """Swallow the Host check's refusal: a probe is answered either way.

    Args:
        message: The ASGI message, dropped.
    """
    del message
