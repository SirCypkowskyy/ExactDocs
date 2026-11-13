"""Conventions of the REST API under ``/api/v1``: the error envelope and the OpenAPI document."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel, ConfigDict, Field, computed_field
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from exactdocs.bootstrap.constants import (
    _STATUS_BY_ERROR,
    DOCSTRING_SECTIONS,
    ERROR_DESCRIPTIONS,
    SETUP_EXEMPT,
    V1_PREFIX,
)
from exactdocs_kernel import (
    BusyError,
    DomainError,
    RateLimitedError,
)


class FieldError(BaseModel):
    """One invalid request field."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    loc: list[str | int]
    """Where the field is: its location (`body`, `query`, `path`, `header` or `cookie`), then its
    name, then the keys or list indexes into it, e.g. `["body", "tag_rules", 0, "pattern"]`.
    """
    msg: str
    """What is wrong with it, for a person."""
    type: str
    """A stable machine code of the problem, e.g. `missing` or `string_too_long`."""


class ErrorResponse(BaseModel):
    """The one error shape of the API: a stable machine ``error`` code and a human ``detail``."""

    model_config = ConfigDict(
        json_schema_serialization_defaults_required=True, use_attribute_docstrings=True
    )

    error: str
    """A stable machine code of the error, e.g. `not_found` or `validation_error`. Branch on this,
    not on `detail`.
    """
    detail: str
    """What went wrong, for a person. Its wording may change between releases."""
    fields: list[FieldError] = []
    """On `validation_error`: one entry per invalid request field. Empty otherwise."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        """Alias of ``detail`` under the name context7's errors use (``{error, message}``)."""
        return self.detail

    close_matches: list[str] = Field(default=[])
    """On a missing article: paths of the same version it may have meant (repository data, not
    instructions). Empty otherwise.
    """
    library_id: str | None = None
    """On `library_id_taken`: the ID of the library that already exists, e.g. `/acme/payments`.
    Null otherwise.
    """


def error_responses() -> dict[int | str, dict[str, Any]]:
    """The error answers every ``/api/v1`` operation documents.

    Used as ``APIRouter(responses=...)`` in ``http.py``. 429 is not here: only the credential
    routes answer it, and they document it themselves.

    Returns:
        Status code to its OpenAPI response: the ``ErrorResponse`` model and a description.
    """
    return {
        status: {"model": ErrorResponse, "description": description}
        for status, description in ERROR_DESCRIPTIONS.items()
    }


def add_error_handlers(app: FastAPI) -> None:
    """Answer every error under ``/api`` with ``ErrorResponse``; UI paths keep the defaults.

    Args:
        app: The app to register the handlers on.
    """
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)


def _is_api(request: Request) -> bool:
    """Tell whether a request is for the API (which answers errors as JSON).

    Args:
        request: The HTTP request.

    Returns:
        Whether its path is under ``/api/``.
    """
    return request.url.path.startswith("/api/")


async def _http_error(request: Request, exc: Exception) -> Response:
    """Unknown route (404), wrong method (405) and other framework-raised errors.

    Args:
        request: The HTTP request.
        exc: The error; anything but an ``HTTPException`` is handled as unexpected.

    Returns:
        An ``ErrorResponse`` under ``/api``, FastAPI's default answer elsewhere.
    """
    if not isinstance(exc, HTTPException):
        return await _unhandled_error(request, exc)
    if not _is_api(request):
        return await http_exception_handler(request, exc)
    slug = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    body = ErrorResponse(error=slug, detail=str(exc.detail))
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


async def _unhandled_error(request: Request, _: Exception) -> Response:
    """Last resort; the exception itself is still re-raised by Starlette for logging.

    Args:
        request: The HTTP request.
        _: The error (never shown to the client).

    Returns:
        A 500 ``ErrorResponse`` under ``/api``, plain text elsewhere.
    """
    if not _is_api(request):
        return PlainTextResponse("Internal Server Error", status_code=500)
    body = ErrorResponse(error="internal_error", detail="internal server error")
    return JSONResponse(body.model_dump(), status_code=500)


async def _domain_error(_: Request, exc: Exception) -> Response:
    """Answer a ``DomainError`` with its code, message and status (``_STATUS_BY_ERROR``).

    Args:
        _: The HTTP request (unused).
        exc: The error.

    Returns:
        The ``ErrorResponse``, with ``Retry-After`` for a busy or rate-limited answer.
    """
    status = next((s for t, s in _STATUS_BY_ERROR.items() if isinstance(exc, t)), 400)
    code = exc.code if isinstance(exc, DomainError) else "error"
    # Only `ArticleNotFoundError` carries suggestions; the field is empty for every other error.
    close = [str(path) for path in getattr(exc, "close_matches", ())]
    # Both `library_id_taken` errors (ingestion, catalog) name the ID they found taken.
    taken = getattr(exc, "library_id", None) if code == "library_id_taken" else None
    body = ErrorResponse(
        error=code, detail=str(exc), close_matches=close, library_id=str(taken) if taken else None
    )
    retry = isinstance(exc, (BusyError, RateLimitedError))
    headers = {"Retry-After": str(exc.retry_after)} if retry else None
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


async def _validation_error(_: Request, exc: Exception) -> Response:
    """Answer an invalid request with 422 and one ``FieldError`` per invalid field.

    Args:
        _: The HTTP request (unused).
        exc: The validation error.

    Returns:
        The 422 ``ErrorResponse``.
    """
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    fields = [FieldError(loc=e["loc"], msg=e["msg"], type=e["type"]) for e in errors]
    body = ErrorResponse(error="validation_error", detail="request is invalid", fields=fields)
    return JSONResponse(body.model_dump(), status_code=422)


def v1_openapi(app: FastAPI) -> dict[str, Any]:
    """Build the OpenAPI document of the ``/api/v1`` operations only (no MCP, health or UI).

    Args:
        app: The app.

    Returns:
        The OpenAPI document, with each operation's description cut before its Python sections.
    """
    routes = [
        ctx
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute) and (ctx.path or "").startswith(V1_PREFIX)
    ]
    # `version` is the API version, not the release, so the committed document only changes
    # when the API does.
    document = get_openapi(title="ExactDocs REST API", version="1", routes=routes)
    for operations in document.get("paths", {}).values():
        for operation in operations.values():
            if "description" in operation:
                operation["description"] = _without_sections(operation["description"])
    return document


def _without_sections(docstring: str) -> str:
    """Cut a handler's docstring before its ``Args:`` / ``Returns:`` / ``Raises:`` sections.

    They document the Python function, not the HTTP operation (FastMCP drops them the same way).

    Args:
        docstring: The description FastAPI took from the handler's docstring.

    Returns:
        The text before the first section, without trailing blank lines.
    """
    lines = docstring.splitlines()
    end = next((i for i, line in enumerate(lines) if line.strip() in DOCSTRING_SECTIONS), None)
    return "\n".join(lines[:end]).rstrip() if end is not None else docstring


def v1_openapi_json(app: FastAPI) -> str:
    """Render the document as the committed ``web/openapi.json``.

    Args:
        app: The app.

    Returns:
        The document as indented JSON, ending in a newline.
    """
    return json.dumps(v1_openapi(app), indent=2) + "\n"


@dataclass(slots=True)  # conventions: allow-mutable-dataclass, allow-positional -- middleware
class SetupGuard:
    """Refuse everything under ``/api/v1`` with 403 ``setup_required`` until an account exists.

    Deny by default: a new route is guarded without anyone remembering to guard it. The
    ``setup_required`` check hits the database only while it is true; an account is never
    removed in the MVP, so the first ``False`` is remembered for the life of the process.

    Only ``/api/v1`` is guarded (every method, HEAD and OPTIONS included). ``/mcp`` and
    ``/.well-known`` are guarded by their own API-token check
    (``identity.adapters.driving.mcp``).
    """

    app: ASGIApp
    """The wrapped app."""
    setup_required: Callable[[], Awaitable[bool]]
    """Tell whether the instance still has no account."""
    _done: bool = False
    """Set once an account exists; the database is not asked again."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, or answer 403 while the instance has no account.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        if scope["type"] == "http" and await self._refuse(scope["method"], scope["path"]):
            body = ErrorResponse(
                error="setup_required",
                detail="create the first admin account (POST /api/v1/setup) before using the API",
            )
            response = JSONResponse(body.model_dump(), status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _refuse(self, method: str, path: str) -> bool:
        """Tell whether a request must wait for the first account.

        Args:
            method: The HTTP method.
            path: The request path.

        Returns:
            ``True`` for a guarded, non-exempt ``/api/v1`` request while setup is required.
        """
        if self._done or not (path == V1_PREFIX or path.startswith(f"{V1_PREFIX}/")):
            return False
        if (method, path) in SETUP_EXEMPT:
            return False
        if await self.setup_required():
            return True
        self._done = True
        return False
