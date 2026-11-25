"""A stand-in Context7 for the Context7 run's tests (pytest and behave, #493).

It answers ``GET /v2/context`` (``type=json``) the way Context7's Public API 2.0.0 does, in the
shape its OpenAPI document and a live response give (``tests/contracts/context7/rest``): ranked
``codeSnippets`` and ``infoSnippets``, the served ``libraryId``, and a ``version`` object when the
version asked is not indexed. The bodies are built here, for ``retrieval_bench_stand_ins``' tiny
corpus: the Install section for the install question, nothing for any other. Nothing reaches the
network.
"""

import json
from dataclasses import dataclass, field
from typing import Literal

from retrieval_eval.context7 import Fetched

INSTALL_TEXT = "Run pip to install the demo package."
"""The Install section's prose in the tiny corpus's guide."""
INSTALL_CODE = "pip install demo"
"""Its code block."""
OTHER_RELEASE = "v2"
"""The release served in place of a pinned version Context7 does not have."""
DATE = "2026-11-25T10:00:00+00:00"
"""When the stand-in "answered"."""

Serves = Literal["pinned", "other release", "current only", "error"]


def _body(library_id: str, query: str, version: dict[str, object] | None) -> str:
    """Build a ``/v2/context`` JSON body.

    Args:
        library_id: The library ID that served the response.
        query: The question.
        version: The ``version`` object, when the version asked is not indexed.

    Returns:
        The body.
    """
    code, info = [], []
    if "install" in query:
        code.append(
            {
                "codeTitle": "Install the demo package",
                "codeDescription": "Context7's own summary of the snippet, not in the docs.",
                "codeLanguage": "sh",
                "codeTokens": 4,
                "codeId": "https://github.com/demo/demo/blob/v1/docs/guide.md#_snippet_0",
                "pageTitle": "Guide",
                "codeList": [{"language": "sh", "code": INSTALL_CODE}],
                "rank": 2,
            }
        )
        info.append(
            {
                "pageId": "https://github.com/demo/demo/blob/v1/docs/guide.md",
                "breadcrumb": "Guide > Install",
                "content": INSTALL_TEXT,
                "contentTokens": 9,
                "rank": 1,
            }
        )
    body: dict[str, object] = {"libraryId": library_id, "codeSnippets": code, "infoSnippets": info}
    if version is not None:
        body["version"] = version
    return json.dumps(body)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- it records calls
class StandInContext7:
    """Context7 serving one library, in one of the ways it serves a version."""

    serves: Serves = "pinned"
    """How it serves a pinned version."""
    calls: list[tuple[str, str]] = field(default_factory=list)
    """Every ``(libraryId, query)`` it was asked, in order."""

    def describe(self) -> dict[str, str]:
        """Say what answers.

        Returns:
            The stand-in's name.
        """
        return {"client": "stand-in"}

    async def context(self, library_id: str, query: str) -> Fetched:
        """Answer one ``/v2/context`` request.

        Args:
            library_id: ``/owner/repo`` or ``/owner/repo/<version>``.
            query: The question.

        Returns:
            The raw response.
        """
        self.calls.append((library_id, query))
        if self.serves == "error":
            return Fetched(status=500, body='{"error": "internal", "message": "boom"}', date=DATE)
        parts = library_id.strip("/").split("/")
        library, requested = "/" + "/".join(parts[:2]), "/".join(parts[2:])
        if not requested:
            return Fetched(status=200, body=_body(library, query, None), date=DATE)
        served_id = f"{library}@{requested}"
        version: dict[str, object] | None = None
        if self.serves == "other release":
            version = {
                "libraryId": f"{library}/{OTHER_RELEASE}",
                "requested": requested,
                "served": OTHER_RELEASE,
                "status": "unverified",
            }
        elif self.serves == "current only":
            version = {
                "libraryId": library,
                "requested": requested,
                "served": None,
                "status": "unverified",
            }
        return Fetched(status=200, body=_body(served_id, query, version), date=DATE)
