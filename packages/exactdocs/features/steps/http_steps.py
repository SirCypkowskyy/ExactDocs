"""Steps that drive ExactDocs through its public HTTP API, like a real client would."""

import asyncio
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    RefKind,
    Version,
    VersionRef,
)
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
)
from exactdocs.identity.adapters.driving.http import SESSION_COOKIE
from exactdocs.identity.models import Account, AccountId, Role, Session, Username, hash_token
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.models import Credential, RemoteRefs, RepositoryUrl
from exactdocs.ingestion.ports import GitRemote

IMPORTED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _version(ref: str, kind: RefKind, sha: str) -> Version:
    return Version(
        ref=VersionRef(ref), kind=kind, commit_sha=sha.ljust(40, "0"), imported_at=IMPORTED
    )


# The demo catalog exists only as test data: ExactDocs itself starts with an empty catalog.
# It is shaped like the fixture docs repository: two tags and a branch.
DEMO_LIBRARIES = [
    Library(
        id=LibraryId("/acme/payments"),
        title="Payments",
        source_url="https://github.com/acme/payments",
        host=HostKind.GITHUB,
        default_branch=VersionRef("main"),
        versions=frozenset(
            {
                _version("v1.3.0", RefKind.TAG, "1a"),
                _version("v1.4.0", RefKind.TAG, "1b"),
                _version("main", RefKind.BRANCH, "1c"),
                _version("next", RefKind.BRANCH, "1d"),
            }
        ),
    ),
    Library(
        id=LibraryId("/acme/ledger"),
        title="Ledger",
        source_url="https://git.example.com/acme/ledger.git",
        host=HostKind.GIT,
        default_branch=VersionRef("main"),
        versions=frozenset({_version("main", RefKind.BRANCH, "2a")}),
    ),
]


# Ends the setup state (the API refuses everything before an account exists). The admin is signed
# in by a session planted directly: the demo steps are not about signing in.
DEMO_COOKIE = "demo-session-token"
NOT_A_HASH = "not-a-hash"
PLACEHOLDER_ADMIN = Account(
    id=AccountId("00000000000000000000000000000001"),
    username=Username("admin"),
    password_hash=NOT_A_HASH,
    role=Role.ADMIN,
    created_at=datetime(2026, 1, 1, tzinfo=UTC),
)


async def store_demo_catalog(settings: Settings) -> None:
    container = Container.build(settings)
    async with container.running(jobs=False):
        await SqliteAccountRepository(container.engine).add_first(PLACEHOLDER_ADMIN)
        now = datetime.now(UTC)
        await SqliteSessionRepository(container.engine).add(
            Session(
                token_hash=hash_token(DEMO_COOKIE),
                account_id=PLACEHOLDER_ADMIN.id,
                created_at=now,
                last_used_at=now,
            )
        )
        repository = SqliteLibraryRepository(container.engine)
        for library in DEMO_LIBRARIES:
            await repository.save(library)


class OfflineGit:
    """Real git for the local fixture servers; a reachable `main` for hosts no test may dial."""

    def __init__(self, local: GitRemote) -> None:
        self.local = local

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        del repository
        return None

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: Credential | None = None
    ) -> RemoteRefs:
        if repository.url.startswith(("file:", "http://127.0.0.1")):
            return await self.local.list_refs(repository, *patterns, credential=credential)
        return RemoteRefs(default_branch="main")


@given("ExactDocs is running with the demo catalog")
def step_running(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)  # runs the app's shutdown after the scenario
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    settings = Settings(data_dir=data_dir)
    context.settings = settings
    asyncio.run(store_demo_catalog(settings))
    context.client = stack.enter_context(
        TestClient(
            create_app(Container.build(settings, remote=OfflineGit(GitCli.locate()))),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@when("I list the libraries over the REST API")
def step_list(context: Context) -> None:
    context.response = context.client.get("/api/v1/libraries")


@when('I request the library "{library_id}"')
def step_get(context: Context, library_id: str) -> None:
    context.response = context.client.get(f"/api/v1/libraries{library_id}")


@when('I request the version "{target}"')
def step_get_version(context: Context, target: str) -> None:
    owner, repo, ref = target.removeprefix("/").split("/", 2)
    context.response = context.client.get(f"/api/v1/libraries/{owner}/{repo}/versions/{ref}")


@then("the response status is {status:d}")
def step_status(context: Context, status: int) -> None:
    assert context.response.status_code == status, context.response.text


@then('the error code is "{code}"')
def step_error(context: Context, code: str) -> None:
    assert context.response.json()["error"] == code


@then("the libraries are:")
def step_libraries(context: Context) -> None:
    expected = [
        (row["id"], row["versions"].split(", "), row["default version"])
        for row in context.table or []
    ]
    actual = [
        (lib["id"], [v["ref"] for v in lib["refs"]], lib["default_version"])
        for lib in context.response.json()["libraries"]
    ]
    assert actual == expected, actual


@then('the default version of "{library_id}" is "{ref}"')
def step_default_version(context: Context, library_id: str, ref: str) -> None:
    body = context.response.json()
    assert (body["id"], body["default_version"]) == (library_id, ref), body


@then('the version used is "{ref}" of "{library_id}"')
def step_version_used(context: Context, ref: str, library_id: str) -> None:
    body = context.response.json()
    assert (body["library"], body["ref"]) == (library_id, ref), body


@when("I fetch the OpenAPI description")
def step_openapi(context: Context) -> None:
    context.response = context.client.get("/api/v1/openapi.json")


@then("every operation has a stable operation ID and documented error responses")
def step_operations(context: Context) -> None:
    paths = context.response.json()["paths"]
    operations = [op for item in paths.values() for op in item.values()]
    assert operations
    for op in operations:
        tag, _, name = op["operationId"].partition("-")
        assert tag in op["tags"], op["operationId"]
        assert name, op["operationId"]
        assert {"404", "422"} <= set(op["responses"]), op["operationId"]


@then("the error has a message")
def step_error_message(context: Context) -> None:
    assert context.response.json()["detail"]
