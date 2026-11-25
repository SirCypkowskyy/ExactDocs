"""The web app."""

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ITEMS = {1: "lamp"}


async def item(request: Request) -> JSONResponse:
    """One item, or 404."""
    item_id = request.path_params["item_id"]
    if item_id not in ITEMS:
        raise HTTPException(status_code=404, detail="no such item")
    return JSONResponse({"id": item_id, "name": ITEMS[item_id]})


async def boom(request: Request) -> JSONResponse:
    """A bug."""
    raise ValueError("a bug")



app = Starlette(routes=[Route("/items/{item_id:int}", item), Route("/boom", boom)])


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """An HTTP error, as JSON."""
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception) -> JSONResponse:
    """Any other error, as JSON."""
    return JSONResponse({"error": "internal error"}, status_code=500)
