"""External search and vector backends (#352): chosen from the settings, opened at start.

``EXACTDOCS_SEARCH_BACKEND`` and ``EXACTDOCS_VECTOR_BACKEND`` name a backend registered in
``INDEX_BACKENDS`` (``database``, the default, keeps today's indexes in ExactDocs' own database).
Its adapter module is imported only then, so its client library can be an optional extra; a
missing extra, invalid options, or a backend that does not answer at start stop the instance
with a message naming it. While serving, ``DriftWatch`` compares the backends with the database
now and then, for ``/healthz`` and the log.
"""

import asyncio
import importlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from exactdocs.bootstrap.cancellation import being_cancelled
from exactdocs.bootstrap.constants import (
    DATABASE_BACKEND,
    INDEX_BACKENDS,
    INDEX_DRIFT_CHECK_SECONDS,
    INDEX_DRIFT_LOGGED,
)
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.index_kinds import IndexBackendKind
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.dtos import ExternalIndexScope, IndexDriftOut
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs.retrieval.ports import CheckExternalIndexes, SearchBackend, VectorBackend

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexBackends:
    """The external backends this instance uses; ``None`` where the database holds the index."""

    search: SearchBackend | None = None
    """The full-text index's backend."""
    vectors: VectorBackend | None = None
    """The vector index's backend."""

    @property
    def names(self) -> tuple[str, str]:
        """The search and vector backends' names (``database`` for the database's own)."""
        return (
            DATABASE_BACKEND if self.search is None else self.search.name,
            DATABASE_BACKEND if self.vectors is None else self.vectors.name,
        )

    async def open(self) -> None:
        """Connect to each backend; one that does not answer stops the start, naming it.

        Raises:
            StartupError: A configured backend cannot be reached.
        """
        for role, backend in (("search", self.search), ("vector", self.vectors)):
            if backend is None:
                continue
            try:
                await backend.open()
            except IndexBackendUnavailableError as error:
                message = (
                    f"the {role} backend {backend.name!r} (EXACTDOCS_{role.upper()}_BACKEND) is "
                    f"unreachable: {error.reason}. Check [index_backends.{backend.name}] "
                    f"(EXACTDOCS_INDEX_BACKENDS__{backend.name.upper()}__...), or set "
                    f"EXACTDOCS_{role.upper()}_BACKEND=database"
                )
                raise StartupError(message) from error
            kind = INDEX_BACKENDS.get(backend.name)
            if kind is not None and not kind.production:
                logger.warning(
                    "The %s backend %r keeps nothing across a restart: it is for tests. "
                    "`exactdocs index rebuild` fills it from the database.",
                    role,
                    backend.name,
                )

    async def close(self) -> None:
        """Release every backend's connection (each is closed even if another fails)."""
        for backend in (self.search, self.vectors):
            if backend is None:
                continue
            try:
                await backend.close()
            except Exception:
                logger.exception("closing the index backend %r failed", backend.name)


def build_index_backends(
    settings: Settings, kinds: Mapping[str, IndexBackendKind] = INDEX_BACKENDS
) -> IndexBackends:
    """Build the backends the settings name (no connection is opened here).

    Args:
        settings: ``search_backend``, ``vector_backend`` and ``index_backends``.
        kinds: The registered backends (tests add their own).

    Returns:
        The backends.
    """
    search = _build(settings, kinds, settings.search_backend, "search")
    vectors = _build(settings, kinds, settings.vector_backend, "vectors")
    return IndexBackends(
        search=cast("SearchBackend | None", search), vectors=cast("VectorBackend | None", vectors)
    )


def _build(
    settings: Settings, kinds: Mapping[str, IndexBackendKind], name: str, role: str
) -> object | None:
    """Import a backend's adapter module and build it from its options.

    Args:
        settings: The settings, for the backend's options.
        kinds: The registered backends.
        name: The backend named in the settings.
        role: ``search`` or ``vectors``.

    Returns:
        The backend, or ``None`` for the database's own index.

    Raises:
        StartupError: The name is unknown, its extra is not installed, or its options are invalid.
    """
    if name == DATABASE_BACKEND:
        return None
    variable = "EXACTDOCS_SEARCH_BACKEND" if role == "search" else "EXACTDOCS_VECTOR_BACKEND"
    kind = kinds.get(name)
    factory_name = None if kind is None else (kind.search if role == "search" else kind.vectors)
    if kind is None or factory_name is None:
        known = ", ".join([DATABASE_BACKEND, *sorted(kinds)])
        message = f"{variable}={name!r} names no backend that can hold the {role} index ({known})"
        raise StartupError(message)
    try:
        module = importlib.import_module(kind.module)
    except ImportError as error:
        extra = f"exactdocs[{kind.extra}]" if kind.extra else "exactdocs"
        message = (
            f"{variable}={name!r} needs the {kind.extra or name} extra, which is not installed "
            f"({error.name or error}): pip install '{extra}' (or uvx --from '{extra}' exactdocs)"
        )
        raise StartupError(message) from error
    factory: Callable[[Mapping[str, Any]], object] = getattr(module, factory_name)
    options = settings.index_backends.get(name, {})
    try:
        return factory(options)
    except (ValueError, TypeError) as error:
        message = (
            f"[index_backends.{name}] (EXACTDOCS_INDEX_BACKENDS__{name.upper()}__...): {error}"
        )
        raise StartupError(message) from error


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- the last check
class DriftWatch:
    """Compares the external backends with the database at start and then every few minutes.

    What it found last is what ``/healthz`` reports (``index_versions_missing``); a check that
    finds drift logs it, naming the first versions, with the command that repairs it.
    """

    check: CheckExternalIndexes
    """Retrieval's comparison."""
    every: float = INDEX_DRIFT_CHECK_SECONDS
    """Seconds between checks."""
    last: IndexDriftOut | None = field(default=None, init=False)
    """What the last check found; ``None`` before the first one ends (or when it failed)."""
    checked_at: datetime | None = field(default=None, init=False)
    """When the last check ended."""

    @property
    def missing(self) -> int | None:
        """Versions the backends lack, hold in part or still hold after a removal (last check)."""
        return None if self.last is None else len(self.last.versions)

    async def run(self) -> None:
        """Check now, then every ``every`` seconds, until cancelled."""
        while True:
            await self.once()
            await asyncio.sleep(self.every)

    async def once(self) -> IndexDriftOut | None:
        """Check once; a failure is logged and leaves the count unknown.

        Returns:
            What the check found, or ``None`` when it failed.
        """
        try:
            found = await self.check(ExternalIndexScope())
        except Exception as error:
            if being_cancelled():  # the error replaced the server's stop: stop all the same
                raise
            if isinstance(error, IndexBackendUnavailableError):
                logger.warning("the external index backends could not be compared: %s", error)
            else:
                logger.exception("comparing the external index backends with the database failed")
            self.last = None
            return None
        self.last, self.checked_at = found, datetime.now(UTC)
        if found.versions:
            named = ", ".join(
                f"{v.index.value}: {v.version_id or v.manifest_id} {v.drift.value}"
                for v in found.versions[:INDEX_DRIFT_LOGGED]
            )
            more = len(found.versions) - INDEX_DRIFT_LOGGED
            logger.warning(
                "The external indexes drifted from the database (%s%s): "
                "`exactdocs index rebuild` writes them again.",
                named,
                f", and {more} more" if more > 0 else "",
            )
        return found
