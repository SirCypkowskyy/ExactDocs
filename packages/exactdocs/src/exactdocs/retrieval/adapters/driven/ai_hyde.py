"""Implements retrieval's ``HypotheticalAnswers`` with pydantic-ai, imported only when called.

This module is light: it imports no SDK, so a process with no LLM configured never loads
pydantic-ai. ``write`` loads ``ai_hyde_sdk`` (pydantic-ai's ``Agent`` and the harness
``SpendLimits``, the ``[ai]`` extra) the first time a hypothetical answer is written.
"""

import importlib
from dataclasses import dataclass

from exactdocs.retrieval.constants import HYDE_SDK_MODULE
from exactdocs.retrieval.models import HypotheticalAnswer, LlmStep
from exactdocs.retrieval.ports.driven import SpendLedger


@dataclass(frozen=True, slots=True, kw_only=True)
class PydanticAiHypotheticalAnswers:
    """Implements ``ports.driven.HypotheticalAnswers``: an agent within the shared budgets."""

    ledger: SpendLedger
    """The ``retrieval_ai_spend`` rows the step's spend is checked against and added to."""

    async def write(self, model: object, query: str, *, step: LlmStep) -> HypotheticalAnswer:
        """Write a short documentation passage that would answer the query.

        Args:
            model: What ``ModelFactory.chat_model`` returned for the ``llm`` role.
            query: The query text.
            step: Who it counts to and the budgets it runs within.

        Returns:
            The passage and its usage.
        """
        sdk = importlib.import_module(HYDE_SDK_MODULE)
        return await sdk.write(model, query, step=step, ledger=self.ledger)
