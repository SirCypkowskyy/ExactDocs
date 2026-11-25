"""The one meaning of a directory filter on article paths, shared by the catalog and retrieval.

``list_articles`` lists, and ``search_docs`` searches, the articles inside a ``path_prefix``
(#573): both read it with these two functions, so the same prefix keeps the same articles.
"""


def clean_path_prefix(value: str) -> str:
    """Drop ``.`` and empty segments (``./guide//x`` is ``guide/x``); refuse ``..``, backslashes.

    Args:
        value: The prefix as sent.

    Returns:
        The prefix, its segments joined by ``/``; empty for every article.

    Raises:
        ValueError: It holds a ``..`` segment or a backslash.
    """
    segments = [s for s in value.split("/") if s not in {"", "."}]
    if ".." in segments or "\\" in value:
        message = "path_prefix must be a plain `/`-separated directory"
        raise ValueError(message)
    return "/".join(segments)


def inside(path: str, prefix: str) -> bool:
    """Tell whether an article path is inside a cleaned prefix, matched literally by segment.

    ``guide`` holds ``guide/install.md`` (and an article named ``guide``), not ``guide-old/x.md``.

    Args:
        path: The article's path.
        prefix: A prefix from ``clean_path_prefix``; empty holds every path.

    Returns:
        True when the path is the prefix or below it.
    """
    return not prefix or path == prefix or path.startswith(f"{prefix}/")
