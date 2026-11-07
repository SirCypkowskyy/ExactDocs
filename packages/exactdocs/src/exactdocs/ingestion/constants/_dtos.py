"""Constants of texts the DTOs share as field descriptions."""

from typing import Final

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
