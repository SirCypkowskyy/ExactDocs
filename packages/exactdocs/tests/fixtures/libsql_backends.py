"""libSQL for the external index contract suites and the libSQL scenario (#358).

Two cases, as an operator can run it:

- ``libsql``: a libSQL server, ``EXACTDOCS_TEST_LIBSQL_URL`` (CI: the pinned
  ``ghcr.io/tursodatabase/libsql-server`` container, started with JWT auth by
  ``deploy/libsql-test-server.sh``; locally ``docker run -p 8080:8080`` the same image and
  ``http://127.0.0.1:8080``), with ``EXACTDOCS_TEST_LIBSQL_AUTH_TOKEN`` when it needs a token.
  Without the URL the case is left out (``EXACTDOCS_REQUIRE_LIBSQL=1`` makes that an error).
- ``libsql_file``: a local file in a temporary folder, through the ``libsql`` package; left out
  where it is not installed (it has a Python 3.14 wheel for Linux x86_64 only).

Every server backend gets tables of its own (a random ``prefix``), dropped after.
"""

import importlib.util
import os
import secrets
import tempfile
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from exactdocs.retrieval.adapters.driven.libsql_index import (
    _HttpEngine,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.ports import SearchBackend, VectorBackend

LIBSQL_URL = os.environ.get("EXACTDOCS_TEST_LIBSQL_URL") or None
LIBSQL_TOKEN = os.environ.get("EXACTDOCS_TEST_LIBSQL_AUTH_TOKEN") or None
HAS_DRIVER = importlib.util.find_spec("libsql") is not None


def server_url() -> str | None:
    """The test server's URL, or ``None`` (``EXACTDOCS_REQUIRE_LIBSQL=1``: an error instead)."""
    if LIBSQL_URL is None and os.environ.get("EXACTDOCS_REQUIRE_LIBSQL") == "1":
        message = "EXACTDOCS_REQUIRE_LIBSQL=1 but EXACTDOCS_TEST_LIBSQL_URL is not set"
        raise RuntimeError(message)
    return LIBSQL_URL


def server_options(prefix: str) -> dict[str, object]:
    """The ``[index_backends.libsql]`` options of the test server, with its token."""
    assert LIBSQL_URL is not None
    found: dict[str, object] = {"url": LIBSQL_URL, "prefix": prefix}
    if LIBSQL_TOKEN:
        found["auth_token"] = LIBSQL_TOKEN
    return found


def admin() -> _HttpEngine:
    """An engine of the test server, for the tests' own looks and clean-ups (open it)."""
    assert LIBSQL_URL is not None
    url = LIBSQL_URL.replace("libsql://", "https://", 1)
    return _HttpEngine(url=url, token=LIBSQL_TOKEN)


async def drop_tables(prefix: str) -> None:
    """Drop every table and index of the test server whose name starts with ``prefix_``."""
    engine = admin()
    await engine.open()
    try:
        pattern = prefix.replace("_", "\\_") + "\\_%"
        listed = "SELECT type, name FROM sqlite_master WHERE name LIKE ? ESCAPE '\\' ORDER BY name"
        (rows,) = await engine.run([(listed, [pattern])], atomic=False)
        indexes = [n for t, n in rows if t == "index" and n.endswith("_ann")]
        await engine.run([(f"DROP INDEX IF EXISTS {n}", ()) for n in indexes], atomic=True)
        await engine.run([(f"DROP TABLE IF EXISTS {prefix}_search", ())], atomic=True)
        (rows,) = await engine.run([(listed, [pattern])], atomic=False)
        tables = [n for t, n in rows if t == "table"]
        await engine.run([(f"DROP TABLE IF EXISTS {n}", ()) for n in tables], atomic=True)
    finally:
        await engine.close()


def _server[B: (SearchBackend, VectorBackend)](
    build: Callable[[dict[str, object]], B],
) -> Callable[[], AbstractAsyncContextManager[B]]:
    """A case that builds a fresh backend of the test server, its tables dropped after."""

    @asynccontextmanager
    async def made() -> AsyncGenerator[B]:
        prefix = f"test_{secrets.token_hex(6)}"
        backend = build(server_options(prefix))
        await backend.open()
        try:
            yield backend
        finally:
            await backend.close()
            await drop_tables(prefix)

    return made


def _file[B: (SearchBackend, VectorBackend)](
    build: Callable[[dict[str, object]], B],
) -> Callable[[], AbstractAsyncContextManager[B]]:
    """A case that builds a fresh backend on a new local file, removed after."""

    @asynccontextmanager
    async def made() -> AsyncGenerator[B]:
        with tempfile.TemporaryDirectory(prefix="exactdocs-libsql-") as folder:
            backend = build({"url": f"file:{Path(folder) / 'index.db'}"})
            await backend.open()
            try:
                yield backend
            finally:
                await backend.close()

    return made


server_search = _server(search_backend)
server_vectors = _server(vector_backend)
file_search = _file(search_backend)
file_vectors = _file(vector_backend)
