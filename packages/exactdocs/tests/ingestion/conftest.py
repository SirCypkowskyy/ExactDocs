import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from exactdocs.ingestion import IngestionModule
from exactdocs.ingestion.adapters.driven.git_cli import MissingGit
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.models import JobKind
from exactdocs.ingestion.ports import JobHandler, JobRepository, RecoveryHook
from exactdocs.ingestion.ports.driven import ManualTagStore


class _NoLibraryIds:
    async def is_taken(self, library_id: str) -> bool:
        del library_id
        return False


class _NoLibraries:
    async def add(self, library: object) -> str:
        raise NotImplementedError

    async def discard(self, library_id: str) -> None:
        raise NotImplementedError


class FakeClock:
    """A kernel ``Clock`` that moves one second on every reading."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        self.moment += timedelta(seconds=1)
        return self.moment


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def jobs() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def build_module(jobs: InMemoryJobRepository, clock: FakeClock) -> Callable[..., IngestionModule]:
    """Build the module over ``jobs`` (or another ``repository``) with the fake clock."""

    def build(
        handlers: dict[JobKind, JobHandler] | None = None,
        recovery_hooks: dict[JobKind, RecoveryHook] | None = None,
        *,
        repository: JobRepository | None = None,
        manual_tags: ManualTagStore | None = None,
    ) -> IngestionModule:
        return IngestionModule.build(
            jobs=repository or jobs,
            clock=clock,
            remote=MissingGit(),
            library_ids=_NoLibraryIds(),
            libraries=_NoLibraries(),
            removals=NoRemovals(),
            index=NoIndex(),
            handlers=handlers or {},
            recovery_hooks=recovery_hooks or {},
            manual_tags=manual_tags,
        )

    return build


@pytest.fixture
def eventually() -> Callable[..., Awaitable[None]]:
    """Wait until an async condition holds; fail the test after a timeout."""

    async def wait(condition: Callable[[], Awaitable[bool]], seconds: float = 5) -> None:
        deadline = asyncio.get_running_loop().time() + seconds
        while not await condition():
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError
            await asyncio.sleep(0.01)

    return wait
