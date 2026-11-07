"""The ledger as the harness's ``BatchSpendStore``, and the limits of every LLM step (``[ai]``).

LLM agents (HyDE, the judge, the agentic explorer) are limited by the harness ``SpendLimits``
capability over ``LedgerSpendStore``: the same ``retrieval_ai_spend`` rows embedding and rerank
calls write to. The harness builds its keys with private helpers (``store_key`` and ``bucket`` in
``pydantic_ai_harness/spend/_budget.py``); ``ledger_key`` parses the key it hands over into the
ledger's own ``SpendKey`` instead of importing them, and a contract test pins the 0.60.0 format.

Imported only by the code that runs an agent, so a process with no LLM configured never loads
pydantic-ai.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from pydantic_ai import RunContext
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.spend import Budget, SpendLimits, Spent
from pydantic_ai_harness.spend import SpendEntry as HarnessEntry

from exactdocs.retrieval.constants import (
    HARNESS_ANY_SCOPE,
    HARNESS_KEY_PARTS,
    HARNESS_KEY_SEPARATOR,
    HARNESS_MONTH_BUCKET,
    INSTANCE_WIDE_KINDS,
    LLM_REQUEST_LIMIT,
    LLM_TOKEN_LIMIT,
    MICROS_PER_USD,
    SPEND_INSTANCE_ID,
)
from exactdocs.retrieval.errors import UnknownSpendKeyError
from exactdocs.retrieval.models import (
    AiCaller,
    BudgetLimit,
    Budgets,
    SpendEntry,
    SpendKey,
    SpendWindow,
)
from exactdocs.retrieval.ports.driven import SpendLedger


def ledger_key(key: str) -> SpendKey:
    """Parse a harness ``SpendEntry.key`` into the ledger's row key.

    The harness key is ``<budget name>|<window>|<scope>|<bucket>``. Our budgets are named after
    the scope kind; an instance-wide kind is unscoped (``*``); a day's bucket is ``YYYY-MM-DD``
    and a month's ``YYYY-MM``.

    Args:
        key: The harness key.

    Returns:
        The row it counts to.

    Raises:
        UnknownSpendKeyError: Not a key of a budget ``agent_limits`` made (another window, a
            scope that does not fit its kind, a bucket in another format).
    """
    parts = key.split(HARNESS_KEY_SEPARATOR)
    if len(parts) != HARNESS_KEY_PARTS:
        raise UnknownSpendKeyError(key)
    kind, window_name, scope, bucket = parts
    if (kind in INSTANCE_WIDE_KINDS) != (scope == HARNESS_ANY_SCOPE):
        raise UnknownSpendKeyError(key)
    if window_name not in {w.value for w in SpendWindow}:
        raise UnknownSpendKeyError(key)
    window = SpendWindow(window_name)
    if window is SpendWindow.MONTH and not re.fullmatch(HARNESS_MONTH_BUCKET, bucket):
        raise UnknownSpendKeyError(key)
    first_day = f"{bucket}-01" if window is SpendWindow.MONTH else bucket
    try:
        start = date.fromisoformat(first_day)
    except ValueError:
        raise UnknownSpendKeyError(key) from None
    if start.isoformat() != first_day:  # fromisoformat also reads 20261107 and other forms
        raise UnknownSpendKeyError(key)
    scope_id = SPEND_INSTANCE_ID if scope == HARNESS_ANY_SCOPE else scope
    return SpendKey(scope_kind=kind, scope_id=scope_id, window=window, window_start=start)


def _spent(row: SpendEntry | None) -> Spent:
    """Show a ledger row as the harness reads a window.

    Args:
        row: The row; ``None`` when nothing was spent.

    Returns:
        Its totals, US dollars exact to the millionth.
    """
    if row is None:
        return Spent()
    return Spent(
        usd=Decimal(row.usd_micros) / MICROS_PER_USD,
        tokens=row.tokens,
        requests=row.requests,
        unpriced_requests=row.unpriced,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerSpendStore:
    """Implements the harness ``BatchSpendStore`` (structurally) over ``ports.driven.SpendLedger``.

    Not the deprecated ``SpendStore``: every window of a response is added in one transaction,
    and the response's replay token keeps a replayed accrual from counting twice.
    """

    ledger: SpendLedger
    """The ``retrieval_ai_spend`` rows."""

    async def get_many(self, keys: Sequence[str]) -> Mapping[str, Spent]:
        """Read what each window has accumulated.

        Args:
            keys: Harness keys.

        Returns:
            Each key's totals; a window never written reads as zero.
        """
        parsed = {key: ledger_key(key) for key in keys}
        rows = await self.ledger.get(list(dict.fromkeys(parsed.values())))
        return {key: _spent(rows.get(row_key)) for key, row_key in parsed.items()}

    async def add_many(self, entries: Sequence[HarnessEntry]) -> Mapping[str, Spent]:
        """Add every window's share of one response, then read the new totals.

        The harness reports one token total per response: it is booked as input tokens.

        Args:
            entries: The shares, one per window.

        Returns:
            Each key's total after the addition.
        """
        added = []
        for entry in entries:
            key = ledger_key(entry.key)
            added.append(
                SpendEntry(
                    scope_kind=key.scope_kind,
                    scope_id=key.scope_id,
                    window=key.window,
                    window_start=key.window_start,
                    input_tokens=entry.tokens,
                    requests=entry.requests,
                    usd_micros=round(entry.usd * MICROS_PER_USD),
                    unpriced=entry.unpriced,
                    token=entry.token,
                )
            )
        await self.ledger.add(added)
        return await self.get_many([entry.key for entry in entries])


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentLimits:
    """What every LLM step runs with: the shared budgets and pydantic-ai's per-call limits."""

    spend: SpendLimits[object]
    """The harness capability: refuses a request once a window is used up, and records spend."""
    usage: UsageLimits
    """At most ``LLM_REQUEST_LIMIT`` requests and ``LLM_TOKEN_LIMIT`` tokens per step."""


def _scoped(scope_id: str) -> Callable[[RunContext[object]], str]:
    """Return a harness scope that always names one scope.

    Args:
        scope_id: The library or account ID.

    Returns:
        The scope function.
    """

    def scope(ctx: RunContext[object]) -> str:
        """Name the scope, whatever the run.

        Args:
            ctx: The run.

        Returns:
            The scope ID.
        """
        del ctx
        return scope_id

    return scope


def _budget(
    kind: str, scope_id: str, window: SpendWindow, limit: BudgetLimit | None
) -> Budget[object]:
    """Build the harness budget of one scope and window: a ceiling, or a plain counter.

    Args:
        kind: The scope kind, the budget's name (so ``ledger_key`` finds the row).
        scope_id: The scope.
        window: Day or month.
        limit: Its ceiling, if any.

    Returns:
        The budget.
    """
    usd = None
    tokens = None
    if limit is not None:
        usd = None if limit.usd_micros is None else Decimal(limit.usd_micros) / MICROS_PER_USD
        tokens = limit.tokens
    return Budget(
        name=kind,
        window=window.value,
        usd=usd,
        tokens=tokens,
        scope=None if kind in INSTANCE_WIDE_KINDS else _scoped(scope_id),
    )


def agent_limits(
    *,
    ledger: SpendLedger,
    budgets: Budgets,
    caller: AiCaller,
    clock: Callable[[], datetime],
) -> AgentLimits:
    """Build the limits of one LLM step for a caller.

    Every scope the caller counts to (instance, library, user) gets a day and a month budget,
    with the ceiling the instance sets for its kind or none (a counter), so the step's spend
    lands in the same rows budgets read.

    Args:
        ledger: The ``retrieval_ai_spend`` rows.
        budgets: The instance's limits.
        caller: The library and the account the step runs for.
        clock: The current time (UTC windows).

    Returns:
        The capability for the agent and the usage limits for its run.
    """
    ceilings = {(limit.scope_kind, limit.window): limit for limit in budgets.limits}
    harness_budgets = [
        _budget(kind, scope_id, window, ceilings.get((kind, window)))
        for kind, scope_id in caller.scopes()
        for window in SpendWindow
    ]
    return AgentLimits(
        spend=SpendLimits(
            budgets=harness_budgets, store=LedgerSpendStore(ledger=ledger), clock=clock
        ),
        usage=UsageLimits(request_limit=LLM_REQUEST_LIMIT, total_tokens_limit=LLM_TOKEN_LIMIT),
    )
