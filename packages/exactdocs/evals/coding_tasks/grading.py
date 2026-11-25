"""Grade a workspace: its hidden tests in the sandbox, the forbidden APIs it uses, what it changed.

``materialize`` builds a workspace from a task: the ecosystem's scaffold, the environment's
lockfile, the task's template and, to check a solution, its files laid over them. ``grade``
copies the workspace, adds the hidden tests and a test configuration the workspace cannot change
(warnings are errors; for TypeScript, a strict type check of ``src/``), and runs them in the
sandbox with the prepared environment. Inside the sandbox it first reads the version of the pinned
package that is installed, so the report shows the tests ran against exactly that version. It
then compares the workspace with the template (files added, changed, deleted) and matches each
forbidden API against the changed code, comments removed.
"""

import io
import json
import re
import shlex
import shutil
import tempfile
import tokenize
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agent_bench.harness import AgentRun
from coding_tasks.environments import Forbidden, PreparedEnvironment
from coding_tasks.sandbox import Isolation, Limits, Sandbox, sandbox_environment
from coding_tasks.tasks import SCAFFOLD_DIR, CodingTask, files_of

HIDDEN_DIR: Final[str] = "hidden_tests"
"""Where the hidden tests go in the graded copy (never in the agent's workspace)."""
VISIBLE_DIR: Final[str] = "tests"
"""The workspace's own tests, which the agent can run."""
SOURCE_DIR: Final[str] = "src"
"""Where a TypeScript workspace's code lives (what the type check covers)."""
HOME_DIR: Final[str] = ".home"
"""``HOME`` and ``TMPDIR`` of a sandboxed command, inside the workspace."""
NODE_MODULES: Final[str] = "node_modules"
"""A Node workspace's link to the prepared ``node_modules``."""
IGNORED: Final[frozenset[str]] = frozenset(
    {HIDDEN_DIR, HOME_DIR, NODE_MODULES, "__pycache__", ".pytest_cache", ".venv", "junit.xml"}
)
"""Names never compared with the template nor shown to the agent."""
CODE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".py", ".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".html", ".jinja"}
)
"""Files the forbidden APIs are looked for in."""
MARKER: Final[re.Pattern[str]] = re.compile(r"^@@(installed|typecheck|tests) (.*)$", re.MULTILINE)
"""The lines the test script prints about each step."""
TS_BLOCK_COMMENT: Final[re.Pattern[str]] = re.compile(r"/\*.*?\*/", re.DOTALL)
"""A ``/* ... */`` comment."""
TS_LINE_COMMENT: Final[re.Pattern[str]] = re.compile(r"(?<![:\"'\\])//.*$", re.MULTILINE)
"""A ``// ...`` comment (not ``://`` in a URL)."""
TEST_TIMEOUT_MS: Final[int] = 30_000
"""How long one Node test may take; the runner also exits once the tests end, whatever timers
the library left (``--test-force-exit``)."""
HIDDEN_PYTEST_INI: Final[str] = """\
[pytest]
pythonpath = .
filterwarnings =
    error
"""
"""The hidden tests' configuration: the workspace's root on the path, every warning an error."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class TestOutcome(_Model):
    """How a workspace's tests ended in the sandbox."""

    passed: bool
    """Every test passed (and, for TypeScript, the type check), and none was missing."""
    installed: str | None = None
    """The version of the pinned package installed in the sandbox, read there."""
    typecheck: bool | None = None
    """``tsc`` found no error (TypeScript); ``None`` for Python."""
    tests: int = 0
    """Tests run."""
    failed: int = 0
    """Tests that failed or errored."""
    failures: list[str] = Field(default_factory=list)
    """The names of the tests that failed."""
    exit_code: int | None = None
    """The test command's exit status; ``None`` when it was killed at the wall limit."""
    timed_out: bool = False
    """It was killed at the wall limit."""
    seconds: float = 0.0
    """How long it took."""
    output: str = ""
    """Its output (the end)."""


class ForbiddenHit(_Model):
    """One use of an API that must not appear for the pinned version."""

    api: str
    """The API."""
    reason: str
    """Why it must not appear."""
    file: str
    """The file, relative to the workspace."""
    line: int
    """The line it is on."""


class Changes(_Model):
    """What a workspace changed against its template."""

    added: list[str] = Field(default_factory=list)
    """Files that are new."""
    modified: list[str] = Field(default_factory=list)
    """Files whose content changed."""
    deleted: list[str] = Field(default_factory=list)
    """Files that are gone."""

    @property
    def count(self) -> int:
        """How many files changed.

        Returns:
            Added, modified and deleted files.
        """
        return len(self.added) + len(self.modified) + len(self.deleted)


class Grade(_Model):
    """A workspace's grade."""

    tests: TestOutcome
    """The hidden tests."""
    forbidden: list[ForbiddenHit] = Field(default_factory=list)
    """Forbidden APIs in the changed code."""
    changes: Changes = Field(default_factory=Changes)
    """The files changed."""
    unexpected: list[str] = Field(default_factory=list)
    """Changed files the task did not name (``files``)."""
    isolation: Isolation
    """How the sandbox enforced its limits."""

    @property
    def passed(self) -> bool:
        """The task passes: its hidden tests passed.

        Returns:
            ``tests.passed``.
        """
        return self.tests.passed

    @property
    def apis(self) -> list[str]:
        """The forbidden APIs used, each once.

        Returns:
            Their names, in order of first use.
        """
        return list(dict.fromkeys(hit.api for hit in self.forbidden))


class TaskRun(_Model):
    """The output of one task: what the agent did (none for a fixed solution) and the grade."""

    agent: AgentRun | None = None
    """The agent's run; ``None`` when a fixed solution was checked."""
    grade: Grade | None = None
    """The grade; ``None`` when the run failed on the provider's side (not graded)."""
    solution: str = "agent"
    """``agent``, or the fixed solution checked (``reference``, ``other``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Runner:
    """Runs a task's tests: the sandbox, its limits and the task's prepared environment."""

    sandbox: Sandbox
    """The sandbox."""
    prepared: PreparedEnvironment
    """The task's environment, installed."""
    limits: Limits = field(default_factory=Limits)
    """The limits of each test run."""

    async def run_tests(self, workspace: Path, *, hidden: bool) -> TestOutcome:
        """Run the hidden or the visible tests of a workspace in the sandbox.

        Args:
            workspace: The workspace (a graded copy for the hidden tests).
            hidden: Run ``hidden_tests/`` with the grading configuration; else the workspace's own
                ``tests/`` with its own configuration.

        Returns:
            How they ended.
        """
        script = test_script(self.prepared, workspace, hidden=hidden)
        script_dir = workspace / HOME_DIR
        script_dir.mkdir(exist_ok=True)
        (script_dir / "junit.xml").unlink(missing_ok=True)
        (script_dir / "run.sh").write_text(script, encoding="utf-8")
        pythonpath = {"PYTHONPATH": ":".join(str(p) for p in self.prepared.pythonpath)}
        env = sandbox_environment(
            home=script_dir,
            path=self.prepared.bin_dirs,
            extra=pythonpath if self.prepared.pythonpath else None,
        )
        ran = await self.sandbox.run(
            ["/bin/sh", str(script_dir / "run.sh")],
            cwd=workspace,
            writable=workspace,
            readable=self.prepared.mounts,
            env=env,
            limits=self.limits,
        )
        markers = {key: value.strip() for key, value in MARKER.findall(ran.output)}
        tests, failures = _junit(script_dir / "junit.xml")
        typecheck = None if "typecheck" not in markers else markers["typecheck"] == "0"
        passed = (
            ran.exit_code == 0
            and markers.get("tests") == "0"
            and typecheck is not False
            and tests > 0
            and not failures
        )
        return TestOutcome(
            passed=passed,
            installed=markers.get("installed") or None,
            typecheck=typecheck,
            tests=tests,
            failed=len(failures),
            failures=failures,
            exit_code=ran.exit_code,
            timed_out=ran.timed_out,
            seconds=ran.seconds,
            output=ran.output,
        )

    async def grade(self, task: CodingTask, workspace: Path) -> Grade:
        """Grade a workspace: its hidden tests, forbidden APIs and changed files.

        Args:
            task: The task.
            workspace: The workspace, left as it is (a copy is graded).

        Returns:
            The grade.
        """
        changes = changes_of(task, workspace)
        forbidden = forbidden_hits(workspace, [*changes.added, *changes.modified], task.forbidden)
        with tempfile.TemporaryDirectory(prefix=f"grade-{task.id}-") as tmp:
            copy = Path(tmp) / "workspace"
            shutil.copytree(
                workspace, copy, symlinks=True, ignore=shutil.ignore_patterns(HIDDEN_DIR, HOME_DIR)
            )
            hidden = copy / HIDDEN_DIR
            shutil.copytree(task.hidden, hidden)
            if task.environment.spec.ecosystem == "python":
                (hidden / "pytest.ini").write_text(HIDDEN_PYTEST_INI, encoding="utf-8")
            else:
                (hidden / "tsconfig.json").write_text(_hidden_tsconfig(), encoding="utf-8")
            outcome = await self.run_tests(copy, hidden=True)
        return Grade(
            tests=outcome,
            forbidden=forbidden,
            changes=changes,
            unexpected=[
                f
                for f in (*changes.added, *changes.modified, *changes.deleted)
                if f not in task.spec.files
            ],
            isolation=self.sandbox.isolation,
        )


def test_script(prepared: PreparedEnvironment, workspace: Path, *, hidden: bool) -> str:
    """Write the shell script that runs a workspace's tests and says how each step ended.

    It prints ``@@installed <version>`` (read inside the sandbox), ``@@typecheck <status>``
    (TypeScript) and ``@@tests <status>``, and writes a JUnit report to ``.home/junit.xml``.

    Args:
        prepared: The environment.
        workspace: The workspace (its tests are listed for Node, which takes files).
        hidden: The hidden tests and their configuration, or the workspace's own.

    Returns:
        The script.
    """
    spec = prepared.environment.spec
    junit = f"{HOME_DIR}/junit.xml"
    tests_dir = HIDDEN_DIR if hidden else VISIBLE_DIR
    lines = ["#!/bin/sh", 'cd "$(dirname "$0")/.." || exit 2']
    if spec.ecosystem == "python":
        python = shlex.quote(str(prepared.python))
        probe = "import importlib.metadata as m, sys; print(m.version(sys.argv[1]))"
        lines.append(f'echo "@@installed $({python} -c {shlex.quote(probe)} {spec.package})"')
        config = f"-c {HIDDEN_DIR}/pytest.ini --rootdir=. --noconftest" if hidden else ""
        lines += [
            (
                f"{python} -m pytest {config} -p no:cacheprovider -q -rfE "
                f"--junitxml={junit} {tests_dir}"
            ),
            "status=$?",
            'echo "@@tests $status"',
            "exit $status",
        ]
        return "\n".join(lines) + "\n"
    node = shlex.quote(str(prepared.node))
    probe = (
        "process.stdout.write(JSON.parse(require('fs').readFileSync("
        f"'{NODE_MODULES}/{spec.package}/package.json','utf8')).version)"
    )
    tsconfig = f"{HIDDEN_DIR}/tsconfig.json" if hidden else "tsconfig.json"
    files = sorted(
        p.relative_to(workspace).as_posix() for p in (workspace / tests_dir).glob("*.test.ts")
    )
    lines += [
        f'echo "@@installed $({node} -e {shlex.quote(probe)})"',
        f"{node} {NODE_MODULES}/typescript/bin/tsc -p {tsconfig} --pretty false",
        "typecheck=$?",
        'echo "@@typecheck $typecheck"',
        f"{node} --test --test-force-exit --test-timeout={TEST_TIMEOUT_MS} "
        "--test-reporter=spec --test-reporter-destination=stdout "
        f"--test-reporter=junit --test-reporter-destination={junit} "
        + " ".join(shlex.quote(f) for f in files),
        "status=$?",
        'echo "@@tests $status"',
        '[ "$typecheck" -eq 0 ] && [ "$status" -eq 0 ]',
    ]
    return "\n".join(lines) + "\n"


def _hidden_tsconfig() -> str:
    """The hidden type check's configuration: the scaffold's, on ``src/`` only.

    Returns:
        ``tsconfig.json`` for ``hidden_tests/`` (paths relative to it).
    """
    config = json.loads((SCAFFOLD_DIR / "node" / "tsconfig.json").read_text(encoding="utf-8"))
    config["include"] = [f"../{SOURCE_DIR}"]
    return json.dumps(config, indent=2) + "\n"


def _junit(path: Path) -> tuple[int, list[str]]:
    """Read a JUnit report.

    Args:
        path: The report (missing when the run never got to the tests).

    Returns:
        The tests run, and the names of those that failed or errored.
    """
    if not path.exists():
        return 0, []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0, ["<unreadable junit report>"]
    cases = list(root.iter("testcase"))
    failed = [
        f"{case.get('classname', '')}::{case.get('name', '')}".removeprefix("::")
        for case in cases
        if case.find("failure") is not None or case.find("error") is not None
    ]
    return len(cases), failed


def materialize(
    task: CodingTask,
    destination: Path,
    prepared: PreparedEnvironment | None = None,
    *,
    solution: Path | None = None,
) -> Path:
    """Build a task's workspace: scaffold, lockfile, template, and a solution over them.

    Args:
        task: The task.
        destination: A new directory.
        prepared: The installed environment, linked in as ``node_modules`` for Node.
        solution: A solution's files to lay over the template (``reference/``, ``other/``).

    Returns:
        The workspace.
    """
    destination.mkdir(parents=True)
    for relative, data in template_files(task).items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for relative, source in files_of(solution or destination / "-none-").items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if prepared is not None and prepared.node_modules is not None:
        (destination / NODE_MODULES).symlink_to(prepared.node_modules, target_is_directory=True)
    return destination


def template_files(task: CodingTask) -> dict[str, bytes]:
    """What a task's workspace starts with.

    Args:
        task: The task.

    Returns:
        ``relative path -> content``: the scaffold, the lockfiles, then the template, each
        overriding the one before.
    """
    files = {
        relative: path.read_bytes()
        for relative, path in files_of(SCAFFOLD_DIR / task.environment.spec.ecosystem).items()
    }
    for name in task.environment.lockfiles:
        files[name] = (task.environment.directory / name).read_bytes()
    files |= {relative: path.read_bytes() for relative, path in files_of(task.workspace).items()}
    return dict(sorted(files.items()))


def workspace_files(workspace: Path) -> dict[str, Path]:
    """List a workspace's files, without the environment link and what the tools write.

    Args:
        workspace: The workspace.

    Returns:
        ``relative path -> file``.
    """
    found = {}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace)
        if IGNORED & set(relative.parts) or not path.is_file() or path.is_symlink():
            continue
        found[relative.as_posix()] = path
    return found


def changes_of(task: CodingTask, workspace: Path) -> Changes:
    """Compare a workspace with its template.

    Args:
        task: The task.
        workspace: The workspace.

    Returns:
        The files added, modified and deleted.
    """
    before = template_files(task)
    after = workspace_files(workspace)
    return Changes(
        added=[f for f in after if f not in before],
        modified=[f for f in after if f in before and after[f].read_bytes() != before[f]],
        deleted=[f for f in before if f not in after],
    )


def code_without_comments(path: Path, text: str) -> str:
    """Remove a file's comments, keeping its lines where they were.

    Args:
        path: The file (its suffix says the language).
        text: Its content.

    Returns:
        The text without Python ``#`` comments or JavaScript/TypeScript ``//`` and ``/* */``
        comments; Python that does not tokenize is returned as it is.
    """
    if path.suffix == ".py":
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except tokenize.TokenError, SyntaxError:
            return text
        lines = text.splitlines(keepends=True)
        for token in reversed(tokens):
            if token.type == tokenize.COMMENT:
                row, col = token.start
                line = lines[row - 1]
                lines[row - 1] = line[:col] + line[token.end[1] :]
        return "".join(lines)
    if path.suffix in {".html", ".jinja"}:
        return text
    text = TS_BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return TS_LINE_COMMENT.sub("", text)


def forbidden_hits(
    workspace: Path, changed: Sequence[str], forbidden: Sequence[Forbidden]
) -> list[ForbiddenHit]:
    """Find the forbidden APIs in a workspace's changed code.

    Args:
        workspace: The workspace.
        changed: The files added or modified (relative paths).
        forbidden: The APIs that must not appear.

    Returns:
        Every hit: API, file and line, in file order.
    """
    hits = []
    patterns = [(f, re.compile(f.pattern, re.MULTILINE)) for f in forbidden]
    for relative in changed:
        path = workspace / relative
        if path.suffix not in CODE_SUFFIXES or not path.is_file():
            continue
        code = code_without_comments(path, path.read_text(encoding="utf-8", errors="replace"))
        for rule, pattern in patterns:
            for match in pattern.finditer(code):
                line = code.count("\n", 0, match.start()) + 1
                hits.append(
                    ForbiddenHit(api=rule.api, reason=rule.reason, file=relative, line=line)
                )
    return sorted(hits, key=lambda h: (h.file, h.line, h.api))
