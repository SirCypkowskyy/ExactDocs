"""``GitCli`` with credentials: real git against token-protected fixture servers, and a fake git
that records what a process is given (arguments, environment, files) while it runs."""

import errno
import json
import logging
import os
import shlex
import sys
import tempfile
import traceback
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.git_cli import GitCli, _failure, _ssh_command
from exactdocs.ingestion.errors import (
    HostKeyChangedError,
    RepositoryAuthRequiredError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import (
    AccessToken,
    DeployKey,
    PathSelection,
    ProposedId,
    RepositoryHost,
    RepositoryUrl,
)
from fixture_repo import TOKEN, DocsRepo

GIT = GitCli.locate()
KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nQmFkZ2VyS2V5Qm9keQ\n-----END OPENSSH PRIVATE KEY-----"


def repository(url: str) -> RepositoryUrl:
    return RepositoryUrl(url=url, host_kind=RepositoryHost.GIT, library_id=ProposedId("/x/y"))


async def test_a_private_repository_lists_its_refs_with_the_token(docs_repo: DocsRepo) -> None:
    refs = await GIT.list_refs(
        repository(docs_repo.private_url), credential=AccessToken(token=TOKEN)
    )

    assert refs.default_branch == "main"
    seen = docs_repo.private_seen or []
    assert "Basic" in (seen[-1][1] or "")
    assert TOKEN not in docs_repo.private_url


@pytest.mark.parametrize("credential", [None, AccessToken(token="wrong-" + TOKEN)])
async def test_without_the_right_token_a_private_repository_requires_authentication(
    docs_repo: DocsRepo, credential: AccessToken | None
) -> None:
    with pytest.raises(RepositoryAuthRequiredError):
        await GIT.list_refs(repository(docs_repo.private_url), credential=credential)


async def test_a_private_repository_is_fetched_with_the_token(docs_repo: DocsRepo) -> None:
    sha = (
        (
            await GIT.list_refs(
                repository(docs_repo.private_url),
                "refs/tags/v1.3.0",
                credential=AccessToken(token=TOKEN),
            )
        )
        .refs[0]
        .sha
    )

    async with GIT.fetch(
        repository(docs_repo.private_url), sha, PathSelection(include=("docs/**",)),
        credential=AccessToken(token=TOKEN),
    ) as folder:  # fmt: skip
        assert (folder / "docs" / "guide" / "auth.md").is_file()
        assert TOKEN not in (folder / ".git" / "config").read_text()


def _only_localhost(docs_repo: DocsRepo) -> list[tuple[str, str | None]]:
    return [seen for seen in docs_repo.private_seen or [] if seen[0].startswith("localhost")]


@pytest.mark.parametrize("which", ["redirect_url", "bounce_url"])
async def test_a_redirect_to_another_host_fails_and_never_gets_the_token(
    docs_repo: DocsRepo, which: str
) -> None:
    before = len(docs_repo.private_seen or [])
    with pytest.raises(RepositoryAuthRequiredError):
        await GIT.list_refs(
            repository(getattr(docs_repo, which)), credential=AccessToken(token=TOKEN)
        )

    other = (docs_repo.private_seen or [])[before:]
    assert any(host.startswith("localhost") for host, _ in other), "the redirect was not followed"
    assert [auth for host, auth in other if host.startswith("localhost")] == [None] * len(
        [1 for host, _ in other if host.startswith("localhost")]
    )


FAKE_GIT = """\
#!{python}
import json, os, stat, subprocess, sys
from pathlib import Path

env = dict(os.environ)
record = {"argv": sys.argv[1:], "env": env}
askpass = env.get("GIT_ASKPASS")
if askpass:
    record["askpass_path"] = askpass
    record["askpass_mode"] = stat.S_IMODE(os.stat(askpass).st_mode)
    secret_file = askpass.replace("askpass.sh", "askpass.secret")
    record["secret_mode"] = stat.S_IMODE(os.stat(secret_file).st_mode)
    answers = {}
    for prompt in json.loads(Path("{prompts}").read_text()):
        run = subprocess.run([askpass, prompt], capture_output=True, text=True, check=False)
        answers[prompt] = [run.returncode, run.stdout]
    record["answers"] = answers
command = env.get("GIT_SSH_COMMAND", "")
parts = command.split()
if "-i" in parts:
    key = parts[parts.index("-i") + 1]
    record["key_path"] = key
    record["key_mode"] = stat.S_IMODE(os.stat(key).st_mode)
    record["key_text"] = Path(key).read_text()
Path("{record}").write_text(json.dumps(record))
print("fatal: stop here", file=sys.stderr)
sys.exit(128)
"""


@pytest.fixture
def fake_git(tmp_path: Path) -> tuple[GitCli, Path]:
    script = tmp_path / "git"
    record = tmp_path / "record.json"
    # git runs with a scrubbed environment, so the paths are baked into the script
    script.write_text(
        FAKE_GIT.replace("{python}", sys.executable)
        .replace("{record}", str(record))  # ruff: ignore[missing-f-string-syntax]
        .replace("{prompts}", str(tmp_path / "prompts.json"))
    )
    script.chmod(0o755)
    (tmp_path / "prompts.json").write_text("[]")
    known = tmp_path / "known hosts"  # a space: the option must be quoted
    return GitCli(git=str(script), known_hosts=known), record


async def test_a_token_reaches_git_only_through_askpass_and_only_for_its_host(
    fake_git: tuple[GitCli, Path],
) -> None:
    git, record = fake_git
    own = "http://LocalHost:8080/acme/x.git"  # git prints the host as typed
    accepted = [
        "Username for 'http://localhost:8080': ",
        "Username for 'http://LOCALHOST:8080': ",
        "Password for 'http://bot@localhost:8080': ",
        "Password for 'http://BOT@LocalHost:8080': ",
        "Password for 'http://localhost:8080': ",
    ]
    refused = [
        "Username for 'http://127.0.0.1:8080': ",  # a redirect target
        "Username for 'https://localhost:8080': ",  # another scheme
        "Username for 'http://localhost:80801': ",
        "Username for 'http://localhost:8080.attacker.com': ",
        "Password for 'http://evil@localhost:8080': ",  # another user
        "Password for 'http://bot@localhost:8080/other': ",
        "xUsername for 'http://localhost:8080': ",
        "Username for 'http://localhost:8080': and more",
        "Username for 'http://x@evil.com' for 'http://localhost:8080': ",
        "Passphrase for key '/home/me/.ssh/id_ed25519': ",
        "",
    ]
    prompts = [*accepted, *refused]
    (record.parent / "prompts.json").write_text(json.dumps(prompts))

    with pytest.raises(RepositoryUnreachableError) as raised:
        await git.list_refs(repository(own), credential=AccessToken(token=TOKEN, username="bot"))

    seen = json.loads(record.read_text())
    assert not any(TOKEN in arg or "bot" in arg for arg in seen["argv"]), seen["argv"]
    assert TOKEN not in str(raised.value)
    # the token is in no environment (git's children inherit it) and no argument
    assert not any(TOKEN in value for value in seen["env"].values())
    assert not any(key.startswith("EXACTDOCS_GIT") for key in seen["env"])
    assert seen["secret_mode"] == 0o600
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "credential.helper=" in seen["argv"]
    assert seen["askpass_mode"] == 0o700
    answers = seen["answers"]
    for prompt in accepted:
        assert answers[prompt][0] == 0, prompt
        assert answers[prompt][1] == ("bot\n" if prompt.startswith("Username") else TOKEN + "\n")
    for prompt in refused:
        assert answers[prompt] == [1, ""], prompt
    assert not Path(seen["askpass_path"]).exists()  # ruff: ignore[blocking-path-method-in-async-function]


async def test_a_deploy_key_is_a_private_temporary_file_named_in_git_ssh_command(
    fake_git: tuple[GitCli, Path],
) -> None:
    git, record = fake_git

    with pytest.raises(Exception, match="unreachable"):
        await git.list_refs(
            repository("ssh://git@git.example.com/acme/x.git"),
            credential=DeployKey(private_key=KEY),
        )

    seen = json.loads(record.read_text())
    assert (seen["key_mode"], seen["key_text"]) == (0o600, KEY + "\n")
    assert not Path(seen["key_path"]).exists()  # ruff: ignore[blocking-path-method-in-async-function]
    assert "QmFkZ2VyS2V5" not in json.dumps({"argv": seen["argv"], "env": seen["env"]})
    options = shlex.split(seen["env"]["GIT_SSH_COMMAND"])
    assert seen["env"]["GIT_SSH_COMMAND"].count("known hosts") == 1
    assert {
        "StrictHostKeyChecking=accept-new",
        "GlobalKnownHostsFile=/dev/null",
        "IdentitiesOnly=yes",
        "IdentityAgent=none",
        "BatchMode=yes",
        "UserKnownHostsFile=" + str(git.known_hosts),
    } <= set(options)
    assert "PubkeyAuthentication=no" not in options


def test_ssh_options_without_a_key_offer_no_identity(tmp_path: Path) -> None:
    options = shlex.split(_ssh_command(tmp_path / "known_hosts"))

    assert "PubkeyAuthentication=no" in options
    assert "-i" not in options
    assert "UserKnownHostsFile=" + str(tmp_path / "known_hosts") in options
    assert "StrictHostKeyChecking=accept-new" in options
    assert "GlobalKnownHostsFile=/dev/null" in options
    assert "UserKnownHostsFile=" + os.devnull in shlex.split(_ssh_command(None))


@pytest.mark.parametrize(
    "stderr",
    [
        (
            "@@@@@@@@\n@    warning: remote host identification has changed!     @@@\n"
            "offending ed25519 key in /data/known_hosts:3\nhost key verification failed.\n"
        ),
        "host key verification failed.\nfatal: could not read from remote repository.",
    ],
)
def test_a_changed_ssh_host_key_is_a_hard_error(stderr: str) -> None:
    error = _failure(stderr, ssh=True)

    assert isinstance(error, HostKeyChangedError)
    assert error.code == "host_key_changed"


def test_an_http_server_cannot_fake_a_host_key_change() -> None:
    stderr = "remote: host key verification failed.\nfatal: authentication failed"

    assert isinstance(_failure(stderr), RepositoryAuthRequiredError)
    assert isinstance(_failure(stderr, ssh=True), HostKeyChangedError)


async def test_a_token_goes_to_a_host_typed_in_capitals(docs_repo: DocsRepo) -> None:
    url = docs_repo.private_url.replace("127.0.0.1", "LOCALHOST")

    refs = await GIT.list_refs(repository(url), credential=AccessToken(token=TOKEN))

    assert refs.default_branch == "main"


def test_other_ssh_failures_keep_their_meaning() -> None:
    assert isinstance(
        _failure("git@x: permission denied (publickey)."), RepositoryAuthRequiredError
    )


async def test_the_key_directory_is_removed_even_when_git_cannot_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    git = GitCli(git=str(tmp_path / "missing-git"))

    with pytest.raises(FileNotFoundError):
        await git.list_refs(
            repository("git@github.com:acme/x.git"), credential=DeployKey(private_key=KEY)
        )

    assert list(scratch.iterdir()) == []


async def test_git_runs_in_a_private_directory_under_the_work_root(
    tmp_path: Path, fake_git: tuple[GitCli, Path]
) -> None:
    git, record = fake_git
    work = tmp_path / "work"
    git = GitCli(git=git.git, work_root=work)

    with pytest.raises(RepositoryUnreachableError):
        await git.list_refs(repository("http://127.0.0.1:1/a/b.git"))

    assert Path(json.loads(record.read_text())["env"]["HOME"]).parent == work


class _LeakyGit:
    """A git that fails with the secret in its message, as a misbehaving helper might."""

    def __init__(self, tmp_path: Path, secret: str) -> None:
        self.path = tmp_path / "leaky-git"
        self.path.write_text(
            f"#!/bin/sh\necho 'fatal: unable to access: password {secret} rejected' >&2\nexit 128\n"
        )
        self.path.chmod(0o755)


async def test_a_git_failure_that_carries_the_secret_reaches_no_error_or_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    git = GitCli(git=str(_LeakyGit(tmp_path, TOKEN).path))

    with pytest.raises(RepositoryUnreachableError) as raised:
        await git.list_refs(
            repository("https://git.example.com/a/b.git"), credential=AccessToken(token=TOKEN)
        )
    with pytest.raises(RepositoryUnreachableError) as fetch_raised:
        async with git.fetch(
            repository("https://git.example.com/a/b.git"),
            "a" * 40,
            PathSelection(),
            credential=AccessToken(token=TOKEN),
        ):
            pass

    for error in (raised.value, fetch_raised.value):
        assert TOKEN not in str(error)
        assert TOKEN not in repr(error)
        assert TOKEN not in "".join(traceback.format_exception(error))
    assert TOKEN not in caplog.text


async def test_a_failure_while_preparing_the_credential_does_not_repeat_it(
    monkeypatch: pytest.MonkeyPatch, fake_git: tuple[GitCli, Path]
) -> None:
    git, _ = fake_git

    def broken(path: Path, text: str, mode: int) -> None:
        del path, text, mode
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("exactdocs.ingestion.adapters.driven.git_cli._write_private", broken)

    with pytest.raises(OSError, match="No space") as raised:
        await git.list_refs(
            repository("ssh://git@git.example.com/a/b.git"), credential=DeployKey(private_key=KEY)
        )

    assert "QmFkZ2VyS2V5" not in "".join(traceback.format_exception(raised.value))
