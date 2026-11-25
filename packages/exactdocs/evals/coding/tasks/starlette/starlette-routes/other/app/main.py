"""The web app."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

app = Starlette()


@app.route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """The app is up."""
    return JSONResponse({"status": "ok"})


@app.route("/items/{item_id:int}", methods=["GET"])
async def item(request: Request) -> JSONResponse:
    """One item."""
    return JSONResponse({"id": request.path_params["item_id"]})
