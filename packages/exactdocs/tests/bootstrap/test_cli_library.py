"""The library and token commands: parsing, exit codes, safe output, README examples."""

import asyncio
import io
import json
import os
import re
import shlex
from collections.abc import AsyncIterator, Coroutine
from pathlib import Path
from unittest.mock import patch

import httpx2
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.cli_library import (
    EXIT_AUTH,
    EXIT_CONFLICT,
    EXIT_FAILED,
    EXIT_IMPORT,
    EXIT_INTERRUPTED,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    ImportFailedError,
    UsageError,
    exit_code,
    list_libraries,
    read_secret,
    split_target,
    sync_library,
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


async def test_a_failed_job_names_its_error_code() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        job = {"state": "failed", "done": 0, "total": 0, "error": "gone", "error_code": "x\x1b"}
        return httpx2.Response(200, json=job)

    async with ApiClient("http://localhost", "t", transport=httpx2.MockTransport(handler)) as api:
        with pytest.raises(ImportFailedError, match=r"failed \[x.*\]: gone") as raised:
            await wait_for_job(api, "j1", label="/a/b@v1", interval=0)
    assert "\x1b" not in str(raised.value)


def _sync_answer(status: int, body: dict) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _: httpx2.Response(status, json=body))


async def test_a_sync_whose_remote_cannot_be_read_fails_with_its_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = {"error": "auth_failed", "detail": "the repository requires authentication"}
    async with ApiClient("http://localhost", "t", transport=_sync_answer(422, body)) as api:
        with pytest.raises(ImportFailedError) as raised:
            await sync_library(api, "/acme/docs")
    assert exit_code(raised.value) == EXIT_IMPORT
    assert "[auth_failed]: the repository requires authentication" in str(raised.value)
    assert not capsys.readouterr().out


async def test_a_sync_names_each_version_that_failed_and_why(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def version(ref: str, status: str, **error: str) -> dict:
        sha = "a" * 40
        return {"ref": ref, "ref_kind": "tag", "status": status, "commit_sha": sha} | error

    body = {
        "library_id": "/acme/docs",
        "versions": [
            version("main", "up_to_date"),
            version("v1", "failed", error_code="tag_moved", error="the tag 'v1' now points at"),
            version("old", "failed", error_code="ref_deleted", error="the branch 'old' is gone"),
        ],
    }
    async with ApiClient("http://localhost", "t", transport=_sync_answer(200, body)) as api:
        with pytest.raises(ImportFailedError) as raised:
            await sync_library(api, "/acme/docs")
    message = str(raised.value)
    assert "sync of v1 failed [tag_moved]: the tag 'v1' now points at" in message
    assert "sync of old failed [ref_deleted]" in message
    assert exit_code(raised.value) == EXIT_IMPORT
    assert "tag_moved" not in capsys.readouterr().out  # the table, then the reason on stderr


def _moved_tag_sync(reimport: httpx2.Response) -> tuple[httpx2.MockTransport, list[str]]:
    """A sync that reports ``v1`` as moved, and ``reimport`` as the answer to re-importing it."""
    asked: list[str] = []
    sha = "a" * 40
    body = {
        "library_id": "/acme/docs",
        "versions": [
            {"ref": "main", "ref_kind": "branch", "status": "up_to_date", "commit_sha": sha},
            {
                "ref": "v1",
                "ref_kind": "tag",
                "status": "failed",
                "commit_sha": sha,
                "error_code": "tag_moved",
                "error": "the tag 'v1' now points at commit b",
            },
        ],
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(f"{request.method} {request.url.path} {request.content.decode()}".strip())
        if request.url.path.endswith("/sync"):
            return httpx2.Response(200, json=body)
        return reimport

    return httpx2.MockTransport(handler), asked


async def test_confirm_re_imports_each_moved_tag_and_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reimported = {"ref": "v1", "commit_sha": "b" * 40, "job_id": "j9"}
    transport, asked = _moved_tag_sync(httpx2.Response(202, json=reimported))
    async with ApiClient("http://localhost", "t", transport=transport) as api:
        await sync_library(api, "/acme/docs", confirm=True, as_json=True)

    assert asked == [
        "POST /api/v1/libraries/acme/docs/sync",
        'POST /api/v1/libraries/acme/docs/versions/reimport {"ref":"v1"}',
    ]
    by_ref = {v["ref"]: v for v in json.loads(capsys.readouterr().out)["versions"]}
    assert (by_ref["v1"]["status"], by_ref["v1"]["commit_sha"], by_ref["v1"]["job_id"]) == (
        "queued",
        "b" * 40,
        "j9",
    )


async def test_a_refused_confirmation_leaves_the_tag_failed_with_the_refusal() -> None:
    refused = {"error": "tag_not_moved", "detail": "the tag 'v1' still points at commit a"}
    transport, _ = _moved_tag_sync(httpx2.Response(409, json=refused))
    async with ApiClient("http://localhost", "t", transport=transport) as api:
        with pytest.raises(ImportFailedError) as raised:
            await sync_library(api, "/acme/docs", confirm=True)

    assert "sync of v1 failed [tag_not_moved]: the tag 'v1' still points" in str(raised.value)
    assert exit_code(raised.value) == EXIT_IMPORT


async def test_without_confirm_a_moved_tag_is_not_re_imported_and_the_way_is_named() -> None:
    transport, asked = _moved_tag_sync(httpx2.Response(500))
    async with ApiClient("http://localhost", "t", transport=transport) as api:
        with pytest.raises(ImportFailedError) as raised:
            await sync_library(api, "/acme/docs")

    assert asked == ["POST /api/v1/libraries/acme/docs/sync"]
    assert "exactdocs sync /acme/docs --confirm" in str(raised.value)


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
    assert len(_readme_commands()) >= 15
    names = {c.split()[1] for c in _readme_commands()}
    assert {"add", "libraries", "sync", "remove", "token", "version"} <= names


@pytest.mark.parametrize("command", _readme_commands())
def test_every_readme_cli_example_parses(command: str) -> None:
    words = shlex.split(command)[1:]
    if words[0] in {"serve", "admin"}:
        pytest.skip("local command")
    cli.app.parse_args(words, exit_on_error=False)
    path = [w for w in words if not w.startswith("-")][:2]  # `token create`, `add`, ...
    resolved = cli.app.parse_commands(path[:2] if path[0] in {"token", "version"} else path[:1])
    assert resolved[0]  # the command path of the example resolves


# --- secret files ---------------------------------------------------------------------------


def _secret(tmp_path: Path, content: str, mode: int = 0o600) -> str:
    path = tmp_path / "secret"
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return str(path)


def test_a_secret_is_read_whole(tmp_path: Path) -> None:
    assert read_secret(_secret(tmp_path, "tok\n")) == "tok\n"


def test_a_secret_over_the_cap_is_refused_not_cut_off(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="not a token or key"):
        read_secret(_secret(tmp_path, "x" * (64 * 1024 + 1)))
    assert len(read_secret(_secret(tmp_path, "x" * 64 * 1024))) == 64 * 1024


@pytest.mark.parametrize("content", ["", " \n\t"])
def test_an_empty_secret_is_refused(tmp_path: Path, content: str) -> None:
    with pytest.raises(UsageError, match="is empty"):
        read_secret(_secret(tmp_path, content))


def test_a_directory_or_a_fifo_is_not_a_secret(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match=r"not a regular file|cannot read"):
        read_secret(str(tmp_path))
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(UsageError, match="not a regular file"):
        read_secret(str(fifo))


def test_a_missing_or_binary_file_names_the_file_not_the_content(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match=r"cannot read .*nope"):
        read_secret(str(tmp_path / "nope"))
    binary = tmp_path / "bin"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(UsageError, match="UnicodeDecodeError"):
        read_secret(str(binary))


def test_a_readable_by_others_secret_warns_without_the_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert read_secret(_secret(tmp_path, "s3cret-value", 0o644)) == "s3cret-value"
    err = capsys.readouterr().err
    assert "readable by others" in err
    assert "s3cret-value" not in err


# --- the commands, against a recording server ---------------------------------------------


class Recorder:
    """A fake server: records each request and answers from ``routes``."""

    def __init__(self, routes: dict[tuple[str, str], list[httpx2.Response]]) -> None:
        self.routes = routes
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answers = self.routes[request.method, request.url.path]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    @property
    def calls(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> object:
    """Point the CLI at a fake server and an empty config; set routes with ``server.use``."""
    recorder = Recorder({})
    real = cli.ApiClient

    def build(url: str, token: str | None = None) -> ApiClient:
        return real(url, token, transport=httpx2.MockTransport(recorder))

    monkeypatch.setattr(cli, "ApiClient", build)
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(tmp_path / "none.json"))
    monkeypatch.setenv("EXACTDOCS_URL", "http://localhost:3000")
    monkeypatch.setenv("EXACTDOCS_TOKEN", "exd_apitoken")
    return recorder


ADDED = {
    "library_id": "/a/b",
    "ref": "v1",
    "ref_kind": "tag",
    "commit_sha": "0123456789abcdef",
    "job_id": "j1",
}
SESSION = {"state": "signed_in"}


def _exit(args: list[str], stdin: str = "") -> int:
    with patch("sys.stdin", io.StringIO(stdin)):
        try:
            cli.app(args, exit_on_error=False, result_action="return_value")
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
    return 0


def test_both_credential_flags_are_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = _exit(["add", "https://x.io/a/b", "--git-token-file", "t", "--ssh-key", "k"])
    assert code == EXIT_USAGE
    assert "not both" in capsys.readouterr().err


def test_an_unreadable_credential_file_is_a_usage_error_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = str(tmp_path / "no-such-key")
    assert _exit(["add", "https://x.io/a/b", "--ssh-key", missing]) == EXIT_USAGE
    assert "no-such-key" in capsys.readouterr().err
    assert _exit(["version", "add", "/a/b", "v2", "--git-token-file", missing]) == EXIT_USAGE


def test_a_credential_goes_through_a_session_never_the_api_token(
    server: Recorder, tmp_path: Path
) -> None:
    key = _secret(tmp_path, "-----BEGIN KEY-----\n")
    server.routes = {
        ("POST", "/api/v1/session"): [httpx2.Response(201, json=SESSION)],
        ("POST", "/api/v1/libraries"): [httpx2.Response(201, json=ADDED)],
        ("DELETE", "/api/v1/session"): [httpx2.Response(204)],
    }
    args = [
        "add",
        "ssh://git@x.io/a/b.git",
        "--ssh-key",
        key,
        "--username",
        "ada",
        "--password-stdin",
    ]
    assert _exit(args, HORSE + "\n") == 0
    assert server.calls == [
        "POST /api/v1/session",
        "POST /api/v1/libraries",
        "DELETE /api/v1/session",
    ]
    assert all("authorization" not in r.headers for r in server.requests)
    body = json.loads(server.requests[1].content)
    assert body["credential"] == {"kind": "ssh_key", "private_key": "-----BEGIN KEY-----\n"}


def test_a_token_credential_carries_its_user(server: Recorder, tmp_path: Path) -> None:
    server.routes = {
        ("POST", "/api/v1/session"): [httpx2.Response(201, json=SESSION)],
        ("POST", "/api/v1/libraries/a/b/versions"): [httpx2.Response(202, json=ADDED)],
        ("DELETE", "/api/v1/session"): [httpx2.Response(204)],
    }
    args = ["version", "add", "/a/b", "v1", "--git-token-file", _secret(tmp_path, "tok\n"),
            "--git-user", "bob", "--username", "ada", "--password-stdin"]  # fmt: skip
    assert _exit(args, HORSE + "\n") == 0
    credential = json.loads(server.requests[1].content)["credential"]
    assert credential == {"kind": "token", "token": "tok", "username": "bob"}


def test_the_session_ends_even_when_the_command_fails(server: Recorder, tmp_path: Path) -> None:
    server.routes = {
        ("POST", "/api/v1/session"): [httpx2.Response(201, json=SESSION)],
        ("POST", "/api/v1/libraries"): [
            httpx2.Response(422, json={"error": "invalid_tag", "detail": "bad"})
        ],
        ("DELETE", "/api/v1/session"): [httpx2.Response(204)],
    }
    args = ["add", "https://x.io/a/b", "--git-token-file", _secret(tmp_path, "t"),
            "--username", "ada", "--password-stdin"]  # fmt: skip
    assert _exit(args, HORSE + "\n") == EXIT_USAGE
    assert server.calls[-1] == "DELETE /api/v1/session"


def test_a_failed_sign_out_is_a_warning(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    server.routes = {
        ("POST", "/api/v1/session"): [httpx2.Response(201, json=SESSION)],
        ("GET", "/api/v1/tokens"): [httpx2.Response(200, json={"tokens": []})],
        ("DELETE", "/api/v1/session"): [httpx2.Response(500, text="boom")],
    }
    assert _exit(["token", "list", "--username", "ada", "--password-stdin"], HORSE + "\n") == 0
    assert "could not end the session" in capsys.readouterr().err


def _job(state: str, **extra: object) -> httpx2.Response:
    return httpx2.Response(
        200, json={"state": state, "done": 1, "total": 2, "problems": [], **extra}
    )


def test_wait_that_ends_in_a_failed_job_exits_6(server: Recorder) -> None:
    server.routes = {
        ("POST", "/api/v1/libraries"): [httpx2.Response(201, json=ADDED)],
        ("GET", "/api/v1/jobs/j1"): [_job("failed", error="boom")],
    }
    assert _exit(["add", "https://x.io/a/b", "--wait"]) == EXIT_IMPORT


def test_a_4xx_while_polling_says_the_job_may_still_run(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    gone = httpx2.Response(404, json={"error": "not_found", "detail": "no job"})
    server.routes = {
        ("POST", "/api/v1/libraries"): [httpx2.Response(201, json=ADDED)],
        ("GET", "/api/v1/jobs/j1"): [gone],
    }
    assert _exit(["add", "https://x.io/a/b", "--wait"]) == EXIT_IMPORT
    assert "may still be running" in capsys.readouterr().err


def test_remove_asks_on_stderr_and_a_bad_target_is_refused_first(
    server: Recorder, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = io.StringIO("n\n")
    answer.isatty = lambda: True  # ty: ignore[invalid-assignment]
    monkeypatch.setattr("sys.stdin", answer)
    with pytest.raises(SystemExit) as raised:
        cli.app(["remove", "/a/b", "--json"], exit_on_error=False)
    out = capsys.readouterr()
    assert raised.value.code == EXIT_FAILED
    assert not out.out
    assert "Remove /a/b" in out.err
    assert server.requests == []
    assert _exit(["remove", "justone", "--yes"]) == EXIT_USAGE


@pytest.mark.parametrize("args", [["sync", "/a/b/v1"], ["version", "add", "/a/b/v1", "v2"]])
def test_a_ref_where_a_library_is_expected_is_a_usage_error(
    server: Recorder, args: list[str]
) -> None:
    assert _exit(args) == EXIT_USAGE
    assert server.requests == []


# --- waiting --------------------------------------------------------------------------------


async def test_a_job_that_never_ends_is_left_to_the_server_after_the_timeout() -> None:
    queued = httpx2.MockTransport(lambda _: _job("queued"))
    async with ApiClient("http://localhost", "t", transport=queued) as api:
        with pytest.raises(ImportFailedError, match="keeps running on the server"):
            await wait_for_job(api, "j9", label="x", interval=0.01, give_up_after=0.05)


async def test_a_transient_poll_error_is_retried_but_not_forever() -> None:
    answers = iter([httpx2.Response(502), httpx2.Response(502), _job("succeeded")])
    flaky = httpx2.MockTransport(lambda _: next(answers))
    async with ApiClient("http://localhost", "t", transport=flaky) as api:
        job = await wait_for_job(api, "j", label="x", interval=0)
    assert job["state"] == "succeeded"
    down = httpx2.MockTransport(lambda _: httpx2.Response(502))
    async with ApiClient("http://localhost", "t", transport=down) as api:
        with pytest.raises(ImportFailedError, match="lost track of job j"):
            await wait_for_job(api, "j", label="x", interval=0)


async def test_an_unknown_job_state_is_an_error_not_an_endless_wait() -> None:
    odd = httpx2.MockTransport(lambda _: _job("paused"))
    async with ApiClient("http://localhost", "t", transport=odd) as api:
        with pytest.raises(ClientError, match="unknown state 'paused'"):
            await wait_for_job(api, "j", label="x", interval=0)


async def test_interrupting_a_wait_says_the_job_keeps_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    queued = httpx2.MockTransport(lambda _: _job("running"))
    async with ApiClient("http://localhost", "t", transport=queued) as api:
        task = asyncio.create_task(wait_for_job(api, "j7", label="x", interval=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert "job j7 keeps running on the server" in capsys.readouterr().err


def test_ctrl_c_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(work: Coroutine[object, object, object]) -> None:
        work.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", interrupted)
    monkeypatch.setenv("EXACTDOCS_URL", "http://localhost")
    monkeypatch.setenv("EXACTDOCS_TOKEN", "t")
    assert _exit(["libraries"]) == EXIT_INTERRUPTED


# --- add --dry-run ----------------------------------------------------------------------------

PREVIEW = {
    "ref": "v1",
    "ref_kind": "tag",
    "commit_sha": "0123456789abcdef",
    "files": ["docs/a.md", "docs/b.md"],
    "total": 2,
    "truncated": False,
}
ADD_ARGS = ["https://x.io/a/b", "--ref", "v1", "--path", "docs/**", "--path", "README.md",
            "--exclude", "docs/old/**"]  # fmt: skip


def test_a_dry_run_sends_what_add_would_and_stores_nothing(server: Recorder) -> None:
    server.routes = {
        ("POST", "/api/v1/libraries"): [httpx2.Response(201, json=ADDED)],
        ("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=PREVIEW)],
    }
    assert _exit(["add", *ADD_ARGS]) == 0
    assert _exit(["add", *ADD_ARGS, "--id", "/a/b", "--tag-rule", "x=y", "--dry-run"]) == 0
    assert server.calls == ["POST /api/v1/libraries", "POST /api/v1/repositories/preview"]
    added, previewed = (json.loads(r.content) for r in server.requests)
    same = ("url", "ref", "include_paths", "exclude_paths")
    assert {k: previewed[k] for k in same} == {k: added[k] for k in same}
    assert set(previewed) == set(same)  # nothing that only matters to a stored library


def test_a_dry_run_prints_the_files_and_their_count_but_no_sizes(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    server.routes = {("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=PREVIEW)]}
    assert _exit(["add", *ADD_ARGS, "--dry-run"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "Dry run of v1 (tag, 012345678): an import would take 2 files. Nothing stored.",
        "docs/a.md",
        "docs/b.md",
    ]


def test_a_cut_list_says_truncated(server: Recorder, capsys: pytest.CaptureFixture[str]) -> None:
    cut = PREVIEW | {"files": ["docs/a.md"], "total": 1500, "truncated": True}
    server.routes = {("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=cut)]}
    assert _exit(["add", *ADD_ARGS, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "1500 files" in out
    assert out.splitlines()[-1] == "... truncated: 1 of 1500 files listed."


def test_a_dry_run_matching_nothing_says_which_flags_to_check(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = PREVIEW | {"files": [], "total": 0}
    server.routes = {("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=empty)]}
    assert _exit(["add", *ADD_ARGS, "--dry-run"]) == 0
    assert "no file matches; check --path and --exclude" in capsys.readouterr().out


def test_a_dry_run_in_json_is_the_preview_as_the_server_sent_it(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    server.routes = {("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=PREVIEW)]}
    assert _exit(["add", *ADD_ARGS, "--dry-run", "--json", "--wait"]) == 0
    assert json.loads(capsys.readouterr().out) == PREVIEW
    assert server.calls == ["POST /api/v1/repositories/preview"]  # --wait has nothing to follow


def test_a_path_from_the_repository_cannot_drive_the_terminal(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = PREVIEW | {"files": ["docs/\x1b[2Jevil.md"], "total": 1}
    server.routes = {("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=hostile)]}
    assert _exit(["add", *ADD_ARGS, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "docs/[2Jevil.md" in out


def test_busy_previews_are_reported_as_try_again(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    busy = httpx2.Response(
        429,
        json={"error": "preview_busy", "detail": "too many previews are running"},
        headers={"Retry-After": "5"},
    )
    server.routes = {("POST", "/api/v1/repositories/preview"): [busy]}
    assert _exit(["add", *ADD_ARGS, "--dry-run"]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert "try again" in err
    assert "in 5 seconds" in err


def test_a_dry_run_of_a_private_repository_goes_through_a_session(
    server: Recorder, tmp_path: Path
) -> None:
    server.routes = {
        ("POST", "/api/v1/session"): [httpx2.Response(201, json=SESSION)],
        ("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=PREVIEW)],
        ("DELETE", "/api/v1/session"): [httpx2.Response(204)],
    }
    args = ["add", "https://x.io/a/b", "--dry-run", "--git-token-file", _secret(tmp_path, "tok"),
            "--username", "ada", "--password-stdin"]  # fmt: skip
    assert _exit(args, HORSE + "\n") == 0
    assert server.calls[1] == "POST /api/v1/repositories/preview"
    assert all("authorization" not in r.headers for r in server.requests)
    assert json.loads(server.requests[1].content)["credential"] == {"kind": "token", "token": "tok"}


def test_a_malformed_tag_rule_fails_the_dry_run_before_any_request(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    server.routes = {("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=PREVIEW)]}
    assert _exit(["add", *ADD_ARGS, "--tag-rule", "bogus", "--dry-run"]) == EXIT_USAGE
    assert "'bogus' is not a tag rule" in capsys.readouterr().err
    assert server.calls == []
    assert _exit(["add", *ADD_ARGS, "--tag-rule", "docs/api/**=api", "--dry-run"]) == 0


def test_a_commit_ref_is_not_followed_by_its_own_short_sha(
    server: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    pinned = PREVIEW | {"ref": sha, "ref_kind": "commit", "commit_sha": sha}
    server.routes = {("POST", "/api/v1/repositories/preview"): [httpx2.Response(200, json=pinned)]}
    assert _exit(["add", "https://x.io/a/b", "--ref", sha, "--dry-run"]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith(f"Dry run of {sha} (commit): ")
