"""Steps for re-syncing a branch of a private copy of the fixture repository."""

import shutil
import tempfile
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import LIBRARY, articles_of, version_commit, wait_for_job

REF = "next"


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.fixture_repo.path)


@given("the fixture repository is a private copy")
def step_copy(context: Context) -> None:
    """Shadow the shared fixture repository for this scenario, so moving a branch stays local."""
    base = Path(tempfile.mkdtemp(prefix="exactdocs-sync-"))
    context.add_cleanup(shutil.rmtree, base, ignore_errors=True)
    copy = base / "fixture" / "docs-repo"
    shutil.copytree(context.fixture_repo.path, copy)
    context.fixture_repo = replace(context.fixture_repo, path=copy, file_url=copy.as_uri())


@given('a commit changed "{path}" on branch "{branch}"')
def step_commit(context: Context, path: str, branch: str) -> None:
    _git(context, "checkout", "-q", branch)
    with (context.fixture_repo.path / path).open("a", encoding="utf-8") as article:
        article.write("\n## Upgrading\n\nRe-run the installer after an upgrade.\n")
    _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
         "commit", "-q", "-am", f"docs: change {path}")  # fmt: skip
    context.new_head = _git(context, "rev-parse", "HEAD")
    context.listed_before = articles_of(context, branch)
    context.read_before = {a["path"]: _read(context, a["path"]) for a in context.listed_before}
    context.changed = path
    _git(context, "checkout", "-q", "main")


@given('an agent holds the chunk ID of a section of "{path}"')
def step_hold(context: Context, path: str) -> None:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": "Python", "ref": REF, "limit": 50}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    held = next(r for r in response.json()["results"] if path in r["article_path"])
    context.held = held["chunk_id"]
    context.held_section = (held["article_path"], held["heading_path"])


@given("the repository is no longer served")
def step_gone(context: Context) -> None:
    shutil.rmtree(context.fixture_repo.path)


@given("the user syncs the library")
@when("the user syncs the library")
def step_sync(context: Context) -> None:
    context.response = context.client.post(f"/api/v1/libraries{LIBRARY}/sync")
    if context.response.status_code == HTTPStatus.ACCEPTED:
        context.job = wait_for_job(context, context.response.headers["Location"].rsplit("/", 1)[-1])


def _jobs(context: Context) -> list[dict]:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["jobs"]


@then("no import runs and the version is reported up to date")
def step_up_to_date(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert [v["status"] for v in context.response.json()["versions"]] == ["up_to_date"]
    assert len(_jobs(context)) == 1, "only the first import ran"


@then("no import runs and the version is reported as pinned")
def step_pinned(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert [v["status"] for v in context.response.json()["versions"]] == ["pinned"]
    assert len(_jobs(context)) == 1, "only the first import ran"


@then('only "{path}" is re-chunked and every other article is reused')
def step_rechunked(context: Context, path: str) -> None:
    assert context.response.status_code == HTTPStatus.ACCEPTED, context.response.text
    assert context.changed == path
    job = context.job
    assert job["state"] == "succeeded", job
    assert job["chunked"] == 1, job  # install.md; every other blob is already chunked
    assert job["reused"] == len(context.served[REF]) - 1, job


@then('only "{path}" is parsed and every other article is taken from the catalog')
def step_parsed(context: Context, path: str) -> None:
    assert context.response.status_code == HTTPStatus.ACCEPTED, context.response.text
    assert context.changed == path
    job = context.job
    assert job["state"] == "succeeded", job
    assert job["parsed"] == 1, job  # install.md
    assert job["taken"] == len(context.served[REF]) - 1, job


@then("every other article reads as it did before the sync")
def step_same_articles(context: Context) -> None:
    after = {a["path"]: a for a in articles_of(context, REF)}
    before = {a["path"]: a for a in context.listed_before}
    assert after.keys() == before.keys()
    for path, listed in before.items():
        if path != context.changed:
            assert after[path] == listed, (after[path], listed)
            assert _read(context, path) == context.read_before[path], path


def _read(context: Context, path: str) -> dict:
    """The article as a reader gets it, less what a new commit changes by itself."""
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/article", params={"ref": REF, "path": path}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return {k: v for k, v in response.json().items() if k not in {"commit_sha", "manifest_id"}}


@then("the version keeps its ID with the new commit SHA")
def step_same_id(context: Context) -> None:
    assert version_commit(context, REF) == context.new_head != context.commits[REF]
    assert [a["path"] for a in articles_of(context, REF)] == context.served[REF]
    detail = context.client.get(f"/api/v1/libraries{LIBRARY}").json()
    assert [v["ref"] for v in detail["versions"]] == [REF], detail


@when("the agent reads that chunk ID")
def step_read_held(context: Context) -> None:
    context.response = context.client.get(f"/api/v1/chunks/{context.held}")


@then('it gets the error "{code}"')
def step_error(context: Context, code: str) -> None:
    assert context.response.status_code == HTTPStatus.CONFLICT, context.response.text
    assert context.response.json()["error"] == code, context.response.text


@then("the error names the section's new chunk ID")
def step_new_location(context: Context) -> None:
    detail = context.response.json()["detail"]
    assert "not instructions" in detail, detail
    article_path, heading_path = context.held_section
    current = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": "Python", "ref": REF, "limit": 50}
    ).json()["results"]
    [expected] = [
        r
        for r in current
        if r["article_path"] == article_path and r["heading_path"] == heading_path
    ]
    assert expected["chunk_id"] != context.held, expected
    assert repr(expected["chunk_id"]) in detail, detail
    assert f"headings [{heading_path[0]!r}" in detail, detail


@then('"{target}" is still served at its previous commit')
def step_previous(context: Context, target: str) -> None:
    ref = target.removeprefix(LIBRARY + "/")
    assert version_commit(context, ref) == context.commits[ref]
    assert [a["path"] for a in articles_of(context, ref)] == context.served[ref]


@then("the sync job is failed with its reason")
def step_failed_job(context: Context) -> None:
    assert context.response.status_code >= HTTPStatus.BAD_REQUEST, context.response.text
    newest = _jobs(context)[0]
    assert newest["version"] == REF, newest
    assert newest["state"] == "failed", newest
    assert newest["error"], newest
