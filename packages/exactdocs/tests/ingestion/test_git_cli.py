import asyncio
import http.server
import os
import shutil
import signal
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven import git_cli
from exactdocs.ingestion.adapters.driven.git_cli import _DRAIN_SECONDS, GitCli
from exactdocs.ingestion.errors import (
    GitNotInstalledError,
    InvalidRepositoryUrlError,
    NotAGitRepositoryError,
    RepositoryAuthRequiredError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import ProposedId, RepositoryHost, RepositoryUrl
from fixture_repo import DocsRepo, git


def repository(url: str) -> RepositoryUrl:
    """A repository without going through ``parse``: the adapter must hold up on its own."""
    return RepositoryUrl(url=url, host_kind=RepositoryHost.GIT, library_id=ProposedId("/x/y"))


GIT = GitCli.locate()


@pytest.fixture
def unauthorized() -> Iterator[str]:
    """An HTTP server that answers 401 to everything, as a private repository does.

    Yields:
        The URL of a repository on it.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            """Stay quiet."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/acme/private.git"
    server.shutdown()
    server.server_close()


@pytest.fixture
def silent() -> Iterator[str]:
    """A server that accepts connections and never answers.

    Yields:
        The URL of a repository on it.
    """
    with socket.create_server(("127.0.0.1", 0)) as server:
        yield f"http://127.0.0.1:{server.getsockname()[1]}/acme/slow.git"


@pytest.fixture
def closed_port() -> str:
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
    return f"http://127.0.0.1:{port}/acme/gone.git"


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
async def test_lists_refs_and_the_default_branch(docs_repo: DocsRepo, transport: str) -> None:
    refs = await GIT.list_refs(repository(getattr(docs_repo, transport)))

    names = {ref.name for ref in refs.refs}
    assert refs.default_branch == "main"
    assert {"HEAD", "refs/heads/main", "refs/tags/v1.3.0", "refs/tags/v1.4.0"} <= names
    assert all(len(ref.sha) == 40 for ref in refs.refs)


async def test_patterns_narrow_the_listing(docs_repo: DocsRepo) -> None:
    refs = await GIT.list_refs(repository(docs_repo.http_url), "HEAD")

    assert [ref.name for ref in refs.refs] == ["HEAD"]
    assert refs.default_branch == "main"


async def test_an_empty_repository_has_no_default_branch(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    git("init", "-q", str(empty))

    refs = await GIT.list_refs(repository(empty.as_uri()))

    assert refs.default_branch is None
    assert refs.refs == ()


async def test_a_directory_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(NotAGitRepositoryError):
        await GIT.list_refs(repository(tmp_path.as_uri()))


async def test_a_missing_path_on_a_git_server(docs_repo: DocsRepo) -> None:
    with pytest.raises(NotAGitRepositoryError):
        await GIT.list_refs(repository(docs_repo.http_url.replace("docs-repo", "nope")))


async def test_a_server_asking_for_credentials(unauthorized: str) -> None:
    with pytest.raises(RepositoryAuthRequiredError):
        await GIT.list_refs(repository(unauthorized))


async def test_ssh_without_a_key_needs_authentication_or_is_unreachable() -> None:
    # No network in CI: an unresolvable host must be "unreachable", never a hang or a prompt.
    with pytest.raises(RepositoryUnreachableError):
        await GIT.list_refs(repository("ssh://git@nonexistent.invalid/acme/payments.git"))


async def test_a_refused_connection_is_unreachable(closed_port: str) -> None:
    with pytest.raises(RepositoryUnreachableError):
        await GIT.list_refs(repository(closed_port))


async def test_an_unknown_host_is_unreachable() -> None:
    with pytest.raises(RepositoryUnreachableError):
        await GIT.list_refs(repository("https://nonexistent.invalid/acme/payments"))


def processes_mentioning(text: str) -> list[int]:
    """Live processes (not zombies) whose command line contains ``text``."""
    found = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            cmdline = (stat.parent / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            state = stat.read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if text in cmdline and state != "Z" and stat.parent.name != str(os.getpid()):
            found.append(int(stat.parent.name))
    return found


async def gone(text: str) -> bool:
    """Wait briefly for every process mentioning ``text`` to be reaped."""
    for _ in range(50):
        if not processes_mentioning(text):
            return True
        await asyncio.sleep(0.1)
    return False


def fake_git(tmp_path: Path, script: str) -> str:
    """A stand-in `git` executable running a shell script."""
    path = tmp_path / "fake-git"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return str(path)


async def test_a_server_that_never_answers_times_out_and_nothing_is_left_running(
    silent: str,
) -> None:
    port = silent.rsplit(":", 1)[1].split("/", 1)[0]

    with pytest.raises(RepositoryUnreachableError, match=r"no answer within 0\.5 seconds"):
        await GitCli(git=GIT.git, timeout=0.5).list_refs(repository(silent))

    # git and the remote helper it started both mention the port on their command line
    assert await gone(f":{port}/"), processes_mentioning(f":{port}/")


async def test_a_helper_that_outlives_git_is_killed_too(tmp_path: Path) -> None:
    # git exits at once, but a background helper keeps its stdout open: the read only ends at
    # the timeout, and the helper must not survive it.
    marker = f"orphan-{tmp_path.name}"
    git = fake_git(tmp_path, f"sh -c 'sleep 77; :' {marker} &\nexit 0\n")

    with pytest.raises(RepositoryUnreachableError, match="no answer"):
        await GitCli(git=git, timeout=1).list_refs(repository("https://git.example.com/a/b"))

    assert await gone(marker), processes_mentioning(marker)


def open_files() -> int:
    """File descriptors this process has open."""
    return len(list(Path("/proc/self/fd").iterdir()))


async def test_a_timed_out_call_leaves_no_pipe_open(tmp_path: Path) -> None:
    # The same helper holding git's stdout: once the call has raised, git's pipes are closed
    # already, not left for the event loop (or the garbage collector) to find later.
    marker = f"holder-{tmp_path.name}"
    git = fake_git(tmp_path, f"sh -c 'sleep 77; :' {marker} &\nexit 0\n")
    before = open_files()

    with pytest.raises(RepositoryUnreachableError, match="no answer"):
        await GitCli(git=git, timeout=1).list_refs(repository("https://git.example.com/a/b"))

    assert open_files() == before
    assert await gone(marker), processes_mentioning(marker)


async def closed_again(count: int) -> bool:
    """Wait briefly for the open file descriptors to drop back to ``count``."""
    for _ in range(50):
        if open_files() == count:
            return True
        await asyncio.sleep(0.1)
    return False


async def test_a_helper_outside_the_group_does_not_hold_up_a_timed_out_call(
    tmp_path: Path,
) -> None:
    # git is still running at the timeout, and a helper in a session of its own keeps git's
    # stdout open: the group kill cannot reach it, so the call waits for it only briefly.
    marker = f"escaped-{tmp_path.name}"
    helper = f"setsid {sys.executable} -c 'import time; time.sleep(20)' {marker}"
    git = fake_git(tmp_path, f"{helper} &\nsleep 30\n")
    before = open_files()
    started = time.monotonic()
    try:
        with pytest.raises(RepositoryUnreachableError, match="no answer"):
            await GitCli(git=git, timeout=1).list_refs(repository("https://git.example.com/a/b"))

        assert time.monotonic() - started < 1 + _DRAIN_SECONDS + 1.5
    finally:
        for pid in processes_mentioning(marker):
            os.kill(pid, signal.SIGKILL)
    assert await gone(marker), processes_mentioning(marker)
    assert await closed_again(before)  # once the helper is gone, its pipes close too


def fake_keygen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GitCli:
    """A ``ssh-keygen`` on ``PATH`` that hangs, and a ``GitCli`` that will run it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    keygen = bin_dir / "ssh-keygen"
    keygen.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(77)\n")
    keygen.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return GitCli(git=GIT.git, known_hosts=tmp_path / "known_hosts")


async def test_a_hanging_ssh_keygen_is_killed_and_leaves_no_pipe_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = fake_keygen(tmp_path, monkeypatch)
    monkeypatch.setattr(git_cli, "_KEYGEN_SECONDS", 0.5)
    before = open_files()

    assert await cli.host_key_fingerprint(repository("ssh://git@git.example.com/a/b")) is None

    assert open_files() == before
    assert await gone(str(tmp_path / "bin")), processes_mentioning(str(tmp_path / "bin"))


async def test_a_cancelled_fingerprint_lookup_kills_ssh_keygen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = fake_keygen(tmp_path, monkeypatch)
    before = open_files()

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.5):
            await cli.host_key_fingerprint(repository("git@git.example.com:a/b.git"))

    assert open_files() == before
    assert await gone(str(tmp_path / "bin")), processes_mentioning(str(tmp_path / "bin"))


async def _run(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await process.communicate()
    assert process.returncode == 0, args
    return out.decode()


async def _host_key(tmp_path: Path, keygen: str, kind: str) -> tuple[str, str]:
    """A fresh host key of ``kind``: its public line and the fingerprint ssh-keygen gives it."""
    key = tmp_path / f"host_{kind}"
    await _run(keygen, "-q", "-t", kind, "-N", "", "-f", str(key))
    shown = await _run(keygen, "-l", "-E", "sha256", "-f", f"{key}.pub")
    fingerprint = next(p for p in shown.split() if p.startswith("SHA256:"))
    kind_name, body = Path(f"{key}.pub").read_text(encoding="ascii").split()[:2]  # ruff: ignore[blocking-path-method-in-async-function]
    return f"{kind_name} {body}", fingerprint


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs OpenSSH's ssh-keygen")
async def test_the_host_key_fingerprint_is_read_from_real_ssh_keygen_output(
    tmp_path: Path,
) -> None:
    keygen = shutil.which("ssh-keygen") or ""
    ed_line, ed_print = await _host_key(tmp_path, keygen, "ed25519")
    rsa_line, _ = await _host_key(tmp_path, keygen, "rsa")
    known = tmp_path / "known_hosts"
    # RSA first: the ED25519 key is the one shown, wherever it sits in the file.
    known.write_text(
        f"[127.0.0.1]:2231 {rsa_line}\n[127.0.0.1]:2231 {ed_line}\ngit.example.com {rsa_line}\n"
    )
    cli = GitCli(git=GIT.git, known_hosts=known)

    assert await cli.host_key_fingerprint(repository("ssh://git@127.0.0.1:2231/a/b.git")) == (
        ed_print
    )
    only_rsa = await cli.host_key_fingerprint(repository("git@git.example.com:a/b.git"))
    assert only_rsa is not None
    assert only_rsa.startswith("SHA256:")
    assert await cli.host_key_fingerprint(repository("git@unknown.example.com:a/b.git")) is None


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        # OpenSSH 9: `-F` prints "host TYPE fingerprint".
        ("[h]:22 RSA SHA256:rrr\n[h]:22 ED25519 SHA256:eee\n", "SHA256:eee"),
        # Older: the `-l` layout, "bits fingerprint comment (TYPE)".
        (
            "# Host h found: line 1\n3072 SHA256:rrr h (RSA)\n256 SHA256:eee h (ED25519)\n",
            "SHA256:eee",
        ),
        ("h ECDSA SHA256:ccc\n", "SHA256:ccc"),
        ("", None),
        ("h ED25519 MD5:aa:bb\n", None),
    ],
)
def test_the_fingerprint_is_the_sha256_field_with_ed25519_first(
    output: str, expected: str | None
) -> None:
    assert git_cli._pick_fingerprint(output) == expected  # ruff: ignore[private-member-access]


async def test_a_flood_of_refs_is_cut_off_at_once_and_reported(tmp_path: Path) -> None:
    marker = f"flood-{tmp_path.name}"
    git = fake_git(tmp_path, f'exec yes "{"a" * 40}\trefs/heads/{marker}"\n')
    started = time.monotonic()

    with pytest.raises(RepositoryUnreachableError, match="too many refs"):
        await GitCli(git=git, timeout=30, max_output=10_000).list_refs(
            repository("https://git.example.com/a/b")
        )

    assert time.monotonic() - started < 5  # not the 30 s timeout
    assert await gone(marker), processes_mentioning(marker)


async def test_only_a_few_git_processes_run_at_once(tmp_path: Path) -> None:
    running = tmp_path / "running"
    running.mkdir()
    log = tmp_path / "log"
    git = fake_git(
        tmp_path,
        f'touch "{running}/$$"\nls "{running}" | wc -l >> "{log}"\nsleep 0.3\nrm "{running}/$$"\n',
    )
    cli = GitCli(git=git, slots=asyncio.Semaphore(2))

    await asyncio.gather(
        *(cli.list_refs(repository("https://git.example.com/a/b")) for _ in range(6))
    )

    counts = [int(line) for line in log.read_text().split()]
    assert len(counts) == 6
    assert max(counts) == 2


async def test_a_url_that_looks_like_an_option_is_never_run(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"

    with pytest.raises(InvalidRepositoryUrlError):
        await GIT.list_refs(repository(f"--upload-pack=touch {marker}"))

    assert not marker.exists()


async def test_an_option_is_not_taken_from_a_pattern(docs_repo: DocsRepo) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        await GIT.list_refs(repository(docs_repo.file_url), "--upload-pack=true")


@pytest.mark.parametrize(
    "template",
    [
        "ext::sh -c 'touch {marker}'",
        "ext::sh -c touch% {marker}",
        "fd::7",
        "git://127.0.0.1/acme/payments",
    ],
)
async def test_transports_that_run_commands_are_refused_by_git_itself(
    tmp_path: Path, template: str
) -> None:
    marker = tmp_path / "pwned"

    # RepositoryUrl.parse already refuses these; this proves the adapter does not rely on it.
    with pytest.raises(RepositoryUnreachableError):
        await GIT.list_refs(repository(template.format(marker=marker)))

    assert not marker.exists()


async def test_a_local_repository_owned_by_someone_else_can_still_be_listed(
    docs_repo: DocsRepo, tmp_path: Path
) -> None:
    # git's own test switch makes every repository look foreign-owned (no second user needed)
    foreign = fake_git(tmp_path, f'GIT_TEST_ASSUME_DIFFERENT_OWNER=1 exec "{GIT.git}" "$@"\n')
    probe = await asyncio.create_subprocess_exec(
        GIT.git,
        "ls-remote",
        docs_repo.file_url,
        env={**os.environ, "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await probe.communicate()
    assert b"dubious ownership" in stderr  # the switch works: this is the problem case

    refs = await GitCli(git=foreign).list_refs(repository(docs_repo.file_url))

    assert refs.default_branch == "main"


async def test_a_local_permission_error_is_not_mistaken_for_a_login_prompt(
    tmp_path: Path,
) -> None:
    git = fake_git(tmp_path, 'echo "fatal: cannot open: Permission denied" >&2\nexit 128\n')

    with pytest.raises(RepositoryUnreachableError):
        await GitCli(git=git).list_refs(repository("file:///srv/locked/repo"))


async def test_a_hostile_default_branch_is_not_returned(tmp_path: Path) -> None:
    sha = "a" * 40
    git = fake_git(
        tmp_path,
        f"printf 'ref: refs/heads/evil\\033[31m\\tHEAD\\n{sha}\\tHEAD\\n'\n",
    )

    refs = await GitCli(git=git).list_refs(repository("https://git.example.com/a/b"))

    assert refs.default_branch is None


async def test_user_git_config_is_ignored(
    docs_repo: DocsRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A global `url.<base>.insteadOf` would silently redirect every URL.
    config = tmp_path / "gitconfig"
    config.write_text(f'[url "http://127.0.0.1:1/"]\n\tinsteadOf = {docs_repo.http_url}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("HOME", str(tmp_path))

    refs = await GIT.list_refs(repository(docs_repo.http_url))

    assert refs.default_branch == "main"


async def test_git_stderr_never_reaches_the_error_message(unauthorized: str) -> None:
    with pytest.raises(RepositoryAuthRequiredError) as error:
        await GIT.list_refs(repository(unauthorized))

    assert "127.0.0.1" not in str(error.value)


async def test_ssh_borrows_no_identity_and_sees_no_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A stand-in `ssh` records how git invoked it.
    fake = tmp_path / "bin" / "ssh"
    fake.parent.mkdir()
    fake.write_text(f'#!/bin/sh\n{{ echo "$@"; env; }} > "{tmp_path / "seen"}"\nexit 255\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:{os.environ['PATH']}")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/run/agent.sock")
    monkeypatch.setenv("RESEND_API_KEY", "top-secret-value")

    with pytest.raises(RepositoryUnreachableError):
        await GIT.list_refs(repository("git@git.example.com:acme/payments.git"))

    seen = (tmp_path / "seen").read_text()
    for option in ("BatchMode=yes", "PubkeyAuthentication=no", "PasswordAuthentication=no"):
        assert option in seen
    assert "SSH_AUTH_SOCK" not in seen
    assert "top-secret-value" not in seen


def test_a_missing_git_binary_is_reported_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")

    with pytest.raises(GitNotInstalledError, match="git is not installed"):
        GitCli.locate()
