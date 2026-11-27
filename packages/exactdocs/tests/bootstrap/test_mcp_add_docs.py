"""Where the MCP tools that add libraries (#613) exist, and where they never do."""

import pytest
from fastmcp import Client, FastMCP

from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.mcp import DomainErrorsAsToolErrors, build_mcp, build_stdio_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.errors import PreviewBusyError

ADDING = {"add_docs", "import_status"}


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


async def test_a_request_without_a_token_does_not_get_them(container: Container) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        names = {tool.name for tool in await mcp.list_tools()}
        called = await mcp.call_tool_mcp("add_docs", {"source": "a/b"})

    assert "search_docs" in names
    assert not names & ADDING
    assert called.is_error
    assert "unknown tool" in called.content[0].text.lower()


async def test_stdio_never_registers_them(container: Container) -> None:
    async with container.running():
        pass
    readonly = ReadOnlyContainer.build(Settings())
    async with readonly.running(), Client(build_stdio_mcp(readonly)) as mcp:
        names = {tool.name for tool in await mcp.list_tools()}

    assert "search_docs" in names
    assert not names & ADDING


def test_the_instructions_every_caller_reads_do_not_name_them(container: Container) -> None:
    instructions = build_mcp(container).instructions or ""

    assert not any(name in instructions for name in ADDING)


async def test_a_busy_preview_says_when_to_try_again() -> None:
    server = FastMCP(mask_error_details=True, middleware=[DomainErrorsAsToolErrors()])

    @server.tool
    def busy() -> str:
        """Every preview slot is taken.

        Returns:
            Never.

        Raises:
            PreviewBusyError: Always.
        """
        raise PreviewBusyError(retry_after=7)

    async with Client(server) as mcp:
        called = await mcp.call_tool_mcp("busy", {})

    assert called.content[0].text == "preview_busy: try again in 7 s"
