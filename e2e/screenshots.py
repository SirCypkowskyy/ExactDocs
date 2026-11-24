"""Take the screenshots of the README and the documentation from the real UI: `just screenshots`.

    uv run python e2e/screenshots.py [playwright args]

It starts ExactDocs from the checkout (the web UI built into the package, as `just e2e` does) on
a new data directory and seeds it through the REST API and MCP with fictional data only:

- the fixture docs repository (`packages/exactdocs/tests/fixtures/docs-repo`, "Acme Payments") at
  v1.4.0, v1.3.0 and `next`, and the fixture Sphinx docs (`sphinx-docs`, "Acme Store"), served
  by `git http-backend` as if from `git.example.com`;
- a stand-in model gateway on `models.example.com` (`tests/fixtures/fake_llm.py`) that embeds by
  hashing terms, so hybrid search and the AI page have something to show without a model;
- an admin and two users, and an API token that makes the MCP calls of the `mcp` figure.

Both hosts are answered by a proxy in this process: the server's proxy settings point to it, and
it refuses every other host, so nothing leaves the machine. Then `screenshots.ts` takes every
picture in Playwright, light and dark, and they are written as WebP to docs/assets/screenshots/.
The fixture's commits are fixed, so the same checkout gives the same pictures.
"""

import contextlib
import http.client
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "packages/exactdocs/tests/fixtures"
sys.path.insert(0, str(FIXTURES))
sys.path.insert(0, str(Path(__file__).parent))
import fake_llm  # ruff: ignore[module-import-not-at-top-of-file]  (test support, not installed)
import fixture_repo  # ruff: ignore[module-import-not-at-top-of-file]
import run  # ruff: ignore[module-import-not-at-top-of-file]  (e2e/run.py: starts the server)

OUT = ROOT / "docs/assets/screenshots"
SHOTS = Path(__file__).parent / "shots/screenshots"
GIT_HOST = "git.example.com"
MODELS_HOST = "models.example.com"
ADMIN = "maya"
USERS = ("theo", "priya")
PASSWORD = "a demo passphrase, not a real one"  # ruff: ignore[hardcoded-password-string]
QUESTION = "How do I start the sandbox with Docker?"
AUTHOR = {"GIT_AUTHOR_NAME": "Fixture Author", "GIT_AUTHOR_EMAIL": "fixture@exactdocs.invalid"}
STORE_DATE = "2025-05-12T10:00:00+00:00"
# Where the pictures show times, they show them as if seeded at this moment (screenshots.ts).
SEEDED_AT = "2026-11-02T09:00:00Z"
WEBP = {"format": "WEBP", "quality": 88, "method": 6}
"""Lossy at a quality where text stays sharp; method 6 is libwebp's slowest and smallest."""

# Hop-by-hop headers, and the ones http.server writes itself.
_SKIPPED = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "content-length"}
_SKIPPED_BACK = _SKIPPED | {"server", "date"}


def _store_repo(dest: Path) -> None:
    """A git repository of the fixture Sphinx docs, one commit tagged v2.1.0 (a fixed SHA)."""
    shutil.copytree(FIXTURES / "sphinx-docs" / "doc", dest / "doc")
    fixture_repo.git("init", "-q", "-b", "main", "--template=", str(dest))
    fixture_repo.git("config", "uploadpack.allowFilter", "true", cwd=dest)
    fixture_repo.git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=dest)
    fixture_repo.git("add", "-A", cwd=dest)
    dates = {"GIT_AUTHOR_DATE": STORE_DATE, "GIT_COMMITTER_DATE": STORE_DATE}
    committer = {"GIT_COMMITTER_NAME": AUTHOR["GIT_AUTHOR_NAME"]}
    committer["GIT_COMMITTER_EMAIL"] = AUTHOR["GIT_AUTHOR_EMAIL"]
    fixture_repo.git(
        "commit", "-q", "--no-verify", "-m", "docs: Acme Store 2.1.0", cwd=dest,
        **AUTHOR, **committer, **dates,
    )  # fmt: skip
    fixture_repo.git("tag", "v2.1.0", cwd=dest)


def _proxy(routes: dict[str, tuple[str, int]]) -> type[http.server.BaseHTTPRequestHandler]:
    """A forward proxy that sends each fictional host to the local server standing in for it."""

    class Proxy(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._forward()

        def do_POST(self) -> None:
            self._forward()

        def do_CONNECT(self) -> None:
            self.send_error(403, "only the fictional hosts of the screenshots are reachable")

        def _forward(self) -> None:
            url = urlsplit(self.path)
            target = routes.get(url.hostname or "")
            if target is None:
                self.send_error(403, "only the fictional hosts of the screenshots are reachable")
                return
            if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                body = b""
                while size := int(self.rfile.readline().split(b";")[0], 16):
                    body += self.rfile.read(size)
                    self.rfile.readline()
                self.rfile.readline()
            else:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in _SKIPPED}
            upstream = http.client.HTTPConnection(*target, timeout=120)
            try:
                path = url.path + (f"?{url.query}" if url.query else "")
                upstream.request(self.command, path, body=body, headers=headers)
                response = upstream.getresponse()
                payload = response.read()
            finally:
                upstream.close()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in _SKIPPED_BACK:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:  # ruff: ignore[builtin-argument-shadowing]
            """Stay quiet."""

    return Proxy


@contextlib.contextmanager
def _serving(handler: type[http.server.BaseHTTPRequestHandler]) -> Generator[int]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _server_env(tmp: Path, proxy: str) -> dict[str, str]:
    """The server's environment: git through the proxy, the gateway as the only AI provider."""
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    env = {k: v for k, v in env.items() if not k.startswith("EXACTDOCS_")}
    config = tmp / "exactdocs.toml"
    config.write_text(
        f"""
[ai.providers.gateway]
kind = "openai-compatible"
base_url = "http://{MODELS_HOST}/v1"
proxy = "{proxy}"

[ai.embedding]
model = "gateway:demo-embedding"
dimensions = {fake_llm.TERM_DIMENSIONS}

[ai.prices."gateway:demo-embedding"]
input_usd_per_mtok = 0.02
""",
        encoding="utf-8",
    )
    return {
        **env,
        "EXACTDOCS_CONFIG_FILE": str(config),
        "EXACTDOCS_AI__PROVIDERS__GATEWAY__API_KEY": "not-a-real-key",
        # git reads these; anything else that tries the network meets the same proxy
        **{name: proxy for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")},
        "no_proxy": "localhost,127.0.0.1",
        "NO_PROXY": "localhost,127.0.0.1",
    }


def _wait_for_job(api: httpx.Client, job_id: str) -> None:
    for _ in range(600):
        job = api.get(f"/api/v1/jobs/{job_id}").raise_for_status().json()
        if job["state"] == "succeeded":
            return
        if job["state"] in {"failed", "cancelled"}:
            sys.exit(f"import job {job_id} ended {job['state']}: {job.get('error')}")
        time.sleep(0.25)
    sys.exit(f"import job {job_id} did not finish in time")


def _wait_for_embeddings(api: httpx.Client) -> None:
    for _ in range(600):
        jobs = api.get("/api/v1/jobs", params={"limit": 100}).raise_for_status().json()
        if all(job["state"] in {"succeeded", "failed", "cancelled"} for job in jobs["jobs"]):
            return
        time.sleep(0.25)
    sys.exit("the embedding jobs did not finish in time")


def _add(api: httpx.Client, library: str, url: str, refs: list[str]) -> None:
    first, *others = refs
    added = api.post("/api/v1/libraries", json={"url": url, "library_id": library, "ref": first})
    _wait_for_job(api, added.raise_for_status().json()["job_id"])
    for ref in others:
        version = api.post(f"/api/v1/libraries{library}/versions", json={"ref": ref})
        _wait_for_job(api, version.raise_for_status().json()["job_id"])


async def _ask(url: str, token: str) -> list[dict[str, str]]:
    """The `query-docs` replies to one question at v1.3.0 and v1.4.0 of Acme Payments."""

    def factory(**options: object) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(trust_env=False, **options)  # ty: ignore[invalid-argument-type]

    transport = StreamableHttpTransport(
        f"{url}/mcp", auth=token, httpx_client_factory=factory
    )
    replies = []
    async with Client(transport) as client:
        for version in ("v1.3.0", "v1.4.0"):
            library = f"/acme/payments/{version}"
            result = await client.call_tool(
                "query-docs", {"libraryId": library, "query": QUESTION}
            )
            texts = [block.text for block in result.content if block.type == "text"]
            replies.append(
                {"library": library, "version": version, "query": QUESTION, "texts": texts}
            )
    return replies


def seed(url: str, shots: Path) -> dict[str, str]:
    """Fill the instance with the fictional data the pictures show; return what Playwright needs."""
    started = datetime.now(UTC)
    with httpx.Client(base_url=url, trust_env=False, timeout=60) as api:
        admin = {"username": ADMIN, "password": PASSWORD}
        api.post("/api/v1/setup", json=admin).raise_for_status()
        api.post("/api/v1/session", json=admin).raise_for_status()  # the client keeps the cookie
        token = api.post("/api/v1/tokens", json={"name": "Claude Code"}).raise_for_status().json()
        for name in USERS:
            user = {"username": name, "password": PASSWORD, "role": "user"}
            api.post("/api/v1/users", json=user).raise_for_status()
        _add(api, "/acme/payments", f"http://{GIT_HOST}/acme/payments.git", ["v1.4.0", "v1.3.0", "next"])
        _add(api, "/acme/store", f"http://{GIT_HOST}/acme/store.git", ["v2.1.0"])
        api.patch("/api/v1/libraries/acme/store", json={"title": "Acme Store"}).raise_for_status()
        grant = {"kind": "user", "subject": USERS[0], "role": "viewer"}
        api.put("/api/v1/libraries/acme/payments/grants", json=grant).raise_for_status()
        cursor = {
            "name": "Cursor",
            "library_ids": ["/acme/payments"],
            "expires_at": (started + timedelta(days=90)).isoformat(),
        }
        api.post("/api/v1/tokens", json=cursor).raise_for_status()
        _wait_for_embeddings(api)
    import asyncio  # ruff: ignore[import-outside-top-level]

    replies = asyncio.run(_ask(url, token["token"]))
    (shots / "mcp.json").write_text(json.dumps(replies, indent=2), encoding="utf-8")
    return {
        "SHOTS_USER": ADMIN,
        "SHOTS_PASSWORD": PASSWORD,
        "SHOTS_STARTED_AT": started.isoformat(),
        "SHOTS_SEEDED_AT": SEEDED_AT,
        "SHOTS_MCP": str(shots / "mcp.json"),
    }


def to_webp(shots: Path, out: Path) -> list[Path]:
    """Write every PNG of `shots` to `out` as WebP; return the files written."""
    written = []
    for png in sorted(shots.glob("*.png")):
        target = out / f"{png.stem}.webp"
        with Image.open(png) as image:
            image.convert("RGB").save(target, **WEBP)
        written.append(target)
    return written


def main() -> int:
    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="exactdocs-screenshots-") as name:
        tmp = Path(name)
        fixture_repo.build(tmp / "git/acme/payments")
        _store_repo(tmp / "git/acme/store")
        with (
            fixture_repo.serve_copy(tmp / "git", token=None) as git,
            fake_llm.gateway(by_terms=True) as gateway,
        ):
            git_port = urlsplit(git.url).port
            gateway_port = urlsplit(gateway.url).port
            assert git_port and gateway_port  # ruff: ignore[assert]
            routes = {GIT_HOST: ("127.0.0.1", git_port), MODELS_HOST: ("127.0.0.1", gateway_port)}
            with _serving(_proxy(routes)) as proxy_port:
                server_env = _server_env(tmp, f"http://127.0.0.1:{proxy_port}")
                with run.exactdocs(run.server_command(), tmp / "data", server_env) as url:
                    env = {**os.environ, "EXACTDOCS_URL": url, **seed(url, SHOTS)}
                    args = ["--config", "screenshots.config.ts", *sys.argv[1:]]
                    if code := run.playwright(args, env):
                        return code
    OUT.mkdir(parents=True, exist_ok=True)
    for path in to_webp(SHOTS, OUT):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KiB")  # ruff: ignore[print]
    return 0


if __name__ == "__main__":
    sys.exit(main())
