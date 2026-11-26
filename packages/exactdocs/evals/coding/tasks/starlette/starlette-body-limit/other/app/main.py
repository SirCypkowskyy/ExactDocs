"""The web app."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

LIMIT = 1024


async def echo(request: Request) -> JSONResponse:
    """How long the body was."""
    return JSONResponse({"length": len(await request.body())})


async def upload(request: Request) -> JSONResponse:
    """Accept a file's bytes."""
    return JSONResponse({"stored": len(await request.body())})


ROUTES = [Route("/echo", echo, methods=["POST"]), Route("/upload", upload, methods=["PUT"])]


app = Starlette(routes=ROUTES, max_body_size=LIMIT)
