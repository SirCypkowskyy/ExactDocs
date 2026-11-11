"""The fastembed side of local models (the ``[local]`` extra): imported only once one is used.

Every model loads from its own folder in ``EXACTDOCS_MODELS_DIR`` (``specific_model_path``,
``local_files_only``): fastembed 0.9.0 returns that folder before any Hub code runs, so loading
never reaches the Hugging Face Hub (``HF_HUB_OFFLINE`` is not needed, and not set; the
socket-blocked tests prove it). ``exactdocs models pull`` uses the same model
lists to know which files to fetch; it is the only command that downloads.
"""

import importlib
from pathlib import Path

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from exactdocs.bootstrap.local_models import LocalModelInfo
from exactdocs.retrieval.constants import LOCAL_MODEL_ERRORS
from exactdocs.retrieval.models import ModelRole


def errors() -> tuple[type[Exception], ...]:
    """Name what loading or calling a model raises.

    Returns:
        The tokenizer's and Python's errors, and ONNX Runtime's (which derive from
        ``Exception`` only).
    """
    native = importlib.import_module("onnxruntime.capi.onnxruntime_pybind11_state")
    found = (getattr(native, n) for n in dir(native))
    onnx = tuple(e for e in found if isinstance(e, type) and issubclass(e, Exception))
    return (*LOCAL_MODEL_ERRORS, KeyError, *onnx)


def describe(model: str) -> LocalModelInfo | None:
    """Look a model up in fastembed's lists (custom models registered in this process too).

    Args:
        model: The model's name, any letter case.

    Returns:
        What fastembed knows of it, or ``None`` when it is neither an embedding model nor a
        cross-encoder fastembed supports.
    """
    lists = (
        (ModelRole.EMBEDDING, TextEmbedding.list_supported_models()),
        (ModelRole.RERANKER, TextCrossEncoder.list_supported_models()),
    )
    for role, entries in lists:
        for entry in entries:
            if str(entry["model"]).lower() != model.lower():
                continue
            sources = entry.get("sources") or {}
            files = (str(entry["model_file"]), *(str(f) for f in entry.get("additional_files", [])))
            dimensions = entry.get("dim")
            return LocalModelInfo(
                model=str(entry["model"]),
                role=role,
                repository=sources.get("hf"),
                files=files,
                dimensions=int(dimensions) if dimensions is not None else None,
                size_mb=round(float(entry.get("size_in_GB") or 0) * 1000),
            )
    return None


def load_embedding(
    model: str, folder: Path, cache_dir: Path, *, threads: int, arena: bool
) -> TextEmbedding:
    """Load an embedding model from its folder, offline.

    Args:
        model: Its name, as fastembed lists it.
        folder: Its folder in the models directory.
        cache_dir: The models directory (fastembed requires one; nothing is written to it).
        threads: ONNX Runtime's threads per call.
        arena: Keep ONNX Runtime's CPU memory arena.

    Returns:
        The model, its ONNX session open.
    """
    return TextEmbedding(
        model,
        cache_dir=str(cache_dir),
        specific_model_path=str(folder),
        local_files_only=True,
        threads=threads,
        enable_cpu_mem_arena=arena,
    )


def load_cross_encoder(
    model: str, folder: Path, cache_dir: Path, *, threads: int, arena: bool
) -> TextCrossEncoder:
    """Load a cross-encoder from its folder, offline.

    Args:
        model: Its name, as fastembed lists it.
        folder: Its folder in the models directory.
        cache_dir: The models directory (fastembed requires one; nothing is written to it).
        threads: ONNX Runtime's threads per call.
        arena: Keep ONNX Runtime's CPU memory arena.

    Returns:
        The model, its ONNX session open.
    """
    return TextCrossEncoder(
        model,
        cache_dir=str(cache_dir),
        specific_model_path=str(folder),
        local_files_only=True,
        threads=threads,
        enable_cpu_mem_arena=arena,
    )
