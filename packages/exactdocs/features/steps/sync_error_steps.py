"""Steps for upstream failures during a sync, against a token-protected copy of the fixture repo."""

import secrets
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import LIBRARY, articles_of, start, version_commit, wait_for_job

VERSIONS = ("next", "v1.4.0")
SEALING = "upstream-secret-key-of-at-least-32-chars"  # seals the stored token


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.fixture_repo.path)


def _jobs(context: Context) -> list[dict]:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["jobs"]


def _serve_copy(context: Context, *, private: bool) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    base = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-upstream-")))
    copy = base / "fixture" / "docs-repo"
    shutil.copytree(context.fixture_repo.path, copy)
    context.fixture_repo = replace(context.fixture_repo, path=copy, file_url=copy.as_uri())
    if private:
        context.server = stack.enter_context(context.fixture_serve_copy(base))
    else:
        context.server = stack.enter_context(context.fixture_serve_copy(base, token=None))
    context.valid_token = context.server.token
    start(context, secret_key=SEALING)


@given("ExactDocs imports a private copy of the fixture repository over HTTP with a token")
def step_private_copy(context: Context) -> None:
    _serve_copy(context, private=True)


@given("ExactDocs imports a public copy of the fixture repository over HTTP")
def step_public_copy(context: Context) -> None:
    _serve_copy(context, private=False)


@given('"/fixture/docs-repo" is imported at "next" and "v1.4.0" {how}')
def step_imported(context: Context, how: str) -> None:
    """Add the library at its branch ``next`` (with the token or not), then its tag ``v1.4.0``."""
    assert how in {"with the token", "without a token"}, how
    body: dict[str, object] = {
        "url": context.server.url,
        "ref": VERSIONS[0],
        "include_paths": ["docs/"],
    }
    if how == "with the token":
        body["credential"] = {"kind": "token", "token": context.server.token}
    added = context.client.post("/api/v1/libraries", json=body)
    assert added.status_code == HTTPStatus.CREATED, added.text
    assert wait_for_job(context, added.json()["job_id"])["state"] == "succeeded", context.job
    tag = context.client.post(f"/api/v1/libraries{LIBRARY}/versions", json={"ref": VERSIONS[1]})
    assert tag.status_code == HTTPStatus.ACCEPTED, tag.text
    assert wait_for_job(context, tag.json()["job_id"])["state"] == "succeeded", context.job
    context.served = {ref: [a["path"] for a in articles_of(context, ref)] for ref in VERSIONS}
    context.commits = {ref: version_commit(context, ref) for ref in VERSIONS}
    context.jobs_before = len(_jobs(context))


@given("the repository was deleted")
def step_deleted(context: Context) -> None:
    shutil.rmtree(context.fixture_repo.path)


@given("the credential expired")
def step_expired(context: Context) -> None:
    context.server.token = "rotated-" + context.valid_token  # the stored one is refused now


@given("the server now asks for a login, as GitHub does for a deleted repository")
def step_asks_for_login(context: Context) -> None:
    context.server.token = secrets.token_hex(16)  # one the library never had


@when("the credential is valid again")
def step_valid_again(context: Context) -> None:
    context.server.token = context.valid_token


@given('branch "{branch}" was deleted')
def step_branch_deleted(context: Context, branch: str) -> None:
    _git(context, "branch", "-D", branch)


@given('tag "{tag}" now points elsewhere')
def step_tag_moved(context: Context, tag: str) -> None:
    _git(context, "tag", "-f", tag, "v1.3.0")


@given("the library was synced twice")
def step_synced_twice(context: Context) -> None:
    step_sync(context)
    step_sync(context)


@when("the library is synced")
def step_sync(context: Context) -> None:
    context.response = context.client.post(f"/api/v1/libraries{LIBRARY}/sync")


@then("the last good version is still served")
def step_still_served(context: Context) -> None:
    for ref in VERSIONS:
        assert version_commit(context, ref) == context.commits[ref], ref
        assert [a["path"] for a in articles_of(context, ref)] == context.served[ref], ref


@then('the library shows the error "{code}"')
def step_shows(context: Context, code: str) -> None:
    newest = _jobs(context)[0]
    assert (newest["state"], newest["error_code"]) == ("failed", code), newest
    assert newest["error"], newest
    assert newest["finished_at"], newest  # when it happened
    latest = context.client.get("/api/v1/jobs/latest").json()["jobs"]  # what the home page shows
    assert code in {j["error_code"] for j in latest if j["library"] == LIBRARY}, latest
    if context.response.status_code == HTTPStatus.OK:  # the remote answered: per version
        failed = [v for v in context.response.json()["versions"] if v["status"] == "failed"]
        assert [v["error_code"] for v in failed] == [code], context.response.text
    else:  # the remote could not be read at all
        body = context.response.json()
        assert (context.response.status_code, body["error"]) == (422, code), body


@then('no import of "{ref}" is queued')
def step_not_queued(context: Context, ref: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    imports = [j for j in _jobs(context) if j["version"] == ref and j["state"] != "failed"]
    assert len(imports) == 1, imports  # only the import that added it


@then('the sync reports "{ref}" as failed with "{code}"')
def step_reported(context: Context, ref: str, code: str) -> None:
    by_ref = {v["ref"]: v for v in context.response.json()["versions"]}
    assert (by_ref[ref]["status"], by_ref[ref]["error_code"]) == ("failed", code), by_ref
    assert by_ref[ref]["commit_sha"] == context.commits[ref], by_ref
    assert by_ref["next"]["status"] == "up_to_date", by_ref


@then('the library has one failed job per version for "{code}"')
def step_one_each(context: Context, code: str) -> None:
    failed = [j for j in _jobs(context) if j["error_code"] == code]
    assert sorted(j["version"] for j in failed) == sorted(VERSIONS), failed


@then("the newest job of each version succeeded")
def step_newest_succeeded(context: Context) -> None:
    newest: dict[str, dict] = {}
    for job in _jobs(context):
        newest.setdefault(job["version"], job)
    assert {ref: j["state"] for ref, j in newest.items()} == dict.fromkeys(VERSIONS, "succeeded"), (
        newest
    )


@given('tag "{tag}" was reported as moved')
def step_reported_moved(context: Context, tag: str) -> None:
    step_tag_moved(context, tag)
    step_sync(context)
    step_reported(context, tag, "tag_moved")


@when('the user confirms the re-import of "{ref}"')
def step_confirm(context: Context, ref: str) -> None:
    context.response = context.client.post(
        f"/api/v1/libraries{LIBRARY}/versions/reimport", json={"ref": ref}
    )


@then('"{ref}" is re-imported at its new commit and the error clears')
def step_reimported(context: Context, ref: str) -> None:
    assert context.response.status_code == HTTPStatus.ACCEPTED, context.response.text
    body = context.response.json()
    moved_to = _git(context, "rev-parse", f"{ref}^{{commit}}").strip()
    assert (body["previous_commit_sha"], body["commit_sha"]) == (context.commits[ref], moved_to)
    assert wait_for_job(context, body["job_id"])["state"] == "succeeded", context.job
    assert version_commit(context, ref) == moved_to
    assert articles_of(context, ref), ref
    latest = context.client.get("/api/v1/jobs/latest").json()["jobs"]
    mine = {j["version"]: j for j in latest if j["library"] == LIBRARY}
    assert (mine[ref]["state"], mine[ref]["error_code"]) == ("succeeded", None), mine[ref]
    synced = context.client.post(f"/api/v1/libraries{LIBRARY}/sync").json()
    assert {v["ref"]: v["status"] for v in synced["versions"]}[ref] == "pinned", synced


@then('the re-import is refused with "{code}"')
def step_refused(context: Context, code: str) -> None:
    assert context.response.json()["error"] == code, context.response.text
    assert context.response.status_code in {HTTPStatus.CONFLICT, 422}, context.response.text
    assert len(_jobs(context)) == context.jobs_before, _jobs(context)
