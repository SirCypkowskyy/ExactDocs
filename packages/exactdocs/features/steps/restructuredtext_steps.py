"""Steps for Sphinx documentation in reStructuredText, imported like Markdown (#435)."""

import re
import shutil
from http import HTTPStatus
from pathlib import Path

from behave import given, then
from behave.runner import Context

from steps.import_steps import LIBRARY, articles_of
from steps.read_steps import outline_nodes

SPHINX = Path(__file__).parents[2] / "tests" / "fixtures" / "sphinx-docs"
"""The fixture Sphinx documentation; its ``doc/`` folder is copied into the branch."""


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.fixture_repo.path)


def _article(context: Context, path: str, ref: str) -> dict:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/article", params={"path": path, "ref": ref}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given('a branch "{branch}" adds the fixture Sphinx documentation')
def step_branch(context: Context, branch: str) -> None:
    """Branch off ``main`` (Markdown in ``docs/``) and add the Sphinx ``doc/`` folder."""
    _git(context, "checkout", "-q", "-b", branch, "main")
    shutil.copytree(SPHINX / "doc", context.fixture_repo.path / "doc")
    _git(context, "add", "-A")
    _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
         "commit", "-q", "-m", "docs: Sphinx documentation")  # fmt: skip
    _git(context, "checkout", "-q", "main")


@then('every reStructuredText article of the Sphinx documentation is an article of "{ref}"')
def step_every_rst(context: Context, ref: str) -> None:
    wanted = sorted(p.relative_to(SPHINX).as_posix() for p in SPHINX.joinpath("doc").rglob("*.rst"))
    found = sorted(a["path"] for a in articles_of(context, ref))
    assert found == wanted, found  # no conf.py, no example .py, no .txt (no path names it)


@then('the article "{path}" of "{ref}" is titled "{title}"')
def step_title(context: Context, path: str, ref: str, title: str) -> None:
    assert _article(context, path, ref)["title"] == title
    context.rst_path, context.rst_ref = path, ref


@then("its outline lists {headings}, in that order")
def step_outline(context: Context, headings: str) -> None:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/outline",
        params={"path": context.rst_path, "ref": context.rst_ref},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    listed = [path[-1] for path, _ in outline_nodes(response.json()["sections"])]
    assert listed == re.findall(r'"([^"]+)"', headings), listed


@then('a search of "{ref}" for "{query}" finds the section "{heading}" of "{path}"')
def step_search_section(context: Context, ref: str, query: str, heading: str, path: str) -> None:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": query, "ref": ref}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    *parents, last = heading.split(" > ")
    hits = [r for r in response.json()["results"] if r["article_path"] == path]
    assert hits, response.json()["results"]
    chunk = _chunk(context, hits[0]["chunk_id"])
    # The chunk is named after its first heading; a deeper one may ride along (split depth).
    assert chunk["heading_path"] == [*parents, last][: len(chunk["heading_path"])], chunk
    assert f"### {last}\n" in chunk["content"] or chunk["heading_path"][-1] == last, chunk
    context.rst_chunk = chunk


def _chunk(context: Context, chunk_id: str) -> dict:
    response = context.client.get(f"/api/v1/chunks/{chunk_id}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@then('reading that section gives its "{language}" code block and its tables')
def step_read_section(context: Context, language: str) -> None:
    chunk = context.rst_chunk
    assert f"```{language}\n" in chunk["content"], chunk
    text = chunk["content"]
    while "| Phase | Order | Notes |" not in text and chunk["next_chunk_id"]:
        chunk = _chunk(context, chunk["next_chunk_id"])
        text += chunk["content"]
    assert "| Phase | Order | Notes |\n| --- | --- | --- |" in text, text


@then('the article "{path}" of "{ref}" reads as Markdown:')
def step_reads_as(context: Context, path: str, ref: str) -> None:
    content = _article(context, path, ref)["content"]
    assert context.table is not None
    for row in context.table:
        assert row["text"] in content, (row["what"], content)


@then('the article "{path}" of "{ref}" does not contain "{text}"')
def step_lacks(context: Context, path: str, ref: str, text: str) -> None:
    assert text not in _article(context, path, ref)["content"]


@then('the job lists "{path}" as imported with a markup problem naming "{first}" and "{second}"')
def step_markup_problem(context: Context, path: str, first: str, second: str) -> None:
    problems = [p for p in context.job["problems"] if p["path"] == path]
    assert len(problems) == 1, context.job["problems"]
    (problem,) = problems
    assert problem["code"] == "markup", problem
    assert not problem["is_skip"], problem
    assert first in problem["reason"], problem
    assert second in problem["reason"], problem


@then('no file of "{ref}" failed the import')
def step_no_failure(context: Context, ref: str) -> None:
    assert context.job["state"] == "succeeded", context.job
    assert not [p for p in context.job["problems"] if p["is_skip"]], context.job["problems"]
    assert articles_of(context, ref)


@then('a search of "{ref}" for "{query}" finds an article below "{folder}"')
def step_search_below(context: Context, ref: str, query: str, folder: str) -> None:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": query, "ref": ref}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    paths = [r["article_path"] for r in response.json()["results"]]
    assert any(p.startswith(folder) for p in paths), paths
