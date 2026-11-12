"""Wiring of the identity domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from dataclasses import dataclass
from typing import Self

from exactdocs.identity.ports.driven import (
    AccountRepository,
    FailedSignInLog,
    PasswordHasher,
    SessionRepository,
    TokenRepository,
)
from exactdocs.identity.ports.driving import (
    Authenticate,
    CreateFirstAdmin,
    CreateToken,
    GetSessionState,
    GetSetupState,
    IdentifyCaller,
    IdentifyToken,
    ListTokens,
    LoginForToken,
    ResetPassword,
    RevokeToken,
    SignIn,
    SignOut,
)
from exactdocs.identity.use_cases import (
    AuthenticateUseCase,
    CreateFirstAdminUseCase,
    CreateTokenUseCase,
    GetSessionStateUseCase,
    GetSetupStateUseCase,
    IdentifyCallerUseCase,
    IdentifyTokenUseCase,
    ListTokensUseCase,
    LoginForTokenUseCase,
    ResetPasswordUseCase,
    RevokeTokenUseCase,
    SignInUseCase,
    SignOutUseCase,
)
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentityModule:
    """The identity driving ports, ready to be exposed by driving adapters."""

    get_setup_state: GetSetupState
    """Tell whether the first admin is still to be created."""
    create_first_admin: CreateFirstAdmin
    """Create the first admin account (once)."""
    authenticate: Authenticate
    """Check a username and password, under the sign-in throttle."""
    sign_in: SignIn
    """Exchange credentials for a browser session."""
    sign_out: SignOut
    """End a browser session."""
    identify_caller: IdentifyCaller
    """Resolve a session token to its account."""
    get_session_state: GetSessionState
    """Tell the UI whether setup is due and who is signed in."""
    reset_password: ResetPassword
    """Set a new password for an account (operators only)."""
    create_token: CreateToken
    """Create an API token for the caller."""
    login_for_token: LoginForToken
    """Exchange credentials for an API token (the CLI's login)."""
    list_tokens: ListTokens
    """List the caller's API tokens."""
    revoke_token: RevokeToken
    """Revoke one of the caller's API tokens."""
    identify_token: IdentifyToken
    """Resolve an API token to its account."""

    @classmethod
    def build(
        cls,
        *,
        repository: AccountRepository,
        sessions: SessionRepository,
        tokens: TokenRepository,
        hasher: PasswordHasher,
        failures: FailedSignInLog,
        clock: Clock,
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        Args:
            repository: Where accounts are stored.
            sessions: Where browser sessions are stored.
            tokens: Where API tokens are stored.
            hasher: The password hasher.
            failures: The log of failed sign-ins, for the throttle.
            clock: The current time.

        Returns:
            The module, its driving ports wired.
        """
        authenticate = AuthenticateUseCase(
            repository=repository, hasher=hasher, failures=failures, clock=clock
        )
        identify_caller = IdentifyCallerUseCase(sessions=sessions, accounts=repository, clock=clock)
        create_token = CreateTokenUseCase(tokens=tokens, clock=clock)
        return cls(
            get_setup_state=GetSetupStateUseCase(repository=repository),
            create_first_admin=CreateFirstAdminUseCase(
                repository=repository, hasher=hasher, clock=clock
            ),
            authenticate=authenticate,
            sign_in=SignInUseCase(authenticate=authenticate, sessions=sessions, clock=clock),
            sign_out=SignOutUseCase(sessions=sessions),
            identify_caller=identify_caller,
            get_session_state=GetSessionStateUseCase(
                accounts=repository, identify_caller=identify_caller
            ),
            reset_password=ResetPasswordUseCase(
                accounts=repository,
                sessions=sessions,
                tokens=tokens,
                hasher=hasher,
                failures=failures,
            ),
            create_token=create_token,
            login_for_token=LoginForTokenUseCase(
                authenticate=authenticate, create_token=create_token
            ),
            list_tokens=ListTokensUseCase(tokens=tokens),
            revoke_token=RevokeTokenUseCase(tokens=tokens),
            identify_token=IdentifyTokenUseCase(tokens=tokens, accounts=repository, clock=clock),
        )
