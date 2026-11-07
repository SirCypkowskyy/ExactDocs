"""Steps for selecting folders whose names have brackets, fetched from a small real repository."""

import asyncio
import shutil
import tempfile
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.models import (
    PathSelection,
    ProposedId,
    RepositoryHost,
    RepositoryUrl,
    context7_selection,
)


def _names(text: str) -> list[str]:
    return [name.strip() for name in text.split(",") if name.strip()]


@given('a repository with the files "{files}"')
def step_repository(context: Context, files: str) -> None:
    root = Path(tempfile.mkdtemp(prefix="brackets-"))
    context.add_cleanup(shutil.rmtree, root, ignore_errors=True)
    git = context.fixture_git
    git("init", "-q", "-b", "main", str(root))
    for name in _names(files):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {name}\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "x", cwd=root)
    context.bracket_repo = root
    context.bracket_commit = git("rev-parse", "HEAD", cwd=root)


def _import(context: Context, selection: PathSelection) -> None:
    root: Path = context.bracket_repo
    url = RepositoryUrl(
        url=root.as_uri(), host_kind=RepositoryHost.GIT, library_id=ProposedId("/acme/brackets")
    )

    async def fetch() -> list[str]:
        async with GitCli.locate().fetch(url, context.bracket_commit, selection) as folder:
            return sorted(
                path
                for p in folder.rglob("*")
                if p.is_file()
                and ".git" not in p.relative_to(folder).parts
                and selection.selects(path := p.relative_to(folder).as_posix())
            )

    context.imported = asyncio.run(fetch())


@when('it is imported with the paths "{include}" excluding "{exclude}"')
def step_import_paths(context: Context, include: str, exclude: str) -> None:
    _import(context, PathSelection.of(_names(include), _names(exclude)))


@when('it is imported with the paths "{include}" excluding ""')
def step_import_paths_only(context: Context, include: str) -> None:
    _import(context, PathSelection.of(_names(include), []))


@when(
    'it is imported with a context7.json with folders "{folders}" and excluded folders "{excluded}"'
)
def step_import_context7(context: Context, folders: str, excluded: str) -> None:
    selection = context7_selection(_names(folders), _names(excluded), [])
    assert selection is not None
    _import(context, selection)


@then('the imported articles are "{articles}"')
def step_articles(context: Context, articles: str) -> None:
    assert context.imported == sorted(_names(articles)), context.imported
