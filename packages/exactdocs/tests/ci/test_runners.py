"""CI runs on our GCP self-hosted runners, and a fork's code never reaches them.

See docs/decisions/ci-runners.md and docs/releasing/runners.md.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
GCP = ["self-hosted", "linux", "ARM64", "exactdocs", "gcp"]
"""The one label set of every self-hosted job: ``gcp`` keeps jobs off any other runner."""
GCP_IN_EXPRESSION = "fromJSON('" + str(GCP).replace("'", '"').replace(" ", "") + "')"
NOT_A_FORK = "!github.event.pull_request.head.repo.fork"
HOSTED = "'ubuntu-24.04'"


def _jobs() -> list[Any]:
    found = []
    for path in WORKFLOWS:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in workflow["jobs"].items():
            if "runs-on" in job:  # a job that calls a reusable workflow has none
                # PyYAML reads the key `on` as True.
                found.append(pytest.param(job["runs-on"], workflow[True], id=f"{path.name}:{name}"))
    return found


JOBS = _jobs()
RUNS_ON = [pytest.param(job.values[0], id=job.id) for job in JOBS]


@pytest.mark.parametrize("runs_on", RUNS_ON)
def test_every_self_hosted_job_asks_for_the_gcp_runners(runs_on: str | list[str]) -> None:
    if isinstance(runs_on, list):
        assert runs_on == GCP
    else:
        rest = runs_on.replace(GCP_IN_EXPRESSION, "").replace(
            "vars.RUNNER_MODE == 'self-hosted'", ""
        )
        assert "self-hosted" not in rest, runs_on


@pytest.mark.parametrize(("runs_on", "on"), JOBS)
def test_a_pull_request_from_a_fork_gets_a_hosted_runner(
    runs_on: str | list[str], on: dict[str, Any]
) -> None:
    assert "pull_request_target" not in on
    if "pull_request" not in on:
        return
    assert isinstance(runs_on, str), runs_on
    assert NOT_A_FORK in runs_on, runs_on
    assert runs_on.endswith(f"|| {HOSTED} }}}}"), runs_on
