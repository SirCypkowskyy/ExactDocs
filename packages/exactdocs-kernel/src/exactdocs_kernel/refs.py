"""The one meaning of a ref written with or without its leading ``v``, shared by every domain.

Agents write ``v1.10.0`` for a version a library imported as ``1.10.0``, and the other way round
(#606). The catalog (``read_article``, ``list_articles``) and retrieval (``search_docs``,
``article_outline``, ``query-docs``) read such a ref as the one imported ref that differs from it
only by the ``v`` in front of its version number, with these functions, so every tool answers the
same spelling from the same version. A different version number is never picked: ``v1.10`` is not
``1.10.0``. When nothing matches, ``closest_refs`` picks the refs the error names.
"""

import re
from collections.abc import Collection, Iterable
from difflib import SequenceMatcher

from exactdocs_kernel.constants import MAX_NAMED_REFS, VERSION_NUMBER


def other_v_spelling(ref: str) -> str | None:
    """Write a version-number ref the other way: its leading ``v`` dropped, or one added.

    Args:
        ref: A ref, as asked or as imported.

    Returns:
        ``1.10.0`` for ``v1.10.0``, ``v1.10.0`` for ``1.10.0``; ``None`` when the ref is no
        version number (``main``, ``vnext``, ``V1.0``, a short SHA such as ``1234abc``).
    """
    bare = _bare(ref)
    if not VERSION_NUMBER.fullmatch(bare):
        return None
    return bare if bare != ref else f"v{ref}"


def leading_v_twin(asked: str, refs: Collection[str]) -> str | None:
    """Find the imported ref that ``asked`` means when ``asked`` is not imported itself.

    Two refs can differ only by a leading ``v`` in one way at most (``v1.0`` has ``1.0``, never
    ``vv1.0``), so the match is never a choice between several.

    Args:
        asked: The ref as asked.
        refs: The library's imported refs.

    Returns:
        The imported ref that is ``asked`` with its version number's leading ``v`` dropped or
        added; ``None`` when ``asked`` is imported itself, or no imported ref is spelled that way.
    """
    if asked in refs:
        return None
    other = other_v_spelling(asked)
    return other if other is not None and other in refs else None


def respelled_note(asked: str | None, answered: str) -> str | None:
    """Say, for a result's notes, that the asked ref's other ``v`` spelling answered.

    Args:
        asked: The ref as asked; ``None`` for the default version.
        answered: The ref of the version that answered.

    Returns:
        The note; ``None`` when the ref answered as asked, or another version did (the default
        one, or a commit a short SHA names).
    """
    if asked is None or other_v_spelling(asked) != answered:
        return None
    how = "without the leading v" if asked.startswith("v") else "with a leading v"
    return f"ref {asked!r} is not imported: version {answered!r}, the same number {how}, answered."


def closest_refs(asked: str | None, refs: Iterable[str], limit: int = MAX_NAMED_REFS) -> list[str]:
    """Pick the refs an error names when a library has no version ``asked``.

    Args:
        asked: The ref asked for; ``None`` for the default version.
        refs: The library's imported refs.
        limit: The most refs returned.

    Returns:
        Every ref when there are ``limit`` or fewer, else the ``limit`` most like ``asked``
        (compared without a version number's leading ``v``). Most alike first, then the higher
        number first (``1.10.0`` before ``1.9.0``).
    """
    wanted = _bare(asked or "")
    newest_first = sorted(set(refs), key=lambda ref: _natural(_bare(ref)), reverse=True)
    alike = sorted(newest_first, key=lambda ref: -SequenceMatcher(None, wanted, _bare(ref)).ratio())
    return alike[:limit]


def _bare(ref: str) -> str:
    """Drop the ``v`` in front of a version number.

    Args:
        ref: A ref.

    Returns:
        ``1.10.0`` for ``v1.10.0``; any other ref as it is.
    """
    return ref[1:] if ref.startswith("v") and VERSION_NUMBER.fullmatch(ref[1:]) else ref


def _natural(ref: str) -> tuple[bool, tuple[tuple[int, int | str], ...]]:
    """Order refs by their numbers, not their characters, version numbers above other names.

    Args:
        ref: A ref, without a version number's leading ``v``.

    Returns:
        Whether it is a version number, then its runs of digits as numbers and the text between
        them, in order: ``1.10.0`` sorts above ``1.9.0``, and both above ``main``.
    """
    parts = tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", ref) if part
    )
    return VERSION_NUMBER.fullmatch(ref) is not None, parts
