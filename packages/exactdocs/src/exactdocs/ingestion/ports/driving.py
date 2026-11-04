"""Driving (primary) ports of ingestion: what the outside world may ask it to do."""

from typing import Protocol

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddLibraryCommand,
    CheckedRepository,
    CheckRepositoryCommand,
    EnqueueJobCommand,
    GetJobQuery,
    JobList,
    JobSummary,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    RepositoryRefs,
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
    """List a page of a library's jobs, newest first."""

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


class CheckRepository(Protocol):
    """Validate a pasted git URL and propose a library ID, saving nothing.

    Raises ``InvalidRepositoryUrlError``, ``LibraryIdTakenError`` (checked before any network
    traffic), ``NotAGitRepositoryError``, ``RepositoryUnreachableError`` or
    ``RepositoryAuthRequiredError``.
    """

    async def __call__(self, command: CheckRepositoryCommand) -> CheckedRepository:
        """Run the use case."""
        ...


class AddLibrary(Protocol):
    """Create a library, pin its ref to a commit and queue the import.

    Raises what ``CheckRepository`` raises, plus ``InvalidPathPatternError``, ``UnknownRefError``
    and ``AmbiguousRefError``. Nothing is stored unless all of it checks out.
    """

    async def __call__(self, command: AddLibraryCommand) -> AddedLibrary:
        """Run the use case."""
        ...


class ListRepositoryRefs(Protocol):
    """List a repository's branches and tags; raises what ``CheckRepository`` raises."""

    async def __call__(self, query: ListRepositoryRefsQuery) -> RepositoryRefs:
        """Run the use case."""
        ...
