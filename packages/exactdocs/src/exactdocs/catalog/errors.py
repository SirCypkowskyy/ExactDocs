"""Errors of ``exactdocs.catalog``: each one names what was asked for and why it failed."""

from collections.abc import Sequence

from exactdocs_kernel import MAX_TAGS, ConflictError, NotFoundError, ValidationError


class InvalidLibraryIdError(ValidationError):
    """A library ID is not `/owner/repo` with segments from `[a-z0-9._-]`."""

    def __init__(self, text: str) -> None:
        """Quote the text that is not a library ID.

        Args:
            text: The text as given.
        """
        super().__init__(
            f"{text!r} is not a library ID: expected /owner/repo, "
            "each segment made of letters, digits, '.', '_' or '-'"
        )


class InvalidVersionRefError(ValidationError):
    """A version ref breaks the basic rules of `git check-ref-format`."""

    def __init__(self, text: str) -> None:
        """Quote the text that is not a version ref.

        Args:
            text: The text as given.
        """
        super().__init__(
            f"{text!r} is not a version ref: no blank or empty parts, '..', control characters, "
            "spaces, leading '-' or trailing '.lock'"
        )


class InvalidCommitShaError(ValidationError):
    """A commit SHA is not a full lower-case hexadecimal object ID."""

    def __init__(self, text: str) -> None:
        """Quote the text that is not a commit SHA.

        Args:
            text: The text as given.
        """
        super().__init__(f"{text!r} is not a full commit SHA (40 or 64 hexadecimal characters)")


class InvalidImportTimeError(ValidationError):
    """A version's import time has no time zone, so it cannot be ordered against others."""

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("imported_at must be timezone-aware")


class DuplicateVersionRefError(ValidationError):
    """A library lists the same ref twice."""

    def __init__(self, ref: str) -> None:
        """Name the ref listed twice.

        Args:
            ref: The ref.
        """
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
        """Create the error with its fixed message, which names the most tags allowed."""
        super().__init__(f"tags must be valid tags, at most {MAX_TAGS} of them")


class AmbiguousCommitError(ValidationError):
    """A short commit SHA matches more than one commit version."""

    def __init__(self, prefix: str) -> None:
        """Name the short SHA.

        Args:
            prefix: The short SHA, lower-case.
        """
        super().__init__(f"commit {prefix!r} is ambiguous: use more characters of the SHA")
        self.prefix = prefix


class LibraryNotFoundError(NotFoundError):
    """No library with this ID is in the catalog."""

    def __init__(self, library_id: str) -> None:
        """Name the library.

        Args:
            library_id: The library ID asked for.
        """
        super().__init__(f"library {library_id!r} is not in the catalog")
        self.library_id = library_id


class VersionNotFoundError(NotFoundError):
    """The library has no such version (or, without a ref, no version at all)."""

    def __init__(self, library_id: str, ref: str | None) -> None:
        """Name the library and the ref.

        Args:
            library_id: The library ID.
            ref: The ref asked for; ``None`` when the default version was asked for.
        """
        if ref is None:
            super().__init__(f"library {library_id!r} has no imported version")
        else:
            super().__init__(f"library {library_id!r} has no version {ref!r}")
        self.library_id = library_id
        self.ref = ref


class InvalidBlobShaError(ValidationError):
    """A blob SHA is not a full lower-case hexadecimal git object ID."""

    def __init__(self, text: str) -> None:
        """Quote the text that is not a blob SHA.

        Args:
            text: The text as given.
        """
        super().__init__(f"{text!r} is not a full blob SHA (40 or 64 hexadecimal characters)")


class InvalidArticlePathError(ValidationError):
    """An article path is not a relative `/`-separated path inside the repository."""

    def __init__(self, text: str) -> None:
        """Quote the text that is not an article path.

        Args:
            text: The text as given.
        """
        super().__init__(
            f"{text!r} is not an article path: expected a relative path without empty, '.' or "
            "'..' parts"
        )


class InvalidSimilarityError(ValidationError):
    """A rename's similarity is not a percentage from 1 to 100."""

    def __init__(self, value: int) -> None:
        """Name the similarity.

        Args:
            value: The similarity, in percent.
        """
        super().__init__(f"similarity {value} is not a percentage from 1 to 100")


class SelfRenameError(ValidationError):
    """A tag's manifest lists renames from the tag itself; a tag has an earlier version only."""

    def __init__(self, ref: str) -> None:
        """Name the tag.

        Args:
            ref: The tag's ref.
        """
        super().__init__(f"renames of tag {ref!r} cannot come from {ref!r} itself")


class RenameLinkMismatchError(ValidationError):
    """A manifest's renames come from another version than the one it follows."""

    def __init__(self, ref: str, from_ref: str, renamed_from: str) -> None:
        """Name the version, where its renames come from and the version it follows.

        Args:
            ref: The manifest's ref.
            from_ref: The version a rename names.
            renamed_from: The version the manifest follows.
        """
        super().__init__(
            f"renames of {ref!r} cannot come from {from_ref!r}: {ref!r} follows {renamed_from!r}"
        )


class DuplicateRenameError(ValidationError):
    """A manifest renames the same old path twice."""

    def __init__(self, path: str) -> None:
        """Name the old path renamed twice.

        Args:
            path: The old path.
        """
        super().__init__(f"old path {path!r} is renamed more than once")


class DuplicateArticlePathError(ValidationError):
    """A manifest lists the same article path twice."""

    def __init__(self, path: str) -> None:
        """Name the path listed twice.

        Args:
            path: The article or image path.
        """
        super().__init__(f"article path {path!r} appears more than once")


class ManifestNotFoundError(NotFoundError):
    """No manifest has this ID."""

    def __init__(self, manifest_id: str) -> None:
        """Name the manifest.

        Args:
            manifest_id: The manifest ID asked for.
        """
        super().__init__(f"manifest {manifest_id!r} does not exist")
        self.manifest_id = manifest_id


class StoredContentOutdatedError(ConflictError):
    """A manifest's articles were stored by another parser version than the one asked for."""

    code = "stored_content_outdated"

    def __init__(self, library: str, ref: str) -> None:
        """Name the version whose articles are outdated.

        Args:
            library: The library ID.
            ref: The version's ref.
        """
        super().__init__(f"the articles of {library} {ref} were stored by another parser version")
        self.library = library
        self.ref = ref


class ManifestNotPendingError(ConflictError):
    """Only a pending manifest can be activated; this one is already active or superseded."""

    def __init__(self, manifest_id: str, state: str) -> None:
        """Name the manifest and the state it is in.

        Args:
            manifest_id: The manifest ID.
            state: Its state, ``active`` or ``superseded``.
        """
        super().__init__(
            f"manifest {manifest_id!r} is {state}, only a pending one can be activated"
        )
        self.manifest_id = manifest_id


class ArticleNotFoundError(NotFoundError):
    """The version has no active manifest, or its manifest has no such article."""

    def __init__(
        self, library_id: str, ref: str, path: str | None, close_matches: Sequence[str] = ()
    ) -> None:
        """Name the version and the article, with the paths an agent may have meant.

        Args:
            library_id: The library ID.
            ref: The version's ref.
            path: The article path asked for; ``None`` when the version has no articles at all.
            close_matches: Existing paths close to ``path``, quoted as repository data.
        """
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
        """Name the version and the image path.

        Args:
            library_id: The library ID.
            ref: The version's ref.
            path: The image path asked for.
        """
        super().__init__(f"version {ref!r} of {library_id!r} has no image {path!r}")
        self.library_id = library_id
        self.ref = ref


class InvalidImageTypeError(ValidationError):
    """An image's content type is not one the catalog serves."""

    def __init__(self, content_type: str) -> None:
        """Quote the content type.

        Args:
            content_type: The image's content type.
        """
        super().__init__(f"{content_type!r} is not an image type the catalog stores")


class InvalidInstructionFileError(ValidationError):
    """An instruction file is too long, a manifest keeps too many, or one path twice."""

    def __init__(self, path: str) -> None:
        """Name the file.

        Args:
            path: Its repository path.
        """
        super().__init__(f"the instruction file {path!r} cannot be kept")


class ConflictingImageError(ValidationError):
    """One batch gives different bytes or types for the same image blob SHA."""

    def __init__(self, blob_sha: str) -> None:
        """Name the blob SHA.

        Args:
            blob_sha: The image's blob SHA.
        """
        super().__init__(f"images with blob SHA {blob_sha!r} are not the same")


class ConflictingContentError(ValidationError):
    """One batch gives different texts for the same blob SHA and content version."""

    def __init__(self, blob_sha: str) -> None:
        """Name the blob SHA.

        Args:
            blob_sha: The article's blob SHA.
        """
        super().__init__(f"articles with blob SHA {blob_sha!r} do not have the same content")


class ManifestOutdatedError(ConflictError):
    """A newer manifest of the version is already active; activating this one would go back."""

    def __init__(self, manifest_id: str) -> None:
        """Name the manifest.

        Args:
            manifest_id: The manifest that would replace a newer one.
        """
        super().__init__(f"manifest {manifest_id!r} is older than the active manifest")
        self.manifest_id = manifest_id


class LibraryAlreadyExistsError(ConflictError):
    """A library with this ID is already in the catalog."""

    code = "library_id_taken"

    def __init__(self, library_id: str) -> None:
        """Name the library ID taken.

        Args:
            library_id: The library ID.
        """
        super().__init__(f"library {library_id!r} already exists: choose another library ID")
        self.library_id = library_id


class LibraryNotEmptyError(ConflictError):
    """A library with imported versions cannot be discarded as if it were new."""

    code = "library_not_empty"

    def __init__(self, library_id: str) -> None:
        """Name the library.

        Args:
            library_id: The library ID.
        """
        super().__init__(f"library {library_id!r} has imported versions")
