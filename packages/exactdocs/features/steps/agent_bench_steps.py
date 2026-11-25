"""Steps for the agent benchmark's documentation arms (packages/exactdocs/evals, #495).

The benchmark runs in-process with the stand-in models of ``agent_bench.offline`` (pydantic-ai
``FunctionModel``s, ``offline:think`` returning thinking as a thinking model does) and the stand-in
documentation servers of ``agent_bench_stand_ins`` (in-process MCP servers shaped like ExactDocs',
Context7's and Grounded Docs'): no provider and no real server, so every arm runs in a fraction of
a second.
"""

import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_bench.arms import ARMS, EXACTDOCS, NONE, parse_arms
from agent_bench.cli import JobKey, load_rows, run_bench
from agent_bench.harness import AgentRun, RetrievalConfig, bench_dataset
from agent_bench.judge import PROMPT_HEAD, AnswerJudge, judge_agent
from agent_bench.offline import OFFLINE_AGENTS, OFFLINE_JUDGE, OFFLINE_THINKING, offline_verdict
from agent_bench.report import QuestionResult, results_of
from agent_bench_stand_ins import FlakyProvider, golden, stand_in_tools
from retrieval_eval.dataset import Question

FAILING = "install the package now"
"""Part of the question the provider fails on."""
MAX_REQUESTS = 8
"""The request limit every arm runs under here."""
CASES = 3
"""Questions in the stand-in golden set."""
STAND_IN_EXACTDOCS = frozenset({"list_libraries", "search_docs", "read_chunk"})
"""The tools the stand-in ExactDocs lists (the arm takes every tool its server lists)."""


@given("a golden set with answerable and unanswerable questions")
def step_golden(context: Context) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="exactdocs-agent-bench-"))
    context.add_cleanup(shutil.rmtree, tmp, ignore_errors=True)
    context.bench_dir = tmp
    context.corpus, context.cases = golden()
    context.models = None


@given("scripted agent models, one of them thinking, and a scripted judge")
def step_models(context: Context) -> None:
    context.agent_models = OFFLINE_AGENTS
    assert OFFLINE_THINKING in context.agent_models


@given("the provider fails on one question")
def step_flaky(context: Context) -> None:
    context.models = FlakyProvider(on=FAILING)


def _run(context: Context, arms: str, done: dict[JobKey, QuestionResult] | None = None) -> None:
    context.arms = arms.split(",")
    context.report = asyncio.run(
        run_bench(
            context.cases,
            context.corpus,
            {},
            agent_models=context.agent_models,
            judge_model=OFFLINE_JUDGE,
            arms=parse_arms([arms]),
            retrieval=[RetrievalConfig.parse("bm25:mode=bm25")],
            work_dir=context.bench_dir,
            max_requests=MAX_REQUESTS,
            concurrency=3,
            tools=stand_in_tools,
            models=context.models,
            checkpoint=context.bench_dir / "rows.jsonl",
            done=done,
        )
    )


@when("the agent benchmark runs the arms {arms}")
def step_run(context: Context, arms: str) -> None:
    _run(context, ",".join(re.findall(r'"([^"]+)"', arms)))


@then("each arm gets the same prompt, the same usage limits and only its own tools")
def step_same_setup(context: Context) -> None:
    meta = context.report.meta
    assert meta.arms == context.arms
    assert "{title}" in meta.prompt  # one template for every arm
    assert meta.max_requests == MAX_REQUESTS
    for row in context.report.questions:
        names = {call.name for call in row.tool_calls}
        if row.arm == NONE:
            assert not names, row
            continue
        own = ARMS[row.arm].tools
        assert names, row
        assert names <= (STAND_IN_EXACTDOCS if own is None else set(own)), row


@then("the instructions of the arms differ only in the sentence about the documentation tool")
def step_same_instructions(context: Context) -> None:
    given = context.report.meta.agent_instructions
    assert set(given) == set(context.arms)
    none, exactdocs = given["none"].split("\n\n"), given["exactdocs"].split("\n\n")
    assert none[1:] == exactdocs[1:]
    assert none[0].split(". ")[0] == exactdocs[0].split(". ")[0]
    for arm, text in given.items():
        tool = ARMS[arm].tool
        if tool is not None:
            assert text == given["exactdocs"].replace("ExactDocs", tool), arm


@then("the report gives accuracy per arm, question kind and project, with intervals")
def step_accuracy(context: Context) -> None:
    for cell in context.report.cells:
        assert "accuracy" in cell.intervals, cell.arm
        assert set(cell.by_kind) == {"how-to", "version-change", "unanswerable"}
        assert all(b.interval is not None for b in cell.by_kind.values())
        assert cell.by_project["demo"].interval is not None


@then('each arm is compared with "none" and with "exactdocs" by a paired test')
def step_paired(context: Context) -> None:
    for cell in context.report.cells:
        expected = {NONE: [], EXACTDOCS: [NONE]}.get(cell.arm, [NONE, EXACTDOCS])
        assert [v.against for v in cell.versus] == expected, cell.arm
        for versus in cell.versus:
            assert versus.cases == CASES
            assert versus.accuracy is not None
            assert versus.accuracy.test == "mcnemar-mid-p"


@then(
    "the report gives, per arm, the wall time per question, the input tokens and the output "
    "tokens including thinking, each as mean, p50 and p95 with an interval"
)
def step_costs(context: Context) -> None:
    for cell in context.report.cells:
        for cost in (cell.seconds, cell.input_tokens, cell.output_tokens):
            assert cost is not None, cell.arm
            assert cost.p50 <= cost.p95
            assert cost.interval is not None
            assert cost.interval.low <= cost.mean <= cost.interval.high
    thinking = [q for q in context.report.questions if q.agent_model == OFFLINE_THINKING]
    plain = [q for q in context.report.questions if q.agent_model == "offline:read"]
    for think, read in zip(thinking, plain, strict=True):
        assert think.output_tokens > read.output_tokens  # the thinking is counted in the output


@then(
    "the thinking tokens on their own where the model returns its thinking, marked estimated, "
    "and as not returned where it does not"
)
def step_thinking(context: Context) -> None:
    for cell in context.report.cells:
        if cell.agent_model == OFFLINE_THINKING:
            assert cell.thinking_tokens is not None
            assert cell.thinking_estimated
            assert cell.output_tokens is not None
            assert 0 < cell.thinking_tokens.mean < cell.output_tokens.mean
        else:
            assert cell.thinking_tokens is None  # not returned, not 0
    for row in context.report.questions:
        assert (row.thinking_tokens is not None) == (row.agent_model == OFFLINE_THINKING)


@then("a model without a price costs nothing known rather than zero")
def step_unpriced(context: Context) -> None:
    assert all(cell.usd is None and cell.usd_per_question is None for cell in context.report.cells)
    assert all(row.usd is None for row in context.report.questions)


@then('each arm\'s time and tokens are compared with the "none" arm on the same cases')
def step_cost_paired(context: Context) -> None:
    for cell in context.report.cells:
        if cell.arm == NONE:
            continue
        versus = next(v for v in cell.versus if v.against == NONE)
        for test in (versus.seconds, versus.input_tokens, versus.output_tokens):
            assert test is not None
            assert test.test == "permutation"
            assert test.cases == versus.cases
        assert versus.seconds_ratio is not None
        assert versus.output_tokens_ratio is not None


@given("an answer that names ExactDocs and its tools")
def step_named_answer(context: Context) -> None:
    context.answer = (
        "ExactDocs' search_docs and read_chunk show it: install the package with pip install demo."
    )


@when("the answer is judged")
def step_judge(context: Context) -> None:
    seen: list[str] = []

    def judge(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request = messages[0]
        assert isinstance(request, ModelRequest)
        prompt = next(p.content for p in request.parts if isinstance(p, UserPromptPart))
        assert isinstance(prompt, str)
        seen.append(prompt)
        verdict = offline_verdict(json.loads(prompt.removeprefix(PROMPT_HEAD)))
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, verdict.model_dump(mode="json"))]
        )

    dataset = bench_dataset(context.cases[:1], context.corpus)
    dataset.add_evaluator(AnswerJudge(judge=judge_agent(FunctionModel(judge))))

    async def task(question: Question) -> AgentRun:
        del question
        return AgentRun(answer=context.answer)

    evaluated = asyncio.run(dataset.evaluate(task, progress=False))
    context.judged = results_of(evaluated, "offline:read", "bm25")
    context.judge_prompts = seen


@then("the judge sees the question, reference and answer only, with tool and product names removed")
def step_blind(context: Context) -> None:
    [prompt] = context.judge_prompts
    case = json.loads(prompt.removeprefix(PROMPT_HEAD))
    assert set(case) == {"library", "version", "kind", "question", "reference", "facts", "answer"}
    for name in ("ExactDocs", "search_docs", "read_chunk", "exactdocs", "bm25", "offline"):
        assert name not in prompt, name
    assert "install the package with pip install demo" in case["answer"]
    [row] = context.judged
    assert row.grade == "correct"
    assert row.answer == context.answer  # the report keeps the answer as given


@then(
    "that question is graded as an error in both arms and left out of the accuracy and the "
    "paired tests"
)
def step_errors(context: Context) -> None:
    failed = [q for q in context.report.questions if q.grade == "error"]
    assert {q.arm for q in failed} == set(context.arms)
    assert all(FAILING in q.question for q in failed)
    assert not [q for q in context.report.questions if q.grade == "wrong" and FAILING in q.question]
    for cell in context.report.cells:
        assert (cell.questions, cell.answered, cell.grades["error"]) == (CASES, CASES - 1, 1)
        assert all(v.cases == CASES - 1 for v in cell.versus)


@then("a resumed run asks only that question again")
def step_resume(context: Context) -> None:
    done = load_rows(context.bench_dir / "rows.jsonl")
    kept = {k: r for k, r in done.items() if r.grade != "error"}
    context.models.failing = False
    _run(context, ",".join(context.arms), done=done)
    for row in context.report.questions:
        assert row.grade != "error", row
        key = (row.agent_model, row.arm, row.retrieval, row.case)
        if key in kept:
            assert row == kept[key]  # not asked again
        else:
            assert FAILING in row.question
