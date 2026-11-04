from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from exactdocs import __version__
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import current_revision
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.rest import (
    ERROR_RESPONSES,
    OPENAPI_PATH,
    SetupGuard,
    add_error_handlers,
    v1_openapi,
)
from exactdocs.catalog.adapters.driving import http as catalog_http
from exactdocs.identity.adapters.driving import http as identity_http
from exactdocs.identity.adapters.driving.http import SESSION_COOKIE
from exactdocs.ingestion.adapters.driving import http as ingestion_http
from exactdocs.retrieval.adapters.driving import http as retrieval_http

# Built web UI, copied into the package by CI / the Docker build (see web/README.md).
WEB_DIST = Path(__file__).parent.parent / "_web"
MCP_PATH = "/mcp"


class Health(BaseModel):
    """Liveness payload."""

    status: str
    version: str
    schema_revision: str | None


def create_app(container: Container) -> FastAPI:
    """Build the single HTTP service: REST API, MCP (Streamable HTTP) and the web UI."""
    settings = container.settings
    mcp_app = build_mcp(container).http_app(
        path=MCP_PATH,
        # No server-initiated requests are needed, and stateless sessions let several
        # processes serve one instance (TEAM-01).
        stateless_http=True,
        host_origin_protection=True,
        allowed_hosts=settings.allowed_hosts or None,
        allowed_origins=settings.allowed_origins or None,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        async with container.running(), mcp_app.lifespan(mcp_app):
            yield

    app = FastAPI(
        title="ExactDocs",
        version=__version__,
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        # No Swagger UI/ReDoc (they load assets from a CDN); the `/api/v1` description is below.
        openapi_url=None,
    )
    add_error_handlers(app)

    async def setup_required() -> bool:
        return (await container.identity.get_setup_state()).setup_required

    # Innermost, so the host and origin checks below still run first.
    app.add_middleware(SetupGuard, setup_required=setup_required)
    # DNS-rebinding guard for the whole app (REST, UI and MCP), one allowlist for all.
    app.add_middleware(
        OriginCheck,
        trusted_hosts=settings.trusted_hosts,
        allowed_origins=settings.allowed_origins,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["system"])
    async def health() -> Health:
        revision = await current_revision(container.engine)
        return Health(status="ok", version=__version__, schema_revision=revision)

    v1 = APIRouter(prefix="/v1", responses=ERROR_RESPONSES)
    # Reachable without a caller: setup and sign-in/state/out. A test pins this list.
    v1.include_router(
        identity_http.build_router(
            create_first_admin=container.identity.create_first_admin,
            sign_in=container.identity.sign_in,
            sign_out=container.identity.sign_out,
            get_session_state=container.identity.get_session_state,
            secure_cookies=settings.secure_cookies,
        )
    )
    session_caller = identity_http.build_session_caller(
        identify_caller=container.identity.identify_caller
    )
    v1.include_router(
        identity_http.build_tokens_router(
            create_token=container.identity.create_token,
            list_tokens=container.identity.list_tokens,
            revoke_token=container.identity.revoke_token,
            session_caller=session_caller,
        )
    )
    # Everything else needs a caller: a session cookie or an API token. Add new domain routers here.
    current_caller = identity_http.build_current_caller(
        identify_caller=container.identity.identify_caller,
        identify_token=container.identity.identify_token,
    )
    protected = APIRouter(dependencies=[Depends(current_caller)])

    async def require_session(request: Request) -> None:
        """Sign-in by cookie only (401 otherwise): for what an API token must not do."""
        await session_caller(request.cookies.get(SESSION_COOKIE))

    protected.include_router(
        catalog_http.build_router(
            list_libraries=container.catalog.list_libraries,
            get_library=container.catalog.get_library,
            resolve_version=container.catalog.resolve_version,
            list_articles=container.catalog.list_articles,
            list_tags=container.catalog.list_tags,
            get_article=container.catalog.get_article,
            update_library=container.catalog.update_library,
        )
    )
    protected.include_router(
        retrieval_http.build_router(
            search_docs=container.retrieval.search_docs,
            read_chunk=container.retrieval.read_chunk,
        )
    )
    protected.include_router(
        ingestion_http.build_router(
            get_job=container.ingestion.get_job,
            list_latest_jobs=container.ingestion.list_latest_jobs,
            list_library_jobs=container.ingestion.list_library_jobs,
            check_repository=container.ingestion.check_repository,
            list_repository_refs=container.ingestion.list_repository_refs,
            add_library=container.ingestion.add_library,
            add_version=container.ingestion.add_version,
            require_session=require_session,
            remove_version=container.ingestion.remove_version,
            remove_library=container.ingestion.remove_library,
            sync_library=container.ingestion.sync_library,
        )
    )
    v1.include_router(protected)
    api.include_router(v1)
    app.include_router(api)

    @app.get(OPENAPI_PATH, include_in_schema=False)
    async def openapi_v1() -> dict[str, Any]:
        return v1_openapi(app)

    # Every route of the MCP app (the endpoint, and OAuth/.well-known routes once auth is on)
    # is served as-is, keeping the MCP app's own middleware; `/mcp/` is an alias some hosts
    # (e.g. ChatGPT) are configured with.
    for path in _route_paths(mcp_app.routes):
        app.router.routes.append(Route(path, endpoint=mcp_app))
    app.router.routes.append(Route(f"{MCP_PATH}/", endpoint=_RewritePath(mcp_app, MCP_PATH)))
    if WEB_DIST.is_dir():
        # SPA: `index.html` only for HTML navigation requests; API and assets keep real 404s.
        app.frontend("/", directory=WEB_DIST, fallback="index.html")
    return app


def _operation_id(route: APIRoute) -> str:
    """Short, stable OpenAPI operation IDs for generated clients: `catalog-list_all`."""
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"


def _route_paths(routes: Iterable[object]) -> list[str]:
    return [path for route in routes if isinstance(path := getattr(route, "path", None), str)]


@dataclass(frozen=True, slots=True)
class _RewritePath:
    """ASGI wrapper that serves another path's app (an alias without a redirect)."""

    app: ASGIApp
    path: str

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        aliased = {**scope, "path": self.path, "raw_path": self.path.encode()}
        await self.app(aliased, receive, send)


_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True, slots=True)
class OriginCheck:
    """Reject state-changing browser requests from foreign origins (CSRF / DNS rebinding).

    Requests without an ``Origin`` header (CLI, MCP clients, curl) pass; browsers always send
    one on cross-site unsafe requests.
    """

    app: ASGIApp
    trusted_hosts: list[str]
    allowed_origins: list[str]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, or answer 403 for an unsafe request from a foreign origin."""
        if scope["type"] == "http" and scope["method"] in _UNSAFE_METHODS:
            origin = dict(scope["headers"]).get(b"origin", b"").decode()
            if origin and not self._allowed(origin):
                response = PlainTextResponse("Origin not allowed", status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _allowed(self, origin: str) -> bool:
        return origin in self.allowed_origins or urlsplit(origin).hostname in self.trusted_hosts
