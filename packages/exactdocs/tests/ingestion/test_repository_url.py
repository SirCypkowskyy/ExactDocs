import pytest

from exactdocs.ingestion.errors import InvalidRepositoryUrlError
from exactdocs.ingestion.models import RepositoryHost, RepositoryUrl, branch_name


@pytest.mark.parametrize(
    ("url", "host", "library_id"),
    [
        ("https://github.com/acme/payments", RepositoryHost.GITHUB, "/acme/payments"),
        ("https://github.com/Acme/Payments.git", RepositoryHost.GITHUB, "/acme/payments"),
        ("https://github.com/acme/payments/", RepositoryHost.GITHUB, "/acme/payments"),
        ("https://bitbucket.org/acme/billing", RepositoryHost.BITBUCKET, "/acme/billing"),
        ("https://gitlab.com/acme/platform/sub/docs", RepositoryHost.GITLAB, "/acme/docs"),
        ("https://git.example.com/acme/handbook.git", RepositoryHost.GIT, "/acme/handbook"),
        ("https://gitea.com/acme/wiki", RepositoryHost.GITEA, "/acme/wiki"),
        ("https://gitea.example.com/acme/wiki", RepositoryHost.GIT, "/acme/wiki"),
        ("https://codeberg.org/acme/wiki", RepositoryHost.GITEA, "/acme/wiki"),
        ("https://gitlab.example.com/acme/wiki", RepositoryHost.GIT, "/acme/wiki"),
        ("https://github.evil.com/acme/wiki", RepositoryHost.GIT, "/acme/wiki"),
        ("https://h.example.com/A/B.GIT", RepositoryHost.GIT, "/a/b"),
        ("git@git.example.com:acme/payments.git", RepositoryHost.GIT, "/acme/payments"),
        ("git@github.com:acme/payments.git", RepositoryHost.GITHUB, "/acme/payments"),
        ("git@gitlab.com:acme/platform/docs.git", RepositoryHost.GITLAB, "/acme/docs"),
        ("ssh://git@git.example.com:2222/acme/payments.git", RepositoryHost.GIT, "/acme/payments"),
        ("ssh://git.example.com/acme/payments", RepositoryHost.GIT, "/acme/payments"),
        ("file:///srv/mirrors/fixture/docs-repo", RepositoryHost.GIT, "/fixture/docs-repo"),
        ("file://localhost/srv/fixture/docs-repo", RepositoryHost.GIT, "/fixture/docs-repo"),
        ("http://127.0.0.1:8080/fixture/docs-repo.git", RepositoryHost.GIT, "/fixture/docs-repo"),
        ("http://[::1]:8080/fixture/docs-repo.git", RepositoryHost.GIT, "/fixture/docs-repo"),
        ("HTTPS://GitHub.com/acme/payments", RepositoryHost.GITHUB, "/acme/payments"),
        ("  https://github.com/acme/payments\n", RepositoryHost.GITHUB, "/acme/payments"),
        ("https://github.com/acme/my%20docs", RepositoryHost.GITHUB, "/acme/my-docs"),
    ],
)
def test_common_urls_get_a_host_kind_and_a_library_id(
    url: str, host: RepositoryHost, library_id: str
) -> None:
    parsed = RepositoryUrl.parse(url)

    assert (parsed.host_kind, parsed.library_id) == (host, library_id)
    assert parsed.url == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "payments",
        "/srv/repos/payments",
        "./payments",
        "https://github.com/payments",  # no owner
        "https://github.com/",
        "https://github.com/acme/..",
        "https://github.com/../payments",
        "https://github.com/acme/%2e%2e",
        "https://github.com/acme/.git",
        "https://github.com/acme/payments?token=abc",
        "https://github.com/acme/payments#readme",
        "git@git.example.com:acme/payments.git?x=1",
        "git@git.example.com:acme/payments.git#x",
        # a link to a page of a flat host is not a repository (and must not collide with /acme/docs)
        "https://github.com/acme/payments/tree/main/docs",
        "https://bitbucket.org/acme/payments/src/main/docs",
        "git@github.com:acme/payments/docs.git",
        "https://git hub.com/acme/payments",
        "https://github.com:notaport/acme/payments",
        "https:///acme/payments",
        "https://exa_mple.com/acme/payments",
        # option injection
        "--upload-pack=touch /tmp/pwned",
        "-oProxyCommand=touch/tmp/pwned",
        "-u./x",
        "git@-oProxyCommand=x:acme/payments.git",
        "ssh://-oProxyCommand=x/acme/payments",
        "ssh://git@-oProxyCommand=x/acme/payments",
        # transports that run commands or are not offered
        "ext::sh -c touch% /tmp/pwned",
        "ext::sh",
        "fd::17/acme/payments",
        "git@ext::x",
        "git://github.com/acme/payments",
        "ftp://example.com/acme/payments",
        "javascript://github.com/acme/payments",
        # credentials never get stored or shown
        "https://token@github.com/acme/payments",
        "https://user:secret@github.com/acme/payments",
        "http://user:secret@127.0.0.1/acme/payments",
        "ssh://user:secret@git.example.com/acme/payments",
        "ssh://bad user@git.example.com/acme/payments",
        # file URLs have no remote host
        "file://evil.example.com/srv/acme/payments",
        "file://user@localhost/srv/acme/payments",
        "file:///payments",
        # control characters
        "https://github.com/acme/pay\x00ments",
        "https://github.com/acme/pay\nments",
    ],
)
def test_unusable_urls_are_refused(url: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        RepositoryUrl.parse(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:hunter2-secret@github.com/acme/payments",
        "https://ghp_TOKENVALUE@github.com/acme/payments",
        "ssh://git:hunter2-secret@git.example.com/acme/payments",
        "https://github.com/acme/payments?access_token=hunter2-secret",
        "ftp://hunter2-secret:x@example.com/a/b",
    ],
)
def test_errors_never_repeat_the_url(url: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError) as error:
        RepositoryUrl.parse(url)

    assert "hunter2" not in str(error.value)
    assert "TOKENVALUE" not in str(error.value)
    assert url not in str(error.value)


@pytest.mark.parametrize("name", ["main", "release/1.4", "feature/x-y_z", "v1.4.0", "ünï"])
def test_a_plausible_branch_name_is_kept(name: str) -> None:
    assert branch_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-oops",
        "a..b",
        "a b",
        "a\nb",
        "a\x1b[31mb",
        "a~1",
        "a^",
        "a:b",
        "a?",
        "a*",
        "a[b",
        "a\\b",
        "a//b",
        "/a",
        "a/",
        "a.",
        ".hidden",
        "a/.b",
        "a.lock",
        "a/b.lock",
        "a@{1}",
        "x" * 256,
    ],
)
def test_a_branch_name_git_would_refuse_or_that_is_hostile_is_dropped(name: str) -> None:
    assert branch_name(name) is None
