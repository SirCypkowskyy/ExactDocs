from starlette.testclient import TestClient

from app.main import app


def test_the_greeting_is_rendered():
    with TestClient(app) as client:
        response = client.get("/hello/Ada")
    assert response.status_code == 200
    assert "<p>Hello, Ada!</p>" in response.text
    assert 'href="http://testserver/hello/Ada"' in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_the_name_is_escaped():
    with TestClient(app) as client:
        assert "Hello, &lt;b&gt;!" in client.get("/hello/<b>").text
