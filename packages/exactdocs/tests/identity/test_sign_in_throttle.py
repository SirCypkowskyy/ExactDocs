"""The sign-in throttle: per client address and per username, with a doubling wait."""

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from exactdocs.identity.adapters.driven.argon2id import Argon2idPasswordHasher
from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccountRepository,
    InMemoryFailedSignInLog,
    InMemorySessionRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.constants import (
    FIRST_WAIT,
    FORGET_FAILURES_AFTER,
    FREE_FAILURES,
    LONGEST_WAIT,
    REMEMBER_SIGN_INS_FOR,
)
from exactdocs.identity.dtos import (
    AuthenticateQuery,
    CreateFirstAdminCommand,
    LoginForTokenCommand,
)
from exactdocs.identity.errors import InvalidCredentialsError, SignInThrottledError
from exactdocs.identity.models import FailedSignIns, address_key
from exactdocs.identity.module import IdentityModule

HORSE = "correct horse battery staple"
WRONG = "wrong horse battery staple"
START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
ATTACKER, ADMIN_HOST = "203.0.113.7", "198.51.100.2"


@dataclass(slots=True)
class MovableClock:
    current: datetime = START

    def now(self) -> datetime:
        return self.current

    def advance(self, by: timedelta) -> None:
        self.current += by


@dataclass(slots=True)
class CountingHasher:
    """A fast reversible stand-in for the KDF that counts the passwords it was asked about."""

    checks: int = 0

    async def hash(self, password: str) -> str:
        self.checks += 1
        return f"fake${password[::-1]}"

    async def verify(self, password_hash: str, password: str) -> bool:
        self.checks += 1
        return password_hash == f"fake${password[::-1]}"


@dataclass(slots=True)
class World:
    identity: IdentityModule
    hasher: CountingHasher
    clock: MovableClock
    failures: InMemoryFailedSignInLog = field(default_factory=InMemoryFailedSignInLog)


@pytest.fixture
async def world() -> World:
    clock, hasher, failures = MovableClock(), CountingHasher(), InMemoryFailedSignInLog()
    identity = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=hasher,
        failures=failures,
        clock=clock,
    )
    await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    )
    return World(identity, hasher, clock, failures)


def credentials(username: str = "ada", password: str = HORSE) -> AuthenticateQuery:
    return AuthenticateQuery(username=username, password=SecretStr(password))


async def fail(world: World, times: int, *, username: str = "root", client: str = ATTACKER) -> None:
    for _ in range(times):
        with pytest.raises(InvalidCredentialsError):
            await world.identity.authenticate(credentials(username, WRONG), client=client)


async def test_the_first_failures_are_free(world: World) -> None:
    await fail(world, FREE_FAILURES - 1)

    await fail(world, 1)  # the last free one is still checked, and still just wrong


async def test_past_the_free_failures_the_address_must_wait(world: World) -> None:
    await fail(world, FREE_FAILURES)
    checks = world.hasher.checks

    with pytest.raises(SignInThrottledError) as refused:
        await world.identity.authenticate(credentials(), client=ATTACKER)  # even the right one

    assert refused.value.code == "rate_limited"
    assert refused.value.retry_after == FIRST_WAIT.total_seconds()
    assert world.hasher.checks == checks  # the password was not even checked
    assert "root" not in str(refused.value)
    assert ATTACKER not in str(refused.value)


async def test_the_wait_doubles_with_each_failure_up_to_a_ceiling(world: World) -> None:
    waits = []
    for _ in range(FREE_FAILURES + 12):
        await fail(world, 1)
        record = await world.failures.get(f"address:{ATTACKER}")
        assert record is not None
        waits.append(record.wait(world.clock.now()))
        world.clock.advance(record.wait(world.clock.now()))  # wait it out, then fail again

    assert waits[: FREE_FAILURES - 1] == [timedelta(0)] * (FREE_FAILURES - 1)
    assert waits[FREE_FAILURES - 1 : FREE_FAILURES + 2] == [
        FIRST_WAIT,
        FIRST_WAIT * 2,
        FIRST_WAIT * 4,
    ]
    assert waits[-1] == LONGEST_WAIT


async def test_once_the_wait_is_over_the_next_attempt_is_checked(world: World) -> None:
    await fail(world, FREE_FAILURES)
    world.clock.advance(FIRST_WAIT)

    assert (await world.identity.authenticate(credentials(), client=ATTACKER)).username == "ada"


async def test_failures_are_forgotten_after_a_quiet_hour(world: World) -> None:
    await fail(world, FREE_FAILURES)
    world.clock.advance(FORGET_FAILURES_AFTER)

    await fail(world, FREE_FAILURES - 1)  # a fresh count: all free again


async def test_another_address_and_username_are_not_affected(world: World) -> None:
    await fail(world, FREE_FAILURES, username="root")

    signed_in = await world.identity.authenticate(credentials(), client=ADMIN_HOST)

    assert signed_in.username == "ada"


async def test_a_username_is_throttled_from_every_address(world: World) -> None:
    for n in range(FREE_FAILURES):
        await fail(
            world, 1, username="ADA", client=f"192.0.2.{n}"
        )  # case-insensitive, like accounts

    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(credentials(), client=ADMIN_HOST)
    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(credentials())  # no address known: still the username


async def test_a_right_password_clears_the_username_but_not_the_address(world: World) -> None:
    await fail(world, FREE_FAILURES - 1, username="ada")

    await world.identity.authenticate(credentials(), client=ATTACKER)

    assert await world.failures.get("username:ada") is None
    record = await world.failures.get(f"address:{ATTACKER}")
    assert record is not None
    assert record.count == FREE_FAILURES - 1


@pytest.mark.parametrize("typos", [FREE_FAILURES, FREE_FAILURES + 8], ids=["first-wait", "long"])
async def test_a_second_sign_in_right_after_a_correct_one_is_not_refused(
    world: World, typos: int
) -> None:
    last_typo = START
    for _ in range(typos):  # typos from the address, waiting each wait out
        world.clock.advance(timedelta(seconds=1))
        await fail(world, 1, username="ada", client=ADMIN_HOST)
        last_typo = world.clock.now()
        record = await world.failures.get(f"address:{ADMIN_HOST}")
        assert record is not None
        world.clock.advance(record.wait(world.clock.now()))

    await world.identity.authenticate(credentials(), client=ADMIN_HOST)  # e.g. the web sign-in
    world.clock.advance(timedelta(seconds=1))
    signed_in = await world.identity.authenticate(credentials(), client=ADMIN_HOST)  # the CLI

    assert signed_in.username == "ada"
    record = await world.failures.get(f"address:{ADMIN_HOST}")
    assert record == FailedSignIns(count=typos, last_at=last_typo)


async def test_a_refund_after_a_later_attempt_only_lowers_the_count() -> None:
    log = InMemoryFailedSignInLog()
    later = START + timedelta(seconds=1)
    await log.charge(["address:a"], START)
    await log.charge(["address:a"], later)

    await log.refund("address:a", START)  # the first attempt was the right password

    record = await log.get("address:a")
    assert record is not None
    assert (record.count, record.last_at) == (1, later)


async def test_refunding_the_only_attempt_leaves_no_record() -> None:
    log = InMemoryFailedSignInLog()
    await log.charge(["address:a"], START)

    await log.refund("address:a", START)

    assert await log.get("address:a") is None


async def test_invalid_usernames_count_against_the_address(world: World) -> None:
    await fail(world, FREE_FAILURES, username="not a valid\nname")

    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(credentials(), client=ATTACKER)


async def test_sign_in_and_token_login_share_the_throttle(world: World) -> None:
    for _ in range(FREE_FAILURES):
        with pytest.raises(InvalidCredentialsError):
            await world.identity.sign_in(credentials("root", WRONG), client=ATTACKER)

    command = LoginForTokenCommand(username="ada", password=SecretStr(HORSE), name="laptop")
    with pytest.raises(SignInThrottledError):
        await world.identity.login_for_token(command, client=ATTACKER)
    with pytest.raises(SignInThrottledError):
        await world.identity.sign_in(credentials(), client=ATTACKER)


def test_a_record_never_overflows_however_many_failures() -> None:
    record = FailedSignIns(count=10**9, last_at=START)

    assert record.wait(START) == LONGEST_WAIT


async def test_the_log_keeps_a_bounded_number_of_records() -> None:
    log = InMemoryFailedSignInLog(max_keys=3)
    for key in "abcd":
        await log.charge([key], START)
    await log.charge(["b"], START)  # b is now the most recent
    await log.charge(["e"], START)

    assert list(log.records) == ["d", "b", "e"]


async def test_a_full_log_drops_records_that_hold_no_one_back_first() -> None:
    log = InMemoryFailedSignInLog(max_keys=3)
    for _ in range(FREE_FAILURES):
        await log.charge(["username:ada"], START)  # the oldest record, and a live throttle
    await log.charge(["junk-1"], START)
    await log.charge(["junk-2"], START)

    for n in range(3, 10):  # a flood of made-up usernames
        await log.charge([f"junk-{n}"], START)

    assert "username:ada" in log.records
    assert len(log.records) == 3


async def test_a_refused_charge_counts_nothing() -> None:
    log = InMemoryFailedSignInLog()
    for _ in range(FREE_FAILURES):
        assert await log.charge(["address:a"], START) == timedelta(0)

    assert await log.charge(["address:a", "username:b"], START) == FIRST_WAIT
    assert await log.get("username:b") is None
    record = await log.get("address:a")
    assert record is not None
    assert record.count == FREE_FAILURES


async def test_the_owner_still_signs_in_from_a_known_address_when_others_hammer_the_username(
    world: World,
) -> None:
    await world.identity.authenticate(credentials(), client=ADMIN_HOST)  # the owner, once
    for n in range(FREE_FAILURES):
        await fail(world, 1, username="ada", client=f"192.0.2.{n}")  # others, from elsewhere

    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(credentials(), client="192.0.2.99")  # a new address
    signed_in = await world.identity.authenticate(credentials(), client=ADMIN_HOST)

    assert signed_in.username == "ada"


async def test_a_known_address_is_still_held_to_its_own_count(world: World) -> None:
    await world.identity.authenticate(credentials(), client=ADMIN_HOST)
    await fail(world, FREE_FAILURES, username="ada", client=ADMIN_HOST)

    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(credentials(), client=ADMIN_HOST)


async def test_a_known_address_is_forgotten_after_a_while(world: World) -> None:
    await world.identity.authenticate(credentials(), client=ADMIN_HOST)
    world.clock.advance(REMEMBER_SIGN_INS_FOR)
    for n in range(FREE_FAILURES):
        await fail(world, 1, username="ada", client=f"192.0.2.{n}")

    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(credentials(), client=ADMIN_HOST)


async def test_ipv6_clients_are_counted_per_64(world: World) -> None:
    for n in range(FREE_FAILURES):
        await fail(world, 1, username=f"user{n}", client=f"2001:db8:1:2::{n:x}")

    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(credentials(), client="2001:db8:1:2:ffff::1")
    signed_in = await world.identity.authenticate(credentials(), client="2001:db8:1:3::1")

    assert signed_in.username == "ada"


@pytest.mark.parametrize(
    ("client", "key"),
    [
        ("203.0.113.7", "address:203.0.113.7"),
        ("::ffff:203.0.113.7", "address:203.0.113.7"),
        ("64:ff9b::203.0.113.7", "address:203.0.113.7"),
        ("64:ff9b::1:203.0.113.7", "address:64:ff9b::/64"),
        ("2001:db8:1:2:3:4:5:6", "address:2001:db8:1:2::/64"),
        ("testclient", "address:testclient"),
    ],
)
def test_the_address_key(client: str, key: str) -> None:
    assert address_key(client) == key


@dataclass(slots=True)
class SlowArgon2:
    """Stands in for argon2-cffi: each call blocks a while, and the peak concurrency is kept."""

    running: int = 0
    peak: int = 0
    calls: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _work(self) -> None:
        with self.lock:
            self.calls += 1
            self.running += 1
            self.peak = max(self.peak, self.running)
        threading.Event().wait(0.02)
        with self.lock:
            self.running -= 1

    def hash(self, password: str) -> str:
        self._work()
        return f"h${password}"

    def verify(self, password_hash: str, password: str) -> bool:
        self._work()
        return password_hash == f"h${password}"


async def test_the_number_of_concurrent_password_checks_is_bounded() -> None:
    slow = SlowArgon2()
    hasher = Argon2idPasswordHasher(argon2=slow, max_concurrent=2)

    results = await asyncio.gather(
        *(hasher.verify("h$pw", "pw") for _ in range(6)), *(hasher.hash("pw") for _ in range(6))
    )

    assert slow.peak == 2
    assert results[:6] == [True] * 6


async def test_a_cancelled_check_keeps_its_slot_until_the_work_is_done() -> None:
    slow = SlowArgon2()
    hasher = Argon2idPasswordHasher(argon2=slow, max_concurrent=1)

    first = asyncio.ensure_future(hasher.verify("h$pw", "pw"))
    await asyncio.sleep(0.005)  # the first check is now running in its thread
    first.cancel()
    second = await hasher.verify("h$pw", "pw")

    assert second is True
    assert slow.peak == 1  # the second check did not start beside the abandoned one


async def test_a_concurrent_burst_gets_no_more_guesses_than_the_free_ones() -> None:
    slow = SlowArgon2()
    identity = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=Argon2idPasswordHasher(argon2=slow),  # the real adapter, its KDF stubbed
        failures=InMemoryFailedSignInLog(),
        clock=MovableClock(),
    )
    await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    )
    slow.calls = 0

    outcomes = await asyncio.gather(
        *(identity.authenticate(credentials("ada", WRONG), client=ATTACKER) for _ in range(50)),
        return_exceptions=True,
    )

    assert slow.calls == FREE_FAILURES  # the rest were refused before the password was checked
    assert sum(isinstance(o, InvalidCredentialsError) for o in outcomes) == FREE_FAILURES
    assert sum(isinstance(o, SignInThrottledError) for o in outcomes) == 50 - FREE_FAILURES


def test_one_hasher_serves_several_event_loops_under_contention() -> None:
    hasher = Argon2idPasswordHasher(argon2=SlowArgon2(), max_concurrent=1)

    async def contend() -> list[bool]:
        return await asyncio.gather(*(hasher.verify("h$pw", "pw") for _ in range(3)))

    assert asyncio.run(contend()) == [True] * 3
    assert asyncio.run(contend()) == [True] * 3  # a second loop gets its own slots
