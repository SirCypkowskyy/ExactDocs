"""Input caps and shapes every domain's tools and routes agree on (one ID, one rule)."""

LIBRARY_ID_PATTERN = r"^/[^/]+/[^/]+$"  # `/owner/repo`; the version goes in `ref`
MAX_NAME = 256  # library ID, ref, path prefix
MAX_TAG_INPUT = 100  # one tag filter value; a comma may pack several tags into it
MAX_PATH = 4096  # an article path inside a repository
MAX_CURSOR = 1024
# Hints every ExactDocs MCP tool states. Open world on purpose: the content is external and
# untrusted, and clients may gate on that even though the catalogue itself is local.
TOOL_HINTS = {"read_only_hint": True, "idempotent_hint": True, "open_world_hint": True}
