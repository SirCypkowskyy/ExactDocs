import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self

from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.bridges import (
    CatalogActiveManifests,
    CatalogIndexedVersions,
    CatalogLibraryIds,
    CatalogNewLibraries,
)
from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.adapters.driven.sqlite import (
    SqliteLibraryRepository,
    SqliteManifestRepository,
)
from exactdocs.identity import IdentityModule
from exactdocs.identity.adapters.driven.argon2id import Argon2idPasswordHasher
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
    SqliteTokenRepository,
)
from exactdocs.ingestion import IngestionModule
from exactdocs.ingestion.adapters.driven.git_cli import GitCli, MissingGit
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.adapters.driving.worker import JobWorker
from exactdocs.ingestion.errors import GitNotInstalledError, ImportNotAvailableError
from exactdocs.ingestion.models import IMPORT_JOB, Job
from exactdocs.ingestion.ports.driven import GitRemote, JobProgress
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.adapters.driven.memory import InMemoryExcerptIndex
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs_kernel import SystemClock

logger = logging.getLogger(__name__)


async def _import_not_available(job: Job, progress: JobProgress, /) -> None:
    """Stands in for the importer (E3-05a) so that adding a library can queue its job."""
    del job, progress
    raise ImportNotAvailableError


@dataclass(frozen=True, slots=True, kw_only=True)
class Container:
    """Every domain module, wired. Built once per process."""

    settings: Settings
    engine: AsyncEngine
    catalog: CatalogModule
    identity: IdentityModule
    ingestion: IngestionModule
    retrieval: RetrievalModule
    job_worker: JobWorker

    @classmethod
    def build(cls, settings: Settings, *, remote: GitRemote | None = None) -> Self:
        """Choose driven adapters and connect domains through bridges.

        Creates the data directory (``StartupError`` when it is unusable) but opens no
        connection; ``running()`` migrates the schema and releases the engine afterwards.
        ``remote`` replaces the system ``git`` (tests). A missing ``git`` is logged here and
        reported as ``git_not_installed`` by everything that needs it, so the rest still runs.
        """
        if remote is None:
            try:
                remote = GitCli.locate()
            except GitNotInstalledError as exc:
                logger.warning("%s", exc)
                remote = MissingGit()
        engine = open_database(settings)
        catalog = CatalogModule.build(
            repository=SqliteLibraryRepository(engine), manifests=SqliteManifestRepository(engine)
        )
        identity = IdentityModule.build(
            repository=SqliteAccountRepository(engine),
            sessions=SqliteSessionRepository(engine),
            tokens=SqliteTokenRepository(engine),
            hasher=Argon2idPasswordHasher(),
            clock=SystemClock(),
        )
        retrieval = RetrievalModule.build(
            versions=CatalogIndexedVersions(catalog.resolve_version),
            index=InMemoryExcerptIndex(),
            manifests=CatalogActiveManifests(
                catalog.get_active_manifest, catalog.get_manifest_states
            ),
            chunks=SqliteChunkRepository(engine),
            search=SqliteSearchIndex(engine),
        )
        # E3-05a replaces the placeholder handler and adds the import's recovery hook.
        ingestion = IngestionModule.build(
            jobs=SqliteJobRepository(engine),
            clock=SystemClock(),
            remote=remote,
            library_ids=CatalogLibraryIds(catalog.get_library),
            libraries=CatalogNewLibraries(catalog.create_library, catalog.discard_library),
            handlers={IMPORT_JOB: _import_not_available},
        )
        job_worker = JobWorker(
            recover_jobs=ingestion.recover_jobs, run_next_job=ingestion.run_next_job
        )
        return cls(
            settings=settings,
            engine=engine,
            catalog=catalog,
            identity=identity,
            ingestion=ingestion,
            retrieval=retrieval,
            job_worker=job_worker,
        )

    @asynccontextmanager
    async def running(self, *, jobs: bool = True) -> AsyncGenerator[None]:
        """Migrate the database, serve, then release the connections.

        ``jobs`` also runs the job worker (and the recovery before it). Only the HTTP server
        does: one process runs jobs, so ``serve --stdio`` passes ``False``.
        """
        try:
            await migrate(self.engine)
            if jobs:
                async with self.job_worker.running():
                    yield
            else:
                yield
        finally:
            await self.engine.dispose()
