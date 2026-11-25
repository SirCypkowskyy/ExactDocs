"""Server settings, read from a settings file."""

from pydantic import BaseModel, Extra


class ServerSettings(BaseModel):
    """Where the server listens."""

    host: str
    port: int

    class Config:
        extra = Extra.forbid
        anystr_strip_whitespace = True
        allow_mutation = False
