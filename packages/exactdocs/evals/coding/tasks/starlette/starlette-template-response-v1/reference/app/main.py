"""The web app."""

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")



async def greet(request: Request):
    """Greet someone by name."""
    name = request.path_params["name"]
    return templates.TemplateResponse(request, "greeting.html", {"name": name})


app = Starlette(routes=[Route("/hello/{name}", greet, name="greet")])
