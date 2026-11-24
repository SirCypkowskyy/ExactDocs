"""Driven (secondary) ports: what identity needs from infrastructure."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal, Protocol

from exactdocs.identity.models import (
    AccessClaims,
    AccessEvent,
    AccessLogFilter,
    Account,
    AccountId,
    ApiToken,
    ExternalClaims,
    ExternalGrant,
    ExternalIdentity,
    FailedSignIns,
    LibraryGrant,
    Role,
    Session,
    SignInAttempt,
    SubjectKind,
    Username,
)


class AccountRepository(Protocol):
    """Persistence for accounts."""

    async def add_first(self, account: Account) -> bool:
        """Store the account only if no account exists yet; ``False`` when one already does.

        Must be atomic: two concurrent calls store at most one account.

        Args:
            account: The first account.

        Returns:
            ``True`` when it was stored, ``False`` when an account already exists.
        """
        ...

    async def add(self, account: Account) -> bool:
        """Store a further account; ``False`` when its username is taken.

        Must be atomic: of two concurrent calls with the same username, at most one stores it.

        Args:
            account: The new account.

        Returns:
            ``True`` when it was stored, ``False`` when another account has the username.
        """
        ...

    async def list_all(self) -> Sequence[Account]:
        """Return every account, oldest first (then by username).

        Returns:
            The accounts.
        """
        ...

    async def set_disabled_at(self, account_id: AccountId, disabled_at: datetime | None) -> bool:
        """Disable the account from ``disabled_at`` on, or enable it again with ``None``.

        Disabling never leaves the instance without an enabled admin: it is refused (``False``)
        when the account is the last one. The check and the change are one atomic step, so two
        admins disabled at the same time cannot both go.

        Args:
            account_id: The account's id.
            disabled_at: When it was disabled, or ``None`` to enable it.

        Returns:
            ``False`` when disabling was refused to keep an enabled admin, else ``True``.
        """
        ...

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``.

        Args:
            username: The normalized username.

        Returns:
            The account, or ``None``.
        """
        ...

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        """Return the account with this id, or ``None``.

        Args:
            account_id: The account's id.

        Returns:
            The account, or ``None``.
        """
        ...

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        """Replace the account's password hash.

        Args:
            account_id: The account's id.
            password_hash: The new encoded hash.
        """
        ...

    async def any_exists(self) -> bool:
        """Return whether at least one account exists.

        Returns:
            ``True`` once an account exists.
        """
        ...

    async def record_activity(self, account_id: AccountId, hour: datetime) -> None:
        """Move the account's ``last_active_at`` forward to ``hour``, never back.

        One conditional write: a later hour recorded meanwhile (another process) stays.

        Args:
            account_id: The account's id.
            hour: The hour it was active (``activity_hour``).
        """
        ...


class SessionRepository(Protocol):
    """Persistence for sessions, keyed by token hash."""

    async def add(self, session: Session) -> None:
        """Store a new session.

        Args:
            session: The session.
        """
        ...

    async def get(self, token_hash: str) -> Session | None:
        """Return the session with this token hash, or ``None``.

        Args:
            token_hash: The hash of the session token.

        Returns:
            The session, or ``None``.
        """
        ...

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the session was used at ``at``.

        Args:
            token_hash: The hash of the session token.
            at: When it was used.
        """
        ...

    async def delete(self, token_hash: str) -> None:
        """Remove the session (nothing happens when it does not exist).

        Args:
            token_hash: The hash of the session token.
        """
        ...

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every session of the account.

        Args:
            account_id: The account's id.
        """
        ...

    async def delete_others(self, account_id: AccountId, *, keep: str | None) -> None:
        """Remove every session of the account but the one with the token hash ``keep``.

        Args:
            account_id: The account's id.
            keep: The hash of the session token that stays; ``None`` removes them all.
        """
        ...

    async def delete_expired(self, *, idle_before: datetime, created_before: datetime) -> None:
        """Remove sessions last used before ``idle_before`` or created before ``created_before``.

        Args:
            idle_before: Idle deadline: sessions last used before it go.
            created_before: Absolute deadline: sessions created before it go.
        """
        ...


class TokenRepository(Protocol):
    """Persistence for API tokens, keyed by token hash."""

    async def add(self, token: ApiToken) -> None:
        """Store a new token.

        Args:
            token: The token.
        """
        ...

    async def get(self, token_hash: str) -> ApiToken | None:
        """Return the token with this hash, or ``None``.

        Args:
            token_hash: The hash of the token's secret.

        Returns:
            The token, or ``None``.
        """
        ...

    async def list_for_account(self, account_id: AccountId) -> list[ApiToken]:
        """Return the account's tokens, newest first.

        Args:
            account_id: The account's id.

        Returns:
            The tokens, newest first.
        """
        ...

    async def list_all(self) -> list[ApiToken]:
        """Return every account's tokens, expired ones not yet removed included, newest first.

        Returns:
            The tokens, newest first.
        """
        ...

    async def count_by_account(self, now: datetime) -> Mapping[AccountId, int]:
        """Count each account's tokens that have not expired at ``now``, in one query.

        Args:
            now: The current time.

        Returns:
            The count per account; an account without a live token is absent.
        """
        ...

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the token was used at ``at``.

        Args:
            token_hash: The hash of the token's secret.
            at: When it was used.
        """
        ...

    async def delete(self, account_id: AccountId, token_id: str) -> bool:
        """Remove the account's token with this id; ``False`` when there is none.

        Args:
            account_id: The owner's id.
            token_id: The token's id.

        Returns:
            ``True`` when a token was removed, ``False`` when the account has none by this id.
        """
        ...

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every token of the account.

        Args:
            account_id: The account's id.
        """
        ...

    async def delete_expired(self, now: datetime) -> None:
        """Remove the tokens whose expiry is at or before ``now``.

        Args:
            now: The current time.
        """
        ...


class FailedSignInLog(Protocol):
    """The sign-in throttle's state: attempt counts, and which address signed into which username.

    Counts are keyed by client address (``address:...``) or ``username:...``. The log may forget
    a record at any time (e.g. to stay within a memory bound): that only makes the throttle more
    lenient, never refuses anyone.
    """

    async def charge(self, keys: Sequence[str], now: datetime) -> timedelta:
        """Count one attempt against every key, unless one of them must still wait.

        The check and the count are one atomic step, so attempts made at the same time cannot
        all pass the check before any is counted. Returns the longest wait; when it is above zero
        nothing was counted.

        Args:
            keys: The throttle keys of the attempt (its address and its username).
            now: When the attempt is made.

        Returns:
            The longest wait among the keys; zero when the attempt was counted and may go ahead.
        """
        ...

    async def refund(self, key: str, charged_at: datetime) -> None:
        """Take back the attempt charged under ``key`` at ``charged_at`` (a right password).

        If no later attempt was charged since, the record goes back to how it was before that
        attempt, so the wait is not restarted; otherwise only the count goes down.

        Args:
            key: The throttle key.
            charged_at: The ``now`` the attempt was charged with.
        """
        ...

    async def get(self, key: str) -> FailedSignIns | None:
        """Return the record under ``key``, or ``None``.

        Args:
            key: The throttle key.

        Returns:
            The record, or ``None``.
        """
        ...

    async def forget(self, key: str) -> bool:
        """Drop the record under ``key`` (nothing happens when there is none).

        Args:
            key: The throttle key.

        Returns:
            ``True`` once no record is left under ``key`` (dropped, or there was none);
            ``False`` when the log was too busy to take the key's turn and skipped it.
        """
        ...

    async def forget_remembered(self, username: str) -> bool:
        """Forget every address remembered for ``username`` (``models.known_sign_ins_prefix``).

        Other usernames' remembered sign-ins and every count stay as they are.

        Args:
            username: The (normalised) username.

        Returns:
            ``True`` once none is left (dropped, or there was none); ``False`` when the log was
            too busy to take their turn and kept some of them (possibly all). Running it again
            is safe and forgets the rest.
        """
        ...

    async def remember_sign_in(self, key: str, now: datetime) -> None:
        """Note that the sign-in ``key`` (a username at an address) just succeeded.

        Args:
            key: The sign-in key.
            now: When the sign-in succeeded.
        """
        ...

    async def signed_in_before(self, key: str, now: datetime) -> bool:
        """Whether ``key`` succeeded within ``REMEMBER_SIGN_INS_FOR`` of ``now``.

        Args:
            key: The sign-in key.
            now: The current time.

        Returns:
            ``True`` when it did.
        """
        ...


class PasswordHasher(Protocol):
    """A memory-hard, salted password KDF. Hashes are self-describing strings."""

    async def hash(self, password: str) -> str:
        """Return the encoded hash of ``password`` (a fresh salt every call).

        Args:
            password: The password.

        Returns:
            The encoded hash, with its parameters and salt.
        """
        ...

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return whether ``password`` matches the hash, in constant time.

        Args:
            password_hash: An encoded hash made by ``hash``.
            password: The password to check.

        Returns:
            ``True`` when the password matches.
        """
        ...


class SignInProvider(Protocol):
    """One configured identity provider, spoken to in its own protocol (OIDC today).

    The adapter validates everything the provider sends (the ID token's signature, issuer,
    audience, times and nonce) before it returns claims. It raises ``ProviderUnavailableError``
    when the provider cannot be reached or answers unusably, ``ExternalSignInFailedError`` when
    what it sent does not check out, and ``ProviderAccessRevokedError`` when it refuses a
    refresh token. It never logs or raises with a token.
    """

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """Return where to send the browser to sign in (authorization code flow, PKCE S256).

        Only the S256 challenge of ``code_verifier`` leaves the server here.

        Args:
            state: Comes back unchanged with the code.
            nonce: Must come back in the ID token.
            code_verifier: The attempt's PKCE verifier.

        Returns:
            The provider's authorization URL with every parameter.
        """
        ...

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> ExternalGrant:
        """Trade the authorization code for tokens and return the validated claims.

        Args:
            code: The authorization code from the callback.
            code_verifier: The attempt's PKCE verifier.
            nonce: The attempt's nonce, which the ID token must hold.

        Returns:
            Who signed in, their groups and the refresh token (if any).
        """
        ...

    async def verify_id_token(self, id_token: str) -> ExternalClaims:
        """Validate an ID token this provider issued to ExactDocs and return its claims.

        The checks are those of ``exchange`` except the ``nonce`` (the token comes from the MCP
        OAuth proxy's own sign-in, long after the browser's attempt).

        Args:
            id_token: The ID token, as the provider issued it.

        Returns:
            Who the token is about, and their groups.
        """
        ...

    async def refresh(self, refresh_token: str, *, subject: str) -> ExternalGrant:
        """Use a refresh token to read the person's claims again.

        Args:
            refresh_token: The stored refresh token.
            subject: Whom the token belongs to: claims of anyone else are refused.

        Returns:
            The current claims and the refresh token to keep (a rotated one, or the same).
        """
        ...


class AccessAssertionVerifier(Protocol):
    """Checks the application token Cloudflare Access puts on each request it lets through.

    The adapter accepts a token only with a valid signature by a key of the team's certs, the
    configured issuer (the team domain) and one of the configured audiences, and valid times.
    It raises ``AccessAssertionRefusedError`` for a token that does not check out and
    ``ProviderUnavailableError`` when the team's certs cannot be fetched. It never logs or raises
    with a token.
    """

    async def verify(self, assertion: str) -> AccessClaims:
        """Validate an Access application token and return who it is about.

        Args:
            assertion: The compact JWT, from the ``Cf-Access-Jwt-Assertion`` header or the
                ``CF_Authorization`` cookie.

        Returns:
            The person or service token the token names.
        """
        ...


class SecretBox(Protocol):
    """Seals the refresh tokens of external identities (bootstrap's box, its own HKDF purpose).

    Nothing here logs or raises with a token or a sealed text; ``open`` raises
    ``exactdocs_kernel.SealedTextUnreadableError`` for a text it cannot open.
    """

    def seal(self, plaintext: str) -> str:
        """Encrypt and authenticate a token.

        Args:
            plaintext: The token.

        Returns:
            The sealed text, safe to store.
        """
        ...

    def open(self, sealed: str) -> str:
        """Decrypt a sealed token.

        Args:
            sealed: What ``seal`` returned.

        Returns:
            The token.
        """
        ...


class SignInAttemptRepository(Protocol):
    """External sign-ins started and not finished yet, keyed by the hash of the browser binding."""

    async def add(self, attempt: SignInAttempt, *, expired_before: datetime) -> None:
        """Store a new attempt, first removing the attempts started before ``expired_before``.

        Args:
            attempt: The attempt.
            expired_before: Attempts started before this are too old to finish.
        """
        ...

    async def take(self, binding_hash: str) -> SignInAttempt | None:
        """Remove and return the attempt of this browser binding, in one atomic step.

        Of two concurrent calls (a replayed callback, another process), at most one gets it.

        Args:
            binding_hash: The hash of the browser's binding value.

        Returns:
            The attempt, or ``None`` when there is none (never started, or already taken).
        """
        ...


LinkOutcome = Literal["created", "username_taken", "already_linked"]
"""What became of storing a new account with its link: stored, refused because the username is
taken, or refused because another sign-in linked the identity first."""


class ExternalIdentityRepository(Protocol):
    """Links between external identities and accounts, with each account's groups.

    Shares the accounts' storage: creating a linked account and recording a sign-in change the
    account (its row, its role) in the same transaction as the link.
    """

    async def get(self, issuer: str, subject: str) -> ExternalIdentity | None:
        """Return the link of this identity, or ``None``.

        Args:
            issuer: The provider's issuer.
            subject: The person's identifier at the issuer.

        Returns:
            The link, or ``None``.
        """
        ...

    async def get_for_account(self, account_id: AccountId) -> ExternalIdentity | None:
        """Return the link of this account, or ``None`` (a local account has none).

        Args:
            account_id: The account's id.

        Returns:
            The link, or ``None``.
        """
        ...

    async def create_linked_account(
        self, account: Account, identity: ExternalIdentity, groups: frozenset[str]
    ) -> LinkOutcome:
        """Store a new account, its link and its groups, all or nothing.

        Args:
            account: The new account (without a password).
            identity: Its link.
            groups: Its groups, as ExactDocs stores them.

        Returns:
            ``created``; ``username_taken`` when another account has the username;
            ``already_linked`` when the identity was linked meanwhile (nothing is stored).
        """
        ...

    async def record_check(
        self, identity: ExternalIdentity, *, role: Role, groups: frozenset[str]
    ) -> None:
        """Store a successful sign-in or revalidation, in one transaction.

        The link's times and tokens, the account's role and its groups (replacing the old ones).

        Args:
            identity: The link as it is now.
            role: The account's role now.
            groups: The account's groups now, as ExactDocs stores them.
        """
        ...

    async def record_revalidation(
        self,
        claimed: ExternalIdentity,
        checked: ExternalIdentity,
        *,
        role: Role,
        groups: frozenset[str],
    ) -> bool:
        """Store a successful revalidation, unless the link changed since it was claimed.

        A revalidation waits on the provider between ``claim_due`` and this write. Meanwhile a
        disable may have dropped the tokens, a refused sign-in or a revocation may have ended
        access, and a sign-in (or another pass, after the lease) may have stored newer tokens.
        The write happens, in one transaction, only when the link still holds the tokens and
        the sign-in, check and access times it was claimed with and its account is not
        disabled; otherwise nothing is stored and the newer state stands.

        Args:
            claimed: The link as ``claim_due`` returned it.
            checked: The link after the check.
            role: The account's role now.
            groups: The account's groups now, as ExactDocs stores them.

        Returns:
            ``True`` when stored; ``False`` when the link had changed (nothing is stored).
        """
        ...

    async def revoke(self, account_id: AccountId, now: datetime) -> None:
        """End the account's access at ``now`` and drop its sealed tokens and groups.

        Args:
            account_id: The account.
            now: The current time.
        """
        ...

    async def forget_tokens(self, account_id: AccountId) -> None:
        """Drop the account's sealed tokens (nothing happens for a local account).

        Args:
            account_id: The account.
        """
        ...

    async def claim_due(
        self, now: datetime, *, lease_until: datetime, limit: int
    ) -> list[ExternalIdentity]:
        """Return links due for a check that have a token to check with, and lease them.

        Each returned link is due again only at ``lease_until``, so another process (or pass)
        skips it meanwhile; two concurrent claims never return the same link.

        Args:
            now: The current time: links with ``next_check_at`` at or before it are due.
            lease_until: Until when the claimed links are not due again.
            limit: The most links to claim.

        Returns:
            The claimed links, as they were before the lease.
        """
        ...

    async def groups_by_account(self) -> Mapping[AccountId, tuple[str, list[str]]]:
        """Return the provider and the groups of every linked account.

        Returns:
            For each linked account: its provider's name and its groups, sorted.
        """
        ...

    async def groups_of(self, account_id: AccountId) -> frozenset[str]:
        """Return the groups of one account (empty for a local account).

        Args:
            account_id: The account.

        Returns:
            Its groups, as ExactDocs stores them.
        """
        ...


class LibraryGrantRepository(Protocol):
    """Who holds which role on which library."""

    async def matching(
        self, libraries: Collection[str], *, account_id: AccountId, groups: frozenset[str]
    ) -> list[LibraryGrant]:
        """Return the grants on these libraries that apply to an account or one of its groups.

        Args:
            libraries: Library IDs, lower-case.
            account_id: The account.
            groups: The account's groups.

        Returns:
            The grants to the account itself and to each of its groups.
        """
        ...

    async def for_library(self, library: str) -> list[LibraryGrant]:
        """Return every grant on a library.

        Args:
            library: The library ID, lower-case.

        Returns:
            The grants, users first, each kind by subject.
        """
        ...

    async def get(self, library: str, kind: SubjectKind, subject: str) -> LibraryGrant | None:
        """Return the grant of one user or group on a library, or ``None``.

        Args:
            library: The library ID, lower-case.
            kind: Whether ``subject`` is an account ID or a group name.
            subject: The account ID or the group name.

        Returns:
            The grant, or ``None``.
        """
        ...

    async def put(self, grant: LibraryGrant) -> None:
        """Store a grant, replacing the role the subject had on the library.

        Args:
            grant: The grant.
        """
        ...

    async def remove(self, library: str, kind: SubjectKind, subject: str) -> bool:
        """Delete one grant.

        Args:
            library: The library ID, lower-case.
            kind: Whether ``subject`` is an account ID or a group name.
            subject: The account ID or the group name.

        Returns:
            ``False`` when there was no such grant.
        """
        ...

    async def claim(self, library: str, account_id: AccountId) -> None:
        """Replace every grant on a library by the creator's, in one step.

        Args:
            library: The library ID, lower-case.
            account_id: The creator.
        """
        ...

    async def transfer(self, library: str, account_id: AccountId) -> list[AccountId]:
        """Make the account the library's creator in one step; the creators before become admins.

        The account's earlier grant on the library, if any, is replaced.

        Args:
            library: The library ID, lower-case.
            account_id: The new creator.

        Returns:
            The accounts that were the library's creator before (none for a library that had
            no creator).
        """
        ...

    async def clear(self, library: str) -> None:
        """Delete every grant on a library.

        Args:
            library: The library ID, lower-case.
        """
        ...


class AccessLog(Protocol):
    """The access log: grants, revocations, ownership transfers and deletions (append-only)."""

    async def record(self, event: AccessEvent) -> None:
        """Append an event.

        Args:
            event: What changed, by whom and when.
        """
        ...

    async def newest(
        self, where: AccessLogFilter, *, older_than: str | None, limit: int, offset: int = 0
    ) -> list[AccessEvent]:
        """Return the newest events that match, newest first.

        Args:
            where: Which events.
            older_than: Only events recorded before the one with this ID (a page's cursor).
            limit: Most events returned.
            offset: How many of the matching events, newest first, to skip first.

        Returns:
            Up to ``limit`` events, by ID descending.
        """
        ...

    async def count(self, where: AccessLogFilter) -> int:
        """Count the events that match.

        Args:
            where: Which events.

        Returns:
            How many there are.
        """
        ...
