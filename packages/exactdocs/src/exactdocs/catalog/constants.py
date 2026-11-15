"""Constants of ``exactdocs.catalog``: every fixed value its modules share.

Each is ``Final`` and documented; see *Python conventions* in docs/architecture.md.
"""

import re
from typing import Final

from exactdocs_kernel import MAX_LIMIT

# ---------------------------------------------------------------- models
_ID_PARTS: Final[int] = 3
"""Parts of a library ID split at ``/``: an empty one, the owner and the repository."""
_HEADING_LEVELS: Final[int] = 6
"""Deepest Markdown heading level; chunking splits at every level by default."""
_SEGMENT: Final[re.Pattern[str]] = re.compile(r"(?!\.+$)[A-Za-z0-9._-]+")
"""One segment of a library ID: no dots-only names, no slashes."""
_OBJECT_ID: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
"""A full git object ID: SHA-1 (40) or SHA-256 (64) hex digits."""
_SHORT_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{7,64}")
"""An abbreviated or full commit SHA."""
_STABLE_SEMVER: Final[re.Pattern[str]] = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\+[0-9A-Za-z.-]+)?"
)
"""Stable semver (https://semver.org) with an optional `v`: a pre-release suffix means not stable.
"""
MAX_LIBRARY_RULES: Final[int] = 20
"""Rules a library's settings may hold."""
MAX_LIBRARY_RULE_CHARS: Final[int] = 500
"""A library's rules: at most this many, each one line of at most this many characters."""
MAX_SIMILARITY: Final[int] = 100
"""Highest rename similarity git reports, in percent."""
MAX_RENAMES: Final[int] = 10_000
"""Renames read per manifest when following a path across versions."""
IMAGE_TYPES: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
)
"""The only types the catalog stores and serves (the importer sniffs, the catalog re-checks)."""
MAX_INSTRUCTION_FILES: Final[int] = 64
"""Instruction files (``AGENTS.md`` / ``CLAUDE.md``) a manifest may keep (RET-08)."""
MAX_INSTRUCTION_FILE_CHARS: Final[int] = 32_768
"""Characters of one kept instruction file."""
MAX_CLOSE_MATCHES: Final[int] = 5
"""Paths suggested when an article does not exist."""

# ---------------------------------------------------------------- dtos
MAX_SUMMARY_REFS: Final[int] = 50
"""Versions listed per library in a library summary."""
_PINNED: Final[str] = (
    "True when an owner pinned `default_version`; false when it follows the default-version rule "
    "(highest stable semver tag, else the default branch, else the newest import)."
)
"""Description of a library's ``default_pinned`` field."""
DEFAULT_GRACE_SECONDS: Final[int] = 7 * 24 * 3600
"""How long a replaced or removed version's content is kept before it may be collected."""
MAX_TAG_RULES: Final[int] = 64
"""Tag rules a library's settings may hold."""
MAX_TITLE: Final[int] = 200
"""Longest library title, in characters."""
MAX_DESCRIPTION: Final[int] = 1000
"""Longest library description, in characters."""
MAX_STORED_ARTICLE_FILES: Final[int] = 1000
"""Files one call may ask the stored text of."""

# ---------------------------------------------------------------- use_cases
MAX_SUGGESTION_SCAN: Final[int] = 10_000
"""A missing article lists at most this many paths to look for close matches."""
TAG_SOURCE_PAGE: Final[int] = 1000
"""Entries read per page when a whole manifest's tag sources are collected."""
MAX_TAG_FACETS: Final[int] = 100
"""Tags counted for a version's tag list; more are reported as truncated."""

# ---------------------------------------------------------------- adapters.driven.sqlite
_PATHS_PER_QUERY: Final[int] = 500
"""Bound variables per statement stay far below SQLite's limit."""
_FILES_PER_QUERY: Final[int] = 250
"""Three bound variables per file at most."""

# ---------------------------------------------------------------- adapters.driving.http
_ASSET_HEADERS: Final[dict[str, str]] = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; sandbox; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    # The URL names a path of a ref, which can move; the bytes are named by the blob SHA (ETag).
    # `private`: for the signed-in caller only. `no-cache`: revalidate, 304 while the SHA is equal.
    "Cache-Control": "private, no-cache",
}
"""Repository content is untrusted. These headers make an image safe to open directly, too: nothing
may load or run in its document (`default-src 'none'`, `sandbox`: no scripts even in an SVG), the
browser must not guess another type, and no other site may embed it.
"""
_SVG: Final[str] = "image/svg+xml"
"""Media type of SVG images, which get extra protection when served."""

# ---------------------------------------------------------------- adapters.driving.mcp
ARTICLE_TEMPLATE: Final[str] = "exactdocs://{owner}/{repo}/{path*}{?ref}"
"""URI template of an article as an MCP resource."""
MAX_LISTED_RESOURCES: Final[int] = MAX_LIMIT
"""Articles in resources/list; the template reaches the rest."""
RESOURCE_PAGE_SIZE: Final[int] = 50
"""Items per resources/list page; clients must not rely on it."""
RESOURCE_LIST_TTL: Final[float] = 30.0
"""Seconds one built list is reused, so paging builds it once."""
MAX_RESOURCE_SNAPSHOTS: Final[int] = 64
"""Callers whose resource list is kept at once; the oldest built is dropped past it."""
LIST_LIBRARIES_LIMIT: Final[int] = 20
"""Each library brings its versions: keep the default page small."""

# ---------------------------------------------------------------- dtos (schema descriptions)
TAG_LIST_DESCRIPTION: Final[str] = f"Most used first, then by name; at most {MAX_TAG_FACETS}."
"""OpenAPI description of a version's ``tags`` list, built from ``MAX_TAG_FACETS``."""
SIMILARITY_DESCRIPTION: Final[str] = (
    f"Percent of the content kept; {MAX_SIMILARITY} is a move unchanged."
)
"""OpenAPI description of a rename's ``similarity``, built from ``MAX_SIMILARITY``."""
MAX_RENAME_HOPS: Final[int] = 100
"""Versions a path is followed across at most, from one version to another; farther is no move."""
