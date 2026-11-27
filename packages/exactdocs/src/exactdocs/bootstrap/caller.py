"""Who is making the current request, for library roles.

A driving adapter that has proven who calls binds the account here; the identity bridge of the
library roles reads it. Work no person started (the command line, a stdio MCP process, a
scheduled check, a job) binds nobody, which the bridge treats as the instance's own work.
"""

from contextvars import ContextVar, Token

from fastmcp.server.dependencies import get_access_token

from exactdocs.identity.dtos import ApiTokenIdentity, ExternalTokenIdentity
from exactdocs.ingestion.models import Person

_caller: ContextVar[str | None] = ContextVar("exactdocs_caller", default=None)
_api_caller: ContextVar[ApiTokenIdentity | None] = ContextVar("exactdocs_api_caller", default=None)
_caller_name: ContextVar[str | None] = ContextVar("exactdocs_caller_name", default=None)

type CallerBinding = tuple[Token[str | None], Token[ApiTokenIdentity | None], Token[str | None]]


def bind_caller(
    account_id: str,
    *,
    api_identity: ApiTokenIdentity | None = None,
    username: str | None = None,
) -> CallerBinding:
    """Name the account of the HTTP request being served (until its task ends).

    Args:
        account_id: The account the request's session or API token resolved to.
        api_identity: The verified API principal; ``None`` for a browser session.
        username: The account's user name, recorded as who queued a job; ``None``: unknown.

    Returns:
        Context bindings to restore once this request ends.
    """
    account_token = _caller.set(account_id)
    identity_token = _api_caller.set(
        api_identity if api_identity is not None and api_identity.id == account_id else None
    )
    name_token = _caller_name.set(username)
    return account_token, identity_token, name_token


def current_account_id() -> str | None:
    """Name the account of the current request, over REST or over MCP.

    Returns:
        The account ID; ``None`` when no person made the request (no token over stdio or in
        process, or work started by the instance itself).
    """
    bound = _caller.get()
    if bound is not None:
        return bound
    token = get_access_token()
    # MultiAuth qualifies client_id with its trust source; identity stores the original ID.
    return None if token is None else (token.original_client_id or token.client_id)


def current_account_name() -> str | None:
    """Name the user name of the current request's account, over REST or over MCP.

    Returns:
        The user name the request's session, API token or OAuth token carries; ``None`` when no
        person made the request, or the binding named none.
    """
    if _caller.get() is not None:
        return _caller_name.get()
    token = get_access_token()
    if token is None:
        return None
    name = token.claims.get("username")  # every MCP verifier puts the account's user name here
    return name if isinstance(name, str) else None


async def current_person() -> Person | None:
    """Name the person of the current request, as ingestion records who queued a job.

    Implements ``ingestion.ports.driven.Requester``. Only the account's ID and user name: never
    a token, its ID or any other credential.

    Returns:
        The account, named by its ID when the request carries no user name, ``via`` ``mcp`` over
        MCP (#613); ``None`` for the instance's own work (no account bound).
    """
    account = current_account_id()
    if account is None:
        return None
    # REST binds its caller; only an MCP request is known by its access token alone.
    via = "mcp" if _caller.get() is None else None
    return Person(id=account, username=current_account_name() or account, via=via)


def current_external_identity() -> ExternalTokenIdentity | None:
    """Read the verified OAuth principal of the same caller as the current request.

    Only the identity verifier inserts this frozen DTO object. JSON claims supplied by a host
    cannot create one, and a principal belonging to another bound caller is never reused.

    Returns:
        The request's trusted external identity, or ``None`` for other credentials.
    """
    if _caller.get() is not None:
        return None
    token = get_access_token()
    if token is None:
        return None
    account_id = token.original_client_id or token.client_id
    if account_id != current_account_id():
        return None
    identity = token.claims.get("external_identity")
    if not isinstance(identity, ExternalTokenIdentity) or identity.account.id != account_id:
        return None
    return identity


def current_api_identity() -> ApiTokenIdentity | None:
    """Read the trusted API principal of the current REST or MCP request.

    Returns:
        The typed principal of this credential, never a deserialized host claim.
    """
    if _caller.get() is not None:
        return _api_caller.get()
    token = get_access_token()
    if token is None:
        return None
    account_id = token.original_client_id or token.client_id
    identity = token.claims.get("api_identity")
    if not isinstance(identity, ApiTokenIdentity) or identity.id != account_id:
        return None
    return identity


def reset_caller(binding: CallerBinding) -> None:
    """Restore the parent context after a REST request.

    Args:
        binding: The context tokens returned by bind_caller.
    """
    account_token, identity_token, name_token = binding
    _caller_name.reset(name_token)
    _api_caller.reset(identity_token)
    _caller.reset(account_token)
