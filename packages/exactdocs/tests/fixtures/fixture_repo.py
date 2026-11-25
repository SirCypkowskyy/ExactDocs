"""Build the fixture docs repository and serve it over the two git transports we import from.

Plain test support (standard library only), used by the pytest fixtures in ``tests/conftest.py``
and by the behave hooks in ``features/environment.py``. Run it as a script to build the
repository by hand: ``python fixture_repo.py <destination>``.
"""

import base64
import contextlib
import http.server
import os
import re
import shutil
import subprocess
import sys
import threading
import tomllib
from collections.abc import Callable, Generator
from dataclasses import dataclass
from io import BufferedIOBase
from pathlib import Path
from urllib.parse import urlsplit

FIXTURE = Path(__file__).parent / "docs-repo"
# git serves it as <root>/fixture/docs-repo[.git]; the importer derives "/fixture/docs-repo".
REPO_PATH = Path("fixture") / "docs-repo"


def _env(**extra: str) -> dict[str, str]:
    """The caller's environment minus anything that makes git behave differently per machine."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {
        **env,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        # git also reads $XDG_CONFIG_HOME/git/{ignore,attributes}, even with GIT_CONFIG_GLOBAL unset
        "XDG_CONFIG_HOME": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "no_proxy": "127.0.0.1",
        **extra,
    }


def git_bytes(*args: str, cwd: Path | None = None, check: bool = True, **env: str) -> bytes:
    """Run git with an isolated configuration; return its raw stdout."""
    git_bin = shutil.which("git")
    assert git_bin, "git is required"
    run = subprocess.run(
        [git_bin, *args], cwd=cwd, env=_env(**env), capture_output=True, check=False
    )
    if check and run.returncode:
        message = f"git {' '.join(args)} exited with {run.returncode}: {run.stderr.decode()}"
        raise RuntimeError(message)
    return run.stdout


def git(*args: str, cwd: Path | None = None, check: bool = True, **env: str) -> str:
    """Like ``git_bytes``, as text without the trailing newline."""
    return git_bytes(*args, cwd=cwd, check=check, **env).decode().rstrip("\n")


def _write_generated(path: Path, size: int) -> None:
    """A deterministic text file of at least ``size`` bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# Complete changelog\n\n")
        written = 0
        number = 0
        while written < size:
            number += 1
            line = f"- entry {number:07d}: a long and uneventful changelog line of filler text\n"
            written += out.write(line)


def build(dest: Path) -> Path:
    """Build the fixture repository at ``dest`` (a new directory); every SHA is reproducible."""
    history = tomllib.loads((FIXTURE / "history.toml").read_text(encoding="utf-8"))
    name, email = history["author"].removesuffix(">").split(" <")
    dest.mkdir(parents=True)
    git("init", "-q", "-b", "main", "--template=", str(dest))
    git("config", "uploadpack.allowFilter", "true", cwd=dest)  # blobless clones
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=dest)  # fetch commits by SHA
    branches: dict[str, str] = {}
    for commit in history["commit"]:
        shutil.copytree(FIXTURE / "commits" / commit["name"], dest, dirs_exist_ok=True)
        for path in commit.get("delete", []):
            (dest / path).unlink()
        for path, size in commit.get("generated", {}).items():
            _write_generated(dest / path, size)
        git("add", "-A", cwd=dest)
        git(
            "commit", "-q", "--no-verify", "-m", commit["message"], cwd=dest,
            GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=commit["date"],
            GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email, GIT_COMMITTER_DATE=commit["date"],
        )  # fmt: skip
        sha = git("rev-parse", "HEAD", cwd=dest)
        for tag in commit.get("tags", []):
            git("tag", tag, sha, cwd=dest)
        branches |= dict.fromkeys(commit.get("branches", []), sha)
    for branch, sha in branches.items():
        git("update-ref", f"refs/heads/{branch}", sha, cwd=dest)
    git("reset", "-q", "--hard", "main", cwd=dest)  # HEAD is main, a commit behind the build
    return dest


def headings(markdown: str) -> set[tuple[str, ...]]:
    """Every heading path (H1 first) of ``markdown``, ignoring front matter and fenced code."""
    markdown = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.DOTALL)
    stack: list[str] = []
    paths: set[tuple[str, ...]] = set()
    fenced = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (match := re.match(r"(#{1,6}) (.+)", line)):
            del stack[len(match[1]) - 1 :]
            stack.append(match[2].strip())
            paths.add(tuple(stack))
    return paths


TOKEN = "s3cr3t-fixture-token-4f1d9a"
USER = "x-access-token"


@dataclass(frozen=True, slots=True)
class DocsRepo:
    path: Path
    file_url: str
    http_url: str  # smart HTTP on 127.0.0.1, served by `git http-backend`
    private_url: str = ""  # the same repository, but only for HTTP Basic `x-access-token:TOKEN`
    token: str = TOKEN
    # (Host header, Authorization header) of every request the private server received
    private_seen: list[tuple[str, str | None]] | None = None
    # Answers every request with a redirect to the private server under another host name
    # ("localhost" instead of "127.0.0.1"): a token must not follow it.
    redirect_url: str = ""
    # Asks for the token, then (once given) redirects to that other host name as well.
    bounce_url: str = ""


def _chunked(stream: BufferedIOBase) -> bytes:
    """Decode a ``Transfer-Encoding: chunked`` request body."""
    body = b""
    while size := int(stream.readline().split(b";")[0], 16):
        body += stream.read(size)
        stream.readline()
    stream.readline()
    return body


def _handler(  # ruff: ignore[complex-structure]
    root: Path,
    *,
    token: str | Callable[[], str | None] | None = None,
    seen: list[tuple[str, str | None]] | None = None,
    redirect_base: Callable[[], str] | None = None,
    redirect_only_with_token: bool = False,
) -> type[http.server.BaseHTTPRequestHandler]:
    def wanted() -> str | None:
        current = token() if callable(token) else token
        return (
            "Basic " + base64.b64encode(f"{USER}:{current}".encode()).decode() if current else None
        )

    class GitHandler(http.server.BaseHTTPRequestHandler):
        """Speaks CGI to ``git http-backend`` (python's own CGI handler is being removed)."""

        def do_GET(self) -> None:
            self._cgi(b"")

        def do_POST(self) -> None:
            if self.headers.get("Transfer-Encoding") == "chunked":
                self._cgi(_chunked(self.rfile))
            else:
                self._cgi(self.rfile.read(int(self.headers.get("Content-Length", 0))))

        def _answer(self, code: int, *headers: tuple[str, str]) -> None:
            self.send_response(code)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _cgi(self, body: bytes) -> None:
            if seen is not None:
                seen.append((self.headers.get("Host", ""), self.headers.get("Authorization")))
            expected = wanted()
            allowed = expected is None or self.headers.get("Authorization") == expected
            if redirect_base is not None and (allowed or not redirect_only_with_token):
                self._answer(302, ("Location", redirect_base() + self.path))
                return
            if not allowed:
                self._answer(401, ("WWW-Authenticate", 'Basic realm="git"'))
                return
            url = urlsplit(self.path)
            env = _env(
                GIT_PROJECT_ROOT=str(root),
                GIT_HTTP_EXPORT_ALL="1",
                REQUEST_METHOD=self.command,
                PATH_INFO=url.path.replace(".git/", "/", 1),  # the repo is a worktree: no .git
                QUERY_STRING=url.query,
                CONTENT_TYPE=self.headers.get("Content-Type", ""),
                CONTENT_LENGTH=str(len(body)),
                REMOTE_ADDR=self.client_address[0],
                **{
                    "HTTP_" + key.upper().replace("-", "_"): value
                    for key, value in self.headers.items()
                    if key.lower() not in {"content-type", "content-length"}
                },
            )
            git_bin = shutil.which("git")
            assert git_bin, "git is required"
            out = subprocess.run(
                [git_bin, "http-backend"],
                input=body,
                env=env,
                capture_output=True,
                check=False,
                timeout=60,
            ).stdout
            head, _, payload = out.partition(b"\r\n\r\n")
            headers = [line.split(": ", 1) for line in head.decode().split("\r\n")]
            status = next((v for k, v in headers if k == "Status"), "200 OK")
            self.send_response(int(status.split()[0]))
            for key, value in headers:
                if key != "Status":
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            """Stay quiet: access logs do not belong in test output."""

    return GitHandler


def git_http_handler(root: Path) -> type[http.server.BaseHTTPRequestHandler]:
    """The smart HTTP handler of the repositories under ``root``, no credentials asked (#538).

    Args:
        root: The folder holding ``<owner>/<name>`` repositories.

    Returns:
        The handler class.
    """
    return _handler(root)


@dataclass(slots=True)
class GitServer:
    """A smart HTTP server for one copy of the repository; set ``token`` to rotate it."""

    url: str
    token: str | None = TOKEN


@contextlib.contextmanager
def serve_copy(base: Path, token: str | None = TOKEN) -> Generator[GitServer]:
    """Serve ``base/fixture/docs-repo`` (a copy, so a test may change or delete it) over HTTP.

    The server asks for ``x-access-token:<token>`` while ``token`` is set, and reads it on every
    request: changing it makes the server refuse the old one, like an expired credential.

    Yields:
        The server's URL and its current token.
    """
    state = GitServer(url="", token=token)
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler(base, token=lambda: state.token)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        state.url = f"http://127.0.0.1:{server.server_address[1]}/{REPO_PATH.as_posix()}.git"
        yield state
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def served(base: Path) -> Generator[DocsRepo]:
    """Build the repository under ``base`` and serve it: ``file://`` and HTTP on 127.0.0.1.

    Yields:
        Where the repository is and the two URLs to clone it from.
    """
    repo = build(base / REPO_PATH)
    seen: list[tuple[str, str | None]] = []
    ports: dict[str, int] = {}

    def start(**options: object) -> http.server.ThreadingHTTPServer:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(base, **options))  # ty: ignore[invalid-argument-type]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def other_host() -> str:
        return f"http://localhost:{ports['private']}"

    servers = [
        start(),
        start(token=TOKEN, seen=seen),
        start(redirect_base=other_host),
        start(token=TOKEN, redirect_base=other_host, redirect_only_with_token=True),
    ]
    try:
        ports["private"] = servers[1].server_address[1]
        path = f"{REPO_PATH.as_posix()}.git"
        urls = [f"http://127.0.0.1:{server.server_address[1]}/{path}" for server in servers]
        yield DocsRepo(
            repo, repo.as_uri(), urls[0],
            private_url=urls[1], private_seen=seen, redirect_url=urls[2], bounce_url=urls[3],
        )  # fmt: skip
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    target = build(Path(sys.argv[1]))
    sys.stdout.write(git("for-each-ref", "--format=%(objectname) %(refname)", cwd=target) + "\n")
