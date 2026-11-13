"""Steps for push webhooks: signed deliveries from a forge queue a sync of the pushed ref."""

import hashlib
import hmac
import json
import time
from datetime import datetime
from http import HTTPStatus

import httpx
from behave import given, then, when
from behave.runner import Context

from steps.import_steps import JOB_SECONDS, LIBRARY, import_version, start, version_commit

HOOK = f"/api/v1/webhooks{LIBRARY}"
NEVER = "0 0 0 1 1 *"  # DBOS cron, seconds first: midnight on January 1st
PUSH_START_SECONDS = 30


@given("ExactDocs imports the fixture docs repository and never ticks its schedule")
def step_running(context: Context) -> None:
    start(context, auto_sync_schedule=NEVER)


def _secret(context: Context) -> str:
    """Import ``main`` (once) and turn the library's webhook on; remember the secret."""
    if not context.library_added:
        import_version(context, "main", include_paths=["docs/"])
        assert context.job["state"] == "succeeded", context.job
        context.served = {}
        context.commits = {"main": version_commit(context, "main")}
    if getattr(context, "webhook_secret", None) is None:
        response = context.client.put(f"/api/v1/libraries{LIBRARY}/webhook")
        assert response.status_code == HTTPStatus.OK, response.text
        body = response.json()
        assert body["url"].endswith(HOOK), body
        context.webhook_secret = body["secret"]
    return context.webhook_secret


def _github(context: Context, ref: str, *, delivery: str, secret: str | None) -> httpx.Response:
    body = json.dumps({"ref": ref, "deleted": False, "after": "1" * 40}).encode()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery,
    }
    if secret is not None:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={digest}"
    return context.client.post(HOOK, content=body, headers=headers)


def _jobs(context: Context) -> list[dict]:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["jobs"]


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


@given('the library "/fixture/docs-repo" has the branch version "main" and a webhook secret')
def step_secret(context: Context) -> None:
    _secret(context)


@given('"{path}" changed in a new commit on "{branch}"')
def step_commit(context: Context, path: str, branch: str) -> None:
    repo = context.fixture_repo.path
    context.fixture_git("checkout", "-q", branch, cwd=repo)
    with (repo / path).open("a", encoding="utf-8") as article:
        article.write("\n## Upgrading\n\nRe-run the installer after an upgrade.\n")
    context.fixture_git(
        "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
        "commit", "-q", "-am", f"docs: change {path}", cwd=repo,
    )  # fmt: skip
    context.new_head = context.fixture_git("rev-parse", "HEAD", cwd=repo)


@when('GitHub sends a push for "{ref}" signed with that secret')
def step_github_push(context: Context, ref: str) -> None:
    started = time.monotonic()
    context.answer = _github(context, ref, delivery="d-push", secret=_secret(context))
    context.answer_seconds = time.monotonic() - started


@then("the answer is 202 within a second")
def step_answer_fast(context: Context) -> None:
    assert context.answer.status_code == HTTPStatus.ACCEPTED, context.answer.text
    assert context.answer.json()["status"] == "queued", context.answer.text
    assert context.answer_seconds < 1, context.answer_seconds


@then('a sync of "{ref}" starts within 30 seconds while the library has no other job running')
def step_sync_starts(context: Context, ref: str) -> None:
    deadline = time.monotonic() + JOB_SECONDS
    while time.monotonic() < deadline:
        jobs = _jobs(context)
        push = next((j for j in jobs if j["kind"] == "push"), None)
        refresh = next((j for j in jobs if j["kind"] == "refresh" and j["version"] == ref), None)
        if (
            push is not None
            and push["state"] == "succeeded"
            and refresh is not None
            and refresh["state"] in {"succeeded", "failed"}
        ):
            break
        time.sleep(0.05)
    else:
        message = f"no sync of {ref!r} ran: {_jobs(context)}"
        raise AssertionError(message)
    assert push["version"] == ref, push
    waited = _moment(push["started_at"]) - _moment(push["created_at"])
    assert waited.total_seconds() < PUSH_START_SECONDS, push
    assert refresh["state"] == "succeeded", refresh
    assert version_commit(context, ref) == context.new_head != context.commits[ref]


@given('"/fixture/docs-repo" has an auto-sync with tag pattern "{pattern}"')
def step_auto_sync(context: Context, pattern: str) -> None:
    _secret(context)
    body = {"tag_pattern": pattern, "keep_last": 5, "interval_minutes": 60}
    response = context.client.put(f"/api/v1/libraries{LIBRARY}/auto-sync", json=body)
    assert response.status_code == HTTPStatus.OK, response.text


@when('GitLab sends a tag push for "{ref}" with the library\'s token')
def step_gitlab_tag(context: Context, ref: str) -> None:
    body = json.dumps(
        {"object_kind": "tag_push", "ref": ref, "before": "0" * 40, "after": "2" * 40}
    ).encode()
    context.answer = context.client.post(
        HOOK,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Gitlab-Event": "Tag Push Hook",
            "X-Gitlab-Token": _secret(context),
            "X-Gitlab-Event-UUID": "gl-1",
        },
    )
    assert context.answer.status_code == HTTPStatus.ACCEPTED, context.answer.text
    assert context.answer.json()["status"] == "queued", context.answer.text


@then('the auto-import of "{ref}" is queued as "{origin}"')
def step_auto_import(context: Context, ref: str, origin: str) -> None:
    deadline = time.monotonic() + JOB_SECONDS
    while time.monotonic() < deadline:
        found = [j for j in _jobs(context) if j["kind"] == "import" and j["version"] == ref]
        if found:
            assert found[0]["origin"] == origin, found
            return
        time.sleep(0.05)
    message = f"no import of {ref!r} was queued: {_jobs(context)}"
    raise AssertionError(message)


@when(
    "a push arrives without a signature, with a wrong signature, or for a library that does "
    "not exist"
)
def step_bad_pushes(context: Context) -> None:
    context.jobs_before = _jobs(context)
    unknown = context.client.post(
        "/api/v1/webhooks/fixture/no-such-repo",
        content=b'{"ref": "refs/heads/main"}',
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "d-3",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
    )
    context.answers = [
        _github(context, "refs/heads/main", delivery="d-1", secret=None),
        _github(context, "refs/heads/main", delivery="d-2", secret=_secret(context)[::-1]),
        unknown,
    ]


@then("each answer is 401 with the same body")
def step_same_401(context: Context) -> None:
    assert {a.status_code for a in context.answers} == {HTTPStatus.UNAUTHORIZED}
    bodies = {a.content for a in context.answers}
    assert len(bodies) == 1, bodies
    assert context.answers[0].json()["error"] == "invalid_signature"


@then("no job is queued")
def step_no_job(context: Context) -> None:
    assert _jobs(context) == context.jobs_before


@given('a delivery with ID "{delivery}" was accepted')
def step_accepted(context: Context, delivery: str) -> None:
    context.delivery = delivery
    answer = _github(context, "refs/heads/main", delivery=delivery, secret=_secret(context))
    assert answer.status_code == HTTPStatus.ACCEPTED, answer.text
    assert answer.json()["status"] == "queued", answer.text


@when("the same delivery arrives again")
def step_again(context: Context) -> None:
    context.answer = _github(
        context, "refs/heads/main", delivery=context.delivery, secret=_secret(context)
    )


@then('the answer is 202 "{status}" and no second job is queued')
def step_duplicate(context: Context, status: str) -> None:
    assert context.answer.status_code == HTTPStatus.ACCEPTED, context.answer.text
    assert context.answer.json()["status"] == status, context.answer.text
    assert len([j for j in _jobs(context) if j["kind"] == "push"]) == 1, _jobs(context)
