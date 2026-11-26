"""The web app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.db import Database


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[dict[str, Database]]:
    """Connect the database for the app's lifetime."""
    database = Database()
    await database.connect()
    try:
        yield {"database": database}
    finally:
        await database.disconnect()


async def count(request: Request) -> JSONResponse:
    """How many rows the database holds."""
    return JSONResponse({"count": await request.state["database"].count()})


app = Starlette(routes=[Route("/count", count)], lifespan=lifespan)
