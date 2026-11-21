import asyncio
import os
import random
import stat
import time
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.git_cli import (
    GitCli,
    MissingGit,
    sparse_patterns,
    sweep_stale_fetches,
)
from exactdocs.ingestion.constants import MAX_FETCHES
from exactdocs.ingestion.errors import (
    CommitUnavailableError,
    GitNotInstalledError,
    InvalidRepositoryUrlError,
    NotAGitRepositoryError,
    PreviewBusyError,
    RepositoryTooLargeError,
    RepositoryUnreachableError,
    TreeTooLargeError,
)
from exactdocs.ingestion.models import (
    FetchedFile,
    PathSelection,
    ProblemCode,
    ProposedId,
    RepositoryHost,
    RepositoryUrl,
)
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


async def test_the_size_error_names_the_byte_limit(docs_repo: DocsRepo, work: Path) -> None:
    gateway = GitCli(git=GitCli.locate().git, work_root=work, max_fetch_bytes=1000)

    with pytest.raises(RepositoryTooLargeError, match="larger than 1000 bytes"):
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of(["docs/"])
        ):
            pass


async def test_the_size_error_names_the_file_limit(docs_repo: DocsRepo, work: Path) -> None:
    gateway = GitCli(git=GitCli.locate().git, work_root=work, max_fetch_files=3)

    with pytest.raises(RepositoryTooLargeError, match="more than 3 files") as raised:
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of(["docs/"])
        ):
            pass
    assert "MiB" not in str(raised.value)


async def test_a_watchdog_stop_names_the_file_limit_too(
    tmp_path: Path, docs_repo: DocsRepo
) -> None:
    gateway = GitCli(
        git=stalling_git(tmp_path, 'for i in 1 2 3 4 5 6; do : > "$4/.git/f$i"; done; sleep 30'),
        work_root=tmp_path / "work", watch_interval=0.05, max_fetch_files=5,
    )  # fmt: skip

    with pytest.raises(RepositoryTooLargeError, match="more than 5 files"):
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of()
        ):
            pass


async def test_fetch_files_writes_only_the_named_files_of_a_directory_full_of_others(
    work: Path, tmp_path: Path
) -> None:
    """A big directory next to the wanted files costs nothing: the paths are literal."""
    origin = tmp_path / "origin"
    origin.mkdir()
    for n in range(30):
        (origin / "docs" / "media").mkdir(parents=True, exist_ok=True)
        (origin / "docs" / "media" / f"{n}.bin").write_bytes(os.urandom(100_000))
    (origin / "docs" / "a.png").write_bytes(b"small")
    git("init", "-q", "-b", "main", cwd=origin)
    git("add", ".", cwd=origin)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x", cwd=origin)
    pinned = git("rev-parse", "HEAD", cwd=origin)
    tight = GitCli.locate(work_root=work)

    async with tight.fetch_files(
        repository(origin.as_uri()), pinned, ["docs/a.png"], max_bytes=10
    ) as dir_:
        assert files(dir_) == {"docs/a.png"}

    with pytest.raises(RepositoryTooLargeError, match="larger than"):
        async with tight.fetch_files(
            repository(origin.as_uri()), pinned, ["docs/media/1.bin"], max_bytes=-4 * 2**20
        ):
            pass


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
        "/README.md", "/README.mdx", "!/docs/archive/", "/context7.json",
    ]  # fmt: skip


def test_no_include_means_every_file() -> None:
    assert sparse_patterns(PathSelection.of()) == [
        "/*", "/README.md", "/README.mdx", "/context7.json",
    ]  # fmt: skip


async def test_fetches_run_side_by_side(gateway: GitCli, docs_repo: DocsRepo) -> None:
    async def one() -> int:
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of(["docs/"])
        ) as dir_:
            return len(files(dir_))

    assert len(set(await asyncio.gather(*(one() for _ in range(3))))) == 1


# --- review round: verbatim content, watchdog, deadline, refs, sparse patterns ---


def commit_tree(tmp_path: Path, tree: dict[str, str | bytes]) -> tuple[Path, str]:
    """Commit the files, then ``.gitattributes`` alone: the blobs are stored exactly as given."""
    origin = tmp_path / "origin"
    git("init", "-q", "-b", "main", str(origin))
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=origin)
    for name, content in sorted(tree.items(), key=lambda item: item[0] == ".gitattributes"):
        target = origin / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
        if name != ".gitattributes":
            git("add", name, cwd=origin)
    git("add", ".gitattributes", cwd=origin, check=False)
    git("-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "x", cwd=origin)
    return origin, git("rev-parse", "HEAD", cwd=origin)


async def test_content_stays_verbatim_whatever_gitattributes_say(
    tmp_path: Path, gateway: GitCli
) -> None:
    tree: dict[str, str | bytes] = {
        ".gitattributes": (
            "*.crlf eol=crlf\n*.id ident\n*.u16 working-tree-encoding=UTF-16\n"
            "*.lfs filter=lfs diff=lfs merge=lfs\n*.txt text eol=crlf\n"
        ),
        "docs/a.crlf": b"hi\nthere\n",
        "docs/b.id": b"$Id$\n",
        "docs/c.u16": "café\n".encode(),
        "docs/d.lfs": b"not a pointer\n",
        "docs/e.txt": b"lf only\n",
    }
    origin, pinned = commit_tree(tmp_path, tree)

    async with gateway.fetch(repository(origin.as_uri()), pinned, PathSelection.of(["docs/"])) as d:
        for name, content in tree.items():
            if name.startswith("docs/"):
                assert (d / name).read_bytes() == content, name


@pytest.mark.parametrize(
    "ref",
    [
        "refs/heads/main:refs/heads/evil", "refs/heads/*", "refs/heads/a..b", "heads/main",
        "refs/heads/x.lock", "refs/heads/", "refs/heads/.h", "refs/a b",
        "refs/heads/a@{1}", "+refs/heads/main", "refs/heads//x",
    ],
)  # fmt: skip
async def test_refuses_refs_that_are_not_plain_names(gateway: GitCli, ref: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        async with gateway.fetch(
            repository("file:///x"), "1" * 40, PathSelection.of(), refs=(ref,)
        ):
            pass


@pytest.mark.parametrize("commit", ["a" * 64, "A" * 40, "a" * 39])
async def test_only_sha1_commits_are_accepted(gateway: GitCli, commit: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        async with gateway.fetch(repository("file:///x"), commit, PathSelection.of()):
            pass


def stalling_git(tmp_path: Path, script: str) -> str:
    """A ``git`` that runs ``script`` instead of fetching (``$4`` is the work folder)."""
    wrapper = tmp_path / "git"
    wrapper.write_text(
        f'#!/bin/sh\ncase " $* " in *" fetch "*) {script};; esac\nexec {GitCli.locate().git} "$@"\n'
    )
    wrapper.chmod(0o755)
    return str(wrapper)


@pytest.mark.parametrize(
    ("script", "limits"),
    [
        ('head -c 20000 /dev/zero > "$4/.git/big"; sleep 30', {"max_fetch_bytes": 10_000}),
        ('for i in 1 2 3 4 5 6; do : > "$4/.git/f$i"; done; sleep 30', {"max_fetch_files": 5}),
    ],
)
async def test_the_watchdog_stops_a_fetch_that_grows_too_big(
    tmp_path: Path, docs_repo: DocsRepo, script: str, limits: dict[str, int]
) -> None:
    gateway = GitCli(
        git=stalling_git(tmp_path, script), work_root=tmp_path / "work", watch_interval=0.05,
        max_fetch_bytes=limits.get("max_fetch_bytes", 10**9),
        max_fetch_files=limits.get("max_fetch_files", 10**6),
    )  # fmt: skip
    started = time.monotonic()

    with pytest.raises(RepositoryTooLargeError):
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of()
        ):
            pass

    assert time.monotonic() - started < 10
    assert leftovers(tmp_path / "work") == []


async def test_the_deadline_covers_all_git_calls_and_the_wait_for_a_slot(
    tmp_path: Path, docs_repo: DocsRepo
) -> None:
    wrapper = tmp_path / "git"  # every call takes 0.4 s: none is over the limit, all together are
    wrapper.write_text(f'#!/bin/sh\nsleep 0.4\nexec {GitCli.locate().git} "$@"\n')
    wrapper.chmod(0o755)
    gateway = GitCli(git=str(wrapper), work_root=tmp_path / "work", fetch_timeout=1.0)

    with pytest.raises(RepositoryUnreachableError):
        async with gateway.fetch(
            repository(docs_repo.file_url), sha(docs_repo, "main"), PathSelection.of()
        ):
            pass


async def test_a_spent_deadline_spawns_nothing(tmp_path: Path) -> None:
    marker = tmp_path / "spawned"
    wrapper = tmp_path / "git"
    wrapper.write_text(f"#!/bin/sh\ntouch {marker}\n")
    wrapper.chmod(0o755)
    gateway = GitCli(git=str(wrapper))

    with pytest.raises(RepositoryUnreachableError, match="too long"):
        await gateway._run(["--version"], cap=10, deadline=asyncio.get_running_loop().time() - 1)  # ruff: ignore[private-member-access]

    assert not marker.exists()


async def test_fetches_leave_slots_for_checks(tmp_path: Path, docs_repo: DocsRepo) -> None:
    gateway = GitCli(git=GitCli.locate().git, work_root=tmp_path / "work")
    for _ in range(2):  # every fetch slot is taken
        await gateway.fetch_slots.acquire()

    refs = await asyncio.wait_for(gateway.list_refs(repository(docs_repo.file_url)), 10)

    assert refs.default_branch == "main"


def test_stale_fetch_folders_are_swept_and_nothing_else(tmp_path: Path) -> None:
    work = tmp_path / "work"
    old, young, other = work / "fetch-old", work / "fetch-young", work / "keep"
    for folder in (old, young, other):
        (folder / "x").mkdir(parents=True)
    os.utime(old, (1, 1))
    os.utime(other, (1, 1))
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "fetch-link").symlink_to(outside)

    sweep_stale_fetches(work, older_than=60)

    assert [p.name for p in sorted(work.iterdir())] == ["fetch-link", "fetch-young", "keep"]
    assert outside.exists()


def test_a_symlinked_work_dir_is_left_alone(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "fetch-old").mkdir(parents=True)
    os.utime(real / "fetch-old", (1, 1))
    (tmp_path / "work").symlink_to(real)

    sweep_stale_fetches(tmp_path / "work", older_than=60)

    assert (real / "fetch-old").exists()


def test_brace_overflow_drops_an_exclusion_but_widens_an_include() -> None:
    many = "{a,b,c,d,e,f,g,h,i}{a,b,c,d,e,f,g,h,i}/x.md"

    assert sparse_patterns(PathSelection.of(["docs/"], [many])) == [
        "/docs/", "/README.md", "/README.mdx", "/context7.json",
    ]  # fmt: skip
    assert sparse_patterns(PathSelection.of([many])) == [
        "/*", "/README.md", "/README.mdx", "/context7.json",
    ]  # fmt: skip


def test_an_include_that_matches_nothing_fetches_only_the_readme_and_context7_json() -> None:
    assert sparse_patterns(PathSelection.of(["{}"])) == [
        "/README.md", "/README.mdx", "/context7.json",
    ]  # fmt: skip
    assert sparse_patterns(PathSelection.of(["{}", "docs/"])) == [
        "/docs/", "/README.md", "/README.mdx", "/context7.json",
    ]  # fmt: skip


def test_no_exclusion_can_drop_context7_json() -> None:
    assert sparse_patterns(PathSelection.of([], ["**/*.json", "context7.json"]))[-1] == (
        "/context7.json"
    )


def test_special_characters_are_neutralised() -> None:
    selection = PathSelection.of(["!bang/", "#hash.md", "sp ace/", "br[ack]et.md"])

    assert sparse_patterns(selection)[:4] == [
        "/!bang/", "/#hash.md", "/sp ace/", "/br\\[ack]et.md",
    ]  # fmt: skip


TREE = [
    "README.md", "readme.md", "AGENTS.md", "docs/index.md", "docs/a.mdx", "docs/img.png",
    "docs/guide/install.md", "docs/guide/deep/x.md", "docs/archive/old.md", "docs/API.MD",
    "guide/g.md", "a/x.md", "b/x.md", "ab/x.md", "src/lib/readme.md", "src/lib/code.py",
    "!bang/b.md", "#hash.md", "br[ack]et.md", "bracket.md", "sp ace/s.md", "notes.txt",
    "app/[locale]/x.md", "app/l/x.md",
]  # fmt: skip
PIECES = [
    "docs", "docs/", "docs/**", "docs/*.md", "docs/**/*.md", "**/x.md", "*/x.md", "{a,b}/x.md",
    "{docs,guide}/", "docs/archive/", "**/readme.md", "*.md", "README.md", "src/", "!bang/",
    "#hash.md", "br[ack]et.md", "sp ace/", "{}", "docs/{guide,archive}/**", "docs/guide/**/x.md",
    "?/x.md", "a?/x.md", "docs/*.mdx", "app/[locale]", "app/[locale]/",
]  # fmt: skip


@pytest.fixture(scope="module")
def tree_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    return commit_tree(tmp_path_factory.mktemp("tree"), dict.fromkeys(TREE, "# t\n"))


def selections() -> list[tuple[list[str], list[str]]]:
    rng = random.Random(29)  # ruff: ignore[suspicious-non-cryptographic-random-usage]
    cases: list[tuple[list[str], list[str]]] = [([], []), ([], ["docs/archive/"])]
    cases += [([p], []) for p in PIECES]
    cases += [
        (rng.sample(PIECES, rng.randint(1, 3)), rng.sample(PIECES, rng.randint(0, 2)))
        for _ in range(30)
    ]
    return cases


@pytest.mark.parametrize(("include", "exclude"), selections())
async def test_sparse_patterns_never_hide_a_file_the_selection_picks(
    tree_repo: tuple[Path, str], gateway: GitCli, include: list[str], exclude: list[str]
) -> None:
    """Differential: what git checks out, filtered by ``selects``, equals what ``selects`` picks."""
    origin, pinned = tree_repo
    selection = PathSelection.of(include, exclude)

    async with gateway.fetch(repository(origin.as_uri()), pinned, selection) as folder:
        fetched = {p for p in files(folder) if selection.selects(p)}

    assert fetched == {p for p in TREE if selection.selects(p)}


async def test_fetch_files_checks_out_exactly_the_named_paths(
    gateway: GitCli, docs_repo: DocsRepo
) -> None:
    pinned = sha(docs_repo, "v1.3.0")

    async with gateway.fetch_files(
        repository(docs_repo.file_url),
        pinned,
        ["docs/assets/logo.png", "docs/*", "docs/guide/[a]uth.md", "docs/nope.png"],
        max_bytes=1024,
    ) as dir_:
        assert files(dir_) == {"docs/assets/logo.png"}  # no README, no glob widening
    assert not dir_.exists()


async def test_fetch_files_with_nothing_to_fetch_checks_out_nothing(
    gateway: GitCli, docs_repo: DocsRepo
) -> None:
    async with gateway.fetch_files(
        repository(docs_repo.file_url), sha(docs_repo, "v1.3.0"), ["bad\nname"], max_bytes=1024
    ) as dir_:
        assert files(dir_) == set()


async def test_fetch_files_is_bounded_by_its_own_byte_limit(
    work: Path, docs_repo: DocsRepo
) -> None:
    tight = GitCli.locate(work_root=work)
    big = "docs/guide/configuration.md"

    with pytest.raises(RepositoryTooLargeError):
        async with tight.fetch_files(
            repository(docs_repo.file_url), sha(docs_repo, "v1.3.0"), [big], max_bytes=-4 * 2**20
        ):
            pass
    assert leftovers(work) == []


async def test_lists_the_tree_without_a_checkout_or_blobs(
    gateway: GitCli, docs_repo: DocsRepo, work: Path
) -> None:
    pinned = sha(docs_repo, "v1.4.0")

    listed = await gateway.list_files(repository(docs_repo.file_url), pinned)

    assert "docs/guide/install.md" in listed
    assert "docs/assets/logo.png" in listed  # everything in the tree; the use case filters
    assert set(listed) == set(
        git("ls-tree", "-r", "--name-only", pinned, cwd=docs_repo.path).split("\n")
    )
    assert leftovers(work) == []


async def test_a_listing_of_a_missing_commit_is_reported(
    gateway: GitCli, docs_repo: DocsRepo
) -> None:
    with pytest.raises(CommitUnavailableError):
        await gateway.list_files(repository(docs_repo.file_url), "0" * 40)


async def test_a_listing_shares_the_process_deadline(gateway: GitCli, docs_repo: DocsRepo) -> None:
    slow = GitCli(git=gateway.git, work_root=gateway.work_root, fetch_timeout=0.0)

    with pytest.raises(RepositoryUnreachableError):
        await slow.list_files(repository(docs_repo.file_url), sha(docs_repo, "v1.4.0"))


async def test_a_tree_over_the_output_cap_is_too_large_to_preview(
    docs_repo: DocsRepo, work: Path
) -> None:
    small = GitCli(git=GitCli.locate().git, work_root=work, max_output=64)

    with pytest.raises(TreeTooLargeError) as raised:
        await small.list_files(repository(docs_repo.file_url), sha(docs_repo, "v1.4.0"))

    assert raised.value.code == "repository_too_large"
    assert "refs" not in str(raised.value)
    assert not isinstance(raised.value, RepositoryTooLargeError)  # no MiB limit to report
    assert leftovers(work) == []


async def test_a_preview_waits_a_bounded_time_for_a_slot(docs_repo: DocsRepo, work: Path) -> None:
    busy = GitCli(git=GitCli.locate().git, work_root=work, preview_wait=0.05)
    for _ in range(2):
        await busy.preview_slots.acquire()

    with pytest.raises(PreviewBusyError) as raised:
        await busy.list_files(repository(docs_repo.file_url), sha(docs_repo, "v1.4.0"))
    assert raised.value.retry_after == 1  # whole seconds, at least one

    busy.preview_slots.release()  # a slot is free again: the preview runs
    assert await busy.list_files(repository(docs_repo.file_url), sha(docs_repo, "v1.4.0"))
    assert leftovers(work) == []


async def test_a_listing_leaves_symlinks_out(tmp_path: Path, gateway: GitCli) -> None:
    source = tmp_path / "src"
    source.mkdir()
    git("init", "-q", "-b", "main", cwd=source)
    (source / "a.md").write_text("a")
    (source / "link.md").symlink_to("a.md")
    git("add", ".", cwd=source)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x", cwd=source)

    listed = await gateway.list_files(
        repository(source.as_uri()), git("rev-parse", "HEAD", cwd=source)
    )

    assert listed == ["a.md"]


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
async def test_one_root_file_is_read_from_the_tree_without_a_checkout(
    gateway: GitCli, docs_repo: DocsRepo, work: Path, transport: str
) -> None:
    url = getattr(docs_repo, transport)

    found = await gateway.read_file(
        repository(url), sha(docs_repo, "next"), "context7.json", max_bytes=2**16
    )
    absent = await gateway.read_file(
        repository(url), sha(docs_repo, "v1.4.0"), "context7.json", max_bytes=2**16
    )

    expected = git("show", "next:context7.json", cwd=docs_repo.path)
    assert found == FetchedFile(data=(expected + "\n").encode())
    assert absent == FetchedFile()
    assert leftovers(work) == []


async def test_a_root_file_over_the_limit_is_not_downloaded(
    gateway: GitCli, docs_repo: DocsRepo
) -> None:
    found = await gateway.read_file(
        repository(docs_repo.file_url), sha(docs_repo, "next"), "context7.json", max_bytes=10
    )

    assert found == FetchedFile(problem="larger than 10 bytes")


async def test_a_root_file_that_is_a_link_or_a_folder_is_not_read(
    tmp_path: Path, gateway: GitCli
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    git("init", "-q", "-b", "main", cwd=source)
    (source / "target.json").write_text("{}")
    (source / "context7.json").symlink_to("target.json")
    (source / "docs").mkdir()
    (source / "docs" / "a.md").write_text("a")
    git("add", ".", cwd=source)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x", cwd=source)
    head = git("rev-parse", "HEAD", cwd=source)

    link = await gateway.read_file(repository(source.as_uri()), head, "context7.json", max_bytes=99)
    folder = await gateway.read_file(repository(source.as_uri()), head, "docs", max_bytes=99)

    assert link == folder == FetchedFile(problem="not a regular file")


async def test_reading_a_root_file_never_waits_for_an_import_slot(
    docs_repo: DocsRepo, work: Path
) -> None:
    busy = GitCli(git=GitCli.locate().git, work_root=work, preview_wait=0.05)
    for _ in range(MAX_FETCHES):
        await busy.fetch_slots.acquire()  # every import slot is taken by a long import

    async with asyncio.timeout(30):
        found = await busy.read_file(
            repository(docs_repo.file_url), sha(docs_repo, "next"), "context7.json", max_bytes=2**16
        )

    assert found.data


async def test_reading_a_root_file_waits_a_bounded_time_for_a_preview_slot(
    docs_repo: DocsRepo, work: Path
) -> None:
    busy = GitCli(git=GitCli.locate().git, work_root=work, preview_wait=0.05)
    for _ in range(2):
        await busy.preview_slots.acquire()

    with pytest.raises(PreviewBusyError):
        await busy.read_file(
            repository(docs_repo.file_url), sha(docs_repo, "next"), "context7.json", max_bytes=99
        )


@pytest.mark.parametrize("path", ["docs/a.md", "*.json", "", "-x", ":(glob)*"])
async def test_only_a_plain_root_name_can_be_read(
    gateway: GitCli, docs_repo: DocsRepo, path: str
) -> None:
    with pytest.raises(ValueError, match="root file name"):
        await gateway.read_file(
            repository(docs_repo.file_url), sha(docs_repo, "next"), path, max_bytes=99
        )


# --- instruction files (RET-08): read one by one, links followed one hop inside the repo ---


def _linked_repo(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "links"
    source.mkdir()
    git("init", "-q", "-b", "main", cwd=source)
    (source / "CLAUDE.md").write_text("Root notes.\n")
    (source / "AGENTS.md").symlink_to("CLAUDE.md")  # a common layout
    (source / "docs" / "guide").mkdir(parents=True)
    (source / "docs" / "guide" / "AGENTS.md").symlink_to("../../CLAUDE.md")
    (source / "docs" / "CLAUDE.md").symlink_to("../../outside/CLAUDE.md")
    (source / "docs" / "AGENTS.md").symlink_to("/etc/passwd")
    (source / "big").mkdir()
    (source / "big" / "AGENTS.md").write_text("x" * 5000)
    (source / "big" / "CLAUDE.md").write_text("Small one.\n")
    (source / "loop").mkdir()
    (source / "loop" / "AGENTS.md").symlink_to("CLAUDE.md")
    (source / "loop" / "CLAUDE.md").symlink_to("AGENTS.md")
    git("add", ".", cwd=source)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x", cwd=source)
    return source, git("rev-parse", "HEAD", cwd=source)


async def test_instruction_files_are_read_one_by_one_and_links_resolve_inside_the_repo(
    tmp_path: Path, gateway: GitCli, work: Path
) -> None:
    source, head = _linked_repo(tmp_path)
    wanted = [
        "AGENTS.md", "CLAUDE.md", "docs/AGENTS.md", "docs/CLAUDE.md", "docs/guide/AGENTS.md",
        "big/AGENTS.md", "big/CLAUDE.md", "loop/AGENTS.md", "nope/AGENTS.md",
    ]  # fmt: skip

    found = await gateway.read_files(repository(source.as_uri()), head, wanted, max_bytes=1000)

    root = FetchedFile(data=b"Root notes.\n")
    assert found["AGENTS.md"] == root  # the target's text, never the link's ("CLAUDE.md")
    assert found["CLAUDE.md"] == root
    assert found["docs/guide/AGENTS.md"] == root
    refused = FetchedFile(problem="a link that leads nowhere usable", code=ProblemCode.NOT_A_FILE)
    assert found["docs/CLAUDE.md"] == refused  # out of the repository
    assert found["docs/AGENTS.md"] == refused  # absolute
    assert found["loop/AGENTS.md"] == refused  # a link to a link: one hop only
    assert found["big/AGENTS.md"] == FetchedFile(
        problem="larger than 1000 bytes", code=ProblemCode.TOO_LARGE
    )
    assert found["big/CLAUDE.md"] == FetchedFile(data=b"Small one.\n")  # the others are kept
    assert "nope/AGENTS.md" not in found
    assert leftovers(work) == []
