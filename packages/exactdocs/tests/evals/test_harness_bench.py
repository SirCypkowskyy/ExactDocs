"""The harness benchmark (#497): coding-agent CLIs run headless with each documentation arm.

Everything here runs in the default suite, with no container, no CLI install and no provider:

- each harness's transcript parser on recorded transcripts (``tests/fixtures/harness_transcripts``):
  OpenCode's and Codex's were captured from real runs of the pinned CLIs (Ollama Cloud,
  ``gpt-oss:120b``), their local paths replaced; Claude Code's and Gemini CLI's are built from their
  documented stream-JSON formats as the pinned releases write them (Claude Code 2.1.330's ``init``
  and ``result`` messages, Gemini CLI 0.70.0's ``StreamJsonFormatter``), since no run of either was
  possible without their providers' keys;
- each harness's configuration (web tools off, only the arm's MCP server, the key passed by name);
- the gate (tunnels only to allowed hosts, forwards, ``NO_PROXY``);
- whole runs with a stand-in CLI (Claude Code's adapter, its CLI replaced by
  ``harness_stand_in_cli.py``) behind the gate on loopback, on the stand-in coding tasks and golden
  questions, graded and judged, and the report with its paired comparisons.

The test that runs a container is marked ``integration``.
"""

import asyncio
import json
import shutil
import tomllib
from pathlib import Path

import pytest

from agent_bench.arms import ARMS, EXACTDOCS, NONE
from agent_bench.cli import setups_of
from agent_bench.harness import RetrievalConfig, bench_dataset
from agent_bench.judge import AnswerJudge, judge_agent
from agent_bench.models import chat_model
from agent_bench.offline import OFFLINE_JUDGE
from agent_bench_stand_ins import golden
from coding_task_stand_ins import V1, V2, prepared, stand_in_tasks
from coding_tasks.evaluators import task_dataset
from coding_tasks.sandbox import Limits, ProcessSandbox
from harness_bench.claude_code import ClaudeCode
from harness_bench.cli import main
from harness_bench.codex import Codex
from harness_bench.container import CliRun, DockerRunner, Placement, ProcessRunner, RunLimits
from harness_bench.gate import bypassed, opened, upstream_for
from harness_bench.gemini_cli import GeminiCli
from harness_bench.harness import HarnessModel, HarnessRun, Invocation, McpServer
from harness_bench.jobs import QuestionJob, TaskJob, agent_run
from harness_bench.opencode import OpenCode
from harness_bench.releases import HARNESSES
from harness_bench.report import cells_of, markdown
from harness_bench.run import Installed, Plan, classify, key_of, load_rows, run_bench
from harness_bench.transcript import Transcript, provider_failed
from harness_stand_ins import MODEL, STAND_IN_CLI, StandInEndpoints, StandInHarness, solutions

TRANSCRIPTS = Path(__file__).parents[1] / "fixtures" / "harness_transcripts"
FAST = Limits(wall_seconds=60, cpu_seconds=60, memory_mb=1024)


def _run(model: str, *, server: str | None = "exactdocs", tmp: Path | None = None) -> HarnessRun:
    mcp = None
    if server:
        mcp = McpServer(
            name=server,
            url="http://services.harness.internal:4321/mcp",
            tools=("search_docs", "read_chunk"),
            excluded=("fetch_url",),
            headers={"Authorization": "Bearer exactdocs-token"},
        )
    root = tmp or Path("/work/run")
    return HarnessRun(
        workspace=root / "workspace",
        home=root / "home",
        prompt="My project uses Zod at version v4.6.7.\n\nAdd a message.",
        model=HarnessModel.parse(model, thinking="high", env={}),
        mcp=mcp,
        max_turns=12,
    )


def _transcript(
    harness: str, name: str, model: str, server: str | None = "exactdocs"
) -> Transcript:
    text = (TRANSCRIPTS / f"{name}.jsonl").read_text(encoding="utf-8")
    return HARNESSES[harness].parse(text, _run(model, server=server))


# ------------------------------------------------------------------------------- the parsers


def test_claude_code_stream_json_gives_calls_mcp_calls_tokens_and_cost() -> None:
    t = _transcript("claude-code", "claude-code-exactdocs", "anthropic:claude-sonnet-4-5")

    assert [c.name for c in t.calls] == [
        "mcp__exactdocs__search_docs",
        "Read",
        "WebFetch",
        "Edit",
        "Bash",
    ]
    assert t.docs_calls("exactdocs") == 1
    assert t.calls[0].server == "exactdocs"
    assert t.calls[0].tool == "search_docs"
    assert '"ref": "v4.6.7"' in t.calls[0].args
    web = t.calls[2]
    assert web.web
    assert web.error is not None
    assert "No such tool" in web.error
    assert "WebSearch" not in t.tools_offered
    assert "mcp__exactdocs__search_docs" in t.tools_offered
    assert (t.input_tokens, t.cached_input_tokens, t.output_tokens) == (93_286, 77_248, 487)
    assert t.thinking_tokens is None
    assert t.thinking == "not reported"
    assert t.thinking_chars > 0
    assert (t.usd, t.usd_source) == (0.08437, "reported")
    assert t.turns == 6
    assert t.reported_seconds == pytest.approx(41.873)
    assert t.cli_version == "2.1.330"
    assert t.answer.startswith("I changed")
    assert t.error is None
    assert t.unparsed == 0


def test_claude_code_rate_limit_is_the_providers_and_max_turns_the_agents() -> None:
    limited = _transcript("claude-code", "claude-code-rate-limited", "anthropic:claude-sonnet-4-5")
    turns = _transcript("claude-code", "claude-code-max-turns", "anthropic:claude-sonnet-4-5")

    assert limited.provider_failure
    assert not limited.answer
    assert turns.error is not None
    assert turns.error.startswith("error_max_turns")
    assert not turns.provider_failure
    assert turns.usd == pytest.approx(0.0451)


def test_gemini_cli_stream_json_derives_the_thinking_from_its_totals() -> None:
    t = _transcript("gemini-cli", "gemini-cli-exactdocs", "google:gemini-2.5-pro")

    assert [c.tool for c in t.calls if c.server] == ["resolve-library-id", "search_docs"]
    assert t.docs_calls("exactdocs") == 2
    assert [c.name for c in t.calls if c.web] == ["google_web_search"]
    assert (t.input_tokens, t.cached_input_tokens) == (57_120, 31_004)
    assert t.thinking_tokens == 61_204 - 57_120 - 1_210
    assert t.thinking == "derived"
    assert t.output_tokens == 1_210 + t.thinking_tokens
    assert t.usd_source == "price list"
    assert t.usd is not None
    assert t.usd > 0
    assert t.reported_seconds == pytest.approx(23.121)
    assert t.answer == "I passed the message with Zod 4's `error` parameter; the tests pass."
    assert t.unparsed == 0


def test_gemini_cli_quota_error_is_the_providers() -> None:
    t = _transcript("gemini-cli", "gemini-cli-quota", "google:gemini-2.5-pro")

    assert t.provider_failure
    assert t.error is not None
    assert "429" in t.error


def test_opencode_real_transcript() -> None:
    t = _transcript("opencode", "opencode-exactdocs", "ollama:gpt-oss:120b")

    mcp = [c.tool for c in t.calls if c.server == "exactdocs"]
    assert mcp == ["resolve-library-id", "search_docs", "search_docs"]
    assert len(t.calls) == 15
    assert t.turns == 16
    assert (t.input_tokens, t.output_tokens) == (192_557, 1_875)
    assert t.thinking_tokens is None  # Ollama's OpenAI-compatible API counts none on its own
    assert t.thinking == "not reported"
    assert t.thinking_chars > 0
    assert (t.usd, t.usd_source) == (None, "unpriced")
    assert t.answer
    assert t.error is None
    assert t.unparsed == 0
    assert not any(c.web for c in t.calls)


def test_opencode_rate_limit_is_the_providers() -> None:
    t = _transcript("opencode", "opencode-rate-limited", "ollama:gpt-oss:120b")

    assert t.provider_failure
    assert not t.answer


def test_codex_real_transcript() -> None:
    t = _transcript("codex", "codex-none", "ollama:gpt-oss:120b", server=None)

    assert [c.name for c in t.calls] == ["shell"]
    assert "echo hi > hello.txt" in t.calls[0].args
    assert t.answer == "done"
    assert (t.input_tokens, t.cached_input_tokens, t.output_tokens) == (17_817, 14_272, 574)
    assert t.thinking == "not reported"  # 0 reasoning tokens next to the reasoning text
    assert t.thinking_chars > 0
    assert t.turns == 1
    assert t.error is None


def test_codex_mcp_calls_web_search_and_reported_reasoning() -> None:
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "mcp_tool_call",
                "server": "exactdocs",
                "tool": "search_docs",
                "arguments": {"library": "/colinhacks/zod", "query": "error"},
                "result": {"content": []},
                "error": None,
                "status": "completed",
            },
        },
        {"type": "item.completed", "item": {"id": "item_1", "type": "web_search", "query": "zod"}},
        {
            "type": "item.completed",
            "item": {"id": "item_2", "type": "agent_message", "text": "Use the error param."},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1000,
                "cached_input_tokens": 400,
                "output_tokens": 300,
                "reasoning_output_tokens": 120,
            },
        },
    ]
    text = "\n".join(json.dumps(e) for e in events)
    t = Codex().parse(text, _run("openai:gpt-5"))

    assert t.docs_calls("exactdocs") == 1
    assert [c.web for c in t.calls] == [False, True]
    assert (t.thinking_tokens, t.thinking) == (120, "reported")
    assert t.usd_source == "price list"


def test_codex_turn_failed_is_the_providers() -> None:
    t = _transcript("codex", "codex-turn-failed", "ollama:gpt-oss:120b")

    assert t.provider_failure
    assert t.error is not None
    assert "429" in t.error


@pytest.mark.parametrize("harness", sorted(HARNESSES))
def test_a_transcript_that_is_not_one_is_an_error(harness: str) -> None:
    t = HARNESSES[harness].parse(
        "Error: something broke\nnot json\n",
        _run(
            next(
                f"{p}:m"
                for p in ("anthropic", "google", "ollama")
                if p in HARNESSES[harness].providers
            )
        ),
    )

    assert t.unparsed == 2
    assert not t.answer


# ------------------------------------------------------------------------- the configuration


def test_claude_code_configuration(tmp_path: Path) -> None:
    run = _run("anthropic:claude-sonnet-4-5", tmp=tmp_path)
    run.home.mkdir(parents=True)
    invocation = ClaudeCode().configure(run, Path("/cli/claude"))

    argv = list(invocation.argv)
    config = json.loads((run.home / "claude-mcp.json").read_text(encoding="utf-8"))
    disallowed = argv[argv.index("--disallowedTools") + 1 :]
    assert argv[:2] == ["/cli/claude", "-p"]
    assert {"--verbose", "--strict-mcp-config", "--no-session-persistence"} <= set(argv)
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--max-turns") + 1] == "12"
    assert {"WebSearch", "WebFetch", "mcp__exactdocs__fetch_url"} <= set(disallowed)
    assert config["mcpServers"]["exactdocs"]["type"] == "http"
    assert config["mcpServers"]["exactdocs"]["headers"]["Authorization"] == "Bearer exactdocs-token"
    assert invocation.secrets == ("ANTHROPIC_API_KEY",)
    assert invocation.env["IS_SANDBOX"] == "1"


def test_codex_configuration(tmp_path: Path) -> None:
    run = _run("ollama:gpt-oss:120b", tmp=tmp_path)
    run.home.mkdir(parents=True)
    invocation = Codex().configure(run, Path("/cli/codex"))

    config = tomllib.loads((run.home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    provider = config["model_providers"][config["model_provider"]]
    server = config["mcp_servers"]["exactdocs"]
    assert config["model_provider"] == "ollama-api"  # Codex reserves "ollama"
    assert (provider["base_url"], provider["env_key"]) == (
        "https://ollama.com/v1",
        "OLLAMA_API_KEY",
    )
    assert provider["wire_api"] == "responses"
    assert config["web_search"] == "disabled"
    assert config["model_reasoning_effort"] == "high"
    assert server["url"].endswith("/mcp")
    assert server["disabled_tools"] == ["fetch_url"]
    assert server["http_headers"] == {"Authorization": "Bearer exactdocs-token"}
    assert {"exec", "--json", "--strict-config"} <= set(invocation.argv)
    assert invocation.env["CODEX_HOME"] == str(run.home / ".codex")
    assert invocation.secrets == ("OLLAMA_API_KEY",)


def test_gemini_cli_configuration(tmp_path: Path) -> None:
    run = _run("google:gemini-2.5-pro", tmp=tmp_path)
    run.home.mkdir(parents=True)
    invocation = GeminiCli().configure(run, Path("/cli/gemini"))

    settings = json.loads((run.home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    argv = list(invocation.argv)
    assert settings["tools"]["exclude"] == ["google_web_search", "web_fetch"]
    assert settings["mcpServers"]["exactdocs"]["excludeTools"] == ["fetch_url"]
    assert settings["mcpServers"]["exactdocs"]["headers"]["Authorization"].startswith("Bearer")
    assert settings["model"]["maxSessionTurns"] == 12
    assert settings["privacy"]["usageStatisticsEnabled"] is False
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--allowed-mcp-server-names") + 1] == "exactdocs"
    assert invocation.secrets == ("GEMINI_API_KEY",)


def test_opencode_configuration(tmp_path: Path) -> None:
    run = _run("ollama:gpt-oss:120b", tmp=tmp_path)
    run.home.mkdir(parents=True)
    invocation = OpenCode().configure(run, Path("/cli/opencode"))

    config = json.loads((run.home / "opencode.json").read_text(encoding="utf-8"))
    provider = config["provider"]["ollama"]
    assert config["model"] == "ollama/gpt-oss:120b"
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["apiKey"] == "{env:OLLAMA_API_KEY}"  # the key's name, not its value
    assert provider["models"]["gpt-oss:120b"]["options"]["reasoningEffort"] == "high"
    assert config["tools"] == {"webfetch": False, "websearch": False, "exactdocs_fetch_url": False}
    assert config["permission"]["webfetch"] == "deny"
    assert config["mcp"]["exactdocs"]["type"] == "remote"
    assert config["agent"]["build"]["steps"] == 12
    assert {"run", "--format", "json", "--thinking", "--auto"} <= set(invocation.argv)
    assert invocation.env["OPENCODE_CONFIG"] == str(run.home / "opencode.json")


@pytest.mark.parametrize("name", sorted(HARNESSES))
def test_the_none_arm_gets_no_mcp_server(name: str, tmp_path: Path) -> None:
    harness = HARNESSES[name]
    model = next(
        f"{p}:some-model" for p in ("anthropic", "google", "ollama") if p in harness.providers
    )
    run = _run(model, server=None, tmp=tmp_path)
    run.home.mkdir(parents=True)
    invocation = harness.configure(run, Path("/cli/x"))

    written = "".join(p.read_text(encoding="utf-8") for p in run.home.rglob("*") if p.is_file())
    assert "services.harness.internal" not in written
    assert "services.harness.internal" not in " ".join(invocation.argv)


def test_models_name_their_provider() -> None:
    model = HarnessModel.parse("ollama:gpt-oss:120b", env={})
    gateway = HarnessModel.parse("openai:gpt-5", env={"OPENAI_BASE_URL": "http://127.0.0.1:9/v1"})

    assert (model.model, model.base_url, model.address) == (
        "gpt-oss:120b",
        "https://ollama.com/v1",
        ("ollama.com", 443),
    )
    assert gateway.address == ("127.0.0.1", 9)
    for wrong in ("gpt-oss", "mistral:large"):
        with pytest.raises(ValueError, match="provider"):
            HarnessModel.parse(wrong, env={})
    with pytest.raises(ValueError, match="thinking"):
        HarnessModel.parse("openai:gpt-5", thinking="lots", env={})


# ------------------------------------------------------------------------------------ the gate


async def _echo() -> tuple[asyncio.Server, int]:
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _ask(host: str, port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(request)
    await writer.drain()
    answer = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    if b" 200 " in answer:
        writer.write(b"ping")
        await writer.drain()
        answer += await asyncio.wait_for(reader.read(4), 5)
    writer.close()
    return answer


async def test_the_gate_tunnels_only_to_allowed_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    server, port = await _echo()
    async with server, opened("127.0.0.1", allowed=[("127.0.0.1", port)], forwards={}) as gate:
        proxy = int(gate.proxy.rpartition(":")[2])
        allowed = await _ask(
            "127.0.0.1", proxy, f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n".encode()
        )
        refused = await _ask("127.0.0.1", proxy, b"CONNECT telemetry.example:443 HTTP/1.1\r\n\r\n")
        plain = await _ask("127.0.0.1", proxy, b"GET http://example.com/ HTTP/1.1\r\n\r\n")

    assert allowed.startswith(b"HTTP/1.1 200")
    assert allowed.endswith(b"ping")
    assert refused.startswith(b"HTTP/1.1 403")
    assert plain.startswith(b"HTTP/1.1 403")
    assert gate.log.allowed == {f"127.0.0.1:{port}": 1}
    assert gate.log.denied["telemetry.example:443"] == 1
    assert len(gate.log.denied) == 2


async def test_the_gate_forwards_a_service() -> None:
    server, port = await _echo()
    async with (
        server,
        opened("127.0.0.1", allowed=[], forwards={"mcp": ("127.0.0.1", port)}) as gate,
    ):
        host, forward = gate.forwards["mcp"]
        reader, writer = await asyncio.open_connection(host, forward)
        writer.write(b"hello")
        await writer.drain()
        echoed = await asyncio.wait_for(reader.read(5), 5)
        writer.close()

    assert echoed == b"hello"
    assert gate.log.forwarded == {"mcp": 1}
    assert gate.url("mcp", "/mcp") == f"http://127.0.0.1:{forward}/mcp"


def test_no_proxy_names_hosts_suffixes_and_networks() -> None:
    rules = "localhost, .internal.test,example.org,10.0.0.0/8"

    assert bypassed("a.internal.test", rules)
    assert bypassed("example.org", rules)
    assert bypassed("api.example.org", rules)
    assert bypassed("10.1.2.3", rules)
    assert not bypassed("ollama.com", rules)
    assert not bypassed("11.0.0.1", rules)
    assert bypassed("anything", "*")


def test_the_gate_tunnels_through_this_process_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("https_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@proxy.test:3128")
    monkeypatch.setenv("NO_PROXY", "services.harness.internal")

    found = upstream_for("ollama.com")
    assert found is not None
    assert found[:2] == ("proxy.test", 3128)
    assert found[2] is not None
    assert found[2].startswith("Basic ")
    assert upstream_for("services.harness.internal") is None


# ------------------------------------------------------------------------------- whole runs


def _plan(jobs: list, tasks: dict, *, harness: StandInHarness | None = None) -> Plan:
    setups = setups_of(
        [ARMS[NONE], ARMS[EXACTDOCS]], {EXACTDOCS: [RetrievalConfig.parse("bm25:mode=bm25")]}
    )
    return Plan(
        jobs=jobs,
        harnesses=[
            Installed(
                harness=harness or StandInHarness(solutions=solutions(tasks)),
                executable=STAND_IN_CLI,
            )
        ],
        models=[HarnessModel.parse(MODEL, env={})],
        setups=setups,
        selection="stand-ins",
    )


def _task_jobs() -> tuple[list[TaskJob], dict]:
    tasks, corpus = stand_in_tasks()
    environments = prepared(tasks)
    dataset = task_dataset([tasks[V1], tasks[V2]], corpus)
    jobs = [
        TaskJob(
            case=case,
            task=tasks[case.name or ""],
            prepared=environments[tasks[case.name or ""].environment.name],
            sandbox=ProcessSandbox(),
            limits=FAST,
            cutoff=tasks[V1].released,
        )
        for case in dataset.cases
    ]
    return jobs, tasks


async def test_a_harness_runs_the_coding_tasks_with_and_without_the_docs_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stand-in")
    jobs, tasks = _task_jobs()
    report = await run_bench(
        _plan(jobs, tasks),
        endpoints=StandInEndpoints(),
        runner=ProcessRunner(),
        work_dir=tmp_path,
        limits=RunLimits(wall_seconds=60),
        concurrency=2,
        checkpoint=tmp_path / "rows.jsonl",
    )

    cells = {c.arm: c for c in report.cells}
    assert len(report.results) == 4
    assert cells[NONE].passed.rate == pytest.approx(0.0)  # it wrote the other version's code
    assert cells[EXACTDOCS].passed.rate == pytest.approx(1.0)
    called = cells[EXACTDOCS].called_docs
    assert called is not None
    assert called.rate == pytest.approx(1.0)
    assert cells[NONE].called_docs is None
    versus = cells[EXACTDOCS].versus_none
    assert versus is not None
    assert versus.accuracy is not None
    assert (versus.cases, versus.accuracy.gained, versus.accuracy.lost) == (2, 2, 0)
    assert versus.seconds is not None
    assert versus.output_tokens is not None
    row = next(r for r in report.results if r.arm == EXACTDOCS)
    assert row.docs_calls == 1
    assert row.calls[0].name == "mcp__exactdocs__search_docs"
    assert (row.input_tokens, row.output_tokens, row.usd) == (500, 60, 0.0123)
    assert row.thinking_source == "not reported"
    assert row.task is not None
    assert row.task.installed in {"1.0", "2.0"}
    assert (tmp_path / row.run_dir / "transcript.jsonl").exists()
    assert not (tmp_path / row.run_dir / "home").exists()  # its configuration held the token
    failing = next(r for r in report.results if r.arm == NONE)
    assert failing.task is not None
    assert failing.task.forbidden
    assert report.meta.servers[EXACTDOCS]["server"] == "stand-in docs"
    assert len(load_rows(tmp_path / "rows.jsonl")) == 4
    text = markdown(report)
    assert "against the harness's own `none` arm" in text
    assert "### Network" in text


async def test_a_resumed_run_runs_nothing_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stand-in")
    jobs, tasks = _task_jobs()
    first = await run_bench(
        _plan(jobs[:1], tasks),
        endpoints=StandInEndpoints(),
        runner=ProcessRunner(),
        work_dir=tmp_path,
        checkpoint=tmp_path / "rows.jsonl",
    )
    again = await run_bench(
        _plan(jobs[:1], tasks),
        endpoints=StandInEndpoints(),
        runner=ProcessRunner(),
        work_dir=tmp_path,
        done=load_rows(tmp_path / "rows.jsonl"),
    )

    assert again.meta.resumed == len(first.results) == 2
    assert [r.run_dir for r in again.results] == [r.run_dir for r in first.results]
    failed = first.results[0].model_copy(update={"failure": "provider", "counted": False})
    rows = {**load_rows(tmp_path / "rows.jsonl"), key_of(failed): failed}
    only = await run_bench(
        _plan(jobs, tasks),  # the second job never ran: it is left out, nothing runs
        endpoints=StandInEndpoints(),
        runner=ProcessRunner(),
        work_dir=tmp_path,
        done=rows,
        run_missing=False,
        servers=first.meta.servers,
    )
    assert len(only.results) == 2
    assert sum(c.errors for c in only.cells) == 1  # a failed run is reported, not run again
    assert only.meta.servers == first.meta.servers


async def test_golden_questions_run_through_a_harness_and_are_judged_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stand-in")
    corpus, cases = golden()
    judge = AnswerJudge(judge=judge_agent(chat_model(OFFLINE_JUDGE)))
    jobs = [QuestionJob(case=c, judge=judge) for c in bench_dataset(cases, corpus).cases]
    _, tasks = _task_jobs()
    report = await run_bench(
        _plan(jobs, tasks), endpoints=StandInEndpoints(), runner=ProcessRunner(), work_dir=tmp_path
    )

    grades = {(r.arm, r.job): r.outcome for r in report.results}
    install = "demo v1: How do I install the package?"
    assert grades[EXACTDOCS, install] == "correct"  # answered from the documentation it searched
    assert grades[NONE, install] == "refused"  # it does not know
    assert all(r.kind == "question" and r.question is not None for r in report.results)
    assert not any(set(r.run_dir) & set(" :?") for r in report.results)  # Docker mounts it
    assert {c.kind for c in report.cells} == {"question"}
    assert "### Golden questions" in markdown(report)


async def test_a_comparison_with_no_harness_pairs_the_same_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stand-in")
    jobs, tasks = _task_jobs()
    report = await run_bench(
        _plan(jobs, tasks), endpoints=StandInEndpoints(), runner=ProcessRunner(), work_dir=tmp_path
    )
    rows = [r.model_copy(update={"seconds": 10.0}) for r in report.results]
    baseline = {(MODEL, r.arm, r.retrieval, "task", r.job): (False, 2.0, 100.0, 10.0) for r in rows}

    cells = {c.arm: c for c in cells_of(rows, baseline=baseline)}
    loop = cells[EXACTDOCS].versus_no_harness
    assert loop is not None
    assert loop.against == "no harness"
    assert loop.accuracy is not None
    assert loop.accuracy.gained == 2
    assert loop.seconds_ratio == pytest.approx(5.0)


# --------------------------------------------------------------------- how a run ended


def _cli(*, exit_code: int | None = 0, stderr: str = "", timed_out: bool = False) -> CliRun:
    return CliRun(exit_code=exit_code, output="", stderr=stderr, seconds=1.0, timed_out=timed_out)


def test_a_run_is_the_providers_the_clis_or_the_agents() -> None:
    limited = Transcript(lines=2, error="429", provider_failure=True)
    nothing = Transcript(lines=1, unparsed=1)
    turns = Transcript(lines=3, error="error_max_turns: 40")

    assert classify(limited, _cli())[:2] == ("provider", "provider")
    assert classify(Transcript(lines=3), _cli(timed_out=True, exit_code=None))[:2] == (
        "no_answer",
        "no_answer",
    )
    assert classify(nothing, _cli(exit_code=1, stderr="config error"))[:2] == (
        "harness",
        "provider",
    )
    assert classify(turns, _cli(exit_code=1))[:2] == ("no_answer", "no_answer")
    assert classify(Transcript(lines=3, answer="done"), _cli()) == (None, None, None)


@pytest.mark.parametrize(
    ("said", "providers"),
    [
        ("API Error: 429 rate_limit_error", True),
        ("We\u2019re currently experiencing high demand, which may cause temporary errors.", True),
        ("stream disconnected before completion: Internal Server Error", True),
        ("you have reached your session usage limit", True),
        ("error_max_turns: Reached maximum number of turns (40)", False),
        ("the transcript has no result", False),
    ],
)
def test_whose_failure_an_error_names(said: str, providers: bool) -> None:
    assert provider_failed(said) is providers


def test_a_transcript_becomes_the_agent_benchmarks_record() -> None:
    t = _transcript("claude-code", "claude-code-exactdocs", "anthropic:claude-sonnet-4-5")
    run = agent_run(t, seconds=42.0, failure=None, error=None)

    assert run.answer == t.answer
    assert [c.name for c in run.tool_calls] == [c.name for c in t.calls]
    assert (run.input_tokens, run.output_tokens, run.usd, run.seconds) == (
        93_286,
        487,
        0.08437,
        42.0,
    )


# ------------------------------------------------------------------------------------- the CLI


def test_list_names_every_harness_and_its_pinned_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    for harness in HARNESSES.values():
        assert f"{harness.release.package}@{harness.release.version}" in out


def test_parse_prints_a_recorded_transcript(capsys: pytest.CaptureFixture[str]) -> None:
    path = TRANSCRIPTS / "opencode-exactdocs.jsonl"
    assert main(["parse", "--harness", "opencode", "--mcp-server", "exactdocs", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["turns"] == 16


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--model", "ollama:gpt-oss:120b"], "give --harness"),
        (["--harness", "opencode"], "give --model"),
        (["--harness", "claude-code", "--model", "ollama:gpt-oss:120b"], "supports"),
        (["--harness", "opencode", "--model", "ollama:x", "--jobs", "questions"], "--judge-model"),
        (["--harness", "opencode", "--model", "ollama:x", "--jobs", "everything"], "--jobs takes"),
        (["--harness", "opencode", "--model", "ollama:x"], "OLLAMA_API_KEY"),
    ],
)
def test_run_refuses_what_it_cannot_run(
    argv: list[str],
    says: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert main(["run", *argv]) == 2
    assert says in capsys.readouterr().err


def test_run_refuses_context7_without_its_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "x")
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    argv = ["run", "--harness", "opencode", "--model", "ollama:x", "--arm", "context7"]
    assert main(argv) == 2
    assert "Context7 API key" in capsys.readouterr().err


# ------------------------------------------------------------------- a container (opt-in)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker")
async def test_a_run_in_its_container_reaches_only_what_the_gate_lets_through(
    tmp_path: Path,
) -> None:
    server, port = await _echo()
    workspace, home = tmp_path / "workspace", tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    script = (
        "set -u; host=${HTTPS_PROXY#http://}; "
        'exec 3<>"/dev/tcp/${host%:*}/${host##*:}"; '
        'printf "CONNECT telemetry.example:443 HTTP/1.1\\r\\n\\r\\n" >&3; '
        "head -c 12 <&3; echo; "
        'exec 4<>"/dev/tcp/services.harness.internal/$MCP_PORT"; printf ping >&4; '
        "head -c 4 <&4; echo; "
        "touch /forbidden 2>/dev/null && echo root-writable || echo root-read-only; "
        "touch ./made && echo workspace-writable"
    )
    async with (
        server,
        DockerRunner().network(allowed=[], forwards={"mcp": ("127.0.0.1", port)}) as network,
    ):
        mcp_port = network.url("mcp").rpartition(":")[2]
        invocation = Invocation(argv=("/bin/bash", "-c", script), env={"MCP_PORT": mcp_port})
        done = await network.run(
            invocation, Placement(workspace=workspace, home=home), RunLimits(wall_seconds=60)
        )

    lines = done.output.splitlines()
    assert lines[0] == "HTTP/1.1 403", done.stderr
    assert lines[1] == "ping"
    assert lines[2:] == ["root-read-only", "workspace-writable"]
    assert done.denied == {"telemetry.example:443": 1}
    assert done.forwarded == {"mcp": 1}
    assert (workspace / "made").exists()
