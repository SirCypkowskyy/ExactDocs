"""RET-01: an ``embed`` job embeds one version in the background, a durable step per batch."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryCheckpoints, InMemoryJobRepository
from exactdocs.ingestion.constants import EMBED_JOB, IMPORT_JOB, JobKind
from exactdocs.ingestion.dtos import EnqueueJobCommand, GetJobQuery, QueueEmbeddingCommand
from exactdocs.ingestion.errors import UnknownJobKindError
from exactdocs.ingestion.models import (
    EmbeddedBatch,
    EmbedPlan,
    Job,
    JobId,
    JobState,
    ProblemCode,
    VersionToEmbed,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs.ingestion.ports.driven import JobProgress
from exactdocs.ingestion.use_cases import EmbedAfterJob, EmbeddingQueue, EmbedVersionUseCase

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"


class Killed(BaseException):
    """The process died in the middle of a step."""


class Clock:
    def now(self) -> datetime:
        return T0


@dataclass(slots=True)
class Runner:
    submitted: list[Job] = field(default_factory=list)

    async def submit(self, job: Job) -> None:
        self.submitted.append(job)


@dataclass(slots=True)
class Embedder:
    """A ``VersionEmbedder`` over ``missing`` chunks per version, ``batch`` per call."""

    missing: dict[tuple[str, str], int] = field(default_factory=dict)
    batch: int = 2
    created: bool = False
    skipped: str | None = None
    kill_at_batch: int | None = None
    batches: int = 0
    finished: list[int] = field(default_factory=list)
    planned: list[tuple[str, str]] = field(default_factory=list)

    async def plan(self, library: str, ref: str) -> EmbedPlan:
        self.planned.append((library, ref))
        if self.skipped is not None:
            return EmbedPlan(space_id=None, manifest_id=None, missing=0, created=False,
                             skipped=self.skipped)  # fmt: skip
        return EmbedPlan(
            space_id=7,
            manifest_id=f"{library}@{ref}",
            missing=self.missing[library, ref],
            created=self.created,
            skipped=None,
        )

    async def embed_batch(self, library: str, ref: str, plan: EmbedPlan) -> EmbeddedBatch:
        assert plan.space_id == 7
        self.batches += 1
        if self.batches == self.kill_at_batch:
            raise Killed
        done = min(self.batch, self.missing[library, ref])
        self.missing[library, ref] -= done
        return EmbeddedBatch(embedded=done, finished=self.missing[library, ref] == 0)

    async def finish(self, plan: EmbedPlan) -> None:
        assert plan.space_id is not None
        self.finished.append(plan.space_id)

    async def unembedded(self, library: str | None) -> Sequence[VersionToEmbed]:
        return [
            VersionToEmbed(library=lib, ref=ref)
            for (lib, ref), left in sorted(self.missing.items())
            if left and library in {None, lib}
        ]


@dataclass(slots=True)
class Progress:
    reports: list[tuple[int, int]] = field(default_factory=list)

    async def report(self, *, done: int, total: int) -> None:
        self.reports.append((done, total))

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        del path, code, reason

    async def chunking(self, *, chunked: int, reused: int) -> None:
        del chunked, reused

    async def parsing(self, *, parsed: int, taken: int) -> None:
        del parsed, taken


def _job(
    kind: JobKind = EMBED_JOB, ref: str | None = "v1", state: JobState = JobState.RUNNING
) -> Job:
    job = Job.queued(job_id=JobId(f"{kind}-{ref}"), kind=kind, library=LIB, version=ref, now=T0)
    return job if state is JobState.QUEUED else job.started(T0)


@dataclass(slots=True)
class World:
    embedder: Embedder
    jobs: InMemoryJobRepository = field(default_factory=InMemoryJobRepository)
    runner: Runner = field(default_factory=Runner)
    steps: InMemoryCheckpoints = field(default_factory=InMemoryCheckpoints)

    @property
    def queue(self) -> EmbeddingQueue:
        return EmbeddingQueue(
            jobs=self.jobs, runner=self.runner, clock=Clock(), embedder=self.embedder
        )

    def handler(self) -> EmbedVersionUseCase:
        return EmbedVersionUseCase(embedder=self.embedder, queue=self.queue, checkpoints=self.steps)


async def test_a_version_is_embedded_batch_by_batch_then_the_spaces_switch() -> None:
    world = World(Embedder(missing={(LIB, "v1"): 5}))
    progress = Progress()

    await world.handler()(_job(), progress)

    assert world.steps.ran == [
        "plan the embedding",
        "embed batch 1",
        "embed batch 2",
        "embed batch 3",
        "switch embedding spaces",
    ]
    assert world.embedder.finished == [7]
    assert progress.reports == [(0, 5), (2, 5), (4, 5), (5, 5)]


async def test_a_killed_job_resumes_at_its_first_unfinished_batch() -> None:
    embedder = Embedder(missing={(LIB, "v1"): 6}, kill_at_batch=3)
    world = World(embedder)
    with pytest.raises(Killed):
        await world.handler()(_job(), Progress())

    world.steps = world.steps.resumed()
    embedder.kill_at_batch = None
    await world.handler()(_job(), Progress())

    assert world.steps.ran == ["embed batch 3", "switch embedding spaces"]
    assert embedder.batches == 4  # 1, 2, the killed 3, then 3 again: 1 and 2 were replayed
    assert embedder.planned == [(LIB, "v1")]
    assert embedder.missing[LIB, "v1"] == 0


async def test_a_skipped_plan_sends_nothing() -> None:
    world = World(Embedder(skipped="ai_off"))

    await world.handler()(_job(), Progress())

    assert world.steps.ran == ["plan the embedding"]
    assert (world.embedder.batches, world.embedder.finished) == (0, [])


async def test_a_new_space_queues_every_other_version_once() -> None:
    embedder = Embedder(missing={(LIB, "v1"): 1, (LIB, "v2"): 1, (LIB, "v3"): 1}, created=True)
    world = World(embedder)
    await world.jobs.add(_job(ref="v3", state=JobState.QUEUED))  # queued already

    await world.handler()(_job(), Progress())

    assert [(j.kind, j.version) for j in world.runner.submitted] == [(EMBED_JOB, "v2")]
    assert "queue the other versions" in world.steps.ran


async def test_a_running_embed_job_does_not_count_as_queued() -> None:
    world = World(Embedder(missing={(LIB, "v1"): 1}))
    await world.jobs.add(_job(ref="v1"))  # running, possibly for a model changed since

    queued = await world.queue(LIB)

    assert queued == 1


async def test_an_import_queues_the_embedding_of_its_library_when_it_succeeds() -> None:
    world = World(Embedder(missing={(LIB, "v1"): 1, ("/other/lib", "v1"): 1}))
    imported: list[str] = []

    async def importer(job: Job, progress: JobProgress, /) -> None:
        del progress
        imported.append(job.id)

    await EmbedAfterJob(inner=importer, queue=world.queue)(_job(IMPORT_JOB), Progress())

    assert imported == [f"{IMPORT_JOB}-v1"]
    assert [(j.library, j.version) for j in world.runner.submitted] == [(LIB, "v1")]


async def test_a_failed_import_queues_nothing_and_a_failed_queue_fails_no_import() -> None:
    world = World(Embedder(missing={(LIB, "v1"): 1}))

    async def fails(job: Job, progress: JobProgress, /) -> None:
        del job, progress
        raise RuntimeError

    with pytest.raises(RuntimeError):
        await EmbedAfterJob(inner=fails, queue=world.queue)(_job(IMPORT_JOB), Progress())
    assert world.runner.submitted == []

    class Broken(Embedder):
        async def unembedded(self, library: str | None) -> Sequence[VersionToEmbed]:
            raise RuntimeError(library)

    async def succeeds(job: Job, progress: JobProgress, /) -> None:
        del job, progress

    broken = World(Broken())
    await EmbedAfterJob(inner=succeeds, queue=broken.queue)(_job(IMPORT_JOB), Progress())


async def test_the_module_runs_embed_jobs_and_embeds_after_imports_only_with_an_embedder(
    build_module: Callable[..., IngestionModule],
) -> None:
    imported: list[str] = []

    async def importer(job: Job, progress: JobProgress, /) -> None:
        del progress
        imported.append(job.library)

    without = build_module({IMPORT_JOB: importer})
    assert (await without.queue_embedding(QueueEmbeddingCommand())).queued == 0
    with pytest.raises(UnknownJobKindError):
        await without.enqueue_job(EnqueueJobCommand(kind=EMBED_JOB, library=LIB, version="v1"))

    embedder = Embedder(missing={(LIB, "v1"): 3})
    module = build_module({IMPORT_JOB: importer}, embedder=embedder)
    job = await module.enqueue_job(EnqueueJobCommand(kind=EMBED_JOB, library=LIB, version="v1"))
    assert await module.run_next_job()
    assert (await module.get_job(GetJobQuery(job_id=job.id))).state is JobState.SUCCEEDED
    assert embedder.missing[LIB, "v1"] == 0

    embedder.missing[LIB, "v2"] = 1
    await module.enqueue_job(EnqueueJobCommand(kind=IMPORT_JOB, library=LIB, version="v2"))
    assert await module.run_next_job()  # the import, which queues the embedding of v2
    assert await module.run_next_job()  # the embedding
    assert imported == [LIB]
    assert embedder.missing[LIB, "v2"] == 0
