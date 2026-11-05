"""Steps for the library and token commands: the real CLI against a server on a loopback port."""

import asyncio
import io
import json
import os
import shlex
import time
from contextlib import redirect_stderr, redirect_stdout
from http import HTTPStatus
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.client import ApiClient
from steps.cli_login_steps import HORSE

LIBRARY = "/fixture/docs-repo"
JOB_SECONDS = 60


def run(context: Context, line: str, *, stdin: str = "", tty: bool = False) -> None:
    """Run ``exactdocs ...`` in-process; stdout, stderr and the exit code land on the context."""
    context.line = line
    words = shlex.split(line.replace("<fixture-url>", context.fixture_repo.file_url))
    assert words.pop(0) == "exactdocs", line
    output, errors = io.StringIO(), io.StringIO()
    standard_in = io.StringIO(stdin)
    standard_in.isatty = lambda: tty  # ty: ignore[invalid-assignment]
    env = {"EXACTDOCS_CONFIG_FILE": str(context.config_file)}
    context.exit_code = 0
    with (
        patch.dict(os.environ, env),
        patch("sys.stdin", standard_in),
        redirect_stdout(output),
        redirect_stderr(errors),
    ):
        try:
            cli.app(words, exit_on_error=False, result_action="return_value")
        except SystemExit as exc:
            context.exit_code = exc.code if isinstance(exc.code, int) else 1
    context.output, context.errors = output.getvalue(), errors.getvalue()


@given("the user is logged in with the CLI")
def step_logged_in(context: Context) -> None:
    run(
        context,
        f"exactdocs login {context.server_url} --username ada --password-stdin",
        stdin=HORSE + "\n",
    )
    assert context.exit_code == 0, context.errors


@when('the user runs the command "{line}"')
def step_run(context: Context, line: str) -> None:
    run(context, line)


@given('the user ran the command "{line}"')
def step_ran(context: Context, line: str) -> None:
    run(context, line)
    assert context.exit_code == 0, context.errors


@when('the user runs the command "{line}" without a terminal')
def step_run_untty(context: Context, line: str) -> None:
    run(context, line)


@when('the user runs the command "{line}" as the admin')
def step_run_admin(context: Context, line: str) -> None:
    run(context, line + " --username ada --password-stdin", stdin=HORSE + "\n")


@when('the user runs the command "{line}" as the admin with a wrong password')
def step_run_wrong(context: Context, line: str) -> None:
    run(context, line + " --username ada --password-stdin", stdin="wrong horse battery staple\n")


@when('the user revokes the token "{name}" as the admin')
def step_revoke(context: Context, name: str) -> None:
    listing = run_json(context, "exactdocs token list --json --username ada --password-stdin")
    token = next(t for t in listing["tokens"] if t["name"] == name)
    run(context, f"exactdocs token revoke {token['id']} --username ada --password-stdin",
        stdin=HORSE + "\n")  # fmt: skip


def run_json(context: Context, line: str) -> dict:
    run(context, line, stdin=HORSE + "\n")
    assert context.exit_code == 0, context.errors
    return json.loads(context.output)


@then("the command succeeds")
def step_ok(context: Context) -> None:
    assert context.exit_code == 0, (context.exit_code, context.errors, context.output)


@then("the command exits with code {code:d}")
def step_code(context: Context, code: int) -> None:
    assert context.exit_code == code, (context.exit_code, context.errors, context.output)


@then('"exactdocs libraries" lists "{library}" with version "{ref}"')
def step_lists(context: Context, library: str, ref: str) -> None:
    run(context, "exactdocs libraries --json")
    listed = {
        lib["id"]: [r["ref"] for r in lib["refs"]]
        for lib in json.loads(context.output)["libraries"]
    }
    assert ref in listed.get(library, []), listed
    run(context, "exactdocs libraries")  # the human table names it too
    assert library in context.output, context.output
    assert ref in context.output, context.output


@then('the output says "{text}"')
def step_says(context: Context, text: str) -> None:
    assert text in context.output, context.output


@then('stdout is JSON that names the job and its state "{state}"')
def step_json(context: Context, state: str) -> None:
    body = json.loads(context.output)  # stdout holds nothing but the JSON
    assert body["added"]["job_id"] == body["job"]["id"]
    assert body["job"]["state"] == state


@then("stderr shows the import progress")
def step_progress(context: Context) -> None:
    assert "succeeded" in context.errors, context.errors


def _admin_rest(context: Context) -> None:
    context.client.post("/api/v1/session", json={"username": "ada", "password": HORSE})


def _settled(detail: dict) -> dict:
    """What an add produces, minus what differs between two libraries (name, time)."""
    detail = {k: v for k, v in detail.items() if k not in {"id", "title", "description"}}
    detail["versions"] = [
        {k: v for k, v in x.items() if k != "imported_at"} for x in detail["versions"]
    ]
    return detail


@then("the REST API returns the same library as for a library added in the UI")
def step_parity(context: Context) -> None:
    _admin_rest(context)
    body = {
        "url": context.fixture_repo.file_url,
        "library_id": "/fixture/via-ui",
        "ref": "v1.4.0",
        "include_paths": ["docs/"],
    }
    response = context.client.post("/api/v1/libraries", json=body)
    assert response.status_code == HTTPStatus.CREATED, response.text
    deadline = time.monotonic() + JOB_SECONDS
    job: dict = {}
    while time.monotonic() < deadline:
        job = context.client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()
        if job["state"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert job["state"] == "succeeded", job
    by_cli = context.client.get(f"/api/v1/libraries{LIBRARY}").json()
    by_ui = context.client.get("/api/v1/libraries/fixture/via-ui").json()
    assert _settled(by_cli) == _settled(by_ui)


@then("the output holds a new token that the server accepts")
def step_new_token(context: Context) -> None:
    secret = context.output.strip().splitlines()[-1]
    assert secret.startswith("exd_"), context.output
    context.new_token = secret

    async def check() -> None:
        async with ApiClient(context.server_url, secret) as api:
            await api.check_token()

    asyncio.run(check())


@then("the revoked token is refused by the server")
def step_revoked(context: Context) -> None:
    async def check() -> int:
        async with ApiClient(context.server_url, context.new_token) as api:
            try:
                await api.check_token()
            except Exception as exc:  # ruff: ignore[blind-except]
                return getattr(exc, "status", 0)
            return 200

    assert asyncio.run(check()) == HTTPStatus.UNAUTHORIZED


def _rest_preview(context: Context) -> dict:
    """What the preview endpoint answers for the fixture at v1.4.0 and ``docs/**``."""
    _admin_rest(context)
    response = context.client.post(
        "/api/v1/repositories/preview",
        json={"url": context.fixture_repo.file_url, "ref": "v1.4.0", "include_paths": ["docs/**"]},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@then("the output lists the files the preview matches, with their count")
def step_dry_run_listed(context: Context) -> None:
    lines = context.output.splitlines()
    preview = _rest_preview(context)
    assert preview["files"], preview
    assert all(f in lines for f in preview["files"]), context.output
    assert f"{preview['total']} files" in context.output, context.output
    assert "truncated" not in context.output, context.output
    assert "bytes" not in context.output.lower(), context.output  # the preview has no sizes


@then("stdout is JSON with the files, their total and whether the list was cut")
def step_dry_run_json(context: Context) -> None:
    body = json.loads(context.output)  # stdout holds nothing but the JSON
    assert body["files"], body
    assert body["total"] == len(body["files"]), body
    assert body["truncated"] is False, body
