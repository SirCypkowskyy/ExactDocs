from exactdocs_kernel import ConflictError, NotFoundError, ValidationError


class EmptySearchTextError(ValidationError):
    """The search text is blank."""

    def __init__(self) -> None:
        super().__init__("search text must not be empty")


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
    """The version's active manifest has no chunk with this ID."""

    def __init__(self, library: str, version: str, chunk_id: str) -> None:
        super().__init__(f"no chunk {chunk_id!r} in {library}@{version}")
        self.chunk_id = chunk_id


class ChunkSetMismatchError(ConflictError):
    """A chunk set with this key is stored, but it holds different chunks.

    The chunker changed without a new ``config_hash``. Change the hash instead of reusing the set.
    """

    def __init__(self, blob_sha: str, config_hash: str) -> None:
        super().__init__(
            f"chunk set ({blob_sha!r}, {config_hash!r}) is stored with different chunks; "
            "give the new chunking a new config_hash"
        )
