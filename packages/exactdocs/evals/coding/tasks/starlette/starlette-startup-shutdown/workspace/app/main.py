"""The web app."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def count(request: Request) -> JSONResponse:
    """How many rows the database holds."""
    raise NotImplementedError


app = Starlette(routes=[Route("/count", count)])
