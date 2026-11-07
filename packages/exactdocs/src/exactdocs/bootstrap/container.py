import asyncio
import logging
import threading
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Self

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.bridges import (
    CatalogActiveManifests,
    CatalogArticleSuggestions,
    CatalogCollector,
    CatalogDefaultVersions,
    CatalogImportedTags,
    CatalogLibraries,
    CatalogLibraryIds,
    CatalogLibrarySettings,
    CatalogLibrarySources,
    CatalogManualTags,
    CatalogNewLibraries,
    CatalogRemovals,
    CatalogRenamedPaths,
    CatalogSearchableVersions,
    CatalogStoredArticles,
    CatalogVersionCopier,
    CatalogVersionPublisher,
    RetrievalChunkIndex,
    RetrievalCollector,
)
from exactdocs.bootstrap.constants import (
    CREDENTIALS_KEY_PURPOSE,
    JOBS_FILE,
    KEY_FILE,
    KNOWN_HOSTS_FILE,
    WORK_DIR,
)
from exactdocs.bootstrap.database import (
    StartupError,
    check_schema_is_current,
    migrate,
    open_database,
)
from exactdocs.bootstrap.secret_box import FernetSecretBox
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.telemetry import search_tracer, traced_jobs
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.adapters.driven.sqlite import (
    SqliteImportedTags,
    SqliteLibraryRepository,
    SqliteManifestCopier,
    SqliteManifestRepository,
    SqliteStoredArticles,
)
from exactdocs.identity import IdentityModule
from exactdocs.identity.adapters.driven.argon2id import Argon2idPasswordHasher
from exactdocs.identity.adapters.driven.memory import InMemoryFailedSignInLog
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
    SqliteTokenRepository,
)
from exactdocs.ingestion import IngestionModule, TagLocks, collect_job, import_job
from exactdocs.ingestion.adapters.driven.dbos import (
    DbosCheckpoints,
    DbosJobQueue,
    DbosScheduleSwitch,
)
from exactdocs.ingestion.adapters.driven.git_cli import GitCli, MissingGit, sweep_stale_fetches
from exactdocs.ingestion.adapters.driven.known_hosts import seed_known_hosts
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.sqlite import (
    SqliteAutoSyncStore,
    SqliteCredentialVault,
    SqliteJobRepository,
)
from exactdocs.ingestion.adapters.driving.dbos_worker import DbosJobWorker
from exactdocs.ingestion.constants import QUEUE, SCHEDULE, STEPS_VERSION, WORKFLOW
from exactdocs.ingestion.errors import GitNotInstalledError
from exactdocs.ingestion.ports.driven import (
    Chunker,
    GitGateway,
    GitRemote,
    RenameSource,
    RepositoryTree,
)
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository, SqliteLibraryModes
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs.retrieval.models import RetrievalMode
from exactdocs.retrieval.ports.driven import ModelRoles, RetrievalPipeline
from exactdocs_kernel import SystemClock

logger = logging.getLogger(__name__)


def _build_read_side(
    engine: AsyncEngine,
    settings: Settings,
    *,
    model_roles: ModelRoles | None = None,
    pipelines: Mapping[RetrievalMode, RetrievalPipeline] | None = None,
) -> tuple[CatalogModule, RetrievalModule]:
    """Build the catalog and retrieval modules: everything the read-only MCP tools use.

    Args:
        engine: The database.
        settings: The runtime configuration.
        model_roles: The configured model roles (tests; none until #241 reads them).
        pipelines: Retrieval modes beside BM25 (tests, until the AI modes are built).

    Returns:
        The two modules.
    """
    catalog = CatalogModule.build(
        repository=SqliteLibraryRepository(engine=engine),
        manifests=SqliteManifestRepository(engine=engine),
        imported_tags=SqliteImportedTags(engine=engine),
        stored_articles=SqliteStoredArticles(engine=engine),
        copier=SqliteManifestCopier(engine=engine),
    )
    search = SqliteSearchIndex(engine=engine)
    retrieval = RetrievalModule.build(
        searchable=CatalogSearchableVersions(
            get_library=catalog.get_library, get_active_manifest=catalog.get_active_manifest
        ),
        libraries=CatalogLibraries(
            list_libraries=catalog.list_libraries, get_library=catalog.get_library
        ),
        defaults=CatalogDefaultVersions(list_default_manifests=catalog.list_default_manifests),
        manifests=CatalogActiveManifests(
            get_active_manifest=catalog.get_active_manifest,
            get_manifest_states=catalog.get_manifest_states,
        ),
        chunks=SqliteChunkRepository(engine=engine),
        search=search,
        maintenance=search,
        renames=CatalogRenamedPaths(resolve_renamed_path=catalog.resolve_renamed_path),
        library_modes=SqliteLibraryModes(engine=engine),
        roles=model_roles,
        instance_mode=settings.retrieval_mode,
        pipelines=pipelines,
        suggestions=CatalogArticleSuggestions(get_article=catalog.get_article),
        query_docs_token_budget=settings.query_docs_token_budget,
        tracer=search_tracer(settings),
    )
    return catalog, retrieval


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadOnlyContainer:
    """Catalog and retrieval over an existing database opened read-only (``serve --stdio``).

    No identity, ingestion, worker, secret key, ``known_hosts`` or ``git``: nothing here can write.
    """

    engine: AsyncEngine
    catalog: CatalogModule
    retrieval: RetrievalModule
    _run: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def build(cls, settings: Settings) -> Self:
        """Open the database read-only; ``StartupError`` when it does not exist."""
        engine = open_database(settings, read_only=True)
        catalog, retrieval = _build_read_side(engine, settings)
        return cls(engine=engine, catalog=catalog, retrieval=retrieval)

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[None]:
        """Check the schema is current (no migration), serve, then release the connections.

        Runs once at a time, like ``Container.running()``: ``RuntimeError`` otherwise.
        """
        if not self._run.acquire(blocking=False):
            message = "this container is already running; run it once"
            raise RuntimeError(message)
        try:
            await check_schema_is_current(self.engine)
            yield
        finally:
            try:
                await self.engine.dispose()
            finally:
                self._run.release()


@dataclass(frozen=True, slots=True, kw_only=True)
class Container:
    """Every domain module, wired. Built once per process."""

    settings: Settings
    engine: AsyncEngine
    catalog: CatalogModule
    identity: IdentityModule
    ingestion: IngestionModule
    retrieval: RetrievalModule
    job_worker: DbosJobWorker
    # Held for the duration of `running()`: a lock, so a run in another thread (a TestClient's
    # event loop) is refused as well.
    _run: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        remote: GitRemote | None = None,
        gateway: GitGateway | None = None,
        renames: RenameSource | None = None,
        tree: RepositoryTree | None = None,
        chunker: Chunker | None = None,
        model_roles: ModelRoles | None = None,
        pipelines: Mapping[RetrievalMode, RetrievalPipeline] | None = None,
    ) -> Self:
        """Choose driven adapters and connect domains through bridges.

        Creates the data directory (``StartupError`` when it is unusable) but opens no
        connection; ``running()`` migrates the schema and releases the engine afterwards.
        ``remote``, ``gateway`` and ``renames`` replace the system ``git`` for listing refs, for
        fetching and for detecting renames (tests; a given ``gateway`` detects none unless
        ``renames`` is given too); ``chunker`` replaces the Markdown chunker (tests);
        ``model_roles`` and ``pipelines`` stand in for configured models and the AI retrieval
        modes (tests, until #241 configures them). A missing
        ``git`` is logged here and reported as ``git_not_installed`` by everything that needs
        it, so the rest still runs.
        """
        engine = open_database(settings)  # creates the data dir first (or says why not)
        if remote is None or gateway is None or tree is None:
            try:
                seed_known_hosts(settings.data_dir / KNOWN_HOSTS_FILE)
                git: GitCli | MissingGit = GitCli.locate(
                    work_root=settings.data_dir / WORK_DIR,
                    known_hosts=settings.data_dir / KNOWN_HOSTS_FILE,
                )
            except GitNotInstalledError as exc:
                logger.warning("%s", exc)
                git = MissingGit()
            remote = remote or git
            renames = renames or (git if gateway is None else None)
            gateway = gateway or git
            tree = tree or git
        try:
            secret_box = (
                FernetSecretBox.from_secrets(
                    settings.secret_key.get_secret_value(),
                    *(
                        [settings.secret_key_previous.get_secret_value()]
                        if settings.secret_key_previous
                        else []
                    ),
                    purpose=CREDENTIALS_KEY_PURPOSE,
                )
                if settings.secret_key
                else FernetSecretBox.from_file(
                    settings.data_dir / KEY_FILE, purpose=CREDENTIALS_KEY_PURPOSE
                )
            )
        except ValueError as error:  # fixed texts: they never repeat a key
            raise StartupError(str(error)) from None
        vault = SqliteCredentialVault(engine=engine, box=secret_box)
        catalog, retrieval = _build_read_side(
            engine, settings, model_roles=model_roles, pipelines=pipelines
        )
        index = RetrievalChunkIndex(
            index_manifest=retrieval.index_manifest,
            get_chunk_sets=retrieval.get_chunk_sets,
            discard_pending_chunks=retrieval.discard_pending_chunks,
            remove_chunks=retrieval.remove_chunks,
            retag_articles=retrieval.retag_articles,
        )
        tag_locks = TagLocks()  # per library: tagging and an import's activation take turns
        handlers, recovery_hooks = import_job(
            gateway=gateway,
            chunker=chunker or MarkdownChunker(),
            sources=CatalogLibrarySources(
                get_library=catalog.get_library, list_renames=catalog.list_renames
            ),
            versions=CatalogVersionPublisher(
                store_manifest=catalog.store_manifest,
                activate_manifest=catalog.activate_manifest,
                discard_pending_manifests=catalog.discard_pending_manifests,
                apply_readme=catalog.apply_readme,
                apply_manual_tags_to=catalog.apply_manual_tags,
                replace_renames_of=catalog.replace_renames,
            ),
            index=index,
            vault=vault,
            max_article_bytes=settings.max_article_bytes,
            max_import_bytes=settings.max_import_bytes,
            renames=renames,
            stored=CatalogStoredArticles(find_stored_articles=catalog.find_stored_articles),
            max_image_bytes=settings.max_image_bytes,
            max_images_bytes=settings.max_images_bytes,
            checkpoints=DbosCheckpoints(),
            batch_files=settings.import_batch_files,
            tag_locks=tag_locks,
            imported_tags=CatalogImportedTags(
                get_version_tags=catalog.get_version_tags,
                set_imported_tags_of=catalog.set_imported_tags,
            ),
            copier=CatalogVersionCopier(copy_manifest=catalog.copy_manifest),
        )
        ingestion = IngestionModule.build(
            jobs=SqliteJobRepository(engine=engine),
            clock=SystemClock(),
            remote=remote,
            tree=tree,
            library_ids=CatalogLibraryIds(get_library=catalog.get_library),
            libraries=CatalogNewLibraries(
                create_library=catalog.create_library, discard_library=catalog.discard_library
            ),
            sources=CatalogLibrarySources(
                get_library=catalog.get_library, list_renames=catalog.list_renames
            ),
            removals=CatalogRemovals(
                version_remover=catalog.remove_version, library_remover=catalog.remove_library
            ),
            index=index,
            vault=vault,
            # The catalog first: retrieval keeps every manifest the catalog still knows.
            handlers=traced_jobs(
                settings,
                {
                    **handlers,
                    **collect_job(
                        collectors=[
                            CatalogCollector(collect_garbage=catalog.collect_garbage),
                            RetrievalCollector(collect_chunks=retrieval.collect_chunks),
                        ]
                    ),
                },
            ),
            recovery_hooks=recovery_hooks,
            manual_tags=CatalogManualTags(set_manual_tags=catalog.set_manual_tags),
            tag_locks=tag_locks,
            settings=CatalogLibrarySettings(set_library_settings=catalog.set_library_settings),
            runner=DbosJobQueue(),
            auto_syncs=SqliteAutoSyncStore(engine=engine),
            schedule_switch=DbosScheduleSwitch(SCHEDULE),
        )
        return cls(
            settings=settings,
            engine=engine,
            catalog=catalog,
            identity=IdentityModule.build(
                repository=SqliteAccountRepository(engine=engine),
                sessions=SqliteSessionRepository(engine=engine),
                tokens=SqliteTokenRepository(engine=engine),
                hasher=Argon2idPasswordHasher(),
                failures=InMemoryFailedSignInLog(),
                clock=SystemClock(),
            ),
            ingestion=ingestion,
            retrieval=retrieval,
            job_worker=DbosJobWorker(
                run_job=ingestion.run_job,
                recover_jobs=ingestion.recover_jobs,
                submit_queued_jobs=ingestion.submit_queued_jobs,
                run_scheduled_checks=ingestion.run_scheduled_checks,
                switch_schedule=ingestion.switch_schedule,
                schedule_name=SCHEDULE,
                schedule=settings.auto_sync_schedule,
                poll_interval=settings.job_poll_seconds,
                database=settings.data_dir / JOBS_FILE,
                queue=QUEUE,
                workflow=WORKFLOW,
                version=STEPS_VERSION,
                engine_options={"poolclass": NullPool},
            ),
        )

    @asynccontextmanager
    async def running(self, *, jobs: bool = True) -> AsyncGenerator[None]:
        """Migrate the database, serve, then release the connections.

        ``jobs`` also runs the job worker (and the recovery before it). Only the HTTP server
        does: one process runs jobs.

        A container runs once at a time: a second run would share the engine, and whichever
        stopped first would dispose it under the other, stranding the connections the other had
        checked out (a job worker's poll). ``RuntimeError`` refuses it; the app's lifespan is
        such a run, so a container whose app is served is not run on its own as well.
        """
        if not self._run.acquire(blocking=False):
            message = "this container is already running; run it once (or through its app)"
            raise RuntimeError(message)
        try:
            await migrate(self.engine)
            index = await self.retrieval.get_search_index_state()
            if index.needs_rebuild:
                stored = (
                    "has no recorded format"
                    if index.stored_format is None
                    else f"is in format {index.stored_format}"
                )
                logger.warning(
                    "The search index %s; this version writes format %s. It keeps answering as "
                    "it was built; `exactdocs reindex` rebuilds it while serving.",
                    stored,
                    index.current_format,
                )
            if jobs:
                # Fetch folders a crash left behind. A data dir has exactly one job runner.
                await asyncio.to_thread(sweep_stale_fetches, self.settings.data_dir / WORK_DIR)
                async with self.job_worker.running():
                    yield
            else:
                yield
        finally:
            try:
                await self.engine.dispose()
            finally:
                self._run.release()
