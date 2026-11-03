"""``exactdocs`` command line."""

import asyncio
from typing import Annotated

import uvicorn
from cyclopts import App, Parameter

from exactdocs import __version__
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings

app = App(name="exactdocs", version=__version__, help="Version-accurate docs for AI agents.")


@app.command
def serve(
    *,
    stdio: Annotated[bool, Parameter(help="Serve MCP over stdio instead of HTTP.")] = False,
    host: str | None = None,
    port: int | None = None,
    reload: bool = False,
) -> None:
    """Run the server: web UI + REST API + MCP over HTTP, or MCP only over stdio."""
    settings = Settings()
    if stdio:
        mcp = build_mcp(Container.build(settings))
        asyncio.run(mcp.run_stdio_async(show_banner=False))
        return
    uvicorn.run(
        "exactdocs.bootstrap.cli:asgi_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


def asgi_app() -> object:
    """ASGI factory used by uvicorn (also with ``--reload``)."""
    return create_app(Container.build(Settings()))


def main() -> None:
    """Console-script entry point."""
    app()
