import pytest

from exactdocs.retrieval.models import SearchableVersion, SourceHost, source_link

SHA = "c" * 40


def link(
    host: SourceHost, url: str, path: str = "docs/a b.md", anchor: str = "intro"
) -> str | None:
    version = SearchableVersion(
        library="/o/r", version="v1", manifest_id="m", commit_sha=SHA, repository_url=url, host=host
    )
    return source_link(version, path, anchor)


@pytest.mark.parametrize(
    ("host", "url", "expected"),
    [
        (
            SourceHost.GITHUB,
            "https://github.com/o/r",
            f"https://github.com/o/r/blob/{SHA}/docs/a%20b.md#intro",
        ),
        (
            SourceHost.GITHUB,
            "git@github.com:o/r.git",
            f"https://github.com/o/r/blob/{SHA}/docs/a%20b.md#intro",
        ),
        (
            SourceHost.GITLAB,
            "https://gitlab.com/g/s/r.git",
            f"https://gitlab.com/g/s/r/-/blob/{SHA}/docs/a%20b.md#intro",
        ),
        (
            SourceHost.BITBUCKET,
            "https://bitbucket.org/o/r/",
            f"https://bitbucket.org/o/r/src/{SHA}/docs/a%20b.md#markdown-header-intro",
        ),
        (
            SourceHost.GITEA,
            "https://git.example.com:3000/o/r",
            f"https://git.example.com:3000/o/r/src/commit/{SHA}/docs/a%20b.md#intro",
        ),
        (
            SourceHost.GITEA,
            "ssh://git@git.example.com:2222/o/r.git",
            f"https://git.example.com/o/r/src/commit/{SHA}/docs/a%20b.md#intro",
        ),
    ],
)
def test_known_hosts_link_to_the_commit_and_the_section(
    host: SourceHost, url: str, expected: str
) -> None:
    assert link(host, url) == expected


@pytest.mark.parametrize(
    ("host", "url"),
    [
        (SourceHost.GIT, "https://git.example.com/o/r.git"),
        (SourceHost.GITHUB, "file:///srv/repos/r"),
        (SourceHost.GITHUB, "/srv/repos/r"),
    ],
)
def test_unknown_hosts_and_local_repositories_have_no_link(host: SourceHost, url: str) -> None:
    assert link(host, url) is None


def test_text_before_the_first_heading_links_to_the_file() -> None:
    assert link(SourceHost.GITHUB, "https://github.com/o/r", "README.md", "") == (
        f"https://github.com/o/r/blob/{SHA}/README.md"
    )
