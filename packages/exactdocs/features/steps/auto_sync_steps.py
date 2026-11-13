"""Steps for the scheduled check: new tags imported automatically, branches re-synced."""

import time
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import (
    JOB_SECONDS,
    LIBRARY,
    import_version,
    start,
    version_commit,
)

EVERY_SECOND = "* * * * * *"  # DBOS cron, seconds first


@given("ExactDocs imports the fixture docs repository and ticks its schedule every second")
def step_running(context: Context) -> None:
    start(context, auto_sync_schedule=EVERY_SECOND)


@given('"{ref}" is added by hand')
def step_by_hand(context: Context, ref: str) -> None:
    import_version(context, ref)
    assert context.job["state"] == "succeeded", context.job


def _push_tag(context: Context, name: str) -> None:
    context.fixture_git("tag", name, "next", cwd=context.fixture_repo.path)


@given('tag "{name}" is pushed')
def step_push(context: Context, name: str) -> None:
    _push_tag(context, name)


def _schedule(context: Context, body: dict) -> None:
    context.auto_sync = body
    response = context.client.put(f"/api/v1/libraries{LIBRARY}/auto-sync", json=body)
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["enabled"], response.text


@given('"/fixture/docs-repo" auto-imports tags "{pattern}" keeping the last {keep:d}')
def step_auto_import(context: Context, pattern: str, keep: int) -> None:
    _schedule(context, {"tag_pattern": pattern, "keep_last": keep, "interval_minutes": 60})


@given('"/fixture/docs-repo" re-syncs its branches on a schedule')
def step_auto_branches(context: Context) -> None:
    _schedule(context, {"tag_pattern": None, "sync_branches": True, "interval_minutes": 60})
    _wait_for_check(context)  # the first check, at once: the branch has not moved yet


def _wait_for_check(context: Context) -> None:
    """Wait for a tick to check the library, then for every job it queued to end."""
    deadline = time.monotonic() + JOB_SECONDS
    while time.monotonic() < deadline:
        state = context.client.get(f"/api/v1/libraries{LIBRARY}/auto-sync").json()
        if state["checked_at"] is not None:
            assert state["last_error"] is None, state
            break
        time.sleep(0.05)
    else:
        message = "the scheduled check did not run"
        raise AssertionError(message)
    while time.monotonic() < deadline:
        jobs = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs").json()["jobs"]
        if all(job["state"] in {"succeeded", "failed"} for job in jobs):
            context.jobs = jobs
            return
        time.sleep(0.05)
    message = "the jobs of the scheduled check did not finish"
    raise AssertionError(message)


def _run_check(context: Context) -> None:
    """Let the next tick check the library: saving its schedule makes it due at once."""
    _schedule(context, context.auto_sync)
    _wait_for_check(context)


def _versions(context: Context) -> dict[str, str]:
    """The library's versions and their origin."""
    detail = context.client.get(f"/api/v1/libraries{LIBRARY}")
    assert detail.status_code == HTTPStatus.OK, detail.text
    return {v["ref"]: v["origin"] for v in detail.json()["versions"]}


@given('the scheduled check imported "{first}" and "{second}"')
def step_first_check(context: Context, first: str, second: str) -> None:
    _wait_for_check(context)
    versions = _versions(context)
    assert (versions.get(first), versions.get(second)) == ("auto", "auto"), versions
    assert all(job["state"] == "succeeded" for job in context.jobs), context.jobs


@when('tag "{name}" is pushed and the scheduled check runs')
def step_push_and_check(context: Context, name: str) -> None:
    _push_tag(context, name)
    _run_check(context)


@when("the scheduled check runs")
@when("the scheduled check runs again")
def step_check(context: Context) -> None:
    _run_check(context)


@then("the oldest auto-imported version is still served")
def step_still_served(context: Context) -> None:
    """Removed only once its replacement is a version: a check that queues does not prune."""
    versions = _versions(context)
    assert sorted(r for r, o in versions.items() if o == "auto") == ["v1.4.0", "v1.4.1", "v1.5.0"]


@then('"{ref}" is imported')
def step_imported(context: Context, ref: str) -> None:
    assert _versions(context).get(ref) == "auto", _versions(context)
    job = next(j for j in context.jobs if j["version"] == ref)
    assert (job["kind"], job["state"], job["origin"]) == ("import", "succeeded", "auto"), job


@then("the oldest auto-imported version is removed")
def step_pruned(context: Context) -> None:
    versions = _versions(context)
    assert "v1.4.0" not in versions, versions
    assert sorted(r for r, o in versions.items() if o == "auto") == ["v1.4.1", "v1.5.0"]


@then("manually imported versions are kept")
def step_manual_kept(context: Context) -> None:
    versions = _versions(context)
    assert (versions.get("v1.3.0"), versions.get("next")) == ("manual", "manual"), versions


@then('"/fixture/docs-repo/next" serves the new commit')
def step_new_commit(context: Context) -> None:
    assert version_commit(context, "next") == context.new_head != context.commits["next"]


@then("no tag was imported")
def step_no_tag(context: Context) -> None:
    assert _versions(context) == {"next": "manual", "v1.3.0": "manual"}
