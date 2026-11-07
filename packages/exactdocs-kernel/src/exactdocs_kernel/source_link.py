"""Links from a stored article or section back to the repository host, pinned to a commit."""

from urllib.parse import quote, urlsplit

from exactdocs_kernel.constants import _BLOB_PATHS, _SCP_URL


def _web_base(repository_url: str) -> str | None:
    """Return the repository's web page (`https://host/owner/repo`), or ``None`` without one."""
    url = repository_url.strip()
    if scp := _SCP_URL.fullmatch(url):
        scheme, host, path = "https", scp["host"], scp["path"]
    else:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https", "ssh"} or not parts.hostname:
            return None
        web = parts.scheme in {"http", "https"}
        scheme = parts.scheme if web else "https"
        host = parts.hostname + (f":{parts.port}" if web and parts.port else "")
        path = parts.path
    path = path.strip("/").removesuffix(".git")
    return f"{scheme}://{host}/{path}" if path else None


def section_link(
    host: str, repository_url: str, commit_sha: str, article_path: str, anchor: str = ""
) -> str | None:
    """Link to the article (or its section) at the commit, or ``None`` for unknown hosts.

    ``host`` is `github`, `gitlab`, `bitbucket`, `gitea` or `git` (no link). Pinned to the commit
    SHA, so the link keeps showing the text that was read.
    """
    blob = _BLOB_PATHS.get(host)
    base = _web_base(repository_url)
    if blob is None or base is None:
        return None
    link = f"{base}/{blob}/{commit_sha}/{quote(article_path)}"
    if not anchor:
        return link
    # Bitbucket prefixes the anchors of rendered Markdown headings.
    prefix = "markdown-header-" if host == "bitbucket" else ""
    return f"{link}#{quote(prefix + anchor)}"
