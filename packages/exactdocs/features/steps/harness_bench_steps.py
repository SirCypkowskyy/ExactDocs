"""Steps for the harness benchmark (packages/exactdocs/evals/harness_bench, #497).

The scenarios run the Claude Code adapter with its CLI replaced by the stand-in of
``harness_stand_ins`` (Claude Code's configuration, command line and transcript format, no model)
on the stand-in coding tasks, behind the gate on loopback (``ProcessRunner``), with the agent
benchmark's stand-in documentation server over HTTP: no container, no download and no provider.
The real CLIs run in containers only from ``just harness-bench run`` or the manual workflow.
"""

import asyncio
import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path

import pytest
from behave import given, then, when
from behave.runner import Context

from agent_bench.arms import ARMS, CONTEXT7, EXACTDOCS, GROUNDED_DOCS, NONE
from agent_bench.cli import setups_of
from agent_bench.harness import RetrievalConfig
from coding_task_stand_ins import V1, V2, prepared, stand_in_tasks
from coding_tasks.evaluators import task_dataset
from coding_tasks.sandbox import Limits, ProcessSandbox
from harness_bench.container import ProcessRunner, RunLimits
from harness_bench.harness import HarnessModel, HarnessRun, McpServer
from harness_bench.jobs import TaskJob
from harness_bench.releases import HARNESSES
from harness_bench.report import HarnessReport, HarnessResult, cells_of
from harness_bench.run import Installed, Plan, run_bench
from harness_bench.transcript import HarnessCall
from harness_stand_ins import MODEL, STAND_IN_CLI, StandInEndpoints, StandInHarness, solutions

LIMITS = Limits(wall_seconds=60, cpu_seconds=60, memory_mb=1024)
"""The hidden tests' limits here."""
STAND_IN_INPUT = 500
"""The input tokens the stand-in CLI reports (its cache reads included)."""
STAND_IN_OUTPUT = 60
"""The output tokens it reports."""
WEB: dict[str, tuple[str, ...]] = {
    "claude-code": ("WebSearch", "WebFetch"),
    "codex": ("web_search",),
    "gemini-cli": ("google_web_search", "web_fetch"),
    "opencode": ("webfetch", "websearch"),
}
"""Each harness's built-in web tools."""


def _work_dir(context: Context) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="exactdocs-harness-bench-"))
    context.add_cleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


@given(
    "a coding CLI that runs headless, coding tasks pinning a stand-in library at 1.0 and 2.0, "
    "and its model"
)
def step_stand_ins(context: Context) -> None:
    tasks, corpus = stand_in_tasks()
    environments = prepared(tasks)
    dataset = task_dataset([tasks[V1], tasks[V2]], corpus)
    context.jobs = [
        TaskJob(
            case=case,
            task=tasks[case.name or ""],
            prepared=environments[tasks[case.name or ""].environment.name],
            sandbox=ProcessSandbox(),
            limits=LIMITS,
            cutoff=tasks[V1].released,
        )
        for case in dataset.cases
    ]
    context.harness = StandInHarness(solutions=solutions(tasks))
    context.work_dir = _work_dir(context)
    previous = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "stand-in"  # the provider's key, passed to the CLI by name
    context.add_cleanup(
        lambda: (
            os.environ.pop("ANTHROPIC_API_KEY", None)
            if previous is None
            else os.environ.update(ANTHROPIC_API_KEY=previous)
        )
    )


def _run(context: Context, arms: list[str]) -> None:
    setups = setups_of(
        [ARMS[a] for a in arms], {EXACTDOCS: [RetrievalConfig.parse("bm25:mode=bm25")]}
    )
    plan = Plan(
        jobs=context.jobs,
        harnesses=[Installed(harness=context.harness, executable=STAND_IN_CLI)],
        models=[HarnessModel.parse(MODEL, env={})],
        setups=setups,
    )
    context.report = asyncio.run(
        run_bench(
            plan,
            endpoints=StandInEndpoints(),
            runner=ProcessRunner(),
            work_dir=context.work_dir,
            limits=RunLimits(wall_seconds=60),
            concurrency=2,
        )
    )


@when('the CLI runs each task headless behind its gate with the "{arm}" arm\'s MCP configuration')
def step_one_arm(context: Context, arm: str) -> None:
    _run(context, [arm])


@when('the CLI runs each task in the "{first}" arm and in the "{second}" arm')
def step_two_arms(context: Context, first: str, second: str) -> None:
    _run(context, [first, second])


@then(
    "its transcript is parsed into tool calls, MCP calls, wall time, input tokens, output tokens "
    "including thinking, and thinking tokens where the CLI reports them"
)
def step_parsed(context: Context) -> None:
    for row in context.report.results:
        assert row.calls, row
        assert row.docs_calls == 1
        assert row.calls[0].server == EXACTDOCS
        assert row.seconds > 0
        assert row.input_tokens == STAND_IN_INPUT
        assert row.output_tokens == STAND_IN_OUTPUT
        assert row.thinking_tokens is None
        assert row.thinking_source == "not reported"  # Claude Code counts it in the output only


@then("the workspace is evaluated with the coding-task evaluators")
def step_evaluated(context: Context) -> None:
    for row in context.report.results:
        assert row.task is not None
        assert row.task.installed in {"1.0", "2.0"}
        assert row.task.tests > 0
        assert row.outcome == "passed"


@then("the gate let the run reach only the arm's MCP server")
def step_gate(context: Context) -> None:
    for row in context.report.results:
        assert row.tunnels == {}
        assert row.denied == {}


@then(
    "the report compares pass rate, wall time and output tokens of the two arms on the same tasks, "
    "with a paired test"
)
def step_paired(context: Context) -> None:
    cells = {c.arm: c for c in context.report.cells}
    versus = cells[EXACTDOCS].versus_none
    assert versus is not None
    assert versus.against == NONE
    assert versus.cases == len(context.jobs)
    assert versus.accuracy is not None
    assert versus.accuracy.test == "mcnemar-mid-p"
    assert versus.seconds is not None
    assert versus.seconds.test == "permutation"
    assert versus.output_tokens is not None


@then(
    "it gives the share of runs that called the docs server and the docs calls per task, with "
    "intervals"
)
def step_docs_share(context: Context) -> None:
    cells = {c.arm: c for c in context.report.cells}
    called = cells[EXACTDOCS].called_docs
    assert called is not None
    assert called.rate == pytest.approx(1.0)
    assert called.interval is not None
    assert cells[EXACTDOCS].docs_calls is not None
    assert cells[NONE].called_docs is None
    assert cells[NONE].passed.rate == pytest.approx(0.0)
    assert cells[EXACTDOCS].passed.rate == pytest.approx(1.0)


@when('each harness is configured for the "{a}", "{b}", "{c}" and "{d}" arms')
def step_configure(context: Context, a: str, b: str, c: str, d: str) -> None:
    context.configured = {}
    root = _work_dir(context)
    for name, harness in HARNESSES.items():
        provider = min(harness.providers)
        for arm in (a, b, c, d):
            home = root / name / arm
            home.mkdir(parents=True)
            mcp = None
            if arm != NONE:
                mcp = McpServer(
                    name=arm.replace("-", "_"),
                    url="http://services.harness.internal:9/mcp",
                    excluded=("fetch_url",) if arm == GROUNDED_DOCS else (),
                    headers={"CONTEXT7_API_KEY": "k"} if arm == CONTEXT7 else {},
                )
            run = HarnessRun(
                workspace=root / "workspace",
                home=home,
                prompt="Add a field.",
                model=HarnessModel.parse(f"{provider}:some-model", env={}),
                mcp=mcp,
            )
            invocation = harness.configure(run, Path("/cli") / name)
            files = {p.name: p.read_text(encoding="utf-8") for p in home.rglob("*") if p.is_file()}
            context.configured[name, arm] = (invocation, files)


@then("its built-in web search and fetch are off, so the arms differ only by the MCP server")
def step_web_off(context: Context) -> None:
    for (name, arm), (invocation, files) in context.configured.items():
        argv = list(invocation.argv)
        if name == "claude-code":
            assert set(WEB[name]) <= set(argv[argv.index("--disallowedTools") + 1 :]), arm
        elif name == "codex":
            assert tomllib.loads(files["config.toml"])["web_search"] == "disabled"
        elif name == "gemini-cli":
            assert json.loads(files["settings.json"])["tools"]["exclude"] == list(WEB[name])
        else:
            tools = json.loads(files["opencode.json"])["tools"]
            assert all(tools[t] is False for t in WEB[name])
        mentioned = " ".join(argv) + " ".join(files.values())
        assert ("services.harness.internal" in mentioned) == (arm != NONE), (name, arm)


@then("a web call or a host the gate refused would be counted in the report")
def step_counted(context: Context) -> None:
    leaked = HarnessResult(
        harness="opencode",
        cli_version="test",
        agent_model=MODEL,
        arm=NONE,
        kind="task",
        job=V1,
        project="demo",
        outcome="failed",
        passed=False,
        counted=True,
        seconds=1.0,
        calls=[HarnessCall(name="webfetch", tool="webfetch", web=True)],
        web_calls=1,
        denied={"docs.example.com:443": 1},
    )
    context.leak_report = HarnessReport.model_construct(
        meta=None, cells=cells_of([leaked]), results=[leaked]
    )
    [cell] = context.leak_report.cells
    assert cell.web_calls == 1
    assert cell.denied == {"docs.example.com:443": 1}
    assert all(h.web_tools.startswith("off") for h in HARNESSES.values())
