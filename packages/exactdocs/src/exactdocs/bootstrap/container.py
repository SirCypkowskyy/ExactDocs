import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self

from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.bridges import (
    CatalogActiveManifests,
    CatalogLibraryIds,
    CatalogLibrarySources,
    CatalogNewLibraries,
    CatalogSearchableVersions,
    CatalogVersionPublisher,
    RetrievalChunkIndex,
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
from exactdocs.ingestion import IngestionModule, import_job
from exactdocs.ingestion.adapters.driven.git_cli import GitCli, MissingGit, sweep_stale_fetches
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.adapters.driving.worker import JobWorker
from exactdocs.ingestion.errors import GitNotInstalledError
from exactdocs.ingestion.ports.driven import GitGateway, GitRemote
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs_kernel import SystemClock

logger = logging.getLogger(__name__)
WORK_DIR = "work"  # under the data dir: one folder per running git fetch


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
    def build(
        cls,
        settings: Settings,
        *,
        remote: GitRemote | None = None,
        gateway: GitGateway | None = None,
    ) -> Self:
        """Choose driven adapters and connect domains through bridges.

        Creates the data directory (``StartupError`` when it is unusable) but opens no
        connection; ``running()`` migrates the schema and releases the engine afterwards.
        ``remote`` and ``gateway`` replace the system ``git`` for listing refs and for fetching
        (tests). A missing ``git`` is logged here and
        reported as ``git_not_installed`` by everything that needs it, so the rest still runs.
        """
        if remote is None or gateway is None:
            try:
                git: GitCli | MissingGit = GitCli.locate(work_root=settings.data_dir / WORK_DIR)
            except GitNotInstalledError as exc:
                logger.warning("%s", exc)
                git = MissingGit()
            remote = remote or git
            gateway = gateway or git
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
            searchable=CatalogSearchableVersions(catalog.get_library, catalog.get_active_manifest),
            manifests=CatalogActiveManifests(
                catalog.get_active_manifest, catalog.get_manifest_states
            ),
            chunks=SqliteChunkRepository(engine),
            search=SqliteSearchIndex(engine),
        )
        handlers, recovery_hooks = import_job(
            gateway=gateway,
            chunker=MarkdownChunker(),
            sources=CatalogLibrarySources(catalog.get_library),
            versions=CatalogVersionPublisher(
                catalog.store_manifest,
                catalog.activate_manifest,
                catalog.discard_pending_manifests,
                catalog.apply_readme,
            ),
            index=RetrievalChunkIndex(
                retrieval.index_manifest, retrieval.get_chunk_sets, retrieval.discard_pending_chunks
            ),
            max_article_bytes=settings.max_article_bytes,
            max_import_bytes=settings.max_import_bytes,
        )
        ingestion = IngestionModule.build(
            jobs=SqliteJobRepository(engine),
            clock=SystemClock(),
            remote=remote,
            library_ids=CatalogLibraryIds(catalog.get_library),
            libraries=CatalogNewLibraries(catalog.create_library, catalog.discard_library),
            sources=CatalogLibrarySources(catalog.get_library),
            handlers=handlers,
            recovery_hooks=recovery_hooks,
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
                # Fetch folders a crash left behind. A data dir has exactly one job runner.
                await asyncio.to_thread(sweep_stale_fetches, self.settings.data_dir / WORK_DIR)
                async with self.job_worker.running():
                    yield
            else:
                yield
        finally:
            await self.engine.dispose()
