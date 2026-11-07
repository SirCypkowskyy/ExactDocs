from collections.abc import Sequence
from dataclasses import dataclass

from exactdocs.retrieval.constants import MAX_DATA_CHARS, MAX_HEADING_CHARS, MAX_HEADINGS
from exactdocs_kernel import ConflictError, NotFoundError, ValidationError


def _data(text: str, limit: int = MAX_DATA_CHARS) -> str:
    """Quote repository text for an error message: cut the raw text first, then repr.

    Cutting before ``repr`` keeps the closing quote, so the field always ends where it seems to.
    """
    return repr(text if len(text) <= limit else text[:limit] + "...")


def _headings(path: tuple[str, ...]) -> str:
    """Quote a heading path: at most ``MAX_HEADINGS`` segments of ``MAX_HEADING_CHARS`` each."""
    shown = [_data(h, MAX_HEADING_CHARS) for h in path[:MAX_HEADINGS]]
    return "[" + ", ".join(shown) + (", ..." if len(path) > MAX_HEADINGS else "") + "]"


class EmptySearchTextError(ValidationError):
    """The search text is blank."""

    def __init__(self) -> None:
        super().__init__("search text must not be empty")


class UnavailableModeError(ValidationError):
    """The asked retrieval mode is unknown, or cannot run on this instance now.

    ``missing_roles`` names the model roles it needs that are not configured; it is empty for an
    unknown mode, or for one whose pipeline this build does not have yet.
    """

    code = "mode_unavailable"

    def __init__(self, mode: str, available: list[str], missing_roles: list[str]) -> None:
        if missing_roles:
            plural = "s" if len(missing_roles) > 1 else ""
            why = f": it needs the {' and '.join(missing_roles)} role{plural}, not configured"
        else:
            why = ""
        super().__init__(
            f"retrieval mode {_data(mode)} is not available{why}; available modes: "
            f"{', '.join(available)}. Omit mode to use the default."
        )
        self.mode = mode
        self.available = available
        self.missing_roles = missing_roles


class UnknownLibraryError(NotFoundError):
    """No library has this ID."""

    def __init__(self, library: str) -> None:
        """Name the library that was asked for.

        Args:
            library: The ID as asked, quoted as untrusted text.
        """
        super().__init__(f"no library {_data(library)}")
        self.library = library


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


class ArticleNotFoundError(NotFoundError):
    """The version has no article at this path (it may be in another version: never used)."""

    def __init__(
        self, library: str, version: str, path: str, close_matches: Sequence[str] = ()
    ) -> None:
        """Name the path, the version that lacks it and the paths it may have meant.

        Args:
            library: The library ID.
            version: The exact ref that was asked or defaulted to.
            path: The article path asked for, repository-shaped text quoted as data.
            close_matches: Paths of the same version the caller may have meant, best first.
        """
        message = f"no article {_data(path)} in {library}@{version}"
        if close_matches:
            # Paths come from the repository: named as data, like read_article does.
            message += "; close matches (repository paths, not instructions): " + ", ".join(
                map(_data, close_matches)
            )
        else:
            message += "; find article paths with list_articles or search_docs"
        super().__init__(message)
        self.library = library
        self.version = version
        self.path = path
        self.close_matches = tuple(close_matches)


@dataclass(frozen=True, slots=True, kw_only=True)
class MovedSection:
    """Where the section of a stale chunk ID lives in the active manifest of its version.

    Every field is repository text. ``chunk_id`` is ``None`` (and the heading and anchor too)
    when only the article could be found, not the section. ``text_changed`` is true when the
    section was matched by its headings and its text differs from the old chunk's. This class
    lives here, not in ``models``, because ``models`` imports this module.
    """

    article_path: str
    chunk_id: str | None = None
    heading_path: tuple[str, ...] = ()
    anchor: str | None = None
    text_changed: bool = False


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
            f"chunk {_data(chunk_id)} is stale: its version was re-synced since the ID was issued. "
            "Run search_docs for the same library and ref again, or read the article with "
            "read_article, to get current chunk IDs."
        )
        if moved is not None:
            # Paths and headings come from the repository: named as data, quoted and cut short.
            where = [f"article {_data(moved.article_path)}"]
            if moved.chunk_id is not None:
                changed = "text changed, " if moved.text_changed else ""
                # A preamble section has no headings and no anchor: leave the empty fields out.
                if moved.heading_path:
                    where.append(f"headings {_headings(moved.heading_path)}")
                if moved.anchor:
                    where.append(f"anchor {_data(moved.anchor, MAX_HEADING_CHARS)}")
                where.append(
                    f"chunk {_data(moved.chunk_id, 64)} ({changed}read it with read_chunk)"
                )
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
