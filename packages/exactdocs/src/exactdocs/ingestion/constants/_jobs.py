"""Constants of the DBOS job queue and worker."""

from datetime import timedelta
from typing import Final

QUEUE: Final[str] = "exactdocs-jobs"
"""Name of the DBOS queue jobs run on."""
SCHEDULE: Final[str] = "exactdocs-scheduled-checks"
"""The DBOS schedule that ticks the scheduled checks (the worker creates it)."""
WORKFLOW: Final[str] = "exactdocs.run_job"
"""Name of the DBOS workflow that runs one job."""
STEPS_VERSION: Final[str] = "jobs-5"
"""DBOS's application version: bump it when a job's steps change (names, order or results).
``jobs-2`` added the steps of ``reprocess`` and ``retag`` (#61); ``jobs-3`` gave ``ImportedRef``
its ``origin`` and ``pinned`` (#81); ``jobs-4`` starts the import with "read the chunking
settings" and added the steps of ``rechunk`` (#67); ``jobs-5`` counted the articles parsed and
taken as stored (#164). A workflow of another version is not resumed: its job starts over from
the beginning.
"""

_WAIT_FOR_OTHER: Final[float] = 30.0
"""Seconds."""
_THREADS: Final[int] = 32
"""The most asyncio's own default pool has (min(32, CPUs + 4))"""
_FORGET_POLL: Final[float] = (
    0.05  # seconds between looks at a finished workflow's status, while it is recorded
)
"""Seconds between looks at a finished workflow's status, while it is recorded."""
_FORGET_TRIES: Final[int] = 200
"""Polls to wait for a cancelled workflow to finish before it is forgotten."""
_VACUUM_ABOVE: Final[int] = 2**20
"""Bytes of free pages."""
_LIVE: Final[list[str]] = ["ENQUEUED", "PENDING", "DELAYED"]
"""DBOS workflow states of a job that may still run."""
SCHEDULE_WORKFLOW: Final[str] = "exactdocs.scheduled_checks"
"""Name of the DBOS workflow that runs the scheduled auto-sync checks."""
EVERY_MINUTE: Final[str] = "0 * * * * *"
"""Seconds first: second 0 of every minute."""
_DONE: Final[frozenset[str]] = frozenset(
    {"SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"}
)
"""DBOS workflow states of a workflow that will not run again."""
LEGACY_CODES: Final[dict[str, str]] = {
    "not valid UTF-8": "undecodable",
    "not a regular file": "not_a_file",
    "file name is not valid UTF-8": "bad_file_name",
}
"""The ``ProblemCode`` of a file problem stored before problems had codes, by its reason text."""
_LOCK_NAMESPACE: Final[str] = "exactdocs:{purpose}:{library}"
"""Text a PostgreSQL library lock is hashed from (``hashtextextended``): one key per purpose and
library, so tag and settings locks of a library never wait on each other."""
_MIN_TICK_RETENTION: Final[timedelta] = timedelta(minutes=10)
"""Shortest time an ended tick workflow is kept on PostgreSQL (see ``tick_retention``)."""
