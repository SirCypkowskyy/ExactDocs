"""The library and token commands: parsing, exit codes, safe output, README examples."""

import json
import re
import shlex
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.cli_library import (
    EXIT_AUTH,
    EXIT_CONFLICT,
    EXIT_FAILED,
    EXIT_IMPORT,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    ImportFailedError,
    exit_code,
    list_libraries,
    split_target,
    table,
    token_create,
    token_list,
    token_revoke,
    wait_for_job,
)
from exactdocs.bootstrap.client import ApiClient, ApiError, ClientError
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand

HORSE = "correct horse battery staple"


@pytest.fixture
async def transport() -> AsyncIterator[httpx2.ASGITransport]:
    container = Container.build(Settings())
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        yield httpx2.ASGITransport(app=create_app(container))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/Acme/Docs", ("Acme/Docs", None)),
        ("acme/docs/", ("acme/docs", None)),
        ("/acme/docs/v1.4.0", ("acme/docs", "v1.4.0")),
        ("acme/docs/release/1.4", ("acme/docs", "release/1.4")),
    ],
)
def test_a_target_is_a_library_with_an_optional_ref(text: str, expected: tuple[str, str]) -> None:
    assert split_target(text) == expected


@pytest.mark.parametrize("text", ["", "/", "acme", "/acme/"])
def test_a_target_without_owner_and_repo_is_refused(text: str) -> None:
    with pytest.raises(ClientError, match="not a library"):
        split_target(text)


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "unauthenticated", EXIT_AUTH),
        (404, "not_found", EXIT_NOT_FOUND),
        (409, "import_in_progress", EXIT_CONFLICT),
        (422, "invalid", EXIT_USAGE),
        (500, "boom", EXIT_FAILED),
    ],
)
def test_exit_codes_follow_the_kind_of_failure(status: int, code: str, expected: int) -> None:
    assert exit_code(ApiError(status, code, "")) == expected
    assert exit_code(ClientError("unreachable")) == EXIT_FAILED
    assert exit_code(ImportFailedError("x")) == EXIT_IMPORT


def test_control_characters_from_a_repository_never_reach_the_terminal() -> None:
    assert "\x1b" not in table(["A"], [["evil\x1b[2Jname"]])
    assert "\x1b" not in str(ApiError(409, "x", "bad \x1b]0;pwned\x07 ref"))


async def test_a_failed_job_ends_the_wait_with_its_reason() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        job = {"state": "failed", "done": 1, "total": 3, "error": "boom\x1b[31m"}
        return httpx2.Response(200, json=job)

    async with ApiClient("http://localhost", "t", transport=httpx2.MockTransport(handler)) as api:
        with pytest.raises(ImportFailedError, match="boom") as raised:
            await wait_for_job(api, "j1", label="/a/b@v1", interval=0)
    assert "\x1b" not in str(raised.value)


async def test_progress_is_reported_once_per_change() -> None:
    states = iter(
        [
            ("queued", 0, 0),
            ("running", 1, 4),
            ("running", 1, 4),
            ("running", 4, 4),
            ("succeeded", 4, 4),
        ]
    )

    def handler(_: httpx2.Request) -> httpx2.Response:
        state, done, total = next(states)
        return httpx2.Response(200, json={"state": state, "done": done, "total": total})

    seen: list[str] = []
    async with ApiClient("http://localhost", "t", transport=httpx2.MockTransport(handler)) as api:
        await wait_for_job(api, "j", label="x", progress=seen.append, interval=0)
    assert seen == [
        "x: queued",
        "x: running 1/4 files",
        "x: running 4/4 files",
        "x: succeeded 4/4 files",
    ]


async def test_tokens_are_managed_by_a_session_never_by_a_token(
    transport: httpx2.ASGITransport, capsys: pytest.CaptureFixture[str]
) -> None:
    async with ApiClient("http://localhost", transport=transport) as api:
        await api.sign_in("ada", HORSE)
        await token_create(api, "ci", None, as_json=True)
        created = json.loads(capsys.readouterr().out)
        await token_list(api, as_json=False)
        assert "ci" in capsys.readouterr().out
        await token_revoke(api, created["id"])
        await api.sign_out()
    async with ApiClient("http://localhost", created["token"], transport=transport) as api:
        with pytest.raises(ApiError) as refused:  # revoked, and a token could not list anyway
            await token_list(api, as_json=True)
    assert exit_code(refused.value) == EXIT_AUTH


async def test_an_empty_catalog_says_how_to_add(
    transport: httpx2.ASGITransport, capsys: pytest.CaptureFixture[str]
) -> None:
    async with ApiClient("http://localhost", transport=transport) as api:
        await api.sign_in("ada", HORSE)
        await list_libraries(api)
    assert "exactdocs add" in capsys.readouterr().out


# The README's `uvx exactdocs ...` examples must parse against the real command tree.
README = Path(__file__).parents[4] / "README.md"


def _readme_commands() -> list[str]:
    blocks = re.findall(r"```bash\n(.*?)```", README.read_text(encoding="utf-8"), re.DOTALL)
    lines = (line for block in blocks for line in block.splitlines())
    found = [re.sub(r"^.*?uvx ", "", line) for line in lines if r"uvx exactdocs " in line]
    return [re.sub(r"\s+#.*$", "", c).replace("uvx ", "") for c in found]


def test_the_readme_has_cli_examples_for_the_new_commands() -> None:
    names = {c.split()[1] for c in _readme_commands()}
    assert {"add", "libraries", "sync", "remove", "token", "version"} <= names


@pytest.mark.parametrize("command", _readme_commands())
def test_every_readme_cli_example_parses(command: str) -> None:
    words = shlex.split(command)[1:]
    if words[0] in {"serve", "admin"}:
        pytest.skip("local command")
    cli.app.parse_args(words, exit_on_error=False)
