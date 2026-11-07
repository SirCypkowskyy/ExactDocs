"""Constants of ``exactdocs.bootstrap``: every fixed value its modules share.

Each is ``Final`` and documented; see *Python conventions* in docs/architecture.md.
"""

import re
from pathlib import Path
from typing import Final

from exactdocs.catalog.models import ManifestState
from exactdocs.retrieval.models import ManifestStatus
from exactdocs_kernel import (
    BusyError,
    ConflictError,
    DomainError,
    NotFoundError,
    RateLimitedError,
    UnauthenticatedError,
    ValidationError,
)

# ---------------------------------------------------------------- cli
DEFAULT_TOKEN_DAYS: Final[int] = 90
"""Lifetime of an API token created on the command line when ``--days`` is not given."""
LOCAL_COMMANDS: Final[frozenset[str]] = frozenset(
    {"serve", "reindex", "backup", "restore", "admin create", "admin reset-password"}
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
CONFIG_FILE_VARIABLE: Final[str] = "EXACTDOCS_CONFIG_FILE"
"""Environment variable that points the CLI client at another config file."""
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
KNOWN_HOSTS_FILE: Final[str] = "known_hosts"
"""Under the data dir: SSH host keys, the big three pre-seeded."""
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
MIN_SQLITE: Final[tuple[int, ...]] = (3, 35)
"""Search uses `WITH ... AS MATERIALIZED`"""

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
    403: "Refused: the instance has no admin account yet (`setup_required`).",
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
SCRUBBED_SPAN_ATTRIBUTES: Final[frozenset[str]] = frozenset({"enduser.id", "enduser.scope"})
"""Who called (FastMCP puts the token's client ID and scopes on every MCP span): left out unless
the operator opted in, like the query text they would tie to a person.
"""
SCRUBBED_EXCEPTION_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"exception.message", "exception.stacktrace"}
)
"""Left out of exception events unless the operator opted in: they can quote the input."""
REDACTED: Final[str] = "REDACTED"
"""What a redacted URL query value is replaced with."""
URL_QUERY_ATTRIBUTE: Final[str] = "url.query"
"""The request span attribute with the URL's query string (OpenTelemetry semantic conventions)."""
OTLP_MODULE: Final[str] = "exactdocs.bootstrap.otlp"
"""The module that sets up the OpenTelemetry SDK, loaded only when telemetry is on."""
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
