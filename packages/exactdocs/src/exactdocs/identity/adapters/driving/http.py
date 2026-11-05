"""REST adapter for identity: the first-run setup, the browser session and "who is the caller"."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, TypedDict

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    LoginForTokenCommand,
    SessionState,
    TokenGrant,
    TokenList,
)
from exactdocs.identity.errors import InvalidTokenError
from exactdocs.identity.ports.driving import (
    CreateFirstAdmin,
    CreateToken,
    GetSessionState,
    IdentifyCaller,
    IdentifyToken,
    ListTokens,
    LoginForToken,
    RevokeToken,
    SignIn,
    SignOut,
)

SESSION_COOKIE = "exactdocs_session"
# Only `/api` needs the cookie (the UI itself is static), so the browser never sends it to `/mcp`.
COOKIE_PATH = "/api"


class _CookieAttrs(TypedDict):
    path: str
    httponly: bool
    samesite: Literal["lax"]


# Shared by `set_cookie` and `delete_cookie`: a deletion only works if the attributes match.
COOKIE_ATTRS: _CookieAttrs = {"path": COOKIE_PATH, "httponly": True, "samesite": "lax"}

# `auto_error=False`: a missing cookie reaches `IdentifyCaller`, which raises the API's own 401.
_session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="SessionCookie",
    description="The HttpOnly cookie set by `POST /api/v1/session`.",
    auto_error=False,
)

# Only documents the scheme in OpenAPI; `current_caller` reads the raw header itself, so that
# `Authorization: Bearer ` (empty) or any odd value is still refused rather than skipped.
_api_token = HTTPBearer(
    scheme_name="ApiToken",
    description="An API token from `POST /api/v1/tokens`: `Authorization: Bearer exd_...`.",
    auto_error=False,
)

type CurrentCaller = Callable[..., Awaitable[AccountSummary]]

# The sign-in throttle's answer, on the two routes that check a password. The body is the API's
# shared error shape, referenced by name (it is defined by the app, not by this domain).
_THROTTLED: dict[int | str, dict[str, object]] = {
    429: {
        "description": (
            "Too many failed sign-ins (`rate_limited`); try again after `Retry-After` seconds."
        ),
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait before the next attempt.",
                "schema": {"type": "integer"},
            }
        },
    }
}


def client_address(request: Request) -> str | None:
    """Return the caller's IP address, for the sign-in throttle.

    Behind a reverse proxy this is already the address the proxy reports: ``exactdocs serve``
    runs uvicorn with its proxy headers on, which takes ``X-Forwarded-For`` from the proxies
    in ``EXACTDOCS_FORWARDED_ALLOW_IPS`` only (anyone else cannot choose their own address).
    """
    return request.client.host if request.client else None


def build_session_caller(*, identify_caller: IdentifyCaller) -> CurrentCaller:
    """Return the dependency that accepts the session cookie only (401 otherwise)."""

    async def session_caller(
        session_token: Annotated[str | None, Depends(_session_cookie)] = None,
    ) -> AccountSummary:
        return await identify_caller(session_token)

    return session_caller


def build_current_caller(
    *, identify_caller: IdentifyCaller, identify_token: IdentifyToken
) -> CurrentCaller:
    """Return the FastAPI dependency that answers "who is calling?" (401 when nobody is).

    Depend on it to require a caller (``Depends(current_caller)``); a route that needs the
    account takes ``caller: Annotated[AccountSummary, Depends(current_caller)]``. It is the one
    place that learns how a request proves who it is: an API token in ``Authorization: Bearer``,
    or else the session cookie. A bearer token that is wrong is refused outright, never
    quietly replaced by a cookie that happens to be there.
    """
    session_caller = build_session_caller(identify_caller=identify_caller)

    async def current_caller(
        request: Request,
        _documented: Annotated[HTTPAuthorizationCredentials | None, Depends(_api_token)] = None,
        session_token: Annotated[str | None, Depends(_session_cookie)] = None,
    ) -> AccountSummary:
        authorization = request.headers.get("authorization")
        if authorization is not None:
            scheme, _, credentials = authorization.partition(" ")
            if scheme.lower() != "bearer":
                raise InvalidTokenError
            return await identify_token(credentials.strip())
        return await session_caller(session_token)

    return current_caller


def build_tokens_router(
    *,
    create_token: CreateToken,
    list_tokens: ListTokens,
    revoke_token: RevokeToken,
    session_caller: CurrentCaller,
) -> APIRouter:
    """Expose ``/tokens``. Managing tokens takes a signed-in session, not a token.

    So a leaked token cannot mint itself a successor that outlives its own revocation.
    """
    router = APIRouter(tags=["identity"], dependencies=[Depends(session_caller)])
    caller = Annotated[AccountSummary, Depends(session_caller)]

    @router.post("/tokens", status_code=201)
    async def create(
        command: CreateTokenCommand, account: caller, response: Response
    ) -> TokenGrant:
        response.headers["Cache-Control"] = "no-store"  # the one time the secret is shown
        return await create_token(account, command)

    @router.get("/tokens")
    async def list_all(account: caller) -> TokenList:
        return await list_tokens(account)

    @router.delete("/tokens/{token_id}", status_code=204)
    async def revoke(token_id: str, account: caller) -> None:
        await revoke_token(account, token_id)

    return router


def build_router(
    *,
    create_first_admin: CreateFirstAdmin,
    sign_in: SignIn,
    sign_out: SignOut,
    get_session_state: GetSessionState,
    login_for_token: LoginForToken,
    secure_cookies: bool,
) -> APIRouter:
    """Expose the routes that need no session: ``/setup``, ``/session`` and ``/tokens/login``.

    ``/session`` signs in, reports the state and signs out; ``/tokens/login`` trades credentials
    for an API token (the CLI's login).

    ``secure_cookies`` forces the ``Secure`` attribute; without it the cookie is ``Secure``
    whenever the request came in over HTTPS. The cookie is HttpOnly (script never reads it) and
    SameSite=Lax (not sent on cross-site POST/DELETE; Origin is checked too). Its ``max_age`` is
    the 30-day absolute limit; the 7-day idle expiry is enforced on the server only, so the browser
    may keep a cookie the server already rejects.
    """
    router = APIRouter(tags=["identity"])

    def secure(request: Request) -> bool:
        return secure_cookies or request.url.scheme == "https"

    @router.post("/setup", status_code=201)
    async def setup(command: CreateFirstAdminCommand) -> AccountSummary:
        return await create_first_admin(command)

    @router.get("/session")
    async def get_session(request: Request, response: Response) -> SessionState:
        response.headers["Cache-Control"] = "no-store"
        return await get_session_state(request.cookies.get(SESSION_COOKIE))

    @router.post("/tokens/login", status_code=201, responses=_THROTTLED)
    async def login(
        command: LoginForTokenCommand, request: Request, response: Response
    ) -> TokenGrant:
        """Exchange a username and password for a new API token (what ``exactdocs login`` does)."""
        response.headers["Cache-Control"] = "no-store"  # the one time the secret is shown
        return await login_for_token(command, client=client_address(request))

    @router.post("/session", status_code=201, responses=_THROTTLED)
    async def create_session(
        query: AuthenticateQuery, request: Request, response: Response
    ) -> SessionState:
        grant = await sign_in(
            query, request.cookies.get(SESSION_COOKIE), client=client_address(request)
        )
        response.set_cookie(
            SESSION_COOKIE,
            grant.token.get_secret_value(),
            max_age=grant.max_age,
            secure=secure(request),
            **COOKIE_ATTRS,
        )
        response.headers["Cache-Control"] = "no-store"
        return SessionState(state="signed_in", account=grant.account)

    @router.delete("/session", status_code=204)
    async def delete_session(request: Request, response: Response) -> None:
        # Always succeeds, signed in or not: signing out twice is not an error.
        if token := request.cookies.get(SESSION_COOKIE):
            await sign_out(token)
        response.delete_cookie(SESSION_COOKIE, secure=secure(request), **COOKIE_ATTRS)

    return router
