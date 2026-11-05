from pathlib import Path
from typing import Annotated, Literal

from platformdirs import user_data_path
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

# Hosts every instance accepts; anything else must be listed in EXACTDOCS_ALLOWED_HOSTS.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _default_data_dir() -> Path:
    return user_data_path("exactdocs", appauthor=False)


class Settings(BaseSettings):
    """Runtime configuration, read from ``EXACTDOCS_*`` environment variables (and a ``.env``)."""

    model_config = SettingsConfigDict(
        env_prefix="EXACTDOCS_", env_file=".env", extra="ignore", hide_input_in_errors=True
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
    telemetry: Literal["off", "otlp"] = "off"
    metrics: bool = False
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

    @field_validator("secret_key", "secret_key_previous", mode="before")
    @classmethod
    def _blank_secret_key_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

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
