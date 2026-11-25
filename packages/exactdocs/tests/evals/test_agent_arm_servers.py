"""The context7 and grounded-docs arms with their real servers, on stand-in data (#495).

Integration tests (``--integration -m eval``, never in CI): each installs a pinned npm release
(Node.js and the npm registry are needed) and runs the stand-in agents through it.

- ``context7``: the official Context7 MCP server, pointed by ``CONTEXT7_API_URL`` at a stand-in
  of Context7's REST API on loopback, so nothing reaches Context7.
- ``grounded-docs``: Grounded Docs indexes a two-version corpus built in a temporary repository
  into a temporary home, and its read-only server answers the agents.

    uv run pytest --integration -m eval packages/exactdocs/tests/evals/test_agent_arm_servers.py
"""

import contextlib
import json
import shutil
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic_evals import Case

import integration
from agent_bench.arms import CONTEXT7_TOOLS, GROUNDED_DOCS_TOOLS, parse_arms
from agent_bench.cli import run_bench
from agent_bench.harness import RetrievalConfig
from agent_bench.offline import OFFLINE_AGENTS, OFFLINE_JUDGE
from agent_bench.servers import CONTEXT7_VERSION
from agent_bench_stand_ins import CHUNKS, LIBRARY, golden
from fixture_repo import git
from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.golden import Corpus, GoldenCase, PinnedVersion, Project, fetch
from retrieval_eval.grounded_docs import VERSION
from retrieval_eval.grounded_docs_cli import home_dir

pytestmark = [
    integration.needs(),
    pytest.mark.eval,
    pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js 22 (node on PATH)"),
]

KEY = "ctx7sk-stand-in-not-a-real-key"
"""The API key the arm hands the Context7 server; the stand-in API checks it arrives."""
BM25 = [RetrievalConfig.parse("bm25:mode=bm25")]
"""The exactdocs arm's configuration (not run here)."""


SEEN: list[tuple[str, str]] = []
"""Each request the stand-in API answered: its path and its ``Authorization`` header."""


class _Context7Api(BaseHTTPRequestHandler):
    """Context7's REST API as its MCP server calls it: ``/v2/libs/search`` and ``/v2/context``."""

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        SEEN.append((url.path, self.headers.get("Authorization", "")))
        if url.path == "/v2/libs/search":
            result = {
                "id": LIBRARY,
                "title": "Demo",
                "description": "The demo package.",
                "totalSnippets": 2,
                "trustScore": 9,
                "versions": ["v1", "v2"],
            }
            self._send("application/json", json.dumps({"results": [result]}))
            return
        version = query.get("libraryId", "").removeprefix(LIBRARY).strip("/") or "v2"
        words = {w.lower() for w in query.get("query", "").split() if len(w) > 3}
        found = [
            f"### {' > '.join(c['heading_path'])}\nSource: https://example.com/{c['article_path']}"
            f"\n\n{c['content']}"
            for c in CHUNKS
            if c["version"] == version and words & set(c["content"].lower().split())
        ]
        self._send("text/plain", "\n\n--------------------------------\n\n".join(found))

    def _send(self, kind: str, body: str) -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # ruff: ignore[builtin-argument-shadowing] - the base class's name
        del format, args


@contextlib.contextmanager
def _context7_api() -> Generator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Context7Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


async def test_the_official_context7_server_answers_the_context7_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus, cases = golden()
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)  # its proxy agent ignores NO_PROXY
    monkeypatch.setenv("CONTEXT7_API_KEY", KEY)
    SEEN.clear()
    with _context7_api() as api:
        monkeypatch.setenv("CONTEXT7_API_URL", api)
        report = await run_bench(
            cases,
            corpus,
            {},
            agent_models=OFFLINE_AGENTS,
            judge_model=OFFLINE_JUDGE,
            arms=parse_arms(["context7"]),
            retrieval=BM25,
            work_dir=tmp_path,
        )

    about = report.meta.servers["context7"]
    assert about["server"] == f"@upstash/context7-mcp {CONTEXT7_VERSION} (stdio)"
    assert (about["api"], about["tools"]) == (api, ", ".join(sorted(CONTEXT7_TOOLS)))
    for row in report.questions:
        assert [c.name for c in row.tool_calls] == ["resolve-library-id", "query-docs"], row
        assert all(c.error is None for c in row.tool_calls), row
        assert row.grade == ("refused" if row.kind == "unanswerable" else "correct"), row
    assert {path for path, _ in SEEN} == {"/v2/libs/search", "/v2/context"}
    assert {auth for _, auth in SEEN} == {f"Bearer {KEY}"}  # the key reached it
    assert KEY not in report.model_dump_json()


GUIDE_V1 = "# Guide\n\n## Install\n\nInstall the package with `pip install demo`, then import it.\n"
START_V2 = "# Guide\n\n## Setup\n\nInstall the package with `uv add demo`; pip is gone.\n"


def _commit(repo: Path, tag: str, files: dict[str, str], delete: tuple[str, ...] = ()) -> str:
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    for path in delete:
        (repo / path).unlink()
    git("add", "-A", cwd=repo)
    author = {"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.com"}
    committer = {"GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.com"}
    git("commit", "-q", "--no-verify", "-m", tag, cwd=repo, **author, **committer)
    git("tag", tag, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def _case(name: str, version: str, kind: str, hits: list[Hit], facts: list[str]) -> GoldenCase:
    return Case(
        name=name,
        inputs=Question(query=name.split(": ", 1)[1], version=version, project="demo"),
        metadata=CaseInfo(kind=kind),  # ty: ignore[invalid-argument-type]
        expected_output=Answer(hits=hits, reference=f"reference of {name}", facts=facts),
    )


async def test_grounded_docs_answers_the_grounded_docs_arm_from_its_own_index(
    tmp_path: Path,
) -> None:
    upstream = tmp_path / "acme" / "demo"
    upstream.mkdir(parents=True)
    git("init", "-q", "-b", "main", "--template=", str(upstream))
    v1 = _commit(upstream, "v1", {"docs/guide.md": GUIDE_V1})
    v2 = _commit(upstream, "v2", {"docs/start.md": START_V2}, delete=("docs/guide.md",))
    project = Project(
        id="demo",
        title="Demo",
        repository=str(upstream),
        include=["docs/"],
        licence="MIT",
        attribution="Copyright (c) A",
        versions=[PinnedVersion(name="v1", commit=v1), PinnedVersion(name="v2", commit=v2)],
    )
    corpus = Corpus(projects=[project])
    repos = {"demo": fetch(project, tmp_path / "cache")}
    install = Hit(version="v1", article="docs/guide.md", heading_path=["Guide", "Install"])
    setup = Hit(version="v2", article="docs/start.md", heading_path=["Guide", "Setup"])
    cases = [
        _case("demo v1: How do I install the package?", "v1", "how-to", [install], ["pip install"]),
        _case("demo v2: How do I install the package?", "v2", "how-to", [setup], ["uv add demo"]),
    ]
    home = tmp_path / "grounded-docs"
    if (installed := home_dir() / VERSION).exists():  # the release `just grounded-bench` installed
        home.mkdir()
        (home / VERSION).symlink_to(installed, target_is_directory=True)

    report = await run_bench(
        [("demo", c) for c in cases],
        corpus,
        repos,
        agent_models=OFFLINE_AGENTS,
        judge_model=OFFLINE_JUDGE,
        arms=parse_arms(["grounded-docs"]),
        retrieval=BM25,
        work_dir=tmp_path / "work",
        grounded_home=home,
    )

    about = report.meta.servers["grounded-docs (full-text)"]
    assert about["tools"] == ", ".join(sorted(GROUNDED_DOCS_TOOLS))  # no fetch_url, no indexing
    assert about["indexed"].startswith("2 pinned versions")
    for row in report.questions:
        names = [c.name for c in row.tool_calls]
        assert names[:2] == ["list_libraries", "search_docs"], row
        assert row.grade == "correct", row
        if row.agent_model == "offline:search":
            assert (names, row.grounded) == (["list_libraries", "search_docs"], False), row
        else:
            assert names[2:] == ["read_page"], row
            assert row.grounded is True, row  # the whole page of the asked version
            assert row.other_versions_read == []
