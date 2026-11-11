"""Upgrade test: a data directory written by the previous release, served by this build.

    python3 deploy/upgrade_check.py [--wheels DIR] [--previous X.Y.Z] [--head REVISION]
    python3 deploy/upgrade_check.py --print-head   # the Alembic head of this checkout

1. The previous release (``uvx --from exactdocs==X.Y.Z``, from PyPI; default: the newest stable
   one below this build's version) starts on an empty data directory; an admin, a token and the
   fixture docs repository at two tags are added over its REST API, and what it serves is
   recorded.
2. It stops, and this build starts on the same directory: it must migrate the schema to the head
   of this checkout's Alembic revisions (not the head the build reports about itself) and serve
   the same libraries, articles and search results, to the same token.
3. ``exactdocs reindex`` runs while that server keeps answering searches, then swaps the index.

With --wheels (the exactdocs and exactdocs-kernel wheels) this build runs the way uvx runs it;
without, ``uv run exactdocs`` from the checkout. Give each build a unique version (CI: a local
version with the commit) or a fresh ``UV_CACHE_DIR``: uv reuses a cached wheel of the same file
name, so another build of ``0.0.0.dev0`` would run instead of this one. Everything it starts is
gone when it exits. Only the fields both releases return are compared: a release may add fields,
not change them (except its own fixed wording, ``NOT_STORED``, such as the notice).
"""

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from http import HTTPStatus
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/exactdocs/tests/fixtures"))
import fixture_repo  # ruff: ignore[module-import-not-at-top-of-file]  (test support next to the package, not installed)

LIBRARY = "/fixture/docs-repo"
REFS = ("v1.3.0", "v1.4.0")
QUERIES = ("token", "retry_policy")
HEALTH_RETRIES = 5  # a null reindex_required (database slow to answer) is asked again
HEAD = (
    "from alembic.script import ScriptDirectory;"
    "from exactdocs.bootstrap.database import alembic_config;"
    "print(ScriptDirectory.from_config(alembic_config()).get_current_head())"
)


def step(message: str) -> None:
    print(f"--- {message}", flush=True)


def release_key(version: str) -> tuple[int, ...] | None:
    """Return ``X.Y.Z`` as a sortable tuple; ``None`` for anything else (pre-, dev-, local)."""
    parts = version.removeprefix("v").split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


def this_version(wheels: Path | None) -> tuple[int, ...] | None:
    """Return this build's release version: the wheel's, else a ``vX.Y.Z`` tag on HEAD.

    The tag fallback only matters for a manual run on a tagged checkout: CI does not build
    tags, and on a pull request HEAD is the merge commit.
    """
    if wheels and (key := release_key(wheel_version(wheels))):
        return key
    tags = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "--points-at", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    return max(filter(None, map(release_key, tags)), default=None)


def previous_release(below: tuple[int, ...] | None) -> str | None:
    """Return the newest stable release on PyPI older than ``below`` (any when it is ``None``)."""
    with urllib.request.urlopen("https://pypi.org/pypi/exactdocs/json", timeout=30) as response:
        releases = json.load(response)["releases"]
    stable = {
        key: v
        for v, files in releases.items()
        if files and (key := release_key(v)) and (below is None or key < below)
    }
    return stable[max(stable)] if stable else None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    """The few REST calls the check needs, with a session cookie or a bearer token."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.cookie: str | None = None
        self.token: str | None = None

    def call(self, method: str, path: str, body: object = None, *, auth: str = "token") -> object:
        headers = {"content-type": "application/json"}
        if auth == "token" and self.token:
            headers["authorization"] = f"Bearer {self.token}"
        if auth == "session" and self.cookie:
            headers["cookie"] = self.cookie
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage]
            self.url + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # ruff: ignore[suspicious-url-open-usage]
                if auth == "session" and (cookie := response.headers.get("set-cookie")):
                    self.cookie = cookie.split(";", 1)[0]
                raw = response.read()
        except urllib.error.HTTPError as exc:
            sys.exit(f"{method} {path}: {exc.code} {exc.read().decode(errors='replace')}")
        return json.loads(raw) if raw else None

    def get(self, path: str) -> object:
        return self.call("GET", path)


def wait_healthy(api: Api, server: subprocess.Popen[bytes]) -> dict:
    """Wait until the server is ready (its database answers), then return its health details."""
    for _ in range(240):
        if server.poll() is not None:
            sys.exit(f"the server exited early with {server.returncode}")
        # Liveness answers before the database does; only readiness means it can serve.
        if _ready(api.url):
            with (
                contextlib.suppress(OSError, ValueError),
                urllib.request.urlopen(f"{api.url}/api/health", timeout=2) as response,  # ruff: ignore[suspicious-url-open-usage]
            ):
                health = json.load(response)
                # Releases before the probes have no `database_reachable` (they 500 until ready).
                if health.get("database_reachable", True):
                    return health
        time.sleep(0.5)
    sys.exit("the server did not become healthy in 120 s")


def _ready(url: str) -> bool:
    """Ask /readyz; a release from before the probes (404) is ready once /api/health answers."""
    try:
        with urllib.request.urlopen(f"{url}/readyz", timeout=3):  # ruff: ignore[suspicious-url-open-usage]
            return True
    except urllib.error.HTTPError as exc:
        return exc.code == HTTPStatus.NOT_FOUND
    except OSError:  # unreachable, refused, timed out (a URLError)
        return False


@contextlib.contextmanager
def running(cmd: list[str], env: dict[str, str], api: Api) -> Generator[dict]:
    port = api.url.rsplit(":", 1)[1]
    server = subprocess.Popen([*cmd, "serve", "--port", port], env=env)
    try:
        yield wait_healthy(api, server)
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()


def search(api: Api, ref: str, query: str) -> object:
    return api.get(f"/api/v1/libraries{LIBRARY}/search?ref={ref}&q={query}")


def served(api: Api) -> dict[str, object]:
    """Return what a client sees: the library, each version's articles, an article, searches."""
    seen: dict[str, object] = {"libraries": api.get("/api/v1/libraries")}
    for ref in REFS:
        seen[f"articles {ref}"] = api.get(f"/api/v1/libraries{LIBRARY}/articles?ref={ref}")
        seen[f"article {ref}"] = api.get(
            f"/api/v1/libraries{LIBRARY}/article?ref={ref}&path=docs/reference/naming.md"
        )
        for query in QUERIES:
            seen[f"search {ref} {query}"] = search(api, ref, query)
    return seen


NOT_STORED = frozenset({"notice"})
"""Fields that are this build's fixed wording, not data the instance stored: a release may
reword the untrusted-content notice (#98 added its model-output clause)."""


def differences(old: object, new: object, where: str = "") -> list[str]:
    """List where ``new`` changed a value ``old`` had.

    Keys only one side has are not compared, nor the fixed wording in ``NOT_STORED``.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        return [
            d
            for k in (old.keys() & new.keys()) - NOT_STORED
            for d in differences(old[k], new[k], f"{where}.{k}")
        ]
    if isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            return [f"{where}: {len(old)} items before, {len(new)} after"]
        return [
            d
            for i, (a, b) in enumerate(zip(old, new, strict=True))
            for d in differences(a, b, f"{where}[{i}]")
        ]
    return [] if old == new else [f"{where}: {old!r} -> {new!r}"]


def import_fixture(api: Api, repository: str) -> None:
    creds = {"username": "upgrade", "password": "upgrade check password"}
    api.call("POST", "/api/v1/setup", creds, auth="none")
    api.call("POST", "/api/v1/session", creds, auth="session")
    api.token = api.call("POST", "/api/v1/tokens", {"name": "upgrade"}, auth="session")["token"]
    job = api.call(
        "POST",
        "/api/v1/libraries",
        {"url": repository, "ref": REFS[0], "include_paths": ["docs/"]},
        auth="session",
    )["job_id"]
    wait_job(api, job)
    job = api.call(
        "POST", f"/api/v1/libraries{LIBRARY}/versions", {"ref": REFS[1]}, auth="session"
    )["job_id"]
    wait_job(api, job)


def wait_job(api: Api, job: str) -> None:
    for _ in range(240):
        state = api.call("GET", f"/api/v1/jobs/{job}", auth="session")
        if state["state"] not in {"queued", "running"}:
            break
        time.sleep(0.5)
    if state["state"] != "succeeded":
        sys.exit(f"import job ended as {state['state']!r}: {state}")


def wheel_version(wheels: Path) -> str:
    [wheel] = wheels.glob("exactdocs-[0-9]*.whl")
    return wheel.name.split("-")[1]


def commands(wheels: Path | None, previous: str) -> tuple[list[str], list[str]]:
    """Return the previous release's command and this build's."""
    old = ["uvx", "--from", f"exactdocs=={previous}", "exactdocs"]
    if not wheels:
        return old, ["uv", "run", "--project", str(ROOT), "exactdocs"]
    return old, [
        "uvx",
        "--prerelease=allow",
        "--find-links",
        str(wheels.resolve()),
        "--from",
        f"exactdocs=={wheel_version(wheels)}",
        "exactdocs",
    ]


def checkout_head() -> str:
    """Return the Alembic head of this checkout, not of the build under test.

    A stale build would agree with its own head, so the migration check could not fail.
    """
    return subprocess.run(
        ["uv", "run", "--project", str(ROOT), "python", "-c", HEAD],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def check_reindex(api: Api, cmd: list[str], env: dict[str, str]) -> None:
    """Run ``exactdocs reindex`` while searching; every answer must stay the same."""
    expected = search(api, REFS[1], QUERIES[1])
    reindex = subprocess.Popen([*cmd, "reindex"], env=env, stdout=subprocess.PIPE, text=True)
    answered = 0
    while reindex.poll() is None:
        if differences(expected, search(api, REFS[1], QUERIES[1])):
            sys.exit("a search during the reindex answered differently")
        answered += 1
    out, _ = reindex.communicate()
    print(out.strip(), f"({answered} searches answered meanwhile)")
    if reindex.returncode or differences(expected, search(api, REFS[1], QUERIES[1])):
        sys.exit(f"reindex failed ({reindex.returncode}) or changed the answer")
    # null means the server could not tell (liveness gives the database ~0.3 s): ask again, and
    # never take it for a pass.
    health = api.call("GET", "/api/health", auth="none")
    for _ in range(HEALTH_RETRIES):
        if health["reindex_required"] is not None:
            break
        time.sleep(1)
        health = api.call("GET", "/api/health", auth="none")
    if health["reindex_required"] is not False:
        sys.exit(f"the health check still asks for a reindex, or cannot tell: {health}")


def main() -> int:
    """Run the check; exit non-zero with the reason at the first difference."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheels", type=Path)
    parser.add_argument(
        "--previous", help="release to upgrade from (default: newest on PyPI below this build)"
    )
    parser.add_argument("--head", help="Alembic head to expect (default: this checkout's)")
    parser.add_argument("--print-head", action="store_true", help="print this checkout's head")
    args = parser.parse_args()
    if args.print_head:
        print(checkout_head())
        return 0
    previous = args.previous or previous_release(this_version(args.wheels))
    if previous is None:
        print("no stable release older than this build on PyPI: nothing to upgrade from, skipped")
        return 0
    old_cmd, new_cmd = commands(args.wheels, previous)
    head = args.head or checkout_head()
    api = Api(f"http://127.0.0.1:{free_port()}")
    with (
        tempfile.TemporaryDirectory(prefix="exactdocs-upgrade-") as tmp,
        fixture_repo.served(Path(tmp) / "git") as docs,
    ):
        env = {**os.environ, "EXACTDOCS_DATA_DIR": f"{tmp}/data"}
        env.pop("EXACTDOCS_DATABASE_URL", None)

        step(f"exactdocs {previous} (PyPI): import {LIBRARY} at {', '.join(REFS)}")
        with running(old_cmd, env, api) as health:
            old_revision = health["schema_revision"]
            import_fixture(api, docs.http_url)
            before = served(api)

        step(f"this build on the same data directory (schema {old_revision} -> {head})")
        with running(new_cmd, env, api) as health:
            if health.get("schema_revision") != head:
                sys.exit(f"not migrated to this checkout's head {head}: {health}")
            if "search_index_format" not in health:
                sys.exit(f"the server is not this build (no search_index_format): {health}")
            if changed := differences(before, served(api)):
                sys.exit("served differently after the upgrade:\n  " + "\n  ".join(changed))
            print(f"served unchanged: {len(before)} answers compared")

            step("exactdocs reindex while the server answers")
            check_reindex(api, new_cmd, env)
    print(f"upgrade {previous} -> this build OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
