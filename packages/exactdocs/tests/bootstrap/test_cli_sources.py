"""``exactdocs sources plan|apply``: reading the YAML, the diff, ``--json`` and exit codes."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.cli_library import (
    SourcesFailedError,
    UsageError,
    apply_sources,
    exit_code,
    plan_sources,
    read_sources,
)
from exactdocs.bootstrap.client import ApiClient, ApiError
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


def test_a_yaml_date_is_sent_as_text_for_the_server_to_judge(tmp_path: Path) -> None:
    loaded = read_sources(_write(tmp_path, "version: 1\nlibraries: [{refs: [2024-01-01]}]\n"))

    assert loaded["libraries"][0]["refs"] == ["2024-01-01"]


def test_the_commands_are_remote_and_parse() -> None:
    assert not {"sources plan", "sources apply"} & LOCAL_COMMANDS
    for line in ("sources plan f.yaml --json", "sources apply f.yaml --prune --json"):
        cli.app.parse_args(line.split(), exit_on_error=False)
