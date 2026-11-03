"""Data crossing the ingestion boundary (into and out of driving ports). Immutable, validated."""

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.ingestion.models import FileProblem, Job, JobState


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
    """Jobs of one library, newest first."""

    jobs: list[JobSummary]

    @classmethod
    def from_models(cls, jobs: Iterable[Job]) -> Self:
        """Map domain entities, keeping their order."""
        return cls(jobs=[JobSummary.from_model(job) for job in jobs])


class EnqueueJobCommand(_Dto):
    """Queue a job of ``kind`` for a library (and optionally one version of it)."""

    kind: str = Field(min_length=1)
    library: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)


class GetJobQuery(_Dto):
    """Look up one job by its ID."""

    job_id: str = Field(min_length=1)


class ListLibraryJobsQuery(_Dto):
    """The latest ``limit`` jobs of one library."""

    library: str = Field(min_length=1)
    limit: Annotated[int, Field(ge=1, le=200)] = 50
