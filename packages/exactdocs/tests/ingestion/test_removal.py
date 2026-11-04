"""Removing a version or library, and the job that frees what it left, on fake ports."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from exactdocs.ingestion import IngestionModule, collect_job
from exactdocs.ingestion.adapters.driven.git_cli import MissingGit
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.dtos import (
    EnqueueJobCommand,
    GetJobQuery,
    RemoveLibraryCommand,
    RemoveVersionCommand,
)
from exactdocs.ingestion.errors import ImportInProgressError
from exactdocs.ingestion.models import COLLECT_JOB, IMPORT_JOB, Collected, JobKind, Removed
from exactdocs_kernel import NotFoundError, SystemClock

LIBRARY = "/acme/payments"


class Catalog(NoRemovals):
    def __init__(self) -> None:
        self.removed: list[tuple[str, str | None]] = []

    async def remove_version(self, library: str, ref: str) -> Removed:
        if ref == "v0":
            message = "no such version"
            raise NotFoundError(message)
        self.removed.append((library, ref))
        return Removed(library=library, ref=ref, manifest_ids=("m1", "m2"), default_ref="v1")

    async def remove_library(self, library: str) -> Removed:
        self.removed.append((library, None))
        return Removed(library=library, ref=None, manifest_ids=("m1",), default_ref=None)


class Index(NoIndex):
    def __init__(self, *, broken: bool = False) -> None:
        self.removed: list[Sequence[str]] = []
        self.broken = broken

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        if self.broken:
            raise OSError
        self.removed.append(manifest_ids)


@dataclass(slots=True)
class Collector:
    name: str
    calls: list[str]
    fails: bool = False
    graces: list[int] = field(default_factory=list)

    async def collect(self, *, grace_seconds: int) -> Collected:
        self.calls.append(self.name)
        self.graces.append(grace_seconds)
        if self.fails:
            raise OSError
        return Collected(deleted=1)


async def nothing(*_: object) -> None:
    return None


@dataclass(slots=True)
class World:
    module: IngestionModule
    jobs: InMemoryJobRepository
    catalog: Catalog
    index: Index
    calls: list[str]

    async def import_job(self, version: str, *, running: bool = False) -> None:
        job = await self.module.enqueue_job(
            EnqueueJobCommand(kind=IMPORT_JOB, library=LIBRARY, version=version)
        )
        assert job.state.value == "queued"
        if running:
            assert await self.jobs.claim_next(SystemClock().now()) is not None


def build(*, with_collect: bool = True, broken_index: bool = False) -> World:
    jobs, catalog, index, calls = InMemoryJobRepository(), Catalog(), Index(broken=broken_index), []
    handlers: dict[JobKind, object] = {IMPORT_JOB: nothing}
    if with_collect:
        handlers |= collect_job(
            collectors=[Collector("catalog", calls), Collector("retrieval", calls)]
        )
    module = IngestionModule.build(
        jobs=jobs,
        clock=SystemClock(),
        remote=MissingGit(),
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        removals=catalog,
        index=index,
        handlers=handlers,  # ty: ignore[invalid-argument-type]
    )
    return World(module, jobs, catalog, index, calls)


async def test_removing_a_version_forgets_its_chunks_and_queues_the_collection() -> None:
    world = build()

    done = await world.module.remove_version(
        RemoveVersionCommand(library="/Acme/Payments", ref="v2")
    )

    assert (done.library, done.ref, done.default_version) == (LIBRARY, "v2", "v1")
    assert world.catalog.removed == [(LIBRARY, "v2")]
    assert world.index.removed == [("m1", "m2")]
    (queued,) = await world.jobs.list_for_library(LIBRARY)
    assert (queued.id, queued.kind, queued.state.value) == (
        done.collection_job_id,
        COLLECT_JOB,
        "queued",
    )


async def test_removing_a_library_has_no_default_and_queues_the_collection() -> None:
    world = build()

    done = await world.module.remove_library(RemoveLibraryCommand(library=LIBRARY))

    assert (done.ref, done.default_version) == (None, None)
    assert world.catalog.removed == [(LIBRARY, None)]
    assert done.collection_job_id is not None


@pytest.mark.parametrize("running", [False, True])
async def test_removal_is_refused_while_an_import_of_that_version_is_unfinished(
    running: bool,
) -> None:
    world = build()
    await world.import_job("v2", running=running)

    with pytest.raises(ImportInProgressError, match="queued or running"):
        await world.module.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v2"))

    assert world.catalog.removed == []  # nothing was cancelled or removed
    assert world.index.removed == []


async def test_removing_a_version_is_allowed_while_another_version_imports() -> None:
    world = build()
    await world.import_job("v3", running=True)

    await world.module.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v2"))

    assert world.catalog.removed == [(LIBRARY, "v2")]


@pytest.mark.parametrize("running", [False, True])
async def test_removing_a_library_is_refused_while_any_import_of_it_is_unfinished(
    running: bool,
) -> None:
    world = build()
    await world.import_job("v3", running=running)

    with pytest.raises(ImportInProgressError):
        await world.module.remove_library(RemoveLibraryCommand(library=LIBRARY))

    assert world.catalog.removed == []


async def test_removal_is_allowed_again_once_the_import_has_finished() -> None:
    world = build()
    await world.import_job("v2")
    assert await world.module.run_next_job() is True

    await world.module.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v2"))

    assert world.catalog.removed == [(LIBRARY, "v2")]


async def test_an_unknown_version_is_not_found_and_queues_nothing() -> None:
    world = build()

    with pytest.raises(NotFoundError):
        await world.module.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v0"))

    assert await world.jobs.list_for_library(LIBRARY) == []
    assert world.index.removed == []


async def test_a_removal_survives_chunks_that_cannot_be_dropped_and_a_collection_that_cannot_queue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = build(with_collect=False, broken_index=True)

    with caplog.at_level(logging.ERROR):
        done = await world.module.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v2"))

    assert world.catalog.removed == [(LIBRARY, "v2")]  # the catalog is the truth for readers
    assert done.collection_job_id is None
    assert "could not remove the chunks" in caplog.text


async def test_the_collection_job_runs_the_catalog_before_retrieval_and_succeeds() -> None:
    world = build()
    done = await world.module.remove_library(RemoveLibraryCommand(library=LIBRARY))

    assert await world.module.run_next_job() is True

    assert world.calls == ["catalog", "retrieval"]
    assert done.collection_job_id is not None
    finished = await world.module.get_job(GetJobQuery(job_id=done.collection_job_id))
    assert finished.state.value == "succeeded"
    assert (finished.done, finished.total) == (2, 2)


async def test_a_failing_collector_fails_the_job_after_the_others_ran() -> None:
    calls: list[str] = []
    handlers = collect_job(
        collectors=[Collector("catalog", calls, fails=True), Collector("retrieval", calls)],
        grace_seconds=60,
    )
    jobs = InMemoryJobRepository()
    module = IngestionModule.build(
        jobs=jobs,
        clock=SystemClock(),
        remote=MissingGit(),
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        removals=NoRemovals(),
        index=NoIndex(),
        handlers=handlers,
    )
    queued = await module.enqueue_job(EnqueueJobCommand(kind=COLLECT_JOB, library=LIBRARY))

    await module.run_next_job()

    assert calls == ["catalog", "retrieval"]
    (job,) = await jobs.list_for_library(LIBRARY)
    assert (job.id, job.state.value) == (queued.id, "failed")


async def test_collection_jobs_are_not_a_library_s_sync_state() -> None:
    world = build()
    await world.import_job("v2")
    await world.module.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v1"))

    latest = await world.module.list_latest_jobs()

    assert [(j.kind, j.version) for j in latest.jobs] == [("import", "v2")]
