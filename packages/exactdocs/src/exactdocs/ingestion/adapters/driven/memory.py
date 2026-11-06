import copy
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self, cast

from exactdocs.ingestion.errors import CredentialsRequiredError, VersionImportingError
from exactdocs.ingestion.models import (
    ACTIVE_JOB_STATES,
    IMPORT_KINDS,
    ArticleChunk,
    AutoSync,
    CopiedVersion,
    Credential,
    GitRename,
    ImportedRef,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    JobState,
    Removed,
    StoredTags,
)
from exactdocs_kernel import NotFoundError


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryJobRepository:
    """Implements ``ports.driven.JobRepository``. For tests."""

    jobs: dict[JobId, Job] = field(default_factory=dict)

    @classmethod
    def of(cls, jobs: Iterable[Job]) -> Self:
        """Create a repository pre-filled with ``jobs``."""
        return cls(jobs={job.id: job for job in jobs})

    async def add(self, job: Job) -> None:
        """Store a new job; a second unfinished import of one (library, ref) is refused."""
        if job.kind in IMPORT_KINDS and job.state in ACTIVE_JOB_STATES and job.version:
            for other in self.jobs.values():
                same = (other.library, other.version) == (job.library, job.version)
                if same and other.kind in IMPORT_KINDS and other.state in ACTIVE_JOB_STATES:
                    raise VersionImportingError(job.library, job.version or "")
        self.jobs[job.id] = job

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID."""
        self.jobs[job.id] = job

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``."""
        return self.jobs.get(job_id)

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered)."""
        mine = [job for job in self.jobs.values() if job.library == library]
        return sorted(mine, key=lambda job: job.id, reverse=True)

    async def list_latest(self) -> Sequence[Job]:
        """Return the newest job of every (library, version), ordered by library and version."""
        newest: dict[tuple[str, str | None], Job] = {}
        for job in sorted(self.jobs.values(), key=lambda job: job.id):
            newest[job.library, job.version] = job
        return sorted(newest.values(), key=lambda job: (job.library, job.version or ""))

    async def delete_for(self, library: str, version: str | None = None) -> None:
        """Delete the library's jobs (only those of ``version`` when given), never a running one."""
        for job in list(self.jobs.values()):
            if (
                job.library == library
                and job.state is not JobState.RUNNING
                and (version is None or job.version == version)
            ):
                del self.jobs[job.id]

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state."""
        return [job for job in self.jobs.values() if job.state is JobState.RUNNING]

    async def list_queued(self) -> Sequence[Job]:
        """Return every job in the ``queued`` state, oldest first."""
        waiting = [job for job in self.jobs.values() if job.state is JobState.QUEUED]
        return sorted(waiting, key=lambda job: (job.created_at, job.id))

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job."""
        busy = {job.library for job in self.jobs.values() if job.state is JobState.RUNNING}
        waiting = [job for job in self.jobs.values() if job.state is JobState.QUEUED]
        for job in sorted(waiting, key=lambda job: (job.created_at, job.id)):
            if job.library not in busy:
                started = job.started(now)
                self.jobs[job.id] = started
                return started
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibrarySources:
    """Implements ``ports.driven.LibrarySources``. For tests."""

    sources: dict[str, ImportSource] = field(default_factory=dict)
    versions: dict[str, list[ImportedRef]] = field(default_factory=dict)
    renames: dict[tuple[str, str], list[GitRename]] = field(default_factory=dict)

    async def renames_of(self, library: str, ref: str) -> Sequence[GitRename]:
        """Return the rename map of the version (empty when it has none)."""
        return self.renames.get((library, ref), [])

    async def imported_versions(self, library: str) -> Sequence[ImportedRef]:
        """Return the library's versions; raises ``NotFoundError`` if unknown."""
        await self.get(library)
        return self.versions.get(library, [])

    async def get(self, library: str) -> ImportSource:
        """Return the library's source; raises ``NotFoundError`` for an unknown library."""
        if library not in self.sources:
            message = f"library {library!r} not found"
            raise NotFoundError(message)
        return self.sources[library]


class NoRemovals:
    """Implements ``ports.driven.Removals``; any call is a test bug. For tests."""

    async def remove_version(self, library: str, ref: str) -> Removed:
        """Not expected to be called."""
        raise NotImplementedError

    async def remove_library(self, library: str) -> Removed:
        """Not expected to be called."""
        raise NotImplementedError


class NoIndex:
    """Implements ``ports.driven.ChunkIndex``; any call is a test bug. For tests."""

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        """Not expected to be called."""
        raise NotImplementedError

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        """Not expected to be called."""
        raise NotImplementedError

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Not expected to be called."""
        raise NotImplementedError

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        """Not expected to be called."""
        raise NotImplementedError

    async def retag(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> None:
        """Not expected to be called."""
        raise NotImplementedError


class NoCopier:
    """Implements ``ports.driven.VersionCopier``; any call is a test bug. For tests."""

    async def copy(self, library: str, ref: str, *, content_version: int) -> CopiedVersion | None:
        """Not expected to be called."""
        raise NotImplementedError


class NoStoredTags:
    """Implements ``ports.driven.ImportedTagStore``; any call is a test bug. For tests."""

    async def stored_tags(self, library: str, ref: str) -> StoredTags | None:
        """Not expected to be called."""
        raise NotImplementedError

    async def set_imported_tags(
        self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Not expected to be called."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryCredentialVault:
    """Implements ``ports.driven.CredentialVault``. For tests; nothing is encrypted."""

    credentials: dict[str, Credential] = field(default_factory=dict)
    scopes: dict[str, str] = field(default_factory=dict)  # of the credentials saved through here

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        """Store the library's credential."""
        self.credentials[library] = credential
        self.scopes[library] = scope

    async def load(self, library: str, scope: str) -> Credential | None:
        """Return the library's credential, or ``None``; one saved for another scope is refused."""
        if self.scopes.get(library, scope) != scope:
            raise CredentialsRequiredError
        return self.credentials.get(library)

    async def delete(self, library: str) -> None:
        """Forget the library's credential."""
        self.credentials.pop(library, None)
        self.scopes.pop(library, None)

    async def has(self, library: str) -> bool:
        """Whether the library has a credential."""
        return library in self.credentials


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- replay position
class InMemoryCheckpoints:
    """``Checkpoints`` that keep the results of one job's completed steps, as DBOS does.

    ``resumed()`` returns the checkpoints of the next run of the same job: it replays the
    completed steps in order, then runs the rest. Results are copied, as a stored result would
    be, so nothing a later step changes reaches them.
    """

    completed: list[tuple[str, object]] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    """The steps that really ran (not replayed), in order."""
    _next: int = 0

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        """Replay the step if this job completed it before, else run and record it."""
        if self._next < len(self.completed):
            recorded, result = self.completed[self._next]
            if recorded != name:
                message = f"step {self._next} was {recorded!r}, not {name!r}"
                raise AssertionError(message)
            self._next += 1
            # The step of this name recorded a T: a job takes the same steps on every run.
            return cast("T", copy.deepcopy(result))
        self.ran.append(name)
        value = await run()
        self.completed.append((name, copy.deepcopy(value)))
        self._next += 1
        return value

    def resumed(self) -> Self:
        """Return the checkpoints of the job's next run, after a crash."""
        return type(self)(completed=list(self.completed))


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryAutoSyncStore:
    """Implements ``ports.driven.AutoSyncStore``. For tests."""

    schedules: dict[str, AutoSync] = field(default_factory=dict)

    async def get(self, library: str) -> AutoSync | None:
        """Return the library's schedule, or ``None``."""
        return self.schedules.get(library)

    async def save(self, auto_sync: AutoSync) -> None:
        """Store the schedule."""
        self.schedules[auto_sync.library] = auto_sync

    async def delete(self, library: str) -> None:
        """Forget the library's schedule."""
        self.schedules.pop(library, None)

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        """Store the check if the schedule is still the one it read."""
        stored = self.schedules.get(read.library)
        if stored is None or (stored.revision, stored.checked_at) != (
            read.revision,
            read.checked_at,
        ):
            return False
        self.schedules[read.library] = checked
        return True

    async def list_all(self) -> Sequence[AutoSync]:
        """Return every schedule, by library."""
        return [self.schedules[k] for k in sorted(self.schedules)]
