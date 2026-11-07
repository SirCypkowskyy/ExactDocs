"""LLM agents are limited by the harness ``SpendLimits`` over the ledger (RET-07).

The ledger owns its key format; ``ledger_key`` parses the harness's. These tests pin the key
format of pydantic-ai-harness 0.60.0: a bump that changes it fails here instead of splitting the
spend over two sets of rows. Agents run on pydantic-ai's ``TestModel``: no provider is called.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.test import TestModel
from pydantic_ai_harness.spend import BatchSpendStore, SpendLimitExceeded, SpendLimits, Spent
from pydantic_ai_harness.spend import SpendEntry as HarnessEntry

from exactdocs.retrieval.adapters.driven.harness_spend import (
    LedgerSpendStore,
    agent_limits,
    ledger_key,
)
from exactdocs.retrieval.adapters.driven.memory import InMemorySpendLedger
from exactdocs.retrieval.constants import LLM_REQUEST_LIMIT, LLM_TOKEN_LIMIT
from exactdocs.retrieval.errors import UnknownSpendKeyError
from exactdocs.retrieval.models import AiCaller, BudgetLimit, Budgets, SpendKey, SpendWindow

LIB = "/acme/payments"
ADA = "account-ada"
T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return T0


@dataclass(slots=True)
class RecordingStore:
    """A ``BatchSpendStore`` over the ledger that keeps every key the harness handed over."""

    inner: LedgerSpendStore
    keys: list[str] = field(default_factory=list)

    async def get_many(self, keys: Sequence[str]) -> Mapping[str, Spent]:
        self.keys.extend(keys)
        return await self.inner.get_many(keys)

    async def add_many(self, entries: Sequence[HarnessEntry]) -> Mapping[str, Spent]:
        self.keys.extend(e.key for e in entries)
        return await self.inner.add_many(entries)


def test_the_store_implements_the_batch_protocol_not_the_deprecated_one() -> None:
    store = LedgerSpendStore(ledger=InMemorySpendLedger())

    assert isinstance(store, BatchSpendStore)
    assert not hasattr(store, "get")
    assert not hasattr(store, "add")


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("instance|day|*|2026-11-07", ("instance", "", SpendWindow.DAY, date(2026, 11, 7))),
        (
            "library|month|/acme/x|2026-11",
            ("library", "/acme/x", SpendWindow.MONTH, date(2026, 11, 1)),
        ),
        (
            "user|day|account-1|2026-11-07",
            ("user", "account-1", SpendWindow.DAY, date(2026, 11, 7)),
        ),
    ],
)
def test_harness_keys_are_parsed_into_ledger_rows(
    key: str, expected: tuple[str, str, SpendWindow, date]
) -> None:
    parsed = ledger_key(key)

    assert (parsed.scope_kind, parsed.scope_id, parsed.window, parsed.window_start) == expected


@pytest.mark.parametrize(
    "key",
    [
        "default|day|*|2026-11-07",  # a budget we never make
        "instance|run|*|run-id",  # a window the ledger has not
        "instance|day|tenant|2026-11-07",  # the instance is unscoped
        "library|day|*|2026-11-07",  # a library budget is scoped
        "instance|day|*|20261107",
        "instance|month|*|2026-11-01",
        "instance|day|*",
        "library|day|a|b|2026-11-07",
    ],
)
def test_a_key_in_another_format_is_refused_not_misfiled(key: str) -> None:
    with pytest.raises(UnknownSpendKeyError):
        ledger_key(key)


async def test_an_agent_step_counts_to_the_callers_rows_in_the_pinned_key_format() -> None:
    ledger = InMemorySpendLedger()
    store = RecordingStore(inner=LedgerSpendStore(ledger=ledger))
    limits = agent_limits(
        ledger=ledger, budgets=Budgets(), caller=AiCaller(library=LIB, user=ADA), clock=_clock
    )
    # The same budgets over a store that records the keys the harness hands over.
    spend = SpendLimits(budgets=limits.spend.budgets, store=store, clock=_clock)
    agent = Agent(TestModel(), capabilities=[spend])

    await agent.run("Which version?", usage_limits=limits.usage)

    # Pinned: pydantic-ai-harness 0.60.0 keys are <name>|<window>|<scope>|<bucket>.
    assert set(store.keys) == {
        "instance|day|*|2026-11-07",
        "instance|month|*|2026-11",
        f"library|day|{LIB}|2026-11-07",
        f"library|month|{LIB}|2026-11",
        f"user|day|{ADA}|2026-11-07",
        f"user|month|{ADA}|2026-11",
    }
    assert {(k.scope_kind, k.scope_id, k.window) for k in ledger.rows} == {
        (kind, scope_id, window)
        for kind, scope_id in (("instance", ""), ("library", LIB), ("user", ADA))
        for window in SpendWindow
    }
    for row in ledger.rows.values():
        assert row.requests == 1
        assert row.tokens > 0  # TestModel reports usage like a provider does


async def test_a_used_up_budget_refuses_the_agents_next_request() -> None:
    ledger = InMemorySpendLedger()
    budgets = Budgets(limits=(BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=1),))
    caller = AiCaller(library=LIB, user=ADA)
    limits = agent_limits(ledger=ledger, budgets=budgets, caller=caller, clock=_clock)
    agent = Agent(TestModel(), capabilities=[limits.spend])
    await agent.run("first", usage_limits=limits.usage)  # crosses the line: it completes

    with pytest.raises(SpendLimitExceeded):
        await agent.run("second", usage_limits=limits.usage)

    other = agent_limits(
        ledger=ledger, budgets=budgets, caller=AiCaller(library="/acme/other"), clock=_clock
    )
    await Agent(TestModel(), capabilities=[other.spend]).run("x", usage_limits=other.usage)


async def test_a_replayed_accrual_is_counted_once() -> None:
    ledger = InMemorySpendLedger()
    store = LedgerSpendStore(ledger=ledger)
    entry = HarnessEntry(
        key=f"library|day|{LIB}|2026-11-07",
        usd=Decimal("0.0012346"),
        tokens=40,
        requests=1,
        token="response-1",
    )

    first = await store.add_many([entry])
    again = await store.add_many([entry])

    assert first == again
    assert first[entry.key] == Spent(usd=Decimal("0.001235"), tokens=40, requests=1)
    key = SpendKey(
        scope_kind="library", scope_id=LIB, window=SpendWindow.DAY, window_start=date(2026, 11, 7)
    )
    assert ledger.rows[key].usd_micros == 1235


async def test_every_llm_step_has_per_call_usage_limits() -> None:
    limits = agent_limits(
        ledger=InMemorySpendLedger(), budgets=Budgets(), caller=AiCaller(library=LIB), clock=_clock
    )
    agent = Agent(TestModel(call_tools=[]), capabilities=[limits.spend])

    assert (limits.usage.request_limit, limits.usage.total_tokens_limit) == (
        LLM_REQUEST_LIMIT,
        LLM_TOKEN_LIMIT,
    )
    with pytest.raises(UsageLimitExceeded):
        await agent.run("x", usage_limits=type(limits.usage)(request_limit=0))
