"""The agent benchmark's documentation arms (#495): none and exactdocs, cost per arm, a blind judge.

Every test here runs in the default pytest run with scripted models (pydantic-ai ``FunctionModel``)
and the stand-in documentation tools of ``agent_bench_stand_ins``: no provider, no ExactDocs
server.
"""

from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.usage import RequestUsage

from agent_bench.arms import ARMS, EXACTDOCS, NONE, REDACTED, blind, parse_arms
from agent_bench.cli import load_rows, run_bench, selected_cases
from agent_bench.harness import (
    AgentRun,
    BenchInfo,
    Recorder,
    RetrievalConfig,
    asker,
    bench_dataset,
    failure_of,
    server_environment,
    thinking_tokens_of,
)
from agent_bench.judge import AnswerJudge, judge_agent, judge_prompt
from agent_bench.models import chat_model, model_settings, providers_used, thinking_setting
from agent_bench.offline import OFFLINE_AGENTS, OFFLINE_JUDGE, OFFLINE_THINKING, offline_judge
from agent_bench.redact import REDACTED as SECRET
from agent_bench.redact import recorded_settings, safe_url, scrub
from agent_bench.report import QuestionResult, against_arms, markdown, results_of, summarize
from agent_bench.retries import RETRIES, RetryLog, on_request, on_response
from agent_bench_stand_ins import golden, stand_in_tools
from retrieval_eval.dataset import Question
from retrieval_eval.golden import load_cases

# ------------------------------------------------------------------------------------- arms


def test_the_arms_have_the_same_instructions_apart_from_the_tool() -> None:
    none, exactdocs = ARMS[NONE].instructions, ARMS[EXACTDOCS].instructions
    context7, grounded = ARMS["context7"].instructions, ARMS["grounded-docs"].instructions

    assert "no tools" in none
    assert "say that you do not know" in none
    assert "the ExactDocs tools" in exactdocs
    assert context7 == exactdocs.replace("ExactDocs", "Context7")
    assert grounded == exactdocs.replace("ExactDocs", "Grounded Docs")
    head, tail = none.split("\n\n")[0].split(".")[0], none.split("\n\n")[1]
    for text in (exactdocs, context7, grounded):
        assert text.startswith(head)
        assert text.endswith(tail)


def test_the_arms_asked_are_read_in_order_and_unbuilt_ones_are_refused() -> None:
    assert [a.name for a in parse_arms([])] == ["none", "exactdocs"]
    assert [a.name for a in parse_arms(["exactdocs", "none"])] == ["none", "exactdocs"]
    assert [a.name for a in parse_arms(["exactdocs,none,exactdocs"])] == ["none", "exactdocs"]
    with pytest.raises(ValueError, match="unknown arm 'web'"):
        parse_arms(["web"])
    with pytest.raises(ValueError, match=r"context7 arm is not built yet \(#493\)"):
        parse_arms(["context7"])


# ------------------------------------------------------------------------------ blind judge


def test_the_judge_reads_the_answer_without_any_arm_s_product_or_tool_names() -> None:
    answer = (
        "ExactDocs' search_docs and `read_chunk` say: use uv add. Context7's get-library-docs "
        "and Grounded Docs agree; exactdocs is case-blind. A query-docs-like word stays."
    )
    blinded = blind(answer)
    for name in ("ExactDocs", "exactdocs", "search_docs", "read_chunk", "Context7", "Grounded"):
        assert name not in blinded
    assert blinded.count(REDACTED) == 7
    assert "use uv add" in blinded
    assert "query-docs-like" in blinded  # a whole word only

    info = BenchInfo(
        kind="how-to", project="demo", title="Demo", library="/acme/demo", reference="r"
    )
    prompt = judge_prompt(Question(query="q", version="v1", project="demo"), info, answer)
    assert "ExactDocs" not in prompt
    assert "search_docs" not in prompt
    for arm in ARMS:
        assert f'"{arm}"' not in prompt  # nothing of the run but the answer reaches the judge


async def test_a_run_without_an_answer_is_not_judged_and_whose_side_failed_decides_its_grade() -> (
    None
):
    corpus, cases = golden()
    dataset = bench_dataset(cases[:2], corpus)
    dataset.add_evaluator(AnswerJudge(judge=judge_agent(offline_judge())))
    runs = {
        cases[0][1].inputs.query: AgentRun(
            answer="", error="UsageLimitExceeded: x", failure="no_answer"
        ),
        cases[1][1].inputs.query: AgentRun(
            answer="", error="ModelHTTPError: 429", failure="provider"
        ),
    }

    async def task(question: Question) -> AgentRun:
        return runs[question.query]

    rows = results_of(await dataset.evaluate(task, progress=False), "m", "bm25")

    assert [r.grade for r in rows] == ["no_answer", "error"]
    assert not any(r.wrong_version for r in rows)
    cell = summarize("m", "bm25", rows)
    assert (cell.questions, cell.answered, cell.accuracy) == (2, 1, 0.0)


# ---------------------------------------------------------------------------------- secrets


def test_recorded_settings_and_errors_never_hold_a_key() -> None:
    settings = recorded_settings(
        {
            "EXACTDOCS_AI__MODE": "hybrid",
            "EXACTDOCS_AI__PROVIDERS__EVAL__API_KEY": "sk-live-1234567890",
            "EXACTDOCS_AI__PROVIDERS__EVAL__BASE_URL": "https://user:pw@gw.example.com/v1?key=k",
        }
    )
    assert settings == {
        "EXACTDOCS_AI__MODE": "hybrid",
        "EXACTDOCS_AI__PROVIDERS__EVAL__API_KEY": SECRET,
        "EXACTDOCS_AI__PROVIDERS__EVAL__BASE_URL": "https://gw.example.com/v1",
    }
    assert safe_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    env = {"OLLAMA_API_KEY": "abcd1234efgh5678", "HOME": "/root/abcd1234efgh5678x"}
    text = "401: key abcd1234efgh5678 refused; Authorization: Bearer sk-abcdefghijk"
    assert scrub(text, env) == f"401: key {SECRET} refused; Authorization: Bearer {SECRET}"
    assert scrub("max token limit reached", env) == "max token limit reached"


def test_the_exactdocs_server_gets_its_own_settings_but_not_the_agents_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "agent-key-123456")
    monkeypatch.setenv("OPENAI_API_KEY", "agent-key-654321")
    monkeypatch.setenv("EXACTDOCS_AI__PROVIDERS__EVAL__API_KEY", "server-key-123456")
    env = server_environment({"EXACTDOCS_AI__MODE": "bm25"}, tmp_path)
    assert "OLLAMA_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert env["EXACTDOCS_AI__PROVIDERS__EVAL__API_KEY"] == "server-key-123456"
    assert (env["EXACTDOCS_AI__MODE"], env["EXACTDOCS_DATA_DIR"]) == ("bm25", str(tmp_path))
    assert "PATH" in env


async def test_a_run_s_report_holds_no_secret_from_its_settings(tmp_path: Path) -> None:
    corpus, cases = golden()
    report = await run_bench(
        cases,
        corpus,
        {},
        agent_models=["offline:read"],
        judge_model=OFFLINE_JUDGE,
        arms=parse_arms(["exactdocs"]),
        retrieval=[RetrievalConfig.parse("bm25:mode=bm25,providers.eval.api_key=sk-12345678")],
        work_dir=tmp_path,
        tools=stand_in_tools,
    )
    assert "sk-12345678" not in report.model_dump_json()
    assert report.meta.retrieval["bm25"]["EXACTDOCS_AI__PROVIDERS__EVAL__API_KEY"] == SECRET


# ---------------------------------------------------------------------- thinking, failures


def _response(*parts: Any, output: int, details: dict[str, int] | None = None) -> ModelResponse:
    return ModelResponse(
        parts=list(parts), usage=RequestUsage(output_tokens=output, details=details or {})
    )


def test_thinking_tokens_are_reported_estimated_or_not_returned() -> None:
    reported = _response(TextPart("a"), output=50, details={"reasoning_tokens": 30})
    thought = _response(ThinkingPart("t" * 300), TextPart("x" * 100), output=100)
    called = _response(ThinkingPart("t" * 50), ToolCallPart("search_docs", {"q": "ab"}), output=40)
    plain = _response(TextPart("an answer"), output=10)

    assert thinking_tokens_of([reported]) == (30, False, 0)
    assert thinking_tokens_of([thought]) == (75, True, 300)  # 300 of 400 characters: 3/4
    tokens, estimated, chars = thinking_tokens_of([thought, called, plain])
    assert (estimated, chars) == (True, 350)
    assert tokens is not None
    assert 75 < tokens < 75 + 40  # the tool call's arguments take a share of its tokens
    assert thinking_tokens_of([plain]) == (None, False, 0)  # not returned is not 0
    assert thinking_tokens_of([]) == (None, False, 0)


def test_a_failed_run_is_the_agent_s_or_the_provider_s() -> None:
    assert failure_of(UsageLimitExceeded("request_limit of 20")) == "no_answer"
    assert failure_of(ModelHTTPError(400, "m", body="context too long")) == "no_answer"
    assert failure_of(ModelHTTPError(429, "m", body="rate limited")) == "provider"
    assert failure_of(ModelHTTPError(503, "m")) == "provider"
    assert failure_of(ModelAPIError("m", "connection lost")) == "provider"


async def test_the_task_records_a_provider_failure_without_a_key_and_the_thinking() -> None:
    def rate_limited(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise ModelHTTPError(429, "m", body="slow down, Bearer sk-abcdefghijkl")

    ask = asker(
        Agent[Recorder, str](FunctionModel(rate_limited), deps_type=Recorder),
        "m",
        {"demo": "Demo"},
        max_requests=5,
    )
    failed = await ask(Question(query="q", version="v1", project="demo"))
    assert (failed.answer, failed.failure) == ("", "provider")
    assert failed.error is not None
    assert "sk-abcdefghijkl" not in failed.error

    thinking = asker(
        Agent[Recorder, str](chat_model(OFFLINE_THINKING), deps_type=Recorder),
        OFFLINE_THINKING,
        {"demo": "Demo"},
        max_requests=5,
        settings=model_settings(thinking_setting("high")),
    )
    run = await thinking(Question(query="q", version="v1", project="demo"))
    assert run.answer.startswith("I do not know")
    assert run.thinking_estimated
    assert run.thinking_tokens is not None
    assert 0 < run.thinking_tokens < run.output_tokens


async def test_the_time_lost_to_retries_is_measured_per_run() -> None:
    log = RetryLog()
    token = RETRIES.set(log)
    try:
        first = httpx2.Request("POST", "https://ollama.example.com/v1/chat/completions")
        await on_request(first)
        await on_response(httpx2.Response(429, request=first))
        retry = httpx2.Request("POST", "https://ollama.example.com/v1/chat/completions")
        await on_request(retry)
        await on_response(httpx2.Response(200, request=retry))
    finally:
        RETRIES.reset(token)
    assert log.failed == 1
    assert log.seconds > 0
    assert log.pending is None


def test_model_names_and_the_thinking_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://user:secret-pass@ollama.example.com/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-a-real-key")
    model = chat_model("ollama:gpt-oss:120b", max_retries=3)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "gpt-oss:120b"
    assert chat_model("openai:gpt-5-mini") == "openai:gpt-5-mini"
    assert isinstance(chat_model(OFFLINE_AGENTS[0]), FunctionModel)
    assert providers_used(["ollama:kimi-k3", "offline"]) == {
        "ollama": "https://ollama.example.com/v1"  # no user or password
    }
    assert providers_used(["offline"]) == {}
    assert [thinking_setting(t) for t in (None, "", "medium", "ON", "off")] == [
        None,
        None,
        "medium",
        True,
        False,
    ]
    assert model_settings(None) is None
    monkeypatch.delenv("OLLAMA_BASE_URL")
    with pytest.raises(Exception, match="OLLAMA_BASE_URL"):
        chat_model("ollama:gpt-oss:120b")


# ------------------------------------------------------------------------ both arms, end to end


async def test_every_arm_answers_with_scripted_models_and_is_compared_with_none(
    tmp_path: Path,
) -> None:
    corpus, cases = golden()
    checkpoint = tmp_path / "rows.jsonl"
    report = await run_bench(
        cases,
        corpus,
        {},
        agent_models=OFFLINE_AGENTS,
        judge_model=OFFLINE_JUDGE,
        arms=parse_arms(["none,exactdocs"]),
        retrieval=[RetrievalConfig.parse("bm25:mode=bm25")],
        work_dir=tmp_path,
        concurrency=3,
        thinking="medium",
        tools=stand_in_tools,
        checkpoint=checkpoint,
    )

    assert [(c.agent_model, c.arm, c.retrieval) for c in report.cells] == [
        (model, arm, retrieval)
        for model in OFFLINE_AGENTS
        for arm, retrieval in (("none", ""), ("exactdocs", "bm25"))
    ]
    assert report.meta.arms == ["none", "exactdocs"]
    assert set(report.meta.agent_instructions) == {"none", "exactdocs"}
    assert report.meta.thinking == "medium"
    for row in report.questions:
        names = [c.name for c in row.tool_calls]
        if row.arm == "none":
            assert (names, row.grade) == ([], "refused"), row  # no tools: it does not know
        else:
            assert names[:2] == ["list_libraries", "search_docs"], row
    cells = {(c.agent_model, c.arm): c for c in report.cells}
    none, read = cells["offline:read", "none"], cells["offline:read", "exactdocs"]
    assert none.correct_refusals == 1
    assert none.refused_answerable == 2
    assert none.tool_calls is not None
    assert none.tool_calls.mean == 0
    assert read.accuracy == 1  # it reads both answers and finds nothing for the third
    assert read.by_kind["how-to"].accuracy == 1
    assert "accuracy" in read.intervals
    for cell in report.cells:
        for cost in (cell.seconds, cell.input_tokens, cell.output_tokens, cell.tool_calls):
            assert cost is not None
            assert cost.p50 <= cost.p95
            assert cost.interval is not None
        assert cell.usd is None  # unpriced, never 0
        if cell.agent_model == OFFLINE_THINKING:
            assert cell.thinking_tokens is not None
            assert cell.thinking_estimated
        else:
            assert cell.thinking_tokens is None
    [versus] = read.versus
    assert (versus.against, versus.cases) == ("none", 3)
    assert versus.accuracy is not None
    assert (versus.accuracy.gained, versus.accuracy.lost) == (2, 0)
    assert versus.output_tokens is not None
    assert versus.seconds is not None
    assert versus.input_tokens is not None
    assert versus.input_tokens.difference > 0
    assert none.versus == []
    text = markdown(report)
    assert "## Against the other arms, on the same cases" in text
    assert "| `offline:think` | exactdocs (bm25) |" in text
    assert "(estimated)" in text
    assert "not returned" in text
    assert len(load_rows(checkpoint)) == len(report.questions) == 18


async def test_a_resumed_run_asks_only_what_failed_on_the_provider_s_side(tmp_path: Path) -> None:
    corpus, cases = golden()
    checkpoint = tmp_path / "rows.jsonl"
    first = await run_bench(
        cases,
        corpus,
        {},
        agent_models=["offline:read"],
        judge_model=OFFLINE_JUDGE,
        arms=parse_arms([]),
        retrieval=[RetrievalConfig.parse("bm25:mode=bm25")],
        work_dir=tmp_path,
        tools=stand_in_tools,
        checkpoint=checkpoint,
    )
    done = load_rows(checkpoint)
    failed_key = next(k for k in done if k[1] == "exactdocs")
    done[failed_key] = done[failed_key].model_copy(update={"grade": "error", "judge_reason": "429"})
    kept_key = next(k for k in done if k[1] == "none")
    done[kept_key] = done[kept_key].model_copy(update={"judge_reason": "from the checkpoint"})

    again = await run_bench(
        cases,
        corpus,
        {},
        agent_models=["offline:read"],
        judge_model=OFFLINE_JUDGE,
        arms=parse_arms([]),
        retrieval=[RetrievalConfig.parse("bm25:mode=bm25")],
        work_dir=tmp_path,
        tools=stand_in_tools,
        done=done,
    )

    rows = {(q.agent_model, q.arm, q.retrieval, q.case): q for q in again.questions}
    assert len(rows) == len(first.questions)
    assert rows[failed_key].grade != "error"  # asked again
    assert rows[kept_key].judge_reason == "from the checkpoint"  # not asked again


# --------------------------------------------------------------------------- report, sample


def _row(case: str, arm: str, **changes: Any) -> QuestionResult:
    values: dict[str, Any] = {
        "agent_model": "m",
        "arm": arm,
        "retrieval": "bm25" if arm == EXACTDOCS else "",
        "case": case,
        "project": "demo",
        "kind": "how-to",
        "version": "v1",
        "question": "q",
        "grade": "correct",
        "seconds": 10.0,
        "input_tokens": 1000,
        "output_tokens": 300,
    }
    return QuestionResult(**(values | changes))


def test_a_provider_failure_is_left_out_of_every_rate_mean_and_test() -> None:
    none = [
        _row(f"c{i}", NONE, grade="wrong", seconds=2.0, output_tokens=200, thinking_tokens=100)
        for i in range(10)
    ]
    exact = [_row(f"c{i}", EXACTDOCS, seconds=6.0 + i, retry_seconds=1.0) for i in range(10)]
    exact[0] = exact[0].model_copy(update={"grade": "error", "seconds": 999.0})
    rows = none + exact
    cells = [summarize("m", "", none, arm=NONE), summarize("m", "bm25", exact, arm=EXACTDOCS)]

    first, second = against_arms(cells, rows)

    assert (second.questions, second.answered, second.grades["error"]) == (10, 9, 1)
    assert second.accuracy == 1
    assert second.seconds is not None
    assert second.seconds.mean == pytest.approx(sum(5.0 + i for i in range(1, 10)) / 9)
    assert (second.seconds.p50, second.seconds.p95) == (10.0, 14.0)
    assert second.thinking_tokens is None
    assert first.thinking_tokens is not None
    assert first.thinking_returned == 10
    assert first.versus == []
    [versus] = second.versus
    assert versus.cases == 9
    assert versus.accuracy is not None
    assert versus.accuracy.significant
    assert versus.seconds is not None
    assert versus.seconds.difference == pytest.approx(10.0 - 2.0)
    assert versus.seconds_ratio == pytest.approx(5.0)
    assert versus.output_tokens_ratio == pytest.approx(1.5)


def test_a_stratified_sample_takes_each_kind_of_each_project() -> None:
    cases, problems = load_cases()
    assert not problems
    picked = selected_cases(cases, per_stratum=3, seed=495)
    strata = {(p, c.metadata.kind if c.metadata else "") for p, c in cases}
    assert len(picked) == 3 * len(strata) == 90
    assert picked == selected_cases(cases, per_stratum=3, seed=495)
    assert picked != selected_cases(cases, per_stratum=3, seed=1)
    assert len(selected_cases(cases, per_stratum=3, projects=["zod"], limit=5)) == 5
