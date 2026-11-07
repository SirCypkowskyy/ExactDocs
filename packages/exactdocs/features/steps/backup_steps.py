"""Steps for ``exactdocs backup`` and ``exactdocs restore``, run as the operator would."""

import asyncio
import io
import os
import sqlite3
import tempfile
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from steps.http_steps import DEMO_COOKIE, OfflineGit, store_demo_catalog

LIBRARY = "/acme/payments"
"""The demo library that gets a scheduled check (a setting) before the backup."""
AUTO_SYNC = {"tag_pattern": "v*", "keep_last": 3, "interval_minutes": 60}
"""The setting stored before the backup."""
NEWER_REVISION = "f0f0f0f0f0f0"
"""A schema revision no build of this checkout knows: one a newer release would have written."""


def _data_dir(context: Context) -> Path:
    """Make an empty data directory that lives as long as the scenario.

    Args:
        context: The behave context.

    Returns:
        The directory (it does not exist yet: restore creates it).
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    return Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-"))) / "data"


def _client(settings: Settings, context: Context, cookie: str | None = None) -> TestClient:
    """Serve an instance until the scenario ends or ``context.stop_serving()`` is called.

    Args:
        settings: Where its data lives.
        context: The behave context, whose cleanups stop it.
        cookie: A session cookie for the client, if any.

    Returns:
        The client.
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.stop_serving = stack.close  # one job worker per process: stop before serving another
    cookies = {SESSION_COOKIE: cookie} if cookie else None
    return stack.enter_context(
        TestClient(
            create_app(Container.build(settings, remote=OfflineGit(GitCli.locate()))),
            base_url="http://localhost",
            cookies=cookies,
        )
    )


def _exactdocs(data_dir: Path, *args: str) -> tuple[int, str]:
    """Run an ``exactdocs`` command in this process, as the operator would in a shell.

    Args:
        data_dir: The EXACTDOCS_DATA_DIR of the command.
        *args: The command line after ``exactdocs``.

    Returns:
        The exit status and what the command printed (stdout and stderr).
    """
    output = io.StringIO()
    env = {"EXACTDOCS_DATA_DIR": str(data_dir)}
    with (
        patch.dict(os.environ, env),
        redirect_stdout(output),
        redirect_stderr(output),
    ):
        try:
            cli.app(list(args), exit_on_error=False, result_action="return_value")
        except SystemExit as exc:
            if isinstance(exc.code, str):
                output.write(exc.code)
            return (exc.code if isinstance(exc.code, int) else 1), output.getvalue()
    return 0, output.getvalue()


def _bearer(context: Context, client: TestClient, path: str) -> object:
    """GET ``path`` with the API token alone (no cookie).

    Args:
        context: The behave context holding the token.
        client: The instance to ask.
        path: The API path.

    Returns:
        The JSON body; the request must succeed.
    """
    request = client.build_request(
        "GET", path, headers={"authorization": f"Bearer {context.token}"}
    )
    request.headers.pop("cookie", None)
    response = client.send(request)
    assert response.status_code == HTTPStatus.OK, (path, response.status_code, response.text)
    return response.json()


def _served(context: Context, client: TestClient) -> dict[str, object]:
    """What a token holder sees of the instance: the libraries, one library, a setting.

    Args:
        context: The behave context holding the token.
        client: The instance to ask.

    Returns:
        The answers by name.
    """
    return {
        "libraries": _bearer(context, client, "/api/v1/libraries"),
        "library": _bearer(context, client, f"/api/v1/libraries{LIBRARY}"),
        "auto_sync": _bearer(context, client, f"/api/v1/libraries{LIBRARY}/auto-sync"),
    }


@given("an instance with libraries, versions, settings, accounts and tokens")
def step_instance(context: Context) -> None:
    """Serve the demo catalog (an admin, libraries with versions); add a setting and a token.

    Args:
        context: The behave context.
    """
    context.settings = Settings(data_dir=_data_dir(context))
    asyncio.run(store_demo_catalog(context.settings))
    context.client = _client(context.settings, context, cookie=DEMO_COOKIE)
    stored = context.client.put(f"/api/v1/libraries{LIBRARY}/auto-sync", json=AUTO_SYNC)
    assert stored.status_code == HTTPStatus.OK, stored.text
    created = context.client.post("/api/v1/tokens", json={"name": "ci"})
    assert created.status_code == HTTPStatus.CREATED, created.text
    context.token = created.json()["token"]
    context.served_before = _served(context, context.client)


@when('the operator runs "exactdocs backup" and restores it into an empty data dir')
def step_backup_and_restore(context: Context) -> None:
    """Back up while the instance serves, then restore into a new data directory.

    Args:
        context: The behave context.
    """
    archive = _data_dir(context).parent / "exactdocs.tar.gz"
    code, output = _exactdocs(context.settings.data_dir, "backup", str(archive))
    assert code == 0, output
    context.restored_dir = _data_dir(context)
    code, output = _exactdocs(context.restored_dir, "restore", str(archive))
    assert code == 0, output


@then("the restored instance serves the same libraries and accepts the same tokens")
def step_same(context: Context) -> None:
    """Serve the restored data directory and compare it with the original.

    Args:
        context: The behave context.
    """
    context.stop_serving()
    restored = _client(Settings(data_dir=context.restored_dir), context)
    assert _served(context, restored) == context.served_before


@given("a backup taken by a newer release of ExactDocs")
def step_newer_backup(context: Context) -> None:
    """Back up an instance, then make the archive's schema one this build does not know.

    Args:
        context: The behave context.
    """
    settings = Settings(data_dir=_data_dir(context))
    asyncio.run(store_demo_catalog(settings))
    database = settings.data_dir / "exactdocs.db"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = ?", (NEWER_REVISION,))
    connection.close()
    context.archive = settings.data_dir.parent / "newer.tar.gz"
    code, output = _exactdocs(settings.data_dir, "backup", str(context.archive))
    assert code == 0, output


@when("the operator restores it into an empty data dir")
def step_restore_newer(context: Context) -> None:
    """Restore the archive into a new data directory.

    Args:
        context: The behave context.
    """
    context.restored_dir = _data_dir(context)
    context.restore = _exactdocs(context.restored_dir, "restore", str(context.archive))


@then("the restore is refused, naming the newer schema")
def step_refused_newer(context: Context) -> None:
    """Check the restore failed and said why.

    Args:
        context: The behave context.
    """
    code, output = context.restore
    assert code != 0, output
    assert NEWER_REVISION in output, output
    assert "newer" in output, output


@then("nothing was written to the data dir")
def step_nothing_written(context: Context) -> None:
    """Check the refused restore left the target empty.

    Args:
        context: The behave context.
    """
    assert not context.restored_dir.exists() or not any(context.restored_dir.iterdir())


@when("the operator restores a backup into that instance's data dir")
def step_restore_over(context: Context) -> None:
    """Back the instance up and restore the archive over the same data directory.

    Args:
        context: The behave context.
    """
    archive = context.settings.data_dir.parent / "same.tar.gz"
    code, output = _exactdocs(context.settings.data_dir, "backup", str(archive))
    assert code == 0, output
    context.restore = _exactdocs(context.settings.data_dir, "restore", str(archive))


@then("the restore is refused because the data dir already holds a database")
def step_refused_existing(context: Context) -> None:
    """Check the restore failed, said why, and the instance still serves as before.

    Args:
        context: The behave context.
    """
    code, output = context.restore
    assert code != 0, output
    assert "already" in output, output
    assert _served(context, context.client) == context.served_before
