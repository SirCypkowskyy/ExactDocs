"""Data crossing the ingestion boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from exactdocs.ingestion.models import (
    MAX_TAG_RULES,
    AccessToken,
    Credential,
    DeployKey,
    FileProblem,
    Job,
    JobState,
    ProblemCode,
    RefKind,
    RepositoryHost,
    ResolvedRef,
    SyncStatus,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, Page


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FileProblemSummary(_Dto):
    """A problem with a file: skipped (`is_skip`) or imported with a note. `code` is stable."""

    path: str
    code: ProblemCode
    reason: str = Field(description="A sentence for people; may change, branch on `code`.")
    is_skip: bool = Field(description="False when the file was imported despite the problem.")

    @classmethod
    def from_model(cls, problem: FileProblem) -> Self:
        """Map a domain value."""
        return cls(
            path=problem.path,
            code=problem.code,
            reason=problem.reason,
            is_skip=problem.code.is_skip,
        )


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
    chunked: int = Field(
        description="Chunk sets cut by an import: one per distinct new file content."
    )
    reused: int = Field(
        description="Articles whose chunk set an earlier import had stored (files, not blobs)."
    )
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
            chunked=job.chunked,
            reused=job.reused,
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
            skipped=job.skipped_count,
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


class GetLibraryAccessQuery(_Dto):
    """Ask whether a library needs a credential to be read from its repository."""

    library: str = Field(min_length=1)


class LibraryAccess(_Dto):
    """Whether the library's repository is private: it has a stored credential (token or key)."""

    private: bool


class AccessTokenIn(_Dto):
    """An HTTPS access token for a private repository. Write-only: no response repeats it."""

    kind: Literal["token"]
    token: SecretStr = Field(max_length=8192)
    username: str | None = Field(
        default=None,
        max_length=100,
        description="What the host expects next to the token; default `x-access-token` "
        "(GitHub, GitLab). Bitbucket repository tokens use `x-token-auth`.",
    )

    def to_model(self) -> Credential:
        """Validate and convert to the domain value."""
        extra = {} if self.username is None else {"username": self.username}
        return AccessToken(token=self.token.get_secret_value(), **extra)


class DeployKeyIn(_Dto):
    """An SSH deploy key (private part, no passphrase). Write-only: no response repeats it."""

    kind: Literal["ssh_key"]
    private_key: SecretStr = Field(max_length=32768)

    def to_model(self) -> Credential:
        """Validate and convert to the domain value."""
        return DeployKey(private_key=self.private_key.get_secret_value())


CredentialIn = Annotated[AccessTokenIn | DeployKeyIn, Field(discriminator="kind")]
_CREDENTIAL_DESCRIPTION = (
    "A token (https URL) or deploy key (ssh URL) for a private repository. It is stored "
    "encrypted, offered only to the repository's own host and never returned."
)


class CheckRepositoryCommand(_Dto):
    """Ask whether a git URL works, before anything is saved."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description="https, http, ssh (`ssh://` or `git@host:org/repo.git`) or file URL, "
        "without credentials.",
    )
    credential: CredentialIn | None = Field(default=None, description=_CREDENTIAL_DESCRIPTION)


class CheckedRepository(_Dto):
    """A reachable git repository and what a new library from it would look like."""

    host: RepositoryHost = Field(description="The hosting service, for source links.")
    library_id: str = Field(description="The proposed `/owner/repo` library ID.")
    default_branch: str | None = Field(
        description="The branch `HEAD` points at; null for an empty repository."
    )
    host_key_fingerprint: str | None = Field(
        default=None,
        description="For an SSH URL, the `SHA256:...` fingerprint of the server's host key "
        "(first seen now, or pinned): compare it with the host's published one.",
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
    credential: CredentialIn | None = Field(default=None, description=_CREDENTIAL_DESCRIPTION)


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


class AddVersionBody(_Dto):
    """The request body of adding a version; the library is in the path."""

    ref: str = Field(
        min_length=1,
        max_length=255,
        description="A tag, a branch or a full or short commit SHA.",
    )
    credential: CredentialIn | None = Field(
        default=None,
        description=_CREDENTIAL_DESCRIPTION + " Replaces the library's stored credential; "
        "needed again when it answers `credentials_required`.",
    )


class AddVersionCommand(AddVersionBody):
    """Import another version of an existing library, with the library's own settings."""

    library: str = Field(min_length=1, max_length=200, description="The canonical `/owner/repo`.")


class AddedVersion(AddedLibrary):
    """Like ``AddedLibrary``, but ``library_id`` is the existing library."""


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


class RemoveVersionCommand(_Dto):
    """Remove one version of a library everywhere and free its content."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str = Field(min_length=1)


class RemoveLibraryCommand(_Dto):
    """Remove a library, with all its versions, everywhere and free its content."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")


class RemovalResult(_Dto):
    """A removal is done for readers when this is returned; the disk is freed by a job."""

    library: str
    ref: str | None = Field(description="The removed version; null when a library was removed.")
    default_version: str | None = Field(
        description="What `/owner/repo` means now; null when no version is left."
    )
    collection_job_id: str | None = Field(
        description="The job that frees the content (`/jobs/{id}`); null if it was not queued."
    )


class SyncLibraryCommand(_Dto):
    """Re-sync the branch versions of a library."""

    library: str = Field(min_length=1, max_length=200, description="The canonical `/owner/repo`.")


class SyncedVersion(_Dto):
    """What the re-sync did with one version of the library."""

    ref: str
    ref_kind: RefKind
    status: SyncStatus
    previous_commit_sha: str = Field(description="The commit the version served before.")
    commit_sha: str = Field(
        description="The branch tip now; for a tag or a commit, the commit it is pinned to."
    )
    job_id: str | None = Field(
        description=(
            "The queued import; the import already in progress (`importing`); the failed job "
            "that records why the branch is gone (`failed`); or the no-op job that cleared an "
            "earlier failure."
        )
    )


class SyncedLibrary(_Dto):
    """The outcome per version; ``queued`` ones have an import to poll by ``job_id``."""

    library_id: str
    versions: list[SyncedVersion]
