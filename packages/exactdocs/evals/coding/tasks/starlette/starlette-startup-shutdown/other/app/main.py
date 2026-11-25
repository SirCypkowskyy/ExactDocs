"""The web app."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.db import Database

database = Database()


async def count(request: Request) -> JSONResponse:
    """How many rows the database holds."""
    return JSONResponse({"count": await database.count()})


app = Starlette(
    routes=[Route("/count", count)],
    on_startup=[database.connect],
    on_shutdown=[database.disconnect],
)
