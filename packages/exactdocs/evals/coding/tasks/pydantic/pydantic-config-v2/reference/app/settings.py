"""Server settings, read from a settings file."""

from pydantic import BaseModel, ConfigDict


class ServerSettings(BaseModel):
    """Where the server listens."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    host: str
    port: int
