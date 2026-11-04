"""Wiring of the identity domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from dataclasses import dataclass
from typing import Self

from exactdocs.identity.ports.driven import (
    AccountRepository,
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
    create_first_admin: CreateFirstAdmin
    authenticate: Authenticate
    sign_in: SignIn
    sign_out: SignOut
    identify_caller: IdentifyCaller
    get_session_state: GetSessionState
    reset_password: ResetPassword
    create_token: CreateToken
    list_tokens: ListTokens
    revoke_token: RevokeToken
    identify_token: IdentifyToken

    @classmethod
    def build(
        cls,
        *,
        repository: AccountRepository,
        sessions: SessionRepository,
        tokens: TokenRepository,
        hasher: PasswordHasher,
        clock: Clock,
    ) -> Self:
        """Assemble the use cases around the given driven adapters."""
        authenticate = AuthenticateUseCase(repository, hasher)
        identify_caller = IdentifyCallerUseCase(sessions, repository, clock)
        return cls(
            get_setup_state=GetSetupStateUseCase(repository),
            create_first_admin=CreateFirstAdminUseCase(repository, hasher, clock),
            authenticate=authenticate,
            sign_in=SignInUseCase(authenticate, sessions, clock),
            sign_out=SignOutUseCase(sessions),
            identify_caller=identify_caller,
            get_session_state=GetSessionStateUseCase(repository, identify_caller),
            reset_password=ResetPasswordUseCase(repository, sessions, tokens, hasher),
            create_token=CreateTokenUseCase(tokens, clock),
            list_tokens=ListTokensUseCase(tokens),
            revoke_token=RevokeTokenUseCase(tokens),
            identify_token=IdentifyTokenUseCase(tokens, repository, clock),
        )
