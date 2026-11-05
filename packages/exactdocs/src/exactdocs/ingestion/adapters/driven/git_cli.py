"""Driven adapter for the git ports (remote, gateway, renames): the system ``git``, run defensively.

The URL comes from a user, so git is treated as a process that must not surprise us:

- the URL goes after ``--`` (and one starting with ``-`` is refused), so it is never an option;
- ``GIT_ALLOW_PROTOCOL`` limits transports to file/http/https/ssh: ``ext::`` and ``fd::``
  (which run commands) and ``git://`` are refused by git itself;
- the environment is built from scratch: no user or system git config, no ssh keys or agent
  (ssh is told to use no authentication at all), no askpass, no terminal prompt, a throw-away
  working directory;
- the process has no stdin, its own session, a timeout and capped output; its whole process
  group is killed whenever the call ends, so no helper outlives it, and its pipes are read to
  EOF before the call returns, so no file descriptor outlives it either;
- at most ``MAX_PROCESSES`` git processes run at once;
- git's stderr is only classified, never passed on: it may contain the URL.

Network: git talks to the repository's host and nothing else, with two things to know. It
follows an HTTP redirect on the first request (``http.followRedirects`` is git's default,
``initial``), so a configured server may send it to another host; a token is never sent there
(see below). And it honours ``http_proxy``/``https_proxy``/``all_proxy`` from the environment
(``_PASSTHROUGH``), so behind a proxy its traffic goes to that proxy.

Credentials (``credential=``) never travel in the URL or the argument list. A token reaches git
through ``GIT_ASKPASS``, a small script in the call's private temporary directory that answers
only prompts for the repository's own ``host[:port]`` (git asks again for any other host a
redirect leads to, and the script then refuses, so the redirect fails and the token is not
sent). A deploy key is written to a 0600 file in the same directory and named in
``GIT_SSH_COMMAND``; the directory, and with it the key, is deleted when the call ends. ssh
checks host keys against ``known_hosts`` (``accept-new``: unknown hosts are remembered, a
changed key is a hard ``HostKeyChangedError``) and never against a system file.

``fetch`` (the ``GitGateway`` port) builds on the same ``_run``. Into a folder of its own it
fetches one commit by SHA, ``--depth 1`` and ``--filter=blob:none`` (a server without filters just
sends more), and checks out only the sparse patterns made from the selection plus the root
README and ``context7.json``, so only those blobs are downloaded. The repository config is
written by us and sets no hooks, no submodules, no symlinks (they become small text files, so a
link can never point out of the folder), no fsmonitor, no auto-gc. A server that refuses a bare
SHA is asked for the caller's ref names instead, and the result must still be the pinned commit.

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
import math
import os
import re
import shlex
import shutil
import signal
import sys
import tempfile
import time
from asyncio.subprocess import DEVNULL, PIPE, Process
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from exactdocs.ingestion.errors import (
    CommitUnavailableError,
    GitNotInstalledError,
    HostKeyChangedError,
    InvalidRepositoryUrlError,
    NotAGitRepositoryError,
    PreviewBusyError,
    RepositoryAuthRequiredError,
    RepositoryTooLargeError,
    RepositoryUnreachableError,
    TreeTooLargeError,
    UrlProblem,
)
from exactdocs.ingestion.models import (
    CONTEXT7_FILE,
    MAX_RENAMES,
    MAX_SIMILARITY,
    AccessToken,
    Credential,
    FetchedFile,
    GitRename,
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
MAX_PREVIEWS = 2
PREVIEW_WAIT_SECONDS = 5.0
MAX_FETCH_FILES = 100_000
WATCH_SECONDS = 1.0
STALE_MARGIN_SECONDS = 60.0
MAX_FETCH_BYTES = 512 * 2**20
RENAME_TIMEOUT_SECONDS = 60.0
RENAME_LIMIT = 400
_MAX_STEP_OUTPUT = 1024 * 1024
_MAX_BRACE_EXPANSIONS = 64
_DRAIN_SECONDS = 2.0  # for a killed process's pipes to reach EOF and its exit to be seen
_KEYGEN_SECONDS = 5.0
_PREFIX = "fetch-"
_ROOT_README = ("/README.md", "/README.mdx")
_ROOT_CONTEXT7 = f"/{CONTEXT7_FILE}"  # last: no exclusion can drop it
_ROOT_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")  # one plain name, never an option or glob
# models.ARTICLE_SUFFIXES, whatever the letter case: never fetch the blobs of other files
_ARTICLE_PATHSPEC = (":(icase)*.md", ":(icase)*.mdx")
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
# authentication method is off unless a deploy key is given: a check must not borrow the server
# user's identity. Host keys: remembered on first sight (`accept-new`), a changed one is refused;
# only our own file is consulted, and the server cannot add keys to it (`UpdateHostKeys=no`).
_SSH_BASE = (
    "ssh", "-F", os.devnull, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
    "-o", "GSSAPIAuthentication=no", "-o", "HostbasedAuthentication=no",
    "-o", "KbdInteractiveAuthentication=no", "-o", "PasswordAuthentication=no",
    "-o", "StrictHostKeyChecking=accept-new", "-o", "GlobalKnownHostsFile=" + os.devnull,
    "-o", "UpdateHostKeys=no", "-o", "HashKnownHosts=no", "-o", "VerifyHostKeyDNS=no",
)  # fmt: skip
# git prints the prompt as `Username for 'scheme://host[:port]': ` and then
# `Password for 'scheme://user@host[:port]': `, with the host as typed in the URL. Only those
# two prompts, for the library's own scheme and host (compared in lower case), are answered; a
# redirect to any other host makes git ask for that host, which gets nothing. The values are
# read from files of the call's private directory, so they are in no environment.
_ASKPASS = """\
#!/bin/sh
d=$(dirname "$0")
base=$(cat "$d/askpass.base")
user=$(cat "$d/askpass.user" | tr '[:upper:]' '[:lower:]')
prompt=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
case "$prompt" in
  "username for '$base': ") cat "$d/askpass.user" ;;
  "password for '$base': ") cat "$d/askpass.secret" ;;
  "password for '${base%%://*}://$user@${base#*://}': ") cat "$d/askpass.secret" ;;
  *) exit 1 ;;
esac
"""
_KEY_FILE = "deploy_key"
_ASKPASS_FILE = "askpass.sh"
_RUN_PREFIX = "exactdocs-git-"
# Wording of `git` (LC_ALL=C) and of the transports behind it. Narrow on purpose: a local error
# ("Permission denied" on a directory, a shell "not found") must not read as a remote verdict.
_HOST_KEY_CHANGED = re.compile(
    r"remote host identification has changed|host key verification failed"
    r"|offending (?:\w+ )?key in"
)
_AUTH = re.compile(
    r"terminal prompts disabled|could not read (?:username|password)|authentication failed"
    r"|permission denied \(|error: 40[13]\b"
)
_NOT_A_REPO = re.compile(
    r"does not appear to be a git repository|repository (?:'[^']*' )?not found|error: 404\b"
)


class _OutputTooBigError(RepositoryUnreachableError):
    """A git step printed more than its cap."""


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
    known_hosts: Path | None = None  # remembered SSH host keys; none are kept when None
    fetch_timeout: float = FETCH_TIMEOUT_SECONDS  # for a whole fetch, not per git call
    rename_timeout: float = RENAME_TIMEOUT_SECONDS  # for a whole rename detection
    rename_limit: int = RENAME_LIMIT  # git's `-l`: no similarity search above limit x limit pairs
    max_fetch_bytes: int = MAX_FETCH_BYTES  # of the fetched repository plus its work tree
    max_fetch_files: int = MAX_FETCH_FILES
    watch_interval: float = WATCH_SECONDS
    # Fetches wait here, so long imports cannot take every slot of `slots` from the checks.
    fetch_slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_FETCHES), compare=False, repr=False
    )
    preview_wait: float = PREVIEW_WAIT_SECONDS  # how long a preview waits for a slot
    # Previews wait here, apart from imports: a flood of dry runs must not starve the importer.
    preview_slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_PREVIEWS), compare=False, repr=False
    )
    # Bounds the cost of an unauthenticated endpoint: one process, its helpers and up to
    # `max_output` bytes each.
    slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_PROCESSES), compare=False, repr=False
    )

    @classmethod
    def locate(
        cls,
        *,
        timeout: float = TIMEOUT_SECONDS,
        work_root: Path | None = None,
        known_hosts: Path | None = None,
    ) -> Self:
        """Find ``git`` on ``PATH``; raises ``GitNotInstalledError`` when it is missing."""
        git = shutil.which("git")
        if git is None:
            raise GitNotInstalledError
        return cls(git=git, timeout=timeout, work_root=work_root, known_hosts=known_hosts)

    async def list_refs(
        self,
        repository: RepositoryUrl,
        *patterns: str,
        credential: Credential | None = None,
    ) -> RemoteRefs:
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
            auth=_Auth.of(repository, credential),
        )
        if output.code:
            raise _failure(output.stderr, ssh=repository.transport == "ssh")
        return _parse(output.stdout.decode(errors="replace"))

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        """Return the ``SHA256:`` fingerprint ssh remembered for the host (ed25519 first)."""
        keygen = shutil.which("ssh-keygen")
        if repository.transport != "ssh" or self.known_hosts is None or keygen is None:
            return None
        port = urlsplit(repository.url).port if "://" in repository.url else None
        name = f"[{repository.hostname}]:{port}" if port else repository.hostname
        try:
            process = await asyncio.create_subprocess_exec(
                keygen, "-l", "-F", name, "-f", str(self.known_hosts),
                stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL,
            )  # fmt: skip
        except OSError:
            return None
        try:
            async with asyncio.timeout(_KEYGEN_SECONDS):
                out, _ = await process.communicate()
        except TimeoutError:
            return None
        finally:
            # Also on cancellation: ssh-keygen must not outlive the call, nor its pipe.
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await _settle(process)
        found = [
            line.split()
            for line in out.decode(errors="replace").splitlines()
            if line and not line.startswith("#")
        ]
        prints = [(parts[1], parts[-1]) for parts in found if len(parts) >= 3]  # ruff: ignore[magic-value-comparison]
        prints.sort(key=lambda p: p[1] != "(ED25519)")
        return prints[0][0] if prints and prints[0][0].startswith("SHA256:") else None

    @asynccontextmanager
    async def fetch(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        selection: PathSelection,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> AsyncGenerator[Path]:
        """Implement ``GitGateway.fetch`` (see the module docstring).

        Yields:
            The folder with the checked-out files; it is removed afterwards.

        """
        async with self.checkout(
            repository, commit_sha, sparse_patterns(selection), refs, credential
        ) as folder:
            yield folder

    @asynccontextmanager
    async def fetch_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        paths: Sequence[str],
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> AsyncGenerator[Path]:
        """Implement ``GitGateway.fetch_files``: the same checkout, but of exactly these files.

        The watchdog's size limit is ``max_bytes`` (plus room for git's own files) instead of
        the whole-repository limit, so a server cannot make a few images cost a repository.

        Yields:
            The folder with the checked-out files; it is removed afterwards.

        """
        bounded = replace(self, max_fetch_bytes=max_bytes + _GIT_OVERHEAD)
        async with bounded.checkout(
            repository,
            commit_sha,
            [p for path in paths if (p := _literal(path))] or ["!/*"],
            refs,
            credential,
        ) as folder:
            yield folder

    @asynccontextmanager
    async def checkout(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        sparse: list[str],
        refs: Sequence[str],
        credential: Credential | None,
    ) -> AsyncGenerator[Path]:
        """Check out the sparse lines of the commit into a folder of its own (see ``fetch``).

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
                auth = _Auth.of(repository, credential)
                await self._populate(
                    folder, repository.url, commit_sha, sparse, refs, deadline, auth
                )
                yield folder
            finally:
                shutil.rmtree(folder, ignore_errors=True)

    def _stepper(
        self, folder: Path, url: str, deadline: float, auth: _Auth | None
    ) -> Callable[..., Awaitable[_Output]]:
        """Return ``git(*args)``: one isolated step inside ``folder`` under the call's deadline.

        A step may pass ``watch_bytes`` to hold ``folder`` to fewer bytes than
        ``max_fetch_bytes`` while it runs.
        """
        local = url.lower().startswith("file:")

        async def git(
            *args: str, cap: int = _MAX_STEP_OUTPUT, watch_bytes: int | None = None
        ) -> _Output:
            # every step may authenticate: checkout fetches the blobs it needs lazily
            return await self._run(
                ["-C", str(folder), *args],
                cap=cap,
                deadline=deadline,
                trust_local=local,
                watch=folder,
                watch_bytes=watch_bytes,
                auth=auth,
            )

        return git

    async def _populate(
        self,
        folder: Path,
        url: str,
        sha: str,
        sparse_lines: list[str],
        refs: Sequence[str],
        deadline: float,
        auth: _Auth | None = None,
    ) -> None:
        git = self._stepper(folder, url, deadline, auth)
        ssh = repository_url_is_ssh(url)
        await _prepare(git, folder, url, "\n".join(sparse_lines) + "\n", ssh=ssh)
        await _fetch_commit(git, sha, refs, ssh=ssh)
        out = await git("checkout", "-q", "--detach", "--no-recurse-submodules", sha)
        if out.code:
            raise _failure(out.stderr, ssh=ssh)
        size, count = await asyncio.to_thread(_measure, folder)
        if size > self.max_fetch_bytes or count > self.max_fetch_files:
            raise RepositoryTooLargeError(self.max_fetch_bytes)

    async def list_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> list[str]:
        """Implement ``RepositoryTree.list_files``: fetch the trees only, run ``git ls-tree``.

        The same hardening, deadline (``fetch_timeout``), size watchdog and process ``slots`` as
        ``fetch``, with ``preview_slots`` of its own. No blob is downloaded and nothing is checked
        out. More than ``max_output`` bytes of paths is an error (``RepositoryUnreachableError``).
        """
        async with self._trees(repository, commit_sha, refs, credential) as trees:
            try:
                out = await trees.git(
                    "ls-tree", "-r", "-z", "--full-tree", commit_sha, cap=self.max_output
                )
            except _OutputTooBigError:
                raise TreeTooLargeError from None
            if out.code:
                raise _failure(out.stderr, ssh=trees.ssh)
            return _tree_files(out.stdout)

    async def read_file(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> FetchedFile:
        """Implement ``RepositoryTree.read_file``: the trees, then that one blob, lazily.

        Runs under a preview slot like ``list_files``, never an import's ``fetch_slots``. The
        tree entry must be a regular file (not a link, a folder or a submodule). The blob is
        then read with ``cat-file`` (the partial clone fetches only it); its output is capped at
        ``max_bytes`` and the download by a watchdog limit of what is already there plus
        ``max_bytes`` and git's overhead, so a huge file costs at most that much.
        """
        if not _ROOT_NAME.fullmatch(path):
            message = f"not a plain root file name: {path!r}"
            raise ValueError(message)
        async with self._trees(repository, commit_sha, refs, credential) as trees:
            out = await trees.git(
                "ls-tree", "-z", "--full-tree", commit_sha, "--", f":(literal){path}"
            )
            if out.code:
                raise _failure(out.stderr, ssh=trees.ssh)
            entry = out.stdout.split(b"\0")[0]
            if not entry:
                return FetchedFile()
            mode, kind, blob = entry.partition(b"\t")[0].decode().split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                return FetchedFile(problem="not a regular file")
            used, _ = await asyncio.to_thread(_measure, trees.folder)
            try:
                data = await trees.git(
                    "cat-file",
                    "blob",
                    blob,
                    cap=max_bytes,
                    watch_bytes=used + max_bytes + _GIT_OVERHEAD,
                )
            except _OutputTooBigError, RepositoryTooLargeError:
                return FetchedFile(problem=f"larger than {max_bytes} bytes")
            if data.code:
                raise _failure(data.stderr, ssh=trees.ssh)
            return FetchedFile(data=data.stdout)

    @asynccontextmanager
    async def _trees(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        refs: Sequence[str],
        credential: Credential | None,
    ) -> AsyncGenerator[_Trees]:
        """Hold a preview slot and fetch the commit and its trees, no blob, into a fresh folder.

        Yields:
            The fetched folder (removed afterwards) and how to run git in it.

        """
        if (
            repository.url.startswith("-")
            or not repository.url.isprintable()
            or not _COMMIT.fullmatch(commit_sha)
            or not all(_valid_ref(ref) for ref in refs)
        ):
            raise InvalidRepositoryUrlError(UrlProblem.GIT_OPTION)
        async with self._preview_slot():
            if self.work_root is not None:
                await asyncio.to_thread(self.work_root.mkdir, parents=True, exist_ok=True)
            folder = Path(await asyncio.to_thread(_make_folder, self.work_root))
            try:
                url = repository.url
                deadline = asyncio.get_running_loop().time() + self.fetch_timeout
                git = self._stepper(folder, url, deadline, _Auth.of(repository, credential))
                ssh = repository_url_is_ssh(url)
                await _prepare(git, folder, url, "", ssh=ssh)
                await _fetch_commit(git, commit_sha, refs, ssh=ssh)
                yield _Trees(git=git, ssh=ssh, folder=folder, deadline=deadline)
            finally:
                shutil.rmtree(folder, ignore_errors=True)

    @asynccontextmanager
    async def _preview_slot(self) -> AsyncGenerator[None]:
        """Hold a preview slot; ``PreviewBusyError`` when none is free within ``preview_wait``."""
        try:
            async with asyncio.timeout(self.preview_wait):
                await self.preview_slots.acquire()
        except TimeoutError:
            raise PreviewBusyError(retry_after=math.ceil(self.preview_wait)) from None
        try:
            yield
        finally:
            self.preview_slots.release()

    async def renames(
        self,
        repository: RepositoryUrl,
        old_sha: str,
        new_sha: str,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> Sequence[GitRename]:
        """Implement ``RenameSource.renames``.

        Cost, measured on ``fastapi/fastapi`` 0.100.0 to 0.115.0 (about 1,400 Markdown files):
        fetching both commits as ``--depth=1 --filter=blob:none`` takes about 1 s and 250 KB (trees
        only), and ``diff-tree -M`` then fetches about 1 MB of blobs in one more second: only the
        files that were added or deleted (Markdown ones, by pathspec) are read to score renames
        with edits. Exact renames (same blob) need no blobs at all. Bounds: a fetch slot (shared
        with imports), ``rename_timeout`` for everything, the folder size watchdog, and
        ``rename_limit`` (git skips the similarity search when added x deleted files exceed
        limit squared; exact renames are still found). The rename limit bounds CPU, not
        downloads: a hostile repository with huge added and deleted Markdown files is stopped by
        the size watchdog and the deadline.
        """
        if (
            repository.url.startswith("-")
            or not repository.url.isprintable()
            or not (_COMMIT.fullmatch(old_sha) and _COMMIT.fullmatch(new_sha))
            or not all(_valid_ref(ref) for ref in refs)
        ):
            raise InvalidRepositoryUrlError(UrlProblem.GIT_OPTION)
        async with self.fetch_slots:
            if self.work_root is not None:
                await asyncio.to_thread(self.work_root.mkdir, parents=True, exist_ok=True)
            folder = Path(await asyncio.to_thread(_make_folder, self.work_root))
            try:
                url = repository.url
                deadline = asyncio.get_running_loop().time() + self.rename_timeout
                git = self._stepper(folder, url, deadline, _Auth.of(repository, credential))
                ssh = repository_url_is_ssh(url)
                await _prepare(git, folder, url, "", ssh=ssh)
                for sha in (new_sha, old_sha):
                    await _fetch_commit(git, sha, refs, ssh=ssh)
                out = await git(
                    "diff-tree", "-r", "-z", "--name-status", "--diff-filter=R", "-M",
                    f"-l{self.rename_limit}", "--no-ext-diff", old_sha, new_sha,
                    "--", *_ARTICLE_PATHSPEC,
                    cap=self.max_output,  # MAX_RENAMES long paths; `_parse_renames` truncates
                )  # fmt: skip
                if out.code:
                    raise _failure(out.stderr, ssh=ssh)
                return _parse_renames(out.stdout)
            finally:
                shutil.rmtree(folder, ignore_errors=True)

    async def _run(
        self,
        args: Sequence[str],
        *,
        cap: int,
        limit: float | None = None,
        deadline: float | None = None,
        trust_local: bool = False,
        watch: Path | None = None,
        watch_bytes: int | None = None,
        auth: _Auth | None = None,
    ) -> _Output:
        """Run ``git <args>`` isolated (see the module docstring); the shared base for fetches.

        ``trust_local`` lets git read local repositories owned by another user. ``deadline`` (a
        loop time) replaces ``limit`` and is read once the slot is held. ``watch`` is a folder
        whose size is limited (to ``watch_bytes``, else ``max_fetch_bytes``) while git runs
        (``RepositoryTooLargeError``). ``auth`` is made
        available to this one process, in its private directory, and gone when it ends.

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
            if self.work_root is not None:  # not the system temp dir: it may be mounted noexec
                await asyncio.to_thread(self.work_root.mkdir, parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=_RUN_PREFIX, dir=self.work_root) as home:
                return await self._execute(
                    args,
                    cap=cap,
                    limit=seconds,
                    home=home,
                    trust_local=trust_local,
                    watch=watch,
                    watch_bytes=watch_bytes,
                    auth=auth,
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
        watch_bytes: int | None = None,
        auth: _Auth | None = None,
    ) -> _Output:
        max_bytes = self.max_fetch_bytes if watch_bytes is None else watch_bytes
        environment = _environment(home, self.known_hosts)
        if auth is not None:
            await asyncio.to_thread(_offer, environment, home, auth, self.known_hosts)
        if trust_local:
            config = Path(home, "gitconfig")
            await asyncio.to_thread(config.write_text, "[safe]\n\tdirectory = *\n", "utf-8")
            environment["GIT_CONFIG_GLOBAL"] = str(config)
        process = await asyncio.create_subprocess_exec(
            self.git, "-c", "credential.helper=", *args,
            stdin=DEVNULL, stdout=PIPE, stderr=PIPE, cwd=home, env=environment,
            start_new_session=True,
        )  # fmt: skip
        guard = asyncio.create_task(self._guard(process, watch, max_bytes)) if watch else None
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
            await _settle(process)
        if tripped:
            raise RepositoryTooLargeError(max_bytes)
        if len(out) > cap:
            raise _OutputTooBigError(_TOO_BIG)
        return _Output(out, err.decode(errors="replace").lower(), code)

    async def _guard(self, process: Process, folder: Path, max_bytes: int) -> None:
        """Return (after killing git) as soon as ``folder`` holds too many bytes or files."""
        while True:
            await asyncio.sleep(self.watch_interval)
            size, count = await asyncio.to_thread(_measure, folder)
            if size > max_bytes or count > self.max_fetch_files:
                _kill_group(process)
                return


@dataclass(frozen=True, slots=True)
class _Trees:
    """A blob-less fetch of one commit: its folder, and ``git`` steps under its deadline."""

    git: Callable[..., Awaitable[_Output]]
    ssh: bool
    folder: Path
    deadline: float


@dataclass(frozen=True, slots=True)
class MissingGit:
    """Stands in for ``GitCli`` when there is no ``git``: every use says what to install."""

    async def list_refs(
        self,
        repository: RepositoryUrl,
        *patterns: str,
        credential: Credential | None = None,
    ) -> RemoteRefs:
        """Refuse with ``GitNotInstalledError``."""
        del repository, patterns, credential
        raise GitNotInstalledError

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        """Refuse with ``GitNotInstalledError``."""
        del repository
        raise GitNotInstalledError

    def fetch(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        selection: PathSelection,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> AbstractAsyncContextManager[Path]:
        """Refuse with ``GitNotInstalledError``."""
        del repository, commit_sha, selection, refs, credential
        return _no_git()

    async def list_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> list[str]:
        """Refuse with ``GitNotInstalledError``."""
        del repository, commit_sha, refs, credential
        raise GitNotInstalledError

    async def read_file(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> FetchedFile:
        """Refuse with ``GitNotInstalledError``."""
        del repository, commit_sha, path, max_bytes, refs, credential
        raise GitNotInstalledError

    async def renames(
        self,
        repository: RepositoryUrl,
        old_sha: str,
        new_sha: str,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> Sequence[GitRename]:
        """Refuse with ``GitNotInstalledError``."""
        del repository, old_sha, new_sha, refs, credential
        raise GitNotInstalledError

    def fetch_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        paths: Sequence[str],
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> AbstractAsyncContextManager[Path]:
        """Refuse with ``GitNotInstalledError``."""
        del repository, commit_sha, paths, max_bytes, refs, credential
        return _no_git()


@asynccontextmanager
async def _no_git() -> AsyncGenerator[Path]:
    raise GitNotInstalledError
    yield  # pragma: no cover


async def _prepare(
    git: Callable[..., Awaitable[_Output]], folder: Path, url: str, sparse: str, *, ssh: bool
) -> None:
    """Make ``folder`` an empty repository that fetches commits without blobs from ``url``."""
    init = await git("init", "-q", "--template=")
    if init.code:
        raise _failure(init.stderr, ssh=ssh)
    await asyncio.to_thread(_write_config, folder, url, sparse)


async def _fetch_commit(
    git: Callable[..., Awaitable[_Output]], sha: str, refs: Sequence[str], *, ssh: bool
) -> None:
    """Fetch ``sha`` alone (depth 1, no blobs); ``refs`` are tried if the server refuses a SHA."""
    for target in (sha, *refs):
        out = await git(
            "fetch", "-q", "--depth=1", "--filter=blob:none", "--no-tags",
            "--no-recurse-submodules", "origin", target,
        )  # fmt: skip
        if out.code and not _GONE.search(out.stderr):
            raise _failure(out.stderr, ssh=ssh)
        if not out.code:
            head = await git("rev-parse", "--verify", "-q", "FETCH_HEAD^{commit}")
            if head.stdout.decode().strip() == sha:
                return
    raise CommitUnavailableError


def _parse_renames(output: bytes) -> list[GitRename]:
    """Parse ``diff-tree -z --name-status``: NUL-separated ``R<score>``, old path, new path."""
    fields = output.split(b"\0")
    renames: list[GitRename] = []
    for index in range(0, len(fields) - 2, 3):
        status, old, new = fields[index : index + 3]
        if (
            status.startswith(b"R")
            and status[1:].isdigit()
            and 0 < int(status[1:]) <= MAX_SIMILARITY
        ):
            renames.append(
                GitRename(
                    old_path=old.decode(errors="surrogateescape"),
                    new_path=new.decode(errors="surrogateescape"),
                    similarity=int(status[1:]),
                )
            )
    return renames[:MAX_RENAMES]


def _write_config(folder: Path, url: str, sparse: str) -> None:
    git_dir = folder / ".git"
    quoted = json.dumps(url, ensure_ascii=False)  # git unescapes \\ and \" in quoted values
    config = _CONFIG.format(null=os.devnull, url=quoted)
    (git_dir / "config").write_text(config, "utf-8")
    (git_dir / "info").mkdir(exist_ok=True)
    (git_dir / "info" / "sparse-checkout").write_text(sparse, "utf-8")
    (git_dir / "info" / "attributes").write_text(_ATTRIBUTES, "utf-8")


def _tree_files(output: bytes) -> list[str]:
    """Parse ``ls-tree -r -z`` (NUL-ended entries ``mode type sha TAB path``): blobs only."""
    paths = []
    for entry in output.split(b"\0"):
        meta, _, path = entry.partition(b"\t")
        mode, _, rest = meta.partition(b" ")
        # Symlinks (120000) are skipped by the import, so they are not previewed either.
        if path and mode != b"120000" and rest.startswith(b"blob "):
            # Lossy on purpose: names are shown, never used. Two different non-UTF-8 names may
            # read alike (the renames use surrogateescape, which they need to look files up).
            paths.append(path.decode(errors="replace"))
    return paths


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
    for prefix in (_PREFIX, _RUN_PREFIX):  # a crash can leave a call's credential files too
        for child in work_root.glob(prefix + "*"):
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

    Includes come first, the root README next, then exclusions as ``!`` lines (the last matching
    line wins, as with ``PathSelection``), and the root ``context7.json`` at the very end.
    Over-fetching is harmless because the importer applies ``PathSelection.selects`` again; a
    folder pattern brings its non-article files too.
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
    return [*includes, *_ROOT_README, *excludes, _ROOT_CONTEXT7]


_GIT_OVERHEAD = 4 * 2**20  # .git of a one-commit, blob-less fetch: trees, refs, config


def _literal(path: str) -> str | None:
    """Return a sparse-checkout line that matches exactly this repository path, or ``None``.

    Glob characters are escaped, so a hostile file name cannot widen the checkout; a path with
    a control character (a newline would start a new pattern) is refused.
    """
    if not path or not path.isprintable():
        return None
    escaped = re.sub(r"([\\*?\[\]])", r"\\\1", path)
    return "/" + (escaped[:-1] + "\\ " if escaped.endswith(" ") else escaped)


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


@dataclass(frozen=True, slots=True)
class _Auth:
    """A credential and the only host it may be offered to."""

    credential: Credential = field(repr=False)
    scope: str  # `scheme://host[:port]`, lower-case

    @classmethod
    def of(cls, repository: RepositoryUrl, credential: Credential | None) -> Self | None:
        return None if credential is None else cls(credential, repository.credential_scope)


def _ssh_command(known_hosts: Path | None, key: str | None = None) -> str:
    kept = ["-o", "UserKnownHostsFile=" + str(known_hosts or os.devnull)]
    if key is None:
        kept += ["-o", "PubkeyAuthentication=no"]
    else:
        kept += ["-i", key, "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none"]
    return shlex.join([*_SSH_BASE, *kept])


def _write_private(path: Path, text: str, mode: int) -> None:
    """Create ``path`` (it must not exist) with ``mode`` from the start, never wider."""
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def _offer(environment: dict[str, str], home: str, auth: _Auth, known_hosts: Path | None) -> None:
    """Make the credential available to one git process through its environment and ``home``."""
    credential = auth.credential
    if isinstance(credential, AccessToken):
        script = Path(home, _ASKPASS_FILE)
        _write_private(script, _ASKPASS, 0o700)
        _write_private(Path(home, "askpass.base"), auth.scope + "\n", 0o600)
        _write_private(Path(home, "askpass.user"), credential.username + "\n", 0o600)
        _write_private(Path(home, "askpass.secret"), credential.token + "\n", 0o600)
        environment["GIT_ASKPASS"] = str(script)
    else:
        key = Path(home, _KEY_FILE)
        _write_private(key, credential.private_key, 0o600)
        environment["GIT_SSH_COMMAND"] = _ssh_command(known_hosts, str(key))


def _environment(home: str, known_hosts: Path | None = None) -> dict[str, str]:
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
        "GIT_SSH_COMMAND": _ssh_command(known_hosts),
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


async def _settle(process: Process) -> None:
    """Read a killed process's pipes to EOF, then wait for it, for at most ``_DRAIN_SECONDS``.

    After a timeout or a cancellation the process is killed while its output is still unread.
    Its transport (and the pipe file descriptors) only closes once every pipe has reached EOF
    and the exit has been seen, so without this they stay open until the event loop happens
    to run again. ``wait()`` itself only returns once the pipes are closed if the process was
    still running when it was called, so it sits inside the bound too: a helper that left the
    process group could keep a pipe open for as long as it lives. The child is reaped either
    way; only its transport then closes later, when that helper exits.
    """
    with suppress(TimeoutError):
        async with asyncio.timeout(_DRAIN_SECONDS):
            for stream in (process.stdout, process.stderr):
                while stream and await stream.read(65536):
                    pass
            await process.wait()


def _kill_group(process: Process) -> None:
    with suppress(ProcessLookupError):
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)


def repository_url_is_ssh(url: str) -> bool:
    """Tell whether git reaches this URL over ssh (``ssh://`` or scp-like ``user@host:path``)."""
    return "://" not in url or url.lower().startswith("ssh://")


def _failure(
    stderr: str,
    *,
    ssh: bool = False,
) -> (
    RepositoryUnreachableError
    | NotAGitRepositoryError
    | RepositoryAuthRequiredError
    | HostKeyChangedError
):
    # Only ssh's own words count: an HTTP server could print them in a "remote:" message.
    if ssh and _HOST_KEY_CHANGED.search(stderr):
        return HostKeyChangedError()
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
