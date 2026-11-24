from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.routing import APIRoute
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from exactdocs import __version__
from exactdocs.bootstrap.caller import bind_caller, reset_caller
from exactdocs.bootstrap.constants import (
    _UNSAFE_METHODS,
    MCP_PATH,
    OPENAPI_PATH,
    WEB_DIST,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.probes import ProbeAwareHostCheck, build_probes
from exactdocs.bootstrap.rest import SetupGuard, add_error_handlers, error_responses, v1_openapi
from exactdocs.bootstrap.telemetry import build_metrics_router, is_untraced, start_telemetry
from exactdocs.catalog.adapters.driving import http as catalog_http
from exactdocs.catalog.dtos import GetLibraryQuery
from exactdocs.identity.adapters.driving import http as identity_http
from exactdocs.identity.adapters.driving.mcp import AccessAssertionAsBearer
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.dtos import AccountSummary, ApiTokenIdentity
from exactdocs.identity.models import Role
from exactdocs.ingestion.adapters.driving import http as ingestion_http
from exactdocs.retrieval.adapters.driving import http as retrieval_http
from exactdocs_kernel import ForbiddenError


def _username_of(
    current_caller: identity_http.CurrentCaller,
) -> Callable[..., Awaitable[str]]:
    """Return a FastAPI dependency naming the user of the request (who cancelled a job).

    Args:
        current_caller: The dependency that names the calling account.

    Returns:
        The dependency; FastAPI runs ``current_caller`` once per request.
    """

    async def username(account: Annotated[AccountSummary, Depends(current_caller)]) -> str:
        """Name the caller as people see it.

        Args:
            account: The caller.

        Returns:
            Its user name.
        """
        return account.username

    return username


def _include_external_sign_in_routers(v1: APIRouter, container: Container) -> None:
    """Add the routes of sign-in through an identity provider, reachable without a caller.

    The browser navigations to and back from the provider (behind the setup guard too), and the
    providers' own icons, which the sign-in page shows to people not signed in yet.

    Args:
        v1: The ``/api/v1`` router.
        container: The wired domains.
    """
    v1.include_router(
        identity_http.build_external_sign_in_router(
            start_external_sign_in=container.identity.start_external_sign_in,
            finish_external_sign_in=container.identity.finish_external_sign_in,
            secure_cookies=container.settings.cookies_always_secure,
        )
    )
    v1.include_router(
        identity_http.build_provider_icon_router(
            get_provider_icon=container.identity.get_provider_icon
        )
    )


def _include_session_routers(v1: APIRouter, container: Container) -> identity_http.CurrentCaller:
    """Add the routes that take a signed-in session and never an API token.

    ``/tokens`` (a leaked token must not mint its own successor), ``/users`` (nor create
    accounts; operators only), ``/access-log`` (operators only) and ``/account`` (nor change
    the password of the account it acts as).

    Args:
        v1: The ``/api/v1`` router.
        container: The wired domains.

    Returns:
        The dependency that requires a signed-in session, for other routes to use.
    """
    session_caller = identity_http.build_session_caller(
        identify_caller=container.identity.identify_caller,
        identify_access=container.identity.identify_access_caller,
    )
    v1.include_router(
        identity_http.build_tokens_router(
            create_token=container.identity.create_token,
            list_tokens=container.identity.list_tokens,
            revoke_token=container.identity.revoke_token,
            session_caller=session_caller,
        )
    )
    v1.include_router(
        identity_http.build_users_router(
            list_users=container.identity.list_users,
            create_user=container.identity.create_user,
            set_user_disabled=container.identity.set_user_disabled,
            reset_password=container.identity.reset_password,
            session_caller=session_caller,
        )
    )
    v1.include_router(
        identity_http.build_access_log_router(
            list_access_log=container.identity.list_access_log, session_caller=session_caller
        )
    )
    v1.include_router(
        identity_http.build_account_router(
            change_password=container.identity.change_password,
            list_account_providers=container.identity.list_account_providers,
            start_account_link=container.identity.start_account_link,
            unlink_provider=container.identity.unlink_provider,
            session_caller=session_caller,
            secure_cookies=container.settings.cookies_always_secure,
        )
    )
    return session_caller


def _protected_router(
    container: Container, current_caller: identity_http.CurrentCaller
) -> APIRouter:
    """Build the router of everything that needs a caller, with the library grants routes.

    Every route of it names the caller to the library roles (``bind_caller``), so each use case
    it reaches checks the role of whoever is calling.

    Args:
        container: The wired domains.
        current_caller: The dependency that names the calling account (session or API token).

    Returns:
        The router; domain routers are added to it.
    """

    async def bind_account(
        account: Annotated[AccountSummary, Depends(current_caller)],
    ) -> AsyncIterator[None]:
        """Tell the library roles whose request this is.

        Args:
            account: The caller (FastAPI runs ``current_caller`` once per request).

        Yields:
            Control to the protected request.
        """
        binding = bind_caller(
            account.id, api_identity=account if isinstance(account, ApiTokenIdentity) else None
        )
        try:
            yield
        finally:
            reset_caller(binding)

    async def require_library(library: str) -> None:
        """Check a sharing request's live read access before revealing its grants.

        Args:
            library: The requested library ID.
        """
        await container.catalog.get_library(GetLibraryQuery(id=library))

    router = APIRouter(dependencies=[Depends(current_caller), Depends(bind_account)])
    router.include_router(
        identity_http.build_grants_router(
            list_grants=container.identity.list_library_grants,
            grant_role=container.identity.grant_library_role,
            revoke_role=container.identity.revoke_library_role,
            list_access_log=container.identity.list_library_access_log,
            transfer=container.identity.transfer_library,
            caller=current_caller,
            require_library=require_library,
        )
    )
    return router


def create_app(container: Container) -> FastAPI:
    """Build the single HTTP service: REST API, MCP (Streamable HTTP) and the web UI.

    Args:
        container: The wired application.

    Returns:
        The ASGI app.
    """
    settings = container.settings
    # Nothing unless EXACTDOCS_TELEMETRY=otlp or EXACTDOCS_METRICS.
    start_telemetry(settings, scraped=True)
    mcp_app = build_mcp(container).http_app(
        path=MCP_PATH,
        # No server-initiated requests are needed, and stateless sessions let several
        # processes serve one instance (TEAM-01).
        stateless_http=True,
        host_origin_protection=True,
        allowed_hosts=settings.allowed_hosts or None,
        allowed_origins=settings.allowed_origins or None,
    )

    probes = build_probes(container)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        """Run the container and the MCP app for as long as the server runs.

        Args:
            _: The app (unused).

        Yields:
            Control while the server runs.
        """
        async with container.running():
            try:
                async with mcp_app.lifespan(mcp_app):
                    yield
            finally:
                # Before `running()` disposes the engine: a probe's check left running would
                # strand its connection in the discarded pool (#291).
                await probes.settle()

    app = FastAPI(
        title="ExactDocs",
        version=__version__,
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        # No Swagger UI/ReDoc (they load assets from a CDN); the `/api/v1` description is below.
        openapi_url=None,
        # FastAPI's built-in OpenTelemetry: request spans and metrics, once `start_telemetry` set
        # up an SDK (none otherwise, so none are made). It never adds exporters of its own.
        telemetry={"exclude": is_untraced, "auto_configure": False},
    )
    add_error_handlers(app)

    async def setup_required() -> bool:
        """Tell whether the instance still needs its first admin.

        Returns:
            ``True`` until the first admin exists.
        """
        return (await container.identity.get_setup_state()).setup_required

    # Innermost, so the host and origin checks below still run first.
    app.add_middleware(SetupGuard, setup_required=setup_required)
    # DNS-rebinding guard for the whole app (REST, UI and MCP), one allowlist for all.
    app.add_middleware(
        OriginCheck,
        trusted_hosts=settings.trusted_hosts,
        allowed_origins=settings.allowed_origins,
    )
    # The probes answer any Host (with no details for an untrusted one); everything else checks it.
    app.add_middleware(ProbeAwareHostCheck.wrap, trusted_hosts=settings.trusted_hosts)

    api = APIRouter(prefix="/api")

    app.include_router(probes.router)
    if settings.metrics:
        app.include_router(build_metrics_router(token=settings.metrics_token))

    v1 = APIRouter(prefix="/v1", responses=error_responses())
    # Reachable without a caller: setup, sign-in/state/out, token login (and the webhook route of
    # `_include_sync_triggers`). A test pins this list.
    v1.include_router(
        identity_http.build_router(
            create_first_admin=container.identity.create_first_admin,
            sign_in=container.identity.sign_in,
            sign_out=container.identity.sign_out,
            get_session_state=container.identity.get_session_state,
            login_for_token=container.identity.login_for_token,
            secure_cookies=settings.cookies_always_secure,
        )
    )
    _include_external_sign_in_routers(v1, container)
    session_caller = _include_session_routers(v1, container)
    # Everything else needs a caller: a session cookie or an API token. Add new domain routers here.
    current_caller = identity_http.build_current_caller(
        identify_caller=container.identity.identify_caller,
        identify_token=container.identity.identify_token,
        identify_access=container.identity.identify_access_caller,
    )

    protected = _protected_router(container, current_caller)

    async def caller_id(account: Annotated[AccountSummary, Depends(current_caller)]) -> str:
        """Name the account of the request (FastAPI runs ``current_caller`` once per request).

        Args:
            account: The caller.

        Returns:
            Its ID: whom AI spend and LLM searches are counted to.
        """
        return account.id

    async def require_session(request: Request) -> None:
        """Sign-in by cookie only (401 otherwise): for what an API token must not do.

        Args:
            request: The HTTP request, for its session cookie.
        """
        await session_caller(request, request.cookies.get(SESSION_COOKIE))

    protected.include_router(
        catalog_http.build_router(
            list_libraries=container.list_libraries,
            get_library=container.catalog.get_library,
            resolve_version=container.catalog.resolve_version,
            list_versions=container.list_versions,
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
            article_outline=container.retrieval.article_outline,
            resolve_library_id=container.retrieval.resolve_library_id,
            query_docs=container.retrieval.query_docs,
            answer_question=container.retrieval.answer_question,
            get_answer_availability=container.retrieval.get_answer_availability,
            caller=caller_id,
        )
    )
    protected.include_router(
        retrieval_http.build_library_retrieval_router(
            get_library_retrieval=container.retrieval.get_library_retrieval,
            set_library_retrieval=container.set_library_retrieval,
        )
    )
    # Instance-wide settings and spend (provider keys and URLs, every library's budgets): for a
    # signed-in operator only, as ``/users`` is. A library role is no reason to reach them.
    protected.include_router(
        retrieval_http.build_ai_router(
            list_providers=container.retrieval.list_providers,
            get_provider=container.retrieval.get_provider,
            save_provider=container.save_provider,
            delete_provider=container.retrieval.delete_provider,
            check_provider=container.retrieval.check_provider,
            list_roles=container.retrieval.list_roles,
            set_role_thinking=container.retrieval.set_role_thinking,
            estimate_embedding=container.retrieval.estimate_embedding,
            get_embedding_progress=container.retrieval.get_embedding_progress,
            get_ai_usage=container.retrieval.get_ai_usage,
            get_spend_history=container.retrieval.get_spend_history,
        ),
        dependencies=[
            Depends(
                identity_http.build_operator(
                    caller=session_caller, action="manages the instance's AI settings"
                )
            )
        ],
    )
    protected.include_router(
        ingestion_http.build_router(
            get_job=container.ingestion.get_job,
            get_library_access=container.ingestion.get_library_access,
            list_latest_jobs=container.ingestion.list_latest_jobs,
            list_jobs=container.ingestion.list_jobs,
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
            plan_sources=container.ingestion.plan_sources,
            apply_sources=container.ingestion.apply_sources,
            # A session or a token: a leaked admin token can already add and remove libraries.
            require_operator=identity_http.build_operator(
                caller=current_caller, action="applies a sources file"
            ),
            cancel_job=container.ingestion.cancel_job,
            caller_name=_username_of(current_caller),
        )
    )
    _include_sync_triggers(container, v1=v1, protected=protected, session_caller=session_caller)
    api.include_router(v1)
    app.include_router(api)

    @app.get(OPENAPI_PATH, include_in_schema=False)
    async def openapi_v1() -> dict[str, Any]:
        """Serve the OpenAPI description of ``/api/v1``.

        Returns:
            The OpenAPI document.
        """
        return v1_openapi(app)

    # Behind Cloudflare Access, its token is the bearer of an MCP request that sends none.
    served = (
        mcp_app if settings.auth.cloudflare_access is None else AccessAssertionAsBearer(app=mcp_app)
    )
    _mount_mcp(app, mcp_app, served)
    if WEB_DIST.is_dir():
        # SPA: `index.html` only for HTML navigation requests; API and assets keep real 404s.
        app.frontend("/", directory=WEB_DIST, fallback="index.html")
    return app


def _include_sync_triggers(
    container: Container,
    *,
    v1: APIRouter,
    protected: APIRouter,
    session_caller: identity_http.CurrentCaller,
) -> None:
    """Add what starts a sync without a person (the scheduled check, push webhooks), then mount.

    The routes that set a webhook secret are for operators, as ``/users`` is: an ``admin``
    signed in with a session cookie (an API token is refused with 401, anyone else with 403),
    since the answer of `PUT` reveals the secret. ``protected`` is then added to ``v1``, and
    after it the route a forge pushes to, which needs no caller, only the library's webhook
    secret (checked by the domain).

    Args:
        container: The wired application.
        v1: The ``/api/v1`` router, reachable without a caller.
        protected: The routes that need a caller; complete once this returns.
        session_caller: The dependency that requires a signed-in session.
    """

    async def require_operator(request: Request) -> None:
        """Let only an ``admin`` signed in with a session cookie through.

        Args:
            request: The HTTP request, for its session cookie.

        Raises:
            ForbiddenError: The account is not an ``admin``.
        """
        account = await session_caller(request, request.cookies.get(SESSION_COOKIE))
        if account.role != Role.ADMIN.value:
            message = "only an admin manages a library's webhook"
            raise ForbiddenError(message)

    protected.include_router(
        ingestion_http.build_auto_sync_router(
            get_auto_sync=container.ingestion.get_auto_sync,
            set_auto_sync=container.ingestion.set_auto_sync,
            disable_auto_sync=container.ingestion.disable_auto_sync,
        )
    )
    protected.include_router(
        ingestion_http.build_webhook_settings_router(
            get_webhook=container.ingestion.get_webhook,
            set_webhook=container.ingestion.set_webhook,
            disable_webhook=container.ingestion.disable_webhook,
            require_operator=require_operator,
        )
    )
    v1.include_router(protected)
    v1.include_router(
        ingestion_http.build_webhook_router(receive_webhook=container.ingestion.receive_webhook)
    )


def _mount_mcp(app: FastAPI, mcp_app: Starlette, served: ASGIApp) -> None:
    """Serve every route of the MCP app as-is, keeping the MCP app's own middleware.

    That is the endpoint, and the OAuth/.well-known routes once auth is on; `/mcp/` is an alias
    some hosts (e.g. ChatGPT) are configured with.

    Args:
        app: The HTTP service.
        mcp_app: FastMCP's Streamable HTTP app, for its routes.
        served: What serves them: the MCP app, maybe wrapped.
    """
    for path in _route_paths(mcp_app.routes):
        app.router.routes.append(Route(path, endpoint=served))
    app.router.routes.append(
        Route(f"{MCP_PATH}/", endpoint=_RewritePath(app=served, path=MCP_PATH))
    )


def _operation_id(route: APIRoute) -> str:
    """Short, stable OpenAPI operation IDs for generated clients: `catalog-list_all`.

    Args:
        route: The route.

    Returns:
        ``<first tag>-<route name>`` (``default`` when the route has no tag).
    """
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"


def _route_paths(routes: Iterable[object]) -> list[str]:
    """List the paths of the routes that have one.

    Args:
        routes: An app's routes.

    Returns:
        Their paths, in order.
    """
    return [path for route in routes if isinstance(path := getattr(route, "path", None), str)]


@dataclass(frozen=True, slots=True, kw_only=True)
class _RewritePath:
    """ASGI wrapper that serves another path's app (an alias without a redirect)."""

    app: ASGIApp
    """The app that serves ``path``."""
    path: str
    """The path the request is served as."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve the request as if it were for ``path``.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        aliased = {**scope, "path": self.path, "raw_path": self.path.encode()}
        await self.app(aliased, receive, send)


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- middleware
class OriginCheck:
    """Reject state-changing browser requests from foreign origins (CSRF / DNS rebinding).

    Requests without an ``Origin`` header (CLI, MCP clients, curl) pass; browsers always send
    one on cross-site unsafe requests.
    """

    app: ASGIApp
    """The wrapped app."""
    trusted_hosts: list[str]
    """Host names whose origins are allowed (``Settings.trusted_hosts``)."""
    allowed_origins: list[str]
    """Further origins allowed as they are (``EXACTDOCS_ALLOWED_ORIGINS``)."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass the request on, or answer 403 for an unsafe request from a foreign origin.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        if scope["type"] == "http" and scope["method"] in _UNSAFE_METHODS:
            origin = dict(scope["headers"]).get(b"origin", b"").decode()
            if origin and not self._allowed(origin):
                response = PlainTextResponse("Origin not allowed", status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _allowed(self, origin: str) -> bool:
        """Tell whether an ``Origin`` may make unsafe requests.

        Args:
            origin: The request's ``Origin`` header.

        Returns:
            Whether it is an allowed origin or its host a trusted one.
        """
        return origin in self.allowed_origins or urlsplit(origin).hostname in self.trusted_hosts
