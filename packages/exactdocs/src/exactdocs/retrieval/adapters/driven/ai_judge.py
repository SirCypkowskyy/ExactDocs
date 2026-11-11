"""Implements retrieval's ``CandidateJudge`` with pydantic-ai, imported only when called.

This module is light: it imports no SDK, so a process with no judge configured never loads
pydantic-ai. ``judge`` loads ``ai_judge_sdk`` (pydantic-ai's ``Agent`` and the harness
``SpendLimits``, the ``[ai]`` extra) the first time a judge rates candidates.
"""

import importlib
from collections.abc import Sequence
from dataclasses import dataclass

from exactdocs.retrieval.constants import JUDGE_SDK_MODULE
from exactdocs.retrieval.models import JudgedCandidate, JudgeVerdict, LlmStep
from exactdocs.retrieval.ports.driven import SpendLedger


@dataclass(frozen=True, slots=True, kw_only=True)
class PydanticAiCandidateJudge:
    """Implements ``ports.driven.CandidateJudge``: one agent call within the shared budgets."""

    ledger: SpendLedger
    """The ``retrieval_ai_spend`` rows the step's spend is checked against and added to."""

    async def judge(
        self, model: object, query: str, candidates: Sequence[JudgedCandidate], *, step: LlmStep
    ) -> JudgeVerdict:
        """Rate every candidate's relevance to the query in one call.

        Args:
            model: What ``ModelFactory.chat_model`` returned for the ``judge`` role.
            query: The query text.
            candidates: The candidates, best first as the search found them.
            step: Who it counts to and the budgets it runs within.

        Returns:
            One validated rating per candidate, and the call's usage.
        """
        sdk = importlib.import_module(JUDGE_SDK_MODULE)
        return await sdk.judge(model, query, candidates, step=step, ledger=self.ledger)
