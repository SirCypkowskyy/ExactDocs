"""Instance creation permissions through the public REST API."""

import sqlite3
import tempfile
from contextlib import ExitStack, closing
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.constants import DATABASE_MEMBER
from exactdocs.bootstrap.settings import Settings
from steps import library_roles_steps as roles
from steps.http_steps import DEMO_COOKIE, running_with


@given('only group "{group}" may create libraries')
def step_creation_group(context: Context, group: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-creators-")))
    running_with(
        context, stack, Settings(data_dir=directory, auth={"library_creation": {"groups": [group]}})
    )


@given('"{username}" belongs to library creator group "{group}"')
def step_creator_membership(context: Context, username: str, group: str) -> None:
    person = roles.get_person(context, username)
    with closing(sqlite3.connect(context.settings.data_dir / DATABASE_MEMBER)) as database:
        database.execute(
            "INSERT INTO identity_account_groups (account_id, name) VALUES (?, ?)",
            (person["id"], group),
        )
        database.commit()


@when('"{username}" outside that group adds a library')
@when('"{username}" adds a permitted library')
def step_create(context: Context, username: str) -> None:
    context.response = roles.send_as(
        context,
        "POST",
        "/api/v1/libraries",
        session=roles.get_person(context, username)["session"],
        json={
            "url": context.fixture_repo.file_url,
            "library_id": "/acme/new-library",
            "ref": "v1.4.0",
            "include_paths": ["docs/**"],
        },
    )


@then("library creation is refused without storing the library")
def step_creation_denied(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.FORBIDDEN, context.response.text
    found = roles.send_as(context, "GET", "/api/v1/libraries/acme/new-library", session=DEMO_COOKIE)
    assert found.status_code == HTTPStatus.NOT_FOUND, found.text


@then('"{username}" owns the new library')
def step_creation_owned(context: Context, username: str) -> None:
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    grants = roles.send_as(
        context,
        "GET",
        "/api/v1/libraries/acme/new-library/grants",
        session=roles.get_person(context, username)["session"],
    )
    assert grants.status_code == HTTPStatus.OK, grants.text
    assert {"kind": "user", "subject": username, "role": "creator"} in grants.json()["grants"]
