"""Job repositories that show a use case reads only a library's unfinished jobs (#329)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.constants import ACTIVE_JOB_STATES, IMPORT_JOB
from exactdocs.ingestion.models import Job, JobId

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class UnfinishedOnly(InMemoryJobRepository):
    """A repository that refuses to hand over a library's whole job history."""

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Fail: the caller should have asked for the unfinished jobs only.

        Args:
            library: The library ID.

        Raises:
            AssertionError: Always.
        """
        loaded_everything = f"every job of {library} was loaded to find its unfinished ones"
        raise AssertionError(loaded_everything)


class HistoryWithoutUnfinished(InMemoryJobRepository):
    """A repository whose history leaves out the unfinished jobs, as if they were not there.

    A caller that still finds a queued or running job must have asked
    ``list_unfinished_for_library`` for it.
    """

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's finished jobs only, newest first.

        Args:
            library: The library ID.

        Returns:
            The finished jobs.
        """
        everything = await super().list_for_library(library)
        return [job for job in everything if job.state not in ACTIVE_JOB_STATES]


def finished_imports(library: str, count: int, *, version: str = "old") -> list[Job]:
    """Return ``count`` succeeded imports of ``library``, older than any job a test queues.

    Args:
        library: The library ID.
        count: How many jobs.
        version: The ref they imported.

    Returns:
        The jobs, IDs ``0000-done-<n>`` (they sort before the uuid7 IDs of new jobs).
    """
    return [
        Job.queued(
            job_id=JobId(f"0000-done-{number:05}"),
            kind=IMPORT_JOB,
            library=library,
            version=version,
            now=T0 + timedelta(seconds=number),
        )
        .started(T0)
        .succeeded(T0)
        for number in range(count)
    ]
