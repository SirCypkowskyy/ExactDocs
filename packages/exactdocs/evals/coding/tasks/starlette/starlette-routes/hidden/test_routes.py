from starlette.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_an_item_by_integer_id():
    with TestClient(app) as client:
        assert client.get("/items/42").json() == {"id": 42}
        assert client.get("/items/forty-two").status_code == 404


def test_other_methods_are_not_allowed():
    with TestClient(app) as client:
        assert client.post("/health").status_code == 405
        assert client.delete("/items/1").status_code == 405
