"""Ingestion errors. Messages never contain the URL a user typed: it may hold a credential."""

from enum import StrEnum

from exactdocs_kernel import ConflictError, DomainError, NotFoundError, ValidationError


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


class LibraryIdTakenError(ConflictError):
    """Another library already uses the ID this repository would get."""

    code = "library_id_taken"

    def __init__(self, library_id: str) -> None:
        super().__init__(f"library {library_id!r} already exists: choose another library ID")
        self.library_id = library_id


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
