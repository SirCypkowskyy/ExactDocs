"""Data crossing the ingestion boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from exactdocs.ingestion.models import (
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_KEEP_LAST,
    MAX_INTERVAL_MINUTES,
    MAX_KEEP_LAST,
    MAX_TAG_PATTERN,
    MAX_TAG_RULES,
    MIN_INTERVAL_MINUTES,
    AccessToken,
    AutoSync,
    Context7Config,
    Credential,
    DeployKey,
    FileProblem,
    Job,
    JobState,
    ProblemCode,
    RefKind,
    RepositoryHost,
    ResolvedRef,
    SettingsChange,
    SyncStatus,
    VersionOrigin,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, MAX_PATH, MAX_TAG_INPUT, MAX_TAGS, Page


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


ERROR_CODE = (
    "The stable code of `error`, null unless the job failed (or failed before codes were "
    "recorded). An upstream problem is `repo_unreachable` (the repository was deleted, made "
    "private, moved, or cannot be reached), `auth_failed` (the credential was refused or cannot "
    "be read), `ref_deleted` (the branch or tag is gone) or `tag_moved` (the tag points "
    "elsewhere now); otherwise the error's own code (`no_articles`, `host_key_changed`...) or "
    "`unexpected`."
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
    error_code: str | None = Field(description=ERROR_CODE)
    origin: VersionOrigin = Field(
        default=VersionOrigin.MANUAL,
        description="`auto` when the scheduled check queued it, `manual` otherwise.",
    )
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
            error_code=job.error_code,
            origin=job.origin,
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
    error_code: str | None = Field(description=ERROR_CODE)
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
            error_code=job.error_code,
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
    origin: VersionOrigin = Field(
        default=VersionOrigin.MANUAL,
        description="Given to the version by its first import: `auto` ones may be pruned.",
    )


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


class _PinnedImport(_Dto):
    """A ref pinned to its commit and the import queued for it."""

    library_id: str
    ref: str = Field(description="The tag or branch name, or the full SHA of a commit.")
    ref_kind: RefKind
    commit_sha: str
    job_id: str

    @classmethod
    def of(cls, library_id: str, resolved: ResolvedRef, job: JobSummary) -> Self:
        """Combine the pieces of a queued import."""
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
    title: str = Field(description="Its display title; empty when the file gives none.")


class Context7Out(_Dto):
    """What the repository's `context7.json` says (LIB-06). All of it is untrusted text.

    `include_paths` / `exclude_paths` are its folders and excludes as ExactDocs patterns: what a
    library added without paths imports.
    """

    project_title: str | None
    description: str | None
    folders: list[str]
    exclude_folders: list[str]
    exclude_files: list[str]
    include_paths: list[str]
    exclude_paths: list[str]
    rules: list[str] = Field(description="Shown to agents with every `query-docs` answer.")
    previous_versions: list[PreviousVersionOut] = Field(
        description="Older tags to offer for import (`POST .../versions` each)."
    )
    notes: list[str] = Field(
        default_factory=list,
        description="What was left out of the file (a `previousVersions` entry whose tag git "
        "would not take), and why.",
    )

    @classmethod
    def from_model(cls, config: Context7Config) -> Self:
        """Map a parsed file."""
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


_CONTEXT7 = (
    "The repository's root `context7.json` at that commit; null when there is none or it is "
    "ignored (see `context7_warning`)."
)
_CONTEXT7_WARNING = "Why the `context7.json` at that commit is ignored; null when it is not."


class AddedLibrary(_PinnedImport):
    """The new library, the commit its ref was pinned to, and the queued import."""

    include_paths: list[str] = Field(
        default_factory=list,
        description="The library's paths: the ones sent, else those of `context7.json`.",
    )
    exclude_paths: list[str] = Field(default_factory=list)
    context7: Context7Out | None = Field(default=None, description=_CONTEXT7)
    context7_warning: str | None = Field(default=None, description=_CONTEXT7_WARNING)


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


class AddedVersion(_PinnedImport):
    """The existing library, the commit the new version's ref was pinned to, and its import."""


class ReimportVersionBody(_Dto):
    """The request body of re-importing a version; the library is in the path."""

    ref: str = Field(
        min_length=1, max_length=255, description="The tag version to re-import, e.g. `v1.4.0`."
    )


class ReimportVersionCommand(ReimportVersionBody):
    """Re-import a tag version that moved upstream, at the commit the tag names now."""

    library: str = Field(min_length=1, max_length=200, description="The canonical `/owner/repo`.")


class ReimportedVersion(_Dto):
    """The tag version whose re-import is queued, and the commits it moves between."""

    library_id: str
    ref: str
    ref_kind: RefKind
    previous_commit_sha: str = Field(description="The commit the version served until now.")
    commit_sha: str = Field(description="The commit the tag names now, which the import takes.")
    job_id: str


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


class PreviewRepositoryCommand(_Dto):
    """Ask which files an import would take (a dry run: nothing is fetched beyond the tree)."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description=CheckRepositoryCommand.model_fields["url"].description,
    )
    ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description=AddLibraryCommand.model_fields["ref"].description,
    )
    include_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["include_paths"].description,
    )
    exclude_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["exclude_paths"].description,
    )
    credential: CredentialIn | None = Field(default=None, description=_CREDENTIAL_DESCRIPTION)


class RepositoryPreview(_Dto):
    """The articles an import would take: the first ones, and how many there are in all."""

    ref: str = Field(description="The tag or branch name, or the full SHA of a commit.")
    ref_kind: RefKind
    commit_sha: str
    files: list[str] = Field(
        description="Sorted repository-relative paths, at most 1000. Untrusted text: show it "
        "as text, never as markup or a link target."
    )
    total: int = Field(description="How many files match, also those not listed.")
    truncated: bool = Field(description="True when `files` is cut (`total` is more than listed).")
    include_paths: list[str] = Field(
        default_factory=list,
        description="The paths applied: the ones sent, else those of `context7.json`.",
    )
    exclude_paths: list[str] = Field(default_factory=list)
    context7: Context7Out | None = Field(default=None, description=_CONTEXT7)
    context7_warning: str | None = Field(default=None, description=_CONTEXT7_WARNING)


class RemoveVersionCommand(_Dto):
    """Remove one version of a library everywhere and free its content."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    ref: str = Field(min_length=1)


class RemoveLibraryCommand(_Dto):
    """Remove a library, with all its versions, everywhere and free its content."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")


class ManualTagsIn(_Dto):
    """The tags to set by hand on an article path; they replace its earlier manual tags."""

    tags: list[Annotated[str, Field(max_length=MAX_TAG_INPUT)]] = Field(
        max_length=MAX_TAGS,
        description=(
            "Normalized like every tag (lower-case, trimmed, deduplicated). Empty removes them."
        ),
    )


class TagArticleCommand(ManualTagsIn):
    """Set the manual tags of `path` for every version of `library`."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")
    path: str = Field(min_length=1, max_length=MAX_PATH)


class TaggedArticle(_Dto):
    """The manual tags of a path as stored: every version's article at that path carries them.

    So does, in a later version, the article git saw it renamed to.
    """

    library: str
    path: str
    tags: list[str]


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
            "that records why the version could not be synced (`failed`); or the no-op job "
            "that cleared an earlier failure."
        )
    )
    error_code: str | None = Field(
        default=None,
        description=(
            "Why a `failed` version could not be synced: `ref_deleted` (the branch or tag is "
            "gone upstream), `tag_moved` (the tag names another commit now; it is "
            "re-imported only when confirmed, with `versions/reimport`) or `unexpected` (its "
            "import could not be queued); null otherwise."
        ),
    )
    error: str | None = Field(
        default=None, description="The reason of a `failed` version, for people; null otherwise."
    )


class SyncedLibrary(_Dto):
    """The outcome per version; ``queued`` ones have an import to poll by ``job_id``."""

    library_id: str
    versions: list[SyncedVersion]


class AutoSyncIn(_Dto):
    """How a library is checked on its own; the whole set (what is left out takes its default)."""

    tag_pattern: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_TAG_PATTERN,
        description=(
            "A glob over tag names (`v*`, `release-1.*`), case-sensitive: matching tags with a "
            "version order become `auto` versions. Null imports no tag."
        ),
    )
    keep_last: Annotated[int, Field(ge=1, le=MAX_KEEP_LAST)] = Field(
        default=DEFAULT_KEEP_LAST,
        description="How many `auto` versions are kept, the newest; older ones are removed.",
    )
    interval_minutes: Annotated[int, Field(ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)] = (
        Field(default=DEFAULT_INTERVAL_MINUTES, description="How often the library is checked.")
    )
    sync_branches: bool = Field(
        default=False, description="Re-sync every branch version at each check."
    )


class SetAutoSyncCommand(AutoSyncIn):
    """Turn a library's scheduled check on, or change it; it runs at the next tick."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")


class GetAutoSyncQuery(_Dto):
    """Read a library's scheduled check."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")


class DisableAutoSyncCommand(_Dto):
    """Turn a library's scheduled check off; its versions stay as they are."""

    library: str = Field(min_length=1, description="`/owner/repo`, any letter case.")


class AutoSyncOut(_Dto):
    """A library's scheduled check, and how the last one went."""

    library: str
    enabled: bool = Field(description="False when the library is never checked on its own.")
    tag_pattern: str | None
    keep_last: int
    interval_minutes: int
    sync_branches: bool
    checked_at: datetime | None = Field(description="When the last check ended.")
    next_check_at: datetime | None = Field(
        description="When the library is due again; null while enabled: at the next tick."
    )
    last_error: str | None = Field(description="What the last check could not do, for people.")

    @classmethod
    def from_model(cls, auto_sync: AutoSync) -> Self:
        """Map a domain value (an enabled check)."""
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
        """Describe a library that is never checked on its own."""
        return cls.from_model(AutoSync(library=library)).model_copy(
            update={"enabled": False, "next_check_at": None}
        )


class ScheduledChecks(_Dto):
    """What one tick of the schedule did."""

    checked: list[str] = Field(description="The libraries that were due and were checked.")
    imports: list[str] = Field(description="IDs of the `auto` import jobs queued.")
    removed: list[str] = Field(description="The `auto` versions removed, `/owner/repo/ref`.")


class LibrarySettingsIn(_Dto):
    """A library's paths and tag rules, as a whole: what is left out is cleared."""

    include_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["include_paths"].description,
    )
    exclude_paths: list[str] = Field(
        default_factory=list,
        description=AddLibraryCommand.model_fields["exclude_paths"].description,
    )
    tag_rules: list[TagRuleIn] = Field(
        default_factory=list,
        max_length=MAX_TAG_RULES,
        description=AddLibraryCommand.model_fields["tag_rules"].description,
    )


class UpdateLibrarySettingsCommand(LibrarySettingsIn):
    """Replace a library's paths and tag rules and re-process every version with them."""

    library: str = Field(min_length=1, max_length=200, description="`/owner/repo`, any case.")


class UpdatedLibrarySettings(_Dto):
    """The settings as stored (normalized) and the job that brings every version in line."""

    library_id: str
    include_paths: list[str]
    exclude_paths: list[str]
    tag_rules: list[TagRuleIn]
    reprocess: SettingsChange | None = Field(
        description=(
            "`paths`: the selection changed, every version is fetched again at its commit; "
            "`tags`: only tag rules changed, every version is re-tagged from what is stored; "
            "null: nothing changed and nothing is re-run, nothing is re-processed."
        )
    )
    job_id: str | None = Field(
        description=(
            "The job re-processing every version (`/jobs/{id}`); one already queued for the "
            "library is reused. Unchanged settings re-run the library's last re-processing job "
            "when it failed. Null when nothing is to do or the library has no versions yet."
        )
    )
    versions: list[str] = Field(
        description=(
            "The library's refs now, at the commits they serve: what the job re-processes (it "
            "reads the versions again when it runs). Listed also when a queued job is reused."
        )
    )
