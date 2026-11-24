"""Wiring of the identity domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self

from exactdocs.identity.models import AccessPolicy, LibraryCreationPolicy, SignInPolicy
from exactdocs.identity.ports.driven import (
    AccessAssertionVerifier,
    AccessLog,
    AccountRepository,
    ExternalIdentityRepository,
    FailedSignInLog,
    LibraryGrantRepository,
    PasswordHasher,
    SecretBox,
    SessionRepository,
    SignInAttemptRepository,
    SignInProvider,
    TokenRepository,
)
from exactdocs.identity.ports.driving import (
    Authenticate,
    CanCreateLibrary,
    ClaimLibrary,
    CreateFirstAdmin,
    CreateToken,
    CreateUser,
    DropLibraryGrants,
    FinishExternalSignIn,
    GetSessionState,
    GetSetupState,
    GrantLibraryRole,
    IdentifyAccessCaller,
    IdentifyCaller,
    IdentifyExternalToken,
    IdentifyToken,
    ListAccessLog,
    ListAllTokens,
    ListLibraryAccessLog,
    ListLibraryGrants,
    ListTokens,
    ListUsers,
    LoginForToken,
    ResetPassword,
    ResolveLibraryRoles,
    RevalidateExternalAccounts,
    RevokeLibraryRole,
    RevokeToken,
    SetUserDisabled,
    SignIn,
    SignOut,
    StartExternalSignIn,
    TransferLibrary,
)
from exactdocs.identity.use_cases import (
    AuthenticateUseCase,
    CanCreateLibraryUseCase,
    ClaimLibraryUseCase,
    CreateFirstAdminUseCase,
    CreateTokenUseCase,
    CreateUserUseCase,
    DropLibraryGrantsUseCase,
    FinishExternalSignInUseCase,
    GetSessionStateUseCase,
    GetSetupStateUseCase,
    GrantLibraryRoleUseCase,
    IdentifyAccessCallerUseCase,
    IdentifyCallerUseCase,
    IdentifyExternalTokenUseCase,
    IdentifyTokenUseCase,
    ListAccessLogUseCase,
    ListAllTokensUseCase,
    ListLibraryAccessLogUseCase,
    ListLibraryGrantsUseCase,
    ListTokensUseCase,
    ListUsersUseCase,
    LoginForTokenUseCase,
    ResetPasswordUseCase,
    ResolveLibraryRolesUseCase,
    RevalidateExternalAccountsUseCase,
    RevokeLibraryRoleUseCase,
    RevokeTokenUseCase,
    SetUserDisabledUseCase,
    Sharing,
    SignInUseCase,
    SignOutUseCase,
    StartExternalSignInUseCase,
    TransferLibraryUseCase,
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
    identify_access_caller: IdentifyAccessCaller
    """Resolve a Cloudflare Access token to its account (refuses every token when not set up)."""
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
    list_all_tokens: ListAllTokens
    """List every account's API tokens with their owners (operators)."""
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
    can_create_library: CanCreateLibrary
    """Resolve the instance-wide creation permission."""
    resolve_library_roles: ResolveLibraryRoles
    """Tell what an account may do with libraries (the highest role it or its groups hold)."""
    claim_library: ClaimLibrary
    """Make an account the creator of a new library."""
    drop_library_grants: DropLibraryGrants
    """Drop every grant on a removed library."""
    grant_library_role: GrantLibraryRole
    """Give a user or a group a role on a library (library admins; creators for admins)."""
    revoke_library_role: RevokeLibraryRole
    """Take a role away from a user or a group."""
    list_library_grants: ListLibraryGrants
    """List who holds a role on a library (library admins)."""
    list_library_access_log: ListLibraryAccessLog
    """Read a library's access log (library admins)."""
    list_access_log: ListAccessLog
    """Read the access log of every library, removed ones included (operators)."""
    transfer_library: TransferLibrary
    """Hand a library over to another user (its creator only)."""

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
        library_grants: LibraryGrantRepository,
        access_log: AccessLog,
        attempts: SignInAttemptRepository,
        box: SecretBox,
        clock: Clock,
        providers: Mapping[str, SignInProvider] = MappingProxyType({}),
        policies: Mapping[str, SignInPolicy] = MappingProxyType({}),
        library_creation: LibraryCreationPolicy | None = None,
        access_verifier: AccessAssertionVerifier | None = None,
        access_policy: AccessPolicy | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        Args:
            library_creation: Optional instance-wide creation allowlist.
            repository: Where accounts are stored.
            sessions: Where browser sessions are stored.
            tokens: Where API tokens are stored.
            hasher: The password hasher.
            failures: The log of failed sign-ins, for the throttle.
            externals: The links of external identities to accounts (kept even when no
                provider is configured: their accounts must still lose access).
            library_grants: Who holds which role on which library.
            access_log: The log of grants, revocations, ownership transfers and deletions.
            attempts: Where started external sign-ins wait for their callback.
            box: Seals the refresh tokens of external identities.
            clock: The current time.
            providers: The configured identity providers, by name.
            policies: Their policies, by the same names.
            access_verifier: Checks Cloudflare Access tokens; ``None`` when Access is off.
            access_policy: Who Cloudflare Access signs in; given with ``access_verifier``.

        Returns:
            The module, its driving ports wired.

        Raises:
            ValueError: ``providers`` and ``policies`` do not name the same providers, or only
                one of ``access_verifier`` and ``access_policy`` is given.
        """
        if providers.keys() != policies.keys() or any(n != p.name for n, p in policies.items()):
            message = "every sign-in provider needs its policy, under the same name"
            raise ValueError(message)
        if (access_verifier is None) != (access_policy is None):
            message = "Cloudflare Access needs both its verifier and its policy"
            raise ValueError(message)
        authenticate = AuthenticateUseCase(
            repository=repository, hasher=hasher, failures=failures, clock=clock
        )
        identify_caller = IdentifyCallerUseCase(
            sessions=sessions, accounts=repository, externals=externals, clock=clock
        )
        identify_access_caller = IdentifyAccessCallerUseCase(
            verifier=access_verifier,
            policy=access_policy,
            accounts=repository,
            externals=externals,
            clock=clock,
        )
        create_token = CreateTokenUseCase(tokens=tokens, clock=clock)
        sharing = Sharing(
            accounts=repository,
            externals=externals,
            grants=library_grants,
            log=access_log,
            clock=clock,
        )
        return cls(
            get_setup_state=GetSetupStateUseCase(repository=repository),
            create_first_admin=CreateFirstAdminUseCase(
                repository=repository, hasher=hasher, clock=clock
            ),
            authenticate=authenticate,
            sign_in=SignInUseCase(authenticate=authenticate, sessions=sessions, clock=clock),
            sign_out=SignOutUseCase(sessions=sessions),
            identify_caller=identify_caller,
            identify_access_caller=identify_access_caller,
            get_session_state=GetSessionStateUseCase(
                accounts=repository,
                identify_caller=identify_caller,
                policies=policies,
                identify_access=None if access_policy is None else identify_access_caller,
                access_sign_out_url=None if access_policy is None else access_policy.sign_out_url,
            ),
            reset_password=ResetPasswordUseCase(
                accounts=repository,
                sessions=sessions,
                tokens=tokens,
                hasher=hasher,
                failures=failures,
            ),
            list_users=ListUsersUseCase(
                accounts=repository, externals=externals, tokens=tokens, clock=clock
            ),
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
            list_all_tokens=ListAllTokensUseCase(tokens=tokens, accounts=repository, clock=clock),
            revoke_token=RevokeTokenUseCase(tokens=tokens),
            identify_token=IdentifyTokenUseCase(
                tokens=tokens, accounts=repository, externals=externals, clock=clock
            ),
            identify_external_token=IdentifyExternalTokenUseCase(
                providers=providers,
                policies=policies,
                accounts=repository,
                externals=externals,
                clock=clock,
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
            can_create_library=CanCreateLibraryUseCase(
                accounts=repository, externals=externals, policy=library_creation
            ),
            resolve_library_roles=ResolveLibraryRolesUseCase(
                accounts=repository, externals=externals, grants=library_grants
            ),
            claim_library=ClaimLibraryUseCase(grants=library_grants, log=access_log, clock=clock),
            drop_library_grants=DropLibraryGrantsUseCase(
                grants=library_grants, log=access_log, clock=clock
            ),
            grant_library_role=GrantLibraryRoleUseCase(sharing=sharing),
            revoke_library_role=RevokeLibraryRoleUseCase(sharing=sharing),
            list_library_grants=ListLibraryGrantsUseCase(sharing=sharing),
            list_library_access_log=ListLibraryAccessLogUseCase(sharing=sharing),
            list_access_log=ListAccessLogUseCase(sharing=sharing),
            transfer_library=TransferLibraryUseCase(sharing=sharing),
        )
