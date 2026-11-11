"""RET-08: turning repo guidance on re-imports the library, so its versions keep the files."""

import logging
from dataclasses import dataclass, field

import pytest

from exactdocs.bootstrap.repo_guidance import SetRetrievalThenReprocess
from exactdocs.ingestion.dtos import EnqueueJobCommand, JobSummary
from exactdocs.retrieval.dtos import (
    GetLibraryRetrievalQuery,
    LibraryRetrievalOut,
    RepoGuidance,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.models import RetrievalMode

LIB = "/Acme/Payments"


def _out(guidance: RepoGuidance) -> LibraryRetrievalOut:
    return LibraryRetrievalOut(
        library=LIB,
        mode=None,
        instance_mode=None,
        effective_mode=RetrievalMode.BM25,
        available_modes=[RetrievalMode.BM25],
        configured_roles=[],
        effective_rerank_top_n=32,
        repo_guidance=guidance,
    )


@dataclass(slots=True)
class Retrieval:
    stored: RepoGuidance

    async def get(self, query: GetLibraryRetrievalQuery) -> LibraryRetrievalOut:
        del query
        return _out(self.stored)

    async def set(self, command: SetLibraryRetrievalCommand) -> LibraryRetrievalOut:
        self.stored = command.repo_guidance
        return _out(self.stored)


@dataclass(slots=True)
class Jobs:
    queued: list[EnqueueJobCommand] = field(default_factory=list)
    broken: bool = False

    async def __call__(self, command: EnqueueJobCommand) -> JobSummary:
        if self.broken:
            message = "the queue is down"
            raise RuntimeError(message)
        self.queued.append(command)
        return JobSummary.model_construct(id="j1", kind=command.kind, library=command.library)


def _glue(stored: RepoGuidance, jobs: Jobs) -> tuple[SetRetrievalThenReprocess, Retrieval]:
    retrieval = Retrieval(stored=stored)
    glue = SetRetrievalThenReprocess(
        get_library_retrieval=retrieval.get,
        set_library_retrieval=retrieval.set,
        enqueue_job=jobs,
    )
    return glue, retrieval


@pytest.mark.parametrize("wanted", [RepoGuidance.NOTES, RepoGuidance.TRUSTED])
async def test_turning_guidance_on_queues_one_reprocess_of_the_library(
    wanted: RepoGuidance,
) -> None:
    jobs = Jobs()
    glue, _ = _glue(RepoGuidance.OFF, jobs)

    saved = await glue(SetLibraryRetrievalCommand(library=LIB, repo_guidance=wanted))

    assert saved.repo_guidance is wanted
    assert [(j.kind, j.library) for j in jobs.queued] == [("reprocess", "/acme/payments")]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (RepoGuidance.OFF, RepoGuidance.OFF),
        (RepoGuidance.NOTES, RepoGuidance.TRUSTED),
        (RepoGuidance.TRUSTED, RepoGuidance.NOTES),
        (RepoGuidance.NOTES, RepoGuidance.OFF),
    ],
)
async def test_other_changes_take_effect_at_search_time_and_queue_nothing(
    before: RepoGuidance, after: RepoGuidance
) -> None:
    jobs = Jobs()
    glue, _ = _glue(before, jobs)

    await glue(SetLibraryRetrievalCommand(library=LIB, repo_guidance=after))

    assert jobs.queued == []


async def test_a_queue_that_fails_keeps_the_setting_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    jobs = Jobs(broken=True)
    glue, retrieval = _glue(RepoGuidance.OFF, jobs)

    saved = await glue(SetLibraryRetrievalCommand(library=LIB, repo_guidance=RepoGuidance.NOTES))

    assert saved.repo_guidance is retrieval.stored is RepoGuidance.NOTES
    assert [r.levelno for r in caplog.records if "repo guidance" in r.getMessage()] == [
        logging.ERROR
    ]
