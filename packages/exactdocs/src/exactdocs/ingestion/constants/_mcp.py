"""Constants of the MCP tools that add libraries and versions (#613)."""

import re
from typing import Final

DEFAULT_MCP_IMPORT_HOSTS: Final[tuple[str, ...]] = (
    "github.com",
    "gitlab.com",
    "codeberg.org",
    "bitbucket.org",
)
"""The hosts ``add_docs`` may import from unless ``EXACTDOCS_MCP_IMPORT_HOSTS`` names others."""
SHORTHAND_HOST: Final[str] = "github.com"
"""Where an ``owner/repo`` source lives."""
MAX_MCP_PATHS: Final[int] = 20
"""The most include paths ``add_docs`` takes."""
MAX_MCP_PATH: Final[int] = 256
"""The longest include path ``add_docs`` takes."""
MAX_MCP_SOURCE: Final[int] = 2048
"""The longest source ``add_docs`` takes, as long as a URL ``POST /libraries`` takes."""
MAX_STATUS_JOBS: Final[int] = 5
"""How many of the caller's jobs ``import_status`` lists without a job ID."""
STATUS_SCAN: Final[int] = 100
"""How many of the newest jobs ``import_status`` looks through for the caller's own."""
MAX_ANSWER_REF: Final[int] = 100
"""The most characters of a ref name an answer repeats; refs are untrusted repository text."""
HTTPS_PORT: Final[int] = 443
"""The only port a source over MCP may name."""
_SHORTHAND: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
"""``owner/repo``: a repository on ``SHORTHAND_HOST``."""
