"""Who is making the current request, for library roles.

A driving adapter that has proven who calls binds the account here; the identity bridge of the
library roles reads it. Work no person started (the command line, a stdio MCP process, a
scheduled check, a job) binds nobody, which the bridge treats as the instance's own work.
"""

from contextvars import ContextVar

from fastmcp.server.dependencies import get_access_token

from exactdocs.identity.dtos import ExternalTokenIdentity

_caller: ContextVar[str | None] = ContextVar("exactdocs_caller", default=None)


def bind_caller(account_id: str) -> None:
    """Name the account of the HTTP request being served (until its task ends).

    Args:
        account_id: The account the request's session or API token resolved to.
    """
    _caller.set(account_id)


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


def current_external_identity() -> ExternalTokenIdentity | None:
    """Read the verified OAuth principal of the same caller as the current request.

    Only the identity verifier inserts this frozen DTO object. JSON claims supplied by a host
    cannot create one, and a principal belonging to another bound caller is never reused.

    Returns:
        The request's trusted external identity, or ``None`` for other credentials.
    """
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
