"""Server settings, read from a settings file."""

from pydantic import BaseModel


class ServerSettings(BaseModel):
    """Where the server listens."""

    host: str
    port: int
