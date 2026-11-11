import os
import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from croniter import croniter
from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from exactdocs.bootstrap.constants import (
    LOCAL_HOSTS,
    MODELS_SUBDIR,
    POSTGRES_DRIVER,
    POSTGRES_DRIVERS,
    SECRETS_REFUSED_IN_FILE,
    SETTINGS_FILE_VARIABLE,
)
from exactdocs.retrieval.constants import (
    DEFAULT_AGENT_CACHE_TTL_DAYS,
    DEFAULT_AGENT_REPEATED_CALLS,
    DEFAULT_AGENT_REQUESTS,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_AGENT_TOKENS,
    DEFAULT_AGENT_TOOL_CALLS,
    DEFAULT_EMBEDDING_BATCH,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RERANK_TOP_N,
    DEFAULT_RETRIES,
    DEFAULT_SANDBOX_MEMORY,
    DEFAULT_SANDBOX_SECONDS,
    DEFAULT_SANDBOX_SUSPENSIONS,
    HYDE_CACHE_TTL_DAYS,
    MAX_AGENT_REPEATED_CALLS,
    MAX_AGENT_REQUESTS,
    MAX_AGENT_TIMEOUT,
    MAX_AGENT_TOKENS,
    MAX_AGENT_TOOL_CALLS,
    MAX_EMBEDDING_BATCH,
    MAX_EMBEDDING_DIMENSIONS,
    MAX_RERANK_TIMEOUT,
    MAX_RERANK_TOP_N,
    MAX_SANDBOX_MEMORY,
    MAX_SANDBOX_SECONDS,
    MAX_SANDBOX_SUSPENSIONS,
    MIN_AGENT_REPEATED_CALLS,
    SANDBOX_NOT_BELOW_TIMEOUT,
)
from exactdocs.retrieval.models import AnthropicPlatform, AzureAuth, RetrievalMode


class ProviderSettings(BaseModel):
    """A provider profile: ``EXACTDOCS_AI__PROVIDERS__<NAME>__<FIELD>``, ``[ai.providers.<name>]``.

    See docs/decisions/ai-retrieval.md (*Provider abstraction*) for what each kind needs. The
    TOML file may not hold ``api_key``: use ``api_key_file`` or the environment.
    """

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True, extra="forbid")

    kind: str
    """`openai-compatible`, `openai`, `openrouter`, `anthropic`, `azure`, `google-vertex`,
    `google`, `ollama`, `vllm`, `litellm`, `local`, or one of pydantic-ai's OpenAI-API providers.
    """
    base_url: str | None = None
    """The endpoint; required for `openai-compatible`, `ollama`, `vllm`, `litellm` and `azure`."""
    api_key: SecretStr | None = None
    """The key (environment only, never the TOML file)."""
    api_key_file: Path | None = None
    """A file holding the key (Docker and Kubernetes secrets), read at every call."""
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    """Extra headers of every call (masked in logs, never shown). No credentials: `Authorization`,
    `Cookie`, `*-key`, `*-token` and the like are refused; use `api_key` or `api_key_file`.
    """
    proxy: str | None = None
    """An HTTP(S) proxy for this profile only; the environment's proxy variables are not read."""
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    """Overall timeout of one call, in seconds."""
    max_retries: int = DEFAULT_RETRIES
    """Retries of one call (the SDK's: the one retry layer)."""
    api_version: str | None = None
    """Azure OpenAI's API version."""
    project: str | None = None
    """Google Cloud project (`google-vertex`, `anthropic` with `platform = "vertex"`)."""
    location: str | None = None
    """Google Cloud location, or the AWS region of Claude on Bedrock."""
    credentials_file: Path | None = None
    """A Google service-account file (configuration only; the endpoint is then Google's own)."""
    credentials: Literal["adc"] | None = None
    """`adc`: Google Application Default Credentials, used only when set here."""
    platform: AnthropicPlatform | None = None
    """`anthropic` only: `api` (default), `vertex`, `foundry` or `bedrock` (needs boto3)."""
    auth: AzureAuth | None = None
    """`azure`, and `anthropic` on `foundry`: `key` (default) or `entra` (Entra ID)."""
    resource: str | None = None
    """Azure OpenAI or Claude on Azure AI Foundry: the resource name, instead of `base_url`."""

    @field_validator(
        "api_key",
        "api_key_file",
        "base_url",
        "proxy",
        "api_version",
        "project",
        "location",
        "credentials_file",
        "resource",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Treat a blank value as unset (``EXACTDOCS_AI__PROVIDERS__X__BASE_URL=``).

        Args:
            value: The raw value.

        Returns:
            ``None`` for blank text, otherwise the value unchanged.
        """
        return None if isinstance(value, str) and not value.strip() else value


class RoleSettings(BaseModel):
    """One model role: ``EXACTDOCS_AI__<ROLE>__MODEL`` or ``[ai.<role>]``.

    Fields a later issue reads are accepted and kept for it; nothing reads them yet.
    """

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True, extra="allow")

    model: str | None = None
    """`<profile>:<model>`, e.g. `corp:gpt-4.1-mini`."""


class RerankerSettings(RoleSettings):
    """The reranker role: ``EXACTDOCS_AI__RERANKER__<FIELD>`` or ``[ai.reranker]`` (RET-02)."""

    top_n: int = Field(default=DEFAULT_RERANK_TOP_N, ge=1, le=MAX_RERANK_TOP_N)
    """`EXACTDOCS_AI__RERANKER__TOP_N`: how many of a search's best candidates are reranked (a
    library may set its own)."""
    timeout: float | None = Field(default=None, gt=0, le=MAX_RERANK_TIMEOUT)
    """`EXACTDOCS_AI__RERANKER__TIMEOUT`: seconds a search gives the reranker, to be built and to
    answer (reading the candidates' text is not counted). Unset: 2 s, or 5 s when the reranker
    runs on a `local` profile (a CPU is slower); after that, or on any reranker error,
    results keep their order (`reranked: false`, `fallback_reason` `reranker_timeout` or
    `reranker_failed`)."""


class EmbeddingRoleSettings(RoleSettings):
    """The embedding role (``EXACTDOCS_AI__EMBEDDING__...`` or ``[ai.embedding]``)."""

    dimensions: int | None = Field(default=None, ge=1, le=MAX_EMBEDDING_DIMENSIONS)
    """`EXACTDOCS_AI__EMBEDDING__DIMENSIONS`: ask the model for vectors of this size (models that
    can shorten theirs, such as OpenAI's `text-embedding-3-*`). Unset: the model's own size, asked
    once with a fixed text. A change makes a new embedding space: every version is embedded again.
    """
    batch_size: int = Field(default=DEFAULT_EMBEDDING_BATCH, ge=1, le=MAX_EMBEDDING_BATCH)
    """`EXACTDOCS_AI__EMBEDDING__BATCH_SIZE`: chunks per embedding call, and per durable step of a
    version's background `embed` job."""


class BudgetSettings(BaseModel):
    """Spend limits and the LLM search rate limit (``EXACTDOCS_AI__BUDGETS__*``, ``[ai.budgets]``).

    Unset: no limit. Windows are UTC days and months.
    The instance's limits count every AI call (embedding runs too); per-library and per-user
    limits apply to each library and each account (the API token's or the session's) on its own;
    the embedding limits only to embedding runs. Reaching one skips the LLM step or the rerank
    (the search answers in a cheaper mode and says why) and pauses embedding until the window
    resets. A US dollar limit needs a price for every configured model.
    """

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True, extra="forbid")

    daily_usd: float | None = Field(default=None, gt=0)
    """The instance's US dollars per day."""
    monthly_usd: float | None = Field(default=None, gt=0)
    """The instance's US dollars per month."""
    daily_tokens: int | None = Field(default=None, ge=1)
    """The instance's tokens per day."""
    monthly_tokens: int | None = Field(default=None, ge=1)
    """The instance's tokens per month."""
    per_library_daily_usd: float | None = Field(default=None, gt=0)
    """Each library's US dollars per day."""
    per_library_monthly_usd: float | None = Field(default=None, gt=0)
    """Each library's US dollars per month."""
    per_library_daily_tokens: int | None = Field(default=None, ge=1)
    """Each library's tokens per day."""
    per_library_monthly_tokens: int | None = Field(default=None, ge=1)
    """Each library's tokens per month."""
    per_user_daily_usd: float | None = Field(default=None, gt=0)
    """Each account's US dollars per day (a stdio MCP process has none)."""
    per_user_monthly_usd: float | None = Field(default=None, gt=0)
    """Each account's US dollars per month."""
    per_user_daily_tokens: int | None = Field(default=None, ge=1)
    """Each account's tokens per day."""
    per_user_monthly_tokens: int | None = Field(default=None, ge=1)
    """Each account's tokens per month."""
    daily_embedding_usd: float | None = Field(default=None, gt=0)
    """Embedding runs' US dollars per day, instance-wide."""
    monthly_embedding_usd: float | None = Field(default=None, gt=0)
    """Embedding runs' US dollars per month, instance-wide."""
    daily_embedding_tokens: int | None = Field(default=None, ge=1)
    """Embedding runs' tokens per day, instance-wide."""
    monthly_embedding_tokens: int | None = Field(default=None, ge=1)
    """Embedding runs' tokens per month, instance-wide."""
    llm_searches_per_minute: int | None = Field(default=None, ge=1)
    """LLM searches each caller may make per minute (REST, HTTP MCP and stdio alike); more
    answer without the LLM step (`fallback_reason` `llm_rate_limited`). Per server process."""


class AgenticSettings(BaseModel):
    """The agentic mode's limits per search (``EXACTDOCS_AI__AGENTIC__*``, ``[ai.agentic]``).

    Passing any of them ends the agent's run, and the search answers with the best mode without an
    LLM step (`fallback_reason` `agent_limit_reached`; `agent_loop_detected` for a repeated
    call). Spend budgets apply on top of them.
    """

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True, extra="forbid")

    max_tool_calls: int = Field(default=DEFAULT_AGENT_TOOL_CALLS, ge=1, le=MAX_AGENT_TOOL_CALLS)
    """Read-tool calls per search, `run_code` itself included."""
    max_requests: int = Field(default=DEFAULT_AGENT_REQUESTS, ge=1, le=MAX_AGENT_REQUESTS)
    """Model requests per search."""
    max_tokens: int = Field(default=DEFAULT_AGENT_TOKENS, ge=1, le=MAX_AGENT_TOKENS)
    """Input and output tokens per search."""
    sandbox_seconds: float = Field(default=DEFAULT_SANDBOX_SECONDS, gt=0, le=MAX_SANDBOX_SECONDS)
    """Execution time of each `run_code` snippet in the Monty sandbox (waiting for a tool does not
    count); less than `timeout`."""
    sandbox_memory: int = Field(default=DEFAULT_SANDBOX_MEMORY, ge=1, le=MAX_SANDBOX_MEMORY)
    """Heap of each snippet, in bytes."""
    sandbox_suspensions: int = Field(
        default=DEFAULT_SANDBOX_SUSPENSIONS, ge=1, le=MAX_SANDBOX_SUSPENSIONS
    )
    """Host interactions (tool calls, name lookups) of the sandbox per search."""
    timeout: float = Field(default=DEFAULT_AGENT_TIMEOUT, gt=0, le=MAX_AGENT_TIMEOUT)
    """Seconds one agentic search may take, model calls included, before it falls back. A snippet
    running then stops at its own `sandbox_seconds`, so a search can last up to `timeout` plus
    `sandbox_seconds`."""
    max_repeated_calls: int = Field(
        default=DEFAULT_AGENT_REPEATED_CALLS,
        ge=MIN_AGENT_REPEATED_CALLS,
        le=MAX_AGENT_REPEATED_CALLS,
    )
    """The agent making the same call (tool and arguments) this many times in one search is
    looping: the run ends and the search falls back with `agent_loop_detected`."""

    @model_validator(mode="after")
    def _snippet_shorter_than_run(self) -> Self:
        """Refuse a snippet time as long as the whole run's.

        Returns:
            The settings.

        Raises:
            ValueError: `sandbox_seconds` is not less than `timeout`.
        """
        if self.sandbox_seconds >= self.timeout:
            raise ValueError(SANDBOX_NOT_BELOW_TIMEOUT)
        return self


class PriceSettings(BaseModel):
    """A model's price, for one the bundled price list does not know: ``[ai.prices."p:m"]``."""

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True, extra="forbid")

    input_usd_per_mtok: float = Field(ge=0)
    """US dollars per million input tokens."""
    output_usd_per_mtok: float = Field(default=0.0, ge=0)
    """US dollars per million output tokens."""


class HydeSettings(BaseModel):
    """HyDE (``EXACTDOCS_AI__HYDE__<FIELD>`` or ``[ai.hyde]``, #94)."""

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True)

    cache_ttl: timedelta = Field(default=timedelta(days=HYDE_CACHE_TTL_DAYS), gt=timedelta(0))
    """`EXACTDOCS_AI__HYDE__CACHE_TTL`: how long a cached hypothetical answer is kept (seconds or
    an ISO 8601 duration such as `P30D`); the collection job deletes older ones, and those of an
    `llm` model no longer configured."""


class AgenticCacheSettings(BaseModel):
    """The agentic answer cache (``EXACTDOCS_AI__AGENTIC_CACHE__<FIELD>``, ``[ai.agentic_cache]``).

    A question similar enough to one answered agentically before, for the same version (manifest),
    tag filter, `llm` model and agentic limits, is answered from the earlier answer (`cache_hit`),
    re-checked against the version and the filter. Questions are compared with the embedding
    model when one is configured (hybrid: embeddings and words), else by their words (#100).
    """

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True, extra="forbid")

    enabled: bool | None = None
    """`EXACTDOCS_AI__AGENTIC_CACHE__ENABLED`: unset, the cache is on only when an embedding model
    is configured; `true` turns it on with words alone too; `false` turns it off, and the nightly
    upkeep then deletes every cached answer."""
    threshold: float | None = Field(default=None, gt=0, le=1)
    """`EXACTDOCS_AI__AGENTIC_CACHE__THRESHOLD`: how similar (0 to 1) a question must be to a cached
    one asked again (the same content terms and guards, or it never matches); 1 reuses only the
    same question (case and spacing aside). With an embedding model the score is the lower of
    the words' similarity and the embeddings' cosine, which only confirms. Unset: 0.8 with an
    embedding model, 0.9 with words alone."""
    scope: Literal["library", "caller"] = "library"
    """`EXACTDOCS_AI__AGENTIC_CACHE__SCOPE`: `library`, every caller of a library's version shares
    the cached answers (one caller's answer, the model's justifications included, can be served to
    another); `caller`, each caller is answered from their own questions only."""
    ttl: timedelta = Field(default=timedelta(days=DEFAULT_AGENT_CACHE_TTL_DAYS), gt=timedelta(0))
    """`EXACTDOCS_AI__AGENTIC_CACHE__TTL`: how long a cached answer is kept (seconds or an ISO 8601
    duration such as `P7D`); the nightly upkeep deletes older ones."""


class AiSettings(BaseModel):
    """The ``ai`` section: AI retrieval, read from ``EXACTDOCS_AI__<FIELD>`` variables."""

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True)

    mode: RetrievalMode | None = None
    """`EXACTDOCS_AI__MODE`: the retrieval mode of every search that names none, for libraries
    without their own: `bm25`, `hybrid`, `hybrid_hyde` or `agentic`. Unset (or `auto`): the best
    default mode the configured models allow: BM25 until the eval suite makes another mode a
    default (docs/evals.md). A mode whose model is not configured falls back to
    the best one, and the results say so (`fallback_reason` `mode_unavailable`).
    """

    providers: dict[str, ProviderSettings] = Field(default_factory=dict)
    """Named provider profiles (`EXACTDOCS_AI__PROVIDERS__<NAME>__...`); read-only over REST."""
    embedding: EmbeddingRoleSettings = Field(default_factory=EmbeddingRoleSettings)
    """The embedding role, instance-wide only (`EXACTDOCS_AI__EMBEDDING__MODEL`)."""
    reranker: RerankerSettings = Field(default_factory=RerankerSettings)
    """The reranker role (`EXACTDOCS_AI__RERANKER__MODEL`, `__TOP_N`, `__TIMEOUT`)."""
    llm: RoleSettings = Field(default_factory=RoleSettings)
    """The LLM role (`EXACTDOCS_AI__LLM__MODEL`)."""
    judge: RoleSettings = Field(default_factory=RoleSettings)
    """The judge role (`EXACTDOCS_AI__JUDGE__MODEL`); the LLM role when unset."""
    hyde: HydeSettings = Field(default_factory=HydeSettings)
    """HyDE's cache (`EXACTDOCS_AI__HYDE__CACHE_TTL`)."""
    budgets: BudgetSettings = Field(default_factory=BudgetSettings)
    """Spend limits and the LLM search rate limit (`EXACTDOCS_AI__BUDGETS__...`)."""
    agentic: AgenticSettings = Field(default_factory=AgenticSettings)
    """The agentic mode's limits per search (`EXACTDOCS_AI__AGENTIC__MAX_TOOL_CALLS`, ...)."""
    agentic_cache: AgenticCacheSettings = Field(default_factory=AgenticCacheSettings)
    """The agentic answer cache (`EXACTDOCS_AI__AGENTIC_CACHE__THRESHOLD`, `__TTL`, `__ENABLED`)."""
    prices: dict[str, PriceSettings] = Field(default_factory=dict)
    """Prices by `<profile>:<model>`, overriding the bundled list (`[ai.prices."corp:m"]`)."""

    @field_validator("mode", mode="before")
    @classmethod
    def _mode_any_case(cls, value: object) -> object:
        """Read the mode in any letter case; blank and ``auto`` count as unset.

        Args:
            value: The raw setting.

        Returns:
            The mode name in lower case, or ``None``.
        """
        if isinstance(value, str):
            name = value.strip().lower()
            return None if name in {"", "auto"} else name
        return value


def _default_data_dir() -> Path:
    return user_data_path("exactdocs", appauthor=False)


class Settings(BaseSettings):
    """Runtime configuration, read from ``EXACTDOCS_*`` environment variables (and a ``.env``)."""

    model_config = SettingsConfigDict(
        use_attribute_docstrings=True,
        env_prefix="EXACTDOCS_",
        # `EXACTDOCS_AI__MODE` is `ai.mode`, as the `ai` section of the decision record wants.
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    host: str = "127.0.0.1"
    port: int = 3000
    # Docker sets EXACTDOCS_DATA_DIR=/data; `uvx` uses the platform user-data directory.
    data_dir: Path = Field(default_factory=_default_data_dir)
    database_url: str | None = None
    """Overrides the SQLite file in the data directory: another SQLite file
    (`sqlite:////srv/exactdocs.db`) or a PostgreSQL database
    (`postgresql+psycopg://user:password@host:5432/exactdocs`, `postgresql://` means the same).
    Several server processes can share a PostgreSQL database; a SQLite one has one server.
    """
    models_dir: Path | None = None
    """Where local models live (`exactdocs models pull` writes them, `local` profiles read them;
    default `<data dir>/models`). Nothing is ever downloaded at run time: a model that is not here
    turns its role off at start. The `-local` image sets it to its read-only
    `/opt/exactdocs/models`.
    """
    dbos_system_schema: str = Field(default="dbos", pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    """PostgreSQL only: the schema of the same database where DBOS keeps its workflows and their
    steps (SQLite keeps them in `<data dir>/jobs.sqlite`). ExactDocs never needs a second database.
    """
    # Article files above this many bytes are skipped by an import, unread.
    max_article_bytes: int = Field(default=2 * 2**20, ge=1)
    # An import fails when its selected articles add up to more bytes than this (they are held in
    # memory, several times over, until stored).
    max_import_bytes: int = Field(default=256 * 2**20, ge=1)
    # An import parses and chunks this many files per durable step: an import interrupted by a
    # crash or a restart resumes after the last step it completed.
    import_batch_files: int = Field(default=100, ge=1)
    # How often the job worker looks for a queued job to start; an idle server polls no more
    # often than this. Tests lower it.
    job_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    # When the scheduled check ticks (a DBOS cron expression, seconds first): each tick checks the
    # libraries whose own interval is up (new tags imported, branches re-synced). Tests tick every
    # second.
    auto_sync_schedule: str = "0 * * * * *"
    # Images the articles reference: one above `max_image_bytes` is skipped unread, and a version
    # keeps images until they add up to `max_images_bytes` (they are held in memory and in the
    # database, about 8 times over at the peak; later ones are skipped and listed as problems).
    max_image_bytes: int = Field(default=2 * 2**20, ge=1)
    max_images_bytes: int = Field(default=32 * 2**20, ge=1)
    # Encrypts the stored tokens and deploy keys of private repositories. It must be random and
    # at least 32 characters (`openssl rand -base64 32`). Unset: a random key is generated into
    # `<data dir>/secret.key` (mode 0600) on first run. Without the key the credentials cannot be
    # read: libraries keep serving their docs and ask for the token again (`credentials_required`).
    secret_key: SecretStr | None = None
    # The key that was `secret_key` before a rotation: credentials sealed with it still open, and
    # are sealed with the new key when they are next saved. Remove it once they were all re-sent.
    secret_key_previous: SecretStr | None = None
    # One whole `query-docs` payload, notice included, in tokens counted as characters / 4. That
    # undercounts for CJK text and dense code. At least 500: the notice alone is ~100 tokens.
    query_docs_token_budget: int = Field(default=10_000, ge=500)
    ai: AiSettings = Field(default_factory=AiSettings)
    """AI retrieval (`EXACTDOCS_AI__...`, or `[ai]` in the `EXACTDOCS_CONFIG_FILE` TOML file;
    docs/decisions/ai-retrieval.md): the instance mode, provider profiles and model roles.
    """
    # `otlp`: traces and metrics over OTLP/HTTP to the collector the standard
    # `OTEL_EXPORTER_OTLP_ENDPOINT` names. Off: no telemetry SDK is set up, nothing is exported.
    telemetry: Literal["off", "otlp"] = "off"
    telemetry_query_text: bool = False
    """Keep the text of search queries in the traces (span attributes and request URLs). Off by
    default: queries can hold code, names or secrets, and traces are read by more people.
    """
    metrics: bool = False
    """Serve Prometheus metrics at `/metrics` (request, search and job metrics, LLM usage once the
    AI modes exist; no query text, library or caller), behind the Host allowlist. `serve` only;
    with `EXACTDOCS_TELEMETRY=otlp` too, the same metrics also go to the collector.
    """
    metrics_token: SecretStr | None = None
    """When set, `/metrics` answers only `Authorization: Bearer <this token>` (401 otherwise).
    Unset, it needs no credentials. Surrounding whitespace and newlines are trimmed, as Prometheus
    trims its `credentials_file`; blank counts as unset.
    """
    # DNS-rebinding guard for the whole app: extra Host names (e.g. `docs.example.com`,
    # `*.example.com`) and browser origins (e.g. `https://docs.example.com`), comma-separated.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # The session cookie is `Secure` whenever a request arrives over HTTPS (uvicorn reads
    # X-Forwarded-Proto from `forwarded_allow_ips`). Set this when TLS ends at a proxy that does
    # not forward the scheme.
    secure_cookies: bool = False
    # Proxies whose X-Forwarded-* headers uvicorn trusts (comma-separated IPs or `*`).
    forwarded_allow_ips: str = "127.0.0.1,::1"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read the arguments, the environment, ``.env``, then the ``EXACTDOCS_CONFIG_FILE`` TOML.

        Earlier sources win, field by field: the environment over the file.

        Args:
            settings_cls: The settings class.
            init_settings: Arguments given to ``Settings(...)``.
            env_settings: ``EXACTDOCS_*`` variables.
            dotenv_settings: A ``.env`` file.
            file_secret_settings: The secrets directory.

        Returns:
            The sources, highest priority first.
        """
        sources = [init_settings, env_settings, dotenv_settings]
        if path := os.environ.get(SETTINGS_FILE_VARIABLE, "").strip():
            sources.append(
                InitSettingsSource(settings_cls, init_kwargs=read_config_file(Path(path)))
            )
        return (*sources, file_secret_settings)

    @field_validator("auto_sync_schedule")
    @classmethod
    def _schedule_is_a_cron_expression(cls, value: str) -> str:
        if not croniter.is_valid(value, second_at_beginning=True):
            message = (
                "EXACTDOCS_AUTO_SYNC_SCHEDULE must be a cron expression with 5 fields, or 6 with "
                "the seconds first (e.g. '0 * * * * *', every minute)"
            )
            raise ValueError(message)
        return value

    @field_validator("secret_key", "secret_key_previous", "models_dir", mode="before")
    @classmethod
    def _blank_secret_key_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("metrics_token", mode="before")
    @classmethod
    def _trimmed_metrics_token(cls, value: object) -> object:
        """Trim the token as Prometheus trims its ``credentials_file``; blank is unset.

        A token kept in a file usually ends in a newline: kept, every scrape would get a 401.

        Args:
            value: The raw setting.

        Returns:
            The token without surrounding whitespace, or ``None`` when nothing is left.
        """
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def effective_database_url(self) -> str:
        """``EXACTDOCS_DATABASE_URL``, or a SQLite file in the data directory.

        SQLite runs on aiosqlite, PostgreSQL on psycopg 3: ``postgresql://`` and
        ``postgresql+psycopg://`` both name it. Any other driver is left as written, and
        ``open_database`` refuses it.
        """
        if self.database_url:
            url = make_url(self.database_url)
        else:
            url = URL.create("sqlite", database=(self.data_dir / "exactdocs.db").as_posix())
        if url.get_backend_name() == "sqlite":
            url = url.set(drivername="sqlite+aiosqlite")
        elif url.drivername in POSTGRES_DRIVERS:
            url = url.set(drivername=POSTGRES_DRIVER)
        return url.render_as_string(hide_password=False)

    @property
    def effective_models_dir(self) -> Path:
        """``EXACTDOCS_MODELS_DIR``, or ``models`` in the data directory."""
        return self.models_dir or self.data_dir / MODELS_SUBDIR

    @property
    def uses_postgres(self) -> bool:
        """Whether the database is PostgreSQL (``False`` for SQLite and for an invalid URL)."""
        try:
            return make_url(self.effective_database_url).get_backend_name() == "postgresql"
        except ArgumentError:
            return False

    @property
    def trusted_hosts(self) -> list[str]:
        """Host names the app answers to: localhost plus the configured ones."""
        return [*LOCAL_HOSTS, *self.allowed_hosts]


def read_config_file(path: Path) -> dict[str, Any]:
    """Read the TOML configuration file, refusing secrets in it.

    Args:
        path: ``EXACTDOCS_CONFIG_FILE``.

    Returns:
        Its settings, as nested tables.

    Raises:
        SettingsError: The file cannot be read, is not TOML, or holds a key or a secret.
    """
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except OSError as error:
        message = f"{SETTINGS_FILE_VARIABLE} names {path}, which cannot be read ({error.strerror})"
        raise SettingsError(message) from None
    except tomllib.TOMLDecodeError as error:
        message = f"{SETTINGS_FILE_VARIABLE}: {path} is not valid TOML ({error})"
        raise SettingsError(message) from None
    found = sorted(SECRETS_REFUSED_IN_FILE & data.keys())
    providers = data.get("ai", {}).get("providers", {})
    if isinstance(providers, dict):
        found += [
            f"ai.providers.{name}.api_key"
            for name, table in providers.items()
            if isinstance(table, dict) and "api_key" in table
        ]
    if found:
        message = (
            f"{path} holds secrets ({', '.join(found)}): keep keys out of the configuration file; "
            "use api_key_file or the environment (EXACTDOCS_AI__PROVIDERS__<NAME>__API_KEY)"
        )
        raise SettingsError(message)
    return data
