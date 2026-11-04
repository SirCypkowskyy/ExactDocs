"""Release-artifact guard (RUN-02): size budgets and no ML models or libraries. Stdlib only.

    check_artifacts.py wheel <file.whl>     size, model files, ML dependencies
    check_artifacts.py image <image-ref>    size, model files (needs docker)

Budgets and reasoning: docs/releasing.md ("Size and model-free budgets").
"""

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

WHEEL_BUDGET = 5_000_000
IMAGE_BUDGET = 375_000_000
MODEL_SUFFIXES = (".safetensors", ".bin", ".onnx", ".gguf", ".pt")
# ML stacks that must stay out of the default install; optional extras (`[ai]`) may carry them.
ML_PACKAGES = {
    "torch",
    "transformers",
    "sentence-transformers",
    "huggingface-hub",
    "onnx",
    "onnxruntime",
    "model2vec",
    "pydantic-ai",
    "pydantic-ai-slim",
    "tensorflow",
}
ML_MODULES = {p.replace("-", "_") for p in ML_PACKAGES}
USAGE = "usage: check_artifacts.py wheel <file.whl> | image <image-ref>"


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


def report(kind: str, size: int, budget: int, problems: list[str]) -> int:
    """Print the size line and problems (also to the job summary); return the exit code."""
    line = f"{kind}: {size / 1e6:.1f} MB of {budget / 1e6:.0f} MB budget"
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


def image(ref: str) -> int:
    """Check a docker image: size and model files anywhere in the filesystem."""
    size = int(
        subprocess.check_output(["docker", "image", "inspect", ref, "--format", "{{.Size}}"])
    )
    predicate = [a for s in MODEL_SUFFIXES for a in ("-o", "-name", f"*{s}")][1:]
    found = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "--entrypoint",
            "find",
            ref,
            "/",
            "-xdev",
            "(",
            *predicate,
            ")",
        ],
        text=True,
    ).split()
    return report("image", size, IMAGE_BUDGET, [f"model file in image: {f}" for f in found])


if __name__ == "__main__":
    handlers = {"wheel": lambda t: wheel(Path(t)), "image": image}
    if len(sys.argv) != 3 or sys.argv[1] not in handlers:  # ruff: ignore[magic-value-comparison]
        sys.exit(USAGE)
    sys.exit(handlers[sys.argv[1]](sys.argv[2]))
