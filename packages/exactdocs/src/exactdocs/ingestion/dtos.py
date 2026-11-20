"""Data crossing the ingestion boundary (into and out of driving ports). Immutable, validated."""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from exactdocs.ingestion.constants import (
    CHANGE_JOBS,
    DEFAULT_CHUNKER,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_KEEP_LAST,
    ERROR_CODE,
    FULL_SHA,
    MAX_CHUNK_CHARS,
    MAX_HEADING_LEVEL,
    MAX_INTERVAL_MINUTES,
    MAX_KEEP_LAST,
    MAX_SOURCE_REF,
    MAX_SOURCE_REFS,
    MAX_SOURCES,
    MAX_TAG_PATTERN,
    MAX_TAG_RULES,
    MIN_INTERVAL_MINUTES,
    PREVIEW_FILES_DESCRIPTION,
    REFS_TRUNCATED_DESCRIPTION,
    SHORT_SHA,
    SOURCES_SCHEMA_DIALECT,
    SOURCES_SCHEMA_TITLE,
)
from exactdocs.ingestion.constants._dtos import (
    _CONTEXT7,
    _CONTEXT7_WARNING,
    _CREDENTIAL_DESCRIPTION,
)
from exactdocs.ingestion.errors import InvalidRepositoryUrlError
from exactdocs.ingestion.models import (
    AccessToken,
    AutoSync,
    ChunkingConfig,
    Context7Config,
    Credential,
    DeclaredLibrary,
    DeployKey,
    FileProblem,
    Job,
    JobState,
    LibraryUpdate,
    ProblemCode,
    RefKind,
    RepositoryHost,
    RepositoryUrl,
    ResolvedRef,
    SettingsChange,
    SourcesField,
    SourcesPlan,
    SyncStatus,
    TagRule,
    VersionOrigin,
    Webhook,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, MAX_PATH, MAX_TAG_INPUT, MAX_TAGS, Page


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class FileProblemSummary(_Dto):
    """A problem with a file: skipped (`is_skip`) or imported with a note. `code` is stable."""

    path: str
    """The file's repository path; empty for a problem of the whole import."""
    code: ProblemCode
    """What kind of problem it is."""
    reason: str
    """A sentence for people; may change, branch on `code`."""
    is_skip: bool
    """False when the file was imported despite the problem."""

    @classmethod
    def from_model(cls, problem: FileProblem) -> Self:
        """Map a domain value.

        Args:
            problem: The problem.

        Returns:
            The problem at the boundary.
        """
        return cls(
            path=problem.path,
            code=problem.code,
            reason=problem.reason,
            is_skip=problem.code.is_skip,
        )


class JobSummary(_Dto):
    """A job and how far it got. ``total`` is 0 until the job knows its size."""

    id: str
    """The job ID, for `/jobs/{id}`."""
    kind: str
    """What the job does: `import`, `refresh`, `reprocess`, `retag`, `rechunk`, `collect` or
    `embed`.
    """
    library: str
    """The library ID, `/owner/repo`."""
    version: str | None
    """The ref of the version the job is for; null for a job of the whole library."""
    commit_sha: str | None
    """The commit `version` was pinned to, if any."""
    state: JobState
    """`queued` and `running` jobs are unfinished; `succeeded` and `failed` ones are done."""
    done: int
    """How much of `total` is done."""
    total: int
    """The job's size, 0 until it is known: files for an import, versions for `reprocess`,
    `retag` and `rechunk`, chunks for `embed`, cleanup steps for `collect`.
    """
    problems: list[FileProblemSummary]
    """The files skipped or imported with a note."""
    chunked: int
    """Chunk sets cut by an import: one per distinct new file content."""
    reused: int
    """Articles whose chunk set an earlier import had stored (files, not blobs). For `embed`, the
    chunks another job embedded while this one ran (files shared with another library); they
    count in `done` too, so a succeeded `embed` job has `done` = `total`."""
    parsed: int = Field(default=0)
    """Articles an import parsed."""
    taken: int = Field(default=0)
    """Articles an import did not parse: an earlier import had stored the same file at the same path
    with the same parser, so its title, front matter and text were taken from the catalog (tags
    are derived again).
    """
    error: str | None
    """Why the job failed, for people; null unless it failed."""
    error_code: str | None = Field(description=ERROR_CODE)
    """The stable code of `error`; its schema description is ``ERROR_CODE``."""
    origin: VersionOrigin = Field(default=VersionOrigin.MANUAL)
    """`auto` when the scheduled check queued it, `manual` otherwise."""
    created_at: datetime
    """When the job was queued."""
    started_at: datetime | None
    """When the job last started running; null while it waits."""
    finished_at: datetime | None
    """When the job ended; null while it is unfinished."""

    @classmethod
    def from_model(cls, job: Job) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            job: The job.

        Returns:
            The job at the boundary, with its problems.
        """
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
            parsed=job.parsed,
            taken=job.taken,
            error=job.error,
            error_code=job.error_code,
            origin=job.origin,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class JobList(_Dto):
    """A page of the jobs of one library, newest first."""

    jobs: list[JobSummary]
    """The jobs, highest ID (newest) first."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""

    @classmethod
    def from_page(cls, page: Page[Job]) -> Self:
        """Map a page of domain entities.

        Args:
            page: The jobs and the cursor of the next page.

        Returns:
            The page at the boundary.
        """
        return cls(
            jobs=[JobSummary.from_model(job) for job in page.items], next_cursor=page.next_cursor
        )


class LatestJob(_Dto):
    """The newest job of one version of a library, light enough to list for every library."""

    id: str
    """The job ID, for `/jobs/{id}`."""
    kind: str
    """What the job does: `import`, `refresh`, `reprocess`, `retag`, `rechunk`, `collect` or
    `embed`.
    """
    library: str
    """The library ID, `/owner/repo`."""
    version: str | None
    """The ref of the version the job is for; null for a job of the whole library."""
    state: JobState
    """`queued` and `running` jobs are unfinished; `succeeded` and `failed` ones are done."""
    done: int
    """How much of `total` is done."""
    total: int
    """The job's size, 0 until it is known: files for an import, versions for `reprocess`,
    `retag` and `rechunk`, chunks for `embed`, cleanup steps for `collect`.
    """
    skipped: int
    """How many files the job skipped; see `/jobs/{id}`."""
    error: str | None
    """Why the job failed, for people; null unless it failed."""
    error_code: str | None = Field(description=ERROR_CODE)
    """The stable code of `error`; its schema description is ``ERROR_CODE``."""
    created_at: datetime
    """When the job was queued."""
    started_at: datetime | None
    """When the job last started running; null while it waits."""
    finished_at: datetime | None
    """When the job ended; null while it is unfinished."""

    @classmethod
    def from_model(cls, job: Job) -> Self:
        """Map a domain entity, keeping the count of skipped files, not the files.

        Args:
            job: The job.

        Returns:
            The job at the boundary, without its problems.
        """
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
            error_code=job.error_code,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class LatestJobs(_Dto):
    """The newest job of every (library, version), ordered by library and version."""

    jobs: list[LatestJob]
    """One job per (library, version); the jobs of a whole library count as one version."""


class EnqueueJobCommand(_Dto):
    """Queue a job of ``kind`` for a library (and optionally one version of it)."""

    kind: str = Field(min_length=1)
    """What the job does; a kind no handler is registered for is refused."""
    library: str = Field(min_length=1)
    """The library ID, `/owner/repo`."""
    version: str | None = Field(default=None, min_length=1)
    """The ref of the version the job is for; null for a job of the whole library."""
    commit_sha: str | None = Field(default=None, min_length=1)
    """The commit `version` is pinned to, if any."""
    ref_kind: RefKind | None = Field(default=None)
    """What `version` is."""
    origin: VersionOrigin = Field(default=VersionOrigin.MANUAL)
    """Given to the version by its first import: `auto` ones may be pruned."""


class GetJobQuery(_Dto):
    """Look up one job by its ID."""

    job_id: str = Field(min_length=1)
    """The job ID."""


class ListLibraryJobsQuery(_Dto):
    """One page of a library's jobs: ``limit`` items after the ``cursor`` of the previous page."""

    library: str = Field(min_length=1)
    """The library ID, `/owner/repo`."""
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    """How many jobs the page holds at most."""
    cursor: str | None = None
    """The `next_cursor` of the previous page; null for the first page."""


class GetLibraryAccessQuery(_Dto):
    """Ask whether a library needs a credential to be read from its repository."""

    library: str = Field(min_length=1)
    """The library ID, `/owner/repo`."""


class LibraryAccess(_Dto):
    """Whether the library's repository is private: it has a stored credential (token or key)."""

    private: bool
    """True when a token or deploy key is stored for the library."""


class AccessTokenIn(_Dto):
    """An HTTPS access token for a private repository. Write-only: no response repeats it."""

    kind: Literal["token"]
    """Always `token`."""
    token: SecretStr = Field(max_length=8192)
    """The token, on one line."""
    username: str | None = Field(default=None, max_length=100)
    """What the host expects next to the token; default `x-access-token` (GitHub, GitLab). Bitbucket
    repository tokens use `x-token-auth`.
    """

    def to_model(self) -> Credential:
        """Validate and convert to the domain value.

        Returns:
            The access token.
        """
        extra = {} if self.username is None else {"username": self.username}
        return AccessToken(token=self.token.get_secret_value(), **extra)


class DeployKeyIn(_Dto):
    """An SSH deploy key (private part, no passphrase). Write-only: no response repeats it."""

    kind: Literal["ssh_key"]
    """Always `ssh_key`."""
    private_key: SecretStr = Field(max_length=32768)
    """The private key as its file holds it, BEGIN and END lines included."""

    def to_model(self) -> Credential:
        """Validate and convert to the domain value.

        Returns:
            The deploy key.
        """
        return DeployKey(private_key=self.private_key.get_secret_value())


CredentialIn = Annotated[AccessTokenIn | DeployKeyIn, Field(discriminator="kind")]


class CheckRepositoryCommand(_Dto):
    """Ask whether a git URL works, before anything is saved."""

    url: str = Field(min_length=1, max_length=2048)
    """HTTPS, HTTP, SSH (`ssh://` or `git@host:org/repo.git`) or file URL, without credentials."""
    credential: CredentialIn | None = Field(default=None, description=_CREDENTIAL_DESCRIPTION)
    """A credential to try the URL with; its schema description is ``_CREDENTIAL_DESCRIPTION``."""


class CheckedRepository(_Dto):
    """A reachable git repository and what a new library from it would look like."""

    host: RepositoryHost
    """The hosting service, for source links."""
    library_id: str
    """The proposed `/owner/repo` library ID."""
    default_branch: str | None
    """The branch `HEAD` points at; null for an empty repository."""
    host_key_fingerprint: str | None = Field(default=None)
    """For an SSH URL, the `SHA256:...` fingerprint of the server's host key (first seen now, or
    pinned): compare it with the host's published one.
    """


class TagRuleIn(_Dto):
    """Articles whose path matches `pattern` (a glob like `docs/api/**`) get `tag`."""

    pattern: str = Field(min_length=1, max_length=256)
    """Glob over article paths, e.g. `docs/api/**`."""
    tag: str = Field(min_length=1, max_length=200)
    """The tag a matching article gets; normalized like every tag (lower-case, trimmed)."""


class AddLibraryCommand(_Dto):
    """Create a library from a git repository, with its doc selection, and queue its import."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description=CheckRepositoryCommand.model_fields["url"].description,
    )
    """The repository URL; its schema description is ``CheckRepositoryCommand.url``'s."""
    library_id: str | None = Field(default=None, min_length=1, max_length=200)
    """`/owner/repo`; omitted: the one proposed from the URL."""
    ref: str | None = Field(default=None, min_length=1, max_length=255)
    """A tag, a branch or a full or short commit SHA; omitted: the default branch."""
    include_paths: list[str] = Field(default_factory=list)
    """Folders, files or globs to import; empty: every `.md`/`.mdx` file."""
    exclude_paths: list[str] = Field(default_factory=list)
    """Folders, files or globs to leave out; they win."""
    tag_rules: list[TagRuleIn] = Field(default_factory=list, max_length=MAX_TAG_RULES)
    """Tags for articles by path; they are added to the front-matter tags."""
    credential: CredentialIn | None = Field(default=None, description=_CREDENTIAL_DESCRIPTION)
    """The library's credential; its schema description is ``_CREDENTIAL_DESCRIPTION``."""
    chunking: ChunkingIn | None = Field(default=None)
    """How articles are cut into chunks; stored before the import is queued. Null: the
    defaults.
    """
    context7_paths: bool | None = Field(default=None)
    """Without paths, take those of the repository's root `context7.json` (null or true); false:
    no paths mean every `.md`/`.mdx` file.
    """


class _PinnedImport(_Dto):
    """A ref pinned to its commit and the import queued for it."""

    library_id: str
    """The library ID, `/owner/repo`."""
    ref: str
    """The tag or branch name, or the full SHA of a commit."""
    ref_kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    commit_sha: str
    """The full SHA of the commit the ref was pinned to: what the import takes."""
    job_id: str
    """The queued import (`/jobs/{id}`)."""

    @classmethod
    def of(cls, library_id: str, resolved: ResolvedRef, job: JobSummary) -> Self:
        """Combine the pieces of a queued import.

        Args:
            library_id: The library ID.
            resolved: The ref and its commit.
            job: The queued import.

        Returns:
            The pinned import.
        """
        return cls(
            library_id=library_id,
            ref=resolved.name,
            ref_kind=resolved.kind,
            commit_sha=resolved.commit_sha,
            job_id=job.id,
        )


class PreviousVersionOut(_Dto):
    """An older tag the repository's `context7.json` offers for import."""

    tag: str
    """The tag, as git names it."""
    title: str
    """Its display title; empty when the file gives none."""


class Context7Out(_Dto):
    """What the repository's `context7.json` says (LIB-06). All of it is untrusted text.

    `include_paths` / `exclude_paths` are its folders and excludes as ExactDocs patterns: what a
    library added without paths imports.
    """

    project_title: str | None
    """Its `projectTitle`; null when it has none."""
    description: str | None
    """Its `description`; null when it has none."""
    folders: list[str]
    """Its `folders`: the folders to import."""
    exclude_folders: list[str]
    """Its `excludeFolders`."""
    exclude_files: list[str]
    """Its `excludeFiles`."""
    include_paths: list[str]
    """`folders` as ExactDocs include patterns."""
    exclude_paths: list[str]
    """`excludeFolders` and `excludeFiles` as ExactDocs exclude patterns."""
    rules: list[str]
    """Shown to agents with every `query-docs` answer."""
    previous_versions: list[PreviousVersionOut]
    """Older tags to offer for import (`POST .../versions` each)."""
    notes: list[str] = Field(default_factory=list)
    """What was left out of the file (a `previousVersions` entry whose tag git would not take), and
    why.
    """

    @classmethod
    def from_model(cls, config: Context7Config) -> Self:
        """Map a parsed file.

        Args:
            config: The parsed ``context7.json``.

        Returns:
            The file at the boundary.
        """
        selection = config.selection
        return cls(
            project_title=config.project_title,
            description=config.description,
            folders=list(config.folders),
            exclude_folders=list(config.exclude_folders),
            exclude_files=list(config.exclude_files),
            include_paths=list(selection.include) if selection else [],
            exclude_paths=list(selection.exclude) if selection else [],
            rules=list(config.rules),
            previous_versions=[
                PreviousVersionOut(tag=v.tag, title=v.title) for v in config.previous_versions
            ],
            notes=list(config.notes),
        )


class AddedLibrary(_PinnedImport):
    """The new library, the commit its ref was pinned to, and the queued import."""

    include_paths: list[str] = Field(default_factory=list)
    """The library's paths: the ones sent, else those of `context7.json`."""
    exclude_paths: list[str] = Field(default_factory=list)
    """The library's exclusions: the ones sent, else those of `context7.json`."""
    context7: Context7Out | None = Field(default=None, description=_CONTEXT7)
    """The repository's `context7.json`; its schema description is ``_CONTEXT7``."""
    context7_warning: str | None = Field(default=None, description=_CONTEXT7_WARNING)
    """Why `context7.json` is ignored; its schema description is ``_CONTEXT7_WARNING``."""


class AddVersionBody(_Dto):
    """The request body of adding a version; the library is in the path."""

    ref: str = Field(min_length=1, max_length=255)
    """A tag, a branch or a full or short commit SHA."""
    credential: CredentialIn | None = Field(
        default=None,
        description=_CREDENTIAL_DESCRIPTION + " Replaces the library's stored credential; "
        "needed again when it answers `credentials_required`.",
    )
    """A credential for the version's import; its schema description is built from
    ``_CREDENTIAL_DESCRIPTION``.
    """


class AddVersionCommand(AddVersionBody):
    """Import another version of an existing library, with the library's own settings."""

    library: str = Field(min_length=1, max_length=200)
    """The canonical `/owner/repo`."""


class AddedVersion(_PinnedImport):
    """The existing library, the commit the new version's ref was pinned to, and its import."""


class ReimportVersionBody(_Dto):
    """The request body of re-importing a version; the library is in the path."""

    ref: str = Field(min_length=1, max_length=255)
    """The tag version to re-import, e.g. `v1.4.0`."""


class ReimportVersionCommand(ReimportVersionBody):
    """Re-import a tag version that moved upstream, at the commit the tag names now."""

    library: str = Field(min_length=1, max_length=200)
    """The canonical `/owner/repo`."""


class ReimportedVersion(_Dto):
    """The tag version whose re-import is queued, and the commits it moves between."""

    library_id: str
    """The library ID, `/owner/repo`."""
    ref: str
    """The tag."""
    ref_kind: RefKind
    """Always `tag`: only a tag version is re-imported."""
    previous_commit_sha: str
    """The commit the version served until now."""
    commit_sha: str
    """The commit the tag names now, which the import takes."""
    job_id: str
    """The queued import (`/jobs/{id}`)."""


class ListRepositoryRefsQuery(_Dto):
    """Ask a repository for its tags and branches (a private one with a credential)."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description=CheckRepositoryCommand.model_fields["url"].description,
    )
    """The repository URL; its schema description is ``CheckRepositoryCommand.url``'s."""
    credential: CredentialIn | None = Field(default=None, description=_CREDENTIAL_DESCRIPTION)
    """The credential of a private repository; it is used for this call only, never stored."""


class RefOut(_Dto):
    """A tag or branch and the commit it points at."""

    name: str
    """The tag or branch name, without `refs/tags/` or `refs/heads/`."""
    commit_sha: str
    """The full SHA of the commit it points at; for an annotated tag, the tagged commit."""


class RepositoryRefs(_Dto):
    """What a repository offers as a ref, for the picker: its branches and its tags, by name."""

    default_branch: str | None
    """The branch `HEAD` points at; null when the repository has none."""
    branches: list[RefOut]
    """The branches, sorted by name."""
    tags: list[RefOut]
    """The tags, sorted by name."""
    truncated: bool = Field(description=REFS_TRUNCATED_DESCRIPTION)
    """Whether a list was cut; its schema description is ``REFS_TRUNCATED_DESCRIPTION``."""


class PreviewRepositoryCommand(_Dto):
    """Ask which files an import would take (a dry run: nothing is fetched beyond the tree)."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description=CheckRepositoryCommand.model_fields["url"].description,
    )
    """The repository URL; its schema description is ``CheckRepositoryCommand.url``'s."""
    ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description=AddLibraryCommand.model_fields["ref"].description,
    )
    """The ref to preview; its schema description is ``AddLibraryCommand.ref``'s."""
    include_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["include_paths"].description,
    )
    """The paths to import; its schema description is ``AddLibraryCommand.include_paths``'."""
    exclude_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["exclude_paths"].description,
    )
    """The paths to leave out; its schema description is ``AddLibraryCommand.exclude_paths``'."""
    credential: CredentialIn | None = Field(default=None, description=_CREDENTIAL_DESCRIPTION)
    """A credential for this preview only; its schema description is ``_CREDENTIAL_DESCRIPTION``."""


class RepositoryPreview(_Dto):
    """The articles an import would take: the first ones, and how many there are in all."""

    ref: str
    """The tag or branch name, or the full SHA of a commit."""
    ref_kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    commit_sha: str
    """The full SHA of the commit the ref names now: the tree that was listed."""
    files: list[str] = Field(description=PREVIEW_FILES_DESCRIPTION)
    """The first matching paths; its schema description is ``PREVIEW_FILES_DESCRIPTION``."""
    total: int
    """How many files match, also those not listed."""
    truncated: bool
    """True when `files` is cut (`total` is more than listed)."""
    include_paths: list[str] = Field(default_factory=list)
    """The paths applied: the ones sent, else those of `context7.json`."""
    exclude_paths: list[str] = Field(default_factory=list)
    """The exclusions applied: the ones sent, else those of `context7.json`."""
    context7: Context7Out | None = Field(default=None, description=_CONTEXT7)
    """The repository's `context7.json`; its schema description is ``_CONTEXT7``."""
    context7_warning: str | None = Field(default=None, description=_CONTEXT7_WARNING)
    """Why `context7.json` is ignored; its schema description is ``_CONTEXT7_WARNING``."""


class RemoveVersionCommand(_Dto):
    """Remove one version of a library everywhere and free its content."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""
    ref: str = Field(min_length=1)
    """The version's ref, as imported (case-sensitive)."""


class RemoveLibraryCommand(_Dto):
    """Remove a library, with all its versions, everywhere and free its content."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""


class ManualTagsIn(_Dto):
    """The tags to set by hand on an article path; they replace its earlier manual tags."""

    tags: list[Annotated[str, Field(max_length=MAX_TAG_INPUT)]] = Field(max_length=MAX_TAGS)
    """Normalized like every tag (lower-case, trimmed, deduplicated). Empty removes them."""


class TagArticleCommand(ManualTagsIn):
    """Set the manual tags of `path` for every version of `library`."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""
    path: str = Field(min_length=1, max_length=MAX_PATH)
    """The article's repository path, e.g. `docs/install.md`."""


class TaggedArticle(_Dto):
    """The manual tags of a path as stored: every version's article at that path carries them.

    So does, in a later version, the article git saw it renamed to.
    """

    library: str
    """The library ID, `/owner/repo`."""
    path: str
    """The article's repository path."""
    tags: list[str]
    """The path's manual tags, normalized; empty when it has none."""


class RemovalResult(_Dto):
    """A removal is done for readers when this is returned; the disk is freed by a job."""

    library: str
    """The library ID, `/owner/repo`."""
    ref: str | None
    """The removed version; null when a library was removed."""
    default_version: str | None
    """What `/owner/repo` means now; null when no version is left."""
    collection_job_id: str | None
    """The job that frees the content (`/jobs/{id}`); null if it was not queued."""


class SyncLibraryCommand(_Dto):
    """Re-sync the branch versions of a library (only those named in `refs`, when given)."""

    library: str = Field(min_length=1, max_length=200)
    """The canonical `/owner/repo`."""
    refs: tuple[str, ...] | None = None
    """Only the versions of these refs are checked (a push names one); null checks every one."""


class SyncedVersion(_Dto):
    """What the re-sync did with one version of the library."""

    ref: str
    """The version's ref."""
    ref_kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    status: SyncStatus
    """`queued`, `up_to_date`, `importing`, `pinned` or `failed`; see each value."""
    previous_commit_sha: str
    """The commit the version served before."""
    commit_sha: str
    """The branch tip now; for a tag or a commit, the commit it is pinned to."""
    job_id: str | None
    """The queued import; the import already in progress (`importing`); the failed job that records
    why the version could not be synced (`failed`); or the no-op job that cleared an earlier
    failure.
    """
    error_code: str | None = Field(default=None)
    """Why a `failed` version could not be synced: `ref_deleted` (the branch or tag is gone
    upstream), `tag_moved` (the tag names another commit now; it is re-imported only when
    confirmed, with `versions/reimport`) or `unexpected` (its import could not be queued); null
    otherwise.
    """
    error: str | None = Field(default=None)
    """The reason of a `failed` version, for people; null otherwise."""


class SyncedLibrary(_Dto):
    """The outcome per version; ``queued`` ones have an import to poll by ``job_id``."""

    library_id: str
    """The library ID, `/owner/repo`."""
    versions: list[SyncedVersion]
    """Every version of the library."""


class ChunkingIn(_Dto):
    """How a library's articles are cut into chunks (the defaults: one chunk per heading)."""

    split_level: int = Field(default=MAX_HEADING_LEVEL, ge=1, le=MAX_HEADING_LEVEL)
    """The deepest heading that starts a chunk: 2 cuts at `#` and `##` only."""
    min_chars: int = Field(default=0, ge=0, le=MAX_CHUNK_CHARS)
    """A chunk shorter than this is merged with the next one (the last with the one before), within
    `max_chars`; the text before the first heading is never merged. At most 8,000 when sent: no
    chunk is longer.
    """
    max_chars: int | None = Field(default=None, ge=1, le=MAX_CHUNK_CHARS)
    """A chunk longer than this is cut again at its deeper headings; never inside a code block or
    table. Null: no bound. At least `min_chars`, and at most 8,000 when sent: whatever the
    settings, a section longer than 8,000 characters is split between its top-level blocks.
    """
    chunker: Literal["markdown"] = Field(default=DEFAULT_CHUNKER)
    """`markdown`: cuts at headings with markdown-it-py (the only one supported)."""

    @classmethod
    def of(cls, config: ChunkingConfig) -> Self:
        """Map the domain value object.

        Args:
            config: The library's chunking settings.

        Returns:
            The settings at the boundary.
        """
        return cls.model_validate(
            {
                "split_level": config.split_depth,
                "min_chars": config.min_chars,
                "max_chars": config.max_chars,
                "chunker": config.chunker,
            }
        )


class AutoSyncIn(_Dto):
    """How a library is checked on its own; the whole set (what is left out takes its default)."""

    tag_pattern: str | None = Field(default=None, min_length=1, max_length=MAX_TAG_PATTERN)
    """A glob over tag names (`v*`, `release-1.*`), case-sensitive: matching tags with a version
    order become `auto` versions. Null imports no tag.
    """
    keep_last: Annotated[int, Field(ge=1, le=MAX_KEEP_LAST)] = Field(default=DEFAULT_KEEP_LAST)
    """How many `auto` versions are kept, the newest; older ones are removed."""
    interval_minutes: Annotated[int, Field(ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)] = (
        Field(default=DEFAULT_INTERVAL_MINUTES)
    )
    """How often the library is checked."""
    sync_branches: bool = Field(default=False)
    """Re-sync every branch version at each check."""


class SetAutoSyncCommand(AutoSyncIn):
    """Turn a library's scheduled check on, or change it; it runs at the next tick."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""


class GetAutoSyncQuery(_Dto):
    """Read a library's scheduled check."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""


class DisableAutoSyncCommand(_Dto):
    """Turn a library's scheduled check off; its versions stay as they are."""

    library: str = Field(min_length=1)
    """`/owner/repo`, any letter case."""


class AutoSyncOut(_Dto):
    """A library's scheduled check, and how the last one went."""

    library: str
    """The library ID, `/owner/repo`."""
    enabled: bool
    """False when the library is never checked on its own."""
    tag_pattern: str | None
    """The glob over tag names whose matching tags become `auto` versions; null imports no tag."""
    keep_last: int
    """How many `auto` versions are kept, the newest."""
    interval_minutes: int
    """How often the library is checked."""
    sync_branches: bool
    """Whether every branch version is re-synced at each check."""
    checked_at: datetime | None
    """When the last check ended."""
    next_check_at: datetime | None
    """When the library is due again; null while enabled: at the next tick."""
    last_error: str | None
    """What the last check could not do, for people."""

    @classmethod
    def from_model(cls, auto_sync: AutoSync) -> Self:
        """Map a domain value (an enabled check).

        Args:
            auto_sync: The library's schedule.

        Returns:
            The schedule at the boundary.
        """
        return cls(
            library=auto_sync.library,
            enabled=True,
            tag_pattern=auto_sync.tag_pattern,
            keep_last=auto_sync.keep_last,
            interval_minutes=auto_sync.interval_minutes,
            sync_branches=auto_sync.sync_branches,
            checked_at=auto_sync.checked_at,
            next_check_at=auto_sync.next_check_at,
            last_error=auto_sync.last_error,
        )

    @classmethod
    def disabled(cls, library: str) -> Self:
        """Describe a library that is never checked on its own.

        Args:
            library: The library ID.

        Returns:
            A disabled schedule with the default settings.
        """
        return cls.from_model(AutoSync(library=library)).model_copy(
            update={"enabled": False, "next_check_at": None}
        )


class ScheduledChecks(_Dto):
    """What one tick of the schedule did."""

    checked: list[str]
    """The libraries that were due and were checked."""
    imports: list[str]
    """IDs of the `auto` import jobs queued."""
    removed: list[str]
    """The `auto` versions removed, `/owner/repo/ref`."""


class LibrarySettingsIn(_Dto):
    """A library's paths and tag rules, as a whole (what is left out is cleared), and chunking.

    Chunking left out (or null) keeps what is stored, so a client that edits only paths and tag
    rules never resets it.
    """

    include_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["include_paths"].description,
    )
    """The paths to import; its schema description is ``AddLibraryCommand.include_paths``'."""
    exclude_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["exclude_paths"].description,
    )
    """The paths to leave out; its schema description is ``AddLibraryCommand.exclude_paths``'."""
    tag_rules: list[TagRuleIn] = Field(
        default_factory=list,
        max_length=MAX_TAG_RULES,
        description=AddLibraryCommand.model_fields["tag_rules"].description,
    )
    """Tags for articles by path; its schema description is ``AddLibraryCommand.tag_rules``'."""
    chunking: ChunkingIn | None = Field(default=None)
    """Left out or null: the stored chunking is kept (unlike paths and tag rules)."""


class UpdateLibrarySettingsCommand(LibrarySettingsIn):
    """Replace a library's paths and tag rules and re-process every version with them."""

    library: str = Field(min_length=1, max_length=200)
    """`/owner/repo`, any case."""


class UpdatedLibrarySettings(_Dto):
    """The settings as stored (normalized) and the job that brings every version in line."""

    library_id: str
    """The library ID, `/owner/repo`."""
    include_paths: list[str]
    """The paths to import, as stored."""
    exclude_paths: list[str]
    """The paths to leave out, as stored."""
    tag_rules: list[TagRuleIn]
    """The tag rules, as stored (tags normalized, duplicates dropped)."""
    chunking: ChunkingIn
    """The chunking, as stored."""
    reprocess: SettingsChange | None
    """`paths`: the selection changed, every version is fetched again at its commit; `chunking`: the
    chunking changed (perhaps the tag rules too), every version is re-chunked and re-tagged from
    what is stored; `tags`: only tag rules changed, every version is re-tagged from what is
    stored; null: nothing changed and nothing is re-run, nothing is re-processed.
    """
    job_id: str | None
    """The job re-processing every version (`/jobs/{id}`); one already queued for the library is
    reused. Unchanged settings re-run the library's last re-processing job when it failed. Null
    when nothing is to do or the library has no versions yet.
    """
    versions: list[str]
    """The library's refs now, at the commits they serve: what the job re-processes (it reads the
    versions again when it runs). Listed also when a queued job is reused.
    """


class QueueEmbeddingCommand(_Dto):
    """Queue an ``embed`` job for every version the embedding model has not fully embedded."""

    library: str | None = Field(default=None, min_length=1)
    """Only this library's versions; every library's when null."""


class QueuedEmbedding(_Dto):
    """How many ``embed`` jobs were queued."""

    queued: int
    """Jobs queued now."""


# ---------------------------------------------------------------- the sources file (TEAM-02)

_SourceRef = Annotated[str, Field(min_length=1, max_length=MAX_SOURCE_REF)]


def _source_ref(ref: str) -> str:
    """Check one declared ref; a full commit SHA is spelled lower-case, as versions are.

    Args:
        ref: The ref as declared.

    Returns:
        The ref to compare with versions.

    Raises:
        ValueError: It is blank, has spaces or control characters, or is a short commit SHA.
    """
    if not ref.strip() or any(c.isspace() or not c.isprintable() for c in ref):
        message = "a ref has no spaces or control characters"
        raise ValueError(message)
    if FULL_SHA.fullmatch(ref):
        return ref.lower()
    if SHORT_SHA.fullmatch(ref):
        message = (
            f"{ref!r} looks like a short commit SHA: "
            "declare the full SHA (40 hex characters, 64 for SHA-256)"
        )
        raise ValueError(message)
    return ref


class SourceLibrary(_Dto):
    """One library of a sources file. A setting left out is not managed: never compared or changed.

    `include_paths`, `exclude_paths` and `tag_rules` are compared as sets, after the server's
    normalization (a reordered list or a tag in other letter case is no change).
    """

    url: str = Field(
        min_length=1,
        max_length=2048,
        description=CheckRepositoryCommand.model_fields["url"].description,
    )
    """The repository URL; its schema description is ``CheckRepositoryCommand.url``'s."""
    id: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"
    )
    """`/owner/repo`, any letter case; left out: the ID derived from `url`, as when a library is
    added.
    """
    refs: list[_SourceRef] = Field(min_length=1, max_length=MAX_SOURCE_REFS)
    """The versions to have: tags, branches or full commit SHAs (40 hex characters, or 64 in
    a SHA-256 repository; a short SHA is refused). The first one is imported when the library
    is created.
    """
    include_paths: list[str] | None = Field(default=None)
    """Folders, files or globs to import; empty: every `.md`/`.mdx` file (the repository's
    `context7.json` does not fill in a managed empty list). Left out: not managed.
    """
    exclude_paths: list[str] | None = Field(default=None)
    """Folders, files or globs to leave out; they win. Left out: not managed."""
    tag_rules: list[TagRuleIn] | None = Field(default=None, max_length=MAX_TAG_RULES)
    """Tags for articles by path, as a whole set. Left out: not managed."""
    chunking: ChunkingIn | None = Field(default=None)
    """How articles are cut into chunks. Left out: not managed."""
    auto_sync: AutoSyncIn | Literal[False] | None = Field(default=None)
    """The scheduled check, as a whole (what it leaves out takes its default); `false` turns it
    off. Left out: not managed.
    """

    @field_validator("refs")
    @classmethod
    def _refs(cls, refs: list[str]) -> list[str]:
        """Check each ref and refuse one declared twice.

        Args:
            refs: The refs as declared.

        Returns:
            The refs, full SHAs lower-case.

        Raises:
            ValueError: A ref is malformed or declared twice.
        """
        checked = [_source_ref(r) for r in refs]
        if len(set(checked)) != len(checked):
            message = "a ref is declared twice"
            raise ValueError(message)
        return checked

    def library_id(self) -> str | None:
        """Return the canonical library ID: `id`, else the one derived from `url`.

        Returns:
            The lower-case ID, or None when `url` gives none (plan reports that entry).
        """
        if self.id is not None:
            return self.id.lower()
        try:
            return RepositoryUrl.parse(self.url).library_id.lower()
        except InvalidRepositoryUrlError:
            return None


class SourcesFile(_Dto):
    """`exactdocs.sources.yaml`: the libraries an instance should have, for code review.

    It holds no credential: a private library is added in the UI with its credential first,
    then managed by the file.
    """

    version: Literal[1]
    """The file format's version: 1."""
    libraries: list[SourceLibrary] = Field(default_factory=list, max_length=MAX_SOURCES)
    """The declared libraries, each ID once."""

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        """Refuse two entries for one library ID (any letter case).

        Returns:
            The file.

        Raises:
            ValueError: An ID is declared twice.
        """
        seen: set[str] = set()
        for entry in self.libraries:
            library_id = entry.library_id()
            if library_id is None:
                continue
            if library_id in seen:
                message = f"library {library_id!r} is declared twice"
                raise ValueError(message)
            seen.add(library_id)
        return self


def sources_json_schema() -> dict[str, object]:
    """Return the JSON Schema of ``SourcesFile``: what is committed and served.

    Returns:
        The schema, with its dialect and title.
    """
    return {
        "$schema": SOURCES_SCHEMA_DIALECT,
        **SourcesFile.model_json_schema(),
        "title": SOURCES_SCHEMA_TITLE,
    }


class PlanSourcesCommand(_Dto):
    """Compare a sources file with the instance; nothing is changed."""

    sources: SourcesFile
    """The file, as JSON (the server never parses YAML)."""
    prune: bool = Field(default=False)
    """Mark undeclared libraries and `manual` versions as removed by apply."""


class ApplySourcesCommand(PlanSourcesCommand):
    """Plan again, then apply the plan library by library; only `prune` removes anything."""


class PathsChange(_Dto):
    """A managed path list as stored and as declared."""

    before: list[str]
    """As stored."""
    after: list[str]
    """As declared, normalized."""


class TagRulesChange(_Dto):
    """The managed tag rules as stored and as declared."""

    before: list[TagRuleIn]
    """As stored."""
    after: list[TagRuleIn]
    """As declared, normalized."""


class ChunkingChange(_Dto):
    """The managed chunking as stored and as declared."""

    before: ChunkingIn
    """As stored."""
    after: ChunkingIn
    """As declared."""


class AutoSyncChange(_Dto):
    """The managed scheduled check as it is and as declared; null is off."""

    before: AutoSyncIn | None
    """As it is; null: off."""
    after: AutoSyncIn | None
    """As declared; null: off."""


class LibraryUpdateOut(_Dto):
    """What apply changes in an existing library; null or empty: nothing of that kind."""

    library_id: str
    """The library ID, `/owner/repo`."""
    include_paths: PathsChange | None
    """The include paths, when they change."""
    exclude_paths: PathsChange | None
    """The exclude paths, when they change."""
    tag_rules: TagRulesChange | None
    """The tag rules, when they change."""
    chunking: ChunkingChange | None
    """The chunking, when it changes."""
    refs_to_add: list[str]
    """Declared refs that are neither versions nor being imported: each queues an import."""
    auto_sync: AutoSyncChange | None
    """The scheduled check, when it is turned on, off or changed."""
    job_kind: str | None
    """The job the settings change queues: `reprocess`, `rechunk` or `retag`; null: none."""
    undeclared_versions: list[str]
    """`manual` versions the file does not declare (`auto` ones belong to the schedule)."""
    remove_undeclared_versions: bool
    """True with `prune`: apply removes `undeclared_versions`."""

    @classmethod
    def from_model(cls, update: LibraryUpdate) -> Self:
        """Map one library's difference.

        Args:
            update: The difference.

        Returns:
            It at the boundary.
        """
        declared, source = update.declared, update.current.source
        changed = set(update.changed)

        def paths(
            name: SourcesField, before: tuple[str, ...], after: tuple[str, ...] | None
        ) -> PathsChange | None:
            """Describe one path list when it changes.

            Args:
                name: Which list.
                before: As stored.
                after: As declared.

            Returns:
                The change, or None.
            """
            if name not in changed or after is None:
                return None
            return PathsChange(before=list(before), after=list(after))

        return cls(
            library_id=update.library_id,
            include_paths=paths(
                SourcesField.INCLUDE_PATHS, source.selection.include, declared.include
            ),
            exclude_paths=paths(
                SourcesField.EXCLUDE_PATHS, source.selection.exclude, declared.exclude
            ),
            tag_rules=TagRulesChange(
                before=_rules_out(source.tag_rules), after=_rules_out(declared.tag_rules)
            )
            if SourcesField.TAG_RULES in changed and declared.tag_rules is not None
            else None,
            chunking=ChunkingChange(
                before=ChunkingIn.of(source.chunking), after=ChunkingIn.of(declared.chunking)
            )
            if SourcesField.CHUNKING in changed and declared.chunking is not None
            else None,
            refs_to_add=list(update.refs_to_add),
            auto_sync=AutoSyncChange(
                before=_schedule_out(update.current.auto_sync),
                after=_schedule_out(declared.auto_sync),
            )
            if update.auto_sync_changes
            else None,
            job_kind=None if update.reprocess is None else CHANGE_JOBS[update.reprocess],
            undeclared_versions=list(update.undeclared_versions),
            remove_undeclared_versions=update.prune and bool(update.undeclared_versions),
        )


def _rules_out(rules: Sequence[TagRule]) -> list[TagRuleIn]:
    """Map tag rules to the boundary.

    Args:
        rules: The rules.

    Returns:
        The rules at the boundary.
    """
    return [TagRuleIn(pattern=r.pattern, tag=r.tag) for r in rules]


def _schedule_out(auto_sync: AutoSync | None) -> AutoSyncIn | None:
    """Map a schedule's settings to the boundary.

    Args:
        auto_sync: The schedule; None: off.

    Returns:
        Its settings, or None.
    """
    if auto_sync is None:
        return None
    return AutoSyncIn(
        tag_pattern=auto_sync.tag_pattern,
        keep_last=auto_sync.keep_last,
        interval_minutes=auto_sync.interval_minutes,
        sync_branches=auto_sync.sync_branches,
    )


def declared_out(declared: DeclaredLibrary) -> SourceLibrary:
    """Map a declared library (normalized) back to a file entry, with its ID.

    Args:
        declared: The declaration.

    Returns:
        The entry, as plan lists it under `create`.
    """
    schedule: AutoSyncIn | Literal[False] | None = None
    if declared.manages_auto_sync:
        schedule = _schedule_out(declared.auto_sync) or False
    return SourceLibrary(
        url=declared.url.url,
        id=declared.library_id,
        refs=list(declared.refs),
        include_paths=None if declared.include is None else list(declared.include),
        exclude_paths=None if declared.exclude is None else list(declared.exclude),
        tag_rules=None if declared.tag_rules is None else _rules_out(declared.tag_rules),
        chunking=None if declared.chunking is None else ChunkingIn.of(declared.chunking),
        auto_sync=schedule,
    )


class UndeclaredLibraryOut(_Dto):
    """A library of the instance that the file does not declare."""

    library_id: str
    """The library ID, `/owner/repo`."""
    source_url: str
    """Its repository."""
    will_be_removed: bool
    """True with `prune`: apply removes it."""


class SourceErrorOut(_Dto):
    """A declared library that cannot be reconciled; apply leaves it alone."""

    library_id: str
    """The declared library ID."""
    error: str
    """A stable machine code: `source_mismatch` (the ID exists with another repository URL)."""
    detail: str
    """What is wrong, for people."""


class SourcesPlanOut(_Dto):
    """The difference between a sources file and the instance."""

    create: list[SourceLibrary]
    """Declared libraries that do not exist, normalized and with their ID."""
    update: list[LibraryUpdateOut]
    """Existing libraries that differ from their declaration, or have undeclared versions."""
    unchanged: list[str]
    """Existing libraries that match their declaration."""
    undeclared: list[UndeclaredLibraryOut]
    """Libraries the file does not declare."""
    errors: list[SourceErrorOut]
    """Declared libraries that cannot be reconciled."""
    prune: bool
    """Whether apply removes undeclared libraries and `manual` versions."""
    changes: bool
    """Whether apply would change anything (false: it calls no write)."""

    @classmethod
    def from_model(cls, plan: SourcesPlan) -> Self:
        """Map the plan.

        Args:
            plan: The plan.

        Returns:
            The plan at the boundary.
        """
        return cls(
            create=[declared_out(d) for d in plan.create],
            update=[LibraryUpdateOut.from_model(u) for u in plan.update],
            unchanged=list(plan.unchanged),
            undeclared=[
                UndeclaredLibraryOut(
                    library_id=c.library_id, source_url=c.source.url.url, will_be_removed=plan.prune
                )
                for c in plan.undeclared
            ],
            errors=[
                SourceErrorOut(library_id=e.library_id, error=e.code, detail=e.message)
                for e in plan.errors
            ],
            prune=plan.prune,
            changes=bool(
                plan.create
                or any(u.writes for u in plan.update)
                or (plan.prune and plan.undeclared)
            ),
        )


class LibraryOutcome(_Dto):
    """What apply did with one library."""

    library_id: str
    """The library ID, `/owner/repo`."""
    action: Literal["created", "updated", "unchanged", "removed", "failed"]
    """What was done; `failed`: nothing was (an error of the plan, or the first write failed)."""
    jobs: list[str]
    """The jobs queued (`/jobs/{id}`): imports, re-processing, the collection of removed content."""
    error_code: str | None = Field(default=None)
    """The stable code of what failed, e.g. `unknown_ref`; null when nothing did."""
    error: str | None = Field(default=None)
    """What failed, for people; a library created or updated before it stays so."""


class AppliedSources(_Dto):
    """The plan that was applied and what was done, library by library."""

    plan: SourcesPlanOut
    """The plan, computed again at apply time."""
    results: list[LibraryOutcome]
    """Created, then updated or unchanged, then removed libraries, then the plan's errors."""
    failed: int
    """How many libraries have an `error`."""


# ---------------------------------------------------------------- push webhooks (TEAM-03)


class WebhookQuery(_Dto):
    """Name the library whose webhook is read, set or turned off."""

    library: str = Field(min_length=1, max_length=200)
    """The library ID, `/owner/repo`."""


class WebhookOut(_Dto):
    """A library's push webhook: whether it is on and where forges send their pushes."""

    library: str
    """The library ID, `/owner/repo`."""
    enabled: bool
    """False when the library has no webhook secret: every delivery is refused."""
    url: str | None = None
    """Where a forge sends its pushes (`POST`); set by the HTTP API, null elsewhere."""
    created_at: datetime | None = None
    """When the secret was created or last rotated; null when off."""

    @classmethod
    def from_model(cls, webhook: Webhook) -> Self:
        """Describe a webhook that is on, without its secret.

        Args:
            webhook: The library's webhook.

        Returns:
            The webhook at the boundary.
        """
        return cls(library=webhook.library, enabled=True, created_at=webhook.created_at)

    @classmethod
    def disabled(cls, library: str) -> Self:
        """Describe a library without a webhook.

        Args:
            library: The library ID.

        Returns:
            The webhook, off.
        """
        return cls(library=library, enabled=False)


class WebhookCreated(WebhookOut):
    """A new or rotated webhook, with the secret: shown in this answer only, never again."""

    secret: str
    """The shared secret to paste into the forge's webhook settings (GitHub, Bitbucket: the
    secret; GitLab: the secret token). It replaces the previous one at once."""

    @classmethod
    def created(cls, webhook: Webhook) -> Self:
        """Describe the webhook with its secret.

        Args:
            webhook: The library's new webhook.

        Returns:
            The webhook and its secret.
        """
        return cls(
            library=webhook.library,
            enabled=True,
            created_at=webhook.created_at,
            secret=webhook.secret,
        )


class ReceiveWebhookCommand(_Dto):
    """A delivery from a forge, as received: verified before anything in it is read."""

    library: str = Field(min_length=1, max_length=200)
    """The library ID, `/owner/repo`, from the webhook's URL."""
    headers: dict[str, str]
    """The request's headers (names in any letter case)."""
    body: bytes
    """The raw body, exactly as received (the signature covers these bytes)."""


class WebhookReceipt(_Dto):
    """What ExactDocs did with a delivery; the sync itself runs later, as a job."""

    status: Literal["queued", "duplicate", "ignored"]
    """`queued`: a `push` job runs the sync (a push of the same ref already waiting counts);
    `duplicate`: this delivery was handled before; `ignored`: nothing it pushed is followed (an
    untracked branch, a tag without auto-import, a ping)."""
    job_ids: list[str] = []
    """The `push` jobs queued by this delivery (empty when they joined waiting ones)."""
