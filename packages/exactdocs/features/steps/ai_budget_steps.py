"""Steps for AI budgets and the LLM search rate limit (#95).

The agentic mode (#98) does not exist yet: a stand-in ``agentic`` pipeline is the search that
"needs an LLM step" (HyDE's own budget scenario is in hyde.feature), and a stand-in BM25
pipeline reports whether it was asked to rerank. Spend is put in the ledger directly, as earlier
calls would have recorded it; the retrieval clock is fixed, so a scenario can move it past a
window's end.
"""

import math
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.ingestion.dtos import EnqueueJobCommand
from exactdocs.retrieval.adapters.driven.memory import StaticModelRoles
from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.models import (
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    RetrievalMode,
    SpendEntry,
    SpendWindow,
)
from exactdocs.retrieval.ports.driven import RetrievalPipeline
from fake_llm import FakeGateway, gateway
from steps.embedding_steps import AnswersHybrid, wait_for_embedding
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.hyde_steps import use_up_the_daily_budget
from steps.search_steps import LIBRARY

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
LAST_HOUR_OF_NOVEMBER = datetime(2026, 11, 30, 23, 0, tzinfo=UTC)
AFTER_THE_MONTH = datetime(2026, 12, 1, 0, 0, 5, tzinfo=UTC)
ONE_USD = 1_000_000


@dataclass(slots=True)
class MovableClock:
    """The retrieval clock of a scenario: fixed, and moved by hand."""

    at: datetime = LAST_HOUR_OF_NOVEMBER

    def now(self) -> datetime:
        return self.at


class StandInAgentic:
    """Answers ``agentic`` with no hits: the search whose LLM step a budget may skip."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        del request
        return PipelineAnswer(
            mode=RetrievalMode.AGENTIC, hits=(), candidates=0, reranked=0, complete=True
        )


def serve_budgets(
    context: Context,
    ai: dict[str, Any],
    *,
    roles: frozenset[ModelRole] | None = None,
    pipelines: dict[RetrievalMode, RetrievalPipeline] | None = None,
) -> None:
    """Serve the same data again with this ``ai`` configuration and a movable retrieval clock.

    Args:
        context: The behave context.
        ai: The ``ai`` settings.
        roles: Model roles that count as configured, instead of resolving profiles.
        pipelines: Stand-in pipelines.
    """
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.clock = MovableClock()
    settings = context.settings.model_copy(update={"ai": AiSettings.model_validate(ai)})
    container = Container.build(
        settings,
        model_roles=None if roles is None else StaticModelRoles(roles=roles),
        pipelines=pipelines,
        clock=context.clock,
    )
    context.container = container
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


def record_spend(context: Context, kind: str, scope_id: str, window: SpendWindow, usd: int) -> None:
    """Record spend as earlier calls would have, in the current window.

    Args:
        context: The behave context.
        kind: The scope kind.
        scope_id: The scope.
        window: Day or month.
        usd: Millionths of a US dollar.
    """
    entry = SpendEntry(
        scope_kind=kind,
        scope_id=scope_id,
        window=window,
        window_start=window.start(context.clock.at),
        input_tokens=1000,
        requests=3,
        usd_micros=usd,
    )
    ledger = SqliteSpendLedger(engine=context.container.engine)
    context.client.portal.call(ledger.add, [entry])


def _search(context: Context, mode: str | None = None) -> dict[str, Any]:
    """Search the fixture library's default version.

    Args:
        context: The behave context.
        mode: The mode asked for, if any.

    Returns:
        The result.
    """
    params = {"q": "retry_policy"} | ({"mode": mode} if mode else {})
    response = context.client.get(SEARCH, params=params)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given("the instance's daily LLM budget is used up")
def step_daily_budget_used_up(context: Context) -> None:
    if getattr(context, "hyde", False):  # hyde.feature: the instance is configured already
        use_up_the_daily_budget(context)
        return
    serve_budgets(
        context,
        {"budgets": {"daily_usd": 1}},
        roles=frozenset({ModelRole.LLM}),
        pipelines={RetrievalMode.AGENTIC: StandInAgentic()},
    )
    assert _search(context, "agentic")["retrieval_mode"] == "agentic"  # within budget: LLM step
    record_spend(context, "instance", "", SpendWindow.DAY, ONE_USD)


@when("a search needs an LLM step")
def step_search_needs_llm(context: Context) -> None:
    context.result = _search(context, "agentic")


@then('the step is skipped and the result names the cheaper mode with fallback reason "{reason}"')
def step_skipped_for_budget(context: Context, reason: str) -> None:
    body = context.result
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("bm25", reason), body
    assert body["results"], "BM25 answered"


@given("a caller is limited to {limit:d} LLM searches per minute")
def step_rate_limited(context: Context, limit: int) -> None:
    serve_budgets(
        context,
        {"budgets": {"llm_searches_per_minute": limit}},
        roles=frozenset({ModelRole.LLM}),
        pipelines={RetrievalMode.AGENTIC: StandInAgentic()},
    )
    context.limit = limit


@when("it makes the 11th within a minute")
def step_eleventh(context: Context) -> None:
    earlier = [_search(context, "agentic") for _ in range(context.limit)]
    assert all(b["retrieval_mode"] == "agentic" and b["fallback_reason"] is None for b in earlier)
    context.result = _search(context, "agentic")


@then('the result answers without the LLM step, with fallback reason "{reason}"')
def step_rate_fallback(context: Context, reason: str) -> None:
    body = context.result
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("bm25", reason), body
    assert body["results"], "BM25 answered"


def _embedding_ai(endpoint: FakeGateway) -> dict[str, Any]:
    """Configure an embedding model with a price and a monthly embedding budget, and choose hybrid.

    Hybrid is no default (docs/evals.md): the instance chooses it, so a search shows it waits for
    embedding.

    Args:
        endpoint: The fake gateway.

    Returns:
        The ``ai`` settings.
    """
    return {
        "mode": "hybrid",
        "providers": {"corp": {"kind": "openai-compatible", "base_url": endpoint.v1}},
        "embedding": {"model": "corp:e5", "dimensions": 3},
        "prices": {"corp:e5": {"input_usd_per_mtok": 0.02}},
        "budgets": {"monthly_embedding_usd": 1},
    }


@given("the instance's monthly embedding budget is used up")
def step_embedding_budget_used_up(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.endpoint = stack.enter_context(gateway())
    serve_budgets(
        context,
        _embedding_ai(context.endpoint),
        pipelines={RetrievalMode.HYBRID: AnswersHybrid()},
    )
    record_spend(context, "embedding", "", SpendWindow.MONTH, ONE_USD)


@when("an embed job runs")
def step_embed_job_runs(context: Context) -> None:
    command = EnqueueJobCommand(kind="embed", library=LIBRARY, version="v1.4.0")
    context.client.portal.call(context.container.ingestion.enqueue_job, command)
    context.jobs = wait_for_embedding(context, LIBRARY)


@then('it stops with "{code}" before its next batch and is retried when the window resets')
def step_stops_then_retried(context: Context, code: str) -> None:
    # The job queued here, and those the start queued before the spend was recorded, all stop.
    assert context.jobs, "an embed job ran"
    for job in context.jobs:
        assert (job["state"], job["error_code"]) == ("failed", code), job
    assert context.endpoint.seen == [], "nothing was sent to the embedding provider"
    context.during = _search(context)
    # The month ends: the queueing that runs after each UTC midnight embeds what is missing.
    context.clock.at = AFTER_THE_MONTH
    context.client.portal.call(context.container.queue_embedding)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        jobs = wait_for_embedding(context, LIBRARY)
        if any(j["state"] == "succeeded" and j["version"] == "v1.4.0" for j in jobs):
            break
        time.sleep(0.05)
    jobs = wait_for_embedding(context, LIBRARY)
    assert any(j["state"] == "succeeded" and j["version"] == "v1.4.0" for j in jobs), jobs
    assert any(s.path == "/v1/embeddings" for s in context.endpoint.seen)


@then("BM25 keeps answering for versions not yet embedded")
def step_bm25_meanwhile(context: Context) -> None:
    body = context.during
    assert (body["retrieval_mode"], body["fallback_reason"]) == (
        "bm25",
        "embedding_in_progress",
    ), body
    assert body["results"], "BM25 answered while embedding was paused"


@given("the library's daily budget is used up and the reranker is a paid endpoint")
def step_library_budget_used_up(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.endpoint = stack.enter_context(gateway())
    serve_budgets(
        context,
        {
            "providers": {"rr": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "reranker": {"model": "rr:rerank-v3.5"},
            "prices": {"rr:rerank-v3.5": {"input_usd_per_mtok": 1.0}},
            "budgets": {"per_library_daily_usd": 0.5},
        },
    )
    assert _search(context)["reranked"] is True  # within budget: the endpoint reranked
    context.rerank_calls = _rerank_calls(context)
    assert context.rerank_calls == 1
    record_spend(context, "library", LIBRARY, SpendWindow.DAY, ONE_USD)


def _rerank_calls(context: Context) -> int:
    """Count the calls the reranker endpoint received.

    Args:
        context: The behave context.

    Returns:
        How many rerank requests it got.
    """
    return sum(1 for seen in context.endpoint.seen if seen.path.endswith("/rerank"))


@when("an agent searches")
def step_agent_searches(context: Context) -> None:
    context.result = _search(context)


@then('results arrive unreranked with "reranked: false" and fallback reason "{reason}"')
def step_unreranked(context: Context, reason: str) -> None:
    body = context.result
    assert (body["reranked"], body["fallback_reason"]) == (False, reason), body
    assert body["results"], "the mode's results arrive in their own order"
    assert _rerank_calls(context) == context.rerank_calls, "the reranker was not called"


@when("the admin reads the AI usage")
def step_read_usage(context: Context) -> None:
    response = context.client.get("/api/v1/ai/usage")
    assert response.status_code == HTTPStatus.OK, response.text
    context.usage = response.json()


@then("it shows the instance's spend today and that its daily budget is reached")
def step_usage_shown(context: Context) -> None:
    instance = context.usage["scopes"][0]
    assert (instance["scope"], instance["id"]) == ("instance", ""), instance
    assert math.isclose(instance["day"]["usd"], 1.0), instance
    (budget,) = instance["budgets"]
    assert (budget["window"], budget["usd_limit"], budget["usd_left"], budget["reached"]) == (
        "day",
        1.0,
        0.0,
        True,
    ), budget


HISTORY = "/api/v1/ai/usage/history"
SPENT_ON = {date(2026, 11, 3): 1, date(2026, 11, 20): 2}
"""Calls the instance made on each day it spent, at one US dollar and 1000 tokens each."""


@given("the instance spent on November 3 and twice on November 20")
def step_spent_on_days(context: Context) -> None:
    serve_budgets(context, {})
    ledger = SqliteSpendLedger(engine=context.container.engine)
    for day, calls in SPENT_ON.items():
        for _ in range(calls):  # each call counts to its day and its month, as a real one does
            moment = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
            entries = [
                SpendEntry(
                    scope_kind="instance",
                    scope_id="",
                    window=window,
                    window_start=window.start(moment),
                    input_tokens=600,
                    output_tokens=400,
                    requests=1,
                    usd_micros=ONE_USD,
                )
                for window in SpendWindow
            ]
            context.client.portal.call(ledger.add, entries)


def _history(context: Context, params: dict[str, str]) -> None:
    """Ask for a spend history; the response is kept in ``context.response``.

    Args:
        context: The behave context.
        params: The query.
    """
    context.response = context.client.get(HISTORY, params=params)


@when("the admin reads the instance's daily spend history from November 1 to November 23")
def step_read_daily_history(context: Context) -> None:
    params = {"scope": "instance", "window": "day", "from": "2026-11-01", "to": "2026-11-23"}
    _history(context, params)


@when("the admin reads the instance's monthly spend history from September to November")
def step_read_monthly_history(context: Context) -> None:
    params = {"scope": "instance", "window": "month", "from": "2026-09-01", "to": "2026-11-30"}
    _history(context, params)


@when("the admin reads the instance's daily spend history over {days:d} days")
def step_read_long_history(context: Context, days: int) -> None:
    last = date(2026, 11, 23)
    first = date.fromordinal(last.toordinal() - days + 1)
    params = {"window": "day", "from": first.isoformat(), "to": last.isoformat()}
    _history(context, params)


def _entries(context: Context) -> list[dict[str, Any]]:
    """Read the entries of the spend history asked for.

    Args:
        context: The behave context.

    Returns:
        One entry per window, oldest first.
    """
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    return context.response.json()["entries"]


@then("there is one entry per day with tokens, calls and US dollars")
def step_one_entry_per_day(context: Context) -> None:
    entries = _entries(context)
    assert [e["window_start"] for e in entries] == [
        date(2026, 11, day).isoformat() for day in range(1, 24)
    ], entries
    spent = {e["window_start"]: (e["tokens"], e["requests"], e["usd"]) for e in entries}
    assert spent["2026-11-03"] == (1000, 1, 1.0), spent
    assert spent["2026-11-20"] == (2000, 2, 2.0), spent


@then("the days without spend show nothing spent")
def step_zero_filled(context: Context) -> None:
    entries = _entries(context)
    quiet = [e for e in entries if date.fromisoformat(e["window_start"]) not in SPENT_ON]
    assert len(quiet) == len(entries) - len(SPENT_ON), quiet
    assert all((e["tokens"], e["requests"], e["usd"]) == (0, 0, 0) for e in quiet), quiet


@then("November shows the month's spend and the earlier months nothing")
def step_monthly(context: Context) -> None:
    entries = _entries(context)
    assert [(e["window_start"], e["tokens"], e["requests"], e["usd"]) for e in entries] == [
        ("2026-09-01", 0, 0, 0),
        ("2026-10-01", 0, 0, 0),
        ("2026-11-01", 3000, 3, 3.0),
    ], entries


@then("the request is refused as an invalid spend history")
def step_refused(context: Context) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT, response.text
    assert response.json()["error"] == "invalid_spend_history", response.text
