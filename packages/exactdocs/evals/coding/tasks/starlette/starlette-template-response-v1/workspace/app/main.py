"""The web app."""

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


app = Starlette()
