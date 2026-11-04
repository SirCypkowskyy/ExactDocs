"""Replay of a recorded context7 session: both tools, the arguments a real client sent."""

import json
from pathlib import Path

from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs_kernel import NOTICE
from next_library import LIBRARY, MIDDLEWARE, import_next

SESSION = json.loads(
    (Path(__file__).parents[1] / "contracts" / "context7" / "session.json").read_text("utf-8")
)
BUDGET_TOKENS = 500


async def test_a_recorded_context7_session_runs_without_errors() -> None:
    container = Container.build(Settings(query_docs_token_budget=BUDGET_TOKENS))
    async with container.running(), Client(build_mcp(container)) as mcp:
        await import_next(container)
        results = [await mcp.call_tool(c["tool"], c["arguments"]) for c in SESSION["calls"]]

    assert [r.is_error for r in results] == [False] * len(SESSION["calls"])
    assert all(r.content[0].text == NOTICE for r in results)
    resolved = results[0].content[1].text
    # The ID the first call hands out is the one the recorded client then queries.
    assert f"- Context7-compatible library ID: {LIBRARY}\n" in resolved
    for docs in results[1:]:
        text = docs.content[1].text
        assert text.startswith("### Middleware\n\nSource: https://github.com/vercel/next.js/blob/")
        assert "\n\nChunk: " in text
        assert text.endswith(MIDDLEWARE)
        assert sum(len(b.text) for b in docs.content) <= BUDGET_TOKENS * 4
