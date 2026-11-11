"""``exactdocs models pull``: download local models into ``EXACTDOCS_MODELS_DIR`` (#245).

The only code that contacts the Hugging Face Hub. Each model goes to ``<models dir>/<org>/<name>``
as plain files (its ONNX file and its tokenizer), fetched into a temporary folder beside it and
renamed into place, with a marker written last: the server loads a model only when its marker is
there. A model already pulled is skipped without any request, so a CI cache of the directory
makes the command offline.
"""

import importlib
import importlib.util
import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from exactdocs.bootstrap.constants import (
    DEFAULT_LOCAL_EMBEDDING,
    DEFAULT_LOCAL_RERANKER,
    HUB_FILES,
    LOCAL_EXTRA,
    LOCAL_MODULES,
    LOCAL_SDK_MODULE,
    MODEL_MARKER,
    TOKENIZER_FILES,
)
from exactdocs.bootstrap.local_models import LocalModelInfo, model_folder, read_marker

type Download = Callable[[str, Sequence[str], Path], None]
"""Fetches ``(repository, files, into folder)``: the Hub's ``snapshot_download`` by default."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Pulled:
    """What ``pull`` did for one model."""

    model: str
    """The model, as asked for."""
    ok: bool
    """It is in the models directory now."""
    message: str
    """What happened, for the terminal."""


def hub_download(repository: str, files: Sequence[str], folder: Path) -> None:
    """Fetch files of a Hub repository into a folder (huggingface_hub, imported here only).

    Args:
        repository: ``<org>/<name>`` on the Hub.
        files: The files (glob patterns) to fetch; others in the repository are skipped.
        folder: Where they go, with the repository's layout.
    """
    hub = importlib.import_module("huggingface_hub")
    hub.snapshot_download(repo_id=repository, allow_patterns=list(files), local_dir=folder)


def default_models() -> tuple[str, ...]:
    """Name the models pulled when none is named.

    Returns:
        The default embedding model and cross-encoder.
    """
    return (DEFAULT_LOCAL_EMBEDDING, DEFAULT_LOCAL_RERANKER)


def pull(
    models: Sequence[str], models_dir: Path, *, download: Download = hub_download
) -> list[Pulled]:
    """Download each model that is not in the models directory yet.

    Args:
        models: The models' names, as fastembed lists them.
        models_dir: ``EXACTDOCS_MODELS_DIR``.
        download: Fetches files from the Hub (tests: copies a fixture).

    Returns:
        One outcome per model, in order.
    """
    if not all(importlib.util.find_spec(m) is not None for m in LOCAL_MODULES):
        return [Pulled(model=m, ok=False, message=LOCAL_EXTRA) for m in models]
    sdk = importlib.import_module(LOCAL_SDK_MODULE)
    return [_pull_one(sdk.describe(model), model, models_dir, download) for model in models]


def _pull_one(
    info: LocalModelInfo | None, model: str, models_dir: Path, download: Download
) -> Pulled:
    """Download one model.

    Args:
        info: fastembed's ``LocalModelInfo`` for it, or ``None``.
        model: The model, as asked for.
        models_dir: ``EXACTDOCS_MODELS_DIR``.
        download: Fetches files from the Hub.

    Returns:
        The outcome.
    """
    if info is None:
        reason = "fastembed supports no embedding model or cross-encoder of this name"
        return Pulled(model=model, ok=False, message=reason)
    name, repository, files = info.model, info.repository, info.files
    folder = model_folder(models_dir, name)
    if (pulled := read_marker(folder)) is not None and pulled.model == name:
        return Pulled(model=model, ok=True, message=f"already in {folder}")
    if repository is None:
        return Pulled(model=model, ok=False, message="it is not on the Hugging Face Hub")
    staging = folder.with_name(f".{folder.name}.pulling")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        download(repository, [*HUB_FILES, *files], staging)
        absent = [f for f in (files[0], *TOKENIZER_FILES) if not (staging / f).is_file()]
        if absent:
            return Pulled(model=model, ok=False, message=f"{repository} has no {', '.join(absent)}")
        shutil.rmtree(staging / ".cache", ignore_errors=True)  # the Hub's download metadata
        marker = {
            "model": name,
            "role": info.role.value,
            "dimensions": info.dimensions,
            "repository": repository,
            "files": list(files),
        }
        (staging / MODEL_MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
        shutil.rmtree(folder, ignore_errors=True)  # an incomplete earlier pull
        staging.rename(folder)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1e6
    return Pulled(model=model, ok=True, message=f"pulled into {folder} ({size:.0f} MB)")
