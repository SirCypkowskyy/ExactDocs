"""The web app."""

from starlette.applications import Starlette
from starlette.middleware import Middleware
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



class TooLarge(Exception):
    """The body passed the limit."""


class BodyLimitMiddleware:
    """Answers 413 to a body longer than `limit` bytes (pure ASGI middleware)."""

    def __init__(self, app, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and int(length) > self.limit:
            await JSONResponse({"error": "too large"}, status_code=413)(scope, receive, send)
            return
        received = 0

        async def counted():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise TooLarge
            return message

        try:
            await self.app(scope, counted, send)
        except TooLarge:
            await JSONResponse({"error": "too large"}, status_code=413)(scope, receive, send)


app = Starlette(routes=ROUTES, middleware=[Middleware(BodyLimitMiddleware, limit=LIMIT)])
