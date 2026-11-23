"""Steps for the logo a library takes from its repository and ExactDocs serves (#504)."""

import re
from http import HTTPStatus

from behave import given, step, then
from behave.runner import Context

from steps.import_steps import LIBRARY

LOGO = f"/api/v1/libraries{LIBRARY}/logo"
BRANDED_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" onclick="steal()">
  <title>Acme Payments, from the README</title>
  <script>steal()</script>
  <circle cx="16" cy="16" r="14" fill="#2856c8"/>
</svg>
"""


def _library(context: Context) -> dict:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given('a branch "{branch}" whose README opens with the logo "{path}"')
def step_branded(context: Context, branch: str, path: str) -> None:
    """Branch off ``v1.3.0`` with a logo file and a README that shows it; needs a private copy."""
    repo = context.fixture_repo.path

    def git(*args: str) -> str:
        return context.fixture_git(*args, cwd=repo)

    git("checkout", "-q", "-b", branch, "v1.3.0")
    readme = repo / "README.md"
    shown = f'<p align="center"><img src="{path}" alt="Acme Payments"></p>\n\n'
    readme.write_text(shown + readme.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(BRANDED_LOGO, encoding="utf-8")
    git("add", "-A")
    git("-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
        "commit", "-q", "-m", "docs: show the logo in the README")  # fmt: skip
    git("checkout", "-q", "main")


@given('a commit redrew "{path}" on branch "{branch}"')
def step_redrawn(context: Context, path: str, branch: str) -> None:
    """Commit a new drawing of the logo on ``branch``; needs a private copy."""
    repo = context.fixture_repo.path

    def git(*args: str) -> str:
        return context.fixture_git(*args, cwd=repo)

    context.logo_before = _library(context)["logo"]
    git("checkout", "-q", branch)
    redrawn = BRANDED_LOGO.replace("from the README", "redrawn").replace("#2856c8", "#28c856")
    (repo / path).write_text(redrawn, encoding="utf-8")
    git("-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
        "commit", "-q", "-am", "chore: redraw the logo")  # fmt: skip
    git("checkout", "-q", "main")


@then("the library has a new logo")
def step_new_logo(context: Context) -> None:
    step_has_logo(context)
    version = _library(context)["logo"]
    assert version != context.logo_before, "the logo did not change"
    context.logo = context.client.get(LOGO, params={"v": version})
    assert context.logo.status_code == HTTPStatus.OK, context.logo.text


@step("the library has a logo")
def step_has_logo(context: Context) -> None:
    (listed,) = [
        lib
        for lib in context.client.get("/api/v1/libraries").json()["libraries"]
        if lib["id"] == LIBRARY
    ]
    version = _library(context)["logo"]
    assert version, "the library has no logo"
    assert listed["logo"] == version


@then("the library has no logo")
def step_no_logo(context: Context) -> None:
    assert _library(context)["logo"] is None
    response = context.client.get(LOGO)
    assert response.status_code == HTTPStatus.NOT_FOUND, response.text


@then('the logo is served by ExactDocs as "{content_type}"')
def step_served(context: Context, content_type: str) -> None:
    version = _library(context)["logo"]
    context.logo = context.client.get(LOGO, params={"v": version})
    assert context.logo.status_code == HTTPStatus.OK, context.logo.text
    assert context.logo.headers["content-type"] == content_type, context.logo.headers
    assert context.logo.headers["etag"] == f'"{version}"'


@then('the served logo is the drawing of "{path}" at "{ref}" without its script')
def step_drawing(context: Context, path: str, ref: str) -> None:
    original = context.fixture_git("show", f"{ref}:{path}", cwd=context.fixture_repo.path)
    served = context.logo.content.decode()
    title = re.search(r"<title>.*?</title>", original)
    assert title is not None
    assert title.group() in served, served
    assert "<script" in original
    for gone in ("<script", "onload", "onclick", "alert", "steal"):
        assert gone not in served, served


@then("the served logo is a download no script can run in, kept until the logo changes")
def step_hardened(context: Context) -> None:
    headers = context.logo.headers
    assert headers["content-disposition"].startswith("attachment"), headers
    policy = headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "sandbox" in policy
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "private, max-age=31536000, immutable", headers
