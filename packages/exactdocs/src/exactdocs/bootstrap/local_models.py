"""Builds the models of ``local`` profiles: fastembed in this process, from the models directory.

This module is light: it imports no fastembed. A model is found by its folder in
``EXACTDOCS_MODELS_DIR`` and the marker ``exactdocs models pull`` writes last, so a missing model
is known at start without importing anything, and its role is turned off there (it is never
downloaded). The first use, or the warm-up at start, imports ``bootstrap/local_sdk.py`` and
loads the model in a worker thread, once per process, from its folder only
(``specific_model_path``, ``local_files_only``). Calls run on two small thread pools: one for
the embedding jobs' document batches, one for what a search waits on (query embeddings,
reranks), so a search never queues behind ingestion. ONNX Runtime gets half the cores per call.
"""

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import NoReturn, cast

from exactdocs.bootstrap.constants import (
    CHECK_TEXT,
    LOCAL_DOCUMENT_WORKERS,
    LOCAL_EXTRA,
    LOCAL_MEMORY_ARENA,
    LOCAL_MODULES,
    LOCAL_QUERY_WORKERS,
    LOCAL_SDK_MODULE,
    MODEL_MARKER,
    MODEL_NAME,
    PINNED_MODEL_REVISIONS,
)
from exactdocs.retrieval.adapters.driven.local_models import (
    CrossEncoderModel,
    LocalEmbedder,
    LocalEmbeddingModels,
    LocalReranker,
    TextEmbeddingModel,
)
from exactdocs.retrieval.errors import EmbeddingFailedError, ProviderUnsupportedError, RerankerError
from exactdocs.retrieval.models import ModelCheck, ModelRole, ProviderProfile

logger = logging.getLogger(__name__)


def _installed(module: str) -> bool:
    """Tell whether a module could be imported, without importing it.

    Args:
        module: The module name.

    Returns:
        True when it is installed.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class PulledModel:
    """What ``exactdocs models pull`` recorded about a model it stored (its marker file)."""

    model: str
    """The model's name, as fastembed lists it."""
    role: ModelRole
    """``embedding`` or ``reranker``."""
    dimensions: int | None = None
    """An embedding model's vector size."""
    revision: str | None = None
    """The Hub commit it was pulled at (``None`` in a marker from before revisions were kept)."""


def onnx_threads() -> int:
    """Name the ONNX Runtime threads of one call: half the cores, at least one.

    Two calls may run at once (a document batch and a search's call), so together they use the
    cores without oversubscribing them.

    Returns:
        The threads.
    """
    return max(1, (os.cpu_count() or 2) // 2)


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalModelInfo:
    """What fastembed says about one of its models."""

    model: str
    """Its name, as fastembed lists it."""
    role: ModelRole
    """``embedding`` (a ``TextEmbedding``) or ``reranker`` (a ``TextCrossEncoder``)."""
    repository: str | None
    """Its repository on the Hugging Face Hub; ``None`` for one served from elsewhere."""
    files: tuple[str, ...]
    """Its ONNX file and the files beside it, relative to the repository."""
    dimensions: int | None
    """An embedding model's vector size."""
    size_mb: int
    """Its approximate download size."""


def model_folder(models_dir: Path, model: str) -> Path:
    """Name a model's folder in the models directory.

    Args:
        models_dir: ``EXACTDOCS_MODELS_DIR``.
        model: The model's name (``<org>/<name>``).

    Returns:
        ``<models dir>/<org>/<name>``.

    Raises:
        ValueError: The name could leave the directory (``..``, an absolute path).
    """
    if not MODEL_NAME.fullmatch(model) or ".." in model:
        message = f"{model!r} is not a model name (<org>/<name>)"
        raise ValueError(message)
    return models_dir / model


def read_marker(folder: Path) -> PulledModel | None:
    """Read the marker a complete pull leaves in a model's folder.

    Args:
        folder: The model's folder.

    Returns:
        What it records, or ``None`` when the folder has no readable marker.
    """
    try:
        data = json.loads((folder / MODEL_MARKER).read_text(encoding="utf-8"))
        dimensions, revision = data.get("dimensions"), data.get("revision")
        return PulledModel(
            model=str(data["model"]),
            role=ModelRole(data["role"]),
            dimensions=int(dimensions) if dimensions is not None else None,
            revision=str(revision) if revision is not None else None,
        )
    except OSError, ValueError, KeyError, TypeError, AttributeError:
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalModels:
    """Implements ``retrieval.ports.driven.ModelFactory`` for ``local`` profiles (fastembed)."""

    models_dir: Path
    """``EXACTDOCS_MODELS_DIR``: where ``exactdocs models pull`` stored the models."""
    _loaded: dict[tuple[ModelRole, str], object] = field(
        default_factory=dict, init=False, repr=False
    )
    """The models loaded so far, by role and lower-cased name: each once per process."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    """One load at a time (two first calls never load a model twice); taken in worker threads
    only, never on the event loop."""
    _pools: dict[str, ThreadPoolExecutor] = field(default_factory=dict, init=False, repr=False)
    """The ``documents`` and ``queries`` pools, made at first use and shut down by ``close``."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        """Say why this installation cannot run local models (fastembed is not installed).

        Args:
            profile: The profile.

        Returns:
            What to install, or ``None``.
        """
        del profile
        return None if all(_installed(m) for m in LOCAL_MODULES) else LOCAL_EXTRA

    def missing(self, model: str, role: ModelRole) -> str | None:
        """Say why a model cannot serve a role from the models directory, reading only its marker.

        Args:
            model: The model's name.
            role: ``embedding`` or ``reranker``.

        Returns:
            Why not (naming ``exactdocs models pull``), or ``None`` when it was pulled for it.
        """
        if role not in {ModelRole.EMBEDDING, ModelRole.RERANKER}:
            return f"a local profile runs embedding and reranker models only, not {role.value}"
        try:
            folder = model_folder(self.models_dir, model)
        except ValueError as error:
            return str(error)
        pulled = read_marker(folder)
        if pulled is None:
            return (
                f"model {model} is not in {self.models_dir}: run `exactdocs models pull {model}` "
                "where the server runs (models are never downloaded at run time)"
            )
        if pulled.role is not role:
            return f"{model} was pulled for the {pulled.role.value} role, not the {role.value} role"
        pinned = PINNED_MODEL_REVISIONS.get(pulled.model)
        if pinned is not None and pulled.revision != pinned:
            return (
                f"model {model} in {self.models_dir} was pulled at revision "
                f"{pulled.revision or 'unknown'}, not the pinned {pinned}: run "
                f"`exactdocs models pull {model}` again"
            )
        return None

    def _refuse(self, profile: ProviderProfile, reason: str) -> NoReturn:
        """Refuse to build a model.

        Args:
            profile: The profile.
            reason: Why.

        Raises:
            ProviderUnsupportedError: Always.
        """
        raise ProviderUnsupportedError(profile.name, reason)

    def _pool(self, kind: str) -> ThreadPoolExecutor:
        """Return one of the two pools, made at first use.

        No lock: a pool starts no thread before its first call, so one made twice by a race is
        dropped unused.

        Args:
            kind: ``documents`` or ``queries``.

        Returns:
            The pool.
        """
        pool = self._pools.get(kind)
        if pool is None:
            workers = LOCAL_DOCUMENT_WORKERS if kind == "documents" else LOCAL_QUERY_WORKERS
            made = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"local-{kind}")
            pool = self._pools.setdefault(kind, made)
        return pool

    def close(self) -> None:
        """Shut both pools down, dropping queued calls (``Container.running`` ends with it).

        A call already running finishes in its thread; the next use makes new pools.
        """
        while self._pools:
            _, pool = self._pools.popitem()
            pool.shutdown(wait=False, cancel_futures=True)

    def _sdk(self) -> ModuleType:
        """Import fastembed's side (in a worker thread the first time: it takes a second or two).

        Returns:
            ``exactdocs.bootstrap.local_sdk``.
        """
        loaded = sys.modules.get(LOCAL_SDK_MODULE)
        if loaded is not None:
            return loaded
        return importlib.import_module(LOCAL_SDK_MODULE)

    def _load(self, profile: ProviderProfile, role: ModelRole, model: str) -> object:
        """Load a model once per process (blocking: called in a worker thread).

        Args:
            profile: The profile.
            role: ``embedding`` or ``reranker``.
            model: The model's name.

        Returns:
            The loaded fastembed model.

        The refusals (``ProviderUnsupportedError``: fastembed is missing, the model was not
        pulled for this role, or it cannot be loaded) come from ``_refuse``.
        """
        if (reason := self.unsupported(profile) or self.missing(model, role)) is not None:
            self._refuse(profile, reason)
        key = (role, model.lower())
        with self._lock:
            if key in self._loaded:
                return self._loaded[key]
            started = time.perf_counter()
            sdk = self._sdk()
            folder = model_folder(self.models_dir, model)
            if sdk.describe(model) is None:
                self._refuse(profile, f"fastembed supports no model named {model!r}")
            load = sdk.load_embedding if role is ModelRole.EMBEDDING else sdk.load_cross_encoder
            try:
                loaded = load(
                    model,
                    folder,
                    self.models_dir,
                    threads=onnx_threads(),
                    arena=LOCAL_MEMORY_ARENA,
                )
            except sdk.errors() as error:  # a file missing or damaged, ONNX Runtime refusing it
                reason = f"model {model} in {folder} cannot be loaded ({type(error).__name__})"
                self._refuse(profile, f"{reason}: run `exactdocs models pull {model}` again")
            self._loaded[key] = loaded
        logger.info(
            "Local %s model %s loaded in %.1fs", role.value, model, time.perf_counter() - started
        )
        return loaded

    async def chat_model(self, profile: ProviderProfile, model: str) -> NoReturn:
        """Refuse: a local profile runs no chat model (``ProviderUnsupportedError``).

        Args:
            profile: The profile.
            model: The model.
        """
        del model
        self._refuse(profile, "a local profile runs no chat model: use the ollama kind for one")

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        """Load an embedding model (once) and hand it over with its thread pool.

        Args:
            profile: The profile.
            model: The model's name.

        Returns:
            A ``LocalEmbedder``.
        """
        loaded = await asyncio.to_thread(self._load, profile, ModelRole.EMBEDDING, model)
        pulled = read_marker(model_folder(self.models_dir, model))
        dimensions = pulled.dimensions if pulled is not None else None
        if dimensions is None:
            self._refuse(profile, f"the marker of {model} records no dimensions: pull it again")
        return LocalEmbedder(
            model=cast("TextEmbeddingModel", loaded),
            dimensions=dimensions,
            executor=self._pool("documents"),
            query_executor=self._pool("queries"),
            errors=self._sdk().errors(),
        )

    async def reranker(self, profile: ProviderProfile, model: str) -> LocalReranker:
        """Load a cross-encoder (once).

        Args:
            profile: The profile.
            model: The model's name.

        Returns:
            The reranker.
        """
        loaded = await asyncio.to_thread(self._load, profile, ModelRole.RERANKER, model)
        return LocalReranker(
            model=cast("CrossEncoderModel", loaded),
            executor=self._pool("queries"),
            errors=self._sdk().errors(),
        )

    async def release(self, name: str) -> None:
        """Keep the models: they belong to no endpoint and serve any profile that names them.

        Args:
            name: The profile's name.
        """
        del name

    async def warm(self, roles: Iterable[tuple[ProviderProfile, ModelRole, str]]) -> None:
        """Load the instance's local models at start, so no search waits for a load.

        A model that cannot be loaded is logged and left for its first call to report; the start
        goes on.

        Args:
            roles: The ``(profile, role, model)`` of each instance role on a ``local`` profile.
        """
        for profile, role, model in roles:
            try:
                await asyncio.to_thread(self._load, profile, role, model)
            except ProviderUnsupportedError as error:
                logger.warning("Local %s model %s not loaded: %s", role.value, model, error)

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        """Load the model and make one call as ``role`` uses it, and time it.

        Args:
            profile: The profile.
            model: The model's name.
            role: ``embedding`` or ``reranker`` (a chat role fails).

        Returns:
            The outcome.
        """
        started = time.perf_counter()
        try:
            dimensions = await self._call_once(profile, model, role)
        except (ProviderUnsupportedError, EmbeddingFailedError, RerankerError) as error:
            return ModelCheck(
                role=role,
                profile=profile.name,
                model=model,
                ok=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(error),
            )
        return ModelCheck(
            role=role,
            profile=profile.name,
            model=model,
            ok=True,
            latency_ms=(time.perf_counter() - started) * 1000,
            served_model=model,
            dimensions=dimensions,
        )

    async def _call_once(self, profile: ProviderProfile, model: str, role: ModelRole) -> int | None:
        """Make the one call a role's check makes.

        Args:
            profile: The profile.
            model: The model's name.
            role: The role.

        Returns:
            An embedding's vector size.
        """
        match role:
            case ModelRole.EMBEDDING:
                handle = await self.embedder(profile, model)
                embeddings = LocalEmbeddingModels().bind(
                    handle, name=f"{profile.name}:{model}", dimensions=None, batch_size=1
                )
                return len((await embeddings.embed_query(CHECK_TEXT)).vectors[0])
            case ModelRole.RERANKER:
                await (await self.reranker(profile, model)).rerank(CHECK_TEXT, [CHECK_TEXT])
                return None
            case ModelRole.LLM | ModelRole.JUDGE:
                return await self.chat_model(profile, model)
