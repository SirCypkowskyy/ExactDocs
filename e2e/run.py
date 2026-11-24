"""Run the browser test against a real server and the fixture HTTP git server.

    python3 run.py [--wheels DIR]

With --wheels (a directory holding the exactdocs and exactdocs-kernel wheels) the server is
`uvx --find-links DIR --from exactdocs==<version> exactdocs serve`; without it,
`uv run exactdocs serve` from the checkout, which needs the web UI built into the package.
Everything it starts (server, git server, data directory) is gone when it exits.
`screenshots.py` starts its server with `exactdocs()` too.
"""

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Generator, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/exactdocs/tests/fixtures"))
import fixture_repo  # ruff: ignore[module-import-not-at-top-of-file]  (test support next to the package, not installed)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(url: str, server: subprocess.Popen[bytes]) -> None:
    for _ in range(120):
        if server.poll() is not None:
            sys.exit(f"the server exited early with {server.returncode}")
        with contextlib.suppress(OSError):
            urllib.request.urlopen(f"{url}/api/health", timeout=2)  # ruff: ignore[suspicious-url-open-usage]
            return
        time.sleep(0.5)
    sys.exit("the server did not become healthy in 60 s")


def server_command(wheels: Path | None = None) -> list[str]:
    """The command that runs `exactdocs`.

    Returns:
        `exactdocs` from the checkout, or from the wheels in `wheels` through uvx.
    """
    if not wheels:
        return ["uv", "run", "--project", str(ROOT), "exactdocs"]
    [wheel] = wheels.glob("exactdocs-[0-9]*.whl")
    version = wheel.name.split("-")[1]
    return [
        "uvx",
        "--prerelease=allow",
        "--find-links",
        str(wheels.resolve()),
        "--from",
        f"exactdocs=={version}",
        "exactdocs",
    ]


@contextlib.contextmanager
def exactdocs(
    cmd: list[str], data_dir: Path, env: Mapping[str, str] | None = None
) -> Generator[str]:
    """Serve ExactDocs on a free port with `data_dir` until the block ends.

    Yields:
        Its URL, once it answers its health check.
    """
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    server_env = {**(os.environ if env is None else env), "EXACTDOCS_DATA_DIR": str(data_dir)}
    server_env.pop("EXACTDOCS_DATABASE_URL", None)
    server = subprocess.Popen([*cmd, "serve", "--port", str(port)], env=server_env)  # ruff: ignore[subprocess-without-shell-equals-true]
    try:
        wait_healthy(url, server)
        yield url
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()


def playwright(args: list[str], env: Mapping[str, str]) -> int:
    """Run `playwright test` in this directory.

    Returns:
        Its exit code.
    """
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        ["pnpm", "exec", "playwright", "test", *args],  # ruff: ignore[start-process-with-partial-path]
        env=env,
        cwd=Path(__file__).parent,
        check=False,
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheels", type=Path)
    parser.add_argument("playwright_args", nargs="*")
    args = parser.parse_args()
    with (
        tempfile.TemporaryDirectory(prefix="exactdocs-e2e-") as tmp,
        fixture_repo.served(Path(tmp) / "git") as docs,
        exactdocs(server_command(args.wheels), Path(tmp) / "data") as url,
    ):
        env = {**os.environ, "EXACTDOCS_URL": url, "FIXTURE_REPO_URL": docs.http_url}
        return playwright(args.playwright_args, env)


if __name__ == "__main__":
    sys.exit(main())
