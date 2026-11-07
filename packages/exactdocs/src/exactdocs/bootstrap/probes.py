"""Liveness and readiness probes for orchestrators, and the Host check that lets them through.

``/healthz`` (alias ``/api/health``) answers while the event loop runs; it gives the database at
most ``LIVENESS_DATABASE_SECONDS`` for its details (schema, search index and engine). ``/readyz``
answers 200 only when the database file exists, answers, and is at this build's schema revision.
Neither connects to a missing database file: SQLite would create an empty one.
"""

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from typing import Literal, Self

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
    READINESS_PATH,
    READINESS_TIMEOUT_SECONDS,
    UNTRUSTED_HOST,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import current_revision, database_file_missing, schema_head


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
    search_engine: str | None
    """The search engine that answers: `fts5` (SQLite), `pg_search` (ParadeDB's BM25 on
    PostgreSQL) or `postgres_fts` (PostgreSQL full-text search, without `pg_search`). Null when the
    database could not tell."""


class Readiness(BaseModel):
    """Readiness payload: whether this instance can serve requests now."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: Literal["ready", "not_ready"]
    """`ready` (HTTP 200) or `not_ready` (HTTP 503)."""
    reason: str | None = None
    """Why it is not ready, as a short sentence; null when ready."""


def build_probe_router(container: Container) -> APIRouter:
    """Liveness and readiness probes, outside ``/api/v1``: no sign-in, no setup guard.

    Args:
        container: The instance whose database the probes ask.

    Returns:
        The router serving ``/healthz`` (and its alias ``/api/health``) and ``/readyz``.
    """
    router = APIRouter(tags=["system"])
    head = schema_head()
    methods = sorted(PROBE_METHODS)

    @router.api_route(LIVENESS_PATH, methods=methods)
    @router.api_route(HEALTH_ALIAS_PATH, methods=methods)
    async def health(request: Request) -> Health | Alive:
        """Liveness: answers 200 while the process runs, whatever the database does.

        Args:
            request: The request; a probe with an untrusted ``Host`` gets no details.

        Returns:
            The version and what the database says about its schema and search index, or only
            ``status`` for an untrusted ``Host``.
        """
        if getattr(request.state, UNTRUSTED_HOST, False):
            return Alive(status="ok")
        return await _health(container)

    @router.api_route(READINESS_PATH, methods=methods, responses={503: {"model": Readiness}})
    async def readiness(response: Response) -> Readiness:
        """Readiness: 200 when the database answers at this build's schema, 503 otherwise.

        Args:
            response: The response, whose status turns 503 when not ready.

        Returns:
            Whether the instance is ready, and why not.
        """
        reason = await _not_ready_because(container, head)
        if reason is None:
            return Readiness(status="ready")
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        return Readiness(status="not_ready", reason=reason)

    return router


async def _health(container: Container) -> Health:
    """Liveness with the database's details, if it gives them within the liveness budget.

    Args:
        container: The instance to describe.

    Returns:
        The liveness payload.
    """
    unknown = Health(
        status="ok",
        version=__version__,
        database_reachable=False,
        schema_revision=None,
        search_index_format=None,
        reindex_required=None,
        search_engine=None,
    )
    try:
        async with asyncio.timeout(LIVENESS_DATABASE_SECONDS):
            # A thread: even a stat must not hold up the event loop liveness stands for.
            if await asyncio.to_thread(database_file_missing, container.engine):
                return unknown
            revision = await current_revision(container.engine)
            index = await container.retrieval.get_search_index_state()
    except SQLAlchemyError, OSError, TimeoutError:
        return unknown
    return Health(
        status="ok",
        version=__version__,
        database_reachable=True,
        schema_revision=revision,
        search_index_format=index.stored_format,
        reindex_required=index.needs_rebuild,
        search_engine=index.engine,
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
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            if await asyncio.to_thread(database_file_missing, container.engine):
                return "the database file is missing"
            revision = await current_revision(container.engine)
    except SQLAlchemyError, OSError, TimeoutError:
        return "the database is unreachable"
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
