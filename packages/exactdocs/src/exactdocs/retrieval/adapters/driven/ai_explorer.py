"""Implements retrieval's ``Explorer`` with pydantic-ai, imported only when an agentic search runs.

This module is light: it imports no SDK, so a process with no LLM configured never loads
pydantic-ai, the harness or Monty. ``explore`` loads ``ai_explorer_sdk`` (the ``[ai]`` extra) the
first time an agentic search runs.
"""

import importlib
from collections.abc import Sequence
from dataclasses import dataclass

from exactdocs.retrieval.constants import EXPLORER_SDK_MODULE
from exactdocs.retrieval.models import AgentPick, AgentRun
from exactdocs.retrieval.ports.driven import DocsBrowser, SpendLedger
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class PydanticAiExplorer:
    """Implements ``ports.driven.Explorer``: a pydantic-ai agent in harness Code Mode."""

    async def explore(
        self,
        model: object,
        browser: DocsBrowser,
        run: AgentRun,
        *,
        ledger: SpendLedger,
        clock: Clock,
    ) -> Sequence[AgentPick]:
        """Run the agent (``ai_explorer_sdk.explore``).

        Args:
            model: The ``llm`` role's pydantic-ai model.
            browser: The read tools on the version searched.
            run: The question, the limits and who pays.
            ledger: The spend rows.
            clock: Decides the spend windows.

        Returns:
            The agent's picks.
        """
        sdk = importlib.import_module(EXPLORER_SDK_MODULE)
        return await sdk.explore(model, browser, run, ledger=ledger, clock=clock)
