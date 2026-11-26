"""#554: GitHub Actions runs the integration and end-to-end jobs only when someone starts them.

``integration.yml`` has no trigger of its own but a manual run, and the workflows that call it do so
only from a manual run that asks for it with the input ``integration``. A pull request, a push or a
tag starts none of them, and no release job waits for them, so a tag push publishes without them.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = ROOT / ".github" / "workflows"
INTEGRATION = "./.github/workflows/integration.yml"
ON_REQUEST = "${{ github.event_name == 'workflow_dispatch' && inputs.integration }}"
"""The ``if:`` of every job that calls the integration workflow."""
ON_A_TAG = "github.event_name == 'push'"
"""The ``if:`` of the release's publishing jobs."""
STATUS_FUNCTIONS = ("always()", "cancelled()", "failure()", "success()")


def _workflow(name: str) -> dict[Any, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """The ``on:`` block: YAML 1.1, which PyYAML reads, takes the bare key ``on`` for ``True``."""
    return {event: config or {} for event, config in workflow[True].items()}


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _upstream(jobs: dict[str, Any], name: str) -> set[str]:
    """Every job ``name`` waits for, directly or through another job."""
    found: set[str] = set()
    todo = _needs(jobs[name])
    while todo:
        job = todo.pop()
        if job not in found:
            found.add(job)
            todo.extend(_needs(jobs[job]))
    return found


def _callers() -> list[tuple[str, str]]:
    return [
        (path.name, name)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for name, job in _workflow(path.name)["jobs"].items()
        if job.get("uses") == INTEGRATION
    ]


def test_the_integration_workflow_runs_only_by_hand_or_when_called() -> None:
    workflow = _workflow("integration.yml")
    triggers = _triggers(workflow)

    assert set(triggers) == {"workflow_dispatch", "workflow_call"}
    # #533: every caller gets the same jobs on the same hosted runners: no trigger has inputs.
    assert all("inputs" not in config for config in triggers.values())


def test_no_integration_job_looks_at_a_pull_request_or_a_label() -> None:
    workflow = _workflow("integration.yml")
    # Comments are gone once parsed: what is left is what GitHub evaluates.
    gates = json.dumps(
        [workflow.get("concurrency"), *(job.get("if") for job in workflow["jobs"].values())]
    )

    for word in ("pull_request", "label", "run integration"):
        assert word not in gates


def test_only_ci_and_the_release_call_the_integration_workflow() -> None:
    assert _callers() == [("ci.yml", "integration"), ("release.yml", "integration")]


@pytest.mark.parametrize(("file", "job"), _callers())
def test_a_caller_runs_the_integration_jobs_only_when_its_manual_run_asks(
    file: str, job: str
) -> None:
    workflow = _workflow(file)
    asked = _triggers(workflow)["workflow_dispatch"]["inputs"]["integration"]

    assert (asked["type"], asked["default"]) == ("boolean", False)
    assert workflow["jobs"][job]["if"] == ON_REQUEST


def test_no_release_job_waits_for_the_integration_jobs() -> None:
    # A tag push skips them, and a job whose `needs` holds a skipped job is skipped, as is every
    # job after it: the release would publish nothing.
    jobs = _workflow("release.yml")["jobs"]

    assert "integration" in jobs
    assert [name for name in jobs if "integration" in _upstream(jobs, name)] == []


def test_every_publishing_job_still_needs_the_eval_and_the_builds_to_pass() -> None:
    jobs = _workflow("release.yml")["jobs"]
    publishing = {name for name, job in jobs.items() if job.get("if") == ON_A_TAG}

    assert publishing == {"pypi-kernel", "pypi", "image-publish", "github-release"}
    assert {"python", "eval"} <= _upstream(jobs, "pypi-kernel")
    assert {"image-scan", "eval", "image"} <= _upstream(jobs, "image-publish")
    for name in publishing | {"image"}:  # no status function: every job it needs must succeed
        assert not any(f in str(jobs[name].get("if", "")) for f in STATUS_FUNCTIONS), name
