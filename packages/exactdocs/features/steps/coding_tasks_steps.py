"""Steps for the version-pinned coding tasks (packages/exactdocs/evals/coding_tasks, #496).

The default scenarios run on the stand-in tasks of ``coding_task_stand_ins`` (a library ``demo``
whose 2.0 renames 1.0's validator decorator, as Pydantic 2 did) in the process sandbox, with the
scripted agents of ``coding_tasks.offline`` and the stand-in documentation tools of the agent
benchmark: no download and no provider. The ``@integration`` scenario installs Pydantic 1.10.22
and 2.5.3 from PyPI and runs the real task.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

from agent_bench.arms import parse_arms
from agent_bench.harness import RetrievalConfig
from agent_bench_stand_ins import stand_in_tools
from coding_task_stand_ins import V1, V2, prepared, stand_in_tasks
from coding_tasks.check import check_tasks, prepare_all
from coding_tasks.evaluators import task_dataset
from coding_tasks.offline import IDLE, OFFLINE_AGENTS, OTHER, REFERENCE, offline_model
from coding_tasks.run import run_tasks
from coding_tasks.sandbox import Limits, ProcessSandbox
from coding_tasks.tasks import load_tasks
from coding_tasks.workspace import WORKSPACE_TOOLS
from retrieval_eval.golden import load_corpus

LIMITS = Limits(wall_seconds=60, cpu_seconds=60, memory_mb=1024)
"""The limits every test run here has."""


def _work_dir(context: Context) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="exactdocs-coding-tasks-"))
    context.add_cleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


@given("coding tasks over a stand-in library, one pinning version 1.0 and one version 2.0")
def step_stand_ins(context: Context) -> None:
    context.tasks, context.corpus = stand_in_tasks()
    context.prepared = prepared(context.tasks)
    context.work_dir = _work_dir(context)
    assert {t.environment.spec.version for t in context.tasks.values()} == {"1.0", "2.0"}


@given("a task workspace that pins demo {version} and asks for a model with a custom validator")
def step_task(context: Context, version: str) -> None:
    context.task = context.tasks[V1 if version == "1.0" else V2]
    assert context.task.environment.spec.version == version
    assert "validator" in context.task.spec.prompt


def _agents(context: Context, models: list[str], arms: str = "none") -> None:
    context.report = asyncio.run(
        run_tasks(
            list(context.tasks.values()),
            context.corpus,
            context.prepared,
            ProcessSandbox(),
            agent_models=models,
            arms=parse_arms([arms]),
            retrieval=[RetrievalConfig.parse("bm25:mode=bm25")],
            work_dir=context.work_dir,
            tools=stand_in_tools,
            models=offline_model,
            limits=LIMITS,
            concurrency=4,
        )
    )


@when("an agent completes the task")
def step_complete(context: Context) -> None:
    _agents(context, [REFERENCE, IDLE])
    context.rows = {r.agent_model: r for r in context.report.results if r.task == context.task.id}


@then("the hidden tests run in a sandbox with exactly that version installed")
def step_installed(context: Context) -> None:
    for row in context.rows.values():
        assert row.installed == context.task.environment.spec.version, row
        assert row.tests > 0
    isolation = context.report.meta.isolation
    assert isolation.sandbox == "process"
    assert isolation.cpu.startswith("RLIMIT_CPU")
    assert isolation.memory.startswith("RLIMIT_DATA")
    assert "killed" in isolation.time


@then("the task passes only when they pass")
def step_passes(context: Context) -> None:
    done, undone = context.rows[REFERENCE], context.rows[IDLE]
    assert done.outcome == "passed"
    assert done.failures == []
    assert undone.outcome == "failed"
    assert undone.failures


@given("a reference solution written for the other major version")
def step_other(context: Context) -> None:
    partner = context.tasks[context.task.spec.other_from]
    assert context.task.other_directory == partner.reference
    assert partner.environment.spec.version != context.task.environment.spec.version


@when("it is evaluated on the task")
def step_evaluate(context: Context) -> None:
    _agents(context, [OTHER])
    [context.row] = [r for r in context.report.results if r.task == context.task.id]
    dataset = task_dataset([context.task], context.corpus)
    assert [type(e).__name__ for e in dataset.evaluators] == [
        "TestsPass",
        "ForbiddenApi",
        "FilesChanged",
    ]


@then("the task fails, and the report names the API that does not exist in the pinned version")
def step_named(context: Context) -> None:
    row = context.row
    assert row.outcome == "failed"
    assert row.forbidden == ["@validator"]
    assert any("deprecated in demo 2.0" in r for r in row.forbidden_reasons)
    [cell] = context.report.cells
    assert cell.forbidden_apis == {"@validator": 1, "field_validator": 1}


@when("the tasks are checked without a model")
def step_check(context: Context) -> None:
    context.check = asyncio.run(
        check_tasks(
            list(context.tasks.values()),
            context.corpus,
            context.prepared,
            ProcessSandbox(),
            work_dir=context.work_dir,
            limits=LIMITS,
        )
    )


@then(
    "each reference passes on its pinned version and each other-version solution fails naming a "
    "forbidden API"
)
def step_checked(context: Context) -> None:
    assert context.check.ok
    for task in context.check.tasks:
        pinned = context.tasks[task.task].environment.spec.version
        assert task.reference.passed
        assert task.reference.installed == pinned
        assert not task.other.passed
        assert task.other.forbidden


@when('scripted agents complete the tasks with the arms "{first}" and "{second}"')
def step_arms(context: Context, first: str, second: str) -> None:
    _agents(context, list(OFFLINE_AGENTS), f"{first},{second}")


@then(
    'every agent works through the workspace tools, and only the "{arm}" arm also has '
    "documentation tools"
)
def step_tools(context: Context, arm: str) -> None:
    for row in context.report.results:
        names = {c.name for c in row.tool_calls}
        assert {"list_files", "run_tests"} <= names, row
        docs = names - set(WORKSPACE_TOOLS)
        assert bool(docs) == (row.arm == arm), row
    instructions = context.report.meta.instructions
    assert instructions["none"].split("\n\n")[1] == instructions[arm].split("\n\n")[1]


@then(
    "the report gives the pass rate, the forbidden-API rate and the files changed per task, "
    "project and arm, with intervals"
)
def step_report(context: Context) -> None:
    cells = {(c.agent_model, c.arm): c for c in context.report.cells}
    assert len(cells) == len(OFFLINE_AGENTS) * 2
    for cell in cells.values():
        assert cell.passed.interval is not None
        assert cell.forbidden.interval is not None
        assert cell.files_changed is not None
        assert cell.files_changed.interval is not None
        assert cell.by_project["demo"].interval is not None
    assert cells[REFERENCE, "none"].passed.rate == 1
    assert cells[OTHER, "exactdocs"].forbidden.rate == 1
    tasks = {(r.agent_model, r.arm, r.task) for r in context.report.results}
    assert len(tasks) == len(OFFLINE_AGENTS) * 2 * 2  # every task in every cell


@then('the "{arm}" arm is compared with "{baseline}" on the same tasks by a paired test')
def step_paired(context: Context, arm: str, baseline: str) -> None:
    for cell in context.report.cells:
        if cell.arm == baseline:
            assert cell.versus_none is None
            continue
        assert cell.arm == arm
        assert cell.versus_none is not None
        assert cell.versus_none.test == "mcnemar-mid-p"
        assert cell.versus_none.cases == len(context.tasks)


@given("the task workspace that pins pydantic 1.10.22 and asks for a model with a custom validator")
def step_real_task(context: Context) -> None:
    tasks, problems = load_tasks(corpus=load_corpus())
    assert not problems
    by_id = {t.id: t for t in tasks}
    context.real = [by_id["pydantic-validator-v1"], by_id["pydantic-validator-v2"]]
    assert context.real[0].environment.spec.version == "1.10.22"


@when("its reference solution and the solution written for Pydantic 2 are evaluated")
def step_real_check(context: Context) -> None:
    work_dir = _work_dir(context)
    environments = asyncio.run(prepare_all(context.real, work_dir / "environments"))
    context.check = asyncio.run(
        check_tasks(
            context.real,
            load_corpus(),
            environments,
            ProcessSandbox(),
            work_dir=work_dir,
            limits=LIMITS,
        )
    )


@then(
    "the hidden tests ran with pydantic 1.10.22 installed, the reference passes, and the "
    'Pydantic 2 solution fails naming "{api}"'
)
def step_real_checked(context: Context, api: str) -> None:
    [v1, _] = context.check.tasks
    assert v1.reference.installed == "1.10.22"
    assert v1.reference.passed
    assert not v1.other.passed
    assert v1.other.forbidden == [api]
