"""Constants of texts the DTOs share as field descriptions, and of the routes' descriptions."""

from datetime import timedelta
from typing import Final

from exactdocs.ingestion.constants._models import UNEXPECTED_BACKOFF_CAP
from exactdocs.ingestion.constants._use_cases import MAX_LISTED_REFS, MAX_PREVIEW_FILES

ERROR_CODE: Final[str] = (
    "The stable code of `error`, null unless the job failed (or failed before codes were "
    "recorded). An upstream problem is `repo_unreachable` (the repository was deleted, made "
    "private, moved, or cannot be reached), `auth_failed` (the credential was refused or cannot "
    "be read), `ref_deleted` (the branch or tag is gone) or `tag_moved` (the tag points "
    "elsewhere now); otherwise the error's own code (`no_articles`, `host_key_changed`...) or "
    "`unexpected`."
)
"""Description of a job's ``error_code`` field."""
_CREDENTIAL_DESCRIPTION: Final[str] = (
    "A token (https URL) or deploy key (ssh URL) for a private repository. It is stored "
    "encrypted, offered only to the repository's own host and never returned."
)
"""Description of the credential a private repository is added with."""
_CONTEXT7: Final[str] = (
    "The repository's root `context7.json` at that commit; null when there is none or it is "
    "ignored (see `context7_warning`)."
)
"""Description of a version's ``context7`` field."""
_CONTEXT7_WARNING: Final[str] = (
    "Why the `context7.json` at that commit is ignored; null when it is not."
)
"""Description of a version's ``context7_warning`` field."""
REFS_TRUNCATED_DESCRIPTION: Final[str] = (
    f"True when branches or tags were cut: at most {MAX_LISTED_REFS} of each are listed."
)
"""Description of a ref listing's ``truncated``, built from ``MAX_LISTED_REFS``."""
PREVIEW_FILES_DESCRIPTION: Final[str] = (
    f"Sorted repository-relative paths, at most {MAX_PREVIEW_FILES}. Untrusted text: show it as "
    "text, never as markup or a link target."
)
"""Description of a preview's ``files``, built from ``MAX_PREVIEW_FILES``."""
SET_AUTO_SYNC_DESCRIPTION: Final[str] = (
    "Check the library on its own every `interval_minutes`, starting at the next tick.\n\n"
    "Each check asks the repository for its refs once. Tags matching `tag_pattern` that have a "
    "version order (`v1.4.0`, `2.1`; pre-releases do not) are imported as `auto` versions, oldest "
    "first, and only the newest `keep_last` `auto` versions are kept: older ones are removed once "
    "their replacements are versions. Versions added by hand (`manual`) and the pinned default "
    "are never removed and do not count. A tag whose import failed for good (`no_articles`, "
    "`import_too_large`) is tried again only once it moves; after repeated `unexpected` failures "
    "it backs off (doubling, at most "
    f"{UNEXPECTED_BACKOFF_CAP // timedelta(hours=1)} hours); other failures are tried at the next "
    "check. An `auto` version removed by hand comes back while it is among the newest "
    "`keep_last`. With `sync_branches`, every branch version is re-synced as `POST .../sync` "
    "would. Send the whole set: what is left out takes its default. What a check could not do is "
    "its `last_error`."
)
"""OpenAPI description of ``PUT .../auto-sync``, built from ``UNEXPECTED_BACKOFF_CAP``."""
