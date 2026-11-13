"""Ingestion errors. Messages never contain the URL a user typed: it may hold a credential."""

from collections.abc import Sequence
from enum import StrEnum

from exactdocs_kernel import (
    BusyError,
    ConflictError,
    DomainError,
    NotFoundError,
    UnauthenticatedError,
    ValidationError,
)


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
        """Say why the URL is refused, without repeating it.

        Args:
            problem: What is wrong with the URL.
        """
        super().__init__(f"not a usable git URL: {problem.value}")


class InvalidChunkingConfigError(ValidationError):
    """The chunking settings are out of range, or name a chunker that is not supported."""

    code = "invalid_chunking_config"

    def __init__(self, reason: str = "split_depth must be between 1 and 6") -> None:
        """Say which chunking setting is wrong.

        Args:
            reason: What is out of range or not supported.
        """
        super().__init__(f"invalid chunking settings: {reason}")


class NotAGitRepositoryError(ValidationError):
    """The address answers, but there is no git repository there (or none visible without login)."""

    code = "not_a_git_repository"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "no git repository was found at that address (a private repository can look the same)"
        )


class RepositoryUnreachableError(ValidationError):
    """The repository could not be contacted (DNS, connection, TLS, timeout...)."""

    code = "repository_unreachable"

    def __init__(self, reason: str) -> None:
        """Say why the repository could not be contacted.

        Args:
            reason: The failure, in a fixed text that never repeats the URL.
        """
        super().__init__(f"the repository is unreachable: {reason}")


class RepositoryAuthRequiredError(ValidationError):
    """The server wants credentials (a private repository, or one that is hidden without them)."""

    code = "repository_auth_required"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the repository requires authentication")


class CredentialProblem(StrEnum):
    """Why a credential is refused. Fixed texts: none of them can repeat the secret."""

    EMPTY = "the token or key is empty"
    ONE_LINE = "a token is one line of at most 4096 printable characters"
    USERNAME = "a token's user name is letters, digits, '.', '_' and '-' (at most 100)"
    KEY = "a deploy key is an unencrypted private key in OpenSSH or PEM format"
    TOO_LONG = "the deploy key is too long"
    ONE_LINE_KEY = (
        "the deploy key has lost its line breaks: send it as its file holds it, the BEGIN and "
        "END lines and each line of the body on its own line"
    )
    ENCRYPTED_KEY = "the deploy key has a passphrase: use a key without one"
    HTTPS_ONLY = "an access token goes with an https:// URL (http:// only for localhost)"
    SSH_ONLY = "a deploy key goes with an ssh:// or user@host:path URL"


class InvalidCredentialError(ValidationError):
    """The credential cannot be used with this repository."""

    code = "invalid_credential"

    def __init__(self, problem: CredentialProblem) -> None:
        """Say why the credential is refused, without repeating it.

        Args:
            problem: What is wrong with the credential.
        """
        super().__init__(f"not a usable credential: {problem.value}")


class CredentialsRequiredError(ValidationError):
    """The library's stored credentials cannot be read (the secret key changed): send them again."""

    code = "credentials_required"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "the stored credentials of this library cannot be read with the current secret key: "
            "send the token or deploy key again"
        )


class HostKeyChangedError(ValidationError):
    """The SSH server's host key is not the one remembered for it: possibly a man in the middle."""

    code = "host_key_changed"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "the SSH host key of the server changed since it was first seen: refusing to "
            "connect (if it was rotated on purpose, remove the host from the known_hosts file)"
        )


class CommitUnavailableError(ValidationError):
    """The repository no longer serves the commit a version is pinned to (a force-pushed branch)."""

    code = "commit_unavailable"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the repository does not serve the pinned commit any more")


class RepositoryTooLargeError(ValidationError):
    """What a fetch brought in is bigger than ExactDocs accepts."""

    code = "repository_too_large"

    def __init__(self, limit: int) -> None:
        """Name the size limit that was passed.

        Args:
            limit: The most bytes accepted; the message names it in MiB.
        """
        super().__init__(f"the selected files are larger than {limit // 2**20} MiB")


class TreeTooLargeError(ValidationError):
    """The commit has more files than a preview can list (same code as ``RepositoryTooLarge``)."""

    code = "repository_too_large"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the repository has too many files to preview")


class PreviewBusyError(BusyError):
    """Every preview slot is taken: the caller may try again in a moment."""

    code = "preview_busy"

    def __init__(self, *, retry_after: int = 5) -> None:
        """Ask the caller to come back later.

        Args:
            retry_after: Seconds the caller should wait before it tries again.
        """
        super().__init__(
            "too many previews are running; try again in a moment", retry_after=retry_after
        )


class LibraryIdTakenError(ConflictError):
    """Another library already uses the ID this repository would get."""

    code = "library_id_taken"

    def __init__(self, library_id: str) -> None:
        """Name the library ID that is taken.

        Args:
            library_id: The ID another library already has.
        """
        super().__init__(f"library {library_id!r} already exists: choose another library ID")
        self.library_id = library_id


class VersionExistsError(ConflictError):
    """The library already has a version for this ref."""

    code = "version_exists"

    def __init__(self, library: str, ref: str) -> None:
        """Name the library and the ref it already has.

        Args:
            library: The library ID.
            ref: The ref of the existing version.
        """
        super().__init__(f"library {library!r} already has the version {ref!r}")
        self.library, self.ref = library, ref


class VersionImportingError(ConflictError):
    """An import of this ref is already queued or running."""

    code = "version_importing"

    def __init__(self, library: str, ref: str) -> None:
        """Name the library and the ref being imported.

        Args:
            library: The library ID.
            ref: The ref whose import is queued or running.
        """
        super().__init__(f"an import of {ref!r} into library {library!r} is already in progress")
        self.library, self.ref = library, ref


class TagNotMovedError(ConflictError):
    """A re-import was asked for a tag that still names the commit its version serves."""

    code = "tag_not_moved"

    def __init__(self, library: str, ref: str, commit_sha: str) -> None:
        """Name the tag and the commit it still points at.

        Args:
            library: The library ID.
            ref: The tag.
            commit_sha: The commit the tag and the version both name.
        """
        super().__init__(
            f"the tag {ref!r} of library {library!r} still points at commit {commit_sha}, "
            "which the version serves: there is nothing to re-import"
        )
        self.library, self.ref, self.commit_sha = library, ref, commit_sha


class CommitImportedError(ConflictError):
    """The commit a SHA names is already a version of the library, under another ref."""

    code = "commit_already_imported"

    def __init__(self, library: str, commit_sha: str, ref: str) -> None:
        """Name the commit and the version that already serves it.

        Args:
            library: The library ID.
            commit_sha: The commit that was asked for.
            ref: The ref of the version that serves it.
        """
        super().__init__(
            f"commit {commit_sha} is already the version {ref!r} of library {library!r}"
        )
        self.library, self.commit_sha, self.ref = library, commit_sha, ref


class ImportInProgressError(ConflictError):
    """An import of what is being removed is queued or running; retry when it has finished."""

    code = "import_in_progress"

    def __init__(self, library: str, version: str | None) -> None:
        """Name what is being imported.

        Args:
            library: The library ID.
            version: The version's ref, or None when the whole library is being removed.
        """
        what = f"library {library!r}" if version is None else f"version {version!r} of {library!r}"
        super().__init__(f"an import of {what} is queued or running: wait for it to finish")
        self.library = library
        self.version = version


class GitNotInstalledError(DomainError):
    """The system ``git`` binary is missing, and ExactDocs cannot read repositories without it."""

    code = "git_not_installed"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("git is not installed or not on PATH: ExactDocs needs the git binary")


class JobNotFoundError(NotFoundError):
    """No job with this ID exists."""

    def __init__(self, job_id: str) -> None:
        """Name the job that does not exist.

        Args:
            job_id: The job ID as given.
        """
        super().__init__(f"job {job_id!r} does not exist")
        self.job_id = job_id


class UnknownLibraryError(NotFoundError):
    """No library with this ID exists."""

    def __init__(self, library: str) -> None:
        """Name the library that does not exist.

        Args:
            library: The library ID as given.
        """
        super().__init__(f"library {library!r} not found")
        self.library = library


class UnknownVersionError(NotFoundError):
    """The library has no version with this ref."""

    def __init__(self, library: str, ref: str) -> None:
        """Name the library and the ref it lacks.

        Args:
            library: The library ID.
            ref: The ref as given.
        """
        super().__init__(f"library {library!r} has no version {ref!r}")
        self.library, self.ref = library, ref


class UnknownJobKindError(ValidationError):
    """Nothing is registered to run jobs of this kind."""

    def __init__(self, kind: str) -> None:
        """Name the kind nothing runs.

        Args:
            kind: The job kind.
        """
        super().__init__(f"unknown job kind {kind!r}")
        self.kind = kind


class InvalidProgressError(ValidationError):
    """Progress that is negative or past its total."""

    def __init__(self, done: int, total: int) -> None:
        """Name the progress that is out of range.

        Args:
            done: Units done.
            total: Units in all.
        """
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
        """Say why the pattern is refused.

        Args:
            problem: What is wrong with the pattern.
        """
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
        """Say why the tag is refused.

        Args:
            problem: What is wrong with the tag or the rules.
        """
        super().__init__(f"invalid tag: {problem.value}")


class InvalidContext7Error(ValidationError):
    """A repository's ``context7.json`` cannot be used; it is reported as a warning and ignored."""

    code = "invalid_context7"

    def __init__(self, reason: str) -> None:
        """Say why the file is ignored.

        Args:
            reason: What is wrong with ``context7.json``.
        """
        super().__init__(f"context7.json is ignored: {reason}")


class UnknownRefError(ValidationError):
    """The repository has no tag, branch or commit like the requested ref."""

    code = "unknown_ref"

    def __init__(self, ref: str | None) -> None:
        """Name the ref the repository lacks.

        Args:
            ref: The requested ref; None when the default branch was asked for and there is none.
        """
        if ref is None:
            super().__init__("the repository has no default branch: choose a tag or branch")
        else:
            super().__init__(f"the repository has no tag, branch or commit {ref!r}")


class AmbiguousRefError(ValidationError):
    """A short commit SHA starts more than one commit."""

    code = "ambiguous_ref"

    def __init__(self, prefix: str) -> None:
        """Name the short SHA that is ambiguous.

        Args:
            prefix: The short SHA as given.
        """
        super().__init__(f"commit {prefix!r} is ambiguous: use more characters of the SHA")


class NotATagError(ValidationError):
    """Only a tag version is re-imported on request: a branch follows its tip with a sync."""

    code = "not_a_tag"

    def __init__(self, ref: str, kind: str) -> None:
        """Say what the ref is instead, and how such a version is kept current.

        Args:
            ref: The version's ref.
            kind: What the ref is: ``branch`` or ``commit``.
        """
        follow = (
            "a branch follows its tip with a sync" if kind == "branch" else "a commit never changes"
        )
        super().__init__(f"{ref!r} is a {kind}, not a tag: {follow}")
        self.ref = ref


class RefDeletedError(ValidationError):
    """The tag a re-import was asked for is gone from the repository."""

    code = "ref_deleted"

    def __init__(self, ref: str) -> None:
        """Name the tag that is gone.

        Args:
            ref: The tag.
        """
        super().__init__(f"the tag {ref!r} no longer exists in the repository")
        self.ref = ref


class ImportNotPinnedError(ValidationError):
    """The import job names no version or no commit, so there is nothing exact to import."""

    code = "import_not_pinned"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the import job has no version or commit to import")


class NoArticlesError(ValidationError):
    """Nothing in the commit matched the library's paths; an empty version is not published."""

    code = "no_articles"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no .md or .mdx file of this commit matches the library's paths")


class ImportTooLargeError(ValidationError):
    """The selected articles add up to more text than one import takes."""

    code = "import_too_large"

    def __init__(self, limit: int) -> None:
        """Name the size limit that was passed.

        Args:
            limit: The most bytes of text one import takes; the message names it in MiB.
        """
        super().__init__(
            f"the selected articles are larger than {limit // 2**20} MiB: narrow the paths"
        )


class CheckoutUnreadableError(DomainError):
    """A folder of the fetched files could not be listed, so the version would be incomplete."""

    code = "checkout_unreadable"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("a folder of the fetched files could not be read")


class SyncFailedError(ValidationError):
    """The remote could not be read during a sync: why (``code``), plus the jobs that say so.

    ``code`` is the sync's own (``repo_unreachable``, ``auth_failed``...), the one the failed
    jobs record too; ``cause_code`` is the finer code of the git error behind it.
    """

    def __init__(self, cause: DomainError, job_ids: Sequence[str], code: str) -> None:
        """Keep the cause's message and code, and list the jobs that recorded the failure.

        Args:
            cause: The git error the sync ran into.
            job_ids: The failed jobs recorded for it; may be empty.
            code: The sync's own error code (``repo_unreachable``, ``auth_failed``...).
        """
        jobs = f" (failed jobs recorded: {', '.join(job_ids)})" if job_ids else ""
        super().__init__(f"{cause}{jobs}")
        self.code = code
        self.cause_code = cause.code
        self.job_ids = tuple(job_ids)


class InvalidAutoSyncError(ValidationError):
    """A library's schedule (tag pattern, retention or interval) cannot be used."""

    code = "invalid_auto_sync"

    def __init__(self, problem: str) -> None:
        """Say what is wrong with the schedule.

        Args:
            problem: Which setting is out of range or malformed.
        """
        super().__init__(f"invalid schedule: {problem}")


class ReprocessFailedError(DomainError):
    """Some versions could not be re-processed after a settings edit; they serve what they had.

    The others were re-processed. ``code`` is the failures' code when they share one (say
    ``repo_unreachable`` or ``no_articles``), else ``reprocess_failed``.
    """

    code = "reprocess_failed"

    def __init__(self, failures: Sequence[tuple[str, str, str]]) -> None:
        """List each version that failed and why; share the failures' code when they have one.

        Args:
            failures: ``(ref, code, reason)`` for each version that could not be re-processed.
        """
        listed = "; ".join(f"{ref}: {reason}" for ref, _, reason in failures)
        super().__init__(
            f"{len(failures)} version(s) could not be re-processed and keep what they served: "
            f"{listed}"
        )
        codes = {code for _, code, _ in failures}
        if len(codes) == 1:
            self.code = codes.pop()
        self.refs = tuple(ref for ref, _, _ in failures)


class StoredTextOutdatedError(DomainError):
    """A version's articles were stored by an older parser: re-chunking needs them re-imported."""

    code = "stored_text_outdated"

    def __init__(self, library: str, ref: str) -> None:
        """Name the version whose text is outdated.

        Args:
            library: The library ID.
            ref: The version's ref.
        """
        super().__init__(
            f"{library} {ref} was stored by another parser version; it is re-imported instead"
        )


class EmbeddingUnavailableError(DomainError):
    """The embedding model did not answer for now (a timeout, a rate limit, a 5xx): try again."""

    code = "embedding_unavailable"

    def __init__(self, reason: str) -> None:
        """Keep retrieval's reason (the model and the error type, never a key).

        Args:
            reason: Why the batch was not embedded.
        """
        super().__init__(reason)


class InvalidWebhookSignatureError(UnauthenticatedError):
    """A webhook delivery is refused: one fixed message, whatever the reason.

    A missing or wrong signature, an unknown forge, a library without a webhook secret and an
    unknown library all read alike, so a caller cannot tell which libraries exist or have one.
    """

    code = "invalid_signature"

    def __init__(self) -> None:
        """Create the error; its message never depends on the request."""
        super().__init__("the webhook signature is missing or invalid")


class MissingDeliveryIdError(DomainError):
    """A signed webhook delivery carries no delivery ID, so a redelivery could not be told apart."""

    code = "missing_delivery_id"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "the delivery has no ID (X-GitHub-Delivery, Idempotency-Key or X-Gitlab-Event-UUID, "
            "X-Request-UUID or X-Request-Id)"
        )


class InvalidWebhookPayloadError(DomainError):
    """A signed push delivery whose body is not the JSON its forge sends."""

    code = "invalid_webhook_payload"

    def __init__(self, reason: str) -> None:
        """Say what is wrong with the body.

        Args:
            reason: What is wrong, in fixed words (never the body itself).
        """
        super().__init__(f"the push payload cannot be read: {reason}")


class WebhookSecretUnreadableError(DomainError):
    """A stored webhook secret does not open (the instance's secret key changed); never shown."""

    code = "webhook_secret_unreadable"

    def __init__(self, library: str) -> None:
        """Name the library.

        Args:
            library: The library ID.
        """
        super().__init__(f"the webhook secret of {library!r} cannot be read; set a new one")
        self.library = library


class PushQueuedError(ConflictError):
    """A ``push`` job of this (library, ref) already waits: the new push joins it."""

    code = "push_queued"

    def __init__(self, library: str, ref: str) -> None:
        """Name the library and the ref.

        Args:
            library: The library ID.
            ref: The pushed branch or tag.
        """
        super().__init__(f"a sync of {ref!r} in library {library!r} is already queued")
        self.library, self.ref = library, ref


class AutoImportFailedError(DomainError):
    """The auto-import after a pushed tag could not queue or remove everything it planned."""

    code = "auto_import_failed"

    def __init__(self, errors: Sequence[str]) -> None:
        """List what could not be done.

        Args:
            errors: One text per tag that was not queued or version that was not removed.
        """
        super().__init__("; ".join(errors))
