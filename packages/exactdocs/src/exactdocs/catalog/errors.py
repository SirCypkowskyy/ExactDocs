from exactdocs_kernel import NotFoundError, ValidationError


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
