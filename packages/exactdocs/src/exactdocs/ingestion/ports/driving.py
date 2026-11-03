"""Driving (primary) ports of ingestion: what the outside world may ask it to do."""

from typing import Protocol

from exactdocs.ingestion.dtos import (
    EnqueueJobCommand,
    GetJobQuery,
    JobList,
    JobSummary,
    ListLibraryJobsQuery,
)


class EnqueueJob(Protocol):
    """Queue a job; raises ``UnknownJobKindError`` when no handler is registered for its kind."""

    async def __call__(self, command: EnqueueJobCommand) -> JobSummary:
        """Run the use case."""
        ...


class GetJob(Protocol):
    """Fetch one job; raises ``JobNotFoundError`` when it does not exist."""

    async def __call__(self, query: GetJobQuery) -> JobSummary:
        """Run the use case."""
        ...


class ListLibraryJobs(Protocol):
    """List a library's latest jobs, newest first."""

    async def __call__(self, query: ListLibraryJobsQuery) -> JobList:
        """Run the use case."""
        ...


class RecoverJobs(Protocol):
    """On start: run each interrupted job's recovery hook, then queue it again."""

    async def __call__(self) -> None:
        """Run the use case."""
        ...


class RunNextJob(Protocol):
    """Run the next job that may run to its end, or do nothing."""

    async def __call__(self) -> bool:
        """Return whether a job ran (``False``: nothing was waiting)."""
        ...
