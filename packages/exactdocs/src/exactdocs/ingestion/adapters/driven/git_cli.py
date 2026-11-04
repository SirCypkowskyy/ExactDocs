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

``fetch`` (the ``GitGateway`` port) builds on the same ``_run``. Into a folder of its own it
fetches one commit by SHA, ``--depth 1`` and ``--filter=blob:none`` (a server without filters just
sends more), and checks out only the sparse patterns made from the selection plus the root
README, so only those blobs are downloaded. The repository config is written by us and sets no
hooks, no submodules, no symlinks (they become small text files, so a link can never point out
of the folder), no fsmonitor, no auto-gc. A server that refuses a bare SHA is asked for the
caller's ref names instead, and the result must still be the pinned commit.

Content stays verbatim: ``.git/info/attributes`` (which beats the repository's own
``.gitattributes``) switches off text/eol conversion, filters, ``$Id$`` expansion and
``working-tree-encoding``, and no system attributes are read. File modes and symlink targets are
lost on purpose. While git runs, a watchdog measures the folder about once a second and kills the
process group when it holds too many bytes or files, so a hostile server cannot fill the disk.
The fetch deadline starts once the fetch has a slot (at most ``MAX_FETCHES`` at a time, apart
from the slots checks use). One data directory has exactly one job runner.
"""

import asyncio
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from asyncio.subprocess import DEVNULL, PIPE, Process
from collections.abc import AsyncGenerator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from exactdocs.ingestion.errors import (
    CommitUnavailableError,
    GitNotInstalledError,
    InvalidRepositoryUrlError,
    NotAGitRepositoryError,
    RepositoryAuthRequiredError,
    RepositoryTooLargeError,
    RepositoryUnreachableError,
    UrlProblem,
)
from exactdocs.ingestion.models import (
    PathSelection,
    RemoteRef,
    RemoteRefs,
    RepositoryUrl,
    branch_name,
)

TIMEOUT_SECONDS = 15.0
MAX_PROCESSES = 4
ALLOWED_PROTOCOLS = "file:http:https:ssh"
MAX_STDOUT = 16 * 1024 * 1024
MAX_STDERR = 64 * 1024
FETCH_TIMEOUT_SECONDS = 300.0
MAX_FETCHES = 2
MAX_FETCH_FILES = 100_000
WATCH_SECONDS = 1.0
STALE_MARGIN_SECONDS = 60.0
MAX_FETCH_BYTES = 512 * 2**20
_MAX_STEP_OUTPUT = 1024 * 1024
_MAX_BRACE_EXPANSIONS = 64
_PREFIX = "fetch-"
_ROOT_README = ("/README.md", "/README.mdx")
# What servers say when they will not serve a bare SHA (or the ref we named instead).
_GONE = re.compile(r"not our ref|unadvertised object|couldn't find remote ref|no such remote ref")
_CONFIG = """\
[core]
\trepositoryformatversion = 1
\tsymlinks = false
\thooksPath = {null}
\tfsmonitor = false
\tprotectNTFS = true
\tprotectHFS = true
\tsparseCheckout = true
\tsparseCheckoutCone = false
[extensions]
\tpartialClone = origin
[gc]
\tauto = 0
[maintenance]
\tauto = false
[protocol]
\tversion = 2
[submodule]
\trecurse = false
[remote "origin"]
\turl = {url}
\tpromisor = true
\tpartialclonefilter = blob:none
"""
_ATTRIBUTES = "* -text -filter -ident !eol !working-tree-encoding\n"
_TOO_BIG = "the repository advertises too many refs"
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")  # fetches are SHA-1 only: no objectformat extension
_REF = re.compile(r"refs/[A-Za-z0-9._/+@-]+")
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
    work_root: Path | None = None  # where fetches get their folders; the temp dir when None
    fetch_timeout: float = FETCH_TIMEOUT_SECONDS  # for a whole fetch, not per git call
    max_fetch_bytes: int = MAX_FETCH_BYTES  # of the fetched repository plus its work tree
    max_fetch_files: int = MAX_FETCH_FILES
    watch_interval: float = WATCH_SECONDS
    # Fetches wait here, so long imports cannot take every slot of `slots` from the checks.
    fetch_slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_FETCHES), compare=False, repr=False
    )
    # Bounds the cost of an unauthenticated endpoint: one process, its helpers and up to
    # `max_output` bytes each.
    slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_PROCESSES), compare=False, repr=False
    )

    @classmethod
    def locate(cls, *, timeout: float = TIMEOUT_SECONDS, work_root: Path | None = None) -> Self:
        """Find ``git`` on ``PATH``; raises ``GitNotInstalledError`` when it is missing."""
        git = shutil.which("git")
        if git is None:
            raise GitNotInstalledError
        return cls(git=git, timeout=timeout, work_root=work_root)

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

    @asynccontextmanager
    async def fetch(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        selection: PathSelection,
        *,
        refs: Sequence[str] = (),
    ) -> AsyncGenerator[Path]:
        """Implement ``GitGateway.fetch`` (see the module docstring).

        Yields:
            The folder with the checked-out files; it is removed afterwards.

        """
        if (
            repository.url.startswith("-")
            or not repository.url.isprintable()
            or not _COMMIT.fullmatch(commit_sha)
            or not all(_valid_ref(ref) for ref in refs)
        ):
            raise InvalidRepositoryUrlError(UrlProblem.GIT_OPTION)
        async with self.fetch_slots:
            if self.work_root is not None:
                await asyncio.to_thread(self.work_root.mkdir, parents=True, exist_ok=True)
            folder = Path(await asyncio.to_thread(_make_folder, self.work_root))
            try:
                deadline = asyncio.get_running_loop().time() + self.fetch_timeout
                await self._populate(folder, repository.url, commit_sha, selection, refs, deadline)
                yield folder
            finally:
                shutil.rmtree(folder, ignore_errors=True)

    async def _populate(
        self,
        folder: Path,
        url: str,
        sha: str,
        selection: PathSelection,
        refs: Sequence[str],
        deadline: float,
    ) -> None:
        local = url.lower().startswith("file:")

        async def git(*args: str) -> _Output:
            return await self._run(
                ["-C", str(folder), *args],
                cap=_MAX_STEP_OUTPUT,
                deadline=deadline,
                trust_local=local,
                watch=folder,
            )

        init = await git("init", "-q", "--template=")
        if init.code:
            raise _failure(init.stderr)
        sparse = "\n".join(sparse_patterns(selection)) + "\n"
        await asyncio.to_thread(_write_config, folder, url, sparse)
        for target in (sha, *refs):
            out = await git(
                "fetch", "-q", "--depth=1", "--filter=blob:none", "--no-tags",
                "--no-recurse-submodules", "origin", target,
            )  # fmt: skip
            if out.code and not _GONE.search(out.stderr):
                raise _failure(out.stderr)
            if not out.code:
                head = await git("rev-parse", "--verify", "-q", "FETCH_HEAD^{commit}")
                if head.stdout.decode().strip() == sha:
                    break
        else:
            raise CommitUnavailableError
        out = await git("checkout", "-q", "--detach", "--no-recurse-submodules", sha)
        if out.code:
            raise _failure(out.stderr)
        size, count = await asyncio.to_thread(_measure, folder)
        if size > self.max_fetch_bytes or count > self.max_fetch_files:
            raise RepositoryTooLargeError(self.max_fetch_bytes)

    async def _run(
        self,
        args: Sequence[str],
        *,
        cap: int,
        limit: float | None = None,
        deadline: float | None = None,
        trust_local: bool = False,
        watch: Path | None = None,
    ) -> _Output:
        """Run ``git <args>`` isolated (see the module docstring); the shared base for fetches.

        ``trust_local`` lets git read local repositories owned by another user. ``deadline`` (a
        loop time) replaces ``limit`` and is read once the slot is held. ``watch`` is a folder
        whose size is limited while git runs (``RepositoryTooLargeError``).

        Raises ``RepositoryUnreachableError`` when it runs out of time or prints more than
        ``cap`` bytes (the process group is killed at once). stderr is truncated and lower-cased
        for classification only.
        """
        async with self.slots:
            seconds = self.timeout if limit is None else limit
            if deadline is not None:
                seconds = deadline - asyncio.get_running_loop().time()
                if seconds <= 0:
                    reason = "it took too long"
                    raise RepositoryUnreachableError(reason)
            with tempfile.TemporaryDirectory(prefix="exactdocs-git-") as home:
                return await self._execute(
                    args, cap=cap, limit=seconds, home=home, trust_local=trust_local, watch=watch
                )

    async def _execute(
        self,
        args: Sequence[str],
        *,
        cap: int,
        limit: float,
        home: str,
        trust_local: bool,
        watch: Path | None = None,
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
        guard = asyncio.create_task(self._guard(process, watch)) if watch else None
        tripped = False
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
            tripped = guard is not None and guard.done() and not guard.cancelled()
            if guard:
                guard.cancel()
            _kill_group(process)
            await process.wait()
        if tripped:
            raise RepositoryTooLargeError(self.max_fetch_bytes)
        if len(out) > cap:
            raise RepositoryUnreachableError(_TOO_BIG)
        return _Output(out, err.decode(errors="replace").lower(), code)

    async def _guard(self, process: Process, folder: Path) -> None:
        """Return (after killing git) as soon as ``folder`` holds too many bytes or files."""
        while True:
            await asyncio.sleep(self.watch_interval)
            size, count = await asyncio.to_thread(_measure, folder)
            if size > self.max_fetch_bytes or count > self.max_fetch_files:
                _kill_group(process)
                return


@dataclass(frozen=True, slots=True)
class MissingGit:
    """Stands in for ``GitCli`` when there is no ``git``: every use says what to install."""

    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        """Refuse with ``GitNotInstalledError``."""
        del repository, patterns
        raise GitNotInstalledError

    def fetch(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        selection: PathSelection,
        *,
        refs: Sequence[str] = (),
    ) -> AbstractAsyncContextManager[Path]:
        """Refuse with ``GitNotInstalledError``."""
        del repository, commit_sha, selection, refs
        return _no_git()


@asynccontextmanager
async def _no_git() -> AsyncGenerator[Path]:
    raise GitNotInstalledError
    yield  # pragma: no cover


def _write_config(folder: Path, url: str, sparse: str) -> None:
    git_dir = folder / ".git"
    quoted = json.dumps(url, ensure_ascii=False)  # git unescapes \\ and \" in quoted values
    config = _CONFIG.format(null=os.devnull, url=quoted)
    (git_dir / "config").write_text(config, "utf-8")
    (git_dir / "info").mkdir(exist_ok=True)
    (git_dir / "info" / "sparse-checkout").write_text(sparse, "utf-8")
    (git_dir / "info" / "attributes").write_text(_ATTRIBUTES, "utf-8")


def _make_folder(work_root: Path | None) -> str:
    return tempfile.mkdtemp(prefix=_PREFIX, dir=work_root)


def _valid_ref(ref: str) -> bool:
    """Tell whether this is a full ref name that cannot be read as a refspec."""
    return bool(
        _REF.fullmatch(ref)
        and ".." not in ref
        and "//" not in ref
        and not ref.endswith(("/", ".", ".lock"))
        and not any(part.startswith(".") or part.endswith(".lock") for part in ref.split("/"))
    )


def sweep_stale_fetches(
    work_root: Path, older_than: float = FETCH_TIMEOUT_SECONDS + STALE_MARGIN_SECONDS
) -> None:
    """Delete fetch folders a crash left in ``work_root`` (blocking; call it in a thread).

    Only ``fetch-*`` children not touched for ``older_than`` seconds go, never ``work_root``
    itself, a symlinked ``work_root`` or a symlink inside it. The data directory must have
    exactly one job runner: a second one could not tell another runner's live folder from a
    stale one beyond its age.
    """
    if work_root.is_symlink() or not work_root.is_dir():
        return
    limit = time.time() - older_than
    for child in work_root.glob(_PREFIX + "*"):
        if not child.is_symlink() and child.is_dir() and child.stat().st_mtime < limit:
            shutil.rmtree(child, ignore_errors=True)


def _measure(folder: Path) -> tuple[int, int]:
    """Total bytes and number of files below ``folder`` (links are not followed)."""
    size = count = 0
    for root, _, names in os.walk(folder):
        for name in names:
            with suppress(OSError):  # git may remove a file while we count
                size += (Path(root) / name).lstat().st_size
                count += 1
    return size, count


def sparse_patterns(selection: PathSelection) -> list[str]:
    """Non-cone sparse-checkout patterns that cover (at least) every file the selection picks.

    Includes come first, the root README next, exclusions last as ``!`` lines (the last matching
    line wins, as with ``PathSelection``). Over-fetching is harmless because the importer applies
    ``PathSelection.selects`` again; a folder pattern brings its non-article files too.
    """
    # ponytail: no include means "all articles", fetched as every file; narrow it if repos with
    # big non-doc trees show up.
    if selection.include:
        parts = [_anchored(i) for i in selection.include]
        # An overflowing include fetches everything; `{}` (no patterns) fetches only the README.
        includes = ["/*"] if None in parts else [p for part in parts if part for p in part]
    else:
        includes = ["/*"]
    # An overflowing exclusion is dropped: over-fetching is safe, `selects` runs again later.
    excludes = [f"!{p}" for e in selection.exclude if (part := _anchored(e)) for p in part]
    return [*includes, *_ROOT_README, *excludes]


def _anchored(pattern: str) -> list[str] | None:
    """Expand ``{a,b}`` choices, escape ``[`` and anchor at the repository root.

    Returns ``None`` when there are too many choices, ``[]`` for a pattern matching nothing.
    """
    match = re.search(r"\{([^{}]*)\}", pattern)
    if match is None:
        return ["/" + pattern.replace("[", "\\[")]
    if not match[1]:
        return []  # `{}` matches nothing
    expanded: list[str] = []
    for option in match[1].split(","):
        part = _anchored(pattern[: match.start()] + option + pattern[match.end() :])
        if part is None:
            return None
        expanded += part
    return expanded if len(expanded) <= _MAX_BRACE_EXPANSIONS else None


def _environment(home: str) -> dict[str, str]:
    kept = {k: v for k, v in os.environ.items() if k.lower() in _PASSTHROUGH}
    return {
        **kept,
        "HOME": home,
        "USERPROFILE": home,
        "XDG_CONFIG_HOME": home,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
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
