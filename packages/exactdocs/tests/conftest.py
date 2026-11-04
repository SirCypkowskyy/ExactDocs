from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exactdocs.bootstrap.container import Container
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
from fixture_repo import DocsRepo, served

IMPORTED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _version(ref: str, kind: RefKind, sha: str) -> Version:
    return Version(
        ref=VersionRef(ref), kind=kind, commit_sha=sha.ljust(40, "0"), imported_at=IMPORTED
    )


# Shaped like the fixture docs repository (two tags and a branch); ExactDocs itself starts empty.
DEMO_LIBRARIES = [
    Library(
        id=LibraryId("/acme/payments"),
        title="Payments",
        description="Payment processing SDK",
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


# An admin that can never sign in (the "hash" is not a hash): it only ends the setup state, so
# the `/api/v1` guard lets the tests through.
NOT_A_HASH = "not-a-hash"
PLACEHOLDER_ADMIN = Account(
    id=AccountId("00000000000000000000000000000001"),
    username=Username("admin"),
    password_hash=NOT_A_HASH,
    role=Role.ADMIN,
    created_at=datetime(2026, 1, 1, tzinfo=UTC),
)


# The admin is signed in with this session, planted directly (signing in would cost a hash).
DEMO_COOKIE = "demo-session-token"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never touch the real data directory: every test starts on an empty one."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("EXACTDOCS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("EXACTDOCS_DATABASE_URL", raising=False)
    return data_dir


@pytest.fixture
async def demo_catalog() -> dict[str, str]:
    """Set the instance up and store the demo libraries, as earlier runs of the app would have.

    Returns:
        The cookies of the admin's signed-in session, for the test's HTTP client.
    """
    container = Container.build(Settings())
    async with container.running():
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
    return {SESSION_COOKIE: DEMO_COOKIE}


@pytest.fixture(scope="session")
def docs_repo(tmp_path_factory: pytest.TempPathFactory) -> Generator[DocsRepo]:
    """The fixture docs repository, built once per run.

    Yields:
        The repository path and its ``file://`` and HTTP URLs.
    """
    with served(tmp_path_factory.mktemp("fixtures")) as repo:
        yield repo
