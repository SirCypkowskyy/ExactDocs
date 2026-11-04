"""Driven (secondary) ports of ingestion: what it needs from git, storage and other domains."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from exactdocs.ingestion.models import (
    ArticleChunk,
    Job,
    JobId,
    NewLibrary,
    ParsedArticle,
    PathSelection,
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

    async def list_latest(self) -> Sequence[Job]:
        """Return the newest job of every (library, version), ordered by library and version."""
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


class GitGateway(Protocol):
    """Fetch the files of one commit: shallow, without unselected blobs, into a managed folder."""

    def fetch(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        selection: PathSelection,
        *,
        refs: Sequence[str] = (),
    ) -> AbstractAsyncContextManager[Path]:
        """Check out ``commit_sha``: only the files ``selection`` may pick, plus the root README.

        Use as ``async with gateway.fetch(...) as folder``. The folder is private to this call and
        is removed on exit, also when the body or the fetch failed. It is a git work tree with no
        history: nothing older than the commit is fetched. ``refs`` (full names such as
        ``refs/tags/v1``) are tried only when the server refuses a request for a bare SHA.

        Never prompts, runs hooks or follows submodules. Raises ``RepositoryUnreachableError``
        (including a timeout), ``RepositoryAuthRequiredError``, ``NotAGitRepositoryError``,
        ``CommitUnavailableError`` or ``RepositoryTooLargeError``.
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


class NewLibraries(Protocol):
    """Where ingestion puts a library it was asked to add (the catalog, in its own words)."""

    async def add(self, library: NewLibrary) -> str:
        """Store the library and return its canonical ID.

        Raises a conflict when the ID is taken and a validation error when it is not a valid ID.
        """
        ...

    async def discard(self, library_id: str) -> None:
        """Remove a library that was just added and has no versions (the undo of ``add``)."""
        ...
