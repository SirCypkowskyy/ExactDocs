from starlette.testclient import TestClient

from app.main import app
from app.support import make_client


def test_a_redirect_is_seen_as_it_is():
    client = make_client(app)
    assert isinstance(client, TestClient)
    response = client.get("/old")
    assert response.status_code == 307
    assert response.headers["location"] == "/new"


def test_other_pages_still_answer():
    client = make_client(app)
    assert client.get("/new").text == "new"
    again = client.get("/old")
    assert (again.status_code, again.headers["location"]) == (307, "/new")
