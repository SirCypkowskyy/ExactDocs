from starlette.applications import Starlette

from app.main import app


def test_the_app_is_a_starlette_app():
    assert isinstance(app, Starlette)
