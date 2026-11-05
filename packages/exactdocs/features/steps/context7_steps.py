"""Steps for the context7.json of the fixture repository (it is on the branch "next" only)."""

import json
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from exactdocs.retrieval.adapters.driving.mcp import RULES_HEADING
from steps.import_steps import LIBRARY, articles_of, import_version
from steps.mcp_steps import call_tool

REF = "next"
EDITED_TITLE = "Payments SDK"


def _context7(context: Context) -> dict:
    shown = context.fixture_git("show", f"{REF}:context7.json", cwd=context.fixture_repo.path)
    return json.loads(shown)


def _library(context: Context) -> dict:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _query_docs(context: Context) -> str:
    call_tool(context, "query-docs", {"libraryId": LIBRARY, "query": "install token"})
    return context.mcp_result.content[1].text


@given('the fixture repository has a context7.json with folders "{folders}" and rules "{rule}"')
def step_has_context7(context: Context, folders: str, rule: str) -> None:
    found = _context7(context)
    assert found["folders"] == folders.split(", "), found
    assert rule in found["rules"], found


@when("a user adds it")
def step_add_it(context: Context) -> None:
    import_version(context, REF)  # no paths, no title: everything comes from the repository
    assert context.job["state"] == "succeeded", context.job


@then("title, description and paths are pre-filled and still editable")
def step_prefilled(context: Context) -> None:
    found, library = _context7(context), _library(context)
    assert (library["title"], library["description"]) == (
        found["projectTitle"],
        found["description"],
    )
    assert library["settings"]["include_paths"] == ["docs/"], library["settings"]
    assert library["settings"]["exclude_paths"] == ["**/archive/", "**/CHANGELOG.md"]
    paths = [a["path"] for a in articles_of(context, REF)]
    assert paths, paths
    assert all(p.startswith("docs/") and "/archive/" not in p for p in paths), paths
    response = context.client.patch(f"/api/v1/libraries{LIBRARY}", json={"title": EDITED_TITLE})
    assert response.status_code == HTTPStatus.OK, response.text
    assert _library(context)["title"] == EDITED_TITLE


@then('"query-docs" for the library includes the rule "{rule}"')
def step_rule_in_query_docs(context: Context, rule: str) -> None:
    assert _library(context)["rules"][0] == rule
    payload = _query_docs(context)
    assert payload.startswith(f"{RULES_HEADING}- {rule}\n"), payload[:200]


@then('"query-docs" for the library has no rules')
def step_no_rules(context: Context) -> None:
    assert _library(context)["rules"] == []
    assert not _query_docs(context).startswith(RULES_HEADING)


@then('the library imports only "{include}"')
def step_only(context: Context, include: str) -> None:
    settings = _library(context)["settings"]
    assert (settings["include_paths"], settings["exclude_paths"]) == ([include], []), settings


@then("its title is the projectTitle of the context7.json")
def step_context7_title(context: Context) -> None:
    assert _library(context)["title"] == _context7(context)["projectTitle"]


@when('a user previews the fixture repository at "{ref}" without paths')
def step_preview_without_paths(context: Context, ref: str) -> None:
    context.response = context.client.post(
        "/api/v1/repositories/preview", json={"url": context.fixture_repo.file_url, "ref": ref}
    )
    assert context.response.status_code == HTTPStatus.OK, context.response.text


@then("the paths of the context7.json are applied")
def step_preview_paths(context: Context) -> None:
    body = context.response.json()
    assert body["include_paths"] == ["docs/"], body
    assert body["files"], body
    assert all(f.startswith("docs/") and "/archive/" not in f for f in body["files"]), body


@then('"{first}" and "{second}" are offered for import')
def step_offered(context: Context, first: str, second: str) -> None:
    offered = context.response.json()["context7"]["previous_versions"]
    assert [v["tag"] for v in offered] == [first, second], offered
