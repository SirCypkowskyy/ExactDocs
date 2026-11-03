"""Conventions of the REST API under ``/api/v1``: the error envelope and the OpenAPI document."""

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from exactdocs_kernel import ConflictError, DomainError, NotFoundError, ValidationError

V1_PREFIX = "/api/v1"
OPENAPI_PATH = f"{V1_PREFIX}/openapi.json"

_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
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


# Documented on every `/api/v1` operation (see `APIRouter(responses=...)` in `http.py`).
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "The request cannot be processed (error code in `error`).",
        404: "The thing does not exist or is not visible to the caller.",
        409: "The request conflicts with the current state.",
        422: "A field is invalid (`fields` names them) or a business rule is violated.",
    }.items()
}


def add_error_handlers(app: FastAPI) -> None:
    """Answer every ``DomainError`` and request validation failure with ``ErrorResponse``."""
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)


async def _domain_error(_: Request, exc: Exception) -> Response:
    status = next((s for t, s in _STATUS_BY_ERROR.items() if isinstance(exc, t)), 400)
    code = exc.code if isinstance(exc, DomainError) else "error"
    return JSONResponse(ErrorResponse(error=code, detail=str(exc)).model_dump(), status_code=status)


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
