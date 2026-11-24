"""#507: by default no test needs a service; one switch runs the integration tests too.

The default is proved the way ``uv run pytest`` runs: a fresh interpreter collects the whole
suite with every service variable set (to addresses nothing listens on, as in CI's fast jobs),
and a probe records what it selected. Nothing selected takes a service fixture, a server's case
or the ``integration`` marker, and the run ends saying how many it left out and how to run them.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from behave.parser import parse_file

import integration
from index_backends import EXTERNAL_BACKENDS

ROOT = Path(__file__).resolve().parents[4]
FEATURES = ROOT / "packages" / "exactdocs" / "features"
BACKENDS = ROOT / "packages" / "exactdocs" / "tests" / "retrieval" / "test_index_backends.py"
NOWHERE = "127.0.0.1:9"  # the discard port: nothing answers
SERVICES = {
    "EXACTDOCS_TEST_POSTGRES_URL": f"postgresql://exactdocs:unused@{NOWHERE}/exactdocs",
    "EXACTDOCS_TEST_PG_SEARCH": "1",
    "EXACTDOCS_TEST_PGBOUNCER_URL": f"postgresql://exactdocs:unused@{NOWHERE}/exactdocs",
    "EXACTDOCS_TEST_SUPABASE_URL": f"postgresql://postgres:unused@{NOWHERE}/postgres",
    "EXACTDOCS_TEST_LIBSQL_DATABASE_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_LIBSQL_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_QDRANT_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_ELASTICSEARCH_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_OPENSEARCH_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_CHROMA_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_REDIS_URL": f"redis://{NOWHERE}",
    "EXACTDOCS_TEST_MILVUS_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_MONGODB_URL": f"mongodb://{NOWHERE}/?directConnection=true",
    "EXACTDOCS_TEST_PINECONE_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_AZURE_SEARCH_URL": f"http://{NOWHERE}",
    "EXACTDOCS_TEST_MODELS_DIR": "/nonexistent/models",
    "EXACTDOCS_TEST_PROXY_IMAGE": "nonexistent/squid:none",
}
"""Every variable an integration test reads its service from, set as an integration run sets
them: the default must leave those tests out all the same."""
PROBE = """
import json, os
import pytest

@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session):
    rows = []
    for item in session.items:
        callspec = getattr(item, "callspec", None)
        rows.append({
            "id": item.nodeid,
            "marked": item.get_closest_marker("integration") is not None,
            "fixtures": list(getattr(item, "fixturenames", ())),
            "params": [str(v) for v in callspec.params.values()] if callspec else [],
        })
    with open(os.environ["PROBE_OUT"], "w", encoding="utf-8") as out:
        json.dump(rows, out)
"""
DESELECTED = re.compile(r"(\d+) integration tests deselected \(.*\); run them with .*--integration")


def _collect(tmp_path: Path, *args: str, switch: bool = False) -> tuple[list[dict], str]:
    """Collect as ``uv run pytest`` would, in a fresh interpreter, with every service variable set.

    Returns:
        What the probe saw selected, and the run's output.
    """
    (tmp_path / "integration_probe.py").write_text(PROBE, encoding="utf-8")
    out = tmp_path / "selected.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("EXACTDOCS_REQUIRE_")}
    env.pop(integration.VARIABLE, None)
    env |= SERVICES | {"PYTHONPATH": str(tmp_path), "PROBE_OUT": str(out)}
    if switch:
        env[integration.VARIABLE] = "1"
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "integration_probe"]
    done = subprocess.run(
        [*command, "-p", "no:cacheprovider", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    return json.loads(out.read_text(encoding="utf-8")), done.stdout


def _behave_environment() -> ModuleType:
    """``features/environment.py``, loaded by its path (behave's own hooks, not a package)."""
    spec = importlib.util.spec_from_file_location("behave_environment", FEATURES / "environment.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _on_a_server(row: dict) -> bool:
    """Whether a selected test runs on a server: a PostgreSQL or a server backend's case.

    The contract suites name a backend case by its name (``test_index_backends.py``) or as
    ``external:<name>``; elsewhere a bare engine name is only a parameter of an options test.
    """
    servers = {case.name for case in EXTERNAL_BACKENDS if case.marks is not None}
    named = {"postgres", "postgres_c", "pg_search", *(f"external:{name}" for name in servers)}
    if row["id"].startswith(f"{BACKENDS.relative_to(ROOT).as_posix()}::"):
        named |= servers
    return bool(named & set(row["params"]))


def test_by_default_no_collected_test_needs_a_service(tmp_path: Path) -> None:
    selected, output = _collect(tmp_path)

    services = set(integration.FIXTURES)
    assert len(selected) > 5000, output[-2000:]  # the whole suite was collected
    assert [r["id"] for r in selected if r["marked"]] == []
    assert [r["id"] for r in selected if services & set(r["fixtures"])] == []
    assert [r["id"] for r in selected if _on_a_server(r)] == []
    found = DESELECTED.search(output)
    assert found is not None, output[-2000:]
    assert int(found.group(1)) > 1000  # PostgreSQL alone has hundreds


def test_the_switch_runs_the_integration_tests_and_m_narrows_to_them(tmp_path: Path) -> None:
    default, output = _collect(tmp_path, str(BACKENDS))
    switched, _ = _collect(tmp_path, str(BACKENDS), switch=True)
    narrowed, _ = _collect(tmp_path, str(BACKENDS), "-m", "integration", switch=True)

    found = DESELECTED.search(output)
    assert found is not None, output
    left_out = {r["id"] for r in switched} - {r["id"] for r in default}
    assert int(found.group(1)) == len(left_out) > 0
    assert {r["id"] for r in narrowed} == left_out
    assert all(r["marked"] for r in narrowed)
    assert not any(r["marked"] for r in default)


def test_every_server_case_carries_the_marker_of_its_variable() -> None:
    for case in EXTERNAL_BACKENDS:
        if case.marks is None:
            continue
        assert case.marks.name == integration.MARKER, case.name
        assert case.marks.args, f"{case.name}: name the variable its server comes from"
        assert all(name.startswith("EXACTDOCS_TEST_") for name in case.marks.args), case.name


def test_every_scenario_with_a_service_tag_is_an_integration_scenario() -> None:
    services = set(_behave_environment().SERVICES)
    tagged, untagged = [], []
    for path in sorted(FEATURES.glob("*.feature")):
        feature = parse_file(str(path))
        assert feature is not None, path
        for scenario in feature.walk_scenarios():
            tags = set(scenario.effective_tags)
            if "integration" in tags:
                tagged.append(scenario.location)
            elif tags & services:
                untagged.append(f"{scenario.location}: {sorted(tags & services)}")

    assert untagged == []
    assert len(tagged) >= len(services)  # at least one scenario per service
    assert services <= set(_behave_environment().SERVICES)
