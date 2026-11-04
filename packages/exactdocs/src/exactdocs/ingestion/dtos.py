"""Data crossing the ingestion boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.ingestion.models import FileProblem, Job, JobState, RepositoryHost
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, Page


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FileProblemSummary(_Dto):
    """A file the job skipped and the reason."""

    path: str
    reason: str

    @classmethod
    def from_model(cls, problem: FileProblem) -> Self:
        """Map a domain value."""
        return cls(path=problem.path, reason=problem.reason)


class JobSummary(_Dto):
    """A job and how far it got. ``total`` is 0 until the job knows its size."""

    id: str
    kind: str
    library: str
    version: str | None
    state: JobState
    done: int
    total: int
    problems: list[FileProblemSummary]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_model(cls, job: Job) -> Self:
        """Map a domain entity to its boundary representation."""
        return cls(
            id=job.id,
            kind=job.kind,
            library=job.library,
            version=job.version,
            state=job.state,
            done=job.done,
            total=job.total,
            problems=[FileProblemSummary.from_model(p) for p in job.problems],
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class JobList(_Dto):
    """A page of the jobs of one library, newest first."""

    jobs: list[JobSummary]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )

    @classmethod
    def from_page(cls, page: Page[Job]) -> Self:
        """Map a page of domain entities."""
        return cls(
            jobs=[JobSummary.from_model(job) for job in page.items], next_cursor=page.next_cursor
        )


class EnqueueJobCommand(_Dto):
    """Queue a job of ``kind`` for a library (and optionally one version of it)."""

    kind: str = Field(min_length=1)
    library: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)


class GetJobQuery(_Dto):
    """Look up one job by its ID."""

    job_id: str = Field(min_length=1)


class ListLibraryJobsQuery(_Dto):
    """One page of a library's jobs: ``limit`` items after the ``cursor`` of the previous page."""

    library: str = Field(min_length=1)
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    cursor: str | None = None


class CheckRepositoryCommand(_Dto):
    """Ask whether a git URL works, before anything is saved."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description="https, http, ssh (`ssh://` or `git@host:org/repo.git`) or file URL, "
        "without credentials.",
    )


class CheckedRepository(_Dto):
    """A reachable git repository and what a new library from it would look like."""

    host: RepositoryHost = Field(description="The hosting service, for source links.")
    library_id: str = Field(description="The proposed `/owner/repo` library ID.")
    default_branch: str | None = Field(
        description="The branch `HEAD` points at; null for an empty repository."
    )
