"""Ingestion errors. Messages never contain the URL a user typed: it may hold a credential."""

from collections.abc import Sequence
from enum import StrEnum

from exactdocs_kernel import BusyError, ConflictError, DomainError, NotFoundError, ValidationError


class UrlProblem(StrEnum):
    """Why a URL is refused. Fixed texts: none of them can repeat what the user typed."""

    EMPTY = "it is empty"
    OPTION = "it starts with '-' or contains spaces or control characters"
    FORM = "use https://, http://, ssh://, file:// or user@host:path"
    MALFORMED = "the URL is malformed"
    SCHEME = "the scheme must be https, http, ssh or file"
    QUERY = "a query or fragment is not part of a git URL"
    FILE_HOST = "a file URL has no host: file:///path/to/repo"
    HOST = "the host name is invalid"
    CREDENTIALS = "credentials in the URL are not accepted (they would be stored and shown)"
    DOTS = "the path must not contain '.' or '..'"
    NO_OWNER = "the path needs an owner and a repository name"
    PAGE_URL = "the path has more than owner/repository (is it a link to a page?)"
    NO_ID = "no library ID can be derived from the path"
    GIT_OPTION = "it would be read as a git option"


class InvalidRepositoryUrlError(ValidationError):
    """The text is not a git URL ExactDocs accepts."""

    code = "invalid_repository_url"

    def __init__(self, problem: UrlProblem) -> None:
        super().__init__(f"not a usable git URL: {problem.value}")


class InvalidChunkingConfigError(ValidationError):
    """The chunking settings are out of range."""

    code = "invalid_chunking_config"

    def __init__(self) -> None:
        super().__init__("split_depth must be between 1 and 6")


class NotAGitRepositoryError(ValidationError):
    """The address answers, but there is no git repository there (or none visible without login)."""

    code = "not_a_git_repository"

    def __init__(self) -> None:
        super().__init__(
            "no git repository was found at that address (a private repository can look the same)"
        )


class RepositoryUnreachableError(ValidationError):
    """The repository could not be contacted (DNS, connection, TLS, timeout...)."""

    code = "repository_unreachable"

    def __init__(self, reason: str) -> None:
        super().__init__(f"the repository is unreachable: {reason}")


class RepositoryAuthRequiredError(ValidationError):
    """The server wants credentials (a private repository, or one that is hidden without them)."""

    code = "repository_auth_required"

    def __init__(self) -> None:
        super().__init__("the repository requires authentication")


class CredentialProblem(StrEnum):
    """Why a credential is refused. Fixed texts: none of them can repeat the secret."""

    EMPTY = "the token or key is empty"
    ONE_LINE = "a token is one line of at most 4096 printable characters"
    USERNAME = "a token's user name is letters, digits, '.', '_' and '-' (at most 100)"
    KEY = "a deploy key is an unencrypted private key in OpenSSH or PEM format"
    TOO_LONG = "the deploy key is too long"
    HTTPS_ONLY = "an access token goes with an https:// URL (http:// only for localhost)"
    SSH_ONLY = "a deploy key goes with an ssh:// or user@host:path URL"


class InvalidCredentialError(ValidationError):
    """The credential cannot be used with this repository."""

    code = "invalid_credential"

    def __init__(self, problem: CredentialProblem) -> None:
        super().__init__(f"not a usable credential: {problem.value}")


class CredentialsRequiredError(ValidationError):
    """The library's stored credentials cannot be read (the secret key changed): send them again."""

    code = "credentials_required"

    def __init__(self) -> None:
        super().__init__(
            "the stored credentials of this library cannot be read with the current secret key: "
            "send the token or deploy key again"
        )


class HostKeyChangedError(ValidationError):
    """The SSH server's host key is not the one remembered for it: possibly a man in the middle."""

    code = "host_key_changed"

    def __init__(self) -> None:
        super().__init__(
            "the SSH host key of the server changed since it was first seen: refusing to "
            "connect (if it was rotated on purpose, remove the host from the known_hosts file)"
        )


class CommitUnavailableError(ValidationError):
    """The repository no longer serves the commit a version is pinned to (a force-pushed branch)."""

    code = "commit_unavailable"

    def __init__(self) -> None:
        super().__init__("the repository does not serve the pinned commit any more")


class RepositoryTooLargeError(ValidationError):
    """What a fetch brought in is bigger than ExactDocs accepts."""

    code = "repository_too_large"

    def __init__(self, limit: int) -> None:
        super().__init__(f"the selected files are larger than {limit // 2**20} MiB")


class TreeTooLargeError(ValidationError):
    """The commit has more files than a preview can list (same code as ``RepositoryTooLarge``)."""

    code = "repository_too_large"

    def __init__(self) -> None:
        super().__init__("the repository has too many files to preview")


class PreviewBusyError(BusyError):
    """Every preview slot is taken: the caller may try again in a moment."""

    code = "preview_busy"

    def __init__(self, *, retry_after: int = 5) -> None:
        super().__init__(
            "too many previews are running; try again in a moment", retry_after=retry_after
        )


class LibraryIdTakenError(ConflictError):
    """Another library already uses the ID this repository would get."""

    code = "library_id_taken"

    def __init__(self, library_id: str) -> None:
        super().__init__(f"library {library_id!r} already exists: choose another library ID")
        self.library_id = library_id


class VersionExistsError(ConflictError):
    """The library already has a version for this ref."""

    code = "version_exists"

    def __init__(self, library: str, ref: str) -> None:
        super().__init__(f"library {library!r} already has the version {ref!r}")
        self.library, self.ref = library, ref


class VersionImportingError(ConflictError):
    """An import of this ref is already queued or running."""

    code = "version_importing"

    def __init__(self, library: str, ref: str) -> None:
        super().__init__(f"an import of {ref!r} into library {library!r} is already in progress")
        self.library, self.ref = library, ref


class TagNotMovedError(ConflictError):
    """A re-import was asked for a tag that still names the commit its version serves."""

    code = "tag_not_moved"

    def __init__(self, library: str, ref: str, commit_sha: str) -> None:
        super().__init__(
            f"the tag {ref!r} of library {library!r} still points at commit {commit_sha}, "
            "which the version serves: there is nothing to re-import"
        )
        self.library, self.ref, self.commit_sha = library, ref, commit_sha


class CommitImportedError(ConflictError):
    """The commit a SHA names is already a version of the library, under another ref."""

    code = "commit_already_imported"

    def __init__(self, library: str, commit_sha: str, ref: str) -> None:
        super().__init__(
            f"commit {commit_sha} is already the version {ref!r} of library {library!r}"
        )
        self.library, self.commit_sha, self.ref = library, commit_sha, ref


class ImportInProgressError(ConflictError):
    """An import of what is being removed is queued or running; retry when it has finished."""

    code = "import_in_progress"

    def __init__(self, library: str, version: str | None) -> None:
        what = f"library {library!r}" if version is None else f"version {version!r} of {library!r}"
        super().__init__(f"an import of {what} is queued or running: wait for it to finish")
        self.library = library
        self.version = version


class GitNotInstalledError(DomainError):
    """The system ``git`` binary is missing, and ExactDocs cannot read repositories without it."""

    code = "git_not_installed"

    def __init__(self) -> None:
        super().__init__("git is not installed or not on PATH: ExactDocs needs the git binary")


class JobNotFoundError(NotFoundError):
    """No job with this ID exists."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id!r} does not exist")
        self.job_id = job_id


class UnknownLibraryError(NotFoundError):
    """No library with this ID exists."""

    def __init__(self, library: str) -> None:
        super().__init__(f"library {library!r} not found")
        self.library = library


class UnknownVersionError(NotFoundError):
    """The library has no version with this ref."""

    def __init__(self, library: str, ref: str) -> None:
        super().__init__(f"library {library!r} has no version {ref!r}")
        self.library, self.ref = library, ref


class UnknownJobKindError(ValidationError):
    """Nothing is registered to run jobs of this kind."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"unknown job kind {kind!r}")
        self.kind = kind


class InvalidProgressError(ValidationError):
    """Progress that is negative or past its total."""

    def __init__(self, done: int, total: int) -> None:
        super().__init__(f"progress {done} of {total} is not valid")


class PatternProblem(StrEnum):
    """Why a path pattern is refused."""

    EMPTY = "a pattern is empty, too long or has control characters"
    PATH = "a pattern must use '/' and no '..' parts"
    BRACE = "a pattern has a '{' without its '}'"
    TOO_MANY = "too many patterns"


class InvalidPathPatternError(ValidationError):
    """A path pattern of the doc selection cannot be used."""

    code = "invalid_path_pattern"

    def __init__(self, problem: PatternProblem) -> None:
        super().__init__(f"invalid path pattern: {problem.value}")


class TagProblem(StrEnum):
    """Why a tag or a tag rule is refused."""

    INVALID = (
        "a tag is lower-case letters, digits, '.', '+', '-' and '_' (not first), "
        "at most 40 characters"
    )
    TOO_MANY = "too many tag rules"


class InvalidTagError(ValidationError):
    """A tag of a tag rule cannot be used."""

    code = "invalid_tag"

    def __init__(self, problem: TagProblem) -> None:
        super().__init__(f"invalid tag: {problem.value}")


class InvalidContext7Error(ValidationError):
    """A repository's ``context7.json`` cannot be used; it is reported as a warning and ignored."""

    code = "invalid_context7"

    def __init__(self, reason: str) -> None:
        super().__init__(f"context7.json is ignored: {reason}")


class UnknownRefError(ValidationError):
    """The repository has no tag, branch or commit like the requested ref."""

    code = "unknown_ref"

    def __init__(self, ref: str | None) -> None:
        if ref is None:
            super().__init__("the repository has no default branch: choose a tag or branch")
        else:
            super().__init__(f"the repository has no tag, branch or commit {ref!r}")


class AmbiguousRefError(ValidationError):
    """A short commit SHA starts more than one commit."""

    code = "ambiguous_ref"

    def __init__(self, prefix: str) -> None:
        super().__init__(f"commit {prefix!r} is ambiguous: use more characters of the SHA")


class NotATagError(ValidationError):
    """Only a tag version is re-imported on request: a branch follows its tip with a sync."""

    code = "not_a_tag"

    def __init__(self, ref: str, kind: str) -> None:
        follow = (
            "a branch follows its tip with a sync" if kind == "branch" else "a commit never changes"
        )
        super().__init__(f"{ref!r} is a {kind}, not a tag: {follow}")
        self.ref = ref


class RefDeletedError(ValidationError):
    """The tag a re-import was asked for is gone from the repository."""

    code = "ref_deleted"

    def __init__(self, ref: str) -> None:
        super().__init__(f"the tag {ref!r} no longer exists in the repository")
        self.ref = ref


class ImportNotPinnedError(ValidationError):
    """The import job names no version or no commit, so there is nothing exact to import."""

    code = "import_not_pinned"

    def __init__(self) -> None:
        super().__init__("the import job has no version or commit to import")


class NoArticlesError(ValidationError):
    """Nothing in the commit matched the library's paths; an empty version is not published."""

    code = "no_articles"

    def __init__(self) -> None:
        super().__init__("no .md or .mdx file of this commit matches the library's paths")


class ImportTooLargeError(ValidationError):
    """The selected articles add up to more text than one import takes."""

    code = "import_too_large"

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"the selected articles are larger than {limit // 2**20} MiB: narrow the paths"
        )


class CheckoutUnreadableError(DomainError):
    """A folder of the fetched files could not be listed, so the version would be incomplete."""

    code = "checkout_unreadable"

    def __init__(self) -> None:
        super().__init__("a folder of the fetched files could not be read")


class SyncFailedError(ValidationError):
    """The remote could not be read during a sync: why (``code``), plus the jobs that say so.

    ``code`` is the sync's own (``repo_unreachable``, ``auth_failed``...), the one the failed
    jobs record too; ``cause_code`` is the finer code of the git error behind it.
    """

    def __init__(self, cause: DomainError, job_ids: Sequence[str], code: str) -> None:
        jobs = f" (failed jobs recorded: {', '.join(job_ids)})" if job_ids else ""
        super().__init__(f"{cause}{jobs}")
        self.code = code
        self.cause_code = cause.code
        self.job_ids = tuple(job_ids)


class InvalidAutoSyncError(ValidationError):
    """A library's schedule (tag pattern, retention or interval) cannot be used."""

    code = "invalid_auto_sync"

    def __init__(self, problem: str) -> None:
        super().__init__(f"invalid schedule: {problem}")


class ReprocessFailedError(DomainError):
    """Some versions could not be re-processed after a settings edit; they serve what they had.

    The others were re-processed. ``code`` is the failures' code when they share one (say
    ``repo_unreachable`` or ``no_articles``), else ``reprocess_failed``.
    """

    code = "reprocess_failed"

    def __init__(self, failures: Sequence[tuple[str, str, str]]) -> None:
        listed = "; ".join(f"{ref}: {reason}" for ref, _, reason in failures)
        super().__init__(
            f"{len(failures)} version(s) could not be re-processed and keep what they served: "
            f"{listed}"
        )
        codes = {code for _, code, _ in failures}
        if len(codes) == 1:
            self.code = codes.pop()
        self.refs = tuple(ref for ref, _, _ in failures)
