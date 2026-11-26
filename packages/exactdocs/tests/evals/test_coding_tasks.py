"""Version-pinned coding tasks (#496): the task set, grading, the sandbox, the agent and the report.

Everything here runs in the default suite: the real tasks are checked statically (they load, the
lockfiles pin their versions, every reference is clean and every other-version solution names a
forbidden API), and the sandbox, grading, workspace tools, agent runs and report run on the
stand-in tasks of ``coding_task_stand_ins`` with scripted models. Running the real tasks' hidden
tests needs their environments (a download): CI's *Coding tasks* job does it with
``just coding-tasks check``; here only the tests marked ``integration`` do.
"""

import shutil
import sys
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel

from agent_bench.arms import parse_arms
from agent_bench.harness import RetrievalConfig
from agent_bench_stand_ins import stand_in_tools
from coding_task_stand_ins import V1, V2, prepared, stand_in_tasks
from coding_tasks.agent import instructions
from coding_tasks.check import check_tasks, prepare_all
from coding_tasks.check import markdown as check_markdown
from coding_tasks.cli import inventory, main, per_project
from coding_tasks.environments import ENVIRONMENTS_DIR, load_environments, lock_problems
from coding_tasks.evaluators import task_dataset
from coding_tasks.grading import (
    Runner,
    changes_of,
    code_without_comments,
    forbidden_hits,
    materialize,
)
from coding_tasks.offline import IDLE, OFFLINE_AGENTS, OTHER, REFERENCE, offline_model
from coding_tasks.report import markdown
from coding_tasks.run import load_rows, run_tasks
from coding_tasks.sandbox import (
    DockerSandbox,
    Limits,
    ProcessSandbox,
    network_namespace,
    sandbox_environment,
)
from coding_tasks.tasks import DEFAULT_CUTOFF, load_tasks
from coding_tasks.workspace import Workspace, _list, _read, _test, _write
from retrieval_eval.golden import load_corpus

FAST = Limits(wall_seconds=60, cpu_seconds=60, memory_mb=1024)


# ------------------------------------------------------------------------------ the task set


@pytest.fixture(scope="module")
def real_tasks():
    tasks, problems = load_tasks(corpus=load_corpus())
    assert problems == []
    return tasks


def test_the_task_set_covers_four_projects_mostly_in_version_pairs(real_tasks) -> None:
    projects = {t.spec.project for t in real_tasks}
    paired = [t for t in real_tasks if t.spec.pair]

    assert len(real_tasks) >= 40
    assert projects == {"pydantic", "starlette", "zod", "tanstack-query"}
    assert len(paired) > len(real_tasks) / 2
    assert sum(t.post_cutoff(DEFAULT_CUTOFF) for t in real_tasks) >= 10
    assert sum(t.post_cutoff() and t.api_post_cutoff() for t in real_tasks) >= 10
    for project in projects:
        assert sum(t.spec.project == project for t in real_tasks) >= 8, project


def test_every_pair_is_two_tasks_whose_references_are_each_other_s_other_solution(real_tasks):
    by_id = {t.id: t for t in real_tasks}
    pairs: dict[str, list[str]] = {}
    for task in real_tasks:
        if task.spec.pair:
            pairs.setdefault(task.spec.pair, []).append(task.id)

    for name, members in pairs.items():
        assert len(members) == 2, name
        first, second = (by_id[m] for m in members)
        assert first.spec.other_from == second.id
        assert second.spec.other_from == first.id
        assert first.other_directory == second.reference
        assert first.spec.environment != second.spec.environment
        assert first.spec.prompt == second.spec.prompt, name


def test_every_environment_pins_its_version_with_a_lockfile() -> None:
    environments, problems = load_environments(ENVIRONMENTS_DIR)

    assert problems == []
    assert {e.spec.package for e in environments.values()} == {
        "pydantic",
        "starlette",
        "zod",
        "@tanstack/query-core",
    }
    for environment in environments.values():
        assert lock_problems(environment) == []
        assert environment.lockfiles
        assert environment.spec.forbidden, environment.name


def test_every_pinned_version_is_a_golden_corpus_version(real_tasks) -> None:
    corpus = load_corpus()
    for task in real_tasks:
        project = corpus.project(task.spec.project)
        assert project is not None
        assert project.commit(task.spec.version) is not None, task.id


def test_references_are_clean_and_other_version_solutions_name_a_forbidden_api(
    real_tasks, tmp_path: Path
) -> None:
    # The static half of CI's check: no environment needed, so it runs on every pull request
    # with the suite; the hidden tests themselves run in the *Coding tasks* job.
    for task in real_tasks:
        for solution, clean in ((task.reference, True), (task.other_directory, False)):
            label = "reference" if clean else "other"
            workspace = materialize(task, tmp_path / task.id / label, solution=solution)
            changes = changes_of(task, workspace)
            hits = forbidden_hits(workspace, [*changes.added, *changes.modified], task.forbidden)
            assert (hits == []) if clean else hits, (task.id, solution, [h.api for h in hits])


def test_the_inventory_counts_pairs_and_post_cutoff_tasks(real_tasks) -> None:
    text = inventory(real_tasks, DEFAULT_CUTOFF)

    assert "| pydantic-validator-v1 | pydantic | v1.10.22 |" in text
    assert f"{len(real_tasks)} tasks over 4 projects" in text
    assert "pin a version released after 2024-06-30" in text


# ------------------------------------------------------------------- forbidden APIs, changes


def test_comments_do_not_count_as_uses_of_an_api() -> None:
    python = "from pydantic import BaseModel  # not field_validator\nx = '# field_validator'\n"
    typescript = "// z.ipv4() is v4 only\n/* z.ipv4() */\nconst url = 'https://x';\n"

    assert "field_validator" not in code_without_comments(Path("a.py"), python).split("\n")[0]
    assert "'# field_validator'" in code_without_comments(Path("a.py"), python)
    stripped = code_without_comments(Path("a.ts"), typescript)
    assert "ipv4" not in stripped
    assert "https://x" in stripped
    assert stripped.count("\n") == typescript.count("\n")


def test_changes_are_measured_against_the_template(tmp_path: Path) -> None:
    tasks, _ = stand_in_tasks()
    task = tasks[V1]
    workspace = materialize(task, tmp_path / "ws", solution=task.reference)
    (workspace / "app" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    (workspace / "tests" / "test_models.py").unlink()

    changes = changes_of(task, workspace)

    assert changes.added == ["app/extra.py"]
    assert changes.modified == ["app/models.py"]
    assert changes.deleted == ["tests/test_models.py"]
    assert changes.count == 3


# -------------------------------------------------------------------------------- the sandbox


async def test_the_sandbox_kills_a_command_at_its_wall_limit(tmp_path: Path) -> None:
    sandbox = ProcessSandbox()
    ran = await sandbox.run(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
        cwd=tmp_path,
        writable=tmp_path,
        readable=[],
        env={"PATH": "/usr/bin:/bin"},
        limits=Limits(wall_seconds=1.5),
    )

    assert ran.timed_out
    assert ran.exit_code is None
    assert "started" in ran.output
    assert ran.seconds < 10


async def test_the_sandbox_limits_cpu_time_and_memory(tmp_path: Path) -> None:
    sandbox = ProcessSandbox()
    spin = await sandbox.run(
        [sys.executable, "-c", "while True: pass"],
        cwd=tmp_path,
        writable=tmp_path,
        readable=[],
        env={"PATH": "/usr/bin:/bin"},
        limits=Limits(wall_seconds=30, cpu_seconds=1),
    )
    hog = await sandbox.run(
        [sys.executable, "-c", "b = bytearray(1024 * 1024 * 1024); print('allocated')"],
        cwd=tmp_path,
        writable=tmp_path,
        readable=[],
        env={"PATH": "/usr/bin:/bin"},
        limits=Limits(wall_seconds=30, memory_mb=256),
    )

    assert not spin.timed_out
    assert spin.exit_code is not None
    assert spin.exit_code != 0  # SIGXCPU, then SIGKILL
    assert spin.seconds < 20
    assert hog.exit_code != 0
    assert "MemoryError" in hog.output
    assert "allocated" not in hog.output.splitlines()


async def test_the_sandbox_cuts_off_the_network_or_says_it_cannot(tmp_path: Path) -> None:
    probe = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('connected')\n"
        "except OSError as error:\n"
        "    print('no network', error.errno)\n"
    )
    sandbox = ProcessSandbox()
    if network_namespace() is None:
        assert sandbox.isolation.network.startswith("not isolated")
        with pytest.raises(RuntimeError, match="no network namespace"):
            await ProcessSandbox(require_network_isolation=True).run(
                [sys.executable, "-c", probe],
                cwd=tmp_path,
                writable=tmp_path,
                readable=[],
                env={},
                limits=FAST,
            )
        return
    ran = await sandbox.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        writable=tmp_path,
        readable=[],
        env={"PATH": "/usr/bin:/bin"},
        limits=FAST,
    )

    assert "no network" in ran.output
    assert sandbox.isolation.network.startswith("none")


def test_the_sandbox_environment_holds_no_key_or_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-secret-value")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
    env = sandbox_environment(home=Path("/w/.home"), path=[Path("/env/bin")])

    assert "OLLAMA_API_KEY" not in env
    assert "HTTPS_PROXY" not in env
    assert env["PATH"].startswith("/env/bin:")
    assert env["HOME"] == "/w/.home"


def test_the_docker_sandbox_says_how_it_isolates() -> None:
    isolation = DockerSandbox().isolation

    assert isolation.network == "none: --network none"
    assert "--memory" in isolation.memory
    assert "--cpus" in isolation.cpu


# ------------------------------------------------------------------------------------ grading


async def test_a_task_passes_only_when_its_hidden_tests_pass_on_the_pinned_version(tmp_path):
    tasks, _ = stand_in_tasks()
    environments = prepared(tasks)
    task = tasks[V1]
    runner = Runner(sandbox=ProcessSandbox(), prepared=environments["demo-v1"], limits=FAST)

    solved = await runner.grade(task, materialize(task, tmp_path / "a", solution=task.reference))
    idle = await runner.grade(task, materialize(task, tmp_path / "b"))

    assert solved.passed
    assert solved.tests.installed == "1.0"
    assert solved.tests.tests == 2
    assert solved.forbidden == []
    assert solved.changes.modified == ["app/models.py"]
    assert not idle.passed
    assert idle.tests.failures == ["hidden_tests.test_sign_up::test_the_username_is_normalized"]
    assert idle.changes.count == 0


async def test_code_for_the_other_version_fails_and_names_the_missing_api(tmp_path: Path) -> None:
    tasks, _ = stand_in_tasks()
    environments = prepared(tasks)
    for task_id, environment, api in (
        (V1, "demo-v1", "field_validator"),
        (V2, "demo-v2", "@validator"),
    ):
        task = tasks[task_id]
        runner = Runner(sandbox=ProcessSandbox(), prepared=environments[environment], limits=FAST)
        workspace = materialize(task, tmp_path / task_id, solution=task.other_directory)

        grade = await runner.grade(task, workspace)

        assert not grade.passed, task_id
        assert grade.apis == [api]
        assert grade.forbidden[0].file == "app/models.py"
        assert "demo 2.0" in grade.forbidden[0].reason


async def test_the_check_reports_every_reference_passing_and_every_other_solution_failing(
    tmp_path: Path,
) -> None:
    tasks, corpus = stand_in_tasks()
    report = await check_tasks(
        list(tasks.values()),
        corpus,
        prepared(tasks),
        ProcessSandbox(),
        work_dir=tmp_path,
        limits=FAST,
        concurrency=2,
    )

    assert report.ok
    assert [t.task for t in report.tasks] == [V1, V2]
    assert all(t.reference.passed and not t.other.passed for t in report.tasks)
    assert report.tasks[0].reference.installed == "1.0"
    assert report.tasks[1].other.forbidden == ["@validator"]
    text = check_markdown(report)
    assert "2 of 2 tasks sound" in text
    assert "| demo-validator-v2 | demo v2 | 2.0 | pass (2) | v1: fails | @validator |" in text


# -------------------------------------------------------------------------- workspace tools


def _workspace(tmp_path: Path) -> Workspace:
    tasks, _ = stand_in_tasks()
    task = tasks[V1]
    environments = prepared(tasks)
    runner = Runner(sandbox=ProcessSandbox(), prepared=environments["demo-v1"], limits=FAST)
    return Workspace(root=materialize(task, tmp_path / "ws"), task=task, runner=runner)


def test_the_workspace_refuses_paths_outside_it_and_hides_the_sandbox_s_files(tmp_path):
    workspace = _workspace(tmp_path)

    assert workspace.resolve("./app/models.py")[0] == "app/models.py"
    for bad in ("../outside.py", "/../../etc/passwd", "", ".home/run.sh", "hidden_tests/x.py"):
        with pytest.raises(ModelRetry):
            workspace.resolve(bad)


async def test_the_workspace_tools_list_read_write_and_run_the_tests(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    assert "app/models.py" in await _list(workspace)
    assert "class SignUp" in await _read(workspace, "app/models.py")
    with pytest.raises(ModelRetry, match="no file"):
        await _read(workspace, "app/nothing.py")
    assert (await _test(workspace)).startswith("passed: 1 tests")
    await _write(workspace, "app/models.py", "raise SystemExit('broken')\n")
    assert (await _test(workspace)).startswith("failed")


async def test_the_lockfile_cannot_be_written(tmp_path: Path) -> None:
    real = next(t for t in load_tasks()[0] if t.environment.spec.ecosystem == "python")
    runner = _workspace(tmp_path / "stand-in").runner
    workspace = Workspace(root=materialize(real, tmp_path / "ws"), task=real, runner=runner)

    with pytest.raises(ModelRetry, match="pins the project's dependencies"):
        await _write(workspace, "requirements.txt", "pydantic==99\n")


# -------------------------------------------------------------------------- the agent and report


def test_the_arms_instructions_differ_only_in_the_documentation_sentence() -> None:
    none, exactdocs = (instructions(a) for a in parse_arms(["none,exactdocs"]))

    assert "no documentation tools" in none
    assert "your only source of documentation is the ExactDocs tools" in exactdocs
    assert none.split(". ", 1)[0] == exactdocs.split(". ", 1)[0]
    assert none.split("\n\n")[1] == exactdocs.split("\n\n")[1]


async def test_scripted_agents_run_the_tasks_with_each_arm(tmp_path: Path) -> None:
    tasks, corpus = stand_in_tasks()
    report = await run_tasks(
        list(tasks.values()),
        corpus,
        prepared(tasks),
        ProcessSandbox(),
        agent_models=OFFLINE_AGENTS,
        arms=parse_arms(["none,exactdocs"]),
        retrieval=[RetrievalConfig.parse("bm25:mode=bm25")],
        work_dir=tmp_path,
        tools=stand_in_tools,
        models=offline_model,
        limits=FAST,
        concurrency=3,
        checkpoint=tmp_path / "rows.jsonl",
    )

    cells = {(c.agent_model, c.arm): c for c in report.cells}
    assert len(report.results) == 2 * 3 * 2
    assert cells[REFERENCE, "none"].passed.rate == pytest.approx(1.0)
    assert cells[OTHER, "exactdocs"].passed.rate == pytest.approx(0.0)
    assert cells[OTHER, "exactdocs"].forbidden.rate == pytest.approx(1.0)
    assert cells[OTHER, "none"].forbidden_apis == {"@validator": 1, "field_validator": 1}
    idle_files = cells[IDLE, "none"].files_changed
    docs_with, docs_without = (cells[REFERENCE, arm].docs_calls for arm in ("exactdocs", "none"))
    versus = cells[REFERENCE, "exactdocs"].versus_none
    assert idle_files is not None
    assert idle_files.mean == 0
    assert docs_with is not None
    assert docs_with.mean == 1  # list_libraries
    assert docs_without is not None
    assert docs_without.mean == 0
    assert versus is not None
    assert versus.cases == 2
    assert cells[REFERENCE, "none"].passed.interval is not None
    assert set(cells[REFERENCE, "none"].by_project) == {"demo"}
    reference = next(r for r in report.results if r.agent_model == REFERENCE and r.arm == "none")
    assert [c.name for c in reference.tool_calls] == ["list_files", "write_file", "run_tests"]
    assert reference.installed in {"1.0", "2.0"}
    assert report.meta.instructions["none"] != report.meta.instructions["exactdocs"]
    assert report.meta.isolation.sandbox == "process"
    text = markdown(report)
    row = "| demo-validator-v1 | pass | pass | fail (field_validator) | fail (field_validator) |"
    assert row in text
    assert "### Against `none`, on the same tasks" in text
    assert len(load_rows(tmp_path / "rows.jsonl")) == 12


async def test_a_provider_failure_is_not_graded_and_a_resumed_run_asks_it_again(tmp_path):
    tasks, corpus = stand_in_tasks()
    failing = {"on": True}

    def models(name: str, task):
        model = offline_model(name, task)
        if task.id != V2 or not failing["on"]:
            return model

        def down(_messages, _info):
            raise ModelHTTPError(status_code=429, model_name=name, body="rate limited")

        return FunctionModel(down)

    async def run(done):
        return await run_tasks(
            list(tasks.values()),
            corpus,
            prepared(tasks),
            ProcessSandbox(),
            agent_models=[REFERENCE],
            arms=parse_arms(["none"]),
            retrieval=[],
            work_dir=tmp_path,
            models=models,
            limits=FAST,
            checkpoint=tmp_path / "rows.jsonl",
            done=done,
        )

    first = await run(None)
    failing["on"] = False
    second = await run(load_rows(tmp_path / "rows.jsonl"))

    outcomes = {r.task: r.outcome for r in first.results}
    assert outcomes == {V1: "passed", V2: "error"}
    assert first.cells[0].errors == 1
    assert first.cells[0].passed.count == 1
    assert {r.task: r.outcome for r in second.results} == {V1: "passed", V2: "passed"}


def test_the_dataset_is_one_pydantic_evals_case_per_task() -> None:
    tasks, corpus = stand_in_tasks()
    dataset = task_dataset(list(tasks.values()), corpus)

    assert [c.name for c in dataset.cases] == [V1, V2]
    assert [type(e).__name__ for e in dataset.evaluators] == [
        "TestsPass",
        "ForbiddenApi",
        "FilesChanged",
    ]
    assert dataset.cases[0].inputs.title == "Demo"
    assert dataset.cases[0].metadata is not None
    assert dataset.cases[0].metadata.pinned == "1.0"


def test_per_project_keeps_the_first_tasks_of_each_project(real_tasks) -> None:
    kept = per_project(real_tasks, 2)

    assert len(kept) == 8
    assert {t.spec.project for t in kept} == {"pydantic", "starlette", "zod", "tanstack-query"}


def test_the_command_line_lists_the_tasks(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "--projects", "zod"]) == 0

    out = capsys.readouterr().out
    assert "| zod-ipv4-v3 | zod | v3.23.8 |" in out
    assert "over 1 projects (zod)" in out


def test_the_command_line_refuses_the_context7_arm_without_its_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    assert main(["run", "--offline", "--arm", "context7"]) == 2
    assert "needs a Context7 API key in CONTEXT7_API_KEY" in capsys.readouterr().err
    assert main(["run", "--offline", "--arm", "web"]) == 2
    assert "unknown arm 'web'" in capsys.readouterr().err


# ------------------------------------------------------------------ real environments (opt-in)


@pytest.mark.integration
async def test_real_tasks_pass_on_their_pinned_versions_and_fail_on_the_other(tmp_path: Path):
    # Downloads Pydantic 1.10.22 and 2.5.3 and Zod 3.23.8 and 4.0.17 from PyPI and npm.
    tasks = [t for t in load_tasks()[0] if t.spec.pair in {"pydantic-validator", "zod-ipv4"}]
    environments = await prepare_all(tasks, tmp_path / "envs")
    report = await check_tasks(
        tasks, load_corpus(), environments, ProcessSandbox(), work_dir=tmp_path, limits=FAST
    )

    assert report.ok, check_markdown(report)
    installed = {t.task: t.reference.installed for t in report.tasks}
    assert installed["pydantic-validator-v1"] == "1.10.22"
    assert installed["zod-ipv4-v4"] == "4.0.17"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker")
async def test_the_docker_sandbox_has_no_network_and_a_memory_limit(tmp_path: Path) -> None:
    tasks, _ = stand_in_tasks()
    environment = prepared(tasks)["demo-v1"]
    probe = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('connected')\n"
        "except OSError:\n"
        "    print('no network')\n"
        "try:\n"
        "    b = bytearray(1024 * 1024 * 1024)\n"
        "    print('allocated')\n"
        "except MemoryError:\n"
        "    print('no memory')\n"
    )
    assert environment.python is not None
    ran = await DockerSandbox().run(
        [str(environment.python.resolve()), "-u", "-c", probe],
        cwd=tmp_path,
        writable=tmp_path,
        readable=environment.mounts,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        limits=Limits(wall_seconds=120, memory_mb=256),
    )

    assert "no network" in ran.output
    assert "allocated" not in ran.output.splitlines()
