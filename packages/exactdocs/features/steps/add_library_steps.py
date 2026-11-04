"""Steps for creating a library over the REST API."""

from http import HTTPStatus

from behave import then, when
from behave.runner import Context


def _commit(context: Context, ref: str) -> str:
    return context.fixture_git("rev-parse", f"{ref}^{{commit}}", cwd=context.fixture_repo.path)


def _add(context: Context, **body: object) -> None:
    body.setdefault("url", context.fixture_repo.file_url)
    context.response = context.client.post("/api/v1/libraries", json=body)


@when('a user adds the fixture repository with paths "{paths}" and no ref')
def step_add_no_ref(context: Context, paths: str) -> None:
    _add(context, include_paths=[paths])


@when('a user adds the fixture repository with paths "{paths}" and the ref "{ref}"')
def step_add_ref(context: Context, paths: str, ref: str) -> None:
    _add(context, include_paths=[paths], ref=ref)


@when('a user adds the fixture repository with paths "{paths}" and the short SHA of "{ref}"')
def step_add_short(context: Context, paths: str, ref: str) -> None:
    _add(context, include_paths=[paths], ref=_commit(context, ref)[:9])


@when('a user adds the fixture repository with paths "{paths}" and exclusion "{exclusion}"')
def step_add_exclusion(context: Context, paths: str, exclusion: str) -> None:
    _add(context, include_paths=[paths], exclude_paths=[exclusion])


@when('a user adds the fixture repository as "{library_id}"')
def step_add_as(context: Context, library_id: str) -> None:
    _add(context, library_id=library_id)


@when("a user lists the refs of the fixture repository")
def step_refs(context: Context) -> None:
    url = context.fixture_repo.file_url
    context.response = context.client.get("/api/v1/repositories/refs", params={"url": url})


@then("the library has a version for the default branch")
def step_default_branch(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    body = context.response.json()
    assert (body["library_id"], body["ref"], body["ref_kind"]) == (
        "/fixture/docs-repo",
        "main",
        "branch",
    ), body


@then("that version records the branch head commit SHA")
def step_head(context: Context) -> None:
    assert context.response.json()["commit_sha"] == _commit(context, "main")


@then("an import job is queued for that version")
def step_job(context: Context) -> None:
    added = context.response.json()
    job = context.client.get(f"/api/v1/jobs/{added['job_id']}")
    assert job.status_code == HTTPStatus.OK, job.text
    body = job.json()
    assert (body["kind"], body["library"], body["version"], body["commit_sha"]) == (
        "import",
        added["library_id"],
        added["ref"],
        added["commit_sha"],
    ), body


@then('the version is "{ref}" and records the commit of "{commit}"')
def step_version(context: Context, ref: str, commit: str) -> None:
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    body = context.response.json()
    assert (body["ref"], body["commit_sha"]) == (ref, _commit(context, commit)), body


@then('the version is the full SHA of "{ref}"')
def step_full_sha(context: Context, ref: str) -> None:
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    body = context.response.json()
    sha = _commit(context, ref)
    assert (body["ref"], body["ref_kind"], body["commit_sha"]) == (sha, "commit", sha), body


@then('the request fails with "{code}"')
def step_fails(context: Context, code: str) -> None:
    assert context.response.status_code in {409, 422}, context.response.text
    assert context.response.json()["error"] == code, context.response.text


@then('the library "{library_id}" does not exist')
def step_absent(context: Context, library_id: str) -> None:
    response = context.client.get(f"/api/v1/libraries{library_id}")
    assert response.status_code == HTTPStatus.NOT_FOUND, response.text


@then('the library keeps the inclusion "{include}" and the exclusion "{exclude}"')
def step_selection(context: Context, include: str, exclude: str) -> None:
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    library = context.client.get(f"/api/v1/libraries{context.response.json()['library_id']}")
    settings = library.json()["settings"]
    assert (settings["include_paths"], settings["exclude_paths"]) == ([include], [exclude])


@then('the default branch is "{default}", the branches are "{branches}" and the tags are "{tags}"')
def step_listed(context: Context, default: str, branches: str, tags: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert body["default_branch"] == default
    assert [b["name"] for b in body["branches"]] == branches.split(", ")
    assert [t["name"] for t in body["tags"]] == tags.split(", ")
