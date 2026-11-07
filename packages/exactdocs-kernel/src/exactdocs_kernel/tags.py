"""The one form of an article tag, shared by ingestion (writes), catalog and retrieval (filter)."""

import unicodedata

from exactdocs_kernel.constants import _EXTRA, MAX_TAG_LENGTH


def normalize_tag(raw: str) -> str | None:
    """Return the tag in its one form, or ``None`` when ``raw`` cannot be a tag.

    NFKC, case-folded (``Straße`` is ``strasse``, final sigma folds), NFKC again, inner whitespace
    becomes ``-``. A tag starts with a letter or digit and goes on with letters, digits, combining
    marks (Devanagari, Arabic harakat...) and ``._+-``; at most ``MAX_TAG_LENGTH`` characters.
    Commas, invisible characters and symbols never survive, so a tag fits a comma-separated
    filter. Confusables (a Cyrillic and a Latin "a") stay distinct. Idempotent.
    """
    folded = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", raw).casefold())
    tag = "-".join(folded.split())
    if not tag or len(tag) > MAX_TAG_LENGTH or not tag[0].isalnum():
        return None
    ok = all(c.isalnum() or c in _EXTRA or unicodedata.category(c)[0] == "M" for c in tag)
    return tag if ok else None
