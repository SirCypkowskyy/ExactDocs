"""Wiring of the identity domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from dataclasses import dataclass
from typing import Self

from exactdocs.identity.ports.driven import AccountRepository, PasswordHasher
from exactdocs.identity.ports.driving import Authenticate, CreateFirstAdmin, GetSetupState
from exactdocs.identity.use_cases import (
    AuthenticateUseCase,
    CreateFirstAdminUseCase,
    GetSetupStateUseCase,
)
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentityModule:
    """The identity driving ports, ready to be exposed by driving adapters."""

    get_setup_state: GetSetupState
    create_first_admin: CreateFirstAdmin
    authenticate: Authenticate

    @classmethod
    def build(cls, *, repository: AccountRepository, hasher: PasswordHasher, clock: Clock) -> Self:
        """Assemble the use cases around the given driven adapters."""
        return cls(
            get_setup_state=GetSetupStateUseCase(repository),
            create_first_admin=CreateFirstAdminUseCase(repository, hasher, clock),
            authenticate=AuthenticateUseCase(repository, hasher),
        )
