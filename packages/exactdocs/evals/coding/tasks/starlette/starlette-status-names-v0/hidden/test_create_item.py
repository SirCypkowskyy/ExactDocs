from starlette.testclient import TestClient

from app.main import app


def test_an_item_is_created():
    with TestClient(app) as client:
        response = client.post("/items", json={"name": "lamp"})
    assert response.status_code == 201
    assert response.json() == {"name": "lamp"}


def test_a_bad_body_is_unprocessable():
    with TestClient(app) as client:
        for body in (b"not json", b"{}", b'{"name": ""}', b'{"name": 3}', b"[1]"):
            response = client.post("/items", content=body)
            assert response.status_code == 422, body
            assert response.json() == {"error": "name is required"}


def test_a_large_body_is_refused():
    with TestClient(app) as client:
        response = client.post("/items", json={"name": "x" * 2000})
    assert response.status_code == 413
    assert response.json() == {"error": "too large"}
