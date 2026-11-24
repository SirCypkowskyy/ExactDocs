"""Bootstrap's usage meter (#510): which served request counts as what, and the background write."""

import asyncio

import pytest

from exactdocs.bootstrap import usage_meter
from exactdocs.bootstrap.caller import bind_caller, reset_caller
from exactdocs.bootstrap.usage_meter import MeteredAnswer, MeteredSearchAll, UsageMeter, flushing
from exactdocs.retrieval.dtos import (
    AnswerLibraryOut,
    AnswerQuery,
    AnswerResult,
    SearchAllQuery,
    SearchAllResult,
)
from exactdocs.retrieval.ports.driven import AnswerProgress
from exactdocs.usage.dtos import FlushedUsage, FlushUsageCommand, RecordUsageCommand
from exactdocs.usage.models import Operation

ACME, BETA = "/acme/docs", "/beta/docs"


class Recorded:
    def __init__(self, *, fail: bool = False) -> None:
        self.commands: list[RecordUsageCommand] = []
        self.fail = fail

    async def __call__(self, command: RecordUsageCommand) -> None:
        if self.fail:
            message = "tally broken"
            raise RuntimeError(message)
        self.commands.append(command)


class Flushes:
    def __init__(self, *, failures: int = 0, wanted: int = 0) -> None:
        self.calls = 0
        self.failures = failures
        self.wanted = wanted
        self.reached = asyncio.Event()

    async def __call__(self, command: FlushUsageCommand) -> FlushedUsage:
        del command
        self.calls += 1
        if self.calls >= self.wanted:
            self.reached.set()
        if self.calls <= self.failures:
            message = "database is locked"
            raise OSError(message)
        return FlushedUsage(written=0, dropped=0)


async def test_a_count_names_the_account_of_the_request_and_never_fails_it() -> None:
    recorded = Recorded()
    meter = UsageMeter(record_usage=recorded)
    binding = bind_caller("id-alice")
    try:
        await meter.count(Operation.READ, [ACME])
    finally:
        reset_caller(binding)
    await meter.count(Operation.SEARCH, [])

    assert [(c.operation, c.libraries, c.account_id, c.token_id) for c in recorded.commands] == [
        (Operation.READ, [ACME], "id-alice", None),
        (Operation.SEARCH, [], None, None),
    ]
    await UsageMeter(record_usage=Recorded(fail=True)).count(Operation.READ, [])  # logged only


@pytest.mark.parametrize(
    ("library", "libraries", "counted"),
    [
        (ACME, [], [ACME]),
        (None, [ACME, BETA], [ACME, BETA]),
        (ACME, [BETA], [BETA, ACME]),
        (None, [], []),
    ],
)
async def test_a_search_of_several_libraries_names_every_one_chosen(
    library: str | None, libraries: list[str], counted: list[str]
) -> None:
    recorded = Recorded()

    async def search(query: SearchAllQuery, *, caller: str | None = None) -> SearchAllResult:
        del query, caller
        return SearchAllResult.model_construct()

    metered = MeteredSearchAll(search_all_libraries=search, meter=UsageMeter(record_usage=recorded))
    await metered(
        SearchAllQuery.model_validate({"query": "x", "library": library, "libraries": libraries})
    )

    assert [c.libraries for c in recorded.commands] == [counted]


@pytest.mark.parametrize(
    ("chosen", "read", "counted"),
    [([], [ACME], [ACME]), ([ACME, BETA], [], [ACME, BETA]), ([], [], [])],
)
async def test_an_answer_counts_to_the_libraries_it_read_or_else_those_chosen(
    chosen: list[str], read: list[str], counted: list[str]
) -> None:
    recorded = Recorded()

    async def answer(
        query: AnswerQuery,
        *,
        caller: str | None = None,
        progress: AnswerProgress | None = None,
    ) -> AnswerResult:
        del query, caller, progress
        return AnswerResult.model_construct(
            libraries=[AnswerLibraryOut(library=name, version="v1") for name in read]
        )

    metered = MeteredAnswer(answer_question=answer, meter=UsageMeter(record_usage=recorded))
    await metered(AnswerQuery.model_validate({"question": "how?", "libraries": chosen}))

    assert [(c.operation, c.libraries) for c in recorded.commands] == [(Operation.ANSWER, counted)]


async def test_a_failing_request_is_not_counted() -> None:
    recorded = Recorded()

    async def search(query: SearchAllQuery, *, caller: str | None = None) -> SearchAllResult:
        del query, caller
        message = "index down"
        raise RuntimeError(message)

    metered = MeteredSearchAll(search_all_libraries=search, meter=UsageMeter(record_usage=recorded))
    with pytest.raises(RuntimeError, match="index down"):
        await metered(SearchAllQuery(query="x"))

    assert recorded.commands == []


async def test_the_counts_are_written_while_serving_and_once_more_at_the_stop() -> None:
    flushes = Flushes(failures=1, wanted=3)  # the first write fails: the loop goes on

    async with flushing(flushes, every=0.01):
        async with asyncio.timeout(5):
            await flushes.reached.wait()
        during = flushes.calls

    assert flushes.calls == during + 1


async def test_a_last_write_that_hangs_does_not_hold_the_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(usage_meter, "USAGE_STOP_SECONDS", 0.05)
    stalled = asyncio.Event()

    async def hang(command: FlushUsageCommand) -> FlushedUsage:
        del command
        stalled.set()
        await asyncio.Event().wait()
        return FlushedUsage(written=0, dropped=0)

    async with asyncio.timeout(5):
        async with flushing(hang, every=3600):
            pass

    assert stalled.is_set()
