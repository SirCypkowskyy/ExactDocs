"""Runs ExactDocs in a fresh interpreter behind a socket guard, with the AI SDKs' variables set.

Shared by ``tests/bootstrap/test_ai_no_outbound.py`` and the behave steps of #241. The guard
refuses, and records, every connection and name lookup that is not loopback; the SDKs' variables
point to a *trap* gateway on loopback (``fake_llm``), so a call that followed them is seen too.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent

SDK_VARIABLES = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_VERSION",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "CLOUD_ML_REGION",
    "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_FOUNDRY_RESOURCE",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "OPENROUTER_API_KEY",
    "OLLAMA_BASE_URL",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
]

GUARD = """
import json, os, socket, sys
sys.path.insert(0, {fixtures!r})
from fake_llm import gateway

blocked = []
LOOPBACK = {{"127.0.0.1", "::1", "localhost"}}

def _host(address):
    return address[0] if isinstance(address, tuple) else str(address)

for name in ("connect", "connect_ex"):
    real = getattr(socket.socket, name)
    def guarded(self, address, _real=real):
        if self.family in (socket.AF_INET, socket.AF_INET6) and _host(address) not in LOOPBACK:
            blocked.append(_host(address))
            raise OSError("refused by the test's socket guard")
        return _real(self, address)
    setattr(socket.socket, name, guarded)

real_getaddrinfo = socket.getaddrinfo
def getaddrinfo(host, *args, **kwargs):
    if host not in LOOPBACK and host is not None:
        blocked.append(str(host))
        raise socket.gaierror("refused by the test's socket guard")
    return real_getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = getaddrinfo

trap_context = gateway()
trap = trap_context.__enter__()
for variable in {variables!r}:
    if variable.endswith(("_BASE_URL", "_ENDPOINT")):
        os.environ[variable] = trap.v1
    else:
        os.environ[variable] = "from-the-environment"
"""

NOTHING_CONFIGURED = """
import asyncio
from fastapi.testclient import TestClient
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.dtos import QueryDocsQuery, SearchDocsQuery
from exactdocs.retrieval.errors import VersionNotIndexedError

with TestClient(create_app(Container.build(Settings())), base_url="http://localhost") as client:
    assert client.get("/api/health").status_code == 200

async def main():
    container = Container.build(Settings())
    async with container.running(jobs=False):
        for ask in (
            lambda: container.retrieval.search_docs(SearchDocsQuery(library="/a/b", query="x")),
            lambda: container.retrieval.query_docs(QueryDocsQuery(library_id="/a/b", query="x")),
        ):
            try:
                await ask()
            except VersionNotIndexedError:
                pass
        checks = await container.retrieval.check_roles()
        assert checks.checks == [], checks

asyncio.run(main())
print(json.dumps({"blocked": blocked, "trap": len(trap.seen), "modules": sorted(sys.modules)}))
"""

CONFIGURED = """
import asyncio
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.dtos import CheckProviderCommand

corp_context = gateway()
corp = corp_context.__enter__()

async def main():
    ai = AiSettings.model_validate({
        "providers": {
            "corp": {"kind": "openai-compatible", "base_url": corp.v1},
            "claude": {"kind": "anthropic", "base_url": corp.url, "api_key": "claude-key"},
        },
        "embedding": {"model": "corp:text-embedding-3-small"},
        "llm": {"model": "corp:gpt-4.1-mini"},
        "judge": {"model": "claude:claude-test"},
    })
    container = Container.build(Settings(ai=ai))
    async with container.running(jobs=False):
        only_chat = CheckProviderCommand(name="corp", role="llm", model="gpt-4.1-mini")
        chat = await container.retrieval.check_provider(only_chat)
        assert chat.ok, chat
        tiktoken_after_chat = "tiktoken" in sys.modules
        return tiktoken_after_chat, await container.retrieval.check_roles()

tiktoken_after_chat, checks = asyncio.run(main())
encodings = sys.modules["tiktoken.registry"].ENCODINGS if "tiktoken.registry" in sys.modules else {}
print(json.dumps({
    "blocked": blocked,
    "trap": len(trap.seen),
    "checks": [[c.role, c.status, c.dimensions, c.error] for c in checks.checks],
    "corp": [
        [s.path, s.headers.get("authorization"), s.headers.get("x-api-key")] for s in corp.seen
    ],
    "modules": sorted(sys.modules),
    "tiktoken_after_chat": tiktoken_after_chat,
    "tiktoken_encodings": sorted(encodings),
}))
"""

AI_MODULES = {
    "pydantic_ai",
    "pydantic_ai_harness",
    "pydantic_monty",
    "sqlite_vec",
    "pgvector",
    "openai",
    "anthropic",
    "google.genai",
    "azure.identity",
    "tiktoken",
    "logfire",
    "logfire_api",
    "genai_prices",
}


def run_guarded(data_dir: Path, body: str) -> dict:
    script = GUARD.format(fixtures=str(FIXTURES), variables=SDK_VARIABLES) + body
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().endswith("_PROXY") and k not in SDK_VARIABLES
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**env, "EXACTDOCS_DATA_DIR": str(data_dir)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])
