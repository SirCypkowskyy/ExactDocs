"""The web app."""

import uuid

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def hello(request: Request) -> JSONResponse:
    """A greeting."""
    return JSONResponse({"hello": "world"})



class RequestIdMiddleware:
    """Sets `X-Request-ID` on every response (pure ASGI middleware)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = dict(scope["headers"]).get(b"x-request-id")
        request_id = given or uuid.uuid4().hex.encode()

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id)]}
            await send(message)

        await self.app(scope, receive, send_with_id)


app = Starlette(routes=[Route("/", hello)], middleware=[Middleware(RequestIdMiddleware)])
