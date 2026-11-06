"""Steps for re-chunking a library whose articles have unusual front matter."""

from http import HTTPStatus

from behave import given, then
from behave.runner import Context

from steps.import_steps import LIBRARY, wait_for_job

# The front matter loads to nothing but is not empty; the block after it is not YAML, so the
# import keeps it as Markdown (no note) and cuts at the heading inside it.
ODD = (
    "---\n# only a comment\n---\n"
    "---\ntitle: [unclosed\n# {heading}\n\nQuokka notes.\n---\n"
    "# Real\n\nBody.\n"
)


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.fixture_repo.path)


@given(
    'a commit on branch "{branch}" adds "{path}" with a comment-only front matter and then an'
    ' invalid "---" block holding the heading "{heading}"'
)
def step_add_odd(context: Context, branch: str, path: str, heading: str) -> None:
    _git(context, "checkout", "-q", branch)
    (context.fixture_repo.path / path).write_text(ODD.format(heading=heading), encoding="utf-8")
    _git(context, "add", path)
    _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
         "commit", "-q", "-m", f"docs: add {path}")  # fmt: skip
    _git(context, "checkout", "-q", "main")


@then("the re-chunking job succeeds")
def step_rechunked(context: Context) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    assert response.json()["reprocess"] == "chunking", response.text
    context.job = wait_for_job(context, response.json()["job_id"])
    assert context.job["state"] == "succeeded", context.job
    assert context.job["kind"] == "rechunk", context.job


@given('searching "{query}" in "{ref}" finds the section "{heading}" of "{path}"')
@then('searching "{query}" in "{ref}" finds the section "{heading}" of "{path}"')
def step_section(context: Context, query: str, ref: str, heading: str, path: str) -> None:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": query, "ref": ref, "limit": 50}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    found = [r["heading_path"] for r in response.json()["results"] if r["article_path"] == path]
    assert [heading] in found, found


@then('the job has no note on "{path}"')
def step_no_note(context: Context, path: str) -> None:
    assert all(p["path"] != path for p in context.job["problems"]), context.job["problems"]
