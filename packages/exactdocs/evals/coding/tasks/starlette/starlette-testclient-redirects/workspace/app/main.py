"""The web app."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.routing import Route


async def old(request: Request) -> RedirectResponse:
    """The old address."""
    return RedirectResponse("/new")


async def new(request: Request) -> PlainTextResponse:
    """The new address."""
    return PlainTextResponse("new")


app = Starlette(routes=[Route("/old", old), Route("/new", new)])
