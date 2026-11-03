"""Catalog entities and value objects. Pure Python: no frameworks, no I/O."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Self

from exactdocs.catalog.errors import (
    AmbiguousCommitError,
    InvalidCommitShaError,
    InvalidLibraryIdError,
    InvalidSettingsError,
    InvalidVersionRefError,
)

# A segment is `[a-z0-9._-]+` once lower-cased, but never only dots (`.`, `..`).
_ID_PARTS = 3  # "", owner, repo
_HEADING_LEVELS = 6
_SEGMENT = re.compile(r"(?!\.+$)[A-Za-z0-9._-]+")
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHORT_SHA = re.compile(r"[0-9a-f]{7,64}")
# Stable semver (https://semver.org) with an optional `v`: a pre-release suffix means not stable.
_STABLE_SEMVER = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+[0-9A-Za-z.-]+)?")


@dataclass(frozen=True, slots=True)
class LibraryId:
    """`/owner/repo`, exactly two segments. Stored lower-case, so matched case-insensitively."""

    value: str

    def __post_init__(self) -> None:
        parts = self.value.split("/")
        if len(parts) != _ID_PARTS or parts[0] or not all(map(_SEGMENT.fullmatch, parts[1:])):
            raise InvalidLibraryIdError(self.value)
        object.__setattr__(self, "value", self.value.lower())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class VersionRef:
    """A git ref as published (`v1.4.0`, `main`, `release/1.4`, a SHA). Case-sensitive."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or "" in self.value.split("/") or any(c.isspace() for c in self.value):
            raise InvalidVersionRefError(self.value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ParsedId:
    """A context7-style ID split into its library and the optional ref after it."""

    library: LibraryId
    ref: VersionRef | None

    @classmethod
    def parse(cls, text: str) -> Self:
        """`/owner/repo` or `/owner/repo/<ref>`: everything after two segments is the ref."""
        parts = text.split("/", _ID_PARTS)
        library = LibraryId("/".join(parts[:_ID_PARTS]))
        return cls(library=library, ref=VersionRef(parts[-1]) if len(parts) > _ID_PARTS else None)


class RefKind(StrEnum):
    """What a version was imported from."""

    TAG = "tag"
    BRANCH = "branch"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True, kw_only=True)
class Version:
    """One imported version of a library: a ref pinned to the commit it was resolved to."""

    ref: VersionRef
    kind: RefKind
    commit_sha: str
    imported_at: datetime

    def __post_init__(self) -> None:
        if not _COMMIT_SHA.fullmatch(self.commit_sha):
            raise InvalidCommitShaError(self.commit_sha)


class HostKind(StrEnum):
    """Where the repository is hosted; `git` is any other HTTPS/SSH git server."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GITEA = "gitea"
    GIT = "git"


@dataclass(frozen=True, slots=True, kw_only=True)
class TagRule:
    """Articles whose path matches the glob get the tag (`docs/api/**` -> `api`)."""

    pattern: str
    tag: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkingConfig:
    """How articles are cut: new chunk at headings up to `split_level` (1-6), size bounds."""

    split_level: int = _HEADING_LEVELS
    min_chars: int = 0
    max_chars: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.split_level <= _HEADING_LEVELS:
            message = f"split_level must be between 1 and 6, not {self.split_level}"
            raise InvalidSettingsError(message)
        if self.min_chars < 0 or (self.max_chars is not None and self.max_chars < self.min_chars):
            message = "chunk sizes must satisfy 0 <= min_chars <= max_chars"
            raise InvalidSettingsError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class LibrarySettings:
    """Per-library import settings; they apply to every version of the library."""

    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()
    tag_rules: tuple[TagRule, ...] = ()
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)


@dataclass(frozen=True, slots=True, kw_only=True)
class Library:
    """A documented library and its imported versions."""

    id: LibraryId
    title: str
    source_url: str
    host: HostKind
    description: str = ""
    default_branch: VersionRef | None = None
    settings: LibrarySettings = field(default_factory=LibrarySettings)
    versions: frozenset[Version] = field(default_factory=frozenset)

    def default_version(self) -> Version | None:
        """Pick what `/owner/repo` without a ref means (docs/user-stories.md, *Default version*).

        The highest stable semver tag; else the default branch's version; else the version
        imported last. Ties go to the larger ref so the answer never depends on set order.
        """
        stable = [
            (semver, version)
            for version in self.versions
            if version.kind is RefKind.TAG and (semver := _stable_semver(version.ref.value))
        ]
        if stable:
            return max(stable, key=lambda found: (found[0], found[1].ref.value))[1]
        branch = next(
            (v for v in self.versions if v.kind is RefKind.BRANCH and v.ref == self.default_branch),
            None,
        )
        if branch:
            return branch
        if not self.versions:
            return None
        return max(self.versions, key=lambda v: (v.imported_at, v.ref.value))

    def find_version(self, ref: VersionRef) -> Version | None:
        """Find the version imported from exactly this ref, else the commit a short SHA names.

        Refs are case-sensitive and the match is never fuzzy: a SHA prefix of 7 or more
        characters counts only when exactly one commit version starts with it.
        """
        exact = next((v for v in self.versions if v.ref == ref), None)
        prefix = ref.value.lower()
        if exact or not _SHORT_SHA.fullmatch(prefix):
            return exact
        matches = [
            v for v in self.versions if v.kind is RefKind.COMMIT and v.commit_sha.startswith(prefix)
        ]
        if len(matches) > 1:
            raise AmbiguousCommitError(prefix)
        return next(iter(matches), None)


def _stable_semver(tag: str) -> tuple[int, int, int] | None:
    match = _STABLE_SEMVER.fullmatch(tag)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None
