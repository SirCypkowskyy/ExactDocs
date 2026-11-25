from starlette.testclient import TestClient

from app.main import LIMIT, app


def test_a_body_at_the_limit_is_accepted():
    with TestClient(app) as client:
        assert client.post("/echo", content=b"x" * LIMIT).json() == {"length": LIMIT}
        assert client.put("/upload", content=b"y" * 10).json() == {"stored": 10}


def test_a_longer_body_is_refused():
    with TestClient(app) as client:
        assert client.post("/echo", content=b"x" * (LIMIT + 1)).status_code == 413
        assert client.put("/upload", content=b"y" * 5000).status_code == 413


def test_a_chunked_body_is_counted_too():
    def chunks():
        for _ in range(3):
            yield b"z" * 600

    with TestClient(app) as client:
        response = client.post("/echo", content=chunks())
    assert response.status_code == 413
