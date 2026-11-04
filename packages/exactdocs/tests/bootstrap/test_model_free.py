"""RUN-02: the default install is small and model-free (no ML libraries, no model weights)."""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# Import names of ML stacks; PyPI names of the same stacks for the lockfile check.
ML_MODULES = ("torch", "transformers", "sentence_transformers", "pydantic_ai", "onnxruntime")
ML_PACKAGES = {
    "torch",
    "transformers",
    "sentence-transformers",
    "huggingface-hub",
    "onnx",
    "onnxruntime",
    "pydantic-ai",
    "pydantic-ai-slim",
    "tensorflow",
    "chonkie",
}

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

    assert not loaded & set(ML_MODULES)


def test_the_dependency_tree_has_no_ml_package() -> None:
    lock = Path(__file__).parents[4] / "uv.lock"
    if not lock.exists():
        pytest.skip("uv.lock is not part of an installed package")
    packages = tomllib.loads(lock.read_text())["package"]

    assert {p["name"] for p in packages} & ML_PACKAGES == set()
