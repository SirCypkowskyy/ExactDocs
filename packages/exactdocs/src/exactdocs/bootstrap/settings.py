from pathlib import Path
from typing import Literal

from platformdirs import user_data_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Extra Host headers / browser origins accepted by the MCP endpoint (DNS-rebinding guard).
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)

    @property
    def effective_database_url(self) -> str:
        """``EXACTDOCS_DATABASE_URL``, or a SQLite file in the data directory."""
        return self.database_url or f"sqlite:///{(self.data_dir / 'exactdocs.db').as_posix()}"
