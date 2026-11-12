"""REST adapter for identity: the first-run setup, the browser session and "who is the caller"."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from exactdocs.identity.constants import (
    _THROTTLED,
    COOKIE_ATTRS,
    CREATE_TOKEN_DESCRIPTION,
    LOGIN_FOR_TOKEN_DESCRIPTION,
    SESSION_COOKIE,
)
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


def client_address(request: Request) -> str | None:
    """Return the caller's IP address, for the sign-in throttle.

    Behind a reverse proxy this is already the address the proxy reports: ``exactdocs serve``
    runs uvicorn with its proxy headers on, which takes ``X-Forwarded-For`` from the proxies
    in ``EXACTDOCS_FORWARDED_ALLOW_IPS`` only (anyone else cannot choose their own address).

    Args:
        request: The HTTP request.

    Returns:
        The client's IP address, or ``None`` when the transport reports none.
    """
    return request.client.host if request.client else None


def build_session_caller(*, identify_caller: IdentifyCaller) -> CurrentCaller:
    """Return the dependency that accepts the session cookie only (401 otherwise).

    Args:
        identify_caller: The driving port that resolves a session token.

    Returns:
        The dependency.
    """

    async def session_caller(
        session_token: Annotated[str | None, Depends(_session_cookie)] = None,
    ) -> AccountSummary:
        """Resolve the request's session cookie to its account.

        Args:
            session_token: The session cookie, if the request carried one.

        Returns:
            The signed-in account.
        """
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

    Args:
        identify_caller: The driving port that resolves a session token.
        identify_token: The driving port that resolves an API token.

    Returns:
        The dependency.
    """
    session_caller = build_session_caller(identify_caller=identify_caller)

    async def current_caller(
        request: Request,
        _documented: Annotated[HTTPAuthorizationCredentials | None, Depends(_api_token)] = None,
        session_token: Annotated[str | None, Depends(_session_cookie)] = None,
    ) -> AccountSummary:
        """Resolve the request's bearer token, or else its session cookie, to its account.

        Args:
            request: The HTTP request, for its ``Authorization`` header.
            _documented: The bearer credentials; only there to document the scheme in OpenAPI.
            session_token: The session cookie, if the request carried one.

        Returns:
            The calling account.

        Raises:
            InvalidTokenError: The ``Authorization`` header is not a bearer token.
        """
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

    Args:
        create_token: The driving port that mints a token.
        list_tokens: The driving port that lists tokens.
        revoke_token: The driving port that revokes a token.
        session_caller: The dependency that requires a signed-in session.

    Returns:
        The router.
    """
    router = APIRouter(tags=["identity"], dependencies=[Depends(session_caller)])
    caller = Annotated[AccountSummary, Depends(session_caller)]

    @router.post("/tokens", status_code=201, description=CREATE_TOKEN_DESCRIPTION)
    async def create(
        command: CreateTokenCommand, account: caller, response: Response
    ) -> TokenGrant:
        """Create an API token for the signed-in account. The secret is in this response only.

        Args:
            command: The token's name and optional expiry.
            account: The signed-in account.
            response: The HTTP response, to forbid caching it.

        Returns:
            The new token, with its secret.
        """
        response.headers["Cache-Control"] = "no-store"  # the one time the secret is shown
        return await create_token(account, command)

    @router.get("/tokens")
    async def list_all(account: caller) -> TokenList:
        """List the signed-in account's API tokens, newest first, without their secrets.

        Args:
            account: The signed-in account.

        Returns:
            The tokens.
        """
        return await list_tokens(account)

    @router.delete("/tokens/{token_id}", status_code=204)
    async def revoke(token_id: str, account: caller) -> None:
        """Revoke one of the signed-in account's API tokens; it stops working at once.

        Args:
            token_id: The token's id.
            account: The signed-in account.
        """
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

    Args:
        create_first_admin: The driving port that creates the first admin.
        sign_in: The driving port that starts a session.
        sign_out: The driving port that ends a session.
        get_session_state: The driving port that reports the session state.
        login_for_token: The driving port that trades credentials for a token.
        secure_cookies: Whether the session cookie is always ``Secure``.

    Returns:
        The router.
    """
    router = APIRouter(tags=["identity"])

    def secure(request: Request) -> bool:
        """Whether the session cookie of this request gets the ``Secure`` attribute.

        Args:
            request: The HTTP request.

        Returns:
            ``True`` when forced, or when the request came over HTTPS.
        """
        return secure_cookies or request.url.scheme == "https"

    @router.post("/setup", status_code=201)
    async def setup(command: CreateFirstAdminCommand) -> AccountSummary:
        """Create the first admin account. Refused (409) once any account exists.

        Args:
            command: The first admin's username and password.

        Returns:
            The new account.
        """
        return await create_first_admin(command)

    @router.get("/session")
    async def get_session(request: Request, response: Response) -> SessionState:
        """Tell whether setup is due, nobody is signed in, or who is.

        Args:
            request: The HTTP request, for its session cookie.
            response: The HTTP response, to forbid caching it.

        Returns:
            The setup and sign-in state.
        """
        response.headers["Cache-Control"] = "no-store"
        return await get_session_state(request.cookies.get(SESSION_COOKIE))

    @router.post(
        "/tokens/login",
        status_code=201,
        responses=_THROTTLED,
        description=LOGIN_FOR_TOKEN_DESCRIPTION,
    )
    async def login(
        command: LoginForTokenCommand, request: Request, response: Response
    ) -> TokenGrant:
        """Exchange a username and password for a new API token (what ``exactdocs login`` does).

        Args:
            command: The credentials and the new token's name and expiry.
            request: The HTTP request, for the client address.
            response: The HTTP response, to forbid caching it.

        Returns:
            The new token, with its secret.
        """
        response.headers["Cache-Control"] = "no-store"  # the one time the secret is shown
        return await login_for_token(command, client=client_address(request))

    @router.post("/session", status_code=201, responses=_THROTTLED)
    async def create_session(
        query: AuthenticateQuery, request: Request, response: Response
    ) -> SessionState:
        """Sign in: check the username and password and set the session cookie.

        Args:
            query: The username and password.
            request: The HTTP request, for the current session and the client address.
            response: The HTTP response, for the cookie.

        Returns:
            The signed-in state and account.
        """
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
        """Sign out: end the session and clear its cookie. Signing out twice is not an error.

        Args:
            request: The HTTP request, for its session cookie.
            response: The HTTP response, to clear the cookie.
        """
        if token := request.cookies.get(SESSION_COOKIE):
            await sign_out(token)
        response.delete_cookie(SESSION_COOKIE, secure=secure(request), **COOKIE_ATTRS)

    return router
