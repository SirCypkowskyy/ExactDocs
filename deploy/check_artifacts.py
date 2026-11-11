"""Release-artifact guard (RUN-02): size budgets and no ML models or libraries. Stdlib only.

    check_artifacts.py wheel <file.whl>                       size, model files, ML dependencies
    check_artifacts.py image <image-ref> [base|ai|local]      size, installed packages, model
                                                              files (needs docker)

The image comes in three variants (#246), each with its own budget: `base` and `ai` hold no
model file and no ML package (`ai` may hold pydantic-ai, which only calls models elsewhere);
`local` holds ONNX Runtime and must hold the default models, at their pinned revisions, in its
read-only models directory. No variant holds aiohttp.

Budgets and reasoning: docs/releasing.md ("Size and model-free budgets").
"""

import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

MB = 1_000_000
WHEEL_BUDGET = 5 * MB
MODEL_SUFFIXES = (".safetensors", ".bin", ".onnx", ".gguf", ".pt")
# ML stacks that must stay out of the default install; optional extras (`[ai]`) may carry them.
ML_PACKAGES = {
    "torch",
    "transformers",
    "sentence-transformers",
    "huggingface-hub",
    "onnx",
    "onnxruntime",
    "fastembed",
    "tokenizers",
    "model2vec",
    "pydantic-ai",
    "pydantic-ai-slim",
    "tensorflow",
}
ML_MODULES = {p.replace("-", "_") for p in ML_PACKAGES}
LLM_CLIENT_PACKAGES = frozenset({"pydantic-ai", "pydantic-ai-slim"})
"""In ML_PACKAGES for the default install, but allowed in the `-ai` image: they call hosted or
self-hosted models over HTTP and run none themselves."""
NEVER_IN_IMAGES = frozenset({"aiohttp"})
"""Entra ID uses azure.identity's sync token provider (#241), never `azure.identity.aio`."""
MODELS_DIR = "/opt/exactdocs/models"
"""Where the `-local` image keeps its default models (EXACTDOCS_MODELS_DIR)."""
ONNX_EXAMPLES = "/site-packages/onnxruntime/datasets/"
"""ONNX Runtime's own example models (a few KB, for its docs): the only model files the `-local`
image may hold outside MODELS_DIR."""


@dataclass(frozen=True, slots=True)
class Variant:
    """What one image variant may hold."""

    budget: int
    """Unpacked file bytes (`du -sxb /` in the container)."""
    allowed_ml: frozenset[str]
    """ML_PACKAGES it may hold."""
    models: bool
    """It holds the default local models in MODELS_DIR (and model files only there)."""


IMAGE_VARIANTS = {
    # 375 MB until DBOS (#65); see docs/releasing.md.
    "base": Variant(budget=400 * MB, allowed_ml=frozenset(), models=False),
    "ai": Variant(budget=560 * MB, allowed_ml=LLM_CLIENT_PACKAGES, models=False),
    "local": Variant(budget=950 * MB, allowed_ml=frozenset(ML_PACKAGES), models=True),
}
IMAGE_BUDGET = IMAGE_VARIANTS["base"].budget
USAGE = "usage: check_artifacts.py wheel <file.whl> | image <image-ref> [base|ai|local]"

# Run in the image's own Python: the installed distributions, and (local) why a default model
# cannot serve its role, judged by ExactDocs' own check of the marker `models pull` wrote
# (EXPECTED, the models directory, is prepended).
LIST_DISTRIBUTIONS = (
    "import importlib.metadata as m, json; "
    "print(json.dumps(sorted({d.metadata['Name'] for d in m.distributions()})))"
)
CHECK_MODELS = """
import json, os
from pathlib import Path
from exactdocs.bootstrap.constants import DEFAULT_LOCAL_EMBEDDING, DEFAULT_LOCAL_RERANKER
from exactdocs.bootstrap.local_models import LocalModels
from exactdocs.retrieval.models import ModelRole
problems = []
folder = os.environ.get("EXACTDOCS_MODELS_DIR")
if folder != EXPECTED:
    problems.append(f"EXACTDOCS_MODELS_DIR is {folder!r}, not {EXPECTED!r}")
else:
    local = LocalModels(models_dir=Path(folder))
    for model, role in (
        (DEFAULT_LOCAL_EMBEDDING, ModelRole.EMBEDDING),
        (DEFAULT_LOCAL_RERANKER, ModelRole.RERANKER),
    ):
        if (reason := local.missing(model, role)) is not None:
            problems.append(reason)
    if os.access(folder, os.W_OK):
        problems.append(f"{folder} is writable by the server's user")
print(json.dumps(problems))
"""


def default_ml_packages(lock: dict, root: str = "exactdocs") -> set[str]:
    """ML packages reachable from `root` through non-optional dependencies of a parsed uv.lock."""
    by_name = {p["name"]: p for p in lock["package"]}
    seen: set[str] = set()
    todo = [root]
    while todo:
        name = todo.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        todo += [d["name"] for d in by_name[name].get("dependencies", [])]
    return seen & ML_PACKAGES


def normalize(name: str) -> str:
    """Normalize a distribution name (PEP 503).

    Args:
        name: The name as its metadata spells it.

    Returns:
        Lower case, with runs of `-`, `_` and `.` as one `-`.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def report(kind: str, size: int, budget: int, problems: list[str]) -> int:
    """Print the size line and problems (also to the job summary); return the exit code."""
    line = f"{kind}: {size / MB:.1f} MB of {budget / MB:.0f} MB budget"
    if size > budget:
        problems.append(f"{line} - over budget")
    sys.stdout.write(f"{line}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as f:
            f.write(f"{line}\n\n")
    for p in problems:
        sys.stdout.write(f"::error::{p}\n")
    return 1 if problems else 0


def wheel(path: Path) -> int:
    """Check a built wheel: size, model files, bundled UI, default ML requirements."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        meta = next(n for n in names if n.endswith(".dist-info/METADATA"))
        requires = re.findall(
            r"^Requires-Dist: ([A-Za-z0-9_.-]+)(.*)$", z.read(meta).decode(), re.M
        )
        has_web = "exactdocs/_web/index.html" in names
    problems = [f"model file in wheel: {n}" for n in names if n.endswith(MODEL_SUFFIXES)]
    if not has_web:
        problems.append("wheel has no exactdocs/_web/index.html (UI not bundled)")
    for r, rest in requires:
        if "extra ==" not in rest and r.lower().replace("_", "-") in ML_PACKAGES:
            problems.append(f"wheel requires ML package {r}")
    return report("wheel", path.stat().st_size, WHEEL_BUDGET, problems)


def image_problems(
    variant: Variant, distributions: list[str], model_files: list[str], models: list[str]
) -> list[str]:
    """Judge what an image variant holds (its size is judged by `report`).

    Args:
        variant: The variant it was built as.
        distributions: The Python distributions installed in it.
        model_files: Files with a model suffix anywhere in its filesystem.
        models: Why its default models cannot serve (local only; empty when they can).

    Returns:
        The problems.
    """
    installed = {normalize(d) for d in distributions}
    banned = (ML_PACKAGES - variant.allowed_ml) | NEVER_IN_IMAGES
    problems = [f"package in image: {p}" for p in sorted(installed & banned)]
    problems += [
        f"model file in image: {f}"
        for f in model_files
        if not (variant.models and (f.startswith(f"{MODELS_DIR}/") or ONNX_EXAMPLES in f))
    ]
    return problems + models


def _run(ref: str, *command: str, root: bool = False) -> str:
    """Run a command in a throwaway container of the image, without network.

    Args:
        ref: The image.
        command: The entry point and its arguments.
        root: Run as root (to read every file), not as the image's user.

    Returns:
        Its standard output.
    """
    user = ["--user", "0"] if root else []
    entry, *args = command
    return subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", *user, "--entrypoint", entry, ref, *args],
        text=True,
    )


def image(ref: str, kind: str = "base") -> int:
    """Check a docker image variant: size, installed packages, model files, default models."""
    variant = IMAGE_VARIANTS[kind]
    # Apparent bytes of the files inside: `docker image inspect` .Size is the compressed size
    # under the containerd image store (115 MB in CI vs 352 MB with overlay2), so don't use it.
    size = int(_run(ref, "du", "-sxb", "/", root=True).split()[0])
    predicate = [a for s in MODEL_SUFFIXES for a in ("-o", "-name", f"*{s}")][1:]
    found = _run(ref, "find", "/", "-xdev", "(", *predicate, ")", root=True).split()
    distributions = json.loads(_run(ref, "python", "-c", LIST_DISTRIBUTIONS))
    models = []
    if variant.models:
        script = f"EXPECTED = {MODELS_DIR!r}\n{CHECK_MODELS}"
        models = json.loads(_run(ref, "python", "-c", script).splitlines()[-1])
    problems = image_problems(variant, distributions, found, models)
    return report(f"image ({kind})", size, variant.budget, problems)


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["wheel", path]:
            sys.exit(wheel(Path(path)))
        case ["image", ref]:
            sys.exit(image(ref))
        case ["image", ref, kind] if kind in IMAGE_VARIANTS:
            sys.exit(image(ref, kind))
        case _:
            sys.exit(USAGE)
