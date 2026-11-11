"""The pydantic-ai side of ``ai_judge``: loaded only once a judge rates candidates.

One ``Agent(output_type=list[Rating])`` per search: every candidate rated in a single call,
each rating a positional ID (``c1`` ...) and a whole score from 0 to ``JUDGE_MAX_SCORE``
(bounded by the schema). The prompt delimits the query and the candidates as untrusted text
(``judge_prompt``) and the instructions say so. An output validator refuses ratings that are not
exactly one per candidate given (``judged_scores``), with no retry (``retries=0``): a judge that
names an ID it was not given, which a candidate's text may have asked for, is refused at once and
the search keeps its order. The run is inside the limits of every LLM step (``agent_limits``)
and an output token cap that grows with the candidates (``judge_max_tokens``). The model comes
instrumented from the factory, without content.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai_harness.spend import SpendLimitExceeded

from exactdocs.retrieval.adapters.driven.harness_spend import agent_limits
from exactdocs.retrieval.constants import JUDGE_INSTRUCTIONS, JUDGE_MAX_SCORE
from exactdocs.retrieval.errors import InvalidJudgmentError, LlmBudgetReachedError, LlmFailedError
from exactdocs.retrieval.models import (
    JudgedCandidate,
    JudgeRating,
    JudgeVerdict,
    LlmStep,
    judge_max_tokens,
    judge_prompt,
    judged_scores,
)
from exactdocs.retrieval.ports.driven import SpendLedger


class Rating(BaseModel):
    """One candidate's rating, as the judge must answer it."""

    model_config = ConfigDict(extra="forbid", strict=True, use_attribute_docstrings=True)

    id: str
    """The candidate's id, exactly as given (``c1``, ``c2``...)."""
    score: int = Field(ge=0, le=JUDGE_MAX_SCORE)
    """0 (unrelated) to 10 (directly answers the query)."""


def _ratings(output: Sequence[Rating]) -> tuple[JudgeRating, ...]:
    """Turn the agent's output into the domain's ratings.

    Args:
        output: The validated output.

    Returns:
        The ratings, in the judge's order.
    """
    return tuple(JudgeRating(id=r.id, score=r.score) for r in output)


async def judge(
    handle: object,
    query: str,
    candidates: Sequence[JudgedCandidate],
    *,
    step: LlmStep,
    ledger: SpendLedger,
) -> JudgeVerdict:
    """Run the judge's agent on the query and the candidates.

    Args:
        handle: What ``ModelFactory.chat_model`` returned: a pydantic-ai ``Model``.
        query: The query text.
        candidates: The candidates, best first.
        step: Who it counts to and the budgets it runs within.
        ledger: The spend ledger.

    Returns:
        One validated rating per candidate and the tokens the provider reported.

    Raises:
        LlmBudgetReachedError: ``SpendLimits`` refused the request (a budget is used up).
        LlmFailedError: The handle is no chat model, the run failed, or the ratings were refused;
            only the error's type (or the validator's fixed fault) is kept, never its message,
            which may echo the prompt.
    """
    name = getattr(handle, "model_name", "unknown")
    if not isinstance(handle, Model):
        raise LlmFailedError(str(name), "not a chat model")
    limits = agent_limits(
        ledger=ledger,
        budgets=step.budgets,
        caller=step.caller,
        clock=step.clock,
        price=step.price,
    )
    agent = Agent(
        handle,
        output_type=list[Rating],
        instructions=JUDGE_INSTRUCTIONS,
        model_settings=ModelSettings(max_tokens=judge_max_tokens(len(candidates))),
        retries=0,
        capabilities=[limits.spend],
    )
    refused: list[InvalidJudgmentError] = []

    @agent.output_validator
    def _only_given(output: list[Rating]) -> list[Rating]:
        """Refuse ratings that are not exactly one per candidate given.

        Args:
            output: The ratings as the model answered them, each already bounded.

        Returns:
            The same ratings.

        Raises:
            ModelRetry: They name an ID not given, rate one twice or miss one; with no retry
                left, the run fails.
        """
        try:
            judged_scores(candidates, _ratings(output))
        except InvalidJudgmentError as error:
            refused.append(error)
            raise ModelRetry(error.fault) from error  # retries=0: refused, never asked again
        return output

    try:
        result = await agent.run(judge_prompt(query, candidates), usage_limits=limits.usage)
    except SpendLimitExceeded as error:
        raise LlmBudgetReachedError(handle.model_name) from error
    except Exception as error:  # the provider's, the transport's, the validator's, pydantic-ai's
        reason = refused[-1].fault if refused else type(error).__name__
        raise LlmFailedError(handle.model_name, reason) from error
    usage = result.usage
    return JudgeVerdict(
        ratings=_ratings(result.output),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
