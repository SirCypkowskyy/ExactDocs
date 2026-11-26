"""Test helpers."""

from starlette.testclient import TestClient
from starlette.types import ASGIApp


def make_client(app: ASGIApp) -> TestClient:
    """A test client for `app` that does not follow redirects."""
    return TestClient(app, follow_redirects=False)
