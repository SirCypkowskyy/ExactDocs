import asyncio
import logging
import os
import signal
import threading
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self

import httpx2
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.ai_models import (
    AiEmbeddingModels,
    AiModels,
    ConfiguredAi,
    PydanticAiModels,
    configured_ai,
)
from exactdocs.bootstrap.bridges import (
    CatalogActiveManifests,
    CatalogArticleSuggestions,
    CatalogArticleTitles,
    CatalogCollector,
    CatalogDefaultVersions,
    CatalogImportedTags,
    CatalogInstructionFiles,
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
    CatalogVersionArticles,
    CatalogVersionCopier,
    CatalogVersionPublisher,
    RetrievalChunkIndex,
    RetrievalCollector,
    RetrievalGuidancePolicy,
    RetrievalVersionEmbedder,
)
from exactdocs.bootstrap.cancellation import being_cancelled
from exactdocs.bootstrap.constants import (
    AGENT_CACHE_PURPOSE,
    AI_KEYS_PURPOSE,
    CREDENTIALS_KEY_PURPOSE,
    HYDE_CACHE_PURPOSE,
    JOBS_FILE,
    KEY_FILE,
    KNOWN_HOSTS_FILE,
    LOCAL_PROFILE,
    LOCAL_PROFILE_HINT,
    SIGN_IN_TOKENS_PURPOSE,
    UPKEEP_RECANCEL_SECONDS,
    UPKEEP_STOP_SECONDS,
    WORK_DIR,
)
from exactdocs.bootstrap.database import (
    ClosingQueuePool,
    StartupError,
    check_schema_is_current,
    is_postgres,
    migrate,
    open_database,
    open_spend_ledger_database,
    warn_unless_session,
)
from exactdocs.bootstrap.embedding import SaveProviderThenEmbed, requeue_daily
from exactdocs.bootstrap.executors import PostgresExecutorSlots
from exactdocs.bootstrap.local_models import LocalModels
from exactdocs.bootstrap.repo_guidance import SetRetrievalThenReprocess
from exactdocs.bootstrap.search_engine import PostgresSearchChoice
from exactdocs.bootstrap.secret_box import FernetSecretBox, derived_key, read_key_file
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import (
    SignInStandIns,
    revalidating,
    sign_in_client,
    sign_in_providers,
)
from exactdocs.bootstrap.telemetry import agent_reads as telemetry_agent_reads
from exactdocs.bootstrap.telemetry import search_tracer, traced_jobs
from exactdocs.bootstrap.workdirs import held, new_work_root, sweep_abandoned_work
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.adapters.driven.sqlite import (
    SqliteArticleTitles,
    SqliteImportedTags,
    SqliteInstructionFiles,
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
    SqliteExternalIdentityRepository,
    SqliteFailedSignInLog,
    SqliteSessionRepository,
    SqliteSignInAttemptRepository,
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
    RepositoryFiles,
    RepositoryTree,
)
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.adapters.driven.ai_explorer import PydanticAiExplorer
from exactdocs.retrieval.adapters.driven.ai_hyde import PydanticAiHypotheticalAnswers
from exactdocs.retrieval.adapters.driven.ai_judge import PydanticAiCandidateJudge
from exactdocs.retrieval.adapters.driven.genai_prices import GenaiPrices
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryCallRates,
    ReadOnlyAgentAnswerCache,
    ReadOnlyHypothesisCache,
    ReadOnlySpendLedger,
)
from exactdocs.retrieval.adapters.driven.pg_search import PgSearchIndex
from exactdocs.retrieval.adapters.driven.postgres_fts import PostgresSearchIndex
from exactdocs.retrieval.adapters.driven.postgres_vectors import PostgresVectorIndex
from exactdocs.retrieval.adapters.driven.sqlite import (
    SqliteAgentAnswerCache,
    SqliteChunkRepository,
    SqliteHypothesisCache,
    SqliteLibraryModes,
    SqliteProviderProfiles,
    SqliteSpendLedger,
)
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs.retrieval.adapters.driven.sqlite_vectors import SqliteVectorIndex
from exactdocs.retrieval.constants import (
    PG_SEARCH_QUIET_SCANS,
)
from exactdocs.retrieval.models import (
    AgentBounds,
    ModelRole,
    ProviderKind,
    ProviderProfile,
    RerankLimits,
    RetrievalMode,
)
from exactdocs.retrieval.ports.driven import (
    AgentAnswerCache,
    AgentReads,
    EmbeddingModels,
    HypotheticalAnswerCache,
    ModelFactory,
    ModelRoles,
    RetrievalPipeline,
    SpendLedger,
)
from exactdocs.retrieval.ports.driving import SaveProvider, SetLibraryRetrieval
from exactdocs.retrieval.use_cases import PriceBook
from exactdocs_kernel import Clock, DomainError, SystemClock

logger = logging.getLogger(__name__)


type LocalRoles = tuple[tuple[ProviderProfile, ModelRole, str], ...]
"""The instance roles on ``local`` profiles: ``(profile, role, model)``."""


def _ai_configuration(
    settings: Settings, local: LocalModels, probe: ModelFactory | None = None
) -> ConfiguredAi:
    """Read the AI profiles and roles of the environment and the TOML file, refusing bad ones.

    A role on a ``local`` profile whose model is not in the models directory is turned off, with
    an error naming ``exactdocs models pull``: it is never downloaded (#245).

    Args:
        settings: The runtime configuration.
        local: Knows which local models were pulled (reading their markers only).
        probe: The model factory the instance calls models with, which says what it cannot call;
            the instance's own by default (tests and the eval suite pass the one they build with).

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
    probe = probe or AiModels(local=local)
    for profile in configured.profiles:
        if (reason := probe.unsupported(profile)) is not None:
            message = f"AI provider {profile.name!r}: {reason}"
            raise StartupError(message)
    _warn_undeclared_local(configured)
    roles = configured.roles
    for profile, role, model in _local_roles(configured):
        if (reason := local.missing(model, role)) is not None:
            logger.error("AI role %s (%s:%s) is off: %s", role.value, profile.name, model, reason)
            roles = replace(roles, **{role.value: None})
    configured = replace(configured, roles=roles)
    if configured.budgets.limits_usd:
        _require_prices(configured)  # a local model is free: priced at 0, its tokens counted
    return configured


def _warn_undeclared_local(configured: ConfiguredAi) -> None:
    """Warn about roles that name a profile ``local`` the configuration does not declare.

    ``local:BAAI/bge-small-en-v1.5`` needs a profile named ``local`` of kind ``local``; without
    one the role resolves only to a profile of that name stored over the REST API, if any.

    Args:
        configured: The configuration.
    """
    if any(p.name == LOCAL_PROFILE for p in configured.profiles):
        return
    for role in ModelRole:
        ref = configured.roles.explicit(role)
        if ref is not None and ref.profile == LOCAL_PROFILE:
            logger.warning(
                "AI role %s names profile %r, which is not configured: set %s to run the model "
                "in this process (a profile of that name stored over the REST API is used "
                "otherwise, if there is one)",
                role.value,
                LOCAL_PROFILE,
                LOCAL_PROFILE_HINT,
            )


def _rerank_limits(settings: Settings) -> RerankLimits:
    """Read the reranker's limits; an unset timeout is resolved per search by the reranker's kind.

    Retrieval gives a reranker on a ``local`` profile ``LOCAL_RERANK_TIMEOUT``, whether the
    instance's role or a library's override names it (#284).

    Args:
        settings: The runtime configuration.

    Returns:
        The limits.
    """
    return RerankLimits(
        top_n=settings.ai.reranker.top_n,
        timeout=settings.ai.reranker.timeout,
        judge_timeout=settings.ai.judge.timeout,
    )


def _local_roles(configured: ConfiguredAi) -> LocalRoles:
    """List the instance roles set to a model of a configured ``local`` profile.

    Args:
        configured: The configuration.

    Returns:
        ``(profile, role, model)`` of each.
    """
    local = {p.name: p for p in configured.profiles if p.kind is ProviderKind.LOCAL}
    return tuple(
        (local[ref.profile], role, ref.model)
        for role in ModelRole
        if (ref := configured.roles.explicit(role)) is not None and ref.profile in local
    )


def _require_prices(configured: ConfiguredAi) -> None:
    """Refuse a US dollar budget while a configured model has no known price.

    Its spend could not be counted in dollars, so the budget would never stop it. Profiles
    stored over the REST API are not known before the database is read; their models count as
    unpriced (``unpriced`` in the usage) until a price is configured.

    Args:
        configured: The AI configuration.

    Raises:
        StartupError: A role's model is neither in the bundled price list nor in
            ``[ai.prices]``.
    """
    book = PriceBook(listed=GenaiPrices(), overrides=configured.prices)
    kinds = {profile.name: profile.kind.value for profile in configured.profiles}
    for role in ModelRole:
        ref = configured.roles.explicit(role)
        if ref is None or ref.profile not in kinds:
            continue
        if book.price(ref, kinds[ref.profile]) is None:
            message = (
                f"a US dollar budget is set, but the price of {ref} ({role.value}) is unknown: "
                f'set [ai.prices."{ref}"] input_usd_per_mtok and output_usd_per_mtok '
                "(EXACTDOCS_AI__PRICES__...), or use token budgets"
            )
            raise StartupError(message)


async def _warm_ai(retrieval: RetrievalModule, local: LocalModels, local_roles: LocalRoles) -> None:
    """Load the provider SDKs and the local models in worker threads at start.

    That is when a provider profile other than ``local`` exists (configured, or stored over the
    REST API): every role, the instance's or a library's own, names an existing profile, and
    ``local`` models (#245) need none of these SDKs. The first search that calls a model would
    otherwise import them (seconds) inside its reranker timeout. With no such profile nothing is
    loaded (RUN-02). A failed load never stops the start (``PydanticAiModels.warm``). The models
    the instance roles name on ``local`` profiles are loaded too (fastembed, once per process);
    a role a library sets on a local profile loads its model at its first call.

    Args:
        retrieval: Lists the provider profiles (reading them imports no SDK).
        local: Loads the local models.
        local_roles: The instance roles on local profiles whose model was pulled.
    """
    profiles = (await retrieval.list_providers()).providers
    if any(p.kind is not ProviderKind.LOCAL for p in profiles):
        await PydanticAiModels().warm()
    await local.warm(local_roles)


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


@dataclass(frozen=True, slots=True, kw_only=True)
class _Identity:
    """The identity domain, wired, with the HTTP client its identity providers use."""

    module: IdentityModule
    """The domain."""
    client: httpx2.AsyncClient | None
    """Calls the identity providers; ``None`` when none is configured."""


def _identity(settings: Settings, engine: AsyncEngine, stand_ins: SignInStandIns) -> _Identity:
    """Wire the identity domain, with the configured identity providers.

    Args:
        settings: The runtime configuration.
        engine: The database.
        stand_ins: Replace the domain's time and the providers' network (tests).

    Returns:
        The module, and the providers' HTTP client.
    """
    clock = stand_ins.clock or SystemClock()
    client = sign_in_client(stand_ins.transport) if settings.auth.providers else None
    providers, policies = sign_in_providers(settings, client, clock) if client else ({}, {})
    identity = IdentityModule.build(
        repository=SqliteAccountRepository(engine=engine),
        sessions=SqliteSessionRepository(engine=engine),
        tokens=SqliteTokenRepository(engine=engine),
        hasher=Argon2idPasswordHasher(),
        # Shared by every process on PostgreSQL; one process serves on SQLite.
        failures=SqliteFailedSignInLog(engine=engine)
        if is_postgres(engine)
        else InMemoryFailedSignInLog(),
        externals=SqliteExternalIdentityRepository(engine=engine),
        attempts=SqliteSignInAttemptRepository(engine=engine),
        box=_secret_box(settings, SIGN_IN_TOKENS_PURPOSE),
        clock=clock,
        providers=providers,
        policies=policies,
    )
    return _Identity(module=identity, client=client)


def _hyde_cache_key(settings: Settings, *, create: bool) -> bytes | None:
    """Derive the HMAC key of HyDE's cache from the instance's secret key (its own purpose).

    Args:
        settings: The runtime configuration.
        create: Generate the key file when there is none (never in a read-only process).

    Returns:
        The key, or ``None`` when there is no secret key and none may be created.
    """
    return _cache_key(settings, HYDE_CACHE_PURPOSE, create=create)


def _agent_cache_key(settings: Settings, *, create: bool) -> bytes | None:
    """Derive the HMAC key of the agentic answer cache (its own purpose), if the cache is on.

    Args:
        settings: The runtime configuration.
        create: Generate the key file when there is none (never in a read-only process).

    Returns:
        The key, or ``None`` when the cache is off, or there is no secret key and none may be
        created.
    """
    if not settings.ai.agentic_cache.enabled:
        return None
    return _cache_key(settings, AGENT_CACHE_PURPOSE, create=create)


def _cache_key(settings: Settings, purpose: bytes, *, create: bool) -> bytes | None:
    """Derive a cache's HMAC key from the instance's secret key, for its own purpose.

    Args:
        settings: The runtime configuration.
        purpose: The HKDF context of the cache.
        create: Generate the key file when there is none (never in a read-only process).

    Returns:
        The key, or ``None`` when there is no secret key and none may be created.

    Raises:
        StartupError: The key or the key file is unusable.
    """
    try:
        if settings.secret_key:
            return derived_key(settings.secret_key.get_secret_value(), purpose)
        path = settings.data_dir / KEY_FILE
        if not create and not path.is_file():
            return None
        return derived_key(read_key_file(path), purpose)
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


def vector_index(
    engine: AsyncEngine, *, sqlite_extension: Callable[[], str] | None = None
) -> PostgresVectorIndex | SqliteVectorIndex:
    """Pick the vector store of the database: pgvector on PostgreSQL, sqlite-vec on SQLite.

    Neither loads anything here: the store is asked whether it can search only once an embedding
    model is configured.

    Args:
        engine: The database.
        sqlite_extension: Finds sqlite-vec's loadable extension (tests: one that cannot load).

    Returns:
        The store.
    """
    if is_postgres(engine):
        return PostgresVectorIndex(engine=engine)
    if sqlite_extension is None:
        return SqliteVectorIndex(engine=engine)
    return SqliteVectorIndex(engine=engine, extension=sqlite_extension)


def _log_late_failure(task: asyncio.Task[None]) -> None:
    """Read the failure of an upkeep the stop left behind, so it is logged, not left unread.

    Args:
        task: The upkeep, done.
    """
    if not task.cancelled() and (error := task.exception()) is not None:
        logger.warning("the nightly upkeep left behind failed", exc_info=error)


@dataclass(frozen=True, slots=True, kw_only=True)
class _ReadSide:
    """The modules the read-only MCP tools use, and on PostgreSQL the search engine to choose."""

    catalog: CatalogModule
    """The catalog."""
    retrieval: RetrievalModule
    """Retrieval."""
    search_choice: PostgresSearchChoice | None
    """On PostgreSQL: the search engine, chosen once the schema is migrated."""
    local: LocalModels
    """Runs the ``local`` profiles' models."""
    local_roles: LocalRoles
    """The instance roles on local profiles, loaded at start."""


def _build_read_side(
    engine: AsyncEngine,
    settings: Settings,
    *,
    ai_box: FernetSecretBox | None,
    hyde_key: bytes | None = None,
    agent_cache_key: bytes | None = None,
    model_roles: ModelRoles | None = None,
    pipelines: Mapping[RetrievalMode, RetrievalPipeline] | None = None,
    vector_extension: Callable[[], str] | None = None,
    model_factory: ModelFactory | None = None,
    embedding_models: EmbeddingModels | None = None,
    read_only: bool = False,
    spend_engine: AsyncEngine | None = None,
    clock: Clock | None = None,
    agent_reads: AgentReads | None = None,
) -> _ReadSide:
    """Build the catalog and retrieval modules: everything the read-only MCP tools use.

    Args:
        engine: The database.
        settings: The runtime configuration.
        ai_box: Seals and opens the provider keys stored over the REST API; ``None``: none can be
            stored or opened.
        hyde_key: The HMAC key of the queries in HyDE's cache; ``None``: nothing is cached.
        agent_cache_key: The HMAC key of the questions in the agentic answer cache; ``None``:
            nothing is cached.
        model_roles: Stands in for the role resolution over the configured profiles (tests).
        pipelines: Retrieval modes beside BM25 (tests, until the AI modes are built).
        vector_extension: Finds sqlite-vec's loadable extension (tests: one that cannot load).
        model_factory: Builds the models instead of pydantic-ai (tests and the eval suite).
        embedding_models: Wraps the embedder instead of pydantic-ai (tests and the eval suite:
            an in-process embedding, so no provider is called).
        read_only: The database is opened read-only (``serve --stdio``): spend is read from it,
            written over ``spend_engine``, and kept in memory when that fails.
        spend_engine: With ``read_only``, the one engine that may write: the spend ledger's.
        clock: Decides the spend windows (tests); the system clock by default.
        agent_reads: Records the agentic explorer's reads (the eval suite's trace check); by
            default span events when telemetry is on, else nothing.

    Returns:
        The two modules (``StartupError`` when the AI configuration is invalid), and on
        PostgreSQL the search engine to choose at start.
    """
    local = LocalModels(models_dir=settings.effective_models_dir)
    ai = _ai_configuration(settings, local, model_factory)
    catalog = CatalogModule.build(
        repository=SqliteLibraryRepository(engine=engine),
        manifests=SqliteManifestRepository(engine=engine),
        imported_tags=SqliteImportedTags(engine=engine),
        stored_articles=SqliteStoredArticles(engine=engine),
        copier=SqliteManifestCopier(engine=engine),
        article_titles=SqliteArticleTitles(engine=engine),
        instruction_files=SqliteInstructionFiles(engine=engine),
    )
    choice = None
    search: SqliteSearchIndex | PostgresSearchChoice = SqliteSearchIndex(engine=engine)
    if is_postgres(engine):
        # The same rows either way; under pg_search, indexing a chunk set asks for no join scan.
        quiet = PostgresSearchIndex(engine=engine, write_settings=PG_SEARCH_QUIET_SCANS)
        choice = search = PostgresSearchChoice(
            full_text=PostgresSearchIndex(engine=engine),
            bm25=PgSearchIndex(engine=engine, table=quiet),
        )
    vectors = vector_index(engine, sqlite_extension=vector_extension)
    spend: SpendLedger = SqliteSpendLedger(engine=engine)
    hypotheses: HypotheticalAnswerCache = SqliteHypothesisCache(engine=engine)
    answers: AgentAnswerCache = SqliteAgentAnswerCache(engine=engine)
    if read_only:
        writer = None if spend_engine is None else SqliteSpendLedger(engine=spend_engine)
        spend = ReadOnlySpendLedger(shared=spend, writer=writer)
        hypotheses = ReadOnlyHypothesisCache(shared=hypotheses)
        answers = ReadOnlyAgentAnswerCache(shared=answers)
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
        models=model_factory
        or AiModels(remote=PydanticAiModels(keys=ai.keys, box=ai_box), local=local),
        secret_box=ai_box,
        instance_mode=settings.ai.mode,
        rerank_limits=_rerank_limits(settings),
        rerank_with=settings.ai.rerank_with,
        judge=PydanticAiCandidateJudge(ledger=spend),
        pipelines=pipelines,
        suggestions=CatalogArticleSuggestions(get_article=catalog.get_article),
        query_docs_token_budget=settings.query_docs_token_budget,
        tracer=search_tracer(settings),
        vectors=vectors,
        embedding_models=embedding_models or AiEmbeddingModels(),
        article_titles=CatalogArticleTitles(get_article_titles=catalog.get_article_titles),
        spend=spend,
        prices=GenaiPrices(),
        price_overrides=ai.prices,
        budgets=ai.budgets,
        call_rates=InMemoryCallRates(),
        clock=clock,
        embedding_dimensions=settings.ai.embedding.dimensions,
        embedding_batch_size=settings.ai.embedding.batch_size,
        explorer=PydanticAiExplorer(),
        version_articles=CatalogVersionArticles(
            list_articles=catalog.list_articles, get_article=catalog.get_article
        ),
        agent_bounds=AgentBounds(**settings.ai.agentic.model_dump()),
        agent_reads=agent_reads or telemetry_agent_reads(settings),
        hypotheses=PydanticAiHypotheticalAnswers(ledger=spend),
        hypothesis_cache=hypotheses,
        hyde_cache_key=hyde_key,
        hyde_cache_ttl=settings.ai.hyde.cache_ttl,
        agent_answer_cache=answers,
        agent_cache_key=agent_cache_key,
        agent_cache_enabled=settings.ai.agentic_cache.enabled,
        agent_cache_threshold=settings.ai.agentic_cache.threshold,
        agent_cache_scope=settings.ai.agentic_cache.scope,
        agent_cache_ttl=settings.ai.agentic_cache.ttl,
        instruction_files=CatalogInstructionFiles(
            get_instruction_files=catalog.get_instruction_files
        ),
    )
    return _ReadSide(
        catalog=catalog,
        retrieval=retrieval,
        search_choice=choice,
        local=local,
        local_roles=_local_roles(ai),
    )


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


def _with_system_git(
    settings: Settings,
    engine: AsyncEngine,
    remote: GitRemote | None,
    gateway: GitGateway | None,
    renames: RenameSource | None,
    tree: RepositoryTree | None,
    files: RepositoryFiles | None,
) -> tuple[
    GitRemote, GitGateway, RenameSource | None, RepositoryTree, RepositoryFiles, Path | None
]:
    """Fill in the git adapters a caller did not hand in with the system ``git``.

    Args:
        settings: The instance's settings.
        engine: The app's database.
        remote: Lists refs, if given.
        gateway: Fetches repositories, if given (then renames are only detected when
            ``renames`` is given too).
        renames: Detects renamed articles, if given.
        tree: Reads one commit's tree, if given.
        files: Reads instruction files, if given.

    Returns:
        The adapters, then the work folder ``running()`` holds on PostgreSQL (else ``None``).
    """
    git, work_owner = _system_git(settings, engine)
    return (
        remote or git,
        gateway or git,
        renames or (git if gateway is None else None),
        tree or git,
        files or git,
        work_owner,
    )


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
            # A connection one of DBOS's threads returns after DBOS stopped is closed (#333).
            "engine_options": {"poolclass": ClosingQueuePool},
        }
    # NullPool: a connection one of DBOS's threads still holds when it stops is closed.
    return {"database": settings.data_dir / JOBS_FILE, "engine_options": {"poolclass": NullPool}}


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadOnlyContainer:
    """Catalog and retrieval over an existing database opened read-only (``serve --stdio``).

    No identity, ingestion, worker, secret key, ``known_hosts`` or ``git``: nothing here can write
    but the AI spend ledger, over its own engine (#274).
    """

    settings: Settings
    """The runtime configuration (which AI roles to load the SDKs for at start)."""
    engine: AsyncEngine
    """The database, opened read-only."""
    spend_engine: AsyncEngine = field(repr=False)
    """Writes the AI spend ledger and nothing else (``open_spend_ledger_database``)."""
    catalog: CatalogModule
    """The catalog domain, wired."""
    retrieval: RetrievalModule
    """The retrieval domain, wired."""
    search_choice: PostgresSearchChoice | None = field(default=None, repr=False)
    """On PostgreSQL: the search engine, chosen in ``running()``."""
    local: LocalModels = field(repr=False)
    """Runs the ``local`` profiles' models."""
    local_roles: LocalRoles = field(default=(), repr=False)
    """The instance roles on local profiles, loaded at start."""
    _run: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    """Held for the duration of ``running()``, which runs once at a time."""

    @classmethod
    def build(cls, settings: Settings) -> Self:
        """Open the database read-only; ``StartupError`` when it does not exist.

        Args:
            settings: The runtime configuration.

        Returns:
            The container, not running yet.
        """
        engine = open_database(settings, read_only=True)
        spend_engine = open_spend_ledger_database(settings)
        # Opens the provider keys stored over the REST API when a key exists; never creates one.
        ai_box = _existing_secret_box(settings, AI_KEYS_PURPOSE)
        read = _build_read_side(
            engine,
            settings,
            ai_box=ai_box,
            hyde_key=_hyde_cache_key(settings, create=False),
            agent_cache_key=_agent_cache_key(settings, create=False),
            read_only=True,
            spend_engine=spend_engine,
        )
        return cls(
            settings=settings,
            engine=engine,
            spend_engine=spend_engine,
            catalog=read.catalog,
            retrieval=read.retrieval,
            search_choice=read.search_choice,
            local=read.local,
            local_roles=read.local_roles,
        )

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[None]:
        """Check the schema is current (no migration), serve, then release the connections.

        Runs once at a time, like ``Container.running()``: ``RuntimeError`` otherwise.

        Yields:
            Control while the container serves.

        Raises:
            RuntimeError: The container is already running.
        """
        if not self._run.acquire(blocking=False):
            message = "this container is already running; run it once"
            raise RuntimeError(message)
        try:
            await check_schema_is_current(self.engine)
            if self.search_choice is not None:  # it may not make the BM25 index: it only reads
                await self.search_choice.choose(create=False)
            await _warm_ai(self.retrieval, self.local, self.local_roles)
            yield
        finally:
            try:
                self.local.close()  # queued local model calls are dropped, not waited for
                try:
                    await self.engine.dispose()
                finally:
                    await self.spend_engine.dispose()
            finally:
                self._run.release()


@dataclass(frozen=True, slots=True, kw_only=True)
class Container:
    """Every domain module, wired. Built once per process."""

    settings: Settings
    """The runtime configuration."""
    engine: AsyncEngine
    """The database."""
    catalog: CatalogModule
    """The catalog domain, wired."""
    identity: IdentityModule
    """The identity domain, wired."""
    ingestion: IngestionModule
    """The ingestion domain, wired."""
    retrieval: RetrievalModule
    """The retrieval domain, wired."""
    job_worker: DbosJobWorker
    """Runs the queued jobs (imports, syncs, embeddings) in ``running(jobs=True)``."""
    save_provider: SaveProvider
    """Retrieval's ``save_provider``, then the embedding queued when the embedding role's profile
    changed (REST ``/ai/providers``)."""
    set_library_retrieval: SetLibraryRetrieval
    """Retrieval's ``set_library_retrieval``, then a ``reprocess`` queued when the library's repo
    guidance was turned on (REST ``/libraries/{owner}/{repo}/retrieval``)."""
    work_owner: Path | None = field(default=None, repr=False)
    """On PostgreSQL: this process's own work folder, held (``workdirs.held``) while it runs."""
    search_choice: PostgresSearchChoice | None = field(default=None, repr=False)
    """On PostgreSQL: the search engine, chosen in ``running()`` once the schema is migrated."""
    local: LocalModels = field(repr=False)
    """Runs the ``local`` profiles' models."""
    local_roles: LocalRoles = field(default=(), repr=False)
    """The instance roles on local profiles, loaded at start."""
    sign_in_client: httpx2.AsyncClient | None = field(default=None, repr=False)
    """Calls the identity providers; ``None`` when none is configured. Closed by ``running()``."""
    _run: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    """Held for the duration of ``running()``: a lock, so a run in another thread (a
    TestClient's event loop) is refused as well.
    """

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        remote: GitRemote | None = None,
        gateway: GitGateway | None = None,
        renames: RenameSource | None = None,
        tree: RepositoryTree | None = None,
        files: RepositoryFiles | None = None,
        chunker: Chunker | None = None,
        model_roles: ModelRoles | None = None,
        pipelines: Mapping[RetrievalMode, RetrievalPipeline] | None = None,
        vector_extension: Callable[[], str] | None = None,
        model_factory: ModelFactory | None = None,
        embedding_models: EmbeddingModels | None = None,
        clock: Clock | None = None,
        agent_reads: AgentReads | None = None,
        sign_in: SignInStandIns | None = None,
    ) -> Self:
        """Choose driven adapters and connect domains through bridges.

        Creates the data directory (``StartupError`` when it is unusable) but opens no
        connection; ``running()`` migrates the schema and releases the engine afterwards.
        An invalid AI configuration (or one this installation cannot call) is a
        ``StartupError``. A missing ``git`` is logged here and reported as
        ``git_not_installed`` by everything that needs it, so the rest still runs. Every
        argument but ``settings`` replaces a production adapter, for tests and the eval suite.

        Args:
            settings: The runtime configuration.
            remote: Lists a repository's refs instead of the system ``git``.
            gateway: Fetches repositories instead of the system ``git``; it detects no renames
                unless ``renames`` is given too.
            renames: Detects renamed articles instead of the system ``git``.
            tree: Looks at one commit's tree without a checkout (previews) instead of the system
                ``git``.
            files: Reads instruction files instead of the system ``git``.
            chunker: Replaces the Markdown chunker.
            model_roles: Stands in for the role resolution over the configured AI profiles.
            pipelines: Stand in for the AI retrieval modes.
            vector_extension: Finds sqlite-vec's extension (tests: one that cannot load).
            model_factory: Replaces pydantic-ai's model construction.
            embedding_models: Replace pydantic-ai's embedding models (the eval suite: an
                in-process one).
            clock: Decides retrieval's spend windows.
            agent_reads: Records the agentic explorer's reads (the eval suite's trace check).
            sign_in: Replace the identity domain's time and the identity providers' network.

        Returns:
            The container, not running yet.
        """
        engine = open_database(settings)  # creates the data dir first (or says why not)
        _require_shared_key(settings, engine)
        work_owner = None
        if remote is None or gateway is None or tree is None:
            # The system `git` stands in for every git adapter a test did not hand in.
            remote, gateway, renames, tree, files, work_owner = _with_system_git(
                settings, engine, remote, gateway, renames, tree, files
            )
        vault = SqliteCredentialVault(
            engine=engine, box=_secret_box(settings, CREDENTIALS_KEY_PURPOSE)
        )
        read = _build_read_side(
            engine,
            settings,
            ai_box=_secret_box(settings, AI_KEYS_PURPOSE),
            hyde_key=_hyde_cache_key(settings, create=True),
            agent_cache_key=_agent_cache_key(settings, create=True),
            model_roles=model_roles,
            pipelines=pipelines,
            vector_extension=vector_extension,
            model_factory=model_factory,
            embedding_models=embedding_models,
            clock=clock,
            agent_reads=agent_reads,
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
            guidance=RetrievalGuidancePolicy(
                get_library_retrieval=read.retrieval.get_library_retrieval
            ),
            files=files,
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
        identity = _identity(settings, engine, sign_in or SignInStandIns())
        return cls(
            settings=settings,
            engine=engine,
            work_owner=work_owner,
            sign_in_client=identity.client,
            search_choice=read.search_choice,
            local=read.local,
            local_roles=read.local_roles,
            catalog=read.catalog,
            identity=identity.module,
            ingestion=ingestion,
            retrieval=read.retrieval,
            save_provider=SaveProviderThenEmbed(
                save_provider=read.retrieval.save_provider,
                queue_embedding=ingestion.queue_embedding,
            ),
            set_library_retrieval=SetRetrievalThenReprocess(
                get_library_retrieval=read.retrieval.get_library_retrieval,
                set_library_retrieval=read.retrieval.set_library_retrieval,
                enqueue_job=ingestion.enqueue_job,
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
        """Queue the missing embedding in the background while the block runs, and every day.

        A start never waits for the coverage of every version; stopping cancels what is left
        and waits for it at most ``UPKEEP_STOP_SECONDS``, then cancels it again and waits at most
        ``UPKEEP_RECANCEL_SECONDS`` more, then stops without it (logged): its connection may then
        outlive the engine, and a late failure of it is logged, not left unread.
        Then the queueing runs again just after each UTC midnight, when the day's (and on the
        first, the month's) spend windows reset: a version an exhausted budget left unembedded
        (its job stopped with ``ai_budget_reached``) is retried then.

        Yields:
            Nothing: the block runs while the queueing goes on.
        """
        queueing = asyncio.create_task(self._queue_embedding_daily())
        try:
            yield
        finally:
            queueing.cancel()
            # Bounded: an upkeep that does not stop (#308) must not hold the server's stop.
            done, _ = await asyncio.wait({queueing}, timeout=UPKEEP_STOP_SECONDS)
            if not done:
                logger.warning(
                    "the nightly upkeep did not stop within %s s; cancelling it again",
                    UPKEEP_STOP_SECONDS,
                )
                queueing.cancel()  # e.g. it caught the first while releasing its connection
                done, _ = await asyncio.wait({queueing}, timeout=UPKEEP_RECANCEL_SECONDS)
            if not done:
                queueing.add_done_callback(_log_late_failure)
                logger.warning(
                    "the nightly upkeep did not stop after a second cancellation; the server "
                    "stops without it, and its connection may outlive the engine"
                )
            elif not queueing.cancelled() and (error := queueing.exception()) is not None:
                logger.warning("the nightly upkeep failed while it stopped", exc_info=error)

    async def _queue_embedding_daily(self) -> None:
        """Run the nightly upkeep now, then after every UTC midnight (one process does)."""
        await self.nightly()
        await requeue_daily(engine=self.engine, queue=self.nightly)

    async def nightly(self) -> None:
        """Queue the missing embedding, then prune HyDE's and the agentic answer cache.

        Each part is logged on failure and never stops the other or the server. A failure while
        the server stops (it cancels this) is raised instead, so the upkeep ends (#308).
        """
        await self.queue_embedding()
        try:
            await self.retrieval.prune_hypotheses()
        except Exception:
            if being_cancelled():  # the error replaced the server's stop: stop all the same
                raise
            logger.exception("pruning the answer caches failed; it runs again tomorrow")

    async def queue_embedding(self) -> None:
        """Queue the embedding of every version the configured model has not embedded.

        A new or changed embedding model, or versions imported while none was configured, are
        embedded in the background from here. No model is called: only the stored spaces are
        read. A failure is logged and never stops the start (BM25 answers meanwhile); one while
        the server stops (it cancels this) is raised instead, so the upkeep ends (#308).
        """
        try:
            queued = await self.ingestion.queue_embedding(QueueEmbeddingCommand())
        except Exception:
            if being_cancelled():  # the error replaced the server's stop: stop all the same
                raise
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

        Args:
            jobs: Also run the job worker, and the recovery before it.

        Yields:
            Control while the container serves.

        Raises:
            RuntimeError: The container is already running.
        """
        if not self._run.acquire(blocking=False):
            message = "this container is already running; run it once (or through its app)"
            raise RuntimeError(message)
        try:
            await migrate(self.engine)
            await warn_unless_session(self.engine)  # a transaction-mode pooler (#279)
            if self.search_choice is not None:
                await self.search_choice.choose(create=True)
            await _warm_ai(self.retrieval, self.local, self.local_roles)
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
                    async with (
                        self.job_worker.running(),
                        self._embedding_queued(),
                        revalidating(
                            self.identity.revalidate_external_accounts,
                            every=self.settings.auth.revalidate_poll_seconds,
                        ),
                    ):
                        yield
                else:
                    yield
        finally:
            try:
                self.local.close()  # queued local model calls are dropped, not waited for
                if self.sign_in_client is not None:
                    await self.sign_in_client.aclose()
                await self.engine.dispose()
            finally:
                self._run.release()
