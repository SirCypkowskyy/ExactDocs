"""``exactdocs sources plan|apply``: reading the YAML, the diff, ``--json`` and exit codes."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap import cli, cli_library
from exactdocs.bootstrap import client as client_module
from exactdocs.bootstrap.cli_library import (
    SourcesFailedError,
    UsageError,
    apply_sources,
    exit_code,
    plan_sources,
    read_sources,
)
from exactdocs.bootstrap.client import ApiClient, ApiError, ClientError
from exactdocs.bootstrap.constants import (
    EXIT_AUTH,
    EXIT_FAILED,
    EXIT_USAGE,
    LOCAL_COMMANDS,
    MAX_SOURCES_BYTES,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand
from fixture_repo import DocsRepo

HORSE = "correct horse battery staple"


@pytest.fixture
async def transport() -> AsyncIterator[httpx2.ASGITransport]:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        yield httpx2.ASGITransport(app=create_app(container))


@pytest.fixture
async def api(transport: httpx2.ASGITransport) -> AsyncIterator[ApiClient]:
    async with ApiClient("http://localhost", transport=transport) as client:
        await client.sign_in("ada", HORSE)
        yield client


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "exactdocs.sources.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _file(tmp_path: Path, docs_repo: DocsRepo, refs: str = "[main]") -> str:
    return _write(
        tmp_path,
        "# yaml-language-server: $schema=../docs/schemas/exactdocs.sources.schema.json\n"
        "version: 1\n"
        "libraries:\n"
        f"  - url: {docs_repo.file_url}\n"
        f"    refs: {refs}\n"
        "    include_paths: [docs]\n"
        "    auto_sync: {tag_pattern: 'v*'}\n",
    )


async def test_plan_prints_the_diff_and_apply_twice_reports_no_changes(
    api: ApiClient, tmp_path: Path, docs_repo: DocsRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _file(tmp_path, docs_repo)

    await plan_sources(api, path, prune=False, as_json=False)
    planned = capsys.readouterr().out
    await apply_sources(api, path, prune=False, as_json=False)
    applied = capsys.readouterr().out
    await apply_sources(api, path, prune=False, as_json=False)
    again = capsys.readouterr().out

    assert "create:\n  + /fixture/docs-repo  (main)" in planned
    assert "created" in applied
    assert "unchanged:\n  = /fixture/docs-repo" in again
    assert "No changes." in again
    assert "created" not in again


async def test_json_output_is_the_servers_answer(
    api: ApiClient, tmp_path: Path, docs_repo: DocsRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _file(tmp_path, docs_repo)

    await plan_sources(api, path, prune=True, as_json=True)
    plan = json.loads(capsys.readouterr().out)
    await apply_sources(api, path, prune=False, as_json=True)
    applied = json.loads(capsys.readouterr().out)

    assert (plan["prune"], [c["id"] for c in plan["create"]]) == (True, ["/fixture/docs-repo"])
    assert [(r["library_id"], r["action"]) for r in applied["results"]] == [
        ("/fixture/docs-repo", "created")
    ]


async def test_a_failed_library_exits_1_after_every_outcome_is_printed(
    api: ApiClient, tmp_path: Path, docs_repo: DocsRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _file(tmp_path, docs_repo, refs="[main, no-such-tag]")

    with pytest.raises(SourcesFailedError) as failed:
        await apply_sources(api, path, prune=False, as_json=False)

    captured = capsys.readouterr()
    assert exit_code(failed.value) == EXIT_FAILED
    assert "created" in captured.out
    assert "unknown_ref" in captured.err


async def test_a_file_the_server_refuses_exits_2(
    api: ApiClient, tmp_path: Path, docs_repo: DocsRepo
) -> None:
    path = _file(tmp_path, docs_repo, refs="[abc1234]")  # a short SHA

    with pytest.raises(ApiError) as refused:
        await plan_sources(api, path, prune=False, as_json=False)

    assert (refused.value.status, exit_code(refused.value)) == (422, EXIT_USAGE)


async def test_without_a_session_or_token_it_exits_5(
    transport: httpx2.ASGITransport, tmp_path: Path, docs_repo: DocsRepo
) -> None:
    async with ApiClient("http://localhost", transport=transport) as anonymous:
        with pytest.raises(ApiError) as refused:
            await plan_sources(anonymous, _file(tmp_path, docs_repo), prune=False, as_json=False)

    assert exit_code(refused.value) == EXIT_AUTH


@pytest.mark.parametrize(
    "text",
    ["version: 1\nlibraries: [\n", "- just\n- a list\n", "plain text"],
)
def test_a_file_that_is_not_a_yaml_mapping_is_a_usage_error(tmp_path: Path, text: str) -> None:
    with pytest.raises(UsageError) as refused:
        read_sources(_write(tmp_path, text))

    assert exit_code(refused.value) == EXIT_USAGE


def test_a_file_over_the_cap_or_missing_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="KB"):
        read_sources(_write(tmp_path, "#" * (MAX_SOURCES_BYTES + 1)))
    with pytest.raises(UsageError, match="cannot read"):
        read_sources(str(tmp_path / "none.yaml"))


@pytest.mark.parametrize(
    ("text", "line"),
    [
        # A small alias bomb: each level doubles the one before it.
        (
            (
                "version: 1\n"
                "a: &a [x, x]\n"
                "b: &b [*a, *a]\n"
                "c: &c [*b, *b]\n"
                "d: &d [*c, *c]\n"
                "libraries: [*d, *d]\n"
            ),
            2,
        ),
        # An anchor on its own is refused too: a sources file has no use for one.
        ("version: 1\nlibraries:\n  - &lib {url: https://github.com/a/b, refs: [v1]}\n", 3),
    ],
)
def test_yaml_anchors_and_aliases_are_a_usage_error(tmp_path: Path, text: str, line: int) -> None:
    with pytest.raises(UsageError, match=f"anchor or alias at line {line}") as refused:
        read_sources(_write(tmp_path, text))

    assert exit_code(refused.value) == EXIT_USAGE


def test_a_yaml_date_is_sent_as_text_for_the_server_to_judge(tmp_path: Path) -> None:
    loaded = read_sources(_write(tmp_path, "version: 1\nlibraries: [{refs: [2024-01-01]}]\n"))

    assert loaded["libraries"][0]["refs"] == ["2024-01-01"]


def test_the_commands_are_remote_and_parse() -> None:
    assert not {"sources plan", "sources apply"} & LOCAL_COMMANDS
    for line in ("sources plan f.yaml --json", "sources apply f.yaml --prune --json"):
        cli.app.parse_args(line.split(), exit_on_error=False)


def _applied(libraries: list[str]) -> dict[str, object]:
    """The server's answer to applying a file that creates ``libraries``."""
    return {
        "plan": {
            "create": [{"id": library, "refs": ["main"]} for library in libraries],
            "update": [],
            "unchanged": [],
            "undeclared": [],
            "errors": [],
            "changes": len(libraries),
        },
        "results": [
            {"library_id": library, "action": "created", "jobs": ["j1"], "error": None}
            for library in libraries
        ],
        "failed": 0,
    }


@asynccontextmanager
async def _slow_server(delay: float, answer: object) -> AsyncGenerator[str]:
    """A real HTTP server on loopback that takes ``delay`` seconds to answer any request."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        lengths = [
            int(line.split(b":", 1)[1])
            for line in head.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        ]
        await reader.readexactly(lengths[0] if lengths else 0)
        await asyncio.sleep(delay)
        body = json.dumps(answer).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
            + f"content-length: {len(body)}\r\nconnection: close\r\n\r\n".encode()
            + body
        )
        with suppress(ConnectionError):
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


def _many(tmp_path: Path, count: int) -> tuple[str, list[str]]:
    entries = "".join(
        f"  - url: https://github.com/owner/repo-{n}\n    refs: [main]\n" for n in range(count)
    )
    path = _write(tmp_path, f"version: 1\nlibraries:\n{entries}")
    return path, [f"/owner/repo-{n}" for n in range(count)]


def _budget(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Shrink one request's timeout and the per-library allowance to ``seconds`` each."""
    monkeypatch.setattr(client_module, "TIMEOUT_SECONDS", seconds)
    monkeypatch.setattr(cli_library, "TIMEOUT_SECONDS", seconds)
    monkeypatch.setattr(cli_library, "SOURCES_SECONDS_PER_LIBRARY", seconds)


async def test_apply_waits_as_long_as_the_file_needs_not_one_requests_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # #422: the server creates the libraries one by one and answers when all are done; a client
    # that gives up after one request's timeout reports a failure for work that succeeded.
    _budget(monkeypatch, 0.2)
    path, libraries = _many(tmp_path, 5)  # 0.2 + 5 x 0.2 = 1.2 s

    async with _slow_server(0.6, _applied(libraries)) as url, ApiClient(url, token="t") as api:
        await apply_sources(api, path, prune=False, as_json=True)

    applied = json.loads(capsys.readouterr().out)
    assert [r["action"] for r in applied["results"]] == ["created"] * 5


async def test_plan_waits_as_long_as_the_file_needs_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _budget(monkeypatch, 0.2)
    path, libraries = _many(tmp_path, 5)

    async with (
        _slow_server(0.6, _applied(libraries)["plan"]) as url,
        ApiClient(url, token="t") as api,
    ):
        await plan_sources(api, path, prune=False, as_json=True)

    assert len(json.loads(capsys.readouterr().out)["create"]) == 5


async def test_an_apply_that_outlasts_its_budget_says_the_server_may_still_be_applying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _budget(monkeypatch, 0.1)
    path, libraries = _many(tmp_path, 1)  # 0.1 + 1 x 0.1 = 0.2 s

    async with _slow_server(1.0, _applied(libraries)) as url, ApiClient(url, token="t") as api:
        with pytest.raises(ClientError) as timed_out:
            await apply_sources(api, path, prune=False, as_json=False)

    message = str(timed_out.value)
    assert "within 0.2 seconds" in message
    assert "exactdocs sources plan" in message
    assert exit_code(timed_out.value) == EXIT_FAILED
