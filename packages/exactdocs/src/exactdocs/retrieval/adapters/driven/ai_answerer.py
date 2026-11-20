"""Implements retrieval's ``Answerer`` with pydantic-ai, imported only when a question is answered.

This module is light: it imports no SDK, so a process with no LLM configured never loads
pydantic-ai, the harness or Monty. ``answer`` loads ``ai_answerer_sdk`` (the ``[ai]`` extra) the
first time an agentic answer runs (#428).
"""

import importlib
from dataclasses import dataclass

from exactdocs.retrieval.constants import ANSWERER_SDK_MODULE
from exactdocs.retrieval.models import AgentRun, AnswerDraft
from exactdocs.retrieval.ports.driven import AnswerProgress, LibrariesBrowser, SpendLedger
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class PydanticAiAnswerer:
    """Implements ``ports.driven.Answerer``: a pydantic-ai agent in harness Code Mode."""

    async def answer(
        self,
        model: object,
        browser: LibrariesBrowser,
        run: AgentRun,
        *,
        ledger: SpendLedger,
        clock: Clock,
        progress: AnswerProgress | None = None,
    ) -> AnswerDraft:
        """Run the agent (``ai_answerer_sdk.answer``).

        Args:
            model: The ``llm`` role's pydantic-ai model.
            browser: The read tools on the question's libraries.
            run: The question, the limits and who pays.
            ledger: The spend rows.
            clock: Decides the spend windows.
            progress: Hears each tool call.

        Returns:
            The answer and its citations, or why the run stopped.
        """
        sdk = importlib.import_module(ANSWERER_SDK_MODULE)
        return await sdk.answer(model, browser, run, ledger=ledger, clock=clock, progress=progress)
