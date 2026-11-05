"""Catalog entities and value objects. Pure Python: no frameworks, no I/O."""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from difflib import get_close_matches
from enum import StrEnum
from typing import Any, NewType, Self

from exactdocs.catalog.errors import (
    AmbiguousCommitError,
    DuplicateArticlePathError,
    DuplicateRenameError,
    DuplicateVersionRefError,
    InvalidArticlePathError,
    InvalidBlobShaError,
    InvalidCommitShaError,
    InvalidImageTypeError,
    InvalidImportTimeError,
    InvalidLibraryIdError,
    InvalidManualTagsError,
    InvalidSettingsError,
    InvalidSimilarityError,
    InvalidTagFilterError,
    InvalidVersionRefError,
    SelfRenameError,
)
from exactdocs_kernel import MAX_TAG_LENGTH, MAX_TAGS, normalize_tag

# A segment is `[a-z0-9._-]+` once lower-cased, but never only dots (`.`, `..`).
_ID_PARTS = 3  # "", owner, repo
_HEADING_LEVELS = 6
_SEGMENT = re.compile(r"(?!\.+$)[A-Za-z0-9._-]+")
_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHORT_SHA = re.compile(r"[0-9a-f]{7,64}")
# Stable semver (https://semver.org) with an optional `v`: a pre-release suffix means not stable.
_STABLE_SEMVER = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\+[0-9A-Za-z.-]+)?"
)


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
    """A git ref as published (`v1.4.0`, `main`, `release/1.4`, a SHA). Case-sensitive.

    Follows the basics of `git check-ref-format` so a ref is safe to hand to git or a path later.
    """

    value: str

    def __post_init__(self) -> None:
        parts = self.value.split("/")
        if (
            "" in parts
            or ".." in self.value
            or self.value.startswith("-")
            or any(part.endswith(".lock") for part in parts)
            or not all(c.isprintable() and not c.isspace() for c in self.value)
        ):
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
        if not _OBJECT_ID.fullmatch(self.commit_sha):
            raise InvalidCommitShaError(self.commit_sha)
        if self.imported_at.tzinfo is None:
            raise InvalidImportTimeError


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

    def __post_init__(self) -> None:
        # Shape only: rules stored under an older normal form must still load.
        if (
            not self.tag
            or len(self.tag) > MAX_TAG_LENGTH
            or "," in self.tag
            or any(c.isspace() for c in self.tag)
        ):
            message = f"{self.tag!r} is not a usable tag"
            raise InvalidSettingsError(message)


class TagMatch(StrEnum):
    """Whether an article needs any or all of the filter's tags."""

    ANY = "any"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class TagSelection:
    """Which articles a tag filter keeps. No tags keeps every article."""

    tags: frozenset[str] = frozenset()
    match: TagMatch = TagMatch.ANY

    @classmethod
    def of(cls, tags: Iterable[str], match: TagMatch = TagMatch.ANY) -> Self:
        """Normalize what a caller typed; refuse a value that is no tag, or too many."""
        raw = list(tags)
        found = [normalize_tag(tag) for tag in raw] if len(raw) <= MAX_TAGS else [None]
        if None in found:
            message = f"tags must be valid tags, at most {MAX_TAGS} of them"
            raise InvalidTagFilterError(message)
        return cls(frozenset(t for t in found if t), match)

    def keeps(self, article_tags: Iterable[str]) -> bool:
        """Tell whether an article with these tags passes."""
        if not self.tags:
            return True
        have = self.tags & set(article_tags)
        return have == self.tags if self.match is TagMatch.ALL else bool(have)


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
    # Set once a user typed the field: README imports never touch it again.
    title_edited: bool = False
    description_edited: bool = False
    # The version an owner chose as the default (LIB-10); it wins over the rule while imported.
    pinned_version: VersionRef | None = None
    # What the default version's `context7.json` tells agents (LIB-06); untrusted repository text.
    rules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        refs = [v.ref for v in self.versions]
        if len(set(refs)) != len(refs):
            duplicate = next(r for r in refs if refs.count(r) > 1)
            raise DuplicateVersionRefError(duplicate.value)

    def default_version(self) -> Version | None:
        """Pick what `/owner/repo` without a ref means (docs/user-stories.md, *Default version*).

        The pinned version while it is imported (LIB-10); else the highest stable semver tag;
        else the default branch's version; else the version imported last. Ties go to the larger
        ref so the answer never depends on set order.
        """
        if pinned := self._pinned():
            return pinned
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

    def default_is_pinned(self) -> bool:
        """Tell whether the default version is the one an owner pinned, not the rule's choice."""
        return self._pinned() is not None

    def _pinned(self) -> Version | None:
        return next((v for v in self.versions if v.ref == self.pinned_version), None)

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
        if len({v.commit_sha for v in matches}) > 1:  # refs of one commit are not ambiguous
            raise AmbiguousCommitError(prefix)
        return min(matches, key=lambda v: v.ref.value) if matches else None


def _stable_semver(tag: str) -> tuple[int, int, int] | None:
    match = _STABLE_SEMVER.fullmatch(tag)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


ManifestId = NewType("ManifestId", str)


class RenameDirection(StrEnum):
    """Which way a path is followed across the rename map of a version."""

    FORWARD = "forward"
    """`path` is from the version imported before `ref`; the answer is its path in `ref`."""
    BACK = "back"
    """`path` is an article of `ref`; the answer is its path in the version before."""


class ManifestState(StrEnum):
    """Where a manifest is in its life: stored, serving readers, or replaced by a newer one."""

    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


type ContentKey = tuple[str, int]  # (git blob SHA, content version)


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestEntry:
    """One article of a manifest: where it lives, and which shared content it points at.

    The content is keyed by blob SHA *and* content version: an opaque number the importer
    raises when it would produce another text from the same blob (a parser fix), so the new
    text is stored next to the old one instead of being ignored.
    """

    path: str
    blob_sha: str  # git blob SHA
    content_version: int
    title: str
    tags: tuple[str, ...] = ()
    """Imported: from front matter and the library's path rules."""
    front_matter: dict[str, Any] = field(default_factory=dict)
    size: int = 0  # bytes of the content
    manual_tags: tuple[ManualTag, ...] = ()
    """Set by hand for this path, or for a path it was renamed from (see ``ManualTags``)."""

    def __post_init__(self) -> None:
        _check_path(self.path)
        if not _OBJECT_ID.fullmatch(self.blob_sha):
            raise InvalidBlobShaError(self.blob_sha)

    @property
    def all_tags(self) -> tuple[str, ...]:
        """What readers see and filter by: the imported tags, then the manual ones they lack."""
        manual = dict.fromkeys(t.tag for t in self.manual_tags if t.tag not in self.tags)
        return (*self.tags, *manual)

    @property
    def content_key(self) -> ContentKey:
        """Where the article's text is stored."""
        return (self.blob_sha, self.content_version)


def _check_path(path: str) -> None:
    if not path or any(part in {"", ".", ".."} for part in path.split("/")):
        raise InvalidArticlePathError(path)


@dataclass(frozen=True, slots=True, order=True)
class ManualTag:
    """A tag an entry carries because a user set it by hand on ``path``.

    ``path`` is the entry's own path, or an older path it was renamed from: the tag is changed or
    removed there (``ManualTags`` is keyed by the path that was tagged, not by its successors).
    """

    tag: str
    path: str


@dataclass(frozen=True, slots=True)
class ManualTags:
    """Tags a user set by hand on an article path of a library: they hold for every version.

    Keyed by path, not by version. A version whose import saw ``old`` renamed to ``new`` gives
    ``new`` the manual tags of ``old`` too (``ManualTags.reaching``), and so on back through the
    versions each rename map names, so a tag follows the article forward across moves.
    """

    path: str
    tags: tuple[str, ...]

    @classmethod
    def of(cls, path: str, tags: Iterable[str]) -> Self:
        """Normalize what a user typed (sorted, no duplicates); refuse a value that is no tag."""
        _check_path(path)
        raw = list(tags)
        found = [normalize_tag(tag) for tag in raw]
        if len(raw) > MAX_TAGS or None in found:
            raise InvalidManualTagsError
        return cls(path, tuple(sorted({t for t in found if t})))

    @staticmethod
    def reaching(
        origins: Mapping[str, Iterable[str]], by_path: Mapping[str, tuple[str, ...]]
    ) -> dict[str, tuple[ManualTag, ...]]:
        """Merge the manual tags each article gets: its own and those of the paths it came from.

        ``origins`` maps an article path to the older paths it was renamed from (any number of
        versions back); paths it leaves out only have their own tags. Each tag names the path it
        was set on, so a tag set on two of them is there twice.
        """
        reached = {path: {ManualTag(t, path) for t in tags} for path, tags in by_path.items()}
        for path, olds in origins.items():
            for old in olds:
                found = reached.setdefault(path, set())
                found.update(ManualTag(t, old) for t in by_path.get(old, ()))
        return {path: tuple(sorted(tags)) for path, tags in reached.items() if tags}


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestRename:
    """A file git saw moved: in version ``from_ref``, ``old_path`` became ``new_path`` here.

    Belongs to the manifest of the *newer* version (the one ``new_path`` is an article of), so it
    is replaced, collected and deleted together with it. A tag's renames come from the previous
    tag; a branch's build up over its syncs, and ``from_ref`` is the branch itself.
    """

    from_ref: VersionRef
    old_path: str
    new_path: str
    similarity: int  # percent of the content kept; 1..100

    def __post_init__(self) -> None:
        _check_path(self.old_path)
        _check_path(self.new_path)
        if not 0 < self.similarity <= MAX_SIMILARITY:
            raise InvalidSimilarityError(self.similarity)


MAX_LIBRARY_RULES = 20
MAX_LIBRARY_RULE_CHARS = 500
"""A library's rules: at most this many, each one line of at most this many characters."""
MAX_SIMILARITY = 100
MAX_RENAMES = 10_000
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"})
"""The only types the catalog stores and serves (the importer sniffs, the catalog re-checks)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestImage:
    """One image of a manifest: the repository path articles reference, and the blob it holds."""

    path: str
    blob_sha: str  # git blob SHA: images with the same blob share one stored copy
    content_type: str
    size: int = 0

    def __post_init__(self) -> None:
        if not self.path or any(part in {"", ".", ".."} for part in self.path.split("/")):
            raise InvalidArticlePathError(self.path)
        if any(part.lower() == ".git" for part in self.path.split("/")):
            raise InvalidArticlePathError(self.path)
        if not _OBJECT_ID.fullmatch(self.blob_sha):
            raise InvalidBlobShaError(self.blob_sha)
        if self.content_type not in IMAGE_TYPES:
            raise InvalidImageTypeError(self.content_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredImage:
    """An image as a reader gets it (and as it is stored once per blob SHA)."""

    blob_sha: str
    content_type: str
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class Manifest:
    """The articles of one version at one commit. Readers only ever see the active manifest.

    A manifest is stored `PENDING` (invisible), activated in one step (the previous one becomes
    `SUPERSEDED`), and collected after a grace period. Other domains hold its ID by value.
    """

    id: ManifestId
    library: LibraryId
    ref: VersionRef
    kind: RefKind
    commit_sha: str
    created_at: datetime
    entries: tuple[ManifestEntry, ...] = ()
    images: tuple[ManifestImage, ...] = ()
    state: ManifestState = ManifestState.PENDING
    superseded_at: datetime | None = None
    renames: tuple[ManifestRename, ...] = ()
    """Files moved since an earlier version; not loaded with the manifest (``find_rename``)."""

    def __post_init__(self) -> None:
        if not _OBJECT_ID.fullmatch(self.commit_sha):
            raise InvalidCommitShaError(self.commit_sha)
        paths = [entry.path for entry in self.entries]
        if len(set(paths)) != len(paths):
            raise DuplicateArticlePathError(next(p for p in paths if paths.count(p) > 1))
        olds = [rename.old_path for rename in self.renames]
        if len(set(olds)) != len(olds):
            raise DuplicateRenameError(next(p for p in olds if olds.count(p) > 1))
        if self.kind is RefKind.TAG and any(r.from_ref == self.ref for r in self.renames):
            raise SelfRenameError(str(self.ref))  # a branch's map builds up over its syncs
        image_paths = [image.path for image in self.images]
        if len(set(image_paths)) != len(image_paths):
            raise DuplicateArticlePathError(
                next(p for p in image_paths if image_paths.count(p) > 1)
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredArticle:
    """An article as a reader gets it: its manifest entry and the shared content."""

    manifest_id: ManifestId
    commit_sha: str
    entry: ManifestEntry
    content: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GarbageCollected:
    """What a collection removed."""

    manifests: int
    contents: int
    images: int = 0


MAX_CLOSE_MATCHES = 5


def close_paths(wanted: str, paths: Sequence[str], limit: int = MAX_CLOSE_MATCHES) -> list[str]:
    """Paths an agent may mean by ``wanted``: the same file name elsewhere, then near typos."""
    name = wanted.rsplit("/", 1)[-1]
    same_name = sorted(p for p in paths if p.rsplit("/", 1)[-1] == name)
    # A typo changes a path a little: skip the (slow) fuzzy match for paths of another size.
    near = [p for p in paths if abs(len(p) - len(wanted)) <= max(3, len(wanted) * 3 // 10)]
    typos = get_close_matches(wanted, near, n=limit, cutoff=0.7)
    return list(dict.fromkeys([*same_name, *typos]))[:limit]
