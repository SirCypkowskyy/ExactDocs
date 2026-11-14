"""Constants of ``exactdocs.bootstrap``: every fixed value its modules share.

Each is ``Final`` and documented; see *Python conventions* in docs/architecture.md.
"""

import re
import sqlite3
from pathlib import Path
from typing import Final

from exactdocs.catalog.models import ManifestState
from exactdocs.retrieval.models import ManifestStatus
from exactdocs_kernel import (
    BusyError,
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthenticatedError,
    ValidationError,
)

# ---------------------------------------------------------------- cli
DEFAULT_TOKEN_DAYS: Final[int] = 90
"""Lifetime of an API token created on the command line when ``--days`` is not given."""
LOCAL_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "serve",
        "reindex",
        "backup",
        "restore",
        "admin create",
        "admin reset-password",
        "user create",
        "user disable",
        "user enable",
        "user reset-password",
        "ai check",
        "ai estimate",
        "models pull",
    }
)
"""CLI commands that work on the local data directory instead of calling a server."""

# ---------------------------------------------------------------- cli_library
POLL_SECONDS: Final[float] = 1.0
"""How often ``--wait`` asks the server how a job is doing."""
SYNC_FAILED_STATUS: Final[int] = 422
"""HTTP status of a sync whose remote could not be read (``repo_unreachable``, ``auth_failed``...).
"""
CONFLICT_STATUS: Final[int] = 409
"""HTTP status of a sync that could queue nothing, e.g. while an import is running."""
TAG_MOVED: Final[str] = "tag_moved"
"""A sync's code for a tag that names another commit now."""
PAGE: Final[int] = 200
"""The largest page the API serves."""
MAX_REFS_SHOWN: Final[int] = 5
"""Refs listed per library in the CLI's tables; the rest are counted."""
WAIT_SECONDS: Final[float] = 600.0
"""How long --wait follows a job before it leaves it to the server."""
POLL_RETRIES: Final[int] = 3
"""Consecutive failed polls (timeouts, 5xx) before the wait gives up."""
MAX_SECRET_BYTES: Final[int] = 64 * 1024
"""A private key is about 3 KB."""
MAX_SOURCES_BYTES: Final[int] = 1024 * 1024
"""The largest sources file the CLI reads; a few hundred libraries take far less."""
EXIT_INTERRUPTED: Final[int] = 130
"""Exit status after Ctrl+C (128 + SIGINT), as shells report it."""
LIBRARY_ID: Final[re.Pattern[str]] = re.compile(
    r"^/[^/]+/[^/]"
)  # ctx7's check: /owner/repo, optionally /ref or @ref
"""Ctx7's check: /owner/repo, optionally /ref or @ref."""

# ---------------------------------------------------------------- client
URL_VARIABLE: Final[str] = "EXACTDOCS_URL"
"""Environment variable with the server's URL for the CLI client."""
TOKEN_VARIABLE: Final[str] = "EXACTDOCS_TOKEN"  # ruff: ignore[hardcoded-password-string] (a name)
"""Environment variable with the API token for the CLI client."""
CONFIG_FILE_VARIABLE: Final[str] = "EXACTDOCS_CLIENT_CONFIG"
"""Environment variable that points the CLI client at another credentials file (it was
``EXACTDOCS_CONFIG_FILE`` before that became the server's TOML configuration file, #241).
"""
DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}
"""The port each URL scheme implies, so ``https://x`` and ``https://x:443`` are one server."""
MAX_TOKEN_NAME_LENGTH: Final[int] = (
    64  # the server's limit, so a long hostname is cut instead of refused
)
"""The server's limit, so a long hostname is cut instead of refused."""
TIMEOUT_SECONDS: Final[float] = 15.0
"""How long the CLI client waits for one HTTP answer."""
FRIENDLY: Final[dict[str, str]] = {
    "invalid_credentials": "wrong username or password",
    "unauthenticated": "the server did not accept the token (invalid, expired or revoked); "
    "run `exactdocs login` again",
    "setup_required": "that instance has no admin account yet; "
    "run `exactdocs admin create` on the server first",
    "too_many_tokens": "this account holds the most API tokens it may; "
    "revoke one in the web UI or log in with --token",
    "not_found": "the server has no such endpoint; is that URL an ExactDocs instance "
    "of a compatible version?",
    "rate_limited": "too many failed sign-ins from here or for this username; "
    "wait a little and try again",
    "preview_busy": "the server is running as many previews as it allows; try again",
}
"""What the API's `error` codes mean to a person at a terminal. Anything else shows the server's own
`detail`, which is already a sentence.
"""

# ---------------------------------------------------------------- container
WORK_DIR: Final[str] = "work"
"""Under the data dir: one folder per running git fetch."""
PROCESS_WORK_PREFIX: Final[str] = "process-"
"""On PostgreSQL each process keeps its fetch folders under `work/process-*` (``workdirs.py``)."""
CLAIM_TRIES: Final[int] = 100
"""How often a process tries to create and lock its work folder while sweeps race it."""
CLAIM_PAUSE_SECONDS: Final[float] = 0.01
"""The pause between two tries."""
PROCESS_WORK_OWNER: Final[str] = ".owner"
"""The file in a process folder its process keeps locked (``flock``) for as long as it lives."""
KNOWN_HOSTS_FILE: Final[str] = "known_hosts"
"""Under the data dir: SSH host keys, the big three pre-seeded."""
SHUTDOWN_GRACE_SECONDS: Final[int] = 30
"""On PostgreSQL, how long `serve` lets open connections finish when it stops (uvicorn's
`timeout_graceful_shutdown`), so a process that lost its executor slot is gone soon."""
EXECUTOR_PREFIX: Final[str] = "exactdocs-"
"""On PostgreSQL each server process runs DBOS as ``exactdocs-<slot>`` (``executors.py``)."""
EXECUTOR_LOCKS: Final[int] = 0x45584443
"""First key of the two-key PostgreSQL advisory locks that hold the executor slots (the second is
the slot); two-key locks never collide with the one-key locks of ``WRITE_LOCK`` and the others."""
SLOT_KEEPALIVES: Final[dict[str, int]] = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "tcp_user_timeout": 10_000,
}
"""libpq TCP keepalives of the connection that holds a process's executor slot: it idles for the
process's whole life, and a NAT or load balancer would otherwise drop it unnoticed. The user
timeout (ms) ends a check whose packets a vanished host never acknowledges."""
MAX_EXECUTORS: Final[int] = 1024
"""Slots tried before a process gives up: more server processes on one database than that is a
mistake, not a deployment."""
JOBS_FILE: Final[str] = (
    "jobs.sqlite"  # under the data dir: DBOS's workflows, the durable steps of jobs
)
"""Under the data dir: DBOS's workflows, the durable steps of jobs."""

# ---------------------------------------------------------------- backup
BACKUP_FORMAT: Final[int] = 1
"""Layout of a backup archive; a restore refuses any other (a newer ExactDocs made it)."""
MANIFEST_MEMBER: Final[str] = "manifest.json"
"""Archive member describing the backup: format, version, schema revision, file checksums."""
DATABASE_MEMBER: Final[str] = "exactdocs.db"
"""Archive member holding the database snapshot, wherever the database file lives."""
PRIVATE_FILE_MODE: Final[int] = 0o600
"""Mode of an archive and of every restored file: they hold account hashes and tokens' hashes."""
COPY_CHUNK_BYTES: Final[int] = 1024 * 1024
"""How much of a file is hashed or copied at a time."""
MAX_MANIFEST_BYTES: Final[int] = 64 * 1024
"""A manifest is a few hundred bytes; a larger one is not read (it would be loaded whole)."""
RESTORE_FREE_MARGIN_BYTES: Final[int] = 64 * 1024 * 1024
"""Room a restore leaves free on each filesystem it writes to, beyond the files themselves."""
STALE_STAGING_SECONDS: Final[float] = 24 * 3600
"""A backup's staging folder this old was left by a backup that was killed: it is removed."""
STAGING_PREFIX: Final[str] = ".exactdocs-backup-"
"""Name prefix of a backup's staging folder (next to the archive, or in the data dir for `-`)."""

# ---------------------------------------------------------------- database
MIGRATIONS: Final[Path] = Path(__file__).parent / "migrations"
"""Folder of the Alembic revisions that build the database."""
BUSY_TIMEOUT_MS: Final[int] = 5000
"""How long SQLite waits for a lock held by another connection before it gives up."""
SPEND_LEDGER_TABLES: Final[frozenset[str]] = frozenset(
    {
        "retrieval_ai_spend",
        "retrieval_ai_spend_replays",
    }
)
"""The only tables a ``serve --stdio`` process may write: the AI spend ledger and its replay
tokens (#274). Its ledger connection's authorizer refuses a write to any other on SQLite."""
SQLITE_READ_ACTIONS: Final[frozenset[int]] = frozenset(
    {
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_SAVEPOINT,
    }
)
"""Authorizer actions the spend ledger's SQLite connection may take anywhere: they write nothing."""
SQLITE_WRITE_ACTIONS: Final[frozenset[int]] = frozenset(
    {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
    }
)
"""Authorizer actions it may take on ``SPEND_LEDGER_TABLES`` only."""
SQLITE_READ_PRAGMAS: Final[frozenset[str]] = frozenset(
    {
        "busy_timeout",
        "data_version",
        "foreign_keys",
        "journal_mode",
        "query_only",
        "read_uncommitted",
        "schema_version",
        "user_version",
    }
)
"""PRAGMAs the spend ledger's SQLite connection may read (with no argument, so nothing is set).
Any other is refused, including ``incremental_vacuum`` and ``wal_checkpoint``, which change the
file even with no argument. The ledger itself issues none: ``busy_timeout`` is set before the
authorizer is installed."""
MIN_SQLITE: Final[tuple[int, ...]] = (3, 35)
"""Search uses `WITH ... AS MATERIALIZED`"""
POSTGRES_DRIVER: Final[str] = "postgresql+psycopg"
"""The one PostgreSQL driver: psycopg 3, async. DBOS already depends on it."""
POSTGRES_DRIVERS: Final[frozenset[str]] = frozenset({"postgresql", POSTGRES_DRIVER})
"""How `EXACTDOCS_DATABASE_URL` may name PostgreSQL; both mean psycopg 3."""
SUPABASE_HOSTS: Final[tuple[str, ...]] = (".supabase.co", ".supabase.com")
"""Host suffixes of Supabase's databases and poolers (``db.<ref>.supabase.co``,
``aws-0-<region>.pooler.supabase.com``)."""
SUPABASE_TRANSACTION_PORT: Final[int] = 6543
"""The port of Supabase's poolers in transaction mode (Supavisor's and the dedicated PgBouncer's),
which ExactDocs refuses: the session pooler and direct connections listen on 5432."""
SESSION_PROBE: Final[str] = "exactdocs.session_probe"
"""The session-level setting the start-up probe writes in one transaction and reads back in the
next (#279): lost in between, the connection is a transaction-mode pooler's, not a session."""
SECURE_SSLMODES: Final[frozenset[str]] = frozenset({"require", "verify-ca", "verify-full"})
"""``sslmode`` values that never fall back to an unencrypted connection."""
MIN_POSTGRES: Final[int] = 140000
"""`server_version_num` of PostgreSQL 14, the oldest supported (generated columns, `FORCE`)."""
WRITE_LOCK: Final[int] = 0x45584443_00000001
"""PostgreSQL advisory lock taken by a writing transaction that asks for ``begin_immediate``:
those transactions take turns, as SQLite's ``BEGIN IMMEDIATE`` makes them."""
WRITE_LOCK_TIMEOUT_MS: Final[int] = 30_000
"""How long a ``begin_immediate`` transaction on PostgreSQL waits for its turn (``WRITE_LOCK``)
before it fails with ``WriteTurnTimeoutError``; SQLite's own wait is ``BUSY_TIMEOUT_MS``."""
LOCK_NOT_AVAILABLE: Final[str] = "55P03"
"""PostgreSQL's SQLSTATE for a lock wait that hit ``lock_timeout``."""
MIGRATION_LOCK: Final[int] = 0x45584443_00000002
"""PostgreSQL advisory lock held while the schema is migrated: processes starting together
migrate one after the other."""
MIGRATION_TURN_SUFFIX: Final[str] = "-migration.lock"
"""Suffix of the file next to a SQLite database (``exactdocs.db-migration.lock``) that a process
keeps locked (``flock``) while it migrates: processes starting together migrate one after the
other, however long each takes (#320). It stays, naming only the current holder (pid and host,
for the waiters' log line); the kernel drops the lock of a process that dies."""
MIGRATION_TURN_POLL_SECONDS: Final[float] = 0.05
"""How often a SQLite process waiting for another one's migration tries the lock again."""
MIGRATION_TURN_NOTICE_SECONDS: Final[float] = 5.0
"""After this long waiting for another process's migration, the wait is first logged."""
MIGRATION_TURN_REPEAT_SECONDS: Final[float] = 60.0
"""While the wait for another process's migration goes on, it is logged again this often, so a
start stuck behind a hung migration stays visible in the logs."""
COLLATED_PREFIXES: Final[tuple[str, ...]] = ("catalog_", "identity_", "ingestion_", "retrieval_")
"""Tables whose text columns get the "C" collation on PostgreSQL, so text compares and sorts by
code point, as SQLite's BINARY collation does, whatever the database's locale."""

# ---------------------------------------------------------------- http
WEB_DIST: Final[Path] = Path(__file__).parent.parent / "_web"
"""Built web UI, copied into the package by CI / the Docker build (see web/README.md)."""
MCP_PATH: Final[str] = "/mcp"
"""Where the HTTP app serves MCP."""
_UNSAFE_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})
"""Methods that change state, so a browser request with them must come from a trusted origin."""

# ---------------------------------------------------------------- probes
LIVENESS_PATH: Final[str] = "/healthz"
"""Liveness probe: 200 while the process answers, whatever the database does."""
HEALTH_ALIAS_PATH: Final[str] = "/api/health"
"""The liveness probe's older path, kept for existing clients."""
READINESS_PATH: Final[str] = "/readyz"
"""Readiness probe: 200 when the database answers, 503 otherwise."""
PROBE_PATHS: Final[frozenset[str]] = frozenset({LIVENESS_PATH, HEALTH_ALIAS_PATH, READINESS_PATH})
"""Paths orchestrators poll: never traced or metered."""
PROBE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD"})
"""Methods the probes answer; only these skip the Host check, and only on ``PROBE_PATHS``."""
READINESS_TIMEOUT_SECONDS: Final[float] = 2.0
"""How long readiness waits for the database before it reports it unreachable."""
READINESS_UNREACHABLE: Final[str] = "the database is unreachable"
"""Readiness' reason when the database does not answer, or not within its budget."""
PROBE_SETTLE_SECONDS: Final[float] = 2.0
"""How long a stopping app waits for a probe's database check before it cancels it, and again
after: at most twice this in all, then the check and its connection are abandoned."""
LIVENESS_DATABASE_SECONDS: Final[float] = 0.3
"""How long liveness waits for the database's details: it must answer fast whatever the database
does (Kubernetes' default probe timeout is 1 s), so after this it answers without them.
"""
UNTRUSTED_HOST: Final[str] = "untrusted_host"
"""Request state key set on a probe request whose ``Host`` is not trusted: it gets no details."""
HOST_TRUSTED: Final[str] = "exactdocs.host_trusted"
"""ASGI scope key the Host check's probe sets when Starlette's own check accepts the Host."""

# ---------------------------------------------------------------- mcp
RESOURCE_NOT_FOUND: Final[int] = -32002
"""JSON-RPC error code MCP uses for a resource that does not exist."""

# ---------------------------------------------------------------- mcp_config
CLIENTS: Final[tuple[str, ...]] = ("claude", "claude-desktop", "cursor", "vscode", "codex")
"""MCP clients ``exactdocs mcp-config`` writes a configuration for."""
SKILL_PATH: Final[Path] = Path(__file__).parent / "skill" / "SKILL.md"
"""The agent skill the server ships and serves as an MCP resource."""
NAME: Final[str] = "exactdocs"
"""Name of the server in MCP client configurations."""
STDIO: Final[dict[str, str | list[str]]] = {
    "command": "uvx",
    "args": ["exactdocs", "serve", "--stdio"],
}
"""How an MCP client starts the server over stdio."""
PLACEHOLDER: Final[str] = "<your-exactdocs-token>"
"""For clients that cannot expand environment variables."""

# ---------------------------------------------------------------- rest
V1_PREFIX: Final[str] = "/api/v1"
"""Path prefix of version 1 of the REST API."""
OPENAPI_PATH: Final[str] = f"{V1_PREFIX}/openapi.json"
"""Where the OpenAPI document of ``/api/v1`` is served."""
_STATUS_BY_ERROR: Final[dict[type[DomainError], int]] = {
    UnauthenticatedError: 401,
    ForbiddenError: 403,
    NotFoundError: 404,
    ConflictError: 409,
    BusyError: 429,
    ValidationError: 422,
    RateLimitedError: 429,
}
"""HTTP status of each kernel error class; any other domain error is a 400."""
SETUP_EXEMPT: Final[frozenset[tuple[str, ...]]] = frozenset(
    {("POST", f"{V1_PREFIX}/setup"), ("GET", f"{V1_PREFIX}/session"), ("GET", OPENAPI_PATH)}
)
"""(method, path) pairs that stay reachable before the first admin exists: `POST /setup` is the way
out of that state, and `GET /session` is how the UI learns that it is in it.
"""

# ---------------------------------------------------------------- secret_box
KEY_FILE: Final[str] = "secret.key"
"""File in the data directory that holds the generated secret key."""
MIN_SECRET_KEY_LENGTH: Final[int] = 32
"""Shortest ``EXACTDOCS_SECRET_KEY`` accepted, in characters."""
CREDENTIALS_KEY_PURPOSE: Final[bytes] = b"exactdocs credentials v1"
"""HKDF context (``purpose``) of the key that seals ingestion's repository credentials.

Each use of the secret box has its own context, so its key serves nothing else; never change this
one: every stored credential is sealed with the key derived from it.
"""
AI_KEYS_PURPOSE: Final[bytes] = b"exactdocs ai provider keys v1"
"""HKDF context (``purpose``) of the key that seals the AI provider keys stored over the REST API.

Its own context: a provider key never opens with the credentials' key, nor the reverse. Never
change it: every stored provider key is sealed with the key derived from it.
"""
SIGN_IN_TOKENS_PURPOSE: Final[bytes] = b"exactdocs sign-in tokens v1"
"""HKDF context (``purpose``) of the key that seals the refresh tokens of external identities.

Its own context: a refresh token never opens with another use's key, nor the reverse. Never change
it: every stored refresh token is sealed with the key derived from it (changing it ends the access
of every external account at its next revalidation, until it signs in again).
"""
SIGN_IN_STOP_SECONDS: Final[float] = 5.0
"""How long stopping the server waits for a revalidation pass to stop once cancelled."""
WEBHOOK_SECRETS_PURPOSE: Final[bytes] = b"exactdocs webhook secrets v1"
"""HKDF context (``purpose``) of the key that seals the libraries' push webhook secrets.

Its own context: a webhook secret never opens with the credentials' key, nor the reverse. Never
change it: every stored webhook secret is sealed with the key derived from it.
"""
AGENT_CACHE_PURPOSE: Final[bytes] = b"exactdocs agentic cache v1"
"""HKDF context of the key of the HMACs that hash the questions in the agentic answer cache.

Its own context, as HyDE's: changing it (or the secret key) only makes every cached answer a miss.
"""
HYDE_CACHE_PURPOSE: Final[bytes] = b"exactdocs hyde cache v1"
"""HKDF context (``purpose``) of the key of the HMAC that hashes the queries in HyDE's cache.

Its own context: the hashes cannot be checked against a list of likely queries without the
instance's secret key. Changing it (or the secret key) only makes every cached answer a miss.
"""
_OWNER_ONLY: Final[int] = 0o600
"""File mode of the secret key file: readable by its owner only."""

# ---------------------------------------------------------------- settings
LOCAL_HOSTS: Final[tuple[str, ...]] = ("localhost", "127.0.0.1", "::1")
"""Hosts every instance accepts; anything else must be listed in EXACTDOCS_ALLOWED_HOSTS."""

# ---------------------------------------------------------------- exit codes of the CLI
EXIT_FAILED: Final[int] = 1
"""The command failed (the server answered with an error, or a job failed)."""
EXIT_USAGE: Final[int] = 2
"""The command line or a value in it is invalid."""
EXIT_NOT_FOUND: Final[int] = 3
"""The library, version or job does not exist."""
EXIT_CONFLICT: Final[int] = 4
"""The request conflicts with the server's state (e.g. an import is already running)."""
EXIT_AUTH: Final[int] = 5
"""The server refused the credentials, or none are configured."""
EXIT_IMPORT: Final[int] = 6
"""The import the command waited for did not complete."""

# ---------------------------------------------------------------- bridges
STATUSES: Final[dict[ManifestState, ManifestStatus]] = {
    ManifestState.PENDING: ManifestStatus.PENDING,
    ManifestState.ACTIVE: ManifestStatus.ACTIVE,
    ManifestState.SUPERSEDED: ManifestStatus.SUPERSEDED,
}
"""Retrieval's status of each catalog manifest state.

Explicit, so a state the catalog adds later cannot crash retrieval: it maps to ``OTHER`` (kept).
"""

# ---------------------------------------------------------------- rest
ERROR_DESCRIPTIONS: Final[dict[int, str]] = {
    400: "The request cannot be processed (error code in `error`).",
    401: "The caller is not signed in, or the credentials are wrong (`unauthenticated`).",
    403: (
        "Refused: the instance has no admin account yet (`setup_required`), or the caller "
        "may not do this (`forbidden`)."
    ),
    404: "The thing does not exist or is not visible to the caller.",
    409: "The request conflicts with the current state.",
    422: "A field is invalid (`fields` names them) or a business rule is violated.",
}
"""The error answers every ``/api/v1`` operation documents, by status."""
DOCSTRING_SECTIONS: Final[frozenset[str]] = frozenset(
    {"Args:", "Arguments:", "Returns:", "Return:", "Yields:", "Raises:"}
)
"""Google docstring sections that end an operation's OpenAPI description."""

# ---------------------------------------------------------------- telemetry, otlp
SERVICE_NAME: Final[str] = "exactdocs"
"""``service.name`` of the exported telemetry, unless ``OTEL_SERVICE_NAME`` names another."""
OTLP_ENDPOINT_VARIABLE: Final[str] = "OTEL_EXPORTER_OTLP_ENDPOINT"
"""The collector for every signal; ``OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT`` names one per signal.
With neither set, that signal is not exported (there is no default collector).
"""
EXPORTER_VARIABLE: Final[str] = "OTEL_{}_EXPORTER"
"""``OTEL_TRACES_EXPORTER`` / ``OTEL_METRICS_EXPORTER``: ``none`` turns that signal off."""
QUERY_TEXT_PARAMETERS: Final[frozenset[str]] = frozenset({"q", "query", "libraryName", "url"})
"""URL query parameters whose value is search input (or a repository URL that may carry a token):
redacted from request spans unless the operator opted in to query text.
"""
PROMPT_SPAN_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        # pydantic-ai's older attribute names (instrumentation version 2) and its agent run's
        # message history and output: the same text under other keys.
        "tool_arguments",
        "tool_response",
        "pydantic_ai.all_messages",
        "final_result",
    }
)
"""What a model was sent and answered, and what an agent's tools were called with and returned
(pydantic-ai's instrumentation): always left out, even with the query text opted in.
``include_content=False`` is the first guard, this the second (docs/decisions/ai-retrieval.md,
*Telemetry*)."""
GEN_AI_PREFIX: Final[str] = "gen_ai."
"""OpenTelemetry's generative AI attributes: any ``gen_ai.<...>.messages`` one is a prompt too."""
MESSAGES_SUFFIX: Final[str] = ".messages"
"""The end of a ``gen_ai`` attribute that holds messages (``gen_ai.input.messages``)."""
SCRUBBED_SPAN_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"enduser.id", "enduser.scope", *PROMPT_SPAN_ATTRIBUTES}
)
"""Who called (FastMCP puts the token's client ID and scopes on every MCP span), left out unless
the operator opted in, like the query text they would tie to a person; and the prompts, always.
"""
SCRUBBED_EXCEPTION_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"exception.message", "exception.stacktrace"}
)
"""Left out of exception events unless the operator opted in: they can quote the input."""
REDACTED: Final[str] = "REDACTED"
"""What a redacted URL query value is replaced with."""
URL_QUERY_ATTRIBUTE: Final[str] = "url.query"
"""The request span attribute with the URL's query string (OpenTelemetry semantic conventions)."""
SDK_MODULE: Final[str] = "exactdocs.bootstrap.otel_sdk"
"""The module that sets up the OpenTelemetry SDK, loaded only when telemetry or metrics are on."""
JOB_TRACER_NAME: Final[str] = "exactdocs.ingestion"
"""OpenTelemetry instrumentation scope of the job spans and metrics."""
METRICS_PATH: Final[str] = "/metrics"
"""Where Prometheus scrapes the metrics, with ``EXACTDOCS_METRICS`` on (404 otherwise)."""
UNTRACED_PATHS: Final[frozenset[str]] = PROBE_PATHS | {METRICS_PATH}
"""Requests that get no span and count in no request metric: the probes and the scrapes, which
poll on a timer and would drown what users do.
"""
JOB_DURATION_METRIC: Final[str] = "exactdocs.job.duration"
"""Histogram of how long each job ran, by kind (``import``, ``refresh``: a branch sync...)."""
JOB_KIND_ATTRIBUTE: Final[str] = "exactdocs.job.kind"
"""The attribute naming a job's kind on its span and its metric."""
ERROR_TYPE_ATTRIBUTE: Final[str] = "error.type"
"""The metric attribute naming the exception class of a failed job (semantic conventions)."""
JOB_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800, 3600,
)  # fmt: skip
"""Bucket bounds of the job duration histogram, in seconds: from a no-op sync to a large import."""


# ---------------------------------------------------------------- settings / ai_models (#241)
SETTINGS_FILE_VARIABLE: Final[str] = "EXACTDOCS_CONFIG_FILE"
"""Names the server's optional TOML configuration file; the environment wins over it. The CLI
client's credentials file is another one (``CONFIG_FILE_VARIABLE``).
"""
SECRETS_REFUSED_IN_FILE: Final[frozenset[str]] = frozenset(
    {"secret_key", "secret_key_previous", "metrics_token"}
)
"""Top-level settings the configuration file may not hold: secrets come from the environment."""
DEFAULT_BASE_URLS: Final[dict[str, str]] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com/",
    "deepseek": "https://api.deepseek.com",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "github": "https://models.github.ai/inference",  # pydantic-ai's provider is deprecated
    "vercel": "https://ai-gateway.vercel.sh/v1",
    "moonshotai": "https://api.moonshot.ai/v1",
    "heroku": "https://us.inference.heroku.com/v1",
    "nebius": "https://api.studio.nebius.com/v1",
    "ovhcloud": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
    "sambanova": "https://api.sambanova.ai/v1",
    "alibaba": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}
"""The endpoint of each hosted kind, passed explicitly (pydantic-ai's own defaults, 2.60.0) so no
SDK ever falls back to a ``*_BASE_URL`` environment variable.
"""
AZURE_OPENAI_HOST: Final[re.Pattern[str]] = re.compile(r"[a-z0-9-]+\.openai\.azure\.com")
"""An Azure OpenAI endpoint derived from ``resource``."""
FOUNDRY_HOST: Final[re.Pattern[str]] = re.compile(r"[a-z0-9-]+\.services\.ai\.azure\.com")
"""An Azure AI Foundry endpoint derived from ``resource``."""
BEDROCK_HOST: Final[re.Pattern[str]] = re.compile(r"bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com")
"""An Amazon Bedrock runtime endpoint derived from ``location`` (the AWS region)."""
VERTEX_HOST: Final[re.Pattern[str]] = re.compile(
    r"(aiplatform|[a-z0-9-]+-aiplatform|aiplatform\.(us|eu)\.rep)\.googleapis\.com"
)
"""A Vertex AI endpoint: global, regional (``<location>-aiplatform``) or multi-region."""
RERANK_DIALECTS: Final[dict[str, str]] = {
    "openai-compatible": "cohere",
    "vllm": "cohere",
    "litellm": "cohere",
    "tei": "tei",
}
"""The rerank dialect (``RerankDialect``) of each provider kind that has a rerank API: the
Cohere-compatible ``/rerank`` (Cohere, Jina, Voyage and Azure AI Foundry through
``openai-compatible``), or TEI's."""
AI_SDK_MODULE: Final[str] = "exactdocs.bootstrap.ai_sdk"
"""The module that imports pydantic-ai and the provider SDKs: loaded only once a role is used."""
NO_KEY: Final[str] = "unused"
"""The key sent by a profile without one, instead of letting an SDK read ``*_API_KEY``."""
AZURE_SCOPE: Final[str] = "https://cognitiveservices.azure.com/.default"
"""The Entra ID scope of Azure OpenAI and Azure AI Foundry tokens."""
GOOGLE_SCOPE: Final[str] = "https://www.googleapis.com/auth/cloud-platform"
"""The scope of Google service-account and ADC credentials (Vertex AI)."""
AMBIENT_HEADERS: Final[frozenset[str]] = frozenset({"openai-organization", "openai-project"})
"""Headers the OpenAI SDK fills from ``OPENAI_ORG_ID`` / ``OPENAI_PROJECT_ID``: dropped from every
call unless the profile's own headers set them.
"""
SDK_HEADER_VARIABLES: Final[tuple[str, ...]] = ("OPENAI_CUSTOM_HEADERS", "ANTHROPIC_CUSTOM_HEADERS")
"""Variables the OpenAI and Anthropic SDKs merge into every request after the key: removed from
the process before any SDK client is built.
"""
CHECK_PROMPT: Final[str] = "Reply with the single word OK."
"""What ``exactdocs ai check`` asks a chat model."""
CHECK_MAX_TOKENS: Final[int] = 16
"""Output cap of a chat model check."""
CHECK_TEXT: Final[str] = "ExactDocs connectivity check"
"""What a check embeds, and reranks against itself."""
WINDOW_RESET_GRACE_SECONDS: Final[float] = 5.0
"""Embedding is queued again this long after each UTC midnight, once the spend windows reset."""

REQUEUE_JITTER_SECONDS: Final[float] = 300.0
"""At most this many seconds more, at random, before the midnight re-queue: processes and
instances sharing a provider do not all wake together."""
UPKEEP_STOP_SECONDS: Final[float] = 5.0
"""How long a stopping server waits for its cancelled nightly upkeep (embedding queueing and
cache pruning) to end; then it logs a warning and cancels it again (#308). Well under the 10 s
``docker stop`` grace, so the job worker's stop and the engine's dispose still fit after it."""
UPKEEP_RECANCEL_SECONDS: Final[float] = 1.0
"""How long a stopping server waits for its upkeep after cancelling it a second time; then it
stops without it (#308)."""
REQUEUE_LOCK_KEY: Final[str] = "exactdocs:embedding:requeue"
"""The PostgreSQL advisory lock whose holder runs the midnight re-queue of embedding."""
REQUEUE_TRY_LOCK: Final[str] = "SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"
"""Takes the re-queue's session lock if no other process holds it, without waiting."""
REQUEUE_UNLOCK: Final[str] = "SELECT pg_advisory_unlock(hashtextextended(:key, 0))"
"""Releases one hold of the re-queue's session lock."""

# ---------------------------------------------------------------- local models (#245)
LOCAL_SDK_MODULE: Final[str] = "exactdocs.bootstrap.local_sdk"
"""The module that imports fastembed (the ``[local]`` extra): loaded only once a local model is
used."""
LOCAL_EXTRA: Final[str] = (
    "install exactdocs[local] (uvx --from 'exactdocs[local]' exactdocs, or the -local image)"
)
"""What a ``local`` profile needs when fastembed or ONNX Runtime is not installed."""
LOCAL_MODULES: Final[tuple[str, ...]] = ("fastembed", "onnxruntime")
"""The modules a ``local`` profile's models import."""
DEFAULT_LOCAL_EMBEDDING: Final[str] = "BAAI/bge-small-en-v1.5"
"""The default local embedding model (384 dimensions, 67 MB quantized ONNX)."""
DEFAULT_LOCAL_RERANKER: Final[str] = "Xenova/ms-marco-MiniLM-L-6-v2"
"""The default local cross-encoder (91 MB)."""
MODELS_SUBDIR: Final[str] = "models"
"""Where models live in the data directory unless ``EXACTDOCS_MODELS_DIR`` says otherwise."""
MODEL_MARKER: Final[str] = "exactdocs-model.json"
"""Written last by ``exactdocs models pull`` in a model's folder: the model is complete."""
MODEL_NAME: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}(/[A-Za-z0-9][A-Za-z0-9._-]{0,95})?"
)
"""A model name as fastembed lists it (``<org>/<name>``): also its folder in the models
directory, so no ``..``, no absolute path."""
LOCAL_DOCUMENT_WORKERS: Final[int] = 1
"""Embedding batches (the background jobs) that run at once: one, on a pool of its own."""
LOCAL_QUERY_WORKERS: Final[int] = 2
"""Query embeddings and reranks that run at once, on a pool of their own: a search never waits
behind an embedding job's batches."""
LOCAL_MEMORY_ARENA: Final[bool] = False
"""ONNX Runtime's CPU memory arena: off, so memory a batch used is given back. Embedding the
fixture library (bge-small, 2 threads, batches of 16) ended at 493 MB with it off, 510 MB on,
at the same speed (#278)."""
PINNED_MODEL_REVISIONS: Final[dict[str, str]] = {
    "BAAI/bge-small-en-v1.5": "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
    "Xenova/ms-marco-MiniLM-L-6-v2": "a09144355adeed5f58c8ed011d209bf8ee5a1fec",
}
"""The Hub commit each default model is pulled at (Qdrant/bge-small-en-v1.5-onnx-Q of
2026-09-24, Xenova/ms-marco-MiniLM-L-6-v2 of 2025-06-30): a pull is reproducible, and a model
pulled at another commit is refused until it is pulled again. Other models are pulled at the
commit ``main`` points to then, which the marker records."""
LOCAL_PROFILE: Final[str] = "local"
"""The profile name the docs' ``local:<model>`` roles use."""
LOCAL_PROFILE_HINT: Final[str] = "EXACTDOCS_AI__PROVIDERS__LOCAL__KIND=local"
"""How an operator declares the ``local`` profile a ``local:<model>`` role names."""
HUB_FILES: Final[tuple[str, ...]] = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
"""The tokenizer and configuration files fetched with a model's ONNX file."""
TOKENIZER_FILES: Final[tuple[str, ...]] = ("tokenizer.json", "tokenizer_config.json")
"""Files a pulled model must have besides its ONNX file (the others are optional)."""
