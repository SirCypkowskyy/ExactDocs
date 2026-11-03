from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from exactdocs import __version__
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.catalog.adapters.driving import http as catalog_http
from exactdocs.retrieval.adapters.driving import http as retrieval_http
from exactdocs_kernel import ConflictError, DomainError, NotFoundError, ValidationError

# Built web UI, copied into the package by CI / the Docker build (see web/README.md).
WEB_DIST = Path(__file__).parent.parent / "_web"
MCP_PATH = "/mcp"

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
    settings = container.settings
    mcp_app = build_mcp(container).http_app(
        path=MCP_PATH,
        # DNS-rebinding guard: only localhost plus the hosts/origins the operator configured.
        host_origin_protection=True,
        allowed_hosts=settings.allowed_hosts or None,
        allowed_origins=settings.allowed_origins or None,
    )

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

    # Exact routes, no redirects; the MCP app keeps its own middleware. `/mcp/` is what some
    # hosts (e.g. ChatGPT) are configured with.
    app.router.routes.append(Route(MCP_PATH, endpoint=mcp_app))
    app.router.routes.append(Route(f"{MCP_PATH}/", endpoint=_RewritePath(mcp_app, MCP_PATH)))
    if WEB_DIST.is_dir():
        # SPA: `index.html` only for HTML navigation requests; API and assets keep real 404s.
        app.frontend("/", directory=WEB_DIST, fallback="index.html")
    return app


@dataclass(frozen=True, slots=True)
class _RewritePath:
    """ASGI wrapper that serves another path's app (an alias without a redirect)."""

    app: ASGIApp
    path: str

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        aliased = {**scope, "path": self.path, "raw_path": self.path.encode()}
        await self.app(aliased, receive, send)


async def _domain_error_handler(_: Request, exc: Exception) -> Response:
    status = next((s for t, s in _STATUS_BY_ERROR.items() if isinstance(exc, t)), 400)
    code = exc.code if isinstance(exc, DomainError) else "error"
    return JSONResponse({"error": code, "detail": str(exc)}, status_code=status)
