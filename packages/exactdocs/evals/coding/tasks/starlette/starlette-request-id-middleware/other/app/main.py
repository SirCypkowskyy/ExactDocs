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


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Set `X-Request-ID` on the response."""
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.headers.get("x-request-id", uuid.uuid4().hex)
    return response
