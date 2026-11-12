"""Constants of ``exactdocs.identity``: every fixed value its modules share.

Each is ``Final`` and documented; see *Python conventions* in docs/architecture.md.
"""

import ipaddress
from datetime import timedelta
from typing import Final, Literal, TypedDict

# ---------------------------------------------------------------- models
MAX_USERNAME_LENGTH: Final[int] = 64
"""Longest username, in characters."""
MAX_TOKEN_NAME_LENGTH: Final[int] = 64
"""Longest name of an API token, in characters."""
VALUE_PREFIX: Final[str] = "exd_"
"""Recognizable, so secret scanners and humans can spot a leaked token."""
PREFIX_SHOWN: Final[int] = len(VALUE_PREFIX) + 4
"""The part of a token kept readable, to tell tokens apart."""
IDLE_TIMEOUT: Final[timedelta] = timedelta(days=7)
"""A session unused for this long ends."""
ABSOLUTE_TIMEOUT: Final[timedelta] = timedelta(days=30)
"""No session lives longer than this, however busy."""
FREE_FAILURES: Final[int] = 5
"""Sign-in throttle, counted apart per client address and per username: this many failures are free,
then each one more doubles the wait before the next attempt, from FIRST_WAIT up to LONGEST_WAIT.
Failures are forgotten once none came for FORGET_FAILURES_AFTER.
"""
FIRST_WAIT: Final[timedelta] = timedelta(seconds=5)
"""Wait imposed after the first sign-in failures beyond the free ones; it doubles with each failure.
"""
LONGEST_WAIT: Final[timedelta] = timedelta(minutes=15)
"""The wait between sign-in attempts never grows beyond this."""
FORGET_FAILURES_AFTER: Final[timedelta] = timedelta(hours=1)
"""Failed sign-ins older than this no longer count."""
REMEMBER_SIGN_INS_FOR: Final[timedelta] = timedelta(days=30)
"""An address that signed into a username is remembered this long after its last success: from
there, that username's own count does not apply (its address count still does), so failures
others cause for the username cannot lock its owner out of a machine they already use.
"""
_IPV6_NETWORK_BITS: Final[int] = 64
"""One IPv6 client usually holds a whole /64."""
_NAT64: Final[ipaddress.IPv6Network] = ipaddress.IPv6Network("64:ff9b::/96")
"""NAT64 (RFC 6052 well-known prefix) puts the IPv4 client in the last 32 bits, so every IPv4 client
reached through it would share one /64.
"""
_MAX_DOUBLINGS: Final[int] = 8
"""FIRST_WAIT * 2**8 is past LONGEST_WAIT; also keeps the arithmetic small."""

# ---------------------------------------------------------------- dtos
MIN_PASSWORD_LENGTH: Final[int] = 12
"""Shortest password an account may have, in characters."""
MAX_PASSWORD_LENGTH: Final[int] = 1024
"""Bounds the work a request can make the hasher do."""

# ---------------------------------------------------------------- use_cases
MAX_TOKENS_PER_ACCOUNT: Final[int] = 50
"""API tokens one account may hold at a time."""
TOKEN_BYTES: Final[int] = 32
"""256 bits of randomness."""
TOUCH_INTERVAL: Final[timedelta] = timedelta(hours=1)
"""Using a session only writes `last_used_at` when it is older than this: a read-only request should
not cost a database write each time, and it is tiny next to the 7-day idle timeout. Consequence:
idle expiry is accurate to this interval, not to the second.
"""

# ---------------------------------------------------------------- adapters.driven.argon2id
MAX_CONCURRENT_HASHES: Final[int] = 4
"""Password hashes computed at once; the rest wait, so sign-in attempts cannot exhaust memory."""

# ---------------------------------------------------------------- adapters.driven.memory
MAX_FAILED_SIGN_IN_KEYS: Final[int] = 10_000
"""Enough for every address and username a busy instance sees in an hour, and small in memory (~200
bytes a record): a flood of made-up usernames cannot grow the log without bound.
"""

# ---------------------------------------------------------------- adapters.driven.sqlite
MAX_CONCURRENT_SIGN_IN_TURNS: Final[int] = 4
"""Sign-in throttle transactions one process runs at once, well below the database pool's size: the
rest wait in the process without a connection, so a sign-in flood cannot take the pool from the
instance's other readers.
"""
SIGN_IN_TURN_TIMEOUT: Final[timedelta] = timedelta(seconds=5)
"""Longest a sign-in attempt waits for its turn on its keys, in the process and then again in the
database (PostgreSQL's ``lock_timeout``). An attempt that runs out is refused with this as its
``Retry-After``, uncounted (it fails closed); a right password's reset is then skipped.
"""
_LOCK_NOT_AVAILABLE: Final[str] = "55P03"
"""PostgreSQL's SQLSTATE for a lock wait that hit ``lock_timeout``."""
_SIGN_IN_LOCKS: Final[int] = 0x45584449
"""First key ("EXDI") of the two-key PostgreSQL advisory locks that make the sign-in throttle's
read-then-write atomic across processes; the second is ``hashtext`` of the throttle key."""

# ---------------------------------------------------------------- adapters.driving.http
SESSION_COOKIE: Final[str] = "exactdocs_session"
"""Name of the web session cookie."""
COOKIE_PATH: Final[str] = "/api"
"""Only `/api` needs the cookie (the UI itself is static), so the browser never sends it to `/mcp`.
"""
_THROTTLED: Final[dict[int | str, dict[str, object]]] = {
    429: {
        "description": (
            "Too many failed sign-ins (`rate_limited`); try again after `Retry-After` seconds."
        ),
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait before the next attempt.",
                "schema": {"type": "integer"},
            }
        },
    }
}
"""The sign-in throttle's answer, on the two routes that check a password. The body is the API's
shared error shape, referenced by name (it is defined by the app, not by this domain).
"""


class CookieAttributes(TypedDict):
    """The attributes of the session cookie, as ``set_cookie`` and ``delete_cookie`` take them."""

    path: str
    """Path the cookie is sent for."""
    httponly: bool
    """Whether scripts are kept from reading it."""
    samesite: Literal["lax"]
    """When a cross-site request carries it."""


COOKIE_ATTRS: Final[CookieAttributes] = {"path": COOKIE_PATH, "httponly": True, "samesite": "lax"}
"""Shared by ``set_cookie`` and ``delete_cookie``: a deletion only works if the attributes match."""
