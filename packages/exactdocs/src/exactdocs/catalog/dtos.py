"""Data crossing the catalog boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.catalog.models import HostKind, Library, LibrarySettings, RefKind, Version
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, Page


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _FromModel(BaseModel):
    """Boundary copy of a domain value object with the same field names."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)


class TagRuleOut(_FromModel):
    """Articles whose path matches `pattern` get `tag`."""

    pattern: str
    tag: str


class ChunkingOut(_FromModel):
    """How articles are cut into chunks."""

    split_level: int
    min_chars: int
    max_chars: int | None


class LibrarySettingsOut(_FromModel):
    """A library's import settings."""

    include_paths: list[str]
    exclude_paths: list[str]
    tag_rules: list[TagRuleOut]
    chunking: ChunkingOut

    @classmethod
    def from_model(cls, settings: LibrarySettings) -> Self:
        """Map the domain value object."""
        return cls.model_validate(settings)


class VersionOut(_Dto):
    """One imported version: the ref, what kind of ref it is, and the commit it stands for."""

    ref: str
    kind: RefKind
    commit_sha: str
    imported_at: datetime
    is_default: bool = Field(description="True for the version `/owner/repo` resolves to.")

    @classmethod
    def from_model(cls, version: Version, *, is_default: bool) -> Self:
        """Map a domain entity."""
        return cls(
            ref=str(version.ref),
            kind=version.kind,
            commit_sha=version.commit_sha,
            imported_at=version.imported_at,
            is_default=is_default,
        )


class ResolvedVersion(VersionOut):
    """The version an ID resolved to; always states which one was used."""

    library: str

    @classmethod
    def from_library(cls, library: Library, version: Version) -> Self:
        """Map the library and the chosen version."""
        found = VersionOut.from_model(version, is_default=version == library.default_version())
        return cls(library=str(library.id), **found.model_dump())


class LibrarySummary(_Dto):
    """A library and its version refs, sorted."""

    id: str
    title: str
    description: str
    versions: list[str]
    default_version: str | None

    @classmethod
    def from_model(cls, library: Library) -> Self:
        """Map a domain entity to its boundary representation."""
        default = library.default_version()
        return cls(
            id=str(library.id),
            title=library.title,
            description=library.description,
            versions=sorted(str(v.ref) for v in library.versions),
            default_version=str(default.ref) if default else None,
        )


class LibraryDetail(_Dto):
    """Everything known about one library."""

    id: str
    title: str
    description: str
    source_url: str
    host: HostKind
    default_branch: str | None
    settings: LibrarySettingsOut
    versions: list[VersionOut]
    default_version: str | None

    @classmethod
    def from_model(cls, library: Library) -> Self:
        """Map a domain entity to its boundary representation."""
        default = library.default_version()
        return cls(
            id=str(library.id),
            title=library.title,
            description=library.description,
            source_url=library.source_url,
            host=library.host,
            default_branch=str(library.default_branch) if library.default_branch else None,
            settings=LibrarySettingsOut.from_model(library.settings),
            versions=[
                VersionOut.from_model(v, is_default=v == default)
                for v in sorted(library.versions, key=lambda v: v.ref.value)
            ],
            default_version=str(default.ref) if default else None,
        )


Limit = Annotated[int, Field(ge=1, le=MAX_LIMIT)]


class ListLibrariesQuery(_Dto):
    """One page of libraries: ``limit`` items after the opaque ``cursor`` of the previous page."""

    limit: Limit = DEFAULT_LIMIT
    cursor: str | None = None


class LibraryList(_Dto):
    """A page of the libraries visible to the caller, sorted by ID."""

    libraries: list[LibrarySummary]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )

    @classmethod
    def from_page(cls, page: Page[Library]) -> Self:
        """Map a page of domain entities."""
        return cls(
            libraries=[LibrarySummary.from_model(lib) for lib in page.items],
            next_cursor=page.next_cursor,
        )


class GetLibraryQuery(_Dto):
    """Look up one library by ID (`/owner/repo`, any letter case)."""

    id: str = Field(min_length=1)


class ResolveVersionQuery(_Dto):
    """Resolve `/owner/repo` (its default version) or `/owner/repo/<ref>` (exactly that ref)."""

    id: str = Field(min_length=1)
