"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

from itertools import groupby
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


def _is_mark(char: str) -> bool:
    return unicodedata.category(char).startswith("M")


def _is_segment_char(char: str) -> bool:
    return char.isalnum() or _is_mark(char)


def _is_word_char(char: str) -> bool:
    return _is_segment_char(char) or char in "_.-"


def identifier_tokens(text: str) -> str:
    """Text for the extra indexed column: every word whole, plus its parts when it has several.

    `retryPolicy` -> `retrypolicy retry policy`, `--dry-run` -> `--dry-run dry run`. Apply it
    once to chunk text when indexing and to the query when searching, so both sides see the same
    tokens. Parts split on `_`, `-`, `.`, case changes (`HTTPServer` -> `http server`) and
    letter/digit changes (`base64` -> `base 64`). Output is NFC-normalized and casefolded
    (`Straße` and `STRASSE` agree); combining marks stay inside their word. Leading dots and
    trailing dots/dashes are stripped from the whole (`.env` -> `env`), leading dashes are kept.

    Contract for the search adapters:

    - The column must be tokenized so that `-`, `_` and `.` stay inside a token: FTS5
      `tokenize="unicode61 tokenchars '-_.'"`; the pg_search configuration (E12-02) must match.
      With the default `unicode61` the whole tokens (`max_retries`, `--dry-run`) are lost.
    - Query tokens are alternatives: `split()` the result and OR / rank them. Do not match them
      as one phrase or AND them, or a query `retryPolicy` misses prose that says `retry policy`.
    """
    tokens: list[str] = []
    for is_word, run in groupby(unicodedata.normalize("NFC", text), _is_word_char):
        if not is_word:
            continue
        candidate = "".join(run)
        whole = candidate.lstrip(".").rstrip(".-").casefold()
        parts = [
            part.casefold()
            for is_segment, segment in groupby(candidate, _is_segment_char)
            if is_segment
            for part in _split_case("".join(segment))
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
        if not _is_mark(cur) and (
            prev.isdigit() != cur.isdigit()
            or (cur.isupper() and (not prev.isupper() or after.islower()))
        ):
            parts.append(segment[start:i])
            start = i
    parts.append(segment[start:])
    return parts
