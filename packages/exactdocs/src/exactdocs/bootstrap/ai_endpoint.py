"""A provider profile ready to be called: shared by ``ai_models`` and ``ai_sdk``."""

from dataclasses import dataclass, field

import httpx2

from exactdocs.retrieval.models import ProviderProfile


@dataclass(frozen=True, slots=True, kw_only=True)
class Endpoint:
    """A profile ready to be called: its endpoint, its key and its one HTTP client."""

    profile: ProviderProfile
    """The profile, as it was when the client was built."""
    base_url: str
    """The endpoint every call goes to."""
    key: str | None = field(repr=False)
    """The key, unsealed or read; ``None`` for a profile without one."""
    client: httpx2.AsyncClient = field(repr=False)
    """The profile's HTTP client."""
