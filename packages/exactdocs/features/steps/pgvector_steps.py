"""Steps for the vector store on PostgreSQL (pgvector). The vectors and searches themselves are
the steps of ``vector_store_steps.py``: they pick the store of the database they run on."""

import asyncio
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then
from behave.runner import Context
from fastapi.testclient import TestClient
from sqlalchemy import TextClause, text

from databases import SECRET_KEY, postgres_database
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import StaticModelRoles
from exactdocs.retrieval.models import ModelRole, RetrievalMode
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, store_demo_catalog
from steps.retrieval_mode_steps import StandInHybrid
from steps.search_steps import import_versions

_EXTENSION = text("SELECT count(*) FROM pg_extension WHERE extname = :name")
_AVAILABLE = text("SELECT count(*) FROM pg_available_extensions WHERE name = :name")
_COLUMN = text(
    "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a"
    " JOIN pg_class c ON c.oid = a.attrelid WHERE c.relname = :table AND a.attname = 'embedding'"
)


def _on_postgres(
    context: Context, *, owner_without_createdb: bool = False, without: tuple[str, ...] = ()
) -> None:
    """Point the scenario's settings at a new PostgreSQL database, with the demo admin in it."""
    stack = ExitStack()
    context.add_cleanup(stack.close)
    database = stack.enter_context(
        postgres_database(owner_without_createdb=owner_without_createdb, without_extensions=without)
    )
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.settings = Settings(data_dir=data_dir, database_url=database.url, secret_key=SECRET_KEY)
    asyncio.run(store_demo_catalog(context.settings))


async def _count(context: Context, statement: TextClause, name: str) -> int:
    container = Container.build(context.settings)
    async with container.running(jobs=False), container.engine.connect() as connection:
        return int(await connection.scalar(statement, {"name": name}) or 0)


@given('ExactDocs runs on PostgreSQL with the "{extension}" extension available')
def step_with_extension(context: Context, extension: str) -> None:
    _on_postgres(context)
    # Installed on the server; the store creates it in the database when it is not there yet.
    assert asyncio.run(_count(context, _AVAILABLE, extension)) == 1


@given('ExactDocs runs on PostgreSQL without the "{extension}" extension')
def step_without_extension(context: Context, extension: str) -> None:
    # A role that owns its database but is no superuser, as on managed PostgreSQL: it may not
    # create pgvector (an untrusted extension) either.
    _on_postgres(context, owner_without_createdb=True, without=(extension,))
    assert asyncio.run(_count(context, _EXTENSION, extension)) == 0


@given('the fixture docs repository is imported at "{first}" and "{second}"')
def step_imported(context: Context, first: str, second: str) -> None:
    asyncio.run(import_versions(context, [first, second]))


@given("an embedding model is configured")
def step_embedding(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    container = Container.build(
        context.settings,
        model_roles=StaticModelRoles(roles=frozenset({ModelRole.EMBEDDING})),
        pipelines={RetrievalMode.HYBRID: StandInHybrid()},
    )
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@then('the vectors of "{name}" are a pgvector column of {dimensions:d} dimensions in the database')
def step_pgvector_column(context: Context, name: str, dimensions: int) -> None:
    async def column() -> str | None:
        container = Container.build(context.settings)
        async with container.running(jobs=False), container.engine.connect() as connection:
            table = f"retrieval_vec_{int(context.spaces[name])}"
            return await connection.scalar(_COLUMN, {"table": table})

    assert asyncio.run(column()) == f"vector({dimensions})"


@then('/api/health names the missing extension "{extension}"')
def step_health_names(context: Context, extension: str) -> None:
    response = context.client.get("/api/health")
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["database_reachable"], body
    assert body["vector_store_missing"] == extension, body
