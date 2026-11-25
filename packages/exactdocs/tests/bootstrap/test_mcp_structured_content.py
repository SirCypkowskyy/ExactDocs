"""What a model gets from each tool when its client reads the structured content (#587).

Some MCP clients give the model a tool's structured content instead of its text blocks:
pydantic-ai does whenever every block is text (``pydantic_ai.mcp._map_mcp_call_tool_result``), and
it runs the agent benchmark. Such a model must get what the text blocks give: the notice first,
the article or chunk text byte for byte, and nothing else the text blocks carry left out.
"""

import hashlib
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from pydantic_ai.mcp import _map_mcp_call_tool_result

from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.mcp import build_mcp, build_stdio_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.retrieval.constants import MORE_MATCHES
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand
from exactdocs.retrieval.models import chunk_id
from exactdocs_kernel import NOTICE

pytestmark = pytest.mark.usefixtures("demo_catalog")

LIBRARY = "/acme/payments"
REF = "v1.4.0"
PATH = "guide/retries.md"
TITLE = "Retries"
# Quotes, a backslash, a non-ASCII dash and code: JSON escapes them, the model must get them back.
SECTION = '## Example\n\n```python\nretry_policy = "3"  # or r"\\d+" — see below\n```\n'
PREAMBLE = "# Retries\n\nSet `retry_policy`.\n\n"
ARTICLE = PREAMBLE + SECTION
CHUNK = chunk_id(f"{LIBRARY}/{REF}", PATH, ["Retries", "Example"], 0, "h")
SOURCE = f"https://github.com/acme/payments/blob/{'a' * 40}/{PATH}"

# Every tool, and the text its model must get verbatim: the article, the chunk, or what it lists.
TOOL_CALLS: dict[str, tuple[dict[str, Any], str]] = {
    "list_libraries": ({}, LIBRARY),
    "list_articles": ({"library": LIBRARY}, PATH),
    "search_docs": ({"library": LIBRARY, "query": "retry_policy"}, SECTION),
    "search_all_docs": ({"query": "retry_policy"}, SECTION),
    "read_article": ({"library": LIBRARY, "path": PATH}, ARTICLE),
    "read_chunk": ({"chunk_id": CHUNK}, SECTION),
    "article_outline": ({"library": LIBRARY, "path": PATH}, CHUNK),
    "resolve-library-id": ({"libraryName": "payments", "query": "retry"}, LIBRARY),
    "query-docs": ({"libraryId": f"{LIBRARY}/{REF}", "query": "retry_policy"}, SECTION),
    "view_article": ({"library": LIBRARY, "path": PATH}, ARTICLE),
    "view_search": ({"library": LIBRARY, "query": "retry_policy"}, SECTION),
}
# A block of their own, byte for byte: these tools' text is a leaf of what the model gets.
VERBATIM_TOOLS = {"read_article", "read_chunk", "view_article"}


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


async def publish(container: Container) -> None:
    """Store, index and activate one article of two sections, both mentioning ``retry_policy``."""
    blob = hashlib.sha1(PATH.encode(), usedforsecurity=False).hexdigest()
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=LIBRARY,
            ref=REF,
            kind="tag",
            commit_sha="a" * 40,
            articles=[
                ArticleIn(
                    path=PATH,
                    blob_sha=blob,
                    content_version=1,
                    title=TITLE,
                    tags=["guide"],
                    content=ARTICLE,
                )
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=LIBRARY,
            ref=REF,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=PATH,
                    blob_sha=blob,
                    chunks=[
                        ChunkIn(
                            heading_path=["Retries"],
                            occurrence_index=0,
                            content=PREAMBLE,
                            content_hash="p",
                            anchor="retries",
                        ),
                        ChunkIn(
                            heading_path=["Retries", "Example"],
                            occurrence_index=0,
                            content=SECTION,
                            content_hash="h",
                            anchor="example",
                        ),
                    ],
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


def leaves(value: object) -> Iterator[str]:
    """Every string in what the model gets, depth first: values, list items, the value itself."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item)


def holds(model_input: object, text: str) -> bool:
    """Whether some string the model gets contains ``text``."""
    return any(text in leaf for leaf in leaves(model_input))


def notice_first(model_input: object) -> bool:
    """Whether the model reads the notice before anything else: first key, or first block."""
    if isinstance(model_input, dict):
        return next(iter(model_input), None) == "notice" and model_input["notice"] == NOTICE
    return isinstance(model_input, list) and bool(model_input) and model_input[0] == NOTICE


def texts(result: CallToolResult) -> list[str]:
    """The text of every block: every block of every tool is text."""
    assert all(isinstance(block, TextContent) for block in result.content), result.content
    return [block.text for block in result.content if isinstance(block, TextContent)]


async def call(container: Container, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    async with container.running(), Client(build_mcp(container)) as mcp:
        await publish(container)
        return await mcp.call_tool(tool, arguments)


@pytest.mark.parametrize("tool", TOOL_CALLS)
async def test_a_model_that_reads_structured_content_gets_the_notice_and_the_text(
    container: Container, tool: str
) -> None:
    arguments, text = TOOL_CALLS[tool]
    result = await call(container, tool, arguments)
    model_input = _map_mcp_call_tool_result(result)

    assert notice_first(model_input), model_input
    assert holds(model_input, text), model_input
    if tool in VERBATIM_TOOLS:  # its own string, nothing added around it
        assert text in list(leaves(model_input)), model_input
    # What the model gets survives the JSON it is sent as, byte for byte.
    assert json.loads(json.dumps(model_input)) == model_input


@pytest.mark.parametrize("tool", TOOL_CALLS)
async def test_the_structured_content_holds_every_text_block(
    container: Container, tool: str
) -> None:
    arguments, _ = TOOL_CALLS[tool]
    result = await call(container, tool, arguments)

    if result.structured_content is None:  # context7's text tools: the model reads the blocks
        assert tool in {"resolve-library-id", "query-docs"}
        assert _map_mcp_call_tool_result(result) == texts(result)
        return
    blocks = texts(result)
    if len(blocks) == 1:  # the data tools: the block is the structured content as JSON
        assert json.loads(blocks[0]) == result.structured_content
        return
    assert blocks[0] == NOTICE
    assert result.structured_content["notice"] == NOTICE
    if tool in {"read_article", "read_chunk"}:  # the text block, byte for byte
        assert blocks[1] == result.structured_content["content"]


async def test_view_article_gives_a_model_everything_its_text_fallback_names(
    container: Container,
) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        await publish(container)
        viewed = await mcp.call_tool("view_article", {"library": LIBRARY, "path": PATH})
        read = await mcp.call_tool("read_article", {"library": LIBRARY, "path": PATH})

    article = read.structured_content
    assert article is not None
    header = viewed.content[1].text
    model_input = _map_mcp_call_tool_result(viewed)
    named = [*(article[key] for key in ("title", "library", "ref", "commit_sha", "path")), SOURCE]
    for value in [*named, *article["tags"]]:
        assert value in header, value  # the text fallback names it ...
        assert holds(model_input, value), value  # ... and so does the UI the model gets


async def test_view_search_gives_a_model_every_result_its_text_fallback_lists(
    container: Container,
) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        await publish(container)
        viewed = await mcp.call_tool("view_search", {"library": LIBRARY, "query": "retry_policy"})
        searched = await mcp.call_tool("search_docs", {"library": LIBRARY, "query": "retry_policy"})

    assert searched.structured_content is not None
    found = searched.structured_content["results"]
    assert found
    text = viewed.content[1].text
    model_input = _map_mcp_call_tool_result(viewed)
    for result in found:
        for value in (
            " > ".join(result["heading_path"]),
            result["article_path"],
            result["source_url"],
            result["chunk_id"],  # for read_chunk: the text fallback had it, the UI did not (#587)
            result["snippet"],
        ):
            assert value in text, value
            assert holds(model_input, value), value


async def test_view_search_says_when_the_limit_cut_the_results(container: Container) -> None:
    query = {"library": LIBRARY, "query": "retry_policy"}
    async with container.running(), Client(build_mcp(container)) as mcp:
        await publish(container)
        cut = await mcp.call_tool("view_search", {**query, "limit": 1})
        whole = await mcp.call_tool("view_search", query)

    assert MORE_MATCHES in cut.content[1].text
    assert holds(_map_mcp_call_tool_result(cut), MORE_MATCHES)
    assert MORE_MATCHES not in whole.content[1].text
    assert not holds(_map_mcp_call_tool_result(whole), MORE_MATCHES)


async def test_over_stdio_a_model_reads_the_whole_article_too(container: Container) -> None:
    async with container.running():
        await publish(container)
    readonly = ReadOnlyContainer.build(Settings())
    async with readonly.running(), Client(build_stdio_mcp(readonly)) as mcp:
        result = await mcp.call_tool("read_article", {"library": LIBRARY, "path": PATH})

    model_input = _map_mcp_call_tool_result(result)
    assert notice_first(model_input)
    assert model_input["content"] == ARTICLE


async def test_read_article_declares_the_notice_and_the_text_in_its_output_schema(
    container: Container,
) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}

    for name in ("read_article", "read_chunk"):
        schema = tools[name].output_schema
        assert schema is not None, name
        assert {"notice", "content"} <= set(schema["required"]), name
        assert schema["properties"]["content"]["type"] == "string", name
