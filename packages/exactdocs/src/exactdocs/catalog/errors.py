from exactdocs_kernel import ConflictError, NotFoundError, ValidationError


class InvalidLibraryIdError(ValidationError):
    """A library ID is not `/owner/repo` with segments from `[a-z0-9._-]`."""

    def __init__(self, text: str) -> None:
        super().__init__(
            f"{text!r} is not a library ID: expected /owner/repo, "
            "each segment made of letters, digits, '.', '_' or '-'"
        )


class InvalidVersionRefError(ValidationError):
    """A version ref breaks the basic rules of `git check-ref-format`."""

    def __init__(self, text: str) -> None:
        super().__init__(
            f"{text!r} is not a version ref: no blank or empty parts, '..', control characters, "
            "spaces, leading '-' or trailing '.lock'"
        )


class InvalidCommitShaError(ValidationError):
    """A commit SHA is not a full lower-case hexadecimal object ID."""

    def __init__(self, text: str) -> None:
        super().__init__(f"{text!r} is not a full commit SHA (40 or 64 hexadecimal characters)")


class InvalidImportTimeError(ValidationError):
    """A version's import time has no time zone, so it cannot be ordered against others."""

    def __init__(self) -> None:
        super().__init__("imported_at must be timezone-aware")


class DuplicateVersionRefError(ValidationError):
    """A library lists the same ref twice."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"version ref {ref!r} appears more than once")


class InvalidSettingsError(ValidationError):
    """A library setting has a value outside its range."""


class InvalidTagFilterError(ValidationError):
    """A tag filter holds a value that cannot be a tag, or too many values."""

    code = "invalid_tag_filter"


class AmbiguousCommitError(ValidationError):
    """A short commit SHA matches more than one commit version."""

    def __init__(self, prefix: str) -> None:
        super().__init__(f"commit {prefix!r} is ambiguous: use more characters of the SHA")
        self.prefix = prefix


class LibraryNotFoundError(NotFoundError):
    """No library with this ID is in the catalog."""

    def __init__(self, library_id: str) -> None:
        super().__init__(f"library {library_id!r} is not in the catalog")
        self.library_id = library_id


class VersionNotFoundError(NotFoundError):
    """The library has no such version (or, without a ref, no version at all)."""

    def __init__(self, library_id: str, ref: str | None) -> None:
        if ref is None:
            super().__init__(f"library {library_id!r} has no imported version")
        else:
            super().__init__(f"library {library_id!r} has no version {ref!r}")
        self.library_id = library_id
        self.ref = ref


class InvalidBlobShaError(ValidationError):
    """A blob SHA is not a full lower-case hexadecimal git object ID."""

    def __init__(self, text: str) -> None:
        super().__init__(f"{text!r} is not a full blob SHA (40 or 64 hexadecimal characters)")


class InvalidArticlePathError(ValidationError):
    """An article path is not a relative `/`-separated path inside the repository."""

    def __init__(self, text: str) -> None:
        super().__init__(
            f"{text!r} is not an article path: expected a relative path without empty, '.' or "
            "'..' parts"
        )


class DuplicateArticlePathError(ValidationError):
    """A manifest lists the same article path twice."""

    def __init__(self, path: str) -> None:
        super().__init__(f"article path {path!r} appears more than once")


class ManifestNotFoundError(NotFoundError):
    """No manifest has this ID."""

    def __init__(self, manifest_id: str) -> None:
        super().__init__(f"manifest {manifest_id!r} does not exist")
        self.manifest_id = manifest_id


class ManifestNotPendingError(ConflictError):
    """Only a pending manifest can be activated; this one is already active or superseded."""

    def __init__(self, manifest_id: str, state: str) -> None:
        super().__init__(
            f"manifest {manifest_id!r} is {state}, only a pending one can be activated"
        )
        self.manifest_id = manifest_id


class ArticleNotFoundError(NotFoundError):
    """The version has no active manifest, or its manifest has no such article."""

    def __init__(self, library_id: str, ref: str, path: str | None) -> None:
        if path is None:
            super().__init__(f"version {ref!r} of {library_id!r} has no articles")
        else:
            super().__init__(f"version {ref!r} of {library_id!r} has no article {path!r}")
        self.library_id = library_id
        self.ref = ref


class ConflictingContentError(ValidationError):
    """One batch gives different texts for the same blob SHA and content version."""

    def __init__(self, blob_sha: str) -> None:
        super().__init__(f"articles with blob SHA {blob_sha!r} do not have the same content")


class ManifestOutdatedError(ConflictError):
    """A newer manifest of the version is already active; activating this one would go back."""

    def __init__(self, manifest_id: str) -> None:
        super().__init__(f"manifest {manifest_id!r} is older than the active manifest")
        self.manifest_id = manifest_id


class LibraryAlreadyExistsError(ConflictError):
    """A library with this ID is already in the catalog."""

    code = "library_id_taken"

    def __init__(self, library_id: str) -> None:
        super().__init__(f"library {library_id!r} already exists: choose another library ID")
        self.library_id = library_id


class LibraryNotEmptyError(ConflictError):
    """A library with imported versions cannot be discarded as if it were new."""

    code = "library_not_empty"

    def __init__(self, library_id: str) -> None:
        super().__init__(f"library {library_id!r} has imported versions")
