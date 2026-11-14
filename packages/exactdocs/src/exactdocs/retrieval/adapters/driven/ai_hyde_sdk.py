"""The pydantic-ai side of ``ai_hyde``: loaded only once a hypothetical answer is written.

One ``Agent(output_type=str)`` per answer, with HyDE's fixed instructions and a cap on its output
tokens, inside the limits of every LLM step (``agent_limits``): the harness ``SpendLimits`` over
the ledger, which refuses the request once a budget is used up and records what it cost, and
pydantic-ai's ``UsageLimits``. The model comes instrumented from the factory, without content.
"""

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai_harness.spend import SpendLimitExceeded

from exactdocs.retrieval.adapters.driven.harness_spend import agent_limits
from exactdocs.retrieval.constants import HYDE_INSTRUCTIONS, HYDE_MAX_TOKENS
from exactdocs.retrieval.errors import LlmBudgetReachedError, LlmFailedError
from exactdocs.retrieval.models import HypotheticalAnswer, LlmStep
from exactdocs.retrieval.ports.driven import SpendLedger


async def write(
    handle: object, query: str, *, step: LlmStep, ledger: SpendLedger
) -> HypotheticalAnswer:
    """Run HyDE's agent on the query.

    Args:
        handle: What ``ModelFactory.chat_model`` returned: a pydantic-ai ``Model``.
        query: The query text, the agent's only user prompt.
        step: Who it counts to and the budgets it runs within.
        ledger: The spend ledger.

    Returns:
        The passage and the tokens the provider reported.

    Raises:
        LlmBudgetReachedError: ``SpendLimits`` refused the request (a budget is used up).
        LlmFailedError: The handle is no chat model, or the run failed; only the error's type is
            kept, never its message, which may echo the prompt.
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
        output_type=str,
        instructions=HYDE_INSTRUCTIONS,
        model_settings=ModelSettings(max_tokens=HYDE_MAX_TOKENS),
        capabilities=[limits.spend],
    )
    try:
        result = await agent.run(query, usage_limits=limits.usage)
    except SpendLimitExceeded as error:
        raise LlmBudgetReachedError(handle.model_name) from error
    except Exception as error:  # the provider's, the transport's or pydantic-ai's
        raise LlmFailedError(handle.model_name, type(error).__name__) from error
    usage = result.usage
    return HypotheticalAnswer(
        text=result.output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
