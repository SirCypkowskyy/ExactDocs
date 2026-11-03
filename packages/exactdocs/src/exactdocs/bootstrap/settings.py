from pathlib import Path
from typing import Annotated, Literal

from platformdirs import user_data_path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Hosts every instance accepts; anything else must be listed in EXACTDOCS_ALLOWED_HOSTS.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _default_data_dir() -> Path:
    return user_data_path("exactdocs", appauthor=False)


class Settings(BaseSettings):
    """Runtime configuration, read from ``EXACTDOCS_*`` environment variables (and a ``.env``)."""

    model_config = SettingsConfigDict(env_prefix="EXACTDOCS_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 3000
    # Docker sets EXACTDOCS_DATA_DIR=/data; `uvx` uses the platform user-data directory.
    data_dir: Path = Field(default_factory=_default_data_dir)
    database_url: str | None = None
    auth_mode: Literal["local", "oidc"] = "local"
    telemetry: Literal["off", "otlp"] = "off"
    metrics: bool = False
    # DNS-rebinding guard for the whole app: extra Host names (e.g. `docs.example.com`,
    # `*.example.com`) and browser origins (e.g. `https://docs.example.com`), comma-separated.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Proxies whose X-Forwarded-* headers uvicorn trusts (comma-separated IPs or `*`).
    forwarded_allow_ips: str = "127.0.0.1,::1"

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def effective_database_url(self) -> str:
        """``EXACTDOCS_DATABASE_URL``, or a SQLite file in the data directory."""
        return self.database_url or f"sqlite:///{(self.data_dir / 'exactdocs.db').as_posix()}"

    @property
    def trusted_hosts(self) -> list[str]:
        """Host names the app answers to: localhost plus the configured ones."""
        return [*LOCAL_HOSTS, *self.allowed_hosts]
