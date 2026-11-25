import re

from starlette.testclient import TestClient

from app.main import app


def test_the_request_s_id_is_echoed():
    with TestClient(app) as client:
        response = client.get("/", headers={"X-Request-ID": "abc-123"})
    assert response.json() == {"hello": "world"}
    assert response.headers["x-request-id"] == "abc-123"


def test_a_new_id_is_made_otherwise():
    with TestClient(app) as client:
        first = client.get("/").headers["x-request-id"]
        second = client.get("/").headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_errors_get_an_id_too():
    with TestClient(app) as client:
        response = client.get("/nowhere")
    assert response.status_code == 404
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
