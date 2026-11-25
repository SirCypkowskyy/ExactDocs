"""The web app."""

import json

from starlette import status
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

LIMIT = 1024



async def create_item(request: Request) -> JSONResponse:
    """Create an item from a JSON body with a non-empty string "name"."""
    raise NotImplementedError


app = Starlette(routes=[Route("/items", create_item, methods=["POST"])])
