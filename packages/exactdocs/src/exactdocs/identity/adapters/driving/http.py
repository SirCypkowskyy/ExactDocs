"""REST adapter for identity: the first-run setup, the browser session and "who is the caller"."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, TypedDict

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import APIKeyCookie

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    SessionState,
)
from exactdocs.identity.ports.driving import (
    CreateFirstAdmin,
    GetSessionState,
    IdentifyCaller,
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

type CurrentCaller = Callable[..., Awaitable[AccountSummary]]


def build_current_caller(*, identify_caller: IdentifyCaller) -> CurrentCaller:
    """Return the FastAPI dependency that answers "who is calling?" (401 when nobody is).

    Depend on it to require a signed-in caller (``Depends(current_caller)``); a route that needs
    the account takes ``caller: Annotated[AccountSummary, Depends(current_caller)]``. It is the one
    place that learns how a request proves who it is (today: the session cookie).
    """

    async def current_caller(
        session_token: Annotated[str | None, Depends(_session_cookie)] = None,
    ) -> AccountSummary:
        return await identify_caller(session_token)

    return current_caller


def build_router(
    *,
    create_first_admin: CreateFirstAdmin,
    sign_in: SignIn,
    sign_out: SignOut,
    get_session_state: GetSessionState,
    secure_cookies: bool,
) -> APIRouter:
    """Expose the routes that need no session: ``/setup`` and ``/session`` (sign in, state, out).

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

    @router.post("/session", status_code=201)
    async def create_session(
        query: AuthenticateQuery, request: Request, response: Response
    ) -> SessionState:
        grant = await sign_in(query, request.cookies.get(SESSION_COOKIE))
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
