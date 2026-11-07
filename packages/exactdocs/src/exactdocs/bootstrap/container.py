import asyncio
import logging
import os
import signal
import threading
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager, nullcontext, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.ai_models import ConfiguredAi, PydanticAiModels, configured_ai
from exactdocs.bootstrap.bridges import (
    CatalogActiveManifests,
    CatalogArticleSuggestions,
    CatalogArticleTitles,
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
    RetrievalVersionEmbedder,
)
from exactdocs.bootstrap.constants import (
    AI_KEYS_PURPOSE,
    CREDENTIALS_KEY_PURPOSE,
    JOBS_FILE,
    KEY_FILE,
    KNOWN_HOSTS_FILE,
    WORK_DIR,
)
from exactdocs.bootstrap.database import (
    StartupError,
    check_schema_is_current,
    is_postgres,
    migrate,
    open_database,
)
from exactdocs.bootstrap.embedding import SaveProviderThenEmbed
from exactdocs.bootstrap.executors import PostgresExecutorSlots
from exactdocs.bootstrap.search_engine import PostgresSearchChoice
from exactdocs.bootstrap.secret_box import FernetSecretBox
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.telemetry import search_tracer, traced_jobs
from exactdocs.bootstrap.workdirs import held, new_work_root, sweep_abandoned_work
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.adapters.driven.sqlite import (
    SqliteArticleTitles,
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
from exactdocs.ingestion.adapters.driven.postgres import PostgresLibraryLocks
from exactdocs.ingestion.adapters.driven.sqlite import (
    SqliteAutoSyncStore,
    SqliteCredentialVault,
    SqliteJobRepository,
)
from exactdocs.ingestion.adapters.driving.dbos_worker import DbosJobWorker
from exactdocs.ingestion.constants import QUEUE, SCHEDULE, STEPS_VERSION, WORKFLOW
from exactdocs.ingestion.dtos import QueueEmbeddingCommand
from exactdocs.ingestion.errors import GitNotInstalledError
from exactdocs.ingestion.ports.driven import (
    Chunker,
    GitGateway,
    GitRemote,
    LibraryLocks,
    RenameSource,
    RepositoryTree,
)
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.adapters.driven.ai_embeddings import PydanticAiEmbeddingModels
from exactdocs.retrieval.adapters.driven.genai_prices import GenaiPrices
from exactdocs.retrieval.adapters.driven.pg_search import PgSearchIndex
from exactdocs.retrieval.adapters.driven.postgres_fts import PostgresSearchIndex
from exactdocs.retrieval.adapters.driven.sqlite import (
    SqliteChunkRepository,
    SqliteLibraryModes,
    SqliteProviderProfiles,
    SqliteSpendLedger,
)
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs.retrieval.adapters.driven.sqlite_vectors import SqliteVectorIndex
from exactdocs.retrieval.models import RetrievalMode
from exactdocs.retrieval.ports.driven import ModelRoles, RetrievalPipeline
from exactdocs.retrieval.ports.driving import SaveProvider
from exactdocs_kernel import DomainError, SystemClock

logger = logging.getLogger(__name__)


def _ai_configuration(settings: Settings) -> ConfiguredAi:
    """Read the AI profiles and roles of the environment and the TOML file, refusing bad ones.

    Args:
        settings: The runtime configuration.

    Returns:
        The configuration.

    Raises:
        StartupError: A profile or a role is invalid, or this installation cannot call a profile
            (the ``[ai]`` extra is missing, ...).
    """
    try:
        configured = configured_ai(settings.ai)
    except DomainError as error:  # fixed texts and names: never a key
        raise StartupError(str(error)) from None
    probe = PydanticAiModels()
    for profile in configured.profiles:
        if (reason := probe.unsupported(profile)) is not None:
            message = f"AI provider {profile.name!r}: {reason}"
            raise StartupError(message)
    return configured


def _secret_box(settings: Settings, purpose: bytes) -> FernetSecretBox:
    """Build the secret box of one purpose from ``EXACTDOCS_SECRET_KEY`` or the key file.

    Args:
        settings: The runtime configuration.
        purpose: The HKDF context of this use.

    Returns:
        The box; the key file is generated when there is none.

    Raises:
        StartupError: The key or the key file is unusable.
    """
    try:
        if settings.secret_key:
            previous = settings.secret_key_previous
            return FernetSecretBox.from_secrets(
                settings.secret_key.get_secret_value(),
                *([previous.get_secret_value()] if previous else []),
                purpose=purpose,
            )
        return FernetSecretBox.from_file(settings.data_dir / KEY_FILE, purpose=purpose)
    except ValueError as error:  # fixed texts: they never repeat a key
        raise StartupError(str(error)) from None


def _existing_secret_box(settings: Settings, purpose: bytes) -> FernetSecretBox | None:
    """Build the secret box only when a key exists (read-only processes never create one).

    Args:
        settings: The runtime configuration.
        purpose: The HKDF context of this use.

    Returns:
        The box, or ``None`` without ``EXACTDOCS_SECRET_KEY`` and without a key file.
    """
    if settings.secret_key or (settings.data_dir / KEY_FILE).is_file():
        return _secret_box(settings, purpose)
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class _ReadSide:
    """The modules the read-only MCP tools use, and on PostgreSQL the search engine to choose."""

    catalog: CatalogModule
    """The catalog."""
    retrieval: RetrievalModule
    """Retrieval."""
    search_choice: PostgresSearchChoice | None
    """On PostgreSQL: the search engine, chosen once the schema is migrated."""


def _build_read_side(
    engine: AsyncEngine,
    settings: Settings,
    *,
    ai_box: FernetSecretBox | None,
    model_roles: ModelRoles | None = None,
    pipelines: Mapping[RetrievalMode, RetrievalPipeline] | None = None,
    vector_extension: Callable[[], str] | None = None,
) -> _ReadSide:
    """Build the catalog and retrieval modules: everything the read-only MCP tools use.

    Args:
        engine: The database.
        settings: The runtime configuration.
        ai_box: Seals and opens the provider keys stored over the REST API; ``None``: none can be
            stored or opened.
        model_roles: Stands in for the role resolution over the configured profiles (tests).
        pipelines: Retrieval modes beside BM25 (tests, until the AI modes are built).
        vector_extension: Finds sqlite-vec's loadable extension (tests: one that cannot load).

    Returns:
        The two modules (``StartupError`` when the AI configuration is invalid), and on
        PostgreSQL the search engine to choose at start.
    """
    ai = _ai_configuration(settings)
    catalog = CatalogModule.build(
        repository=SqliteLibraryRepository(engine=engine),
        manifests=SqliteManifestRepository(engine=engine),
        imported_tags=SqliteImportedTags(engine=engine),
        stored_articles=SqliteStoredArticles(engine=engine),
        copier=SqliteManifestCopier(engine=engine),
        article_titles=SqliteArticleTitles(engine=engine),
    )
    choice = None
    search: SqliteSearchIndex | PostgresSearchChoice = SqliteSearchIndex(engine=engine)
    if is_postgres(engine):
        full_text = PostgresSearchIndex(engine=engine)
        choice = search = PostgresSearchChoice(
            full_text=full_text, bm25=PgSearchIndex(engine=engine, table=full_text)
        )
    # On PostgreSQL there is no vector store yet (pgvector is #243): the hybrid modes report
    # themselves unavailable and fall back to BM25, as without an embedding model.
    vectors = (
        None
        if is_postgres(engine)
        else SqliteVectorIndex(engine=engine)
        if vector_extension is None
        else SqliteVectorIndex(engine=engine, extension=vector_extension)
    )
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
        configured_profiles=ai.profiles,
        stored_profiles=SqliteProviderProfiles(engine=engine),
        instance_roles=ai.roles,
        models=PydanticAiModels(keys=ai.keys, box=ai_box),
        secret_box=ai_box,
        instance_mode=settings.ai.mode,
        pipelines=pipelines,
        suggestions=CatalogArticleSuggestions(get_article=catalog.get_article),
        query_docs_token_budget=settings.query_docs_token_budget,
        tracer=search_tracer(settings),
        vectors=vectors,
        embedding_models=PydanticAiEmbeddingModels(),
        article_titles=CatalogArticleTitles(get_article_titles=catalog.get_article_titles),
        spend=SqliteSpendLedger(engine=engine),
        prices=GenaiPrices(),
        embedding_dimensions=settings.ai.embedding.dimensions,
        embedding_batch_size=settings.ai.embedding.batch_size,
    )
    return _ReadSide(catalog=catalog, retrieval=retrieval, search_choice=choice)


def _system_git(settings: Settings, engine: AsyncEngine) -> tuple[GitCli | MissingGit, Path | None]:
    """Return the system ``git`` (or ``MissingGit``, logged) and this process's work folder.

    On SQLite fetches work in ``<data dir>/work``; on PostgreSQL, where processes may share the
    data directory, in a folder of this process's own (``workdirs.py``).

    Args:
        settings: The instance's settings.
        engine: The app's database.

    Returns:
        The git adapter, and on PostgreSQL the work folder ``running()`` holds (else ``None``).
    """
    work_root, owner = settings.data_dir / WORK_DIR, None
    if is_postgres(engine):
        work_root = owner = new_work_root(work_root)
    try:
        seed_known_hosts(settings.data_dir / KNOWN_HOSTS_FILE)
        git: GitCli | MissingGit = GitCli.locate(
            work_root=work_root, known_hosts=settings.data_dir / KNOWN_HOSTS_FILE
        )
    except GitNotInstalledError as exc:
        logger.warning("%s", exc)
        git = MissingGit()
    return git, owner


def _require_shared_key(settings: Settings, engine: AsyncEngine) -> None:
    """Refuse PostgreSQL without ``EXACTDOCS_SECRET_KEY``.

    Each process would otherwise generate its own ``secret.key``, and credentials one sealed
    could not be opened by the others.

    Args:
        settings: The instance's settings.
        engine: The app's database.

    Raises:
        StartupError: On PostgreSQL without a configured key.
    """
    if is_postgres(engine) and settings.secret_key is None:
        message = (
            "On PostgreSQL every ExactDocs process must seal private repositories' "
            "credentials with the same key: set EXACTDOCS_SECRET_KEY (at least 32 random "
            "characters, e.g. `openssl rand -base64 32`) for all of them."
        )
        raise StartupError(message)


def _library_locks(engine: AsyncEngine, purpose: str) -> LibraryLocks:
    """Return per-library locks for one purpose (``tags``, ``settings``).

    On PostgreSQL they are advisory locks every process shares; on SQLite one process runs jobs
    and serves the API, so ``asyncio`` locks are enough.

    Args:
        engine: The app's database.
        purpose: What the locks order; each purpose has its own.

    Returns:
        The locks.
    """
    if is_postgres(engine):
        return PostgresLibraryLocks(engine=engine, purpose=purpose)
    return TagLocks()


def _stop_this_process() -> None:
    """Stop the server as ``SIGTERM`` does: another process took this one's executor slot.

    The orchestrator (or the operator) starts it again, and it takes a free slot then.
    """
    os.kill(os.getpid(), signal.SIGTERM)


def _dbos_database(settings: Settings, engine: AsyncEngine) -> dict[str, Any]:
    """Return where DBOS keeps its workflows: the app's PostgreSQL database, or its SQLite file.

    On PostgreSQL DBOS uses the same database, in a schema of its own (it never creates a
    database), and each process takes an executor slot. On SQLite it keeps ``jobs.sqlite``.

    Args:
        settings: The instance's settings.
        engine: The app's database.

    Returns:
        The job worker's database arguments.
    """
    if is_postgres(engine):
        return {
            "system_database_url": engine.url.render_as_string(hide_password=False),
            "system_schema": settings.dbos_system_schema,
            "executors": PostgresExecutorSlots(engine=engine, schema=settings.dbos_system_schema),
            "on_slot_lost": _stop_this_process,
        }
    # NullPool: a connection one of DBOS's threads still holds when it stops is closed.
    return {"database": settings.data_dir / JOBS_FILE, "engine_options": {"poolclass": NullPool}}


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadOnlyContainer:
    """Catalog and retrieval over an existing database opened read-only (``serve --stdio``).

    No identity, ingestion, worker, secret key, ``known_hosts`` or ``git``: nothing here can write.
    """

    engine: AsyncEngine
    catalog: CatalogModule
    retrieval: RetrievalModule
    search_choice: PostgresSearchChoice | None = field(default=None, repr=False)
    """On PostgreSQL: the search engine, chosen in ``running()``."""
    _run: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def build(cls, settings: Settings) -> Self:
        """Open the database read-only; ``StartupError`` when it does not exist."""
        engine = open_database(settings, read_only=True)
        # Opens the provider keys stored over the REST API when a key exists; never creates one.
        ai_box = _existing_secret_box(settings, AI_KEYS_PURPOSE)
        read = _build_read_side(engine, settings, ai_box=ai_box)
        return cls(
            engine=engine,
            catalog=read.catalog,
            retrieval=read.retrieval,
            search_choice=read.search_choice,
        )

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
            if self.search_choice is not None:  # it may not make the BM25 index: it only reads
                await self.search_choice.choose(create=False)
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
    save_provider: SaveProvider
    """Retrieval's ``save_provider``, then the embedding queued when the embedding role's profile
    changed (REST ``/ai/providers``)."""
    work_owner: Path | None = field(default=None, repr=False)
    """On PostgreSQL: this process's own work folder, held (``workdirs.held``) while it runs."""
    search_choice: PostgresSearchChoice | None = field(default=None, repr=False)
    """On PostgreSQL: the search engine, chosen in ``running()`` once the schema is migrated."""
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
        vector_extension: Callable[[], str] | None = None,
    ) -> Self:
        """Choose driven adapters and connect domains through bridges.

        Creates the data directory (``StartupError`` when it is unusable) but opens no
        connection; ``running()`` migrates the schema and releases the engine afterwards.
        ``remote``, ``gateway`` and ``renames`` replace the system ``git`` for listing refs, for
        fetching and for detecting renames (tests; a given ``gateway`` detects none unless
        ``renames`` is given too); ``chunker`` replaces the Markdown chunker (tests);
        ``model_roles`` stands in for the role resolution over the configured AI profiles and
        ``pipelines`` for the AI retrieval modes (tests); ``vector_extension`` finds sqlite-vec's
        extension (tests: one that cannot load). An invalid AI configuration (or one this
        installation cannot call) is a ``StartupError``. A missing
        ``git`` is logged here and reported as ``git_not_installed`` by everything that needs
        it, so the rest still runs.
        """
        engine = open_database(settings)  # creates the data dir first (or says why not)
        _require_shared_key(settings, engine)
        work_owner = None
        if remote is None or gateway is None or tree is None:
            git, work_owner = _system_git(settings, engine)
            remote = remote or git
            renames = renames or (git if gateway is None else None)
            gateway = gateway or git
            tree = tree or git
        vault = SqliteCredentialVault(
            engine=engine, box=_secret_box(settings, CREDENTIALS_KEY_PURPOSE)
        )
        read = _build_read_side(
            engine,
            settings,
            ai_box=_secret_box(settings, AI_KEYS_PURPOSE),
            model_roles=model_roles,
            pipelines=pipelines,
            vector_extension=vector_extension,
        )
        index = RetrievalChunkIndex(
            index_manifest=read.retrieval.index_manifest,
            get_chunk_sets=read.retrieval.get_chunk_sets,
            discard_pending_chunks=read.retrieval.discard_pending_chunks,
            remove_chunks=read.retrieval.remove_chunks,
            retag_articles=read.retrieval.retag_articles,
        )
        tag_locks = _library_locks(engine, "tags")  # tagging and activations take turns
        handlers, recovery_hooks = import_job(
            gateway=gateway,
            chunker=chunker or MarkdownChunker(),
            sources=CatalogLibrarySources(
                get_library=read.catalog.get_library, list_renames=read.catalog.list_renames
            ),
            versions=CatalogVersionPublisher(
                store_manifest=read.catalog.store_manifest,
                activate_manifest=read.catalog.activate_manifest,
                discard_pending_manifests=read.catalog.discard_pending_manifests,
                apply_readme=read.catalog.apply_readme,
                apply_manual_tags_to=read.catalog.apply_manual_tags,
                replace_renames_of=read.catalog.replace_renames,
            ),
            index=index,
            vault=vault,
            max_article_bytes=settings.max_article_bytes,
            max_import_bytes=settings.max_import_bytes,
            renames=renames,
            stored=CatalogStoredArticles(find_stored_articles=read.catalog.find_stored_articles),
            max_image_bytes=settings.max_image_bytes,
            max_images_bytes=settings.max_images_bytes,
            checkpoints=DbosCheckpoints(),
            batch_files=settings.import_batch_files,
            tag_locks=tag_locks,
            imported_tags=CatalogImportedTags(
                get_version_tags=read.catalog.get_version_tags,
                set_imported_tags_of=read.catalog.set_imported_tags,
            ),
            copier=CatalogVersionCopier(copy_manifest=read.catalog.copy_manifest),
        )
        ingestion = IngestionModule.build(
            jobs=SqliteJobRepository(engine=engine),
            clock=SystemClock(),
            remote=remote,
            tree=tree,
            library_ids=CatalogLibraryIds(get_library=read.catalog.get_library),
            libraries=CatalogNewLibraries(
                create_library=read.catalog.create_library,
                discard_library=read.catalog.discard_library,
            ),
            sources=CatalogLibrarySources(
                get_library=read.catalog.get_library, list_renames=read.catalog.list_renames
            ),
            removals=CatalogRemovals(
                version_remover=read.catalog.remove_version,
                library_remover=read.catalog.remove_library,
                forget_library=read.retrieval.forget_library,
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
                            CatalogCollector(collect_garbage=read.catalog.collect_garbage),
                            RetrievalCollector(collect_chunks=read.retrieval.collect_chunks),
                        ]
                    ),
                },
            ),
            recovery_hooks=recovery_hooks,
            manual_tags=CatalogManualTags(set_manual_tags=read.catalog.set_manual_tags),
            tag_locks=tag_locks,
            settings_locks=_library_locks(engine, "settings"),
            settings=CatalogLibrarySettings(set_library_settings=read.catalog.set_library_settings),
            runner=DbosJobQueue(),
            auto_syncs=SqliteAutoSyncStore(engine=engine),
            schedule_switch=DbosScheduleSwitch(SCHEDULE),
            embedder=RetrievalVersionEmbedder(
                plan_embedding=read.retrieval.plan_embedding,
                embed_batch_of=read.retrieval.embed_batch,
                finish_embedding=read.retrieval.finish_embedding,
                list_unembedded_versions=read.retrieval.list_unembedded_versions,
            ),
            checkpoints=DbosCheckpoints(),
        )
        return cls(
            settings=settings,
            engine=engine,
            work_owner=work_owner,
            search_choice=read.search_choice,
            catalog=read.catalog,
            identity=IdentityModule.build(
                repository=SqliteAccountRepository(engine=engine),
                sessions=SqliteSessionRepository(engine=engine),
                tokens=SqliteTokenRepository(engine=engine),
                hasher=Argon2idPasswordHasher(),
                failures=InMemoryFailedSignInLog(),
                clock=SystemClock(),
            ),
            ingestion=ingestion,
            retrieval=read.retrieval,
            save_provider=SaveProviderThenEmbed(
                save_provider=read.retrieval.save_provider,
                queue_embedding=ingestion.queue_embedding,
            ),
            job_worker=DbosJobWorker(
                run_job=ingestion.run_job,
                recover_jobs=ingestion.recover_jobs,
                submit_queued_jobs=ingestion.submit_queued_jobs,
                run_scheduled_checks=ingestion.run_scheduled_checks,
                switch_schedule=ingestion.switch_schedule,
                schedule_name=SCHEDULE,
                schedule=settings.auto_sync_schedule,
                poll_interval=settings.job_poll_seconds,
                queue=QUEUE,
                workflow=WORKFLOW,
                version=STEPS_VERSION,
                **_dbos_database(settings, engine),
            ),
        )

    @asynccontextmanager
    async def _embedding_queued(self) -> AsyncGenerator[None]:
        """Queue the missing embedding in the background while the block runs.

        A start never waits for the coverage of every version; stopping cancels what is left.

        Yields:
            Nothing: the block runs while the queueing goes on.
        """
        queueing = asyncio.create_task(self._queue_embedding())
        try:
            yield
        finally:
            queueing.cancel()
            with suppress(asyncio.CancelledError):
                await queueing

    async def _queue_embedding(self) -> None:
        """Queue the embedding of every version the configured model has not embedded.

        A new or changed embedding model, or versions imported while none was configured, are
        embedded in the background from here. No model is called: only the stored spaces are
        read. A failure is logged and never stops the start (BM25 answers meanwhile).
        """
        try:
            queued = await self.ingestion.queue_embedding(QueueEmbeddingCommand())
        except Exception:
            logger.exception("could not queue the embedding of the versions not embedded yet")
            return
        if queued.queued:
            logger.info("%d versions are being embedded in the background", queued.queued)

    @asynccontextmanager
    async def running(self, *, jobs: bool = True) -> AsyncGenerator[None]:
        """Migrate the database, serve, then release the connections.

        ``jobs`` also runs the job worker (and the recovery before it). Only the HTTP server
        does: on SQLite one process runs jobs; on PostgreSQL every server process does.

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
            if self.search_choice is not None:
                await self.search_choice.choose(create=True)
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
            with held(self.work_owner) if self.work_owner else nullcontext():
                if jobs:
                    # Fetch folders a crash left behind: on SQLite this process is the data dir's
                    # one job runner; on PostgreSQL only the folders of processes that are gone.
                    sweep = sweep_abandoned_work if self.work_owner else sweep_stale_fetches
                    await asyncio.to_thread(sweep, self.settings.data_dir / WORK_DIR)
                    async with self.job_worker.running(), self._embedding_queued():
                        yield
                else:
                    yield
        finally:
            try:
                await self.engine.dispose()
            finally:
                self._run.release()
