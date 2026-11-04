"""Data crossing the ingestion boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.ingestion.models import (
    MAX_TAG_RULES,
    FileProblem,
    Job,
    JobState,
    RefKind,
    RepositoryHost,
    ResolvedRef,
)
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
    commit_sha: str | None = Field(description="The commit `version` was pinned to, if any.")
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
            commit_sha=job.commit_sha,
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


class LatestJob(_Dto):
    """The newest job of one version of a library, light enough to list for every library."""

    id: str
    kind: str
    library: str
    version: str | None
    state: JobState
    done: int
    total: int
    skipped: int = Field(description="How many files the job skipped; see `/jobs/{id}`.")
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_model(cls, job: Job) -> Self:
        """Map a domain entity, keeping the count of skipped files, not the files."""
        return cls(
            id=job.id,
            kind=job.kind,
            library=job.library,
            version=job.version,
            state=job.state,
            done=job.done,
            total=job.total,
            skipped=len(job.problems),
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class LatestJobs(_Dto):
    """The newest job of every (library, version), ordered by library and version."""

    jobs: list[LatestJob]


class EnqueueJobCommand(_Dto):
    """Queue a job of ``kind`` for a library (and optionally one version of it)."""

    kind: str = Field(min_length=1)
    library: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)
    commit_sha: str | None = Field(default=None, min_length=1)
    ref_kind: RefKind | None = Field(default=None, description="What `version` is.")


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


class TagRuleIn(_Dto):
    """Articles whose path matches `pattern` (a glob like `docs/api/**`) get `tag`."""

    pattern: str = Field(min_length=1, max_length=256)
    tag: str = Field(min_length=1, max_length=200)


class AddLibraryCommand(_Dto):
    """Create a library from a git repository, with its doc selection, and queue its import."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description=CheckRepositoryCommand.model_fields["url"].description,
    )
    library_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="`/owner/repo`; omitted: the one proposed from the URL.",
    )
    ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="A tag, a branch or a full or short commit SHA; omitted: the default branch.",
    )
    include_paths: list[str] = Field(
        default_factory=list,
        description="Folders, files or globs to import; empty: every `.md`/`.mdx` file.",
    )
    exclude_paths: list[str] = Field(
        default_factory=list, description="Folders, files or globs to leave out; they win."
    )
    tag_rules: list[TagRuleIn] = Field(
        default_factory=list,
        max_length=MAX_TAG_RULES,
        description="Tags for articles by path; they are added to the front-matter tags.",
    )


class AddedLibrary(_Dto):
    """The new library, the commit its ref was pinned to, and the queued import."""

    library_id: str
    ref: str = Field(description="The tag or branch name, or the full SHA of a commit.")
    ref_kind: RefKind
    commit_sha: str
    job_id: str

    @classmethod
    def of(cls, library_id: str, resolved: ResolvedRef, job: JobSummary) -> Self:
        """Combine the pieces of a created library."""
        return cls(
            library_id=library_id,
            ref=resolved.name,
            ref_kind=resolved.kind,
            commit_sha=resolved.commit_sha,
            job_id=job.id,
        )


class ListRepositoryRefsQuery(_Dto):
    """Ask a repository for its tags and branches."""

    url: str = Field(min_length=1, max_length=2048)


class RefOut(_Dto):
    """A tag or branch and the commit it points at."""

    name: str
    commit_sha: str


class RepositoryRefs(_Dto):
    """What a repository offers as a ref, for the picker. Sorted by name, 1000 of each at most."""

    default_branch: str | None
    branches: list[RefOut]
    tags: list[RefOut]
    truncated: bool = Field(description="True when branches or tags were cut at 1000 each.")
