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
    body = await request.body()
    if len(body) > LIMIT:
        return JSONResponse({"error": "too large"}, status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name:
        return JSONResponse({"error": "name is required"}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    return JSONResponse({"name": name}, status_code=status.HTTP_201_CREATED)


app = Starlette(routes=[Route("/items", create_item, methods=["POST"])])
