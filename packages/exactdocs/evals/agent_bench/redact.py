"""Keep credentials and accounts out of the benchmark's report: settings, URLs and error messages.

The report records how a run was configured so that it can be repeated, and what failed. Neither
may carry a key or say whose account ran it: a retrieval configuration can name a provider's API
key (``providers.eval.api_key=...``), a base URL can hold a user and password, and a provider's
error message can echo a header or name the account (Ollama Cloud's usage limit says
``you (<account>) have reached your session usage limit``). Everything the report records from the
environment or a provider goes through here.
"""

import os
import re
from collections.abc import Mapping
from typing import Final
from urllib.parse import urlsplit, urlunsplit

REDACTED: Final[str] = "<redacted>"
"""What a secret becomes in the report."""
SECRET_NAME: Final[re.Pattern[str]] = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|HEADER|COOKIE|SESSION", re.IGNORECASE
)
"""A setting or environment variable whose value is a secret, by its name."""
BEARER: Final[re.Pattern[str]] = re.compile(
    r"(?P<scheme>bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE
)
"""A credential in an ``Authorization`` header's form."""
ACCOUNT: Final[re.Pattern[str]] = re.compile(r"\b(?P<you>you) \([^()\s]{1,64}\)", re.IGNORECASE)
"""An account named in a provider's message: ``you (<account>)``."""
EMAIL: Final[re.Pattern[str]] = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
"""An email address."""
SHORTEST_SECRET: Final[int] = 8
"""Environment values shorter than this are not scrubbed from text (they would match words)."""


def safe_url(url: str) -> str:
    """Drop a URL's user, password and query (where a key can travel).

    Args:
        url: A base URL.

    Returns:
        Scheme, host, port and path only.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def recorded_settings(env: Mapping[str, str]) -> dict[str, str]:
    """The settings as the report records them: a secret's value is replaced.

    Args:
        env: Setting names to values.

    Returns:
        The same names; the value of each whose name looks secret is ``REDACTED``, and URLs lose
        their user, password and query.
    """
    recorded = {}
    for name, value in env.items():
        if SECRET_NAME.search(name):
            recorded[name] = REDACTED
        elif "://" in value:
            recorded[name] = safe_url(value)
        else:
            recorded[name] = value
    return recorded


def scrub(text: str, environ: Mapping[str, str] | None = None) -> str:
    """Remove credentials and accounts from text a provider or a tool produced (an error message).

    Args:
        text: The text.
        environ: The environment whose secret-named values are removed; ``os.environ`` by default.

    Returns:
        The text with every such value, every ``Bearer <token>``, every ``you (<account>)``'s
        account and every email address replaced by ``REDACTED``.
    """
    environ = os.environ if environ is None else environ
    for name, value in environ.items():
        if SECRET_NAME.search(name) and len(value) >= SHORTEST_SECRET and value in text:
            text = text.replace(value, REDACTED)
    text = BEARER.sub(lambda m: f"{m['scheme']} {REDACTED}", text)
    text = ACCOUNT.sub(lambda m: f"{m['you']} ({REDACTED})", text)
    return EMAIL.sub(REDACTED, text)
