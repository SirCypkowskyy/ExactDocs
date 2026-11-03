from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from ``EXACTDOCS_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="EXACTDOCS_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 3000
    database_url: str = "sqlite:///data/exactdocs.db"
    auth_mode: Literal["local", "oidc", "proxy"] = "local"
    telemetry: Literal["off", "console", "otlp", "logfire"] = "off"
