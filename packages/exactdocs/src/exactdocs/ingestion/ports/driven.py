"""Driven (secondary) ports of ingestion: what it needs from git, storage and other domains."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from exactdocs.ingestion.models import (
    ArticleChunk,
    Collected,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    NewLibrary,
    ParsedArticle,
    PathSelection,
    ProblemCode,
    ProposedId,
    RemoteRefs,
    Removed,
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

    async def delete_for(self, library: str, version: str | None = None) -> None:
        """Delete the library's jobs (only those of ``version`` when given). Not running ones."""
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
    """What a running job reports to; stored soon (not at every call), and at the job's end."""

    async def report(self, *, done: int, total: int) -> None:
        """``done`` of ``total`` files processed."""
        ...

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        """Record a problem with a file (skipped or imported with a note); the job goes on."""
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

        The files must be checked out verbatim (no eol, filter or encoding conversion): the import
        derives each file's git blob SHA from the bytes it reads.
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


class LibrarySources(Protocol):
    """Where a library's articles come from (the catalog, in ingestion's words)."""

    async def imported_versions(self, library: str) -> Mapping[str, str]:
        """Return ``{ref: commit SHA}`` of the library's versions; raises ``NotFoundError``.

        ``library`` is a canonical (lower-case) ID.
        """
        ...

    async def get(self, library: str) -> ImportSource:
        """Return the repository and path selection of a library; raises when it is unknown."""
        ...


class VersionPublisher(Protocol):
    """Publishes a version into the catalog in two steps: store (invisible), then activate."""

    async def store(self, version: ImportedVersion) -> str:
        """Store the version's articles as a pending manifest; return its ID. Nothing is served."""
        ...

    async def activate(self, manifest_id: str) -> None:
        """Make the pending manifest what its version serves, all at once."""
        ...

    async def describe(
        self, *, library: str, ref: str, title: str | None, description: str | None
    ) -> None:
        """Offer the root README's heading and first paragraph of an activated version.

        The catalog decides what to do with them: it only takes the default version's README
        and never replaces a title or description a user edited. ``None`` means the README
        had none.
        """
        ...

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete the library's pending manifests (only ``manifest_id``'s when given)."""
        ...


class ChunkIndex(Protocol):
    """Where chunks are stored and searched (retrieval, in ingestion's words)."""

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        """Return the stored chunks of blobs chunked under ``config_hash``; others are left out."""
        ...

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        """Store and index the version's chunks of a pending manifest (before it is activated)."""
        ...

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete the library's pending chunks (only ``manifest_id``'s when given).

        Call it before the catalog's discard: it needs the catalog to still say "pending".
        """
        ...

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        """Delete the chunks of manifests the catalog has just deleted (and unused chunk sets)."""
        ...


class Removals(Protocol):
    """Removes versions and libraries from the catalog (in ingestion's words)."""

    async def remove_version(self, library: str, ref: str) -> Removed:
        """Delete the version and its manifests at once; raises ``NotFoundError`` if unknown."""
        ...

    async def remove_library(self, library: str) -> Removed:
        """Delete the library, its versions and manifests; raises ``NotFoundError`` if unknown."""
        ...


class Collector(Protocol):
    """Frees what one domain no longer needs; the collection job runs them in order."""

    async def collect(self, *, grace_seconds: int) -> Collected:
        """Delete what is unused and older than the grace period; say how many things."""
        ...
