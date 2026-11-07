"""Steps for importing folders whose names have brackets, from a branch of a private copy."""

import json

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import articles_of, import_version

CONTEXT7 = "context7.json"


def _names(text: str) -> list[str]:
    return [name.strip() for name in text.split(",") if name.strip()]


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.fixture_repo.path)


@given('a branch "{branch}" adds "{files}"')
def step_branch(context: Context, branch: str, files: str) -> None:
    """Branch off ``next`` (which has a context7.json) and commit the files there."""
    _git(context, "checkout", "-q", "-b", branch, "next")
    for name in _names(files):
        target = context.fixture_repo.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {name}\n\nAn article at {name}.\n", encoding="utf-8")
    _git(context, "add", "-A")
    _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
         "commit", "-q", "-m", "docs: bracketed folders")  # fmt: skip
    context.bracket_branch = branch


@given('its context7.json has the folders "{folders}" and the excluded folders "{excluded}"')
def step_context7(context: Context, folders: str, excluded: str) -> None:
    path = context.fixture_repo.path / CONTEXT7
    document = json.loads(path.read_text(encoding="utf-8"))
    document |= {"folders": _names(folders), "excludeFolders": _names(excluded)}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
         "commit", "-q", "-am", "docs: context7 names bracketed folders")  # fmt: skip
    _git(context, "checkout", "-q", "main")


def _added(context: Context) -> None:
    assert context.job["state"] == "succeeded", context.job


@when('"{ref}" is added with the paths "{include}" excluding "{exclude}"')
def step_add_paths(context: Context, ref: str, include: str, exclude: str) -> None:
    import_version(context, ref, include_paths=_names(include), exclude_paths=_names(exclude))
    _added(context)


@when('"{ref}" is added with the paths "{include}" excluding ""')
def step_add_include(context: Context, ref: str, include: str) -> None:
    import_version(context, ref, include_paths=_names(include))
    _added(context)


@when('"{ref}" is added without paths')
def step_add_no_paths(context: Context, ref: str) -> None:
    import_version(context, ref)  # the committed context7.json gives the paths
    _added(context)


@then('the articles of "{ref}" below "{folder}" are "{articles}"')
@then('the articles of "{ref}" below "{folder}" are ""')
def step_articles(context: Context, ref: str, folder: str, articles: str = "") -> None:
    found = sorted(a["path"] for a in articles_of(context, ref) if a["path"].startswith(folder))
    assert found == sorted(_names(articles)), found
