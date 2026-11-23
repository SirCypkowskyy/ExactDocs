"""Constants of ``exactdocs.identity``: every fixed value its modules share.

Each is ``Final`` and documented; see *Python conventions* in docs/architecture.md.
"""

import ipaddress
from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Final, Literal, TypedDict

# ---------------------------------------------------------------- models
MAX_USERNAME_LENGTH: Final[int] = 64
"""Longest username, in characters."""
RESERVED_IN_USERNAME: Final[str] = "@address:"
"""Not allowed in the username of an account an operator creates: the sign-in throttle keeps an
address's remembered sign-ins under ``<username>@address:...``, so such a name would share keys
with another account's (see ``known_sign_ins_prefix``).
"""
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
SIGN_IN_ATTEMPT_LIFETIME: Final[timedelta] = timedelta(minutes=10)
"""An external sign-in must come back from the identity provider within this long after it
started; a later callback is refused, and the attempt's row is pruned."""
MAX_RETURN_TO_LENGTH: Final[int] = 2048
"""Longest path an external sign-in may return to; a longer one becomes ``/``."""
PROVIDER_NAME_PATTERN: Final[str] = r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"
"""A sign-in provider's name: lower-case letters, digits and inner hyphens, at most 32 characters.
It appears in URLs (``/api/v1/auth/<name>/...``) and in the ``<username>@<name>`` fallback."""

ACCESS_PROVIDER: Final[str] = "cloudflare-access"
"""The provider name an account created by Cloudflare Access is linked under (the users page shows
it, and ``<email>@cloudflare-access`` is its fallback username)."""
ACCESS_CERTS_PATH: Final[str] = "/cdn-cgi/access/certs"
"""Where a Cloudflare Access team publishes the keys its application tokens are signed with."""
ACCESS_LOGOUT_PATH: Final[str] = "/cdn-cgi/access/logout"
"""Where a browser signs out of Cloudflare Access (its session cookie for the team is cleared)."""

# ---------------------------------------------------------------- dtos
MIN_PASSWORD_LENGTH: Final[int] = 12
"""Shortest password an account may have, in characters."""
MAX_PASSWORD_LENGTH: Final[int] = 1024
"""Bounds the work a request can make the hasher do."""
MAX_TOKEN_NAME_INPUT: Final[int] = 4 * MAX_TOKEN_NAME_LENGTH
"""Longest token name a request may send: a cap on the raw input, checked before it is trimmed and
held to ``MAX_TOKEN_NAME_LENGTH``.
"""
USERNAME_DESCRIPTION: Final[str] = (
    f"Login name of the first admin: 1 to {MAX_USERNAME_LENGTH} characters once normalised "
    "(Unicode NFKC, trimmed, case-folded), no whitespace or control characters."
)
"""OpenAPI description of the first admin's username, built from the limit so it cannot drift."""
NEW_USERNAME_DESCRIPTION: Final[str] = (
    f"Login name of the new account: 1 to {MAX_USERNAME_LENGTH} characters once normalised "
    "(Unicode NFKC, trimmed, case-folded), no whitespace or control characters, and not "
    f"`{RESERVED_IN_USERNAME}`. Taken names are refused with `username_taken` (409)."
)
"""OpenAPI description of a new local account's username, built from the limits."""
NEW_PASSWORD_DESCRIPTION: Final[str] = f"{MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters."
"""OpenAPI description tail of a password being set, built from the limits so they cannot drift."""
TOKEN_NAME_DESCRIPTION: Final[str] = (
    f"Label of the new token, to tell it apart in the token list: 1 to {MAX_TOKEN_NAME_LENGTH} "
    f"characters once trimmed. `maxLength` ({MAX_TOKEN_NAME_INPUT}) only caps the raw input; "
    f"a name longer than {MAX_TOKEN_NAME_LENGTH} characters after trimming, or a blank one, is "
    "refused with `invalid_token_name` (422)."
)
"""OpenAPI description of a new token's name, built from the limits so they cannot drift."""
USER_SORT_FIELDS: Final[tuple[str, ...]] = ("created_at", "username", "role")
"""What the users list can be sorted by; `created_at` (oldest first) is the default."""
TOKEN_SORT_FIELDS: Final[tuple[str, ...]] = ("created_at", "name", "expires_at", "last_used_at")
"""What the token list can be sorted by; `-created_at` (newest first) is the default."""
GRANT_SORT_FIELDS: Final[tuple[str, ...]] = ("kind", "subject", "role")
"""What a library's grants can be sorted by; `kind` (users, then groups, by name) is the default."""
ACCESS_LOG_ACTION: Final[str] = "reads the access log of every library"
"""What only an instance operator does, for the 403 of the instance-wide access log."""

# ---------------------------------------------------------------- use_cases
SIGN_IN_SECRET_BYTES: Final[int] = 32
"""256 bits for each secret of an external sign-in attempt: the browser binding, ``state`` and
``nonce``."""
CODE_VERIFIER_BYTES: Final[int] = 48
"""The PKCE code verifier: 48 random bytes are 64 URL-safe characters (RFC 7636 allows 43 to 128).
"""
REVALIDATION_BATCH: Final[int] = 50
"""External identities one revalidation pass claims at a time; the pass claims again until none is
due."""
REVALIDATION_LEASE: Final[timedelta] = timedelta(minutes=10)
"""A claimed external identity is not due again for this long, so another process skips it while
this one checks it; a process that dies mid-check leaves it due again after the lease."""
MAX_TOKENS_PER_ACCOUNT: Final[int] = 50
"""API tokens one account may hold at a time."""
TOKEN_BYTES: Final[int] = 32
"""256 bits of randomness."""
TOUCH_INTERVAL: Final[timedelta] = timedelta(hours=1)
"""Using a session only writes `last_used_at` when it is older than this: a read-only request should
not cost a database write each time, and it is tiny next to the 7-day idle timeout. Consequence:
idle expiry is accurate to this interval, not to the second.
"""

ACCESS_LINK_REFRESH: Final[timedelta] = timedelta(hours=1)
"""A Cloudflare Access visit writes its account's link (``access_until``, the role from
``admin_emails``) only when the link was written longer ago than this, or the role changed: a
request should not cost a database write each time."""
ACCESS_LINK_LIFETIME: Final[timedelta] = timedelta(days=30)
"""An account created by Cloudflare Access keeps using its sessions and API tokens this long after
its owner last came through Access; Access itself keeps a removed person away from the origin."""

# ---------------------------------------------------------------- adapters.driven.argon2id
MAX_CONCURRENT_HASHES: Final[int] = 4
"""Password hashes computed at once; the rest wait, so sign-in attempts cannot exhaust memory."""

# ---------------------------------------------------------------- adapters.driven.memory
MAX_FAILED_SIGN_IN_KEYS: Final[int] = 10_000
"""Enough for every address and username a busy instance sees in an hour, and small in memory (~200
bytes a record): a flood of made-up usernames cannot grow the log without bound.
"""

# ---------------------------------------------------------------- adapters.driven.oidc
ID_TOKEN_LEEWAY: Final[timedelta] = timedelta(seconds=60)
"""Clock skew allowed on an ID token's ``exp``, ``iat`` and ``nbf``."""
DISCOVERY_TTL: Final[timedelta] = timedelta(hours=1)
"""How long one process keeps an issuer's discovery document before it fetches it again."""
JWKS_REFETCH_INTERVAL: Final[timedelta] = timedelta(minutes=1)
"""An ID token signed by a key the cached JWKS does not hold fetches the JWKS again (key rotation),
at most this often: a flood of tokens with made-up ``kid`` values cannot flood the issuer."""
ASYMMETRIC_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)
"""The ID token signatures accepted, when the issuer advertises them: never ``none``, never an
``HS*`` MAC (whose key would be the client secret, or worse, the issuer's public key)."""
SIGNING_KEY_TYPES: Final[Mapping[str, str]] = MappingProxyType(
    {"RS": "RSA", "PS": "RSA", "ES": "EC", "Ed": "OKP"}
)
"""The JWK key type each family of ``ASYMMETRIC_ALGORITHMS`` signs with, by the algorithm name's
first two letters (a token without a ``kid`` is tried with the keys of that type)."""
NUMERIC_DATE_CLAIMS: Final[tuple[str, ...]] = ("exp", "iat", "nbf")
"""The ID token's times: when present, each must be an integer (JSON booleans, fractions,
``NaN`` and infinities are refused)."""
OIDC_TIMEOUT: Final[float] = 10.0
"""Seconds one call to an identity provider may take (discovery, JWKS, token, userinfo)."""
MAX_PROVIDER_RESPONSE_BYTES: Final[int] = 1 * 2**20
"""An identity provider's answer above this size is refused unread to the end (checked while it
streams in, decoded)."""
_BAD_REQUEST: Final[int] = 400
"""The token endpoint's status for a refused grant (RFC 6749 section 5.2)."""
_UNAUTHORIZED: Final[int] = 401
"""The token endpoint's status for a refused client."""
_SUCCESS: Final[range] = range(200, 300)
"""Statuses of a usable answer."""

# ---------------------------------------------------------------- adapters.driven.cloudflare_access
ACCESS_ALGORITHMS: Final[tuple[str, ...]] = ("RS256",)
"""Cloudflare Access signs its application tokens with RS256 only; nothing else is accepted."""
ACCESS_TOKEN_LEEWAY: Final[timedelta] = timedelta(seconds=60)
"""Clock skew allowed on an Access token's ``exp``, ``iat`` and ``nbf``."""
ACCESS_CERTS_REFETCH_INTERVAL: Final[timedelta] = timedelta(minutes=1)
"""A token signed by a key the cached certs do not hold fetches them again (Cloudflare rotates its
keys), at most this often: made-up ``kid`` values cannot flood the team domain."""
ACCESS_TIMEOUT: Final[float] = 10.0
"""Seconds one fetch of the team's certs may take."""
MAX_ACCESS_CERTS_BYTES: Final[int] = 256 * 2**10
"""The team's certs above this size are refused unread to the end."""
MAX_ACCESS_TOKEN_LENGTH: Final[int] = 16 * 2**10
"""An assertion longer than this is refused without being parsed."""

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
FORGOTTEN_SIGN_INS_PER_TURN: Final[int] = 256
"""Remembered sign-ins ``forget_remembered`` deletes in one turn (one transaction). Each key is one
PostgreSQL advisory lock held to the end of the transaction, and the shared lock table only holds
``max_locks_per_transaction`` (default 64) times ``max_connections`` of them: one turn for every key
of a username with tens of thousands of remembered addresses ran out of it and failed every time.
"""
_LOCK_NOT_AVAILABLE: Final[str] = "55P03"
"""PostgreSQL's SQLSTATE for a lock wait that hit ``lock_timeout``."""
_SIGN_IN_LOCKS: Final[int] = 0x45584449
"""First key ("EXDI") of the two-key PostgreSQL advisory locks that make the sign-in throttle's
read-then-write atomic across processes; the second is ``hashtext`` of the throttle key."""

# ---------------------------------------------------------------- adapters.driving.http
SESSION_COOKIE: Final[str] = "exactdocs_session"
"""Name of the web session cookie."""
ACCESS_ASSERTION_HEADER: Final[str] = "cf-access-jwt-assertion"
"""The header Cloudflare Access adds to every request it lets through: the signed application token.
"""
ACCESS_COOKIE: Final[str] = "CF_Authorization"
"""The cookie Cloudflare Access sets in the browser, holding the same application token."""
SIGN_IN_COOKIE: Final[str] = "exactdocs_sign_in"
"""Name of the cookie that binds an external sign-in attempt to the browser that started it."""
SIGN_IN_COOKIE_PATH: Final[str] = "/api/v1/auth"
"""The binding cookie is only sent to the external sign-in routes (start and callback)."""
SIGN_IN_PAGE: Final[str] = "/sign-in"
"""The web UI's sign-in page: a refused external sign-in comes back here with ``?error=<code>``."""
COOKIE_PATH: Final[str] = "/api"
"""Only `/api` needs the cookie (the UI itself is static), so the browser never sends it to `/mcp`.
"""
USERS_DESCRIPTION: Final[str] = (
    "Operators only (`admin`): any other signed-in account is refused with `forbidden` (403). "
    "Needs a signed-in session; an API token is refused (401), so a leaked token cannot create "
    "accounts. There is no self-signup: accounts are created here, by `exactdocs user create` "
    "or, for the first admin, by the setup."
)
"""OpenAPI description shared by the ``/users`` routes."""
CREATE_TOKEN_DESCRIPTION: Final[str] = (
    "Create an API token for the signed-in account. The secret is in this response only. "
    f"An account holds at most {MAX_TOKENS_PER_ACCOUNT} tokens; one more is refused with "
    "`too_many_tokens` (409) until one is revoked."
)
"""OpenAPI description of ``POST /tokens``, built from the token cap so it cannot drift."""
LOGIN_FOR_TOKEN_DESCRIPTION: Final[str] = (
    "Exchange a username and password for a new API token (what `exactdocs login` does). "
    f"An account holds at most {MAX_TOKENS_PER_ACCOUNT} tokens; one more is refused with "
    "`too_many_tokens` (409) until one is revoked."
)
"""OpenAPI description of ``POST /tokens/login``, built from the token cap so it cannot drift."""
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

GITHUB_MAX_TEAM_PAGES: Final[int] = 100
"""Maximum GitHub team pages per check; reaching an unfinished bound fails closed."""

OAUTH_CLIENT_BASIC: Final[str] = "client_secret_basic"
"""OAuth client authentication using the HTTP Basic header."""

OAUTH_CLIENT_POST: Final[str] = "client_secret_post"
"""OAuth client authentication using token form fields (GitHub OAuth Apps)."""

TEXT_SCALES: Final[tuple[int, ...]] = (90, 100, 110, 125, 150)
"""The text sizes the interface offers, in percent of its default size (#487); the same as
``models.TextScale``, which types them."""

ACCOUNTS_PER_QUERY: Final[int] = 500
"""How many account IDs one ``IN (...)`` list holds when the leaderboard asks who opted in
(#510); longer lists are asked in turns, within every database's limit on bound parameters."""
