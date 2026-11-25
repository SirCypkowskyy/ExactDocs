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

from exactdocs.bootstrap.constants import PINNED_MODEL_REVISIONS

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
    # The `[local]` extra (#245).
    "fastembed",
    "onnxruntime",
    "tokenizers",
    "huggingface_hub",
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


def test_the_ai_and_local_extras_are_installed_for_the_tests() -> None:
    """Otherwise the next test would pass for the wrong reason."""
    assert importlib.util.find_spec("pydantic_ai") is not None
    assert importlib.util.find_spec("sqlite_vec") is not None
    assert importlib.util.find_spec("fastembed") is not None
    assert importlib.util.find_spec("onnxruntime") is not None


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


LOCAL_MODULES = {"fastembed", "onnxruntime", "tokenizers", "huggingface_hub"}


@pytest.mark.parametrize("script", [START_APP, SEARCH_WITHOUT_MODELS], ids=["start", "search"])
def test_a_local_profile_without_a_role_imports_nothing_of_the_local_extra(
    tmp_path: Path, script: str
) -> None:
    """A `local` profile alone loads no model: only a role set on it does (#245)."""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "EXACTDOCS_DATA_DIR": str(tmp_path),
            "EXACTDOCS_AI__PROVIDERS__OFFLINE__KIND": "local",
        },
    )

    assert result.returncode == 0, result.stderr
    loaded = {m.split(".")[0] for m in json.loads(result.stdout.splitlines()[-1])}

    assert not loaded & LOCAL_MODULES


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


def _wheel(
    tmp_path: Path, requires: str, web: bool = True, notices: bool = True, licensed: bool = True
) -> Path:
    path = tmp_path / "exactdocs-0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("exactdocs-0.dist-info/METADATA", f"Name: exactdocs\n{requires}\n")
        if licensed:
            z.writestr("exactdocs-0.dist-info/licenses/LICENSE", "Apache License")
        if web:
            z.writestr("exactdocs/_web/index.html", "<html>")
            if notices:
                z.writestr("exactdocs/_web/THIRD_PARTY_NOTICES.txt", "MIT License")
    return path


def test_a_wheel_with_an_ml_extra_passes(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, 'Requires-Dist: torch ; extra == "ai"\nRequires-Dist: fastapi')

    assert check_artifacts.wheel(wheel) == 0


def test_a_wheel_with_a_default_ml_dependency_fails(tmp_path: Path) -> None:
    assert check_artifacts.wheel(_wheel(tmp_path, "Requires-Dist: torch")) == 1


def test_a_wheel_without_the_bundled_ui_fails(tmp_path: Path) -> None:
    assert check_artifacts.wheel(_wheel(tmp_path, "", web=False)) == 1


def test_a_wheel_whose_ui_has_no_third_party_notices_fails(tmp_path: Path) -> None:
    assert check_artifacts.wheel(_wheel(tmp_path, "", notices=False)) == 1


def test_a_wheel_without_the_license_fails(tmp_path: Path) -> None:
    assert check_artifacts.wheel(_wheel(tmp_path, "", licensed=False)) == 1


def test_chonkie_is_not_banned() -> None:
    assert "chonkie" not in check_artifacts.ML_PACKAGES


# The image variants (#246): what each may hold, judged from what `check_artifacts.py image`
# reads out of a built image (its distributions, its model files, its default models).
VARIANTS = check_artifacts.IMAGE_VARIANTS
MODELS_DIR = check_artifacts.MODELS_DIR
BASE_DISTRIBUTIONS = ["fastapi", "exactdocs", "dbos"]
AI_DISTRIBUTIONS = [*BASE_DISTRIBUTIONS, "pydantic_ai_slim", "openai", "azure-identity"]
LOCAL_DISTRIBUTIONS = [*AI_DISTRIBUTIONS, "fastembed", "onnxruntime", "tokenizers"]
DEFAULT_MODEL_FILES = [
    f"{MODELS_DIR}/BAAI/bge-small-en-v1.5/model_optimized.onnx",
    f"{MODELS_DIR}/Xenova/ms-marco-MiniLM-L-6-v2/onnx/model.onnx",
]
ONNX_EXAMPLE = "/app/.venv/lib/python3.14/site-packages/onnxruntime/datasets/sigmoid.onnx"


def test_each_variant_has_its_documented_budget() -> None:
    assert {k: v.budget for k, v in VARIANTS.items()} == {
        "base": 410_000_000,
        "ai": 560_000_000,
        "local": 950_000_000,
    }
    assert VARIANTS["base"].budget == check_artifacts.IMAGE_BUDGET


@pytest.mark.parametrize(
    ("variant", "distributions", "model_files"),
    [
        ("base", BASE_DISTRIBUTIONS, []),
        ("ai", AI_DISTRIBUTIONS, []),
        ("local", LOCAL_DISTRIBUTIONS, [*DEFAULT_MODEL_FILES, ONNX_EXAMPLE]),
    ],
)
def test_a_variant_with_what_it_may_hold_passes(
    variant: str, distributions: list[str], model_files: list[str]
) -> None:
    assert check_artifacts.image_problems(VARIANTS[variant], distributions, model_files, []) == []


@pytest.mark.parametrize(
    ("variant", "package"),
    [
        ("base", "pydantic-ai-slim"),
        ("base", "onnxruntime"),
        ("ai", "fastembed"),
        ("ai", "onnxruntime"),
        ("ai", "Huggingface_Hub"),
        ("ai", "torch"),
        ("local", "torch"),
        ("local", "onnx"),
        ("local", "transformers"),
        ("local", "sentence-transformers"),
    ],
)
def test_an_ml_package_the_variant_may_not_hold_fails(variant: str, package: str) -> None:
    problems = check_artifacts.image_problems(VARIANTS[variant], [package], [], [])

    assert problems == [f"package in image: {check_artifacts.normalize(package)}"]


@pytest.mark.parametrize("variant", ["base", "ai", "local"])
def test_no_variant_holds_aiohttp(variant: str) -> None:
    """Entra ID uses azure.identity's sync token provider (#241), never `azure.identity.aio`."""
    problems = check_artifacts.image_problems(VARIANTS[variant], ["aiohttp"], [], [])

    assert problems == ["package in image: aiohttp"]


@pytest.mark.parametrize("variant", ["base", "ai"])
def test_a_model_file_in_a_model_free_variant_fails(variant: str) -> None:
    problems = check_artifacts.image_problems(VARIANTS[variant], [], DEFAULT_MODEL_FILES[:1], [])

    assert problems == [f"model file in image: {DEFAULT_MODEL_FILES[0]}"]


def test_a_model_file_outside_the_models_directory_of_the_local_variant_fails() -> None:
    stray = "/data/models/BAAI/bge-small-en-v1.5/model_optimized.onnx"

    problems = check_artifacts.image_problems(VARIANTS["local"], [], [stray], [])

    assert problems == [f"model file in image: {stray}"]


def test_the_local_variant_without_its_default_models_fails() -> None:
    reason = "model BAAI/bge-small-en-v1.5 is not in /opt/exactdocs/models: run ..."

    problems = check_artifacts.image_problems(VARIANTS["local"], [], [], [reason])

    assert problems == [reason]


def test_the_local_variant_may_hold_only_what_the_local_extra_brings() -> None:
    allowed = VARIANTS["local"].allowed_ml

    assert allowed == {
        "fastembed",
        "onnxruntime",
        "tokenizers",
        "huggingface-hub",
        "pydantic-ai",
        "pydantic-ai-slim",
    }
    assert allowed <= check_artifacts.ML_PACKAGES


def test_every_default_model_has_a_pinned_onnx_digest() -> None:
    """The check verifies the ONNX bytes of each default model (one entry per model folder)."""
    folders = {
        name.rsplit("/", 1)[0].removesuffix("/onnx") for name in check_artifacts.MODEL_SHA256
    }

    assert folders == set(PINNED_MODEL_REVISIONS)
    assert all(len(d) == 64 for d in check_artifacts.MODEL_SHA256.values())


def test_without_python_the_distributions_come_from_their_dist_info_directories() -> None:
    """`check_artifacts.py image --no-python` (an amd64 image under QEMU) judges the same names."""
    site = "/app/.venv/lib/python3.14/site-packages"
    paths = [
        f"{site}/pydantic_ai_slim-1.0.0.dist-info",
        f"{site}/huggingface_hub-0.36.0.dist-info",
        f"{site}/exactdocs-0.0.0.dev0.dist-info",
        f"{site}/exactdocs-0.0.0.dev0.dist-info",
    ]

    names = check_artifacts.dist_info_names(paths)

    assert names == ["exactdocs", "huggingface_hub", "pydantic_ai_slim"]
    assert check_artifacts.image_problems(VARIANTS["base"], names, [], []) == [
        "package in image: huggingface-hub",
        "package in image: pydantic-ai-slim",
    ]
