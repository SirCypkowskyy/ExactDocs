"""Driven (secondary) ports of ingestion: what it needs from git, storage and other domains."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from exactdocs.ingestion.models import (
    ArticleChunk,
    Job,
    JobId,
    ParsedArticle,
    ProposedId,
    RemoteRefs,
    RepositoryUrl,
)


class JobRepository(Protocol):
    """Persistence for jobs."""

    async def add(self, job: Job) -> None:
        """Store a new job."""
        ...

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID."""
        ...

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``."""
        ...

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered)."""
        ...

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state."""
        ...

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job.

        Returns it in the ``running`` state with ``started_at`` set, or ``None`` when nothing
        may run. This is what keeps two jobs of one library from ever running together.
        """
        ...


class JobProgress(Protocol):
    """What a running job reports to; every call is stored at once."""

    async def report(self, *, done: int, total: int) -> None:
        """``done`` of ``total`` files processed."""
        ...

    async def problem(self, path: str, reason: str) -> None:
        """Record a skipped file; the job goes on."""
        ...


class JobHandler(Protocol):
    """Runs jobs of one kind. Raising fails the job; the error text is shown to users."""

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the job from the beginning."""
        ...


class RecoveryHook(Protocol):
    """Cleans up after a job of one kind that was ``running`` when the app stopped."""

    async def __call__(self, job: Job, /) -> None:
        """Undo what the interrupted run left half done."""
        ...


class GitRemote(Protocol):
    """Talk to a remote git repository (the system ``git``; no hosting APIs)."""

    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        """List the remote's refs (``git ls-remote``), narrowed by ref patterns such as ``HEAD``.

        Never prompts for credentials. Raises ``NotAGitRepositoryError``,
        ``RepositoryUnreachableError`` (including a timeout) or ``RepositoryAuthRequiredError``.
        """
        ...


class LibraryIds(Protocol):
    """What ingestion needs to know about the catalog, in its own words."""

    async def is_taken(self, library_id: ProposedId) -> bool:
        """Tell whether a library with this ``/owner/repo`` ID already exists."""
        ...


class Chunker(Protocol):
    """Cuts a parsed article into chunks at its headings, never inside a code block or table."""

    @property
    def config_hash(self) -> str:
        """Key for chunk sets: changes with the chunker's config, its version and the parser's."""
        ...

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        """Return the chunks in reading order; their contents joined are ``article.body``.

        An empty body has no chunks. This is CPU-bound and synchronous: the import use case
        should call it through ``asyncio.to_thread``. There is no size cap yet.
        """
        ...
