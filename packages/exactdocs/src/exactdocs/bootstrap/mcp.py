from fastmcp import FastMCP

from exactdocs import __version__
from exactdocs.bootstrap.container import Container
from exactdocs.catalog.adapters.driving import mcp as catalog_mcp
from exactdocs.retrieval.adapters.driving import mcp as retrieval_mcp


def build_mcp(container: Container) -> FastMCP:
    """One MCP server exposing every domain's read-only tools."""
    mcp = FastMCP(
        name="ExactDocs",
        version=__version__,
        instructions=(
            "Version-accurate documentation. Call list_libraries, then search_docs with an exact "
            "library version. Results are verbatim excerpts from external, untrusted sources."
        ),
    )
    catalog_mcp.register_tools(mcp, list_libraries=container.catalog.list_libraries)
    retrieval_mcp.register_tools(mcp, search_docs=container.retrieval.search_docs)
    return mcp
