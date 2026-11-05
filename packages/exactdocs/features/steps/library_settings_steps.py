"""Steps for editing a library's paths and tag rules, which re-processes every version."""

from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import LIBRARY, articles_of, import_version, version_commit, wait_for_job

VERSIONS = ("v1.3.0", "v1.4.0")
ARCHIVE = "docs/archive/"


def _settings(context: Context) -> dict:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["settings"]


def _put(context: Context, **changes: object) -> None:
    current = _settings(context)
    body = {
        "include_paths": current["include_paths"],
        "exclude_paths": current["exclude_paths"],
        "tag_rules": current["tag_rules"],
    } | changes
    context.response = context.client.put(f"/api/v1/libraries{LIBRARY}/settings", json=body)


def _jobs(context: Context) -> list[dict]:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["jobs"]


def _tags(context: Context, ref: str, path: str) -> list[str]:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/article", params={"ref": ref, "path": path}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["tags"]


@given('"/fixture/docs-repo" has versions "v1.3.0" and "v1.4.0"')
def step_versions(context: Context) -> None:
    for ref in VERSIONS:
        import_version(context, ref, include_paths=["docs/"])
        assert context.job["state"] == "succeeded", context.job
    context.commits = {ref: version_commit(context, ref) for ref in VERSIONS}
    for ref in VERSIONS:
        assert any(a["path"].startswith(ARCHIVE) for a in articles_of(context, ref))
    context.jobs_before = len(_jobs(context))


@given("the repository can no longer be fetched")
def step_unfetchable(context: Context) -> None:
    context.git.failing = True
    context.renames.failing = True


@when('the user adds the exclusion "{pattern}"')
def step_exclude(context: Context, pattern: str) -> None:
    context.git.held = True  # the re-processing job waits at its first fetch
    context.add_cleanup(setattr, context.git, "held", False)
    _put(context, exclude_paths=[*_settings(context)["exclude_paths"], pattern])


@when('the user sets the exclusion "{pattern}"')
def step_set_exclusion(context: Context, pattern: str) -> None:
    _put(context, exclude_paths=[pattern])


@when('the user sets the tag rule "{rule}"')
def step_tag_rule(context: Context, rule: str) -> None:
    pattern, tag = rule.split(" -> ")
    _put(context, tag_rules=[{"pattern": pattern, "tag": tag}])


@when("the user saves the library's settings unchanged")
def step_unchanged(context: Context) -> None:
    _put(context)


@then("a job re-processes both versions")
def step_job(context: Context) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    body = response.json()
    assert body["exclude_paths"] == ["docs/archive/**"], body
    assert sorted(body["versions"]) == list(VERSIONS), body
    assert body["reprocess"] == "paths", body
    job = context.client.get(response.headers["Location"]).json()
    assert job["id"] == body["job_id"], job
    assert job["kind"] == "reprocess", job
    assert job["library"] == LIBRARY, job
    context.job_id = body["job_id"]


@then('until it finishes, both versions still list "docs/archive/" articles')
def step_old_state(context: Context) -> None:
    assert context.client.get(f"/api/v1/jobs/{context.job_id}").json()["state"] in {
        "queued",
        "running",
    }
    for ref in VERSIONS:
        assert any(a["path"].startswith(ARCHIVE) for a in articles_of(context, ref)), ref


@then("afterwards neither does")
def step_new_state(context: Context) -> None:
    context.git.held = False
    job = wait_for_job(context, context.job_id)
    assert job["state"] == "succeeded", job
    for ref in VERSIONS:
        paths = [a["path"] for a in articles_of(context, ref)]
        assert paths, ref
        assert not any(p.startswith(ARCHIVE) for p in paths), (ref, paths)


@then("both versions keep their commits")
def step_commits(context: Context) -> None:
    assert {ref: version_commit(context, ref) for ref in VERSIONS} == context.commits


@then("the re-processing job succeeds without fetching")
def step_retagged(context: Context) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    assert response.json()["reprocess"] == "tags", response.text
    job = wait_for_job(context, response.json()["job_id"])
    assert job["state"] == "succeeded", job
    assert job["kind"] == "retag", job


@then('"{path}" is tagged "{tag}" in both versions')
def step_tagged(context: Context, path: str, tag: str) -> None:
    for ref in VERSIONS:
        assert tag in _tags(context, ref, path), (ref, path)


@then('searching both versions with the tag "{tag}" finds only guide articles')
def step_search(context: Context, tag: str) -> None:
    for ref in VERSIONS:
        response = context.client.get(
            f"/api/v1/libraries{LIBRARY}/search",
            params={"q": "token", "ref": ref, "tags": [tag], "limit": 50},
        )
        assert response.status_code == HTTPStatus.OK, response.text
        found = {r["article_path"] for r in response.json()["results"]}
        assert found, ref
        assert all(p.startswith("docs/guide/") for p in found), (ref, found)


@then('"{path}" keeps its front-matter tags in both versions')
def step_front_matter(context: Context, path: str) -> None:
    for ref in VERSIONS:
        assert _tags(context, ref, path) == ["auth"], ref


@then("the settings are refused as invalid")
def step_refused(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, context.response.text


@then("no re-processing job is queued")
def step_no_job(context: Context) -> None:
    assert len(_jobs(context)) == context.jobs_before
    assert "docs/archive/**" not in _settings(context)["exclude_paths"]
    assert _settings(context)["exclude_paths"] == []


@then("the settings are accepted without a job")
def step_no_job_needed(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.response.json()["job_id"] is None, context.response.text
    assert len(_jobs(context)) == context.jobs_before
