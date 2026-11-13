"""Steps for OPS-01's Prometheus endpoint: a real ``exactdocs serve`` process with metrics on.

The server runs in a process of its own (``serve``): metrics set up a process-wide OpenTelemetry
meter provider, which must not leak into the other scenarios of this run.
"""

import asyncio
import re
import shutil
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

import httpx
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from steps.http_steps import DEMO_COOKIE, store_demo_catalog
from steps.telemetry_steps import serve

LIBRARY = "/fixture/docs-repo"
BRANCH = "next"
JOB_SECONDS = 60
SEARCH_ROUTE = "/api/v1/libraries/{owner}/{repo}/search"


def _client(context: Context, host: str | None = None) -> httpx.Client:
    headers = {"host": host} if host else {}
    return httpx.Client(
        base_url=context.server,
        cookies={SESSION_COOKIE: DEMO_COOKIE},
        headers=headers,
        timeout=30,
    )


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.repository)


@given('"EXACTDOCS_METRICS" is on')
def step_metrics_on(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    asyncio.run(store_demo_catalog(Settings(data_dir=data_dir)))
    serve(context, stack, data_dir, {"EXACTDOCS_METRICS": "true"})


def _wait_for_job(client: httpx.Client, job_id: str) -> dict:
    deadline = time.monotonic() + JOB_SECONDS
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.05)
    message = f"job {job_id} did not finish"
    raise AssertionError(message)


@given("a branch of the fixture repository was imported and then synced")
def step_imported_and_synced(context: Context) -> None:
    """Import a branch of a private copy, move the branch, sync: an import and a refresh job."""
    base = Path(tempfile.mkdtemp(prefix="exactdocs-metrics-"))
    context.add_cleanup(shutil.rmtree, base, ignore_errors=True)
    context.repository = base / "fixture" / "docs-repo"
    shutil.copytree(context.fixture_repo.path, context.repository)
    with _client(context) as client:
        added = client.post(
            "/api/v1/libraries",
            json={
                "url": context.repository.as_uri(),
                "ref": BRANCH,
                "include_paths": ["docs/"],
            },
        )
        assert added.status_code == HTTPStatus.CREATED, added.text
        assert _wait_for_job(client, added.json()["job_id"])["state"] == "succeeded"
        _git(context, "checkout", "-q", BRANCH)
        with (context.repository / "docs/guide/install.md").open("a", encoding="utf-8") as doc:
            doc.write("\n## Upgrading\n\nRe-run the installer after an upgrade.\n")
        _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
             "commit", "-q", "-am", "docs: change the install guide")  # fmt: skip
        synced = client.post(f"/api/v1/libraries{LIBRARY}/sync")
        assert synced.status_code == HTTPStatus.ACCEPTED, synced.text
        job_id = synced.headers["Location"].rsplit("/", 1)[-1]
        assert _wait_for_job(client, job_id)["state"] == "succeeded"


@given('a user searched "{query}"')
def step_searched(context: Context, query: str) -> None:
    with _client(context) as client:
        found = client.get(f"/api/v1/libraries{LIBRARY}/search", params={"q": query, "ref": BRANCH})
    assert found.status_code == HTTPStatus.OK, found.text
    context.query = query


@when('Prometheus scrapes "{path:S}"')
def step_scrape(context: Context, path: str) -> None:
    if getattr(context, "server", None) is None:  # the in-process demo instance
        context.scrape = context.client.get(path)
        return
    with httpx.Client(base_url=context.server, timeout=30) as prometheus:
        context.scrape = prometheus.get(path)


@when('Prometheus scrapes "{path:S}" as "{host:S}"')
def step_scrape_as(context: Context, path: str, host: str) -> None:
    with httpx.Client(base_url=context.server, headers={"host": host}, timeout=30) as prometheus:
        context.scrape = prometheus.get(path)


def _series(text: str, name: str) -> list[str]:
    """The samples of one metric: ``name{labels} value`` lines.

    Returns:
        The sample lines.
    """
    return [line for line in text.splitlines() if re.match(rf"{re.escape(name)}(\{{| )", line)]


def _counted(text: str, name: str, **labels: str) -> float:
    """The sum of the samples of ``name`` that carry every one of ``labels``.

    Returns:
        The sum, 0 when no sample matches.
    """
    total = 0.0
    for line in _series(text, name):
        if all(f'{label}="{value}"' in line for label, value in labels.items()):
            total += float(line.rsplit(" ", 1)[-1])
    return total


@then("it gets request, search, import and sync metrics")
def step_metrics(context: Context) -> None:
    response: httpx.Response = context.scrape
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.headers["content-type"].startswith("text/plain"), response.headers
    text = response.text
    requests = "http_server_request_duration_seconds_count"
    assert _counted(text, requests, http_route=SEARCH_ROUTE, http_response_status_code="200")
    searches = "exactdocs_search_duration_seconds_count"
    assert _counted(text, searches, exactdocs_search="search_docs", exactdocs_search_stage="total",
                    exactdocs_retrieval_mode="bm25")  # fmt: skip
    assert _counted(text, searches, exactdocs_search="search_docs", exactdocs_search_stage="rank")
    jobs = "exactdocs_job_duration_seconds_count"
    assert _counted(text, jobs, exactdocs_job_kind="import") == 1, _series(text, jobs)
    assert _counted(text, jobs, exactdocs_job_kind="refresh") == 1, _series(text, jobs)  # sync
    # The probes that waited for the server, and the scrapes, are not counted as requests.
    assert not [s for s in _series(text, requests) if "health" in s or "/metrics" in s]


@then('no metric contains "{text}", the library or the caller')
def step_nothing_identifying(context: Context, text: str) -> None:
    body = context.scrape.text
    for secret in [text, LIBRARY, "fixture/docs-repo", "docs-repo", DEMO_COOKIE, "admin"]:
        assert secret not in body, secret


@then("the scrape is refused")
def step_refused(context: Context) -> None:
    assert context.scrape.status_code == HTTPStatus.BAD_REQUEST, context.scrape.text
    assert "exactdocs_" not in context.scrape.text


@then("there are no metrics to scrape")
def step_none(context: Context) -> None:
    assert context.scrape.status_code == HTTPStatus.NOT_FOUND, context.scrape.text
