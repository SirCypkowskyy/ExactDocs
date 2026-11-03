"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

import re
import unicodedata
from dataclasses import dataclass

from exactdocs.retrieval.errors import EmptySearchTextError


@dataclass(frozen=True, slots=True, kw_only=True)
class DocTarget:
    """The exact library version a search is pinned to. Version is a hard filter."""

    library: str
    version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchText:
    """What the agent is looking for: an identifier, an error code or a question."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise EmptySearchTextError


@dataclass(frozen=True, slots=True, kw_only=True)
class Excerpt:
    """Original documentation text, never a summary, with where it came from."""

    text: str
    source_url: str
    target: DocTarget
    commit_sha: str | None = None


_CANDIDATE = re.compile(r"[\w.\-]+")
_SEGMENT = re.compile(r"[^\W_]+")


def identifier_tokens(text: str) -> str:
    """Text for the extra indexed column: every word whole, plus its parts when it has several.

    `retryPolicy` -> `retrypolicy retry policy`, `--dry-run` -> `--dry-run dry run`. Apply it to
    chunk text when indexing and to the query when searching so both sides see the same tokens.
    Parts split on `_`, `-`, `.`, case changes (`HTTPServer` -> `http server`) and letter/digit
    changes (`base64` -> `base 64`). Output is lowercase and NFC-normalized.
    """
    tokens: list[str] = []
    for candidate in _CANDIDATE.findall(unicodedata.normalize("NFC", text)):
        whole = candidate.lstrip(".").rstrip(".-").lower()
        parts = [
            part.lower() for segment in _SEGMENT.findall(candidate) for part in _split_case(segment)
        ]
        if parts:
            tokens.append(whole)
            tokens.extend(parts if len(parts) > 1 or parts[0] != whole else [])
    return " ".join(tokens)


def _split_case(segment: str) -> list[str]:
    """Split one alphanumeric run at lower->Upper, ACRONYMWord and letter<->digit boundaries."""
    parts: list[str] = []
    start = 0
    for i in range(1, len(segment)):
        prev, cur = segment[i - 1], segment[i]
        after = segment[i + 1] if i + 1 < len(segment) else ""
        if prev.isdigit() != cur.isdigit() or (
            cur.isupper() and (not prev.isupper() or after.islower())
        ):
            parts.append(segment[start:i])
            start = i
    parts.append(segment[start:])
    return parts
