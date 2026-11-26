from starlette.testclient import TestClient

from app.main import app


def test_an_item():
    with TestClient(app) as client:
        assert client.get("/items/1").json() == {"id": 1, "name": "lamp"}


def test_an_http_error_is_json():
    with TestClient(app) as client:
        response = client.get("/items/2")
    assert response.status_code == 404
    assert response.json() == {"error": "no such item"}


def test_a_bug_is_a_json_500():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"error": "internal error"}
