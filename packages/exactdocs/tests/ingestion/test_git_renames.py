"""``GitCli.renames`` against the fixture repository (real git, both transports)."""

from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven import git_cli
from exactdocs.ingestion.adapters.driven.git_cli import GitCli, MissingGit, _parse_renames
from exactdocs.ingestion.errors import (
    CommitUnavailableError,
    GitNotInstalledError,
    InvalidRepositoryUrlError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import (
    MAX_RENAMES,
    GitRename,
    ProposedId,
    RepositoryHost,
    RepositoryUrl,
)
from fixture_repo import DocsRepo, git

SETUP = "docs/guide/setup.md"
INSTALL = "docs/guide/install.md"


def repository(url: str) -> RepositoryUrl:
    return RepositoryUrl(url=url, host_kind=RepositoryHost.GIT, library_id=ProposedId("/x/y"))


def sha(docs_repo: DocsRepo, ref: str) -> str:
    return git("rev-parse", f"{ref}^{{commit}}", cwd=docs_repo.path)


def leftovers(work: Path) -> list[Path]:
    return list(work.iterdir())


@pytest.fixture
def work(tmp_path: Path) -> Path:
    return tmp_path / "work"


@pytest.fixture
def gateway(work: Path) -> GitCli:
    return GitCli.locate(work_root=work)


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
async def test_a_file_renamed_and_edited_between_two_tags_is_found(
    gateway: GitCli, docs_repo: DocsRepo, transport: str, work: Path
) -> None:
    found = await gateway.renames(
        repository(getattr(docs_repo, transport)),
        sha(docs_repo, "v1.3.0"),
        sha(docs_repo, "v1.4.0"),
    )

    assert [(r.old_path, r.new_path) for r in found] == [(SETUP, INSTALL)]
    assert 50 <= found[0].similarity < 100  # edited on the way, so git had to score it
    assert leftovers(work) == []  # nothing left behind


async def test_nothing_but_trees_and_the_few_candidate_blobs_are_fetched(
    gateway: GitCli, docs_repo: DocsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders: list[Path] = []
    objects: list[str] = []
    make, parse = git_cli._make_folder, git_cli._parse_renames  # ruff: ignore[private-member-access]

    def made(root: Path | None) -> str:
        folders.append(Path(make(root)))
        return str(folders[-1])

    def peek(output: bytes) -> list[GitRename]:  # runs before the folder is removed
        listing = git("cat-file", "--batch-all-objects", "--batch-check", cwd=folders[0])
        objects.extend(listing.split("\n"))
        return parse(output)

    monkeypatch.setattr(git_cli, "_make_folder", made)
    monkeypatch.setattr(git_cli, "_parse_renames", peek)

    await gateway.renames(
        repository(docs_repo.file_url), sha(docs_repo, "v1.3.0"), sha(docs_repo, "v1.4.0")
    )

    blobs = [line for line in objects if " blob " in line]
    # setup.md (deleted) and install.md, resilience.md, errors.md (added), never the other ~40 files
    assert 0 < len(blobs) <= 4
    assert len([line for line in objects if " commit " in line]) == 2  # no history


async def test_the_rename_limit_keeps_the_exact_moves_and_drops_the_scored_ones(
    docs_repo: DocsRepo, work: Path
) -> None:
    tight = GitCli.locate(work_root=work)
    tight = GitCli(git=tight.git, work_root=work, rename_limit=1)

    found = await tight.renames(
        repository(docs_repo.file_url), sha(docs_repo, "v1.3.0"), sha(docs_repo, "v1.4.0")
    )

    assert found == []  # setup.md -> install.md was edited: not exact, and over the limit


async def test_no_change_means_no_renames(gateway: GitCli, docs_repo: DocsRepo) -> None:
    same = sha(docs_repo, "v1.4.0")

    assert await gateway.renames(repository(docs_repo.file_url), same, same) == []


async def test_an_unknown_commit_is_commit_unavailable(
    gateway: GitCli, docs_repo: DocsRepo, work: Path
) -> None:
    with pytest.raises(CommitUnavailableError):
        await gateway.renames(repository(docs_repo.file_url), "1" * 40, sha(docs_repo, "v1.4.0"))
    assert leftovers(work) == []


async def test_it_gives_up_at_its_own_deadline(docs_repo: DocsRepo, work: Path) -> None:
    slow = GitCli(git=GitCli.locate().git, work_root=work, rename_timeout=0)

    with pytest.raises(RepositoryUnreachableError):
        await slow.renames(
            repository(docs_repo.file_url), sha(docs_repo, "v1.3.0"), sha(docs_repo, "v1.4.0")
        )
    assert leftovers(work) == []


@pytest.mark.parametrize("bad", ["main", "--upload-pack=x", "A" * 40, ""])
async def test_only_full_lower_case_commit_ids_are_accepted(
    gateway: GitCli, docs_repo: DocsRepo, bad: str
) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        await gateway.renames(repository(docs_repo.file_url), bad, sha(docs_repo, "v1.4.0"))


async def test_without_git_it_says_so() -> None:
    with pytest.raises(GitNotInstalledError):
        await MissingGit().renames(repository("https://example.com/a/b"), "a" * 40, "b" * 40)


def moved_repo(tmp_path: Path, files: dict[str, str]) -> tuple[str, str, str]:
    """A repository whose second commit renames every file to ``files[old]``; (url, old, new)."""
    repo = tmp_path / "moved"
    repo.mkdir()
    git("init", "-q", "-b", "main", "--template=", str(repo))
    git("config", "uploadpack.allowFilter", "true", cwd=repo)
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=repo)
    for number, old in enumerate(files):
        (repo / old).parent.mkdir(parents=True, exist_ok=True)
        (repo / old).write_text(f"# Page {number}\n\nUnique body {number} " * 5, "utf-8")
    commit = ("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m")
    git("add", "-A", cwd=repo)
    git(*commit, "one", cwd=repo)
    old = git("rev-parse", "HEAD", cwd=repo)
    for source, target in files.items():
        (repo / target).parent.mkdir(parents=True, exist_ok=True)
        (repo / source).rename(repo / target)
    git("add", "-A", cwd=repo)
    git(*commit, "two", cwd=repo)
    return f"file://{repo}", old, git("rev-parse", "HEAD", cwd=repo)


async def test_article_suffixes_match_whatever_the_letter_case(
    gateway: GitCli, tmp_path: Path
) -> None:
    url, old, new = moved_repo(
        tmp_path,
        {"Guide.MD": "docs/Guide.MD", "a.Mdx": "docs/a.Mdx", "image.png": "docs/image.png"},
    )

    found = await gateway.renames(repository(url), old, new)

    assert sorted((r.old_path, r.new_path) for r in found) == [
        ("Guide.MD", "docs/Guide.MD"),
        ("a.Mdx", "docs/a.Mdx"),
    ]  # as the importer selects them; the png is none of its business


async def test_thousands_of_exact_renames_with_long_paths_come_back_whole(
    gateway: GitCli, tmp_path: Path
) -> None:
    deep = "d" * 120
    files = {
        f"{deep}/old-{i:05d}-{'x' * 80}.md": f"{deep}/new/{i:05d}-{'y' * 80}.md"
        for i in range(3000)
    }
    url, old, new = moved_repo(tmp_path, files)

    found = await gateway.renames(repository(url), old, new)

    assert len(found) == len(files)  # about 1.5 MB of git output, over the old 1 MiB cap
    assert {r.old_path: r.new_path for r in found} == files
    assert {r.similarity for r in found} == {100}


def test_more_renames_than_the_cap_are_cut_not_refused() -> None:
    lines = b"".join(b"R100\0o%d.md\0n%d.md\0" % (i, i) for i in range(MAX_RENAMES + 5))

    assert len(_parse_renames(lines)) == MAX_RENAMES


def test_the_name_status_output_is_parsed_whatever_the_file_names_hold() -> None:
    output = b"R100\0a b.md\0dir/n\xc3\xa4me.md\0R084\0x.mdx\0y.mdx\0R050\0q\nr.md\0s.md\0"

    assert _parse_renames(output) == [
        GitRename(old_path="a b.md", new_path="dir/näme.md", similarity=100),
        GitRename(old_path="x.mdx", new_path="y.mdx", similarity=84),
        GitRename(old_path="q\nr.md", new_path="s.md", similarity=50),
    ]
    assert _parse_renames(b"") == []
    assert _parse_renames(b"M\0a.md\0") == []  # not a rename record: skipped, never raised
