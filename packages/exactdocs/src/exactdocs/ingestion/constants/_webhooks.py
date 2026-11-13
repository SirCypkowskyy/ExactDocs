"""Constants of push webhooks: what a forge may send and how long a delivery is remembered."""

from datetime import timedelta
from typing import Final

MAX_WEBHOOK_BYTES: Final[int] = 5 * 2**20
"""Largest webhook body read, in bytes (5 MiB); a larger one is refused with 413 before any
lookup. GitHub caps its payloads at 25 MiB but a push of docs is a few kilobytes."""
WEBHOOK_DELIVERY_TTL: Final[timedelta] = timedelta(days=7)
"""How long a delivery ID is remembered; older ones are pruned when a delivery is recorded.
Forges redeliver within hours, and by hand within a few days."""
WEBHOOK_SECRET_BYTES: Final[int] = 32
"""Random bytes of a webhook secret, shown URL-safe base64 encoded (43 characters)."""
MAX_DELIVERY_ID: Final[int] = 200
"""Longest delivery ID accepted, in characters (forges send UUIDs)."""
SIGNATURE_SCHEME: Final[str] = "sha256="
"""How a GitHub or Bitbucket signature header starts: HMAC-SHA256, in lowercase hex after it."""
GITHUB_SIGNATURE_HEADER: Final[str] = "x-hub-signature-256"
"""The header GitHub signs its deliveries in (``X-Hub-Signature``, its SHA-1 one, is ignored)."""
