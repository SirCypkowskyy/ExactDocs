import asyncio
import os
import stat
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.git_cli import GitCli, MissingGit, sparse_patterns
from exactdocs.ingestion.errors import (
    CommitUnavailableError,
    GitNotInstalledError,
    InvalidRepositoryUrlError,
    NotAGitRepositoryError,
    RepositoryTooLargeError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import PathSelection, ProposedId, RepositoryHost, RepositoryUrl
from fixture_repo import DocsRepo, git


def repository(url: str) -> RepositoryUrl:
    return RepositoryUrl(url=url, host_kind=RepositoryHost.GIT, library_id=ProposedId("/x/y"))


def sha(docs_repo: DocsRepo, ref: str) -> str:
    return git("rev-parse", f"{ref}^{{commit}}", cwd=docs_repo.path)


def files(folder: Path) -> set[str]:
    return {
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(folder).parts
    }


def leftovers(work: Path) -> list[Path]:
    return list(work.iterdir())


@pytest.fixture
def work(tmp_path: Path) -> Path:
    return tmp_path / "work"


@pytest.fixture
def gateway(work: Path) -> GitCli:
    return GitCli.locate(work_root=work)


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
async def test_fetches_one_commit_and_the_selected_paths_only(
    gateway: GitCli, docs_repo: DocsRepo, transport: str, work: Path
) -> None:
    pinned = sha(docs_repo, "v1.4.0")
    selection = PathSelection.of(["docs/guide/"])

    async with gateway.fetch(repository(getattr(docs_repo, transport)), pinned, selection) as dir_:
        assert dir_.parent == work
        assert files(dir_) == {
            "README.md",
            *(f"docs/guide/{n}" for n in ("auth.md", "callouts.md", "configuration.md",
                                          "install.md", "resilience.md")),
        }  # fmt: skip
        assert git("rev-parse", "HEAD", cwd=dir_) == pinned
        assert git("rev-list", "--all", "--count", cwd=dir_) == "1"
        local = git("cat-file", "--batch-all-objects", "--batch-check", cwd=dir_).split("\n")
        blobs = [line for line in local if " blob " in line]
        assert len(blobs) == 6  # the README and five guides, nothing else
        content = (dir_ / "docs/guide/install.md").read_text("utf-8")
        assert content == git("show", f"{pinned}:docs/guide/install.md", cwd=docs_repo.path) + "\n"
    assert not dir_.exists()


async def test_exclusions_win(gateway: GitCli, docs_repo: DocsRepo) -> None:
    selection = PathSelection.of(["docs/"], ["docs/legacy/", "docs/reference/", "**/*.png"])

    async with gateway.fetch(
        repository(docs_repo.file_url), sha(docs_repo, "v1.3.0"), selection
    ) as dir_:
        found = files(dir_)

    assert "docs/index.md" in found
    assert not any(f.startswith(("docs/legacy/", "docs/reference/")) for f in found)
    assert "docs/assets/logo.png" not in found


async def test_the_folder_is_removed_when_the_body_fails(
    gateway: GitCli, docs_repo: DocsRepo, work: Path
) -> None:
    with pytest.raises(RuntimeError):
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of()
        ):
            raise RuntimeError

    assert leftovers(work) == []


async def test_the_folder_is_removed_when_the_fetch_fails(
    gateway: GitCli, docs_repo: DocsRepo, work: Path
) -> None:
    with pytest.raises(CommitUnavailableError):
        async with gateway.fetch(repository(docs_repo.file_url), "0" * 40, PathSelection.of()):
            pass

    assert leftovers(work) == []


async def test_a_missing_repository_is_reported(gateway: GitCli, tmp_path: Path) -> None:
    with pytest.raises(NotAGitRepositoryError):
        async with gateway.fetch(
            repository((tmp_path / "nope").as_uri()), "1" * 40, PathSelection.of()
        ):
            pass


async def test_runs_out_of_time(docs_repo: DocsRepo, work: Path) -> None:
    gateway = GitCli.locate(work_root=work)
    gateway = GitCli(git=gateway.git, work_root=work, fetch_timeout=0.001)

    with pytest.raises(RepositoryUnreachableError):
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of()
        ):
            pass

    assert leftovers(work) == []


async def test_refuses_more_than_the_size_cap(docs_repo: DocsRepo, work: Path) -> None:
    gateway = GitCli(git=GitCli.locate().git, work_root=work, max_fetch_bytes=1000)

    with pytest.raises(RepositoryTooLargeError):
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of(["docs/"])
        ):
            pass

    assert leftovers(work) == []


@pytest.mark.parametrize(
    ("url", "commit"),
    [("-x", "1" * 40), ("file:///a b\n", "1" * 40), ("file:///x", "main"), ("file:///x", "--all")],
)
async def test_refuses_what_could_be_an_option(gateway: GitCli, url: str, commit: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        async with gateway.fetch(repository(url), commit, PathSelection.of()):
            pass


async def test_hooks_never_run(gateway: GitCli, docs_repo: DocsRepo, tmp_path: Path) -> None:
    """A hook in the *remote* is not copied, and ours has no hooks path to run from."""
    marker = tmp_path / "ran"
    hook = docs_repo.path / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    try:
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of(["docs/"])
        ) as dir_:
            config = git("config", "--local", "--get", "core.hookspath", cwd=dir_)
            assert config == os.devnull
    finally:
        hook.unlink()

    assert not marker.exists()


async def test_symlinks_become_plain_files(tmp_path: Path, gateway: GitCli) -> None:
    origin = tmp_path / "origin"
    git("init", "-q", "-b", "main", str(origin))
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=origin)
    (origin / "docs").mkdir()
    (origin / "docs" / "a.md").write_text("# A\n")
    (origin / "docs" / "evil.md").symlink_to("/etc/passwd")
    git("add", "-A", cwd=origin)
    git(
        "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "x",
        cwd=origin,
    )  # fmt: skip

    async with gateway.fetch(
        repository(origin.as_uri()),
        git("rev-parse", "HEAD", cwd=origin),
        PathSelection.of(["docs/"]),
    ) as dir_:
        evil = dir_ / "docs" / "evil.md"
        assert not evil.is_symlink()
        assert evil.read_text() == "/etc/passwd"


async def test_a_server_without_filter_support_still_serves_the_commit(
    gateway: GitCli, docs_repo: DocsRepo
) -> None:
    git("config", "uploadpack.allowFilter", "false", cwd=docs_repo.path)
    try:
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "v1.4.0"), PathSelection.of(["docs/"])
        ) as dir_:
            assert "docs/index.md" in files(dir_)
            assert git("rev-list", "--all", "--count", cwd=dir_) == "1"
    finally:
        git("config", "uploadpack.allowFilter", "true", cwd=docs_repo.path)


async def test_a_server_that_refuses_bare_shas_is_asked_for_the_ref(
    tmp_path: Path, docs_repo: DocsRepo
) -> None:
    # Protocol v2 servers serve any SHA, so the refusal is played by a wrapper around git.
    pinned = sha(docs_repo, "v1.4.0")
    wrapper = tmp_path / "git"
    wrapper.write_text(
        f'#!/bin/sh\ncase " $* " in *" fetch "*" {pinned} ") '
        f'echo "fatal: remote error: upload-pack: not our ref {pinned}" >&2; exit 128;; esac\n'
        f'exec {GitCli.locate().git} "$@"\n'
    )
    wrapper.chmod(0o755)
    gateway = GitCli(git=str(wrapper), work_root=tmp_path / "work")
    async with gateway.fetch(
        repository(docs_repo.file_url), pinned, PathSelection.of(["docs/"]),
        refs=("refs/tags/v1.4.0",),
    ) as dir_:  # fmt: skip
        assert git("rev-parse", "HEAD", cwd=dir_) == pinned
    with pytest.raises(CommitUnavailableError):  # the ref names another commit
        async with gateway.fetch(
            repository(docs_repo.file_url), pinned, PathSelection.of(),
            refs=("refs/heads/next",),
        ):  # fmt: skip
            pass
    with pytest.raises(CommitUnavailableError):  # nothing to fall back to
        async with gateway.fetch(repository(docs_repo.file_url), pinned, PathSelection.of()):
            pass


async def test_missing_git_refuses() -> None:
    with pytest.raises(GitNotInstalledError):
        async with MissingGit().fetch(repository("file:///x"), "1" * 40, PathSelection.of()):
            pass


def test_sparse_patterns_follow_the_selection() -> None:
    selection = PathSelection.of(["docs/", "guide/*.md", "{a,b}/x", "[z]", "{}"], ["docs/archive/"])

    assert sparse_patterns(selection) == [
        "/docs/", "/guide/*.md", "/a/x", "/b/x", "/\\[z]",
        "/README.md", "/README.mdx", "!/docs/archive/",
    ]  # fmt: skip


def test_no_include_means_every_file() -> None:
    assert sparse_patterns(PathSelection.of()) == ["/*", "/README.md", "/README.mdx"]


async def test_fetches_run_side_by_side(gateway: GitCli, docs_repo: DocsRepo) -> None:
    async def one() -> int:
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of(["docs/"])
        ) as dir_:
            return len(files(dir_))

    assert len(set(await asyncio.gather(*(one() for _ in range(3))))) == 1
