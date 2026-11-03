"""Composition root: the only package allowed to import more than one domain.

It picks adapters, wires domains to each other through ports, and builds the HTTP, MCP and CLI
entry points.
"""

import os

# No outbound connections the operator did not configure (RUN-03): FastMCP would otherwise
# check PyPI for updates. Set before anything imports fastmcp.
os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")  # ruff: ignore[non-empty-init-module]
