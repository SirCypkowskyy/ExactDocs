"""Catalog entities and value objects. Pure Python: no frameworks, no I/O."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from difflib import get_close_matches
from enum import StrEnum
from typing import Any, NewType, Self

from exactdocs.catalog.constants import (
    _HEADING_LEVELS,
    _ID_PARTS,
    _OBJECT_ID,
    _SEGMENT,
    _SHORT_SHA,
    _STABLE_SEMVER,
    IMAGE_TYPES,
    MAX_CLOSE_MATCHES,
    MAX_INSTRUCTION_FILE_CHARS,
    MAX_INSTRUCTION_FILES,
    MAX_SIMILARITY,
)
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
    InvalidInstructionFileError,
    InvalidLibraryIdError,
    InvalidManualTagsError,
    InvalidSettingsError,
    InvalidSimilarityError,
    InvalidTagFilterError,
    InvalidVersionRefError,
    RenameLinkMismatchError,
    SelfRenameError,
)
from exactdocs_kernel import MAX_TAG_LENGTH, MAX_TAGS, normalize_tag


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- one-field value object
class LibraryId:
    """`/owner/repo`, exactly two segments. Stored lower-case, so matched case-insensitively."""

    value: str
    """The ID as given; stored lower-case."""

    def __post_init__(self) -> None:
        """Check the shape and store the ID lower-case.

        Raises:
            InvalidLibraryIdError: Not ``/owner/repo`` with two valid segments.
        """
        parts = self.value.split("/")
        if len(parts) != _ID_PARTS or parts[0] or not all(map(_SEGMENT.fullmatch, parts[1:])):
            raise InvalidLibraryIdError(self.value)
        object.__setattr__(self, "value", self.value.lower())

    def __str__(self) -> str:
        """Render as ``/owner/repo``.

        Returns:
            The ID, lower-case.
        """
        return self.value


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- one-field value object
class VersionRef:
    """A git ref as published (`v1.4.0`, `main`, `release/1.4`, a SHA). Case-sensitive.

    Follows the basics of `git check-ref-format` so a ref is safe to hand to git or a path later.
    """

    value: str
    """The ref as published; case-sensitive."""

    def __post_init__(self) -> None:
        """Check the ref against the basics of ``git check-ref-format``.

        Raises:
            InvalidVersionRefError: An empty part, ``..``, a leading ``-``, a part ending in
                ``.lock``, a space or a control character.
        """
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
        """Render as the ref.

        Returns:
            The ref as published.
        """
        return self.value


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedId:
    """A context7-style ID split into its library and the optional ref after it."""

    library: LibraryId
    """The library the ID names."""
    ref: VersionRef | None
    """The ref after the library; ``None`` when there is none (the default version)."""

    @classmethod
    def parse(cls, text: str) -> Self:
        """`/owner/repo` or `/owner/repo/<ref>`: everything after two segments is the ref.

        Args:
            text: The ID as given.

        Returns:
            The library and the optional ref.
        """
        parts = text.split("/", _ID_PARTS)
        library = LibraryId("/".join(parts[:_ID_PARTS]))
        return cls(library=library, ref=VersionRef(parts[-1]) if len(parts) > _ID_PARTS else None)


class RefKind(StrEnum):
    """What a version was imported from."""

    TAG = "tag"
    BRANCH = "branch"
    COMMIT = "commit"


class VersionOrigin(StrEnum):
    """Who asked for a version: a person, or the scheduled check (which may prune its own)."""

    MANUAL = "manual"
    AUTO = "auto"


@dataclass(frozen=True, slots=True, kw_only=True)
class Version:
    """One imported version of a library: a ref pinned to the commit it was resolved to."""

    ref: VersionRef
    """The ref it was imported from."""
    kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    commit_sha: str
    """The full commit SHA the ref resolved to at import."""
    imported_at: datetime
    """When it was last imported; timezone-aware."""
    origin: VersionOrigin = VersionOrigin.MANUAL
    """Set by the version's first import and never changed by a later one."""

    def __post_init__(self) -> None:
        """Check the commit SHA and the import time.

        Raises:
            InvalidCommitShaError: The SHA is not a full lower-case object ID.
            InvalidImportTimeError: The import time has no time zone.
        """
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
    """Glob over article paths, e.g. ``docs/api/**``."""
    tag: str
    """The tag a matching article gets."""

    def __post_init__(self) -> None:
        """Check the tag's shape.

        Raises:
            InvalidSettingsError: The tag is empty, too long, or holds a comma or a space.
        """
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


@dataclass(frozen=True, slots=True, kw_only=True)
class TagSelection:
    """Which articles a tag filter keeps. No tags keeps every article."""

    tags: frozenset[str] = frozenset()
    """The normalized tags; empty keeps every article."""
    match: TagMatch = TagMatch.ANY
    """Whether an article needs any or all of ``tags``."""

    @classmethod
    def of(cls, tags: Iterable[str], match: TagMatch = TagMatch.ANY) -> Self:
        """Normalize what a caller typed; refuse a value that is no tag, or too many.

        Args:
            tags: The tags as typed.
            match: Whether an article needs any or all of them.

        Returns:
            The selection.

        Raises:
            InvalidTagFilterError: A value is not a valid tag, or there are more than ``MAX_TAGS``.
        """
        raw = list(tags)
        found = [normalize_tag(tag) for tag in raw] if len(raw) <= MAX_TAGS else [None]
        if None in found:
            message = f"tags must be valid tags, at most {MAX_TAGS} of them"
            raise InvalidTagFilterError(message)
        return cls(tags=frozenset(t for t in found if t), match=match)

    def keeps(self, article_tags: Iterable[str]) -> bool:
        """Tell whether an article with these tags passes.

        Args:
            article_tags: The article's tags.

        Returns:
            True when the selection is empty or the article has any (or all) of its tags.
        """
        if not self.tags:
            return True
        have = self.tags & set(article_tags)
        return have == self.tags if self.match is TagMatch.ALL else bool(have)


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkingConfig:
    """How articles are cut: new chunk at headings up to `split_level` (1-6), size bounds."""

    split_level: int = _HEADING_LEVELS
    """Deepest heading level that starts a new chunk."""
    min_chars: int = 0
    """A chunk shorter than this is merged with the next one, within ``max_chars``."""
    max_chars: int | None = None
    """A chunk longer than this is cut again at deeper headings; ``None``: no bound."""
    chunker: str = "markdown"
    """Which chunker cuts; the importer knows which ones exist."""

    def __post_init__(self) -> None:
        """Check the level, the size bounds and the chunker name.

        Raises:
            InvalidSettingsError: The level is out of range, the bounds are inverted or negative,
                or no chunker is named.
        """
        if not 1 <= self.split_level <= _HEADING_LEVELS:
            message = f"split_level must be between 1 and 6, not {self.split_level}"
            raise InvalidSettingsError(message)
        if self.min_chars < 0 or (self.max_chars is not None and self.max_chars < self.min_chars):
            message = "chunk sizes must satisfy 0 <= min_chars <= max_chars"
            raise InvalidSettingsError(message)
        if not self.chunker:
            message = "a chunker must be named"
            raise InvalidSettingsError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class LibrarySettings:
    """Per-library import settings; they apply to every version of the library."""

    include_paths: tuple[str, ...] = ()
    """Folders, files or globs to import; empty: every Markdown file."""
    exclude_paths: tuple[str, ...] = ()
    """Folders, files or globs to leave out; they win over ``include_paths``."""
    tag_rules: tuple[TagRule, ...] = ()
    """Tags given to articles by path."""
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    """How articles are cut into chunks."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Library:
    """A documented library and its imported versions."""

    id: LibraryId
    """``/owner/repo``."""
    title: str
    """Display name."""
    source_url: str
    """Where the repository is cloned from."""
    host: HostKind
    """What kind of server hosts the repository."""
    description: str = ""
    """What the library is; from the README unless a user typed it."""
    default_branch: VersionRef | None = None
    """The repository's default branch, once known."""
    settings: LibrarySettings = field(default_factory=LibrarySettings)
    """Import settings for every version."""
    versions: frozenset[Version] = field(default_factory=frozenset)
    """The imported versions, one per ref."""
    title_edited: bool = False
    """A user typed the title: README imports never touch it again."""
    description_edited: bool = False
    """A user typed the description: README imports never touch it again."""
    pinned_version: VersionRef | None = None
    """The version an owner chose as the default (LIB-10); it wins over the rule while imported."""
    rules: tuple[str, ...] = ()
    """What the default version's ``context7.json`` tells agents (LIB-06); untrusted text."""

    def __post_init__(self) -> None:
        """Refuse two versions of one ref.

        Raises:
            DuplicateVersionRefError: A ref is listed twice.
        """
        refs = [v.ref for v in self.versions]
        if len(set(refs)) != len(refs):
            duplicate = next(r for r in refs if refs.count(r) > 1)
            raise DuplicateVersionRefError(duplicate.value)

    def default_version(self) -> Version | None:
        """Pick what `/owner/repo` without a ref means (docs/user-stories.md, *Default version*).

        The pinned version while it is imported (LIB-10); else the highest stable semver tag;
        else the default branch's version; else the version imported last. Ties go to the larger
        ref so the answer never depends on set order.

        Returns:
            The default version; ``None`` when nothing is imported.
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
        """Tell whether the default version is the one an owner pinned, not the rule's choice.

        Returns:
            True while the pinned version is imported.
        """
        return self._pinned() is not None

    def _pinned(self) -> Version | None:
        """Find the pinned version among the imported ones.

        Returns:
            The pinned version; ``None`` when none is pinned or it is not imported.
        """
        return next((v for v in self.versions if v.ref == self.pinned_version), None)

    def find_version(self, ref: VersionRef) -> Version | None:
        """Find the version imported from exactly this ref, else the commit a short SHA names.

        Refs are case-sensitive and the match is never fuzzy: a SHA prefix of 7 or more
        characters counts only when exactly one commit version starts with it.

        Args:
            ref: The ref asked for, or a commit SHA prefix.

        Returns:
            The version; ``None`` when no ref or commit matches.

        Raises:
            AmbiguousCommitError: The prefix matches commit versions of different commits.
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
    """Read a tag as stable semver.

    Args:
        tag: The tag's name.

    Returns:
        Major, minor and patch; ``None`` for a pre-release or a tag that is not semver.
    """
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
    """Stored by an import and not yet activated: no reader sees it."""
    ACTIVE = "active"
    """The version's current manifest: readers are served from it."""
    SUPERSEDED = "superseded"
    """Replaced by a newer manifest of the same version; kept until it is collected."""


type ContentKey = tuple[str, int]  # (git blob SHA, content version)


class TagOrigin(StrEnum):
    """Where a tag of an article comes from; a tag may come from several places at once."""

    FRONT_MATTER = "front_matter"
    """Declared in the article's front matter."""
    PATH_RULE = "path_rule"
    """Given by one of the library's tag rules, whose pattern matches the article's path."""
    IMPORTED = "imported"
    """Imported, from the front matter or a path rule; which one was not recorded (a manifest
    stored before the origins were). A re-import or a change of the tag rules records it."""
    MANUAL = "manual"
    """Set by hand on the article's path, or on one it was renamed from."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TagSources:
    """The imported tags of an article, by source: what an import combined into its tags."""

    front_matter: tuple[str, ...] = ()
    """Declared in the front matter, normalized."""
    rules: tuple[str, ...] = ()
    """Given by the library's tag rules that match the article's path."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedTags:
    """An article's imported tags, and where they come from when that is known."""

    tags: tuple[str, ...]
    """Every imported tag, as the import combined and capped them."""
    sources: TagSources | None = None
    """Where they come from; ``None`` when it was not recorded."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestEntry:
    """One article of a manifest: where it lives, and which shared content it points at.

    The content is keyed by blob SHA *and* content version: an opaque number the importer
    raises when it would produce another text from the same blob (a parser fix), so the new
    text is stored next to the old one instead of being ignored.
    """

    path: str
    """Repository path of the article."""
    blob_sha: str
    """Git blob SHA."""
    content_version: int
    """The importer's content version: a new one stores a new text for the same blob."""
    title: str
    """The article's title."""
    tags: tuple[str, ...] = ()
    """Imported: from front matter and the library's path rules."""
    front_matter: dict[str, Any] = field(default_factory=dict)
    """The article's front matter, parsed; untrusted repository data."""
    size: int = 0
    """Bytes of the content."""
    manual_tags: tuple[ManualTag, ...] = ()
    """Set by hand for this path, or for a path it was renamed from (see ``ManualTags``)."""
    sources: TagSources | None = None
    """Where ``tags`` come from; ``None`` in a manifest stored before that was recorded."""

    def __post_init__(self) -> None:
        """Check the path and the blob SHA.

        Raises:
            InvalidBlobShaError: The SHA is not a full lower-case object ID.
        """
        _check_path(self.path)
        if not _OBJECT_ID.fullmatch(self.blob_sha):
            raise InvalidBlobShaError(self.blob_sha)

    @property
    def all_tags(self) -> tuple[str, ...]:
        """What readers see and filter by: the imported tags, then the manual ones they lack."""
        manual = dict.fromkeys(t.tag for t in self.manual_tags if t.tag not in self.tags)
        return (*self.tags, *manual)

    @property
    def tag_origins(self) -> tuple[tuple[str, tuple[TagOrigin, ...]], ...]:
        """Every tag of ``all_tags``, in that order, with where it comes from.

        The origins of a tag are in ``TagOrigin`` order. Only a tag among the imported ``tags``
        has a source (one the cap left out has none); an imported tag no recorded source names
        (``sources`` is ``None``, or does not list it) is ``IMPORTED``.
        """
        sources = self.sources or TagSources()
        manual = {t.tag for t in self.manual_tags}
        found: list[tuple[str, tuple[TagOrigin, ...]]] = []
        for tag in self.all_tags:
            imported = tag in self.tags
            origins = [
                TagOrigin.FRONT_MATTER if imported and tag in sources.front_matter else None,
                TagOrigin.PATH_RULE if imported and tag in sources.rules else None,
            ]
            if imported and not any(origins):
                origins.append(TagOrigin.IMPORTED)
            origins.append(TagOrigin.MANUAL if tag in manual else None)
            found.append((tag, tuple(o for o in origins if o is not None)))
        return tuple(found)

    @property
    def imported(self) -> ImportedTags:
        """The imported tags with their sources."""
        return ImportedTags(tags=self.tags, sources=self.sources)

    @property
    def content_key(self) -> ContentKey:
        """Where the article's text is stored."""
        return (self.blob_sha, self.content_version)


def _check_path(path: str) -> None:
    """Refuse a path that is not relative and normalized.

    Args:
        path: A repository path.

    Raises:
        InvalidArticlePathError: It is empty or has an empty, ``.`` or ``..`` part.
    """
    if not path or any(part in {"", ".", ".."} for part in path.split("/")):
        raise InvalidArticlePathError(path)


@dataclass(frozen=True, slots=True, kw_only=True, order=True)
class ManualTag:
    """A tag an entry carries because a user set it by hand on ``path``.

    ``path`` is the entry's own path, or an older path it was renamed from: the tag is changed or
    removed there (``ManualTags`` is keyed by the path that was tagged, not by its successors).
    """

    tag: str
    """The tag."""
    path: str
    """The path it was set on: the entry's own, or one it was renamed from."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualTags:
    """Tags a user set by hand on an article path of a library: they hold for every version.

    Keyed by path, not by version. A version whose import saw ``old`` renamed to ``new`` gives
    ``new`` the manual tags of ``old`` too (``ManualTags.reaching``), and so on back through the
    versions each rename map names, so a tag follows the article forward across moves.
    """

    path: str
    """The article path tagged."""
    tags: tuple[str, ...]
    """The tags, normalized and sorted."""

    @classmethod
    def of(cls, path: str, tags: Iterable[str]) -> Self:
        """Normalize what a user typed (sorted, no duplicates); refuse a value that is no tag.

        Args:
            path: The article path.
            tags: The tags as typed.

        Returns:
            The path's manual tags.

        Raises:
            InvalidManualTagsError: A value is not a valid tag, or there are more than
                ``MAX_TAGS``.
        """
        _check_path(path)
        raw = list(tags)
        found = [normalize_tag(tag) for tag in raw]
        if len(raw) > MAX_TAGS or None in found:
            raise InvalidManualTagsError
        return cls(path=path, tags=tuple(sorted({t for t in found if t})))

    @staticmethod
    def reaching(
        origins: Mapping[str, Iterable[str]], by_path: Mapping[str, tuple[str, ...]]
    ) -> dict[str, tuple[ManualTag, ...]]:
        """Merge the manual tags each article gets: its own and those of the paths it came from.

        ``origins`` maps an article path to the older paths it was renamed from (any number of
        versions back); paths it leaves out only have their own tags. Each tag names the path it
        was set on, so a tag set on two of them is there twice.

        Args:
            origins: Article path to the older paths it was renamed from.
            by_path: Manual tags by the path they were set on.

        Returns:
            Each article path that gets a tag, with its tags sorted.
        """
        reached = {
            path: {ManualTag(tag=t, path=path) for t in tags} for path, tags in by_path.items()
        }
        for path, olds in origins.items():
            for old in olds:
                found = reached.setdefault(path, set())
                found.update(ManualTag(tag=t, path=old) for t in by_path.get(old, ()))
        return {path: tuple(sorted(tags)) for path, tags in reached.items() if tags}


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestRename:
    """A file git saw moved: in version ``from_ref``, ``old_path`` became ``new_path`` here.

    Belongs to the manifest of the *newer* version (the one ``new_path`` is an article of), so it
    is replaced, collected and deleted together with it. A tag's renames come from the previous
    tag; a branch's build up over its syncs, and ``from_ref`` is the branch itself.
    """

    from_ref: VersionRef
    """The version ``old_path`` is from."""
    old_path: str
    """The path in ``from_ref``."""
    new_path: str
    """The path in this manifest's version."""
    similarity: int
    """Percent of the content kept; 1..100."""

    def __post_init__(self) -> None:
        """Check both paths and the similarity.

        Raises:
            InvalidSimilarityError: The similarity is not from 1 to ``MAX_SIMILARITY``.
        """
        _check_path(self.old_path)
        _check_path(self.new_path)
        if not 0 < self.similarity <= MAX_SIMILARITY:
            raise InvalidSimilarityError(self.similarity)


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestImage:
    """One image of a manifest: the repository path articles reference, and the blob it holds."""

    path: str
    """Repository path of the image."""
    blob_sha: str
    """Git blob SHA: images with the same blob share one stored copy."""
    content_type: str
    """Media type, one of ``IMAGE_TYPES``."""
    size: int = 0
    """Bytes of the image."""

    def __post_init__(self) -> None:
        """Check the path, the blob SHA and the media type.

        Raises:
            InvalidArticlePathError: An empty, ``.``, ``..`` or ``.git`` segment.
            InvalidBlobShaError: The SHA is not a full lower-case object ID.
            InvalidImageTypeError: The media type is not one of ``IMAGE_TYPES``.
        """
        if not self.path or any(part in {"", ".", ".."} for part in self.path.split("/")):
            raise InvalidArticlePathError(self.path)
        if any(part.lower() == ".git" for part in self.path.split("/")):
            raise InvalidArticlePathError(self.path)
        if not _OBJECT_ID.fullmatch(self.blob_sha):
            raise InvalidBlobShaError(self.blob_sha)
        if self.content_type not in IMAGE_TYPES:
            raise InvalidImageTypeError(self.content_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class ManifestInstruction:
    """An instruction file (``AGENTS.md`` / ``CLAUDE.md``) the version's commit holds (RET-08).

    Kept with the manifest, even outside the selected paths, only when the library's repo
    guidance is on; untrusted repository text, never shown as an article.
    """

    path: str
    """Repository-relative, e.g. ``AGENTS.md`` or ``docs/guide/CLAUDE.md``."""
    content: str
    """Its text, as the commit holds it (decoded, at most ``MAX_INSTRUCTION_FILE_CHARS``)."""

    def __post_init__(self) -> None:
        """Refuse a path that is not a plain repository path, or an oversized text.

        Raises:
            InvalidArticlePathError: An empty, ``.``, ``..`` or ``.git`` segment.
            InvalidInstructionFileError: The text is longer than ``MAX_INSTRUCTION_FILE_CHARS``.
        """
        _check_path(self.path)
        if any(part.lower() == ".git" for part in self.path.split("/")):
            raise InvalidArticlePathError(self.path)
        if len(self.content) > MAX_INSTRUCTION_FILE_CHARS:
            raise InvalidInstructionFileError(self.path)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredImage:
    """An image as a reader gets it (and as it is stored once per blob SHA)."""

    blob_sha: str
    """Git blob SHA of the image."""
    content_type: str
    """Media type, one of ``IMAGE_TYPES``."""
    data: bytes = field(repr=False)
    """The image's bytes."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Manifest:
    """The articles of one version at one commit. Readers only ever see the active manifest.

    A manifest is stored `PENDING` (invisible), activated in one step (the previous one becomes
    `SUPERSEDED`), and collected after a grace period. Other domains hold its ID by value.
    """

    id: ManifestId
    """The manifest's ID."""
    library: LibraryId
    """The library."""
    ref: VersionRef
    """The version's ref."""
    kind: RefKind
    """Whether the ref is a tag, a branch or a commit."""
    commit_sha: str
    """The commit the articles are from."""
    created_at: datetime
    """When it was stored."""
    entries: tuple[ManifestEntry, ...] = ()
    """Its articles, one per path."""
    images: tuple[ManifestImage, ...] = ()
    """Its images, one per path."""
    state: ManifestState = ManifestState.PENDING
    """Pending, active or superseded."""
    superseded_at: datetime | None = None
    """When a newer manifest replaced it; starts the grace period before collection."""
    renames: tuple[ManifestRename, ...] = ()
    """Files moved since an earlier version; not loaded with the manifest (``find_rename``)."""
    renamed_from: VersionRef | None = None
    """The version ``renames`` were detected against, also when nothing moved: the version this
    one follows, a link in the chain a path is followed along across versions. ``None`` when no
    version was compared; a branch's is the branch itself (its map builds up over its syncs)."""
    origin: VersionOrigin = VersionOrigin.MANUAL
    """What its activation gives the version when it creates it (an existing one keeps its own)."""
    instructions: tuple[ManifestInstruction, ...] = ()
    """The commit's instruction files kept for agentic retrieval (RET-08); not loaded with the
    manifest (``list_instructions``)."""

    def __post_init__(self) -> None:
        """Check the instruction files, the commit SHA, and that no path or rename repeats.

        Raises:
            InvalidInstructionFileError: More than ``MAX_INSTRUCTION_FILES`` instruction files,
                or one path twice.
            InvalidCommitShaError: The SHA is not a full lower-case object ID.
            DuplicateArticlePathError: An article or image path is listed twice.
            DuplicateRenameError: An old path is renamed twice.
            SelfRenameError: A tag's renames come from the tag itself.
            RenameLinkMismatchError: A rename comes from another version than ``renamed_from``.
        """
        kept = [instruction.path for instruction in self.instructions]
        if len(kept) > MAX_INSTRUCTION_FILES:
            raise InvalidInstructionFileError(kept[MAX_INSTRUCTION_FILES])
        if len(set(kept)) != len(kept):
            raise InvalidInstructionFileError(next(p for p in kept if kept.count(p) > 1))
        if not _OBJECT_ID.fullmatch(self.commit_sha):
            raise InvalidCommitShaError(self.commit_sha)
        paths = [entry.path for entry in self.entries]
        if len(set(paths)) != len(paths):
            raise DuplicateArticlePathError(next(p for p in paths if paths.count(p) > 1))
        olds = [rename.old_path for rename in self.renames]
        if len(set(olds)) != len(olds):
            raise DuplicateRenameError(next(p for p in olds if olds.count(p) > 1))
        if self.kind is RefKind.TAG and (
            self.renamed_from == self.ref or any(r.from_ref == self.ref for r in self.renames)
        ):
            raise SelfRenameError(str(self.ref))  # a branch's map builds up over its syncs
        if self.renamed_from is not None and (
            stray := next((r for r in self.renames if r.from_ref != self.renamed_from), None)
        ):
            # The chain across versions follows ``renamed_from``: a rename of another version
            # would answer with a path that version has, not the one followed (#201).
            raise RenameLinkMismatchError(
                str(self.ref), str(stray.from_ref), str(self.renamed_from)
            )
        image_paths = [image.path for image in self.images]
        if len(set(image_paths)) != len(image_paths):
            raise DuplicateArticlePathError(
                next(p for p in image_paths if image_paths.count(p) > 1)
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredArticle:
    """An article as a reader gets it: its manifest entry and the shared content."""

    manifest_id: ManifestId
    """The active manifest it was read from."""
    commit_sha: str
    """The commit the article is from."""
    entry: ManifestEntry
    """Its manifest entry."""
    content: str
    """Its text."""


@dataclass(frozen=True, slots=True, kw_only=True)
class GarbageCollected:
    """What a collection removed."""

    manifests: int
    """Manifests removed."""
    contents: int
    """Article texts removed."""
    images: int = 0
    """Stored images removed."""


def close_paths(wanted: str, paths: Sequence[str], limit: int = MAX_CLOSE_MATCHES) -> list[str]:
    """Paths an agent may mean by ``wanted``: the same file name elsewhere, then near typos.

    Args:
        wanted: The path asked for.
        paths: The paths that exist.
        limit: The most paths returned.

    Returns:
        The close paths, best first, without repeats.
    """
    name = wanted.rsplit("/", 1)[-1]
    same_name = sorted(p for p in paths if p.rsplit("/", 1)[-1] == name)
    # A typo changes a path a little: skip the (slow) fuzzy match for paths of another size.
    near = [p for p in paths if abs(len(p) - len(wanted)) <= max(3, len(wanted) * 3 // 10)]
    typos = get_close_matches(wanted, near, n=limit, cutoff=0.7)
    return list(dict.fromkeys([*same_name, *typos]))[:limit]


class Access(StrEnum):
    """The library role a caller needs for an action; the values are the role names."""

    READ = "viewer"
    """Search and read."""
    CONTRIBUTE = "contributor"
    """Import content: add versions, sync, tag articles."""
    ADMINISTER = "admin"
    """Configure the library and remove versions."""
    OWN = "creator"
    """Remove the library."""
