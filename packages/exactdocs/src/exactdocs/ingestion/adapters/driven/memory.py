from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from exactdocs.ingestion.models import (
    ArticleChunk,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    JobState,
    Removed,
)
from exactdocs_kernel import NotFoundError


@dataclass(slots=True)
class InMemoryJobRepository:
    """Implements ``ports.driven.JobRepository``. For tests."""

    jobs: dict[JobId, Job] = field(default_factory=dict)

    @classmethod
    def of(cls, jobs: Iterable[Job]) -> Self:
        """Create a repository pre-filled with ``jobs``."""
        return cls({job.id: job for job in jobs})

    async def add(self, job: Job) -> None:
        """Store a new job."""
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


@dataclass(slots=True)
class InMemoryLibrarySources:
    """Implements ``ports.driven.LibrarySources``. For tests."""

    sources: dict[str, ImportSource] = field(default_factory=dict)
    versions: dict[str, dict[str, str]] = field(default_factory=dict)
    """``{library: {ref: commit SHA}}``."""

    async def imported_versions(self, library: str) -> Mapping[str, str]:
        """Return the library's ``{ref: commit SHA}``; raises ``NotFoundError`` if unknown."""
        await self.get(library)
        return self.versions.get(library, {})

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
