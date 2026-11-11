"""RET-07 over REST and MCP: spend counts to the caller's account; limits are configuration.

Per-user budgets and the LLM search rate limit see the account of the request: the session's or
the API token's over REST, the token's over HTTP MCP. A US dollar budget needs a price for every
configured model, or the server refuses to start.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import SecretStr
from sqlalchemy import text

from app_lifespan import serving
from databases import ADMIN_URL
from exactdocs.bootstrap.ai_models import budgets
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import StartupError, open_database
from exactdocs.bootstrap.embedding import (
    RequeueLeader,
    requeue_daily,
    requeue_nightly,
    seconds_to_next_window,
)
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, BudgetSettings, Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand
from exactdocs.retrieval.adapters.driven.memory import StaticModelRoles
from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.models import (
    BudgetLimit,
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    RetrievalMode,
    SpendEntry,
    SpendWindow,
)
from fixture_import import LIBRARY, import_fixture
from fixture_repo import DocsRepo

HORSE = "correct horse battery staple"
SEARCH = f"/api/v1/libraries{LIBRARY}/search"
T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def mcp_client(app: FastAPI, token: str) -> Client[StreamableHttpTransport]:
    """A FastMCP client that talks to the app in-process, over the real HTTP transport."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **extra: Any,
    ) -> httpx2.AsyncClient:  # the MCP SDK ships its own fork of httpx
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            **extra,
        )

    transport = StreamableHttpTransport(
        "http://localhost/mcp",
        headers={"authorization": f"Bearer {token}"},
        httpx_client_factory=factory,
    )
    return Client(transport)


class Clock:
    def now(self) -> datetime:
        return T0


class StandInAgentic:
    """Answers ``agentic`` with no hits: the search with an LLM step."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        del request
        return PipelineAnswer(
            mode=RetrievalMode.AGENTIC, hits=(), candidates=0, reranked=0, complete=True
        )


@pytest.fixture
async def app(docs_repo: DocsRepo) -> AsyncIterator[tuple[FastAPI, Container]]:
    """The app with a per-user budget and an agentic stand-in, the fixture library imported.

    Yields:
        The running app and its container.
    """
    ai = AiSettings(budgets=BudgetSettings(per_user_daily_usd=1, llm_searches_per_minute=3))
    container = Container.build(
        Settings(ai=ai),
        model_roles=StaticModelRoles(roles=frozenset({ModelRole.LLM})),
        pipelines={RetrievalMode.AGENTIC: StandInAgentic()},
        clock=Clock(),
    )
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        await import_fixture(container, docs_repo)
        yield app, container


@pytest.fixture
async def ada(app: tuple[FastAPI, Container]) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app[0]), base_url="http://localhost"
    ) as client:
        login = {"username": "ada", "password": HORSE}
        assert (await client.post("/api/v1/session", json=login)).status_code == 201
        yield client


async def _search(client: httpx.AsyncClient, **headers: str) -> tuple[str, Any]:
    response = await client.get(
        SEARCH, params={"q": "retry_policy", "mode": "agentic"}, headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["retrieval_mode"], body["fallback_reason"]


async def test_a_users_budget_and_rate_limit_follow_their_account_over_rest_and_mcp(
    app: tuple[FastAPI, Container], ada: httpx.AsyncClient
) -> None:
    _, container = app
    account = (await ada.get("/api/v1/session")).json()["account"]["id"]
    token = (await ada.post("/api/v1/tokens", json={"name": "agent"})).json()["token"]
    bearer = {"authorization": f"Bearer {token}"}

    # Three LLM searches a minute for the account: by cookie, by token, then over MCP.
    assert await _search(ada) == ("agentic", None)
    assert await _search(ada, **bearer) == ("agentic", None)
    async with mcp_client(app[0], token) as mcp:
        found = await mcp.call_tool(
            "search_docs", {"library": LIBRARY, "query": "retry_policy", "mode": "agentic"}
        )
        assert found.structured_content is not None
        assert found.structured_content["retrieval_mode"] == "agentic"
        limited = await mcp.call_tool(
            "search_docs", {"library": LIBRARY, "query": "retry_policy", "mode": "agentic"}
        )
        assert limited.structured_content is not None
        assert limited.structured_content["fallback_reason"] == "llm_rate_limited"

    await SqliteSpendLedger(engine=container.engine).add(
        [
            SpendEntry(
                scope_kind="user",
                scope_id=account,
                window=SpendWindow.DAY,
                window_start=T0.date(),
                input_tokens=10,
                requests=1,
                usd_micros=1_000_000,
            )
        ]
    )
    assert await _search(ada) == ("bm25", "llm_budget_reached")

    usage = (await ada.get("/api/v1/ai/usage")).json()
    user = next(s for s in usage["scopes"] if s["scope"] == "user")
    assert (user["id"], user["day"]["requests"], user["budgets"][0]["reached"]) == (
        account,
        1,
        True,
    )
    assert usage["llm_searches_per_minute"] == 3


async def test_the_usage_route_needs_a_signed_in_caller(app: tuple[FastAPI, Container]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app[0]), base_url="http://localhost"
    ) as anonymous:
        assert (await anonymous.get("/api/v1/ai/usage")).status_code == 401


# ---------------------------------------------------------------- configuration


def test_budget_settings_become_one_limit_per_scope_kind_and_window() -> None:
    settings = BudgetSettings(
        daily_usd=10,
        monthly_tokens=5_000_000,
        per_library_daily_usd=2,
        per_user_monthly_usd=1.5,
        monthly_embedding_usd=50,
        llm_searches_per_minute=30,
    )

    limits = budgets(settings)

    assert limits.llm_searches_per_minute == 30
    assert set(limits.limits) == {
        BudgetLimit(scope_kind="instance", window=SpendWindow.DAY, usd_micros=10_000_000),
        BudgetLimit(scope_kind="instance", window=SpendWindow.MONTH, tokens=5_000_000),
        BudgetLimit(scope_kind="library", window=SpendWindow.DAY, usd_micros=2_000_000),
        BudgetLimit(scope_kind="user", window=SpendWindow.MONTH, usd_micros=1_500_000),
        BudgetLimit(scope_kind="embedding", window=SpendWindow.MONTH, usd_micros=50_000_000),
    }
    assert budgets(BudgetSettings()).limits == ()


def test_budgets_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__BUDGETS__PER_USER_DAILY_TOKENS", "20000")
    monkeypatch.setenv("EXACTDOCS_AI__BUDGETS__LLM_SEARCHES_PER_MINUTE", "12")
    monkeypatch.setenv("EXACTDOCS_AI__PRICES__CORP:M__INPUT_USD_PER_MTOK", "0.4")

    ai = Settings().ai

    assert (ai.budgets.per_user_daily_tokens, ai.budgets.llm_searches_per_minute) == (20000, 12)
    assert ai.prices["corp:m"].input_usd_per_mtok == pytest.approx(0.4)


def _llm(budget: BudgetSettings, prices: dict[str, Any] | None = None) -> Settings:
    return Settings(
        ai=AiSettings.model_validate(
            {
                "providers": {
                    "corp": {"kind": "openai-compatible", "base_url": "http://127.0.0.1:9/v1"}
                },
                "llm": {"model": "corp:in-house-model"},
                "budgets": budget.model_dump(exclude_none=True),
                "prices": prices or {},
            }
        )
    )


def test_a_usd_budget_on_a_model_without_a_price_is_refused_at_start() -> None:
    with pytest.raises(StartupError, match=r"corp:in-house-model.*ai\.prices"):
        Container.build(_llm(BudgetSettings(daily_usd=5)))


@pytest.mark.parametrize(
    ("budget", "prices"),
    [
        (BudgetSettings(daily_tokens=1000), None),  # tokens are always counted
        (BudgetSettings(daily_usd=5), {"corp:in-house-model": {"input_usd_per_mtok": 0.1}}),
    ],
)
def test_a_token_budget_or_a_configured_price_starts(
    budget: BudgetSettings, prices: dict[str, Any] | None
) -> None:
    Container.build(_llm(budget, prices))


def test_embedding_is_queued_again_just_after_each_utc_midnight() -> None:
    assert seconds_to_next_window(datetime(2026, 11, 7, 23, 59, tzinfo=UTC)) == pytest.approx(65)
    late = datetime(2026, 12, 31, 23, 0, tzinfo=UTC) - timedelta(seconds=1)
    assert seconds_to_next_window(late) == pytest.approx(3606)


# ---------------------------------------------------------------- the midnight re-queue


class NightsOverError(Exception):
    """Ends a re-queue loop after a few nights."""


def _nights(count: int, waits: list[float]) -> Any:
    """A fake ``sleep`` that lets ``count`` nights pass, then stops the loop."""

    async def sleep(seconds: float) -> None:
        if len(waits) == count:
            raise NightsOverError
        waits.append(seconds)
        await asyncio.sleep(0)

    return sleep


async def test_embedding_is_queued_after_each_midnight_with_jitter() -> None:
    engine = open_database(Settings())
    queued: list[int] = []
    waits: list[float] = []

    async def queue() -> None:
        queued.append(1)

    with pytest.raises(NightsOverError):
        await requeue_daily(
            engine=engine,
            queue=queue,
            now=lambda: datetime(2026, 11, 7, 23, 59, tzinfo=UTC),
            sleep=_nights(2, waits),
            jitter=lambda: 42.0,
        )
    await engine.dispose()

    assert waits == [65 + 42.0, 65 + 42.0]
    assert len(queued) == 2


@pytest.mark.skipif(ADMIN_URL is None, reason="needs a PostgreSQL server")
async def test_only_one_process_requeues_on_postgresql(on_postgres: object) -> None:
    del on_postgres
    engines = [open_database(Settings()) for _ in range(3)]
    queued: list[int] = []

    def process(index: int) -> Any:
        async def queue() -> None:
            queued.append(index)

        return requeue_daily(
            engine=engines[index], queue=queue, sleep=_nights(2, []), jitter=lambda: 0.0
        )

    results = await asyncio.gather(*(process(i) for i in range(3)), return_exceptions=True)
    for engine in engines:
        await engine.dispose()

    assert all(isinstance(r, NightsOverError) for r in results), results
    assert len(queued) == 2  # two nights, one process each night
    assert len(set(queued)) == 1  # the same one: it keeps the lock


@dataclass(slots=True)
class FakeSession:
    """A lock session that holds the lock, or fails like a dropped connection."""

    world: FakeDatabase
    alive: bool = True

    async def holds_lock(self, *, held_before: bool) -> bool:
        del held_before
        if not self.alive:
            message = "server closed the connection unexpectedly"
            raise ConnectionError(message)
        return True

    async def close(self) -> None:
        self.world.closed += 1


@dataclass(slots=True)
class FakeDatabase:
    sessions: list[FakeSession] = field(default_factory=list)
    closed: int = 0

    async def open(self) -> FakeSession:
        session = FakeSession(world=self)
        self.sessions.append(session)
        return session


async def test_a_dropped_connection_between_nights_is_replaced_and_the_loop_goes_on() -> None:
    database = FakeDatabase()
    leader = RequeueLeader(open_session=database.open)
    queued: list[int] = []
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        if len(waits) == 3:
            raise NightsOverError
        if len(waits) == 1:
            database.sessions[-1].alive = False  # PostgreSQL restarted after the first night
        waits.append(seconds)

    async def queue() -> None:
        queued.append(len(database.sessions))

    with pytest.raises(NightsOverError):
        await requeue_nightly(
            leader=leader, queue=queue, now=lambda: T0, sleep=sleep, jitter=lambda: 0.0
        )

    assert queued == [1, 2, 2]  # every night queued; the second on a new session
    assert database.closed == 2  # the dead session, then the live one at the end
    assert leader.session is None


async def test_a_failed_night_is_logged_and_the_next_one_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    waits: list[float] = []
    nights: list[int] = []

    async def queue() -> None:
        nights.append(1)
        if len(nights) == 1:
            message = "database is locked"
            raise RuntimeError(message)

    with pytest.raises(NightsOverError):
        await requeue_nightly(
            leader=None, queue=queue, now=lambda: T0, sleep=_nights(2, waits), jitter=lambda: 0.0
        )

    assert len(nights) == 2
    assert "re-queue of embedding failed" in caplog.text


async def test_stopping_the_loop_cancels_it_cleanly() -> None:
    database = FakeDatabase()
    leader = RequeueLeader(open_session=database.open)
    started = asyncio.Event()

    async def sleep(seconds: float) -> None:
        del seconds
        started.set()
        await asyncio.Event().wait()

    async def queue() -> None: ...

    task = asyncio.create_task(
        requeue_nightly(leader=leader, queue=queue, now=lambda: T0, sleep=sleep, jitter=lambda: 0.0)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.skipif(ADMIN_URL is None, reason="needs a PostgreSQL server")
async def test_the_leader_survives_its_session_being_terminated(on_postgres: object) -> None:
    del on_postgres
    engine, admin = open_database(Settings()), open_database(Settings())
    queued: list[int] = []
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        if len(waits) == 3:
            raise NightsOverError
        if len(waits) == 1:  # the server ends the leader's session between nights
            async with admin.connect() as connection:
                await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_locks "
                        "WHERE locktype = 'advisory' AND pid <> pg_backend_pid()"
                    )
                )
                await connection.commit()
        waits.append(seconds)

    async def queue() -> None:
        queued.append(1)

    with pytest.raises(NightsOverError):
        await requeue_daily(engine=engine, queue=queue, sleep=sleep, jitter=lambda: 0.0)
    for each in (engine, admin):
        await each.dispose()

    assert len(queued) == 3
