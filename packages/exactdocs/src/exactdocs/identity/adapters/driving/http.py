"""REST adapter for identity: setup, sessions, "who is the caller", tokens and the users page."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from exactdocs.identity.constants import (
    _THROTTLED,
    ACCESS_ASSERTION_HEADER,
    ACCESS_COOKIE,
    ACCESS_LOG_ACTION,
    CHANGE_PASSWORD_DESCRIPTION,
    COOKIE_ATTRS,
    CREATE_TOKEN_DESCRIPTION,
    LOGIN_FOR_TOKEN_DESCRIPTION,
    SESSION_COOKIE,
    SIGN_IN_COOKIE,
    SIGN_IN_COOKIE_PATH,
    SIGN_IN_PAGE,
    USERS_DESCRIPTION,
)
from exactdocs.identity.dtos import (
    AccessLogPage,
    AccessLogQuery,
    AccountSummary,
    AuthenticateQuery,
    ChangePasswordCommand,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    FinishExternalSignInCommand,
    GrantLibraryRoleCommand,
    GrantListQuery,
    LibraryAccessLogQuery,
    LibraryGrantList,
    LibraryGrantRequest,
    LibraryGrants,
    LibraryTransferRequest,
    ListAccessLogQuery,
    ListLibraryAccessLogQuery,
    ListLibraryGrantsQuery,
    LoginForTokenCommand,
    NewPassword,
    PasswordReset,
    ResetPasswordCommand,
    RevokeLibraryRoleCommand,
    SessionState,
    SetUserDisabledCommand,
    StartExternalSignInCommand,
    TokenGrant,
    TokenList,
    TokenListQuery,
    TransferLibraryCommand,
    UserList,
    UserListQuery,
    UserSummary,
)
from exactdocs.identity.errors import (
    InvalidTokenError,
    NotAnOperatorError,
    NotSignedInError,
    UnknownSignInProviderError,
)
from exactdocs.identity.models import Role
from exactdocs.identity.ports.driving import (
    ChangePassword,
    CreateFirstAdmin,
    CreateToken,
    CreateUser,
    FinishExternalSignIn,
    GetSessionState,
    GrantLibraryRole,
    IdentifyAccessCaller,
    IdentifyCaller,
    IdentifyToken,
    ListAccessLog,
    ListLibraryAccessLog,
    ListLibraryGrants,
    ListTokens,
    ListUsers,
    LoginForToken,
    ResetPassword,
    RevokeLibraryRole,
    RevokeToken,
    SetUserDisabled,
    SignIn,
    SignOut,
    StartExternalSignIn,
    TransferLibrary,
)
from exactdocs_kernel import DomainError

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


def access_assertion(request: Request) -> str | None:
    """Return the request's Cloudflare Access token: its header, else its cookie.

    Only a configured Access verifier trusts it (``IdentifyAccessCaller``); anyone can send one.

    Args:
        request: The HTTP request.

    Returns:
        The token, or ``None`` when the request carries none.
    """
    return request.headers.get(ACCESS_ASSERTION_HEADER) or request.cookies.get(ACCESS_COOKIE)


def build_session_caller(
    *, identify_caller: IdentifyCaller, identify_access: IdentifyAccessCaller | None = None
) -> CurrentCaller:
    """Return the dependency that accepts a browser's sign-in only (401 otherwise).

    The session cookie; without a live one, the Cloudflare Access token of the request (a
    person who passed Access is signed in by it, with no session of ExactDocs).

    Args:
        identify_caller: The driving port that resolves a session token.
        identify_access: The driving port that resolves a Cloudflare Access token.

    Returns:
        The dependency.
    """

    async def session_caller(
        request: Request,
        session_token: Annotated[str | None, Depends(_session_cookie)] = None,
    ) -> AccountSummary:
        """Resolve the request's session cookie, or else its Access token, to its account.

        Args:
            request: The HTTP request, for its Cloudflare Access token.
            session_token: The session cookie, if the request carried one.

        Returns:
            The signed-in account.

        Raises:
            NotSignedInError: Neither signs anyone in.
        """
        try:
            return await identify_caller(session_token)
        except NotSignedInError:
            assertion = access_assertion(request)
            if identify_access is None or not assertion:
                raise
            return await identify_access(assertion)

    return session_caller


def build_current_caller(
    *,
    identify_caller: IdentifyCaller,
    identify_token: IdentifyToken,
    identify_access: IdentifyAccessCaller | None = None,
) -> CurrentCaller:
    """Return the FastAPI dependency that answers "who is calling?" (401 when nobody is).

    Depend on it to require a caller (``Depends(current_caller)``); a route that needs the
    account takes ``caller: Annotated[AccountSummary, Depends(current_caller)]``. It is the one
    place that learns how a request proves who it is: an API token in ``Authorization: Bearer``,
    or else the session cookie, or else the Cloudflare Access token. A bearer token that is wrong
    is refused outright, never quietly replaced by a cookie or an Access token that happens to be
    there.

    Args:
        identify_caller: The driving port that resolves a session token.
        identify_token: The driving port that resolves an API token.
        identify_access: The driving port that resolves a Cloudflare Access token.

    Returns:
        The dependency.
    """
    session_caller = build_session_caller(
        identify_caller=identify_caller, identify_access=identify_access
    )

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
        return await session_caller(request, session_token)

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
    async def list_all(account: caller, query: Annotated[TokenListQuery, Query()]) -> TokenList:
        """List the signed-in account's API tokens, newest first, without their secrets.

        A page at a time; filter with `q`, order with `sort`; `total` counts every match.

        Args:
            account: The signed-in account.
            query: The filter, the sort, the page size and the cursor of the previous page.

        Returns:
            The page of tokens, its next cursor and the total.
        """
        return await list_tokens(account, query)

    @router.delete("/tokens/{token_id}", status_code=204)
    async def revoke(token_id: str, account: caller) -> None:
        """Revoke one of the signed-in account's API tokens; it stops working at once.

        Args:
            token_id: The token's id.
            account: The signed-in account.
        """
        await revoke_token(account, token_id)

    return router


def build_account_router(
    *, change_password: ChangePassword, session_caller: CurrentCaller
) -> APIRouter:
    """Expose ``/account``: what a signed-in person does with their own account.

    Every route needs a signed-in session (an API token is refused with 401, as for ``/tokens``:
    a leaked token must not change the password of the account it acts as).

    Args:
        change_password: The driving port that changes the caller's own password.
        session_caller: The dependency that requires a signed-in session.

    Returns:
        The router.
    """
    router = APIRouter(tags=["identity"], dependencies=[Depends(session_caller)])
    caller = Annotated[AccountSummary, Depends(session_caller)]

    @router.put(
        "/account/password",
        status_code=204,
        responses=_THROTTLED,
        description=CHANGE_PASSWORD_DESCRIPTION,
    )
    async def put_password(
        command: ChangePasswordCommand, account: caller, request: Request
    ) -> None:
        """Change the signed-in account's own password.

        Args:
            command: The current password and the new one.
            account: The signed-in account.
            request: The HTTP request, for the session cookie and the client address.
        """
        await change_password(
            account,
            command,
            session_token=request.cookies.get(SESSION_COOKIE),
            client=client_address(request),
        )

    return router


def build_operator(*, caller: CurrentCaller, action: str) -> Callable[..., Awaitable[None]]:
    """Return the dependency that lets only an ``admin`` through (403 for anyone else).

    Args:
        caller: Who may call at all: the session caller, or the session-or-token one.
        action: What only an admin does, for the 403's message.

    Returns:
        The dependency.
    """

    async def operator(account: Annotated[AccountSummary, Depends(caller)]) -> None:
        """Let only an operator through.

        Args:
            account: The calling account.

        Raises:
            NotAnOperatorError: The account is not an ``admin``.
        """
        if account.role != Role.ADMIN.value:
            raise NotAnOperatorError(action)

    return operator


def build_users_router(
    *,
    list_users: ListUsers,
    create_user: CreateUser,
    set_user_disabled: SetUserDisabled,
    reset_password: ResetPassword,
    session_caller: CurrentCaller,
) -> APIRouter:
    """Expose ``/users``: the operator's users page. There is no self-signup route.

    Every route needs a signed-in session (an API token is refused with 401, as for ``/tokens``:
    a leaked token must not be able to create accounts) of an ``admin``; anyone else gets 403.

    Args:
        list_users: The driving port that lists the accounts.
        create_user: The driving port that creates an account.
        set_user_disabled: The driving port that disables or enables an account.
        reset_password: The driving port that sets an account's password.
        session_caller: The dependency that requires a signed-in session.

    Returns:
        The router.
    """
    operator = build_operator(caller=session_caller, action="manages user accounts")
    router = APIRouter(tags=["identity"], dependencies=[Depends(operator)])

    @router.get(
        "/users",
        description=f"List the local accounts, disabled ones included, oldest first unless "
        f"`sort` says otherwise, a page at a time. Filter with `q`, `role` and `disabled`; "
        f"`total` counts every match. {USERS_DESCRIPTION}",
    )
    async def get_users(query: Annotated[UserListQuery, Query()]) -> UserList:
        """List a page of the local accounts, disabled ones included.

        Args:
            query: The filters, the sort, the page size and the cursor of the previous page.

        Returns:
            The page of accounts, its next cursor and the total.
        """
        return await list_users(query)

    @router.post("/users", status_code=201)
    async def add_user(command: CreateUserCommand) -> UserSummary:
        """Create a local account with a password the operator passes on to its owner.

        Operators only, with a session (see `GET /users`).

        Args:
            command: The new account's username, password and role.

        Returns:
            The new account.
        """
        return await create_user(command)

    @router.post("/users/{user_id}/disable")
    async def disable_user(user_id: str) -> UserSummary:
        """Disable an account: its sessions end, its tokens are revoked, and it cannot sign in.

        The last enabled admin cannot be disabled (409 `last_operator`). Disabling a disabled
        account changes nothing. Operators only, with a session (see `GET /users`).

        Args:
            user_id: The account's id.

        Returns:
            The account as it is now.
        """
        return await set_user_disabled(SetUserDisabledCommand(id=user_id, disabled=True))

    @router.post("/users/{user_id}/enable")
    async def enable_user(user_id: str) -> UserSummary:
        """Let a disabled account sign in again, with its password unchanged.

        Its revoked API tokens stay revoked. Operators only, with a session (see `GET /users`).

        Args:
            user_id: The account's id.

        Returns:
            The account as it is now.
        """
        return await set_user_disabled(SetUserDisabledCommand(id=user_id, disabled=False))

    @router.put("/users/{user_id}/password")
    async def set_user_password(user_id: str, body: NewPassword) -> PasswordReset:
        """Set a new password: every session of the account ends and its tokens are revoked.

        The username's sign-in throttle count is dropped too, so its owner can sign in with the
        new password at once (`throttle` says whether that worked). Operators only, with a
        session (see `GET /users`).

        Args:
            user_id: The account's id.
            body: The new password.

        Returns:
            The account, and what became of its sign-in throttle count.
        """
        return await reset_password(ResetPasswordCommand(id=user_id, password=body.password))

    return router


def build_access_log_router(
    *, list_access_log: ListAccessLog, session_caller: CurrentCaller
) -> APIRouter:
    """Expose ``/access-log``: the operator's log of every library's access changes.

    It needs a signed-in session of an ``admin`` (an API token is refused with 401, as for
    ``/users``); anyone else gets 403. Removed libraries' events stay in it.

    Args:
        list_access_log: The driving port that reads the log.
        session_caller: The dependency that requires a signed-in session.

    Returns:
        The router.
    """
    operator = build_operator(caller=session_caller, action=ACCESS_LOG_ACTION)
    router = APIRouter(tags=["identity"], dependencies=[Depends(operator)])
    account = Annotated[AccountSummary, Depends(session_caller)]

    @router.get("/access-log", name="list_access_log")
    async def get_access_log(
        who: account, query: Annotated[AccessLogQuery, Query()]
    ) -> AccessLogPage:
        """List the access changes of every library, newest first. Operators only.

        Creations, grants (a new role, or another one), revocations, ownership transfers and
        removals, each with who made it and when; a removed library's events stay. Filter with
        `library` and `change`; `total` counts every match.

        Args:
            who: The caller.
            query: The filters, the page size and the cursor of the previous page.

        Returns:
            The page of events, its next cursor and the total.
        """
        return await list_access_log(
            ListAccessLogQuery(caller_id=who.id, **query.model_dump(exclude_unset=True))
        )

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
            request: The HTTP request, for its session cookie and its Cloudflare Access token.
            response: The HTTP response, to forbid caching it.

        Returns:
            The setup and sign-in state.
        """
        response.headers["Cache-Control"] = "no-store"
        return await get_session_state(
            request.cookies.get(SESSION_COOKIE), access_assertion(request)
        )

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
        return SessionState(state="signed_in", account=grant.account, source="session")

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


def build_external_sign_in_router(
    *,
    start_external_sign_in: StartExternalSignIn,
    finish_external_sign_in: FinishExternalSignIn,
    secure_cookies: bool,
) -> APIRouter:
    """Expose ``/auth/{provider}/start`` and ``/auth/{provider}/callback``: sign-in through an IdP.

    Both are browser navigations (top-level ``GET``), never API calls: they answer with
    redirects. The start sets a short-lived HttpOnly, SameSite=Lax binding cookie on
    ``/api/v1/auth`` and sends the browser to the provider; the callback needs that cookie, so a
    callback another browser started (login CSRF) or one already used is refused. A refusal
    redirects to the sign-in page with ``?error=<code>``; a success sets the session cookie
    (exactly as a password sign-in does) and redirects to the path the sign-in was started
    for. An unknown provider is a 404.

    Args:
        start_external_sign_in: The driving port that starts the sign-in.
        finish_external_sign_in: The driving port that finishes it.
        secure_cookies: Whether the cookies are always ``Secure``.

    Returns:
        The router.
    """
    router = APIRouter(tags=["identity"])

    def secure(request: Request) -> bool:
        """Whether this request's cookies get the ``Secure`` attribute.

        Args:
            request: The HTTP request.

        Returns:
            ``True`` when forced, or when the request came over HTTPS.
        """
        return secure_cookies or request.url.scheme == "https"

    def refused(error: DomainError) -> RedirectResponse:
        """Send the browser back to the sign-in page, naming the refusal by its code.

        Only the code travels (never a message), so nobody can craft a link that shows the
        sign-in page saying something else.

        Args:
            error: Why the sign-in was refused.

        Returns:
            The redirect.
        """
        return _no_store(
            RedirectResponse(f"{SIGN_IN_PAGE}?{urlencode({'error': error.code})}", status_code=303)
        )

    @router.get(
        "/auth/{provider}/start",
        status_code=303,
        response_class=RedirectResponse,
        responses={303: {"description": "To the identity provider, or back to the sign-in page"}},
    )
    async def start(
        provider: str,
        request: Request,
        return_to: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> RedirectResponse:
        """Start signing in through an identity provider (a browser navigation).

        Redirects to the provider with a binding cookie; when the provider cannot be reached,
        back to the sign-in page with `?error=provider_unavailable`.

        Args:
            provider: The provider's name.
            request: The HTTP request, for the scheme.
            return_to: Where to go once signed in: a path on this server (else `/`).

        Returns:
            The redirect.

        Raises:
            UnknownSignInProviderError: No provider of this name is configured (404).
        """
        try:
            begun = await start_external_sign_in(
                StartExternalSignInCommand(provider=provider, return_to=return_to)
            )
        except UnknownSignInProviderError:
            raise
        except DomainError as error:
            return refused(error)
        response = _no_store(RedirectResponse(begun.redirect_url, status_code=303))
        response.set_cookie(
            SIGN_IN_COOKIE,
            begun.binding.get_secret_value(),
            max_age=begun.max_age,
            path=SIGN_IN_COOKIE_PATH,
            httponly=True,
            samesite="lax",
            secure=secure(request),
        )
        return response

    @router.get(
        "/auth/{provider}/callback",
        status_code=303,
        response_class=RedirectResponse,
        responses={303: {"description": "Signed in, or back to the sign-in page with `?error=`"}},
    )
    async def callback(
        provider: str,
        request: Request,
        code: Annotated[str | None, Query(max_length=4096)] = None,
        state: Annotated[str | None, Query(max_length=512)] = None,
        error: Annotated[str | None, Query(max_length=256)] = None,
    ) -> RedirectResponse:
        """Finish signing in: the identity provider sends the browser here.

        The binding cookie is cleared whatever happens. Refusals go back to the sign-in page
        with `?error=` and one of `sign_in_failed`, `sign_in_cancelled`, `not_allowed`,
        `account_disabled`, `username_unavailable` or `provider_unavailable`; no session is
        created then.

        Args:
            provider: The provider's name.
            request: The HTTP request, for the cookies and the scheme.
            code: The authorization code.
            state: The state the sign-in was started with.
            error: The provider's error, when it did not sign the person in.

        Returns:
            The redirect.

        Raises:
            UnknownSignInProviderError: No provider of this name is configured (404).
        """
        binding = request.cookies.get(SIGN_IN_COOKIE)
        command = FinishExternalSignInCommand(
            provider=provider,
            binding=None if binding is None else SecretStr(binding),
            state=state,
            code=code,
            error=error,
        )
        try:
            result = await finish_external_sign_in(command, request.cookies.get(SESSION_COOKIE))
        except UnknownSignInProviderError:
            raise
        except DomainError as refusal:
            response = refused(refusal)
        else:
            response = _no_store(RedirectResponse(result.return_to, status_code=303))
            response.set_cookie(
                SESSION_COOKIE,
                result.session.token.get_secret_value(),
                max_age=result.session.max_age,
                secure=secure(request),
                **COOKIE_ATTRS,
            )
        response.delete_cookie(
            SIGN_IN_COOKIE,
            path=SIGN_IN_COOKIE_PATH,
            httponly=True,
            samesite="lax",
            secure=secure(request),
        )
        return response

    return router


def _no_store(response: RedirectResponse) -> RedirectResponse:
    """Keep a sign-in redirect out of caches and its URL out of the next page's ``Referer``.

    Args:
        response: The redirect.

    Returns:
        The same response.
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def build_grants_router(
    *,
    list_grants: ListLibraryGrants,
    grant_role: GrantLibraryRole,
    revoke_role: RevokeLibraryRole,
    list_access_log: ListLibraryAccessLog,
    transfer: TransferLibrary,
    caller: CurrentCaller,
    require_library: Callable[[str], Awaitable[None]],
) -> APIRouter:
    """Expose ``/libraries/{owner}/{repo}/grants``, ``.../transfer`` and ``.../access-log``.

    Who holds which role, handing the library over, and who changed its access and when.

    Every route needs the ``admin`` role on the library (an instance operator holds it on all of
    them). Giving or taking the ``admin`` role, and handing the library over, needs the
    ``creator`` role. A session or an API token may call them: a token acts as its account.

    Args:
        list_grants: The driving port that lists the grants.
        grant_role: The driving port that gives a role.
        revoke_role: The driving port that takes a role away.
        list_access_log: The driving port that reads the library's access log.
        transfer: The driving port that hands a library over to a new creator.
        caller: The dependency that names the calling account.
        require_library: Verifies live catalog presence and credential read access.

    Returns:
        The router.
    """
    router = APIRouter(tags=["identity"], dependencies=[Depends(caller)])
    account = Annotated[AccountSummary, Depends(caller)]

    @router.get("/libraries/{owner}/{repo}/grants", name="list_library_grants")
    async def get_grants(
        owner: str, repo: str, who: account, query: Annotated[GrantListQuery, Query()]
    ) -> LibraryGrantList:
        """List who holds a role on the library: users first, then groups. Library admins only.

        A page at a time; filter with `q`, `kind` and `role`, order with `sort`; `total` counts
        every match.

        Args:
            owner: The library's owner segment.
            repo: The library's repository segment.
            who: The caller.
            query: The filters, the sort, the page size and the cursor of the previous page.

        Returns:
            The page of grants, its next cursor and the total.
        """
        await require_library(f"/{owner}/{repo}")
        return await list_grants(
            ListLibraryGrantsQuery(
                caller_id=who.id,
                library=f"/{owner}/{repo}",
                **query.model_dump(exclude_unset=True),
            )
        )

    @router.put("/libraries/{owner}/{repo}/grants", name="grant_library_role")
    async def put_grant(
        owner: str, repo: str, request: LibraryGrantRequest, who: account
    ) -> LibraryGrants:
        """Give a user or a group a role on the library, replacing the role they had.

        Needs the `admin` role on the library, and `creator` to give or change `admin`. A
        group is named as stored (with the provider's prefix). The creator's role is never
        changed here.

        Args:
            owner: The library's owner segment.
            repo: The library's repository segment.
            request: Whom to give a role, and which.
            who: The caller.

        Returns:
            The library's grants now.
        """
        await require_library(f"/{owner}/{repo}")
        return await grant_role(
            GrantLibraryRoleCommand(
                caller_id=who.id, library=f"/{owner}/{repo}", **request.model_dump()
            )
        )

    @router.delete(
        "/libraries/{owner}/{repo}/grants/{kind}/{subject:path}", name="revoke_library_role"
    )
    async def delete_grant(
        owner: str, repo: str, kind: Literal["user", "group"], subject: str, who: account
    ) -> LibraryGrants:
        """Take a role away from a user or a group. Needs `admin`, and `creator` for an admin's.

        Args:
            owner: The library's owner segment.
            repo: The library's repository segment.
            kind: `user` or `group`.
            subject: The username or the group's name.
            who: The caller.

        Returns:
            The library's grants now.
        """
        await require_library(f"/{owner}/{repo}")
        return await revoke_role(
            RevokeLibraryRoleCommand(
                caller_id=who.id, library=f"/{owner}/{repo}", kind=kind, subject=subject
            )
        )

    @router.post("/libraries/{owner}/{repo}/transfer", name="transfer_library")
    async def post_transfer(
        owner: str, repo: str, request: LibraryTransferRequest, who: account
    ) -> LibraryGrants:
        """Hand the library over to another user: they become its creator.

        Only the library's `creator` (or an operator) may. The creator before stays an `admin`
        of the library. A user who is already the creator is a 422 `invalid_grant`.

        Args:
            owner: The library's owner segment.
            repo: The library's repository segment.
            request: The new creator.
            who: The caller.

        Returns:
            The library's grants now.
        """
        await require_library(f"/{owner}/{repo}")
        return await transfer(
            TransferLibraryCommand(
                caller_id=who.id, library=f"/{owner}/{repo}", **request.model_dump()
            )
        )

    @router.get("/libraries/{owner}/{repo}/access-log", name="list_library_access_log")
    async def get_access_log(
        owner: str, repo: str, who: account, query: Annotated[LibraryAccessLogQuery, Query()]
    ) -> AccessLogPage:
        """List who changed the library's access, how and when, newest first. Library admins only.

        Its creation, grants (a new role, or another one), revocations and ownership transfers,
        each with who made it and when. Operators see every event under the library's ID;
        anyone else only those since it was last removed. Filter with `change`; `total` counts
        every match.

        Args:
            owner: The library's owner segment.
            repo: The library's repository segment.
            who: The caller.
            query: The filter, the page size and the cursor of the previous page.

        Returns:
            The page of events, its next cursor and the total.
        """
        await require_library(f"/{owner}/{repo}")
        return await list_access_log(
            ListLibraryAccessLogQuery(
                caller_id=who.id,
                library=f"/{owner}/{repo}",
                **query.model_dump(exclude_unset=True),
            )
        )

    return router
