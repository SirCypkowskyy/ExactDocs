from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import Scope

from exactdocs import __version__
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.catalog.adapters.driving import http as catalog_http
from exactdocs.retrieval.adapters.driving import http as retrieval_http
from exactdocs_kernel import ConflictError, DomainError, NotFoundError, ValidationError

# Built web UI, copied into the package by CI / the Docker build (see web/README.md).
WEB_DIST = Path(__file__).parent.parent / "_web"

_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ValidationError: 422,
}


class Health(BaseModel):
    """Liveness payload."""

    status: str
    version: str


def create_app(container: Container) -> FastAPI:
    """Build the single HTTP service: REST API, MCP (Streamable HTTP) and the web UI."""
    mcp_app = build_mcp(container).http_app(path="/mcp")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        async with mcp_app.lifespan(mcp_app):
            yield

    app = FastAPI(title="ExactDocs", version=__version__, lifespan=lifespan)
    app.add_exception_handler(DomainError, _domain_error_handler)

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["system"])
    async def health() -> Health:
        return Health(status="ok", version=__version__)

    v1 = APIRouter(prefix="/v1")
    v1.include_router(
        catalog_http.build_router(
            list_libraries=container.catalog.list_libraries,
            get_library=container.catalog.get_library,
        )
    )
    v1.include_router(retrieval_http.build_router(search_docs=container.retrieval.search_docs))
    api.include_router(v1)
    app.include_router(api)

    # Exact route (no /mcp -> /mcp/ redirect); the MCP app keeps its own middleware.
    app.router.routes.append(Route("/mcp", endpoint=mcp_app))
    if WEB_DIST.is_dir():
        app.mount("/", SpaStaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


async def _domain_error_handler(_: Request, exc: Exception) -> Response:
    status = next((s for t, s in _STATUS_BY_ERROR.items() if isinstance(exc, t)), 400)
    code = exc.code if isinstance(exc, DomainError) else "error"
    return JSONResponse({"error": code, "detail": str(exc)}, status_code=status)


class SpaStaticFiles(StaticFiles):
    """Serve the built UI; unknown paths fall back to ``index.html`` for client routing."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Return the file, or the SPA shell when it does not exist."""
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith(("api/", "mcp")):  # ruff: ignore[magic-value-comparison]
                raise
            return await super().get_response("index.html", scope)
