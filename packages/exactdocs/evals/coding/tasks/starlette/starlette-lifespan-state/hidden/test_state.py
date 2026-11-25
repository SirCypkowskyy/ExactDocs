from starlette.testclient import TestClient

from app.db import Database
from app.main import app


def test_the_database_is_connected_while_the_app_runs():
    with TestClient(app) as client:
        assert client.get("/count").json() == {"count": 42}
        database = Database.instances[-1]
        assert database.connected
    assert not database.connected


def test_each_run_of_the_app_connects_again():
    with TestClient(app) as client:
        assert client.get("/count").json() == {"count": 42}
    with TestClient(app) as client:
        assert client.get("/count").json() == {"count": 42}
