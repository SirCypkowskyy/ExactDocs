"""Driven adapter for ``GitRemote``: the system ``git`` binary, run defensively.

The URL comes from a user, so git is treated as a process that must not surprise us:

- the URL goes after ``--`` (and one starting with ``-`` is refused), so it is never an option;
- ``GIT_ALLOW_PROTOCOL`` limits transports to file/http/https/ssh: ``ext::`` and ``fd::``
  (which run commands) and ``git://`` are refused by git itself;
- the environment is built from scratch: no user or system git config, no ssh keys or agent
  (ssh is told to use no authentication at all), no askpass, no terminal prompt, a throw-away
  working directory;
- the process has no stdin, its own session, a timeout and capped output; its whole process
  group is killed whenever the call ends, so no helper outlives it;
- at most ``MAX_PROCESSES`` git processes run at once;
- git's stderr is only classified, never passed on: it may contain the URL.
"""

import asyncio
import os
import re
import shutil
import signal
import sys
import tempfile
from asyncio.subprocess import DEVNULL, PIPE, Process
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from exactdocs.ingestion.errors import (
    GitNotInstalledError,
    InvalidRepositoryUrlError,
    NotAGitRepositoryError,
    RepositoryAuthRequiredError,
    RepositoryUnreachableError,
    UrlProblem,
)
from exactdocs.ingestion.models import RemoteRef, RemoteRefs, RepositoryUrl, branch_name

TIMEOUT_SECONDS = 15.0
MAX_PROCESSES = 4
ALLOWED_PROTOCOLS = "file:http:https:ssh"
MAX_STDOUT = 16 * 1024 * 1024
MAX_STDERR = 64 * 1024
_TOO_BIG = "the repository advertises too many refs"
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_NO_CONNECTION = "could not connect to it"
_SYMREF = "ref: "
_HEADS = "refs/heads/"
# Not secrets: where certificates live and which proxy to use, so corporate networks keep working.
_PASSTHROUGH = frozenset(
    {
        "path", "systemroot", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
        "ssl_cert_file", "ssl_cert_dir", "curl_ca_bundle", "git_ssl_cainfo", "git_ssl_capath",
    }
)  # fmt: skip
# ssh reads keys from the passwd-entry home (not $HOME) and from any agent, so every
# authentication method is switched off: a check must not borrow the server user's identity.
_SSH = " ".join(
    [
        "ssh -F", os.devnull, "-o BatchMode=yes -o ConnectTimeout=10",
        "-o PubkeyAuthentication=no -o GSSAPIAuthentication=no -o HostbasedAuthentication=no",
        "-o KbdInteractiveAuthentication=no -o PasswordAuthentication=no",
        "-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=" + os.devnull,
    ]
)  # fmt: skip
# Wording of `git` (LC_ALL=C) and of the transports behind it. Narrow on purpose: a local error
# ("Permission denied" on a directory, a shell "not found") must not read as a remote verdict.
_AUTH = re.compile(
    r"terminal prompts disabled|could not read (?:username|password)|authentication failed"
    r"|permission denied \(|error: 40[13]\b"
)
_NOT_A_REPO = re.compile(
    r"does not appear to be a git repository|repository (?:'[^']*' )?not found|error: 404\b"
)


@dataclass(frozen=True, slots=True)
class _Output:
    stdout: bytes
    stderr: str
    code: int


@dataclass(frozen=True, slots=True)
class GitCli:
    """Implements ``ports.driven.GitRemote`` with ``git ls-remote``."""

    git: str
    timeout: float = TIMEOUT_SECONDS
    max_output: int = MAX_STDOUT
    # Bounds the cost of an unauthenticated endpoint: one process, its helpers and up to
    # `max_output` bytes each.
    slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_PROCESSES), compare=False, repr=False
    )

    @classmethod
    def locate(cls, *, timeout: float = TIMEOUT_SECONDS) -> Self:
        """Find ``git`` on ``PATH``; raises ``GitNotInstalledError`` when it is missing."""
        git = shutil.which("git")
        if git is None:
            raise GitNotInstalledError
        return cls(git=git, timeout=timeout)

    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        """Run ``git ls-remote --symref`` and parse it."""
        if repository.url.startswith("-") or any(p.startswith("-") for p in patterns):
            raise InvalidRepositoryUrlError(UrlProblem.GIT_OPTION)
        # A local repository owned by someone else (a read-only mount) is refused by git unless
        # `safe.directory` allows it. `-c` is not passed to the upload-pack git starts for a local
        # path, so a global config file of ours says it, for `file:` URLs only.
        local = repository.url.lower().startswith("file:")
        output = await self._run(
            ["ls-remote", "--symref", "--", repository.url, *patterns],
            cap=self.max_output,
            trust_local=local,
        )
        if output.code:
            raise _failure(output.stderr)
        return _parse(output.stdout.decode(errors="replace"))

    async def _run(
        self,
        args: Sequence[str],
        *,
        cap: int,
        limit: float | None = None,
        trust_local: bool = False,
    ) -> _Output:
        """Run ``git <args>`` isolated (see the module docstring); the shared base for fetches.

        ``trust_local`` lets git read local repositories owned by another user.

        Raises ``RepositoryUnreachableError`` when it runs out of time or prints more than
        ``cap`` bytes (the process group is killed at once). stderr is truncated and lower-cased
        for classification only.
        """
        async with self.slots:
            with tempfile.TemporaryDirectory(prefix="exactdocs-git-") as home:
                seconds = self.timeout if limit is None else limit
                return await self._execute(
                    args, cap=cap, limit=seconds, home=home, trust_local=trust_local
                )

    async def _execute(
        self, args: Sequence[str], *, cap: int, limit: float, home: str, trust_local: bool
    ) -> _Output:
        environment = _environment(home)
        if trust_local:
            config = Path(home, "gitconfig")
            await asyncio.to_thread(config.write_text, "[safe]\n\tdirectory = *\n", "utf-8")
            environment["GIT_CONFIG_GLOBAL"] = str(config)
        process = await asyncio.create_subprocess_exec(
            self.git, "-c", "credential.helper=", *args,
            stdin=DEVNULL, stdout=PIPE, stderr=PIPE, cwd=home, env=environment,
            start_new_session=True,
        )  # fmt: skip
        try:
            async with asyncio.timeout(limit):
                out, err = await asyncio.gather(
                    _read(process, process.stdout, cap), _read(process, process.stderr, None)
                )
                code = await process.wait()
        except TimeoutError:
            reason = f"no answer within {limit:g} seconds"
            raise RepositoryUnreachableError(reason) from None
        finally:
            # Also when git itself is gone: a helper (git-remote-https, ssh) may still hold the
            # pipes. The group id stays valid while any member lives.
            _kill_group(process)
            await process.wait()
        if len(out) > cap:
            raise RepositoryUnreachableError(_TOO_BIG)
        return _Output(out, err.decode(errors="replace").lower(), code)


@dataclass(frozen=True, slots=True)
class MissingGit:
    """Stands in for ``GitCli`` when there is no ``git``: every use says what to install."""

    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        """Refuse with ``GitNotInstalledError``."""
        del repository, patterns
        raise GitNotInstalledError


def _environment(home: str) -> dict[str, str]:
    kept = {k: v for k, v in os.environ.items() if k.lower() in _PASSTHROUGH}
    return {
        **kept,
        "HOME": home,
        "USERPROFILE": home,
        "XDG_CONFIG_HOME": home,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS,
        "GIT_SSH_COMMAND": _SSH,
        "LC_ALL": "C",
    }


async def _read(process: Process, stream: asyncio.StreamReader | None, cap: int | None) -> bytes:
    """Read to the end keeping at most ``cap + 1`` bytes (``MAX_STDERR`` if no cap).

    Going over ``cap`` kills the process group, so a server that streams forever is cut off at
    once instead of when the timeout fires.
    """
    limit = MAX_STDERR if cap is None else cap
    kept = b""
    while stream and (chunk := await stream.read(65536)):
        kept += chunk[: limit + 1 - len(kept)]
        if cap is not None and len(kept) > cap:
            _kill_group(process)
    return kept


def _kill_group(process: Process) -> None:
    with suppress(ProcessLookupError):
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)


def _failure(
    stderr: str,
) -> RepositoryUnreachableError | NotAGitRepositoryError | RepositoryAuthRequiredError:
    if _AUTH.search(stderr):
        return RepositoryAuthRequiredError()
    if _NOT_A_REPO.search(stderr):
        return NotAGitRepositoryError()
    return RepositoryUnreachableError(_NO_CONNECTION)


def _parse(output: str) -> RemoteRefs:
    """Parse `--symref` output: `ref: refs/heads/main<TAB>HEAD`, then `<sha><TAB><ref>` lines."""
    default_branch = None
    refs: list[RemoteRef] = []
    for line in output.splitlines():
        if line.startswith(_SYMREF):
            target, _, source = line.removeprefix(_SYMREF).partition("\t")
            if source == "HEAD" and target.startswith(_HEADS):
                default_branch = branch_name(target.removeprefix(_HEADS))
        else:
            sha, _, name = line.partition("\t")
            if name and _SHA.fullmatch(sha):
                refs.append(RemoteRef(name=name, sha=sha))
    return RemoteRefs(default_branch=default_branch, refs=tuple(refs))
