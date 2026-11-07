"""RUN-02: the default install is small and model-free (no ML libraries, no model weights)."""

import importlib.util
import json
import os
import runpy
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[4]
# deploy/ is not a package: load the script (the one shared ML list) as a namespace.
check_artifacts = SimpleNamespace(**runpy.run_path(str(ROOT / "deploy" / "check_artifacts.py")))

START_APP = """
import json, sys
from fastapi.testclient import TestClient
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
with TestClient(create_app(Container.build(Settings())), base_url="http://localhost") as client:
    assert client.get("/api/health").status_code == 200
print(json.dumps(sorted(m.split(".")[0] for m in sys.modules)))
"""


def test_starting_the_app_imports_no_ml_library(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", START_APP],
        capture_output=True,
        text=True,
        env={**os.environ, "EXACTDOCS_DATA_DIR": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    loaded = set(json.loads(result.stdout.splitlines()[-1]))

    assert not loaded & check_artifacts.ML_MODULES


# What the `[ai]` extra brings (and what it pulls in that ExactDocs must never load on its own).
AI_MODULES = {
    "pydantic_ai",
    "pydantic_ai_harness",
    "pydantic_graph",
    "pydantic_monty",
    "sqlite_vec",
    "pgvector",
    "openai",
    "anthropic",
    "google.genai",
    "tiktoken",
    "logfire",
    "logfire_api",
    "genai_prices",
}

SEARCH_WITHOUT_MODELS = """
import asyncio, json, sys
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.dtos import GetLibraryRetrievalQuery, QueryDocsQuery, SearchDocsQuery
from exactdocs.retrieval.errors import UnknownLibraryError, VersionNotIndexedError

async def main():
    container = Container.build(Settings())
    async with container.running(jobs=False):
        retrieval = container.retrieval
        for ask in (
            lambda: retrieval.search_docs(SearchDocsQuery(library="/acme/x", query="retry")),
            lambda: retrieval.query_docs(QueryDocsQuery(library_id="/acme/x", query="retry")),
            lambda: retrieval.get_library_retrieval(GetLibraryRetrievalQuery(library="/acme/x")),
        ):
            try:
                await ask()
            except (UnknownLibraryError, VersionNotIndexedError):
                pass

asyncio.run(main())
print(json.dumps(sorted(sys.modules)))
"""


def test_the_ai_extra_is_installed_for_the_tests() -> None:
    """Otherwise the next test would pass for the wrong reason."""
    assert importlib.util.find_spec("pydantic_ai") is not None
    assert importlib.util.find_spec("sqlite_vec") is not None


@pytest.mark.parametrize("script", [START_APP, SEARCH_WITHOUT_MODELS], ids=["start", "search"])
def test_with_no_model_configured_nothing_of_the_ai_extra_is_imported(
    tmp_path: Path, script: str
) -> None:
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "EXACTDOCS_DATA_DIR": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    loaded = set(json.loads(result.stdout.splitlines()[-1]))
    top_level = {m.split(".")[0] for m in loaded}

    assert not (loaded | top_level) & AI_MODULES


def _lock(default: list[str], extra: list[str]) -> dict:
    def deps(names: list[str]) -> list[dict]:
        return [{"name": n} for n in names]

    return {
        "package": [
            {
                "name": "exactdocs",
                "dependencies": deps(default),
                "optional-dependencies": {"ai": deps(extra)},
            },
            {"name": "fastapi", "dependencies": deps(["starlette"])},
            {"name": "starlette"},
            {"name": "torch"},
        ]
    }


def test_an_ml_package_in_an_optional_extra_is_allowed() -> None:
    assert check_artifacts.default_ml_packages(_lock(["fastapi"], ["torch"])) == set()


def test_an_ml_package_in_the_default_dependencies_is_found() -> None:
    assert check_artifacts.default_ml_packages(_lock(["fastapi", "torch"], [])) == {"torch"}


def test_an_ml_package_below_a_default_dependency_is_found() -> None:
    lock = _lock(["fastapi"], [])
    lock["package"][1]["dependencies"].append({"name": "torch"})

    assert check_artifacts.default_ml_packages(lock) == {"torch"}


def test_the_dependency_tree_has_no_ml_package() -> None:
    lock = ROOT / "uv.lock"
    if not lock.exists():
        if os.environ.get("CI"):
            pytest.fail("uv.lock is missing in CI")
        pytest.skip("uv.lock is not part of an installed package")

    assert check_artifacts.default_ml_packages(tomllib.loads(lock.read_text())) == set()


def _wheel(tmp_path: Path, requires: str, web: bool = True) -> Path:
    path = tmp_path / "exactdocs-0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("exactdocs-0.dist-info/METADATA", f"Name: exactdocs\n{requires}\n")
        if web:
            z.writestr("exactdocs/_web/index.html", "<html>")
    return path


def test_a_wheel_with_an_ml_extra_passes(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, 'Requires-Dist: torch ; extra == "ai"\nRequires-Dist: fastapi')

    assert check_artifacts.wheel(wheel) == 0


def test_a_wheel_with_a_default_ml_dependency_fails(tmp_path: Path) -> None:
    assert check_artifacts.wheel(_wheel(tmp_path, "Requires-Dist: torch")) == 1


def test_a_wheel_without_the_bundled_ui_fails(tmp_path: Path) -> None:
    assert check_artifacts.wheel(_wheel(tmp_path, "", web=False)) == 1


def test_chonkie_is_not_banned() -> None:
    assert "chonkie" not in check_artifacts.ML_PACKAGES
