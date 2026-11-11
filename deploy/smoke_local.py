"""Hybrid search and reranking in the `-local` image with no network at all (#246).

Runs inside the container, in the image's own Python (stdlib only), against the server on its
loopback: the container is started with `--network none`, so nothing but the models baked into
the image can answer. Start it with the default local models on the roles, then:

    docker exec -i exactdocs-local python - \
        file:///fixture/docs-repo /fixture/docs-repo v1.3.0 < deploy/smoke_local.py

It sets up the instance, imports the fixture repository, waits for the version to be embedded
and searches it: the answer must come from `hybrid` with `reranked: true`. Exits non-zero
otherwise. Needs a fresh instance (no admin yet).
"""

import http
import http.client
import json
import sys
import time
import urllib.parse

HOST, PORT = "127.0.0.1", 3000
CREDENTIALS = {"username": "ci", "password": "ci smoke test password"}
QUERY = "how do I authenticate with a token"
EMBEDDING_WAIT = 300  # seconds: the version's chunks are embedded on the CPU
cookies: dict[str, str] = {}
"""The session cookie, once signed in."""


def call(path: str, body: dict | None = None, token: str | None = None) -> dict:
    """Send one request to the server.

    Args:
        path: The path under the server, with its query.
        body: A JSON body (POST), or None (GET).
        token: An API token for `Authorization: Bearer`.

    Returns:
        The JSON answer.

    Raises:
        OSError: The server did not answer, or answered with an error status.
    """
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    if cookies:
        headers["cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    connection = http.client.HTTPConnection(HOST, PORT, timeout=30)
    try:
        data = None if body is None else json.dumps(body)
        connection.request("GET" if body is None else "POST", path, data, headers)
        answer = connection.getresponse()
        payload = answer.read()
        for header in answer.headers.get_all("set-cookie") or []:
            name, _, value = header.split(";", 1)[0].partition("=")
            cookies[name.strip()] = value.strip()
    finally:
        connection.close()
    if answer.status >= http.HTTPStatus.BAD_REQUEST:
        message = f"{path}: HTTP {answer.status} {payload[:300]!r}"
        raise OSError(message)
    return json.loads(payload or b"{}")


def step(text: str) -> None:
    """Log a step."""
    sys.stdout.write(f"--- {text}\n")
    sys.stdout.flush()


def wait_ready() -> None:
    """Wait until the server's database answers."""
    for _ in range(120):
        try:
            if call("/readyz").get("status") == "ready":
                return
        except OSError:  # not listening yet, or not ready (503)
            pass
        time.sleep(1)
    sys.exit("server did not get ready")


def main(repository: str, library: str, ref: str) -> None:
    """Import the fixture and search it in hybrid mode, reranked.

    Args:
        repository: The fixture repository's URL (file://, inside the container).
        library: Its library ID, with the leading slash.
        ref: The version to import and search.
    """
    step("wait for the server")
    wait_ready()

    step("setup, sign in, token")
    call("/api/v1/setup", CREDENTIALS)
    call("/api/v1/session", CREDENTIALS)
    token = call("/api/v1/tokens", {"name": "ci"})["token"]

    step("import the fixture repository")
    job = call("/api/v1/libraries", {"url": repository, "ref": ref, "include_paths": ["docs/"]})[
        "job_id"
    ]
    for _ in range(120):
        state = call(f"/api/v1/jobs/{job}")["state"]
        if state not in {"queued", "running"}:
            break
        time.sleep(1)
    if state != "succeeded":
        sys.exit(f"import ended as {state!r}: {call(f'/api/v1/jobs/{job}')}")

    step("search in hybrid mode once the version is embedded")
    query = urllib.parse.urlencode({"ref": ref, "q": QUERY, "mode": "hybrid"})
    deadline = time.monotonic() + EMBEDDING_WAIT
    while True:
        found = call(f"/api/v1/libraries{library}/search?{query}", token=token)
        fallback = found.get("fallback_reason")
        if fallback != "embedding_in_progress" or time.monotonic() > deadline:
            break
        time.sleep(2)
    summary = {k: found.get(k) for k in ("retrieval_mode", "reranked", "fallback_reason")}
    sys.stdout.write(f"{json.dumps(summary)}, {len(found.get('results', []))} results\n")
    if found.get("retrieval_mode") != "hybrid" or fallback is not None:
        sys.exit(f"expected retrieval mode 'hybrid' with no fallback, got {summary}")
    if found.get("reranked") is not True:
        sys.exit(f"expected reranked: true, got {summary}")
    if not found.get("results"):
        sys.exit("hybrid search found nothing")
    sys.stdout.write("local models smoke OK: hybrid, reranked, no network\n")


if __name__ == "__main__":
    match sys.argv[1:]:
        case [repository, library, ref]:
            main(repository, library, ref)
        case _:
            sys.exit("usage: smoke_local.py REPOSITORY_URL LIBRARY_ID REF")
