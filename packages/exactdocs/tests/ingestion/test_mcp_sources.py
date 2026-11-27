"""What ``add_docs`` accepts as a source over MCP, and every class of URL it refuses (#613)."""

import pytest

from exactdocs.ingestion.adapters.driving.mcp import Source, check_addresses, parse_source
from exactdocs.ingestion.errors import SourceNotAllowedError

HOSTS = frozenset({"github.com", "gitlab.com"})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "https://github.com/fastapi/fastapi",
            Source(url="https://github.com/fastapi/fastapi", library="/fastapi/fastapi"),
        ),
        (
            " https://GitHub.com/FastAPI/FastAPI.git ",
            Source(url="https://GitHub.com/FastAPI/FastAPI.git", library="/fastapi/fastapi"),
        ),
        (
            "https://gitlab.com/group/sub/docs",
            Source(url="https://gitlab.com/group/sub/docs", library="/group/docs"),
        ),
        (
            "fastapi/fastapi",
            Source(url="https://github.com/fastapi/fastapi", library="/fastapi/fastapi"),
        ),
        ("/fastapi/fastapi", Source(library="/fastapi/fastapi")),
        ("FastAPI", Source(name="FastAPI")),
    ],
)
def test_a_source_is_a_url_a_shorthand_a_library_id_or_a_name(text: str, expected: Source) -> None:
    assert parse_source(text, hosts=HOSTS) == expected


@pytest.mark.parametrize(
    "text",
    [
        "file:///etc",
        "ssh://git@internal/x.git",
        "git@github.com:a/b.git",
        "http://github.com/a/b",
        "http://169.254.169.254/",
        "https://10.0.0.5/repo.git",
        "https://[::1]/a/b",
        "https://u:p@github.com/a/b",
        "https://token@github.com/a/b",
        "https://github.com:8443/a/b",
        "https://evil.example/a/b",
        "https://github.com.evil.example/a/b",
        "https://github.com/a/b?x=1",
        "ext::sh -c touch% /tmp/x",
        "-uhttps://github.com/a/b",
        "https://github.com/onlyowner",
    ],
)
def test_every_other_url_is_refused(text: str) -> None:
    with pytest.raises(SourceNotAllowedError) as refused:
        parse_source(text, hosts=HOSTS)
    assert refused.value.code == "source_not_allowed"


def test_the_shorthand_needs_github_in_the_allowed_hosts() -> None:
    with pytest.raises(SourceNotAllowedError):
        parse_source("fastapi/fastapi", hosts=frozenset({"gitlab.com"}))


async def test_a_public_address_passes() -> None:
    async def resolve(host: str) -> list[str]:
        del host
        return ["140.82.112.3", "2606:50c0:8000::153"]

    await check_addresses("github.com", resolve)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.1.2.3",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:10.0.0.5",
        "fd00:ec2::254",
    ],
)
async def test_a_name_that_resolves_to_a_private_address_is_refused(address: str) -> None:
    async def resolve(host: str) -> list[str]:
        del host
        return ["140.82.112.3", address]

    with pytest.raises(SourceNotAllowedError):
        await check_addresses("git.internal", resolve)


async def test_a_name_that_does_not_resolve_is_refused() -> None:
    async def resolve(host: str) -> list[str]:
        raise OSError(host)

    with pytest.raises(SourceNotAllowedError):
        await check_addresses("nowhere.invalid", resolve)
