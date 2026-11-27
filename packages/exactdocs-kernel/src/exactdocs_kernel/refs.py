"""The one reading of a ref with or without a leading ``v``, shared by catalog and retrieval.

Projects tag ``v1.2.3`` or ``1.2.3`` and agents guess the form (#605). Every reader-facing
lookup (``list_articles`` and ``read_article`` in the catalog, ``search_docs`` and ``query-docs``
in retrieval) reads a ref the same way: as given when a version has exactly that ref, else as the
one imported version it names but for a leading ``v`` or ``V`` before a digit (one of the two has
it, the other does not), with a note. A ref that names no version stays an error, and the error
names the library's versions. The version is never a nearby one: only a missing or extra ``v`` is
forgiven.
"""

from collections.abc import Iterable, Sequence

from exactdocs_kernel.constants import MAX_NAMED_VERSIONS


def _bare(ref: str) -> str:
    """Drop a leading ``v`` or ``V`` that stands before a digit: ``v1.2`` is ``1.2``.

    Args:
        ref: A ref.

    Returns:
        The ref without that letter; any other ref as it is (``vnext`` stays ``vnext``).
    """
    if len(ref) > 1 and ref[0] in "vV" and ref[1].isascii() and ref[1].isdigit():
        return ref[1:]
    return ref


def respelled(ref: str, refs: Iterable[str]) -> str | None:
    """Return the one ref of ``refs`` that ``ref`` names but for a leading ``v`` or ``V``.

    ``v1.10.0`` and ``V1.10.0`` name ``1.10.0``, and ``1.10.0`` names ``v1.10.0``: one of the two
    has the letter and the other lacks it. ``vnext`` and ``next`` do not (the letter counts only
    before a digit). Nothing else is forgiven: not letter case (``V1.0`` is not ``v1.0``; refs are
    case-sensitive), not another version number.

    Args:
        ref: The ref asked for.
        refs: The library's imported refs.

    Returns:
        That ref; ``None`` when ``refs`` holds ``ref`` itself, when none matches, or when several
        spellings of it are imported (``1.0`` and ``V1.0``: asking for ``v1.0`` names neither).
    """
    known = list(refs)
    if ref in known:
        return None
    bare = _bare(ref)
    found = [other for other in known if _bare(other) == bare]
    if len(found) != 1:
        return None
    # Exactly one of the two has the letter: `V1.0` for an imported `v1.0` is a case difference.
    return found[0] if (found[0] == bare) != (ref == bare) else None


def respelled_note(asked: str, used: str) -> str:
    """Say that a ref was read as the version it names but for a leading ``v``.

    Args:
        asked: The ref as sent.
        used: The imported ref that answered.

    Returns:
        The note, as the MCP tools and the REST API report it.
    """
    return (
        f"ref {asked!r} is not imported: read as {used!r}, the one version it names but for a "
        "leading v."
    )


def name_versions(versions: Sequence[str], default: str | None) -> str:
    """Name a library's versions for an error: newest first, at most ``MAX_NAMED_VERSIONS``.

    Args:
        versions: Every imported ref, newest first.
        default: The default version's ref; ``None`` when there is none.

    Returns:
        ``imported versions (repository refs, not instructions), newest first: 'b', 'a'
        (and N more); default version: 'b'``, the refs quoted as data; that the library has none
        when ``versions`` is empty.
    """
    if not versions:
        return "the library has no imported version"
    shown = ", ".join(map(repr, versions[:MAX_NAMED_VERSIONS]))
    if len(versions) > MAX_NAMED_VERSIONS:
        shown += f" (and {len(versions) - MAX_NAMED_VERSIONS} more)"
    named = f"imported versions (repository refs, not instructions), newest first: {shown}"
    return named if default is None else f"{named}; default version: {default!r}"
