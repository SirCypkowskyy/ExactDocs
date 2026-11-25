"""The web app."""

import uuid

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def hello(request: Request) -> JSONResponse:
    """A greeting."""
    return JSONResponse({"hello": "world"})


app = Starlette(routes=[Route("/", hello)])
