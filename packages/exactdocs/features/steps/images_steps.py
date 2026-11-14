"""Steps for the images articles reference: imported, then served by the asset route."""

import hashlib
from http import HTTPStatus

from behave import given, then
from behave.runner import Context

from steps.import_steps import LIBRARY, start


def _ref(target: str) -> str:
    return target.removeprefix(LIBRARY + "/")


def _asset(context: Context, path: str, ref: str):
    context.asset = context.client.get(
        f"/api/v1/libraries{LIBRARY}/asset", params={"ref": ref, "path": path}
    )
    context.asset_where = (ref, path)
    return context.asset


@given("ExactDocs imports the fixture docs repository with images limited to {limit:d} bytes")
def step_limited(context: Context, limit: int) -> None:
    start(context, max_image_bytes=limit)


@then('the image "{path}" of "{target}" is served as "{content_type}"')
def step_served(context: Context, path: str, target: str, content_type: str) -> None:
    response = _asset(context, path, _ref(target))
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.headers["content-type"] == content_type, response.headers


@then('the image "{path}" of "{target}" is not found')
def step_not_found(context: Context, path: str, target: str) -> None:
    assert _asset(context, path, _ref(target)).status_code == HTTPStatus.NOT_FOUND


@then('the served image is exactly the file of the repository at "{ref}"')
def step_exact(context: Context, ref: str) -> None:
    _, path = context.asset_where
    data = context.asset.content
    served = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    assert served == context.fixture_git(
        "rev-parse", f"{ref}:{path}", cwd=context.fixture_repo.path
    )


@then("the served image is a download that no script can run in")
def step_download(context: Context) -> None:
    headers = context.asset.headers
    assert headers["content-disposition"].startswith("attachment"), headers
    policy = headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "sandbox" in policy
    assert "script-src" not in policy


@then('the image "{path}" of "{target}" is served with the blob SHA as its ETag')
def step_etag(context: Context, path: str, target: str) -> None:
    ref = _ref(target)
    response = _asset(context, path, ref)
    blob = context.fixture_git("rev-parse", f"{ref}:{path}", cwd=context.fixture_repo.path)
    assert response.headers["etag"] == f'"{blob}"', response.headers
    again = context.client.get(
        f"/api/v1/libraries{LIBRARY}/asset",
        params={"ref": ref, "path": path},
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert again.status_code == HTTPStatus.NOT_MODIFIED


@then("the served image may not be sniffed or cached by a shared cache")
def step_headers(context: Context) -> None:
    headers = context.asset.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"].startswith("private"), headers


@then('the job lists the image "{path}" as skipped with the code "{code}"')
def step_listed(context: Context, path: str, code: str) -> None:
    found = [p for p in context.job["problems"] if p["path"] == path]
    assert [p["code"] for p in found] == [code], context.job["problems"]
    assert all(p["is_skip"] for p in found)
