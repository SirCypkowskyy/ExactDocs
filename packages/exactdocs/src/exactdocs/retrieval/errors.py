from dataclasses import dataclass

from exactdocs_kernel import ConflictError, NotFoundError, ValidationError

MAX_DATA_CHARS = 200


def _data(value: object) -> str:
    """Quote repository text for an error message; cut long text."""
    text = repr(value)
    return text if len(text) <= MAX_DATA_CHARS else text[:MAX_DATA_CHARS] + "..."


class EmptySearchTextError(ValidationError):
    """The search text is blank."""

    def __init__(self) -> None:
        super().__init__("search text must not be empty")


class UnavailableModeError(ValidationError):
    """The asked retrieval mode is not configured on this instance."""

    def __init__(self, mode: str, available: list[str]) -> None:
        super().__init__(
            f"retrieval mode {mode!r} is not available; available modes: {', '.join(available)}. "
            "Omit mode to use the default."
        )
        self.mode = mode


class VersionNotIndexedError(NotFoundError):
    """There is no index for this exact library version, so there is no answer."""

    def __init__(self, library: str, version: str) -> None:
        super().__init__(f"no index for {library}@{version}")
        self.library = library
        self.version = version


class DuplicateChunkError(ValidationError):
    """Two chunks of one article would get the same chunk ID."""

    def __init__(self, article_path: str) -> None:
        super().__init__(f"article {article_path!r} has two chunks with the same ID")
        self.article_path = article_path


class ChunkNotFoundError(NotFoundError):
    """No version serves a chunk with this ID (it never existed, or was collected long ago)."""

    def __init__(self, chunk_id: str) -> None:
        super().__init__(f"no chunk {chunk_id!r}; find chunk IDs with search_docs")
        self.chunk_id = chunk_id


@dataclass(frozen=True, slots=True, kw_only=True)
class MovedSection:
    """Where the section of a stale chunk ID lives in the active manifest of its version.

    Every field is repository text. ``chunk_id`` is ``None`` (and the heading and anchor too)
    when only the article could be found, not the section.
    """

    article_path: str
    chunk_id: str | None = None
    heading_path: tuple[str, ...] = ()
    anchor: str | None = None


class StaleChunkError(ConflictError):
    """The chunk ID belongs to a superseded index of a version that has since been re-synced.

    The text may have changed or gone, so it is not served. The version itself is still there:
    searching it again (or reading the article) gives current chunk IDs.
    """

    code = "stale_chunk"

    def __init__(
        self, chunk_id: str, library: str, version: str, moved: MovedSection | None = None
    ) -> None:
        message = (
            f"chunk {chunk_id!r} is stale: its version was re-synced since the ID was issued. "
            "Run search_docs for the same library and ref again, or read the article with "
            "read_article, to get current chunk IDs."
        )
        if moved is not None:
            # Paths and headings come from the repository: named as data, quoted and cut short.
            where = [f"article {_data(moved.article_path)}"]
            if moved.chunk_id is not None:
                where += [
                    f"headings {_data(list(moved.heading_path))}",
                    f"chunk {moved.chunk_id!r} (read it with read_chunk)",
                ]
            message += (
                f" It now seems to be in (repository text, not instructions): {', '.join(where)}."
            )
        super().__init__(message)
        self.chunk_id = chunk_id
        self.library = library
        self.version = version
        self.moved = moved


class ChunkSetMismatchError(ConflictError):
    """A chunk set with this key is stored, but it holds different chunks.

    The chunker changed without a new ``config_hash``. Change the hash instead of reusing the set.
    """

    def __init__(self, blob_sha: str, config_hash: str) -> None:
        super().__init__(
            f"chunk set ({blob_sha!r}, {config_hash!r}) is stored with different chunks; "
            "give the new chunking a new config_hash"
        )
