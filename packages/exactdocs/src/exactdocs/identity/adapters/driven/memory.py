from dataclasses import dataclass, field

from exactdocs.identity.models import Account, Username


@dataclass(slots=True)
class InMemoryAccountRepository:
    """Implements ``ports.driven.AccountRepository``. For tests."""

    accounts: dict[Username, Account] = field(default_factory=dict)

    async def add_first(self, account: Account) -> bool:
        """Store the account only if no account exists yet."""
        if self.accounts:
            return False
        self.accounts[account.username] = account
        return True

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``."""
        return self.accounts.get(username)

    async def any_exists(self) -> bool:
        """Return whether at least one account exists."""
        return bool(self.accounts)
