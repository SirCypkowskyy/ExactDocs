import os
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal

from croniter import croniter
from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
)
from sqlalchemy.engine import URL, make_url

from exactdocs.bootstrap.constants import (
    LOCAL_HOSTS,
    SECRETS_REFUSED_IN_FILE,
    SETTINGS_FILE_VARIABLE,
)
from exactdocs.retrieval.constants import DEFAULT_REQUEST_TIMEOUT, DEFAULT_RETRIES
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

    Fields the later issues read (``dimensions``, ``batch_size``, ``top_n``) are accepted and kept
    for them; nothing reads them yet.
    """

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True, extra="allow")

    model: str | None = None
    """`<profile>:<model>`, e.g. `corp:gpt-4.1-mini`."""


class AiSettings(BaseModel):
    """The ``ai`` section: AI retrieval, read from ``EXACTDOCS_AI__<FIELD>`` variables."""

    model_config = ConfigDict(use_attribute_docstrings=True, frozen=True)

    mode: RetrievalMode | None = None
    """`EXACTDOCS_AI__MODE`: the retrieval mode of every search that names none, for libraries
    without their own: `bm25`, `hybrid`, `hybrid_hyde` or `agentic`. Unset (or `auto`): the best
    mode the configured models allow (BM25 with none). A mode whose model is not configured falls
    back to the best one, and the results say so (`fallback_reason` `mode_unavailable`).
    """

    providers: dict[str, ProviderSettings] = Field(default_factory=dict)
    """Named provider profiles (`EXACTDOCS_AI__PROVIDERS__<NAME>__...`); read-only over REST."""
    embedding: RoleSettings = Field(default_factory=RoleSettings)
    """The embedding role, instance-wide only (`EXACTDOCS_AI__EMBEDDING__MODEL`)."""
    reranker: RoleSettings = Field(default_factory=RoleSettings)
    """The reranker role (`EXACTDOCS_AI__RERANKER__MODEL`)."""
    llm: RoleSettings = Field(default_factory=RoleSettings)
    """The LLM role (`EXACTDOCS_AI__LLM__MODEL`)."""
    judge: RoleSettings = Field(default_factory=RoleSettings)
    """The judge role (`EXACTDOCS_AI__JUDGE__MODEL`); the LLM role when unset."""

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
    # Overrides the SQLite file in the data directory, e.g. `sqlite:////srv/exactdocs.db`.
    database_url: str | None = None
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

    @field_validator("secret_key", "secret_key_previous", mode="before")
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
        """``EXACTDOCS_DATABASE_URL``, or a SQLite file in the data directory (aiosqlite driver)."""
        if self.database_url:
            url = make_url(self.database_url)
        else:
            url = URL.create("sqlite", database=(self.data_dir / "exactdocs.db").as_posix())
        if url.get_backend_name() == "sqlite":
            url = url.set(drivername="sqlite+aiosqlite")
        return url.render_as_string(hide_password=False)

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
