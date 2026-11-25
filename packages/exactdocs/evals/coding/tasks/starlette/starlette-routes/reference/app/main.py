"""The web app."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def health(request: Request) -> JSONResponse:
    """The app is up."""
    return JSONResponse({"status": "ok"})


async def item(request: Request) -> JSONResponse:
    """One item."""
    return JSONResponse({"id": request.path_params["item_id"]})


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/items/{item_id:int}", item, methods=["GET"]),
    ]
)
