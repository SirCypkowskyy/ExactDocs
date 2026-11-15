"""Wiring of the identity domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self

from exactdocs.identity.models import SignInPolicy
from exactdocs.identity.ports.driven import (
    AccountRepository,
    ExternalIdentityRepository,
    FailedSignInLog,
    PasswordHasher,
    SecretBox,
    SessionRepository,
    SignInAttemptRepository,
    SignInProvider,
    TokenRepository,
)
from exactdocs.identity.ports.driving import (
    Authenticate,
    CreateFirstAdmin,
    CreateToken,
    CreateUser,
    FinishExternalSignIn,
    GetSessionState,
    GetSetupState,
    IdentifyCaller,
    IdentifyExternalToken,
    IdentifyToken,
    ListTokens,
    ListUsers,
    LoginForToken,
    ResetPassword,
    RevalidateExternalAccounts,
    RevokeToken,
    SetUserDisabled,
    SignIn,
    SignOut,
    StartExternalSignIn,
)
from exactdocs.identity.use_cases import (
    AuthenticateUseCase,
    CreateFirstAdminUseCase,
    CreateTokenUseCase,
    CreateUserUseCase,
    FinishExternalSignInUseCase,
    GetSessionStateUseCase,
    GetSetupStateUseCase,
    IdentifyCallerUseCase,
    IdentifyExternalTokenUseCase,
    IdentifyTokenUseCase,
    ListTokensUseCase,
    ListUsersUseCase,
    LoginForTokenUseCase,
    ResetPasswordUseCase,
    RevalidateExternalAccountsUseCase,
    RevokeTokenUseCase,
    SetUserDisabledUseCase,
    SignInUseCase,
    SignOutUseCase,
    StartExternalSignInUseCase,
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
    list_users: ListUsers
    """List every local account (operators only)."""
    create_user: CreateUser
    """Create a further local account (operators only; there is no self-signup)."""
    set_user_disabled: SetUserDisabled
    """Disable or enable an account (operators only)."""
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
    identify_external_token: IdentifyExternalToken
    """Resolve an ID token of a sign-in provider (MCP's OAuth) to who it acts as."""
    start_external_sign_in: StartExternalSignIn
    """Start a sign-in through a configured identity provider."""
    finish_external_sign_in: FinishExternalSignIn
    """Finish an external sign-in (the provider's callback) and start a session."""
    revalidate_external_accounts: RevalidateExternalAccounts
    """Check again the memberships of the external identities that are due."""

    @classmethod
    def build(
        cls,
        *,
        repository: AccountRepository,
        sessions: SessionRepository,
        tokens: TokenRepository,
        hasher: PasswordHasher,
        failures: FailedSignInLog,
        externals: ExternalIdentityRepository,
        attempts: SignInAttemptRepository,
        box: SecretBox,
        clock: Clock,
        providers: Mapping[str, SignInProvider] = MappingProxyType({}),
        policies: Mapping[str, SignInPolicy] = MappingProxyType({}),
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        Args:
            repository: Where accounts are stored.
            sessions: Where browser sessions are stored.
            tokens: Where API tokens are stored.
            hasher: The password hasher.
            failures: The log of failed sign-ins, for the throttle.
            externals: The links of external identities to accounts (kept even when no
                provider is configured: their accounts must still lose access).
            attempts: Where started external sign-ins wait for their callback.
            box: Seals the refresh tokens of external identities.
            clock: The current time.
            providers: The configured identity providers, by name.
            policies: Their policies, by the same names.

        Returns:
            The module, its driving ports wired.

        Raises:
            ValueError: ``providers`` and ``policies`` do not name the same providers.
        """
        if providers.keys() != policies.keys() or any(n != p.name for n, p in policies.items()):
            message = "every sign-in provider needs its policy, under the same name"
            raise ValueError(message)
        authenticate = AuthenticateUseCase(
            repository=repository, hasher=hasher, failures=failures, clock=clock
        )
        identify_caller = IdentifyCallerUseCase(
            sessions=sessions, accounts=repository, externals=externals, clock=clock
        )
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
                accounts=repository, identify_caller=identify_caller, policies=policies
            ),
            reset_password=ResetPasswordUseCase(
                accounts=repository,
                sessions=sessions,
                tokens=tokens,
                hasher=hasher,
                failures=failures,
            ),
            list_users=ListUsersUseCase(accounts=repository, externals=externals),
            create_user=CreateUserUseCase(
                accounts=repository, hasher=hasher, failures=failures, clock=clock
            ),
            set_user_disabled=SetUserDisabledUseCase(
                accounts=repository,
                sessions=sessions,
                tokens=tokens,
                externals=externals,
                clock=clock,
            ),
            create_token=create_token,
            login_for_token=LoginForTokenUseCase(
                authenticate=authenticate, create_token=create_token
            ),
            list_tokens=ListTokensUseCase(tokens=tokens),
            revoke_token=RevokeTokenUseCase(tokens=tokens),
            identify_token=IdentifyTokenUseCase(
                tokens=tokens, accounts=repository, externals=externals, clock=clock
            ),
            identify_external_token=IdentifyExternalTokenUseCase(
                providers=providers, policies=policies, accounts=repository, externals=externals
            ),
            start_external_sign_in=StartExternalSignInUseCase(
                providers=providers, policies=policies, attempts=attempts, clock=clock
            ),
            finish_external_sign_in=FinishExternalSignInUseCase(
                providers=providers,
                policies=policies,
                attempts=attempts,
                accounts=repository,
                externals=externals,
                sessions=sessions,
                box=box,
                clock=clock,
            ),
            revalidate_external_accounts=RevalidateExternalAccountsUseCase(
                providers=providers,
                policies=policies,
                accounts=repository,
                externals=externals,
                sessions=sessions,
                box=box,
                clock=clock,
            ),
        )
