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


def report(kind: str, size: int, budget: int, problems: list[str]) -> int:
    line = f"{kind}: {size / 1e6:.1f} MB of {budget / 1e6:.0f} MB budget"
    if size > budget:
        problems.append(f"{line} - over budget")
    print(line)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as f:
            f.write(f"{line}\n\n")
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


def wheel(path: Path) -> int:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        meta = next(n for n in names if n.endswith(".dist-info/METADATA"))
        requires = re.findall(r"^Requires-Dist: ([A-Za-z0-9_.-]+)", z.read(meta).decode(), re.M)
    problems = [f"model file in wheel: {n}" for n in names if n.endswith(MODEL_SUFFIXES)]
    for r in requires:
        if r.lower().replace("_", "-") in ML_PACKAGES:
            problems.append(f"wheel requires ML package {r}")
    return report("wheel", path.stat().st_size, WHEEL_BUDGET, problems)


def image(ref: str) -> int:
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
    kind, target = sys.argv[1:3]
    sys.exit({"wheel": lambda: wheel(Path(target)), "image": lambda: image(target)}[kind]())
