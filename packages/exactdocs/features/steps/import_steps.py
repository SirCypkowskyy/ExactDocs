"""Steps for importing the fixture docs repository through the app's own job worker."""

import asyncio
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driving.http import SESSION_COOKIE
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.dtos import EnqueueJobCommand
from exactdocs.ingestion.errors import RepositoryUnreachableError
from exactdocs.ingestion.models import RefKind
from steps.http_steps import DEMO_COOKIE, OfflineGit, store_demo_catalog

LIBRARY = "/fixture/docs-repo"
# Selected by "docs/" yet not imported: skipped and listed with a reason (latin1.md is decoded).
UNREADABLE = [
    "docs/legacy/binary.md",
    "docs/legacy/undecodable.md",
    "docs/reference/oversized.md",
]
JOB_SECONDS = 60


class SwitchableGit:
    """The real git, until a scenario makes fetching fail (a server that went away)."""

    def __init__(self, git: GitCli) -> None:
        self.git = git
        self.failing = False

    def fetch(self, *args: object, **kwargs: object):
        if self.failing:
            reason = "connection refused"
            raise RepositoryUnreachableError(reason)
        return self.git.fetch(*args, **kwargs)  # ty: ignore[invalid-argument-type]


def _commit(context: Context, ref: str) -> str:
    return context.fixture_git("rev-parse", f"{ref}^{{commit}}", cwd=context.fixture_repo.path)


def _articles(context: Context, ref: str) -> list[dict]:
    """Every article of a version, over the paged listing."""
    found, cursor = [], None
    while True:
        params = {"ref": ref, "limit": 100} | ({"cursor": cursor} if cursor else {})
        response = context.client.get(f"/api/v1/libraries{LIBRARY}/articles", params=params)
        assert response.status_code == HTTPStatus.OK, response.text
        body = response.json()
        found += body["articles"]
        cursor = body["next_cursor"]
        if not cursor:
            return found


def _wait(context: Context, job_id: str) -> dict:
    deadline = time.monotonic() + JOB_SECONDS
    while time.monotonic() < deadline:
        job = context.client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in {"succeeded", "failed"}:
            context.job = job
            return job
        time.sleep(0.02)
    message = "the import job did not finish"
    raise AssertionError(message)


def _import(context: Context, ref: str, **settings: object) -> None:
    """Add the library at ``ref`` the first time; later, queue another version of it."""
    commit = _commit(context, ref)
    if context.library_added:
        added = context.container.ingestion.enqueue_job
        job = context.client.portal.call(
            added,
            EnqueueJobCommand(
                kind="import",
                library=LIBRARY,
                version=ref,
                commit_sha=commit,
                ref_kind=RefKind.TAG,
            ),
        )
        job_id = job.id
    else:
        body = {"url": context.fixture_repo.file_url, "ref": ref, **settings}
        response = context.client.post("/api/v1/libraries", json=body)
        assert response.status_code == HTTPStatus.CREATED, response.text
        job_id = response.json()["job_id"]
        context.library_added = True
    _wait(context, job_id)


@given("ExactDocs imports the fixture docs repository")
def step_running(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    settings = Settings(data_dir=data_dir)
    asyncio.run(store_demo_catalog(settings))
    git = GitCli.locate()
    context.git = SwitchableGit(git)
    context.container = Container.build(settings, remote=OfflineGit(git), gateway=context.git)
    context.library_added = False
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given('"{target}" is imported')
def step_given_imported(context: Context, target: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    _import(context, ref, include_paths=["docs/"])
    assert context.job["state"] == "succeeded", context.job
    context.served = {ref: [a["path"] for a in _articles(context, ref)]}
    context.commits = {ref: _version_commit(context, ref)}


def _version_commit(context: Context, ref: str) -> str:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/versions/{ref}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["commit_sha"]


@when('"{paths}" of the fixture repository at "{ref}" is imported')
def step_import(context: Context, paths: str, ref: str) -> None:
    _import(context, ref, include_paths=[paths])


@when('"{paths}" of the fixture repository at "{ref}" is imported excluding "{exclusion}"')
def step_import_excluding(context: Context, paths: str, ref: str, exclusion: str) -> None:
    _import(context, ref, include_paths=[paths], exclude_paths=[exclusion])


@when('"{paths}" of the fixture repository at "{ref}" is imported with the tag rule "{rule}"')
def step_import_tagged(context: Context, paths: str, ref: str, rule: str) -> None:
    pattern, tag = rule.split(" -> ")
    _import(context, ref, include_paths=[paths], tag_rules=[{"pattern": pattern, "tag": tag}])


@when('"{ref}" is imported again')
def step_again(context: Context, ref: str) -> None:
    context.chunks_before = _search_all(context, ref)
    _import(context, ref)
    assert context.job["state"] == "succeeded", context.job


@when('a re-import of "{ref}" fails before activation')
def step_fail(context: Context, ref: str) -> None:
    context.git.failing = True
    # The branch "moved": the job is pinned to a newer commit than the one that is served.
    context.moved_to = _commit(context, "v1.4.0")
    commit = context.moved_to
    job = context.client.portal.call(
        context.container.ingestion.enqueue_job,
        EnqueueJobCommand(
            kind="import",
            library=LIBRARY,
            version=ref,
            commit_sha=commit,
            ref_kind=RefKind.BRANCH,
        ),
    )
    _wait(context, job.id)
    assert context.job["state"] == "failed", context.job
    assert "unreachable" in context.job["error"], context.job


@then("the import succeeds and reports every file as processed")
def step_succeeds(context: Context) -> None:
    job = context.job
    assert job["state"] == "succeeded", job
    assert job["total"] > 0
    assert job["done"] == job["total"], job


@then('"{target}" lists every selected article')
def step_lists_all(context: Context, target: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    tree = context.fixture_git(
        "ls-tree", "-r", "--name-only", ref, "--", "docs", cwd=context.fixture_repo.path
    ).splitlines()
    expected = sorted(p for p in tree if p.endswith((".md", ".mdx")) and p not in UNREADABLE)
    assert [a["path"] for a in _articles(context, ref)] == expected


def _search_all(context: Context, ref: str) -> list[tuple[str, str]]:
    """(chunk ID, commit SHA) of every hit for a few words that the fixture articles share."""
    hits = []
    for word in ("token", "install", "configuration", "guide", "client"):
        response = context.client.get(
            f"/api/v1/libraries{LIBRARY}/search", params={"q": word, "ref": ref, "limit": 50}
        )
        assert response.status_code == HTTPStatus.OK, response.text
        hits += [(r["chunk_id"], r["commit_sha"]) for r in response.json()["results"]]
    return sorted(set(hits))


@then('every article and chunk carries the commit SHA of "{ref}"')
def step_commit(context: Context, ref: str) -> None:
    commit = _commit(context, ref)
    detail = context.client.get(
        f"/api/v1/libraries{LIBRARY}/article", params={"ref": ref, "path": "docs/guide/auth.md"}
    ).json()
    assert detail["commit_sha"] == commit, detail
    hits = _search_all(context, ref)
    assert hits
    assert {sha for _, sha in hits} == {commit}, hits


@then("the import succeeds")
def step_import_succeeds(context: Context) -> None:
    assert context.job["state"] == "succeeded", context.job


@then("the job lists these skipped files:")
def step_skipped(context: Context) -> None:
    listed = [(p["path"], p["code"], p["reason"]) for p in context.job["problems"]]
    expected = [(r["path"], r["code"], r["reason"]) for r in context.table or []]
    assert listed == expected, listed
    assert all(p["skipped"] for p in context.job["problems"])


@then('the article "{path}" of "{target}" keeps its accented characters')
def step_accents(context: Context, path: str, target: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/article", params={"ref": ref, "path": path}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert "enregistr\u00e9e" in response.json()["content"], response.text


@then('"{target}" still serves the previous commit')
def step_previous(context: Context, target: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    assert _version_commit(context, ref) == context.commits[ref] != context.moved_to
    assert [a["path"] for a in _articles(context, ref)] == context.served[ref]
    assert context.job["error"], context.job


@then('"{target}" has the article "{path}"')
def step_has(context: Context, target: str, path: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    assert path in [a["path"] for a in _articles(context, ref)]


@then('"{target}" has no article "{path}"')
def step_has_not(context: Context, target: str, path: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    assert path not in [a["path"] for a in _articles(context, ref)]


@then('"{target}" lists the same articles and chunks as before')
def step_same(context: Context, target: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    assert [a["path"] for a in _articles(context, ref)] == context.served[ref]
    assert _search_all(context, ref) == context.chunks_before != []


@then('the article "{path}" of "{target}" is tagged "{first}" and "{second}"')
def step_tags(context: Context, path: str, target: str, first: str, second: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/article", params={"ref": ref, "path": path}
    )
    assert sorted(response.json()["tags"]) == sorted([first, second]), response.text
