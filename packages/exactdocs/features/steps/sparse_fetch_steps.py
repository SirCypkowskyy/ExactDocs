"""Steps for fetching one commit and a few paths of the fixture repository."""

import asyncio
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.models import PathSelection, ProposedId, RepositoryHost, RepositoryUrl


def _files(folder: Path) -> list[str]:
    return sorted(
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(folder).parts
    )


@given('the fixture repository has history and files outside "{folder}"')
def step_history(context: Context, folder: str) -> None:
    git = context.fixture_git
    assert int(git("rev-list", "--count", "v1.4.0", cwd=context.fixture_repo.path)) > 1
    outside = git("ls-tree", "-r", "--name-only", "v1.4.0", cwd=context.fixture_repo.path)
    assert any(not line.startswith(folder) for line in outside.split("\n"))


@when('"{path}" at "{ref}" is fetched')
def step_fetch(context: Context, path: str, ref: str) -> None:
    repo = context.fixture_repo
    sha = context.fixture_git("rev-parse", f"{ref}^{{commit}}", cwd=repo.path)
    url = RepositoryUrl(
        url=repo.file_url, host_kind=RepositoryHost.GIT, library_id=ProposedId("/fixture/docs-repo")
    )

    async def fetch() -> None:
        async with GitCli.locate().fetch(url, sha, PathSelection.of([path])) as folder:
            context.checked_out = _files(folder)
            context.fetched_head = context.fixture_git("rev-parse", "HEAD", cwd=folder)
            context.fetched_commits = int(
                context.fixture_git("rev-list", "--all", "--count", cwd=folder)
            )

    asyncio.run(fetch())


@then('the working copy contains "{folder}" and the root README only')
def step_contents(context: Context, folder: str) -> None:
    files = context.checked_out
    assert "README.md" in files, files
    assert all(f == "README.md" or f.startswith(folder) for f in files), files
    assert any(f.startswith(folder) for f in files), files


@then('no commit older than "{ref}" was fetched')
def step_no_history(context: Context, ref: str) -> None:
    sha = context.fixture_git("rev-parse", f"{ref}^{{commit}}", cwd=context.fixture_repo.path)
    assert context.fetched_head == sha
    assert context.fetched_commits == 1, context.fetched_commits
