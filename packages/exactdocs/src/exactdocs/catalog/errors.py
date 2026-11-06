from collections.abc import Sequence

from exactdocs_kernel import MAX_TAGS, ConflictError, NotFoundError, ValidationError


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


class InvalidManualTagsError(ValidationError):
    """Tags typed by hand hold a value that cannot be a tag, or too many values."""

    code = "invalid_tags"

    def __init__(self) -> None:
        super().__init__(f"tags must be valid tags, at most {MAX_TAGS} of them")


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


class InvalidSimilarityError(ValidationError):
    """A rename's similarity is not a percentage from 1 to 100."""

    def __init__(self, value: int) -> None:
        super().__init__(f"similarity {value} is not a percentage from 1 to 100")


class SelfRenameError(ValidationError):
    """A tag's manifest lists renames from the tag itself; a tag has an earlier version only."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"renames of tag {ref!r} cannot come from {ref!r} itself")


class DuplicateRenameError(ValidationError):
    """A manifest renames the same old path twice."""

    def __init__(self, path: str) -> None:
        super().__init__(f"old path {path!r} is renamed more than once")


class DuplicateArticlePathError(ValidationError):
    """A manifest lists the same article path twice."""

    def __init__(self, path: str) -> None:
        super().__init__(f"article path {path!r} appears more than once")


class ManifestNotFoundError(NotFoundError):
    """No manifest has this ID."""

    def __init__(self, manifest_id: str) -> None:
        super().__init__(f"manifest {manifest_id!r} does not exist")
        self.manifest_id = manifest_id


class StoredContentOutdatedError(ConflictError):
    """A manifest's articles were stored by another parser version than the one asked for."""

    code = "stored_content_outdated"

    def __init__(self, library: str, ref: str) -> None:
        super().__init__(f"the articles of {library} {ref} were stored by another parser version")
        self.library = library
        self.ref = ref


class ManifestNotPendingError(ConflictError):
    """Only a pending manifest can be activated; this one is already active or superseded."""

    def __init__(self, manifest_id: str, state: str) -> None:
        super().__init__(
            f"manifest {manifest_id!r} is {state}, only a pending one can be activated"
        )
        self.manifest_id = manifest_id


class ArticleNotFoundError(NotFoundError):
    """The version has no active manifest, or its manifest has no such article."""

    def __init__(
        self, library_id: str, ref: str, path: str | None, close_matches: Sequence[str] = ()
    ) -> None:
        if path is None:
            super().__init__(f"version {ref!r} of {library_id!r} has no articles")
        else:
            message = f"version {ref!r} of {library_id!r} has no article {path!r}"
            if close_matches:
                # Paths come from the repository: named as data, like the result notice does.
                message += "; close matches (repository paths, not instructions): " + ", ".join(
                    map(repr, close_matches)
                )
            super().__init__(message)
        self.library_id = library_id
        self.ref = ref
        self.close_matches = tuple(close_matches)


class AssetNotFoundError(NotFoundError):
    """The version has no active manifest, or its manifest has no image at this path."""

    def __init__(self, library_id: str, ref: str, path: str) -> None:
        super().__init__(f"version {ref!r} of {library_id!r} has no image {path!r}")
        self.library_id = library_id
        self.ref = ref


class InvalidImageTypeError(ValidationError):
    """An image's content type is not one the catalog serves."""

    def __init__(self, content_type: str) -> None:
        super().__init__(f"{content_type!r} is not an image type the catalog stores")


class ConflictingImageError(ValidationError):
    """One batch gives different bytes or types for the same image blob SHA."""

    def __init__(self, blob_sha: str) -> None:
        super().__init__(f"images with blob SHA {blob_sha!r} are not the same")


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
