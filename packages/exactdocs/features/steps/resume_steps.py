"""Steps for an import killed halfway: ExactDocs runs it in a process of its own, then again.

The process kills itself (SIGKILL) before chunking the next file; the chunk log says which files
each run chunked (see ``tests/fixtures/import_child.py``). The version is read over HTTP.
"""

import asyncio
import json
import signal
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
)
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.models import Session, hash_token
from import_child import LIBRARY, big_repository, page, run
from steps.jobs_steps import ADMIN_COOKIE, PLACEHOLDER_ADMIN


@given("an import of {files:d} files was killed after {done:d} files")
def step_killed_import(context: Context, files: int, done: int) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    base = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-kill-")))
    url, commit = big_repository(base / "repo", files)
    context.files, context.data_dir, context.chunk_log = files, base / "data", base / "chunked.log"
    code, _, err = asyncio.run(
        run(str(context.data_dir), url, commit, str(context.chunk_log), str(done))
    )
    assert code == -signal.SIGKILL, err
    assert context.chunk_log.read_text().splitlines() == [page(n) for n in range(1, done + 1)]
    context.chunk_log.unlink()


@when("ExactDocs starts again")
def step_starts_again(context: Context) -> None:
    code, out, err = asyncio.run(run(str(context.data_dir), "-", "-", str(context.chunk_log)))
    assert code == 0, err
    context.job = json.loads(out)


@then("the import finishes from file {first:d}")
def step_finishes_from(context: Context, first: int) -> None:
    assert context.job["state"] == "succeeded", context.job
    assert (context.job["done"], context.job["total"]) == (context.files, context.files)
    chunked = context.chunk_log.read_text().splitlines()
    assert chunked == [page(n) for n in range(first, context.files + 1)]


@then("the version has each article exactly once")
def step_each_article_once(context: Context) -> None:
    container = Container.build(Settings(data_dir=context.data_dir))
    with TestClient(create_app(container), base_url="http://localhost") as client:
        portal = client.portal  # the app's own event loop
        assert portal is not None
        portal.call(SqliteAccountRepository(engine=container.engine).add_first, PLACEHOLDER_ADMIN)
        now = datetime.now(UTC)
        session = Session(
            token_hash=hash_token(ADMIN_COOKIE),
            account_id=PLACEHOLDER_ADMIN.id,
            created_at=now,
            last_used_at=now,
        )
        portal.call(SqliteSessionRepository(engine=container.engine).add, session)
        client.cookies.set(SESSION_COOKIE, ADMIN_COOKIE)
        paths, cursor = [], None
        while True:
            params = {"ref": "main", "limit": 100} | ({"cursor": cursor} if cursor else {})
            response = client.get(f"/api/v1/libraries{LIBRARY}/articles", params=params)
            assert response.status_code == HTTPStatus.OK, response.text
            body = response.json()
            paths += [article["path"] for article in body["articles"]]
            if not (cursor := body["next_cursor"]):
                break
    assert paths == [page(n) for n in range(1, context.files + 1)]
