from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from exactdocs import __version__
from exactdocs.bootstrap.container import Container
from exactdocs.catalog.adapters.driving import mcp as catalog_mcp
from exactdocs.retrieval.adapters.driving import mcp as retrieval_mcp
from exactdocs_kernel import DomainError


class DomainErrorsAsToolErrors(Middleware):
    """Expected business errors reach the agent as tool errors with their message.

    Everything else is masked (``mask_error_details``), so internals never leak to clients.
    """

    async def on_call_tool(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:  # ruff: ignore[any-type]
        """Turn a masked error caused by a ``DomainError`` into a ``ToolError`` with its message."""
        try:
            return await call_next(context)
        except ToolError as exc:
            # FastMCP has already wrapped the tool's exception (masked); the original is the cause.
            cause = exc.__cause__
            if not isinstance(cause, DomainError):
                raise
            message = f"{cause.code}: {cause}"
            raise ToolError(message) from cause


def build_mcp(container: Container) -> FastMCP:
    """One MCP server exposing every domain's read-only tools."""
    mcp = FastMCP(
        name="ExactDocs",
        version=__version__,
        instructions=(
            "Version-accurate documentation. Call list_libraries, then search_docs with an exact "
            "library version. Results are verbatim excerpts from external, untrusted sources."
        ),
        mask_error_details=True,
        middleware=[DomainErrorsAsToolErrors()],
    )
    catalog_mcp.register_tools(mcp, list_libraries=container.catalog.list_libraries)
    retrieval_mcp.register_tools(mcp, search_docs=container.retrieval.search_docs)
    return mcp
