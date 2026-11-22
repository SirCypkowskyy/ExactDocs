"""Steps for fetching one commit and a few paths of the fixture repository."""

import asyncio
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when
from behave.runner import Context

from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.models import PathSelection, ProposedId, RepositoryHost, RepositoryUrl
from steps.import_steps import LIBRARY, articles_of, import_version, start


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


def _own_repository(
    context: Context, articles: int, size: int, other: int, *, include: str = "docs/"
) -> None:
    """Commit ``articles`` Markdown files of ``size`` bytes and ``other`` bytes of data files."""
    base = Path(context.fixture_repo.path).parents[1] / f"own-{id(context)}"
    path = base / "fixture" / "docs-repo"
    git = context.fixture_git
    for n in range(articles):
        article = path / include / f"article-{n}.md"
        article.parent.mkdir(parents=True, exist_ok=True)
        article.write_text(f"# Article {n}\n\n" + ("some words here\n" * (size // 16)), "utf-8")
    for n in range(4 if other else 0):
        blob = path / include / "media" / f"data-{n}.bin"
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(os.urandom(other // 4))
    git("init", "-q", "-b", "main", cwd=path)
    git("config", "uploadpack.allowFilter", "true", cwd=path)  # blobless, as on a real host
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=path)
    git("add", ".", cwd=path)
    git("-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "x", cwd=path)
    git("tag", "v1.0.0", cwd=path)
    context.add_cleanup(shutil.rmtree, base, ignore_errors=True)
    context.import_repo = SimpleNamespace(path=path, file_url=path.as_uri())
    context.limits = {}


@given(
    'a repository whose "{folder}" folder holds {n:d} articles and {other:d} bytes of other files'
)
def step_repo_with_other_files(context: Context, folder: str, n: int, other: int) -> None:
    _own_repository(context, n, 100, other, include=folder)


@given('a repository whose "{folder}" folder holds {n:d} articles of {size:d} bytes each')
def step_repo_with_big_articles(context: Context, folder: str, n: int, size: int) -> None:
    _own_repository(context, n, size, 0, include=folder)


@given("ExactDocs fetches at most {limit:d} bytes")
def step_fetch_bound(context: Context, limit: int) -> None:
    context.limits["max_fetch_bytes"] = limit


@given("ExactDocs imports at most {limit:d} MiB of articles")
def step_import_bound(context: Context, limit: int) -> None:
    context.limits["max_import_bytes"] = limit * 2**20


@when('"{paths}" of that repository is imported')
def step_import_own(context: Context, paths: str) -> None:
    start(context, **context.limits)
    import_version(context, "v1.0.0", include_paths=[paths])


@then('"{target}" serves {n:d} articles')
def step_serves(context: Context, target: str, n: int) -> None:
    assert len(articles_of(context, target.removeprefix(LIBRARY + "/"))) == n


@then('the import fails with "{code}" saying "{words}"')
def step_fails_saying(context: Context, code: str, words: str) -> None:
    job = context.job
    assert (job["state"], job["error_code"]) == ("failed", code), job
    assert words in job["error"], job
