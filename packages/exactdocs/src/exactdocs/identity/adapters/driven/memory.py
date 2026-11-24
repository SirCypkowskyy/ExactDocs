from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from exactdocs.identity.constants import (
    FREE_FAILURES,
    MAX_FAILED_SIGN_IN_KEYS,
    REMEMBER_SIGN_INS_FOR,
)
from exactdocs.identity.models import (
    AccessEvent,
    AccessLogFilter,
    Account,
    AccountId,
    ApiToken,
    ExternalIdentity,
    FailedSignIns,
    LibraryGrant,
    LibraryRole,
    Role,
    Session,
    SignInAttempt,
    SubjectKind,
    Username,
    known_sign_ins_prefix,
)
from exactdocs.identity.ports.driven import LinkOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryAccountRepository:
    """Implements ``ports.driven.AccountRepository``. For tests."""

    accounts: dict[Username, Account] = field(default_factory=dict)
    """The accounts, by username."""

    async def add_first(self, account: Account) -> bool:
        """Store the account only if no account exists yet.

        Args:
            account: The first account.

        Returns:
            ``True`` when it was stored, ``False`` when an account already exists.
        """
        if self.accounts:
            return False
        self.accounts[account.username] = account
        return True

    async def add(self, account: Account) -> bool:
        """Store a further account, unless its username is taken.

        Args:
            account: The new account.

        Returns:
            ``True`` when it was stored, ``False`` when another account has the username.
        """
        if account.username in self.accounts:
            return False
        self.accounts[account.username] = account
        return True

    async def list_all(self) -> list[Account]:
        """Return every account, oldest first (then by username).

        Returns:
            The accounts.
        """
        return sorted(self.accounts.values(), key=lambda a: (a.created_at, a.username.value))

    async def set_disabled_at(self, account_id: AccountId, disabled_at: datetime | None) -> bool:
        """Disable or enable the account, never disabling the last enabled admin.

        Args:
            account_id: The account's id.
            disabled_at: When it was disabled, or ``None`` to enable it.

        Returns:
            ``False`` when disabling was refused to keep an enabled admin, else ``True``.
        """
        account = await self.get_by_id(account_id)
        if account is None:
            return True
        if disabled_at is not None and account.is_operator and not account.is_disabled:
            others = [
                a
                for a in self.accounts.values()
                if a.id != account_id and a.is_operator and not a.is_disabled
            ]
            if not others:
                return False
        self.accounts[account.username] = replace(account, disabled_at=disabled_at)
        return True

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``.

        Args:
            username: The normalized username.

        Returns:
            The account, or ``None``.
        """
        return self.accounts.get(username)

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        """Return the account with this id, or ``None``.

        Args:
            account_id: The account's id.

        Returns:
            The account, or ``None``.
        """
        return next((a for a in self.accounts.values() if a.id == account_id), None)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        """Replace the account's password hash.

        Args:
            account_id: The account's id.
            password_hash: The new encoded hash.
        """
        account = await self.get_by_id(account_id)
        if account is not None:
            self.accounts[account.username] = replace(account, password_hash=password_hash)

    async def any_exists(self) -> bool:
        """Return whether at least one account exists.

        Returns:
            ``True`` once an account exists.
        """
        return bool(self.accounts)

    async def record_activity(self, account_id: AccountId, hour: datetime) -> None:
        """Move the account's ``last_active_at`` forward to ``hour``, never back.

        Args:
            account_id: The account's id.
            hour: The hour it was active.
        """
        account = await self.get_by_id(account_id)
        if account is not None and (
            account.last_active_at is None or account.last_active_at < hour
        ):
            self.accounts[account.username] = replace(account, last_active_at=hour)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemorySessionRepository:
    """Implements ``ports.driven.SessionRepository``. For tests."""

    sessions: dict[str, Session] = field(default_factory=dict)
    """The sessions, by token hash."""

    async def add(self, session: Session) -> None:
        """Store a new session.

        Args:
            session: The session.
        """
        self.sessions[session.token_hash] = session

    async def get(self, token_hash: str) -> Session | None:
        """Return the session with this token hash, or ``None``.

        Args:
            token_hash: The hash of the session token.

        Returns:
            The session, or ``None``.
        """
        return self.sessions.get(token_hash)

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the session was used at ``at``.

        Args:
            token_hash: The hash of the session token.
            at: When it was used.
        """
        if (session := self.sessions.get(token_hash)) is not None:
            self.sessions[token_hash] = replace(session, last_used_at=at)

    async def delete(self, token_hash: str) -> None:
        """Remove the session.

        Args:
            token_hash: The hash of the session token.
        """
        self.sessions.pop(token_hash, None)

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every session of the account.

        Args:
            account_id: The account's id.
        """
        for token_hash in [h for h, s in self.sessions.items() if s.account_id == account_id]:
            del self.sessions[token_hash]

    async def delete_others(self, account_id: AccountId, *, keep: str | None) -> None:
        """Remove every session of the account but the one with the token hash ``keep``.

        Args:
            account_id: The account's id.
            keep: The hash of the session token that stays; ``None`` removes them all.
        """
        for token_hash in [
            h for h, s in self.sessions.items() if s.account_id == account_id and h != keep
        ]:
            del self.sessions[token_hash]

    async def delete_expired(self, *, idle_before: datetime, created_before: datetime) -> None:
        """Remove sessions last used before ``idle_before`` or created before ``created_before``.

        Args:
            idle_before: Idle deadline: sessions last used before it go.
            created_before: Absolute deadline: sessions created before it go.
        """
        for token_hash in [
            h
            for h, s in self.sessions.items()
            if s.last_used_at < idle_before or s.created_at < created_before
        ]:
            del self.sessions[token_hash]


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryTokenRepository:
    """Implements ``ports.driven.TokenRepository``. For tests."""

    tokens: dict[str, ApiToken] = field(default_factory=dict)
    """The tokens, by the hash of their secret."""

    async def add(self, token: ApiToken) -> None:
        """Store a new token.

        Args:
            token: The token.
        """
        self.tokens[token.token_hash] = token

    async def get(self, token_hash: str) -> ApiToken | None:
        """Return the token with this hash, or ``None``.

        Args:
            token_hash: The hash of the token's secret.

        Returns:
            The token, or ``None``.
        """
        return self.tokens.get(token_hash)

    async def list_for_account(self, account_id: AccountId) -> list[ApiToken]:
        """Return the account's tokens, newest first.

        Args:
            account_id: The account's id.

        Returns:
            The tokens, newest first.
        """
        own = [t for t in self.tokens.values() if t.account_id == account_id]
        return sorted(own, key=lambda t: (t.created_at, t.id), reverse=True)

    async def list_all(self) -> list[ApiToken]:
        """Return every account's tokens, newest first.

        Returns:
            The tokens, newest first.
        """
        return sorted(self.tokens.values(), key=lambda t: (t.created_at, t.id), reverse=True)

    async def count_by_account(self, now: datetime) -> Mapping[AccountId, int]:
        """Count each account's tokens that have not expired at ``now``.

        Args:
            now: The current time.

        Returns:
            The count per account; an account without a live token is absent.
        """
        return Counter(t.account_id for t in self.tokens.values() if not t.is_expired(now))

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the token was used at ``at``.

        Args:
            token_hash: The hash of the token's secret.
            at: When it was used.
        """
        if (token := self.tokens.get(token_hash)) is not None:
            self.tokens[token_hash] = replace(token, last_used_at=at)

    async def delete(self, account_id: AccountId, token_id: str) -> bool:
        """Remove the account's token with this id; ``False`` when there is none.

        Args:
            account_id: The owner's id.
            token_id: The token's id.

        Returns:
            ``True`` when a token was removed, ``False`` when the account has none by this id.
        """
        for token_hash, token in self.tokens.items():
            if token.id == token_id and token.account_id == account_id:
                del self.tokens[token_hash]
                return True
        return False

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every token of the account.

        Args:
            account_id: The account's id.
        """
        for token_hash in [h for h, t in self.tokens.items() if t.account_id == account_id]:
            del self.tokens[token_hash]

    async def delete_expired(self, now: datetime) -> None:
        """Remove the tokens whose expiry is at or before ``now``.

        Args:
            now: The current time.
        """
        for token_hash in [h for h, t in self.tokens.items() if t.is_expired(now)]:
            del self.tokens[token_hash]


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryFailedSignInLog:
    """Implements ``ports.driven.FailedSignInLog`` in the process's memory. Used on SQLite.

    A restart forgets everything, and each process counts its own: on PostgreSQL, where several
    processes serve, ``SqliteFailedSignInLog`` shares the counts instead.
    ``charge`` never awaits, so on one event loop the check and the count cannot interleave
    with another attempt's. At most ``max_keys`` counts and ``max_keys`` remembered sign-ins are
    kept. Dict order is "least recently changed first", which is also oldest ``last_at`` first.
    When full, the oldest count that does not hold anyone back (under ``FREE_FAILURES``, or
    forgotten) is dropped, and only when every count does, the oldest of all: a flood of
    made-up usernames then pushes out its own records, not a live throttle on a real one.
    """

    max_keys: int = MAX_FAILED_SIGN_IN_KEYS
    """Most counts, and most remembered sign-ins, kept."""
    records: dict[str, FailedSignIns] = field(default_factory=dict)
    """The failure counts by throttle key, least recently changed first."""
    sign_ins: dict[str, datetime] = field(default_factory=dict)
    """When each sign-in key last succeeded, least recent first."""

    async def charge(self, keys: Sequence[str], now: datetime) -> timedelta:
        """Count one attempt against every key unless one must wait; return the longest wait.

        Args:
            keys: The throttle keys of the attempt (its address and its username).
            now: When the attempt is made.

        Returns:
            The longest wait among the keys; zero when the attempt was counted and may go ahead.
        """
        records = {key: self.records.get(key) for key in keys}
        wait = max((r.wait(now) for r in records.values() if r), default=timedelta(0))
        if wait > timedelta(0):
            return wait
        for key, record in records.items():
            self._put(key, record.plus_one(now) if record else FailedSignIns(count=1, last_at=now))
        return timedelta(0)

    async def refund(self, key: str, charged_at: datetime) -> None:
        """Take back the attempt charged under ``key`` at ``charged_at``; its place stays.

        Args:
            key: The throttle key.
            charged_at: The ``now`` the attempt was charged with.
        """
        record = self.records.get(key)
        if record is None:
            return
        if (fewer := record.refunded(charged_at)) is None:
            del self.records[key]
        else:
            self.records[key] = fewer

    async def get(self, key: str) -> FailedSignIns | None:
        """Return the record under ``key``, or ``None``.

        Args:
            key: The throttle key.

        Returns:
            The record, or ``None``.
        """
        return self.records.get(key)

    async def forget(self, key: str) -> bool:
        """Drop the record under ``key``.

        Args:
            key: The throttle key.

        Returns:
            Always ``True``: the process's memory is never busy.
        """
        self.records.pop(key, None)
        return True

    async def forget_remembered(self, username: str) -> bool:
        """Forget every address remembered for ``username``.

        Args:
            username: The username.

        Returns:
            Always ``True``: the process's memory is never busy.
        """
        prefix = known_sign_ins_prefix(username)
        for key in [k for k in self.sign_ins if k.startswith(prefix)]:
            del self.sign_ins[key]
        return True

    async def remember_sign_in(self, key: str, now: datetime) -> None:
        """Remember the sign-in as the most recent one, dropping the oldest when full.

        Args:
            key: The sign-in key.
            now: When the sign-in succeeded.
        """
        self.sign_ins.pop(key, None)
        while len(self.sign_ins) >= self.max_keys:
            del self.sign_ins[next(iter(self.sign_ins))]
        self.sign_ins[key] = now

    async def signed_in_before(self, key: str, now: datetime) -> bool:
        """Whether ``key`` succeeded within ``REMEMBER_SIGN_INS_FOR``.

        Args:
            key: The sign-in key.
            now: The current time.

        Returns:
            ``True`` when it did.
        """
        last = self.sign_ins.get(key)
        return last is not None and now - last < REMEMBER_SIGN_INS_FOR

    def _put(self, key: str, failures: FailedSignIns) -> None:
        """Store ``failures`` under ``key`` as the most recent record, making room when full.

        Args:
            key: The throttle key.
            failures: The new record.
        """
        self.records.pop(key, None)  # re-inserted below as the most recent
        if len(self.records) >= self.max_keys:
            del self.records[self._least_needed(failures.last_at)]
        self.records[key] = failures

    def _least_needed(self, now: datetime) -> str:
        """Pick the record to drop when the log is full.

        Args:
            now: The time of the attempt being stored.

        Returns:
            The key of the oldest record that holds no one back, else of the oldest record.
        """
        for key, record in self.records.items():
            if record.count < FREE_FAILURES or record.is_forgotten(now):
                return key
        return next(iter(self.records))


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemorySignInAttemptRepository:
    """Implements ``ports.driven.SignInAttemptRepository``. For tests."""

    attempts: dict[str, SignInAttempt] = field(default_factory=dict)
    """The attempts, by binding hash."""

    async def add(self, attempt: SignInAttempt, *, expired_before: datetime) -> None:
        """Store a new attempt after pruning the expired ones.

        Args:
            attempt: The attempt.
            expired_before: Attempts started before this are dropped.
        """
        for key in [k for k, a in self.attempts.items() if a.created_at < expired_before]:
            del self.attempts[key]
        self.attempts[attempt.binding_hash] = attempt

    async def take(self, binding_hash: str) -> SignInAttempt | None:
        """Remove and return the attempt of this binding.

        Args:
            binding_hash: The hash of the browser's binding value.

        Returns:
            The attempt, or ``None``.
        """
        return self.attempts.pop(binding_hash, None)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryExternalIdentityRepository:
    """Implements ``ports.driven.ExternalIdentityRepository`` over an in-memory account store."""

    accounts: InMemoryAccountRepository
    """The accounts the links point to (they share its storage, as the tables do)."""
    links: dict[tuple[str, str], ExternalIdentity] = field(default_factory=dict)
    """The links, by (issuer, subject)."""
    groups: dict[AccountId, frozenset[str]] = field(default_factory=dict)
    """Each linked account's groups."""

    async def get(self, issuer: str, subject: str) -> ExternalIdentity | None:
        """Return the link of this identity, or ``None``.

        Args:
            issuer: The provider's issuer.
            subject: The person's identifier at the issuer.

        Returns:
            The link, or ``None``.
        """
        return self.links.get((issuer, subject))

    async def get_for_account(self, account_id: AccountId) -> ExternalIdentity | None:
        """Return the link of this account, or ``None``.

        Args:
            account_id: The account's id.

        Returns:
            The link, or ``None``.
        """
        return next((ln for ln in self.links.values() if ln.account_id == account_id), None)

    async def create_linked_account(
        self, account: Account, identity: ExternalIdentity, groups: frozenset[str]
    ) -> LinkOutcome:
        """Store a new account, its link and its groups, all or nothing.

        Args:
            account: The new account.
            identity: Its link.
            groups: Its groups.

        Returns:
            ``created``, ``username_taken`` or ``already_linked``.
        """
        if (identity.issuer, identity.subject) in self.links:
            return "already_linked"
        if not await self.accounts.add(account):
            return "username_taken"
        self.links[identity.issuer, identity.subject] = identity
        self.groups[account.id] = groups
        return "created"

    async def record_check(
        self, identity: ExternalIdentity, *, role: Role, groups: frozenset[str]
    ) -> None:
        """Store a successful sign-in or revalidation.

        Args:
            identity: The link as it is now.
            role: The account's role now.
            groups: The account's groups now.
        """
        self.links[identity.issuer, identity.subject] = identity
        self.groups[identity.account_id] = groups
        account = await self.accounts.get_by_id(identity.account_id)
        if account is not None:
            self.accounts.accounts[account.username] = replace(account, role=role)

    async def record_revalidation(
        self,
        claimed: ExternalIdentity,
        checked: ExternalIdentity,
        *,
        role: Role,
        groups: frozenset[str],
    ) -> bool:
        """Store a successful revalidation, unless the link changed since it was claimed.

        Args:
            claimed: The link as ``claim_due`` returned it.
            checked: The link after the check.
            role: The account's role now.
            groups: The account's groups now.

        Returns:
            ``True`` when stored; ``False`` when the link had changed.
        """
        current = self.links.get((claimed.issuer, claimed.subject))
        account = await self.accounts.get_by_id(claimed.account_id)
        if current is None or account is None or account.is_disabled:
            return False
        if _revision(current) != _revision(claimed):
            return False
        await self.record_check(checked, role=role, groups=groups)
        return True

    async def revoke(self, account_id: AccountId, now: datetime) -> None:
        """End the account's access now, dropping its tokens and groups.

        Args:
            account_id: The account.
            now: The current time.
        """
        link = await self.get_for_account(account_id)
        if link is not None:
            self.links[link.issuer, link.subject] = replace(
                link, access_until=now, sealed_tokens=None
            )
        self.groups.pop(account_id, None)

    async def forget_tokens(self, account_id: AccountId) -> None:
        """Drop the account's sealed tokens.

        Args:
            account_id: The account.
        """
        link = await self.get_for_account(account_id)
        if link is not None:
            self.links[link.issuer, link.subject] = replace(link, sealed_tokens=None)

    async def claim_due(
        self, now: datetime, *, lease_until: datetime, limit: int
    ) -> list[ExternalIdentity]:
        """Return due links that hold a token, leasing them until ``lease_until``.

        Args:
            now: The current time.
            lease_until: Until when the claimed links are not due again.
            limit: The most links to claim.

        Returns:
            The claimed links, as they were before the lease.
        """
        due = sorted(
            (ln for ln in self.links.values() if ln.sealed_tokens and ln.next_check_at <= now),
            key=lambda ln: ln.next_check_at,
        )[:limit]
        for link in due:
            self.links[link.issuer, link.subject] = replace(link, next_check_at=lease_until)
        return due

    async def groups_by_account(self) -> Mapping[AccountId, tuple[str, list[str]]]:
        """Return the provider and the groups of every linked account.

        Returns:
            For each linked account: its provider's name and its groups, sorted.
        """
        return {
            ln.account_id: (ln.provider, sorted(self.groups.get(ln.account_id, ())))
            for ln in self.links.values()
        }

    async def groups_of(self, account_id: AccountId) -> frozenset[str]:
        """Return the groups of one account (empty for a local account).

        Args:
            account_id: The account.

        Returns:
            Its groups.
        """
        return self.groups.get(account_id, frozenset())


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibraryGrantRepository:
    """Implements ``ports.driven.LibraryGrantRepository``. For tests."""

    grants: dict[tuple[str, SubjectKind, str], LibraryGrant] = field(default_factory=dict)
    """The grants, by (library, kind, subject)."""

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
        wanted = set(libraries)
        return [
            grant
            for grant in self.grants.values()
            if grant.library in wanted
            and (
                (grant.kind is SubjectKind.USER and grant.subject == account_id)
                or (grant.kind is SubjectKind.GROUP and grant.subject in groups)
            )
        ]

    async def for_library(self, library: str) -> list[LibraryGrant]:
        """Return every grant on a library.

        Args:
            library: The library ID, lower-case.

        Returns:
            The grants, users first, each kind by subject.
        """
        return sorted(
            (g for g in self.grants.values() if g.library == library),
            key=lambda g: (g.kind is not SubjectKind.USER, g.subject),
        )

    async def get(self, library: str, kind: SubjectKind, subject: str) -> LibraryGrant | None:
        """Return the grant of one user or group on a library, or ``None``.

        Args:
            library: The library ID, lower-case.
            kind: Whether ``subject`` is an account ID or a group name.
            subject: The account ID or the group name.

        Returns:
            The grant, or ``None``.
        """
        return self.grants.get((library, kind, subject))

    async def put(self, grant: LibraryGrant) -> None:
        """Store a grant, replacing the role the subject had on the library.

        Args:
            grant: The grant.
        """
        self.grants[grant.library, grant.kind, grant.subject] = grant

    async def remove(self, library: str, kind: SubjectKind, subject: str) -> bool:
        """Delete one grant.

        Args:
            library: The library ID, lower-case.
            kind: Whether ``subject`` is an account ID or a group name.
            subject: The account ID or the group name.

        Returns:
            ``False`` when there was no such grant.
        """
        return self.grants.pop((library, kind, subject), None) is not None

    async def claim(self, library: str, account_id: AccountId) -> None:
        """Replace every grant on a library by the creator's.

        Args:
            library: The library ID, lower-case.
            account_id: The creator.
        """
        await self.clear(library)
        await self.put(
            LibraryGrant(
                library=library,
                kind=SubjectKind.USER,
                subject=account_id,
                role=LibraryRole.CREATOR,
            )
        )

    async def transfer(self, library: str, account_id: AccountId) -> list[AccountId]:
        """Make the account the library's creator; the creators before become admins.

        Args:
            library: The library ID, lower-case.
            account_id: The new creator.

        Returns:
            The accounts that were the library's creator before.
        """
        previous = [
            g
            for g in self.grants.values()
            if g.library == library and g.kind is SubjectKind.USER and g.role is LibraryRole.CREATOR
        ]
        for grant in previous:
            await self.put(replace(grant, role=LibraryRole.ADMIN))
        await self.put(
            LibraryGrant(
                library=library,
                kind=SubjectKind.USER,
                subject=account_id,
                role=LibraryRole.CREATOR,
            )
        )
        return sorted(AccountId(g.subject) for g in previous)

    async def clear(self, library: str) -> None:
        """Delete every grant on a library.

        Args:
            library: The library ID, lower-case.
        """
        for key in [k for k in self.grants if k[0] == library]:
            del self.grants[key]


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryAccessLog:
    """Implements ``ports.driven.AccessLog``. For tests."""

    events: list[AccessEvent] = field(default_factory=list)
    """The events, in the order they were recorded."""

    async def record(self, event: AccessEvent) -> None:
        """Append an event.

        Args:
            event: What changed, by whom and when.
        """
        self.events.append(event)

    def _matching(self, where: AccessLogFilter) -> list[AccessEvent]:
        """Return the events that match, newest first.

        Args:
            where: Which events.

        Returns:
            The events, by ID descending.
        """
        return sorted(
            (
                e
                for e in self.events
                if (where.library is None or e.library == where.library)
                and (where.changes is None or e.change in where.changes)
                and (where.newer_than is None or e.id > where.newer_than)
            ),
            key=lambda e: e.id,
            reverse=True,
        )

    async def newest(
        self, where: AccessLogFilter, *, older_than: str | None, limit: int, offset: int = 0
    ) -> list[AccessEvent]:
        """Return the newest events that match, newest first.

        Args:
            where: Which events.
            older_than: Only events recorded before the one with this ID.
            limit: Most events returned.
            offset: How many of the matching events, newest first, to skip first.

        Returns:
            Up to ``limit`` events, by ID descending.
        """
        found = self._matching(where)
        older = [e for e in found if older_than is None or e.id < older_than]
        return older[offset : offset + limit]

    async def count(self, where: AccessLogFilter) -> int:
        """Count the events that match.

        Args:
            where: Which events.

        Returns:
            How many there are.
        """
        return len(self._matching(where))


def _revision(link: ExternalIdentity) -> tuple[object, ...]:
    """Return what a sign-in, a revalidation, a revocation or a disable changes in a link.

    The lease (``next_check_at``) is left out: claiming a link changes it.

    Args:
        link: The link.

    Returns:
        The fields compared before a revalidation is stored.
    """
    return (
        link.account_id,
        link.sealed_tokens,
        link.signed_in_at,
        link.checked_at,
        link.access_until,
    )
