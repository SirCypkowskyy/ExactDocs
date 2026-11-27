"""Steps for adding libraries over MCP (#613): API tokens over HTTP, the fixture repository behind
an ``https://`` URL, and no DNS or git server outside this machine."""

import asyncio
import json
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.models import RepositoryUrl
from steps import library_roles_steps as roles
from steps.http_steps import DEMO_COOKIE, store_demo_catalog
from steps.library_creation_steps import step_creator_membership

PUBLIC_ADDRESS = "140.82.112.3"
MAX_LINE = 300  # characters an answer line may take, about


class MirroredGit:
    """The system git, with the repository's ``https://`` URL read from the fixture's file URL.

    Every call is counted, so a scenario can tell that nothing was fetched.
    """

    def __init__(self, git: GitCli, mirrors: dict[str, str]) -> None:
        self.git, self.mirrors, self.calls = git, mirrors, 0

    def __getattr__(self, name: str) -> Callable[..., Any]:
        method = getattr(self.git, name)

        def call(repository: RepositoryUrl, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            local = self.mirrors.get(repository.url)
            if local is not None:
                repository = replace(repository, url=local)
            return method(repository, *args, **kwargs)

        return call


def _app(context: Context) -> TestClient:
    """Serve the app the scenario configured, once, at its first request."""
    if getattr(context, "client", None) is None:
        stack = ExitStack()
        context.add_cleanup(stack.close)
        data = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-mcp-add-")))
        settings = Settings(
            data_dir=data,
            auth={"library_creation": {"groups": ["docs-admins"]}},
            mcp_import_hosts=context.import_hosts,
        )
        context.settings = settings
        asyncio.run(store_demo_catalog(settings))

        async def resolve(host: str) -> Sequence[str]:
            return [context.addresses.get(host, PUBLIC_ADDRESS)]

        git = context.mirrored_git
        container = Container.build(
            settings,
            remote=git,
            gateway=git,
            renames=git,
            tree=git,
            files=git,
            resolve_host=resolve,
        )
        context.client = stack.enter_context(
            TestClient(
                create_app(container),
                base_url="http://localhost",
                cookies={SESSION_COOKIE: DEMO_COOKIE},
            )
        )
    return context.client


def _token(context: Context, who: str) -> str:
    _app(context)
    who = who.strip('"')
    if who == "the admin":
        if not getattr(context, "admin_token", None):
            made = roles.send_as(
                context, "POST", "/api/v1/tokens", session=DEMO_COOKIE, json={"name": "agent"}
            )
            assert made.status_code == HTTPStatus.CREATED, made.text
            context.admin_token = made.json()["token"]
        return context.admin_token
    return roles.get_person(context, who)["token"]


def _rpc(context: Context, who: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    response = roles.send_as(
        context,
        "POST",
        "/mcp",
        token=_token(context, who),
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers=roles.MCP_HEADERS,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    payload = response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        payload = next(
            line.removeprefix("data:").strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        )
    return json.loads(payload)


def _call(context: Context, who: str, tool: str, arguments: dict[str, Any]) -> str:
    """Call a tool; keep and return its answer after the notice (or its error text)."""
    reply = _rpc(context, who, "tools/call", {"name": tool, "arguments": arguments})
    context.reply = reply
    result = reply.get("result")
    if result is None:
        return reply["error"]["message"]
    texts = [block["text"] for block in result["content"]]
    context.answer = texts[-1]
    context.is_error = result.get("isError", False)
    return context.answer


def _sha(context: Context, ref: str) -> str:
    return context.fixture_git("rev-parse", ref, cwd=context.fixture_repo.path)[:7]


def _expected(context: Context, text: str) -> str:
    for ref in ("main", "next", "v1.3.0", "v1.4.0"):
        text = text.replace(f"<sha of {ref}>", _sha(context, ref))
    return text


@given(
    'ExactDocs serves the fixture repository as "{url}", and group "{group}" may create libraries'
)
def step_serves(context: Context, url: str, group: str) -> None:
    assert group == "docs-admins"
    context.client = None
    context.import_hosts = ["github.com", "gitlab.com"]
    context.addresses = {}
    context.mirrored_git = MirroredGit(GitCli.locate(), {url: context.fixture_repo.file_url})
    context.jobs = []


@given('"{username}" is a user outside every creator group')
def step_plain_user(context: Context, username: str) -> None:
    _token(context, username)


@given('"{username}" belongs to the creator group "{group}"')
def step_creator(context: Context, username: str, group: str) -> None:
    _token(context, username)
    step_creator_membership(context, username, group)


@given('the admin has an agent token limited to "{library}"')
def step_limited_admin(context: Context, library: str) -> None:
    _app(context)
    made = roles.send_as(
        context,
        "POST",
        "/api/v1/tokens",
        session=DEMO_COOKIE,
        json={"name": "limited agent", "library_ids": [library]},
    )
    assert made.status_code == HTTPStatus.CREATED, made.text
    context.admin_token = made.json()["token"]


@given('the operator allows imports over MCP from "{host}"')
def step_allow_host(context: Context, host: str) -> None:
    assert context.client is None, "set before the app starts"
    context.import_hosts = [*context.import_hosts, host]


@given('"{host}" resolves to "{address}"')
def step_resolves(context: Context, host: str, address: str) -> None:
    context.addresses[host] = address


@when("{who} lists the MCP tools")
def step_list_tools(context: Context, who: str) -> None:
    context.tools = [t["name"] for t in _rpc(context, who, "tools/list", {})["result"]["tools"]]


@then('the tools hold no "{first}" and no "{second}"')
def step_hidden(context: Context, first: str, second: str) -> None:
    assert context.tools, "the read-only tools are listed"
    assert first not in context.tools, context.tools
    assert second not in context.tools, context.tools


@then('the tools hold "{first}" and "{second}"')
def step_shown(context: Context, first: str, second: str) -> None:
    assert {first, second} <= set(context.tools), context.tools


@then('"{username}" calling "{tool}" gets the answer of a tool that does not exist')
def step_unknown(context: Context, username: str, tool: str) -> None:
    hidden = _rpc(context, username, "tools/call", {"name": tool, "arguments": {"source": "a/b"}})
    missing = _rpc(
        context, username, "tools/call", {"name": "no_such_tool", "arguments": {"source": "a/b"}}
    )
    assert json.dumps(hidden).replace(tool, "X") == json.dumps(missing).replace(
        "no_such_tool", "X"
    ), (hidden, missing)
    assert "unknown tool" in json.dumps(hidden).lower(), hidden


@given('the admin added "{source}" over MCP')
def step_added(context: Context, source: str) -> None:
    answer = _call(context, "the admin", "add_docs", {"source": source})
    assert answer.startswith("queued "), answer
    context.job = answer.rsplit("job ", 1)[1]


@when('{who} calls add_docs with source "{source}" and ref "{ref}" again')
@when('{who} calls add_docs with source "{source}" and ref "{ref}"')
def step_add_ref(context: Context, who: str, source: str, ref: str) -> None:
    context.calls_before = context.mirrored_git.calls
    context.answers = [
        *getattr(context, "answers", []),
        _call(context, who, "add_docs", {"source": source, "ref": ref}),
    ]


@when('{who} calls add_docs with source "{source}"')
def step_add(context: Context, who: str, source: str) -> None:
    context.calls_before = context.mirrored_git.calls
    _call(context, who, "add_docs", {"source": source})


@then('the answer is one line "{expected}"')
def step_one_line(context: Context, expected: str) -> None:
    answer = context.answer
    assert "\n" not in answer, answer
    wanted = _expected(context, expected)
    if "<job>" in wanted:
        head = wanted.split("<job>")[0]
        assert answer.startswith(head), (answer, wanted)
        context.job = answer.removeprefix(head)
    else:
        assert answer == wanted, (answer, wanted)
    assert len(answer) <= MAX_LINE, answer


@then('the job records "{username}" as who queued it, over MCP')
def step_job_person(context: Context, username: str) -> None:
    job = roles.send_as(context, "GET", f"/api/v1/jobs/{context.job}", session=DEMO_COOKIE)
    assert job.status_code == HTTPStatus.OK, job.text
    person = job.json()["created_by"]
    assert (person["username"], person["via"]) == (username, "mcp"), person


@then('the library "{library}" takes the paths of its context7.json')
def step_context7_paths(context: Context, library: str) -> None:
    found = roles.send_as(context, "GET", f"/api/v1/libraries{library}", session=DEMO_COOKIE)
    assert found.status_code == HTTPStatus.OK, found.text
    settings = found.json()["settings"]
    assert settings["include_paths"] == ["docs/"], settings


@then('the access log records that "{username}" created "{library}"')
def step_created_log(context: Context, username: str, library: str) -> None:
    log = roles.send_as(
        context, "GET", f"/api/v1/libraries{library}/access-log", session=DEMO_COOKIE
    )
    assert log.status_code == HTTPStatus.OK, log.text
    events = log.json()["events"]
    assert {(e["change"], e["actor"]) for e in events} == {("library_created", username)}, events


@then("the second answer names the first job as already importing")
def step_second(context: Context) -> None:
    first, second = context.answers[-2:]
    job = first.rsplit("job ", 1)[1]
    assert second.startswith("already importing: /fixture/docs-repo@v1.4.0, job " + job), second


@then('the library has one import job for "{ref}"')
def step_one_job(context: Context, ref: str) -> None:
    jobs = roles.send_as(
        context,
        "GET",
        "/api/v1/libraries/fixture/docs-repo/jobs",
        session=DEMO_COOKIE,
        params={"version": ref, "kind": "import"},
    )
    assert jobs.status_code == HTTPStatus.OK, jobs.text
    assert len(jobs.json()["jobs"]) == 1, jobs.json()


@when("the imports finish")
@given("the imports finish")
def step_finish(context: Context) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        jobs = roles.send_as(
            context,
            "GET",
            "/api/v1/libraries/fixture/docs-repo/jobs",
            session=DEMO_COOKIE,
            params={"state": ["queued", "running"]},
        )
        assert jobs.status_code == HTTPStatus.OK, jobs.text
        if not jobs.json()["jobs"]:
            return
        time.sleep(0.1)
    message = "the imports did not finish"
    raise AssertionError(message)


@when("{who} calls import_status with that job")
def step_status(context: Context, who: str) -> None:
    _call(context, who, "import_status", {"job_id": context.job})


@when("{who} calls import_status with no job")
def step_status_all(context: Context, who: str) -> None:
    _call(context, who, "import_status", {})


@then('the answer is one line starting "{start}"')
def step_starts(context: Context, start: str) -> None:
    assert "\n" not in context.answer, context.answer
    assert context.answer.startswith(start), context.answer


@then("the answer has at most {count:d} lines, each a job the admin queued")
def step_mine(context: Context, count: int) -> None:
    lines = context.answer.splitlines()
    assert 1 <= len(lines) <= count, lines
    assert all("job " in line for line in lines), lines
    assert any(context.job in line for line in lines), lines


@then('the answer has the line "{line}"')
def step_has_line(context: Context, line: str) -> None:
    assert line in context.answer.splitlines(), context.answer


@then('the answer is the error "{code}" naming "{library}"')
def step_error_naming(context: Context, code: str, library: str) -> None:
    _error(context, code)
    assert library in context.answer, context.answer


@then('the answer is the error "{code}"')
def step_error(context: Context, code: str) -> None:
    _error(context, code)


def _error(context: Context, code: str) -> None:
    assert context.is_error, context.answer
    assert context.answer.startswith(f"{code}: "), context.answer


@then("no git command ran")
def step_no_git(context: Context) -> None:
    assert context.mirrored_git.calls == context.calls_before, "git was asked"
