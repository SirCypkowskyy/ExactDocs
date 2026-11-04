from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import TypeAdapter
from sqlalchemy import (
    Column,
    ColumnElement,
    ForeignKey,
    MetaData,
    Table,
    Text,
    delete,
    insert,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    LibrarySettings,
    RefKind,
    Version,
    VersionRef,
)

# The catalog's tables, prefixed `catalog_`. The schema itself is created by an Alembic revision
# in `exactdocs.bootstrap`; this is only the adapter's query-side description of it.
metadata = MetaData()
libraries = Table(
    "catalog_libraries",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("host", Text, nullable=False),
    Column("default_branch", Text),
    Column("pinned_version", Text),  # LIB-10 (MVP-2): never written or read yet
    Column("settings", Text, nullable=False),
)
library_versions = Table(
    "catalog_library_versions",
    metadata,
    Column(
        "library_id", Text, ForeignKey("catalog_libraries.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("ref", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("commit_sha", Text, nullable=False),
    Column("imported_at", Text, nullable=False),
)

_SETTINGS = TypeAdapter(LibrarySettings)  # settings are stored as one JSON document
_LIBRARY_COLUMNS = (
    libraries.c.id,
    libraries.c.title,
    libraries.c.description,
    libraries.c.source_url,
    libraries.c.host,
    libraries.c.default_branch,
    libraries.c.settings,
)


@dataclass(frozen=True, slots=True)
class SqliteLibraryRepository:
    """Implements ``ports.driven.LibraryRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        return await self._load()

    async def get(self, library_id: LibraryId) -> Library | None:
        """Return the library with this ID, or ``None``."""
        found = await self._load(libraries.c.id == library_id.value)
        return next(iter(found), None)

    async def save(self, library: Library) -> None:
        """Store the library and its versions, replacing any earlier entry with the same ID."""
        values = {
            "title": library.title,
            "description": library.description,
            "source_url": library.source_url,
            "host": library.host.value,
            "default_branch": None
            if library.default_branch is None
            else library.default_branch.value,
            "settings": _SETTINGS.dump_json(library.settings).decode(),
        }
        async with self.engine.begin() as connection:
            await connection.execute(
                sqlite_insert(libraries)
                .values(id=library.id.value, **values)
                .on_conflict_do_update(index_elements=[libraries.c.id], set_=values)
            )
            await connection.execute(
                delete(library_versions).where(library_versions.c.library_id == library.id.value)
            )
            if library.versions:
                await connection.execute(
                    insert(library_versions),
                    [
                        {
                            "library_id": library.id.value,
                            "ref": v.ref.value,
                            "kind": v.kind.value,
                            "commit_sha": v.commit_sha,
                            "imported_at": v.imported_at.isoformat(),
                        }
                        for v in library.versions
                    ],
                )

    async def _load(self, *where: ColumnElement[bool]) -> Sequence[Library]:
        chosen = select(libraries.c.id).where(*where)
        async with self.engine.connect() as connection:
            rows = (await connection.execute(select(*_LIBRARY_COLUMNS).where(*where))).all()
            version_rows = (
                await connection.execute(
                    select(library_versions).where(library_versions.c.library_id.in_(chosen))
                )
            ).all()
        versions: defaultdict[str, set[Version]] = defaultdict(set)
        for row in version_rows:
            versions[row.library_id].add(
                Version(
                    ref=VersionRef(row.ref),
                    kind=RefKind(row.kind),
                    commit_sha=row.commit_sha,
                    imported_at=datetime.fromisoformat(row.imported_at),
                )
            )
        return tuple(
            Library(
                id=LibraryId(row.id),
                title=row.title,
                description=row.description,
                source_url=row.source_url,
                host=HostKind(row.host),
                default_branch=VersionRef(row.default_branch) if row.default_branch else None,
                settings=_SETTINGS.validate_json(row.settings),
                versions=frozenset(versions[row.id]),
            )
            for row in rows
        )
