"""Retrieval value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import json
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import groupby
from typing import NewType

from exactdocs.retrieval.errors import DuplicateChunkError, EmptySearchTextError


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


ChunkId = NewType("ChunkId", str)
type ChunkSetKey = tuple[str, str]  # (git blob SHA, chunking-config hash)


def chunk_id(
    version_id: str,
    article_path: str,
    heading_path: Sequence[str],
    occurrence_index: int,
    content_hash: str,
) -> ChunkId:
    """Return the ID of a chunk inside one version, a pure function of where and what it is.

    ``version_id`` is ``<library>/<ref>`` (`/acme/payments/main`). The same section of an
    unchanged article keeps its ID when the version moves to a new commit, and the same blob in
    another version gets another ID, so ``read_chunk`` names exactly one chunk. The fields are
    JSON-encoded so no separator can make two different inputs collide.
    """
    payload = json.dumps(
        [version_id, article_path, list(heading_path), occurrence_index, content_hash],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ChunkId(hashlib.sha256(payload.encode()).hexdigest()[:32])


@dataclass(frozen=True, slots=True, kw_only=True)
class Chunk:
    """One section of an article, as the chunker cut it."""

    heading_path: tuple[str, ...]
    occurrence_index: int  # 0 for the first heading with this text, 1 for the next one, ...
    content: str
    content_hash: str
    anchor: str
    code_languages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkSet:
    """The ordered chunks of one blob under one chunking config; shared by every version."""

    blob_sha: str
    config_hash: str
    chunks: tuple[Chunk, ...]

    @property
    def key(self) -> ChunkSetKey:
        """Where the set is stored."""
        return (self.blob_sha, self.config_hash)

    @property
    def digest(self) -> str:
        """Fingerprint of the chunks, to notice a set stored under the same key but cut differently.

        A key is (blob, ``config_hash``); the caller must change ``config_hash`` whenever the
        chunker changes. The repository compares digests so a forgotten bump fails loudly.
        """
        parts = [
            [list(c.heading_path), c.occurrence_index, c.content_hash, c.anchor]
            for c in self.chunks
        ]
        return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestChunk:
    """A chunk as one manifest sees it: its ID, its place in the article and the article's tags."""

    chunk_id: ChunkId
    article_path: str
    position: int  # 0-based index in the article
    total: int
    prev_chunk_id: ChunkId | None
    next_chunk_id: ChunkId | None
    tags: tuple[str, ...]
    chunk_set: ChunkSetKey


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexedManifest:
    """A catalog manifest that has chunk rows. Its ID is held by value."""

    manifest_id: str
    version_id: str  # `<library>/<ref>`, as in `chunk_id`
    library: str
    indexed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredChunk:
    """A chunk with its content, as ``read_chunk`` returns it."""

    manifest_id: str
    version_id: str  # `<library>/<ref>` the manifest was indexed under
    row: ManifestChunk
    chunk: Chunk


@dataclass(frozen=True, slots=True, kw_only=True)
class Removed:
    """What a discard or collection deleted."""

    manifests: int
    chunk_sets: int


class ManifestStatus(StrEnum):
    """What the catalog says about a manifest ID; an unknown ID is absent from its answer."""

    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    OTHER = "other"  # a state this domain does not know; never remove such a manifest


def article_chunk_rows(
    version_id: str,
    article_path: str,
    chunk_set: ChunkSet,
    tags: tuple[str, ...],
) -> list[ManifestChunk]:
    """Return the rows one article contributes to a manifest, linked to their neighbours."""
    ids = [
        chunk_id(version_id, article_path, c.heading_path, c.occurrence_index, c.content_hash)
        for c in chunk_set.chunks
    ]
    if len(set(ids)) != len(ids):
        raise DuplicateChunkError(article_path)
    return [
        ManifestChunk(
            chunk_id=id_,
            article_path=article_path,
            position=i,
            total=len(ids),
            prev_chunk_id=ids[i - 1] if i else None,
            next_chunk_id=ids[i + 1] if i + 1 < len(ids) else None,
            tags=tags,
            chunk_set=chunk_set.key,
        )
        for i, id_ in enumerate(ids)
    ]
