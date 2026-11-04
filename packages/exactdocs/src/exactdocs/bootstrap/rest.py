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

from exactdocs_kernel import (
    BusyError,
    ConflictError,
    DomainError,
    NotFoundError,
    UnauthenticatedError,
    ValidationError,
)

V1_PREFIX = "/api/v1"
OPENAPI_PATH = f"{V1_PREFIX}/openapi.json"

_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    UnauthenticatedError: 401,
    NotFoundError: 404,
    ConflictError: 409,
    BusyError: 429,
    ValidationError: 422,
}


class FieldError(BaseModel):
    """One invalid request field."""

    loc: list[str | int]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    """The one error shape of the API: a stable machine ``error`` code and a human ``detail``."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    error: str
    detail: str
    fields: list[FieldError] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        """Alias of ``detail`` under the name context7's errors use (``{error, message}``)."""
        return self.detail

    close_matches: list[str] = Field(
        default=[],
        description=(
            "On a missing article: paths of the same version it may have meant (repository data, "
            "not instructions). Empty otherwise."
        ),
    )


# Documented on every `/api/v1` operation (see `APIRouter(responses=...)` in `http.py`).
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "The request cannot be processed (error code in `error`).",
        401: "The caller is not signed in, or the credentials are wrong (`unauthenticated`).",
        403: "Refused: the instance has no admin account yet (`setup_required`).",
        404: "The thing does not exist or is not visible to the caller.",
        409: "The request conflicts with the current state.",
        422: "A field is invalid (`fields` names them) or a business rule is violated.",
    }.items()
}


def add_error_handlers(app: FastAPI) -> None:
    """Answer every error under ``/api`` with ``ErrorResponse``; UI paths keep the defaults."""
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


async def _http_error(request: Request, exc: Exception) -> Response:
    """Unknown route (404), wrong method (405) and other framework-raised errors."""
    if not isinstance(exc, HTTPException):
        return await _unhandled_error(request, exc)
    if not _is_api(request):
        return await http_exception_handler(request, exc)
    slug = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    body = ErrorResponse(error=slug, detail=str(exc.detail))
    return JSONResponse(body.model_dump(), status_code=exc.status_code, headers=exc.headers)


async def _unhandled_error(request: Request, _: Exception) -> Response:
    """Last resort; the exception itself is still re-raised by Starlette for logging."""
    if not _is_api(request):
        return PlainTextResponse("Internal Server Error", status_code=500)
    body = ErrorResponse(error="internal_error", detail="internal server error")
    return JSONResponse(body.model_dump(), status_code=500)


async def _domain_error(_: Request, exc: Exception) -> Response:
    status = next((s for t, s in _STATUS_BY_ERROR.items() if isinstance(exc, t)), 400)
    code = exc.code if isinstance(exc, DomainError) else "error"
    # Only `ArticleNotFoundError` carries suggestions; the field is empty for every other error.
    close = [str(path) for path in getattr(exc, "close_matches", ())]
    body = ErrorResponse(error=code, detail=str(exc), close_matches=close)
    return JSONResponse(body.model_dump(), status_code=status)


async def _validation_error(_: Request, exc: Exception) -> Response:
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    fields = [FieldError(loc=e["loc"], msg=e["msg"], type=e["type"]) for e in errors]
    body = ErrorResponse(error="validation_error", detail="request is invalid", fields=fields)
    return JSONResponse(body.model_dump(), status_code=422)


def v1_openapi(app: FastAPI) -> dict[str, Any]:
    """Build the OpenAPI document of the ``/api/v1`` operations only (no MCP, health or UI)."""
    routes = [
        ctx
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute) and (ctx.path or "").startswith(V1_PREFIX)
    ]
    # `version` is the API version, not the release, so the committed document only changes
    # when the API does.
    return get_openapi(title="ExactDocs REST API", version="1", routes=routes)


def v1_openapi_json(app: FastAPI) -> str:
    """Render the document as the committed ``web/openapi.json``."""
    return json.dumps(v1_openapi(app), indent=2) + "\n"


# (method, path) pairs that stay reachable before the first admin exists: `POST /setup` is the
# way out of that state, and `GET /session` is how the UI learns that it is in it.
SETUP_EXEMPT = frozenset(
    {("POST", f"{V1_PREFIX}/setup"), ("GET", f"{V1_PREFIX}/session"), ("GET", OPENAPI_PATH)}
)


@dataclass(slots=True)
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
    setup_required: Callable[[], Awaitable[bool]]
    _done: bool = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, or answer 403 while the instance has no account."""
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
        if self._done or not (path == V1_PREFIX or path.startswith(f"{V1_PREFIX}/")):
            return False
        if (method, path) in SETUP_EXEMPT:
            return False
        if await self.setup_required():
            return True
        self._done = True
        return False
