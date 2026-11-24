# ruff: file-ignore[suspicious-subprocess-import, subprocess-without-shell-equals-true]
"""The two sides of the behind-a-proxy integration test (#538), run inside its containers.

``python3 proxy_world.py serve <repos>``: the world behind the proxy (or behind ``NO_PROXY``), on
every address of its container: the repositories in ``<repos>`` over smart HTTP on 8001
(``fixture_repo``), the Hub stand-in on
8002 (``fake_hub``) and an OpenAI-compatible model gateway on 8003 (one minimal chat completion
and embedding). It is started once outside (reached only through the proxy) and once inside the
company network (reached only directly).

``python3 proxy_world.py drill``: ExactDocs, on a network whose only way out is the proxy, with
the outbound settings in its environment. It pulls a model from the Hub stand-in, checks two AI
profiles (one outside through the proxy, one inside through ``NO_PROXY``), checks once more with
wrong proxy credentials, starts ``exactdocs serve`` and imports the fixture repository from the
outside and from the inside over the REST API (on loopback, never proxied). It prints one JSON
object with what happened; the test reads it, and the proxy's log.

Standard library only (and the fixtures next to it): the containers run the checkout's own
virtual environment.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import fake_hub
import fixture_repo

GIT_PORT, HUB_PORT, LLM_PORT, SERVER_PORT = 8001, 8002, 8003, 3000
OUTSIDE_REPOSITORY = "outside/docs-repo"
"""The fixture repository's path on the git server behind the proxy."""
INSIDE_REPOSITORY = "corp/docs-repo"
"""Its path on the company's own git server, reached directly (``NO_PROXY``)."""
REF = "v1.3.0"


class _Gateway(BaseHTTPRequestHandler):
    """One chat completion (``OK``) and one embedding, as an OpenAI-compatible gateway answers."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        model = body.get("model", "m")
        if self.path.endswith("/embeddings"):
            answer: dict[str, Any] = {
                "object": "list",
                "model": model,
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
        else:
            answer = {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            }
        payload = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        del code, size


def serve(repos: Path) -> None:
    """Serve git, the Hub and the gateway on every address of the container until killed.

    Args:
        repos: The folder that holds the repositories (``<owner>/<name>``).
    """
    address = ""  # every interface: the container's network is the test's own
    servers = [
        ThreadingHTTPServer((address, GIT_PORT), fixture_repo.git_http_handler(repos)),
        ThreadingHTTPServer((address, HUB_PORT), fake_hub.handler(fake_hub.FakeHub())),
        ThreadingHTTPServer((address, LLM_PORT), _Gateway),
    ]
    for server in servers[1:]:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    servers[0].serve_forever()


def _exactdocs(*args: str, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).with_name("exactdocs")), *args],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
"""Talks to the server on loopback, never through a proxy."""


def _api(method: str, path: str, body: object = None, cookie: str = "") -> tuple[int, Any, str]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{SERVER_PORT}{path}", data=data, method=method
    )
    request.add_header("content-type", "application/json")
    if cookie:
        request.add_header("cookie", cookie)
    try:
        with _LOCAL.open(request, timeout=30) as answer:
            raw = answer.read()
            return answer.status, json.loads(raw or b"null"), answer.headers.get("set-cookie", "")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null"), ""


def _import(url: str, cookie: str) -> dict[str, Any]:
    status, body, _ = _api(
        "POST", "/api/v1/libraries", {"url": url, "ref": REF, "include_paths": ["docs/"]}, cookie
    )
    if status >= 300:
        return {"state": f"refused {status}", "detail": body}
    job = body["job_id"]
    for _ in range(240):
        _, state, _ = _api("GET", f"/api/v1/jobs/{job}", cookie=cookie)
        if state["state"] in {"succeeded", "failed", "cancelled"}:
            return {"state": state["state"], "detail": state.get("error")}
        time.sleep(0.5)
    return {"state": "timed out"}


def drill() -> None:
    """Exercise every outbound client behind the proxy and print what happened, as JSON."""
    found: dict[str, Any] = {}
    pulled = _exactdocs("models", "pull", "BAAI/bge-small-en-v1.5", env={})
    found["pull"] = {"code": pulled.returncode, "out": pulled.stdout + pulled.stderr}
    profiles = {
        "EXACTDOCS_AI__USE_INSTANCE_PROXY": "true",
        "EXACTDOCS_AI__PROVIDERS__OUTSIDE__KIND": "openai-compatible",
        "EXACTDOCS_AI__PROVIDERS__OUTSIDE__BASE_URL": f"http://llm.outside.test:{LLM_PORT}/v1",
        "EXACTDOCS_AI__PROVIDERS__CORP__KIND": "openai-compatible",
        "EXACTDOCS_AI__PROVIDERS__CORP__BASE_URL": os.environ["DRILL_CORP_GATEWAY"],
        "EXACTDOCS_AI__LLM__MODEL": "outside:m",
        "EXACTDOCS_AI__EMBEDDING__MODEL": "corp:e",
        "EXACTDOCS_DATA_DIR": "/data/ai",
    }
    checked = _exactdocs("ai", "check", env=profiles)
    found["ai"] = {"code": checked.returncode, "out": checked.stdout + checked.stderr}
    wrong = os.environ["DRILL_WRONG_PROXY"]
    refused = _exactdocs("ai", "check", env={**profiles, "EXACTDOCS_HTTP_PROXY": wrong})
    found["ai_wrong_credentials"] = {
        "code": refused.returncode,
        "out": refused.stdout + refused.stderr,
    }
    with Path("/data/serve.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [str(Path(sys.executable).with_name("exactdocs")), "serve"],
            env={**os.environ, "EXACTDOCS_DATA_DIR": "/data/server"},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        for _ in range(120):
            try:
                if _api("GET", "/readyz")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        credentials = {"username": "ada", "password": "correct horse battery staple"}
        _api("POST", "/api/v1/setup", credentials)
        _, _, cookie = _api("POST", "/api/v1/session", credentials)
        cookie = cookie.split(";", 1)[0]
        outside = f"http://git.outside.test:{GIT_PORT}/{OUTSIDE_REPOSITORY}.git"
        found["import_outside"] = _import(outside, cookie)
        inside = f"http://git.corp.test:{GIT_PORT}/{INSIDE_REPOSITORY}.git"
        found["import_inside"] = _import(inside, cookie)
    finally:
        server.terminate()
        server.wait(timeout=60)
    log = Path("/data/serve.log").read_text(encoding="utf-8", errors="replace")
    found["serve_log"] = log[-4000:]
    sys.stdout.write(json.dumps(found) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        serve(Path(sys.argv[2]))
    else:
        drill()
