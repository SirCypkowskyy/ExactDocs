"""Steps for the sources file: the real CLI against a server on a loopback port."""

import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from steps.cli_library_steps import JOB_SECONDS, run
from steps.cli_login_steps import HORSE

FILE = "exactdocs.sources.yaml"


def _admin(context: Context) -> None:
    context.client.post("/api/v1/session", json={"username": "ada", "password": HORSE})


def _manual_jobs(context: Context, library: str) -> list[dict]:
    _admin(context)
    response = context.client.get(f"/api/v1/libraries{library}/jobs")
    assert response.status_code == HTTPStatus.OK, response.text
    return [j for j in response.json()["jobs"] if j["origin"] == "manual"]


def _section(output: str, name: str) -> list[str]:
    """The items listed under ``name:`` in the readable diff."""
    items: list[str] = []
    inside = False
    for line in output.splitlines():
        if not line.startswith(" "):
            inside = line == f"{name}:"
        elif inside and line.startswith("  ") and not line.startswith("    "):
            items.append(line.split()[1])
    return items


def _library_ids(context: Context) -> list[str]:
    _admin(context)
    return [lib["id"] for lib in context.client.get("/api/v1/libraries").json()["libraries"]]


@given(
    'a sources file declaring "{library}" at ref "{ref}" with tag pattern "{pattern}" '
    'and include path "{path}"'
)
def step_sources_file(context: Context, library: str, ref: str, pattern: str, path: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-sources-")))
    context.sources_file = folder / FILE
    context.sources_file.write_text(
        "# yaml-language-server: $schema=https://example.invalid/exactdocs.sources.schema.json\n"
        "version: 1\n"
        "libraries:\n"
        f"  - url: {context.fixture_repo.file_url}\n"
        f"    id: {library}\n"
        f"    refs: [{ref}]\n"
        f"    include_paths: [{path}]\n"
        "    auto_sync:\n"
        f"      tag_pattern: '{pattern}'\n",
        encoding="utf-8",
    )


@given("an instance with no libraries")
def step_no_libraries(context: Context) -> None:
    assert _library_ids(context) == []


@when('the operator runs "exactdocs sources {rest}"')
def step_operator_runs(context: Context, rest: str) -> None:
    run(context, f"exactdocs sources {rest}".replace(FILE, str(context.sources_file)))


@when('the operator runs "apply" again')
def step_apply_again(context: Context) -> None:
    context.jobs_before = _manual_jobs(context, "/fixture/docs-repo")
    run(context, context.line)


@then('the output lists "{library}" under "{section}"')
def step_listed_under(context: Context, library: str, section: str) -> None:
    assert library in _section(context.output, section), context.output


@then("the instance still has no libraries and no jobs")
def step_nothing(context: Context) -> None:
    assert _library_ids(context) == []
    assert context.client.get("/api/v1/jobs/latest").json()["jobs"] == []


@then('"{library}" exists with include path "{path}" and an auto-sync with tag pattern "{pattern}"')
def step_exists(context: Context, library: str, path: str, pattern: str) -> None:
    _admin(context)
    detail = context.client.get(f"/api/v1/libraries{library}").json()
    assert detail["settings"]["include_paths"] == [path], detail
    schedule = context.client.get(f"/api/v1/libraries{library}/auto-sync").json()
    assert (schedule["enabled"], schedule["tag_pattern"]) == (True, pattern), schedule


@then('an import of "{ref}" is queued')
def step_import_queued(context: Context, ref: str) -> None:
    jobs = _manual_jobs(context, "/fixture/docs-repo")
    assert [(j["kind"], j["version"]) for j in jobs] == [("import", ref)], jobs


@then("the second apply reports no changes and queues no job")
def step_no_changes(context: Context) -> None:
    assert context.exit_code == 0, (context.exit_code, context.errors)
    assert "No changes." in context.output, context.output
    after = _manual_jobs(context, "/fixture/docs-repo")
    assert [j["id"] for j in after] == [j["id"] for j in context.jobs_before]


@given('the instance also has the library "{library}", which the file does not declare')
def step_other_library(context: Context, library: str) -> None:
    _admin(context)
    body = {"url": context.fixture_repo.file_url, "library_id": library, "ref": "v1.4.0"}
    response = context.client.post("/api/v1/libraries", json=body)
    assert response.status_code == HTTPStatus.CREATED, response.text
    deadline = time.monotonic() + JOB_SECONDS  # removing it waits for no import
    job: dict = {}
    while time.monotonic() < deadline:
        job = context.client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()
        if job["state"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert job["state"] == "succeeded", job


@then('"{library}" is listed under "{section}" and still exists')
def step_listed_and_kept(context: Context, library: str, section: str) -> None:
    assert context.exit_code == 0, (context.exit_code, context.errors)
    assert library in _section(context.output, section), context.output
    assert library in _library_ids(context)


@then('"{library}" is removed')
def step_removed(context: Context, library: str) -> None:
    assert context.exit_code == 0, (context.exit_code, context.errors, context.output)
    assert library not in _library_ids(context)


@given('the sources file also declares the title "{title}" and the description "{description}"')
def step_declares_texts(context: Context, title: str, description: str) -> None:
    with context.sources_file.open("a", encoding="utf-8") as file:
        file.write(f"    title: '{title}'\n    description: '{description}'\n")


@when('the sources file declares the title "{title}"')
def step_declares_title(context: Context, title: str) -> None:
    lines = context.sources_file.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if not line.startswith("    title:")]
    context.sources_file.write_text("".join(kept) + f"    title: '{title}'\n", encoding="utf-8")


@then('the output shows the title changing to "{title}"')
def step_title_change(context: Context, title: str) -> None:
    assert f'title: "Azure Functions" -> "{title}"' in context.output, context.output


@then('"{library}" has the title "{title}" and the description "{description}"')
def step_has_texts(context: Context, library: str, title: str, description: str) -> None:
    assert context.exit_code == 0, (context.exit_code, context.errors, context.output)
    _admin(context)
    detail = context.client.get(f"/api/v1/libraries{library}").json()
    assert (detail["title"], detail["description"]) == (title, description), detail


@then('the library "{library}" was named by its README')
def step_readme_title(context: Context, library: str) -> None:
    assert context.exit_code == 0, (context.exit_code, context.errors, context.output)
    _admin(context)
    detail = context.client.get(f"/api/v1/libraries{library}").json()
    assert detail["title"] not in {"", "Azure Functions"}, detail
