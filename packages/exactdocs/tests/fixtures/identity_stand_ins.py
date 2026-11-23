"""Stand-ins for the identity module's external sign-in parts, for tests about something else."""

from typing import Any

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccessLog,
    InMemoryAccountRepository,
    InMemoryExternalIdentityRepository,
    InMemoryLibraryGrantRepository,
    InMemorySignInAttemptRepository,
)


class _NoBox:
    """A secret box no test about local accounts should ever reach."""

    def seal(self, plaintext: str) -> str:
        raise AssertionError(plaintext[:0] + "nothing is sealed without external sign-in")

    def open(self, sealed: str) -> str:
        raise AssertionError(sealed[:0] + "nothing is opened without external sign-in")


def no_external_sign_in() -> dict[str, Any]:
    """The ``IdentityModule.build`` arguments of an instance with no identity provider."""
    return {
        "externals": InMemoryExternalIdentityRepository(accounts=InMemoryAccountRepository()),
        "library_grants": InMemoryLibraryGrantRepository(),
        "access_log": InMemoryAccessLog(),
        "attempts": InMemorySignInAttemptRepository(),
        "box": _NoBox(),
    }
