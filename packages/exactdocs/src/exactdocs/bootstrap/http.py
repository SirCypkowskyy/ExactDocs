import asyncio
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from exactdocs import __version__
from exactdocs.bootstrap.constants import (
    _UNSAFE_METHODS,
    HEALTH_ALIAS_PATH,
    LIVENESS_PATH,
    MCP_PATH,
    OPENAPI_PATH,
    PROBE_TIMEOUT_SECONDS,
    READINESS_PATH,
    WEB_DIST,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import current_revision, ping
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.rest import SetupGuard, add_error_handlers, error_responses, v1_openapi
from exactdocs.catalog.adapters.driving import http as catalog_http
from exactdocs.identity.adapters.driving import http as identity_http
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.ingestion.adapters.driving import http as ingestion_http
from exactdocs.retrieval.adapters.driving import http as retrieval_http


class Health(BaseModel):
    """Liveness payload: the process answers. The database details are best effort."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: Literal["ok"]
    """Always `ok`: an answer at all means the process is up."""
    version: str
    """The ExactDocs version serving."""
    database_reachable: bool
    """The database answered this check; when false, the fields below are null or false."""
    schema_revision: str | None
    """Alembic revision the database is at; null before the first migration or when unreachable."""
    search_index_format: int | None
    """Format the stored search index was built in; null when none is recorded."""
    reindex_required: bool
    """The index is in an older or unrecorded format: run `exactdocs reindex` (it keeps serving)."""


class Readiness(BaseModel):
    """Readiness payload: whether this instance can serve requests now."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: Literal["ready", "not_ready"]
    """`ready` (HTTP 200) or `not_ready` (HTTP 503)."""
    reason: str | None = None
    """Why it is not ready, as a short sentence; null when ready."""


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

    app.include_router(_probes(container))

    v1 = APIRouter(prefix="/v1", responses=error_responses())
    # Reachable without a caller: setup, sign-in/state/out, token login. A test pins this list.
    v1.include_router(
        identity_http.build_router(
            create_first_admin=container.identity.create_first_admin,
            sign_in=container.identity.sign_in,
            sign_out=container.identity.sign_out,
            get_session_state=container.identity.get_session_state,
            login_for_token=container.identity.login_for_token,
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
            resolve_renamed_path=container.catalog.resolve_renamed_path,
            get_asset=container.catalog.get_asset,
            update_library=container.catalog.update_library,
            pin_default_version=container.catalog.pin_default_version,
        )
    )
    protected.include_router(
        retrieval_http.build_router(
            search_docs=container.retrieval.search_docs,
            search_all_libraries=container.retrieval.search_all_libraries,
            read_chunk=container.retrieval.read_chunk,
            resolve_library_id=container.retrieval.resolve_library_id,
            query_docs=container.retrieval.query_docs,
        )
    )
    protected.include_router(
        ingestion_http.build_router(
            get_job=container.ingestion.get_job,
            get_library_access=container.ingestion.get_library_access,
            list_latest_jobs=container.ingestion.list_latest_jobs,
            list_library_jobs=container.ingestion.list_library_jobs,
            check_repository=container.ingestion.check_repository,
            list_repository_refs=container.ingestion.list_repository_refs,
            preview_repository=container.ingestion.preview_repository,
            add_library=container.ingestion.add_library,
            add_version=container.ingestion.add_version,
            require_session=require_session,
            remove_version=container.ingestion.remove_version,
            remove_library=container.ingestion.remove_library,
            sync_library=container.ingestion.sync_library,
            reimport_version=container.ingestion.reimport_version,
            tag_article=container.ingestion.tag_article,
            update_library_settings=container.ingestion.update_library_settings,
        )
    )
    protected.include_router(
        ingestion_http.build_auto_sync_router(
            get_auto_sync=container.ingestion.get_auto_sync,
            set_auto_sync=container.ingestion.set_auto_sync,
            disable_auto_sync=container.ingestion.disable_auto_sync,
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
    app.router.routes.append(
        Route(f"{MCP_PATH}/", endpoint=_RewritePath(app=mcp_app, path=MCP_PATH))
    )
    if WEB_DIST.is_dir():
        # SPA: `index.html` only for HTML navigation requests; API and assets keep real 404s.
        app.frontend("/", directory=WEB_DIST, fallback="index.html")
    return app


def _probes(container: Container) -> APIRouter:
    """Liveness and readiness probes for orchestrators.

    Outside ``/api/v1``, so neither sign-in nor the setup guard applies to them.

    Args:
        container: The instance whose database the probes ask.

    Returns:
        The router serving ``/healthz`` (and its alias ``/api/health``) and ``/readyz``.
    """
    router = APIRouter(tags=["system"])

    @router.get(LIVENESS_PATH)
    @router.get(HEALTH_ALIAS_PATH)
    async def health() -> Health:
        """Liveness: answers 200 while the process runs, even when the database does not.

        Returns:
            The version, and what the database says about its schema and search index.
        """
        try:
            async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
                revision = await current_revision(container.engine)
                index = await container.retrieval.get_search_index_state()
        except SQLAlchemyError, OSError, TimeoutError:
            return Health(
                status="ok",
                version=__version__,
                database_reachable=False,
                schema_revision=None,
                search_index_format=None,
                reindex_required=False,
            )
        return Health(
            status="ok",
            version=__version__,
            database_reachable=True,
            schema_revision=revision,
            search_index_format=index.stored_format,
            reindex_required=index.needs_rebuild,
        )

    @router.get(READINESS_PATH, responses={503: {"model": Readiness}})
    async def readiness(response: Response) -> Readiness:
        """Readiness: 200 when the database answers a query, 503 otherwise.

        Args:
            response: The response, whose status turns 503 when not ready.

        Returns:
            Whether the instance is ready, and why not.
        """
        try:
            async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
                await ping(container.engine)
        except SQLAlchemyError, OSError, TimeoutError:
            response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
            return Readiness(status="not_ready", reason="the database is unreachable")
        return Readiness(status="ready")

    return router


def _operation_id(route: APIRoute) -> str:
    """Short, stable OpenAPI operation IDs for generated clients: `catalog-list_all`."""
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"


def _route_paths(routes: Iterable[object]) -> list[str]:
    return [path for route in routes if isinstance(path := getattr(route, "path", None), str)]


@dataclass(frozen=True, slots=True, kw_only=True)
class _RewritePath:
    """ASGI wrapper that serves another path's app (an alias without a redirect)."""

    app: ASGIApp
    path: str

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        aliased = {**scope, "path": self.path, "raw_path": self.path.encode()}
        await self.app(aliased, receive, send)


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- middleware
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
