"""The LLM judge: grades an agent's answer against the case's reference answer and facts.

The judge is a pydantic-ai agent with a typed output (``Verdict``), run as a Pydantic Evals
evaluator. It sees the question, the version, the kind, the reference answer, the facts and the
answer, as JSON; never the documentation itself, so it grades against the golden case only. It is
blind to the arm (#495): the answer it reads has every arm's product and tool names removed
(``arms.blind``), and nothing else of the run reaches it.

A run that ended without an answer is not judged: ``no_answer`` when the agent failed (it counts
as a miss), ``error`` when the provider did (it is left out of the rates and can be run again).
"""

import json
from dataclasses import dataclass
from typing import Final, Literal, get_args

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from agent_bench.arms import blind
from agent_bench.harness import AgentRun, BenchInfo
from retrieval_eval.dataset import Question

type Grade = Literal["correct", "partially_correct", "wrong", "refused"]
"""A judged answer: ``refused`` says the documentation does not cover the question, or that the
agent does not know (or declines), without stating facts."""
GRADES: Final[tuple[str, ...]] = get_args(Grade.__value__)
"""Every grade, best first."""
NO_ANSWER: Final[str] = "no_answer"
"""The grade of a run that ended without an answer on the agent's side (a miss, not judged)."""
ERROR: Final[str] = "error"
"""The grade of a question the provider or the judge failed on: left out of the rates."""
GRADE: Final[str] = "grade"
"""The label holding the grade."""
WRONG_VERSION: Final[str] = "wrong_version"
"""The assertion that the answer states something true of another version only."""
PROMPT_HEAD: Final[str] = "Grade this answer.\n\n"
"""What comes before the case's JSON in the judge's prompt."""
JUDGE_INSTRUCTIONS: Final[str] = """\
You grade an answer a coding assistant gave about one version of a library. You get, as JSON, \
the question, the library and its version, the kind of question, a reference answer and the \
facts a correct answer must contain (both taken from that version's documentation), and the \
answer.

Grades:
- correct: the answer states every required fact, in any wording, and nothing the reference \
contradicts.
- partially_correct: it states some of the required facts and nothing the reference contradicts.
- wrong: it states none of them, or states something the reference contradicts, or invents an \
API, an option or a behaviour.
- refused: it says the documentation does not cover the question, or that it does not know, or \
declines, and states no facts.

A question of kind "unanswerable" has no facts: this version's documentation does not answer it. \
Grade an answer that says the documentation does not cover it, or that it does not know, refused \
(the benchmark counts that as the right answer for such a question), and an answer that answers \
anyway (from another version, from memory, or invented) wrong.

Parts of the answer may read [redacted]: names were removed from it. Ignore them.

Set wrong_version to true when the answer states something that holds for another version of \
the library but not for this one, for example an option this version renamed or removed.

Grade against the reference and the facts only, not your own knowledge of the library. Give the \
reason in one or two sentences."""
"""The judge's instructions."""


class Verdict(BaseModel):
    """The judge's grade of one answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grade: Grade
    """The grade."""
    wrong_version: bool
    """The answer states something true of another version only."""
    reason: str
    """Why, in one or two sentences."""


def judge_agent(model: Model | str) -> Agent[None, Verdict]:
    """Build the judge.

    Args:
        model: A pydantic-ai model or model name.

    Returns:
        The agent; it has no tools.
    """
    return Agent(model, output_type=Verdict, instructions=JUDGE_INSTRUCTIONS, retries=2)


def judge_prompt(question: Question, info: BenchInfo, answer: str) -> str:
    """Write what the judge is asked about one answer.

    Args:
        question: The golden question.
        info: The case's expectations.
        answer: The agent's answer.

    Returns:
        ``PROMPT_HEAD`` and the case as JSON, the answer with every arm's product and tool names
        removed.
    """
    case = {
        "library": info.title,
        "version": question.version,
        "kind": info.kind,
        "question": question.query,
        "reference": info.reference,
        "facts": info.facts,
        "answer": blind(answer),
    }
    return PROMPT_HEAD + json.dumps(case, ensure_ascii=False, indent=2)


@dataclass(repr=False)
class AnswerJudge(Evaluator[Question, AgentRun, BenchInfo]):
    """Labels each answer with the judge's grade and asserts whether it is of another version."""

    judge: Agent[None, Verdict]
    """The judge."""

    async def evaluate(
        self, ctx: EvaluatorContext[Question, AgentRun, BenchInfo]
    ) -> dict[str, EvaluationReason]:
        """Grade one answer; a run that ended without an answer is not judged.

        Args:
            ctx: The question, the agent's run and the case's expectations.

        Returns:
            ``grade`` (a label: a judge's grade, or ``no_answer`` / ``error`` for a run without
            an answer) and ``wrong_version`` (an assertion), each with the reason.

        Raises:
            ValueError: The case has no metadata.
        """
        if ctx.metadata is None:
            message = f"{ctx.name}: no case metadata"
            raise ValueError(message)
        run = ctx.output
        if run.error and not run.answer:
            grade = ERROR if run.failure == "provider" else NO_ANSWER
            reason = f"no answer: {run.error}"
            return {
                GRADE: EvaluationReason(value=grade, reason=reason),
                WRONG_VERSION: EvaluationReason(value=False, reason=reason),
            }
        prompt = judge_prompt(ctx.inputs, ctx.metadata, run.answer)
        verdict = (await self.judge.run(prompt)).output
        return {
            GRADE: EvaluationReason(value=verdict.grade, reason=verdict.reason),
            WRONG_VERSION: EvaluationReason(value=verdict.wrong_version, reason=verdict.reason),
        }
