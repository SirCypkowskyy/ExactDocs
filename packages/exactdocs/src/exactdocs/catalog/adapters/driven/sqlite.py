from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Column, ForeignKey, MetaData, Table, Text, delete, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.catalog.models import Library, LibraryName, Version

# The catalog's tables, prefixed `catalog_`. The schema itself is created by an Alembic revision
# in `exactdocs.bootstrap`; this is only the adapter's query-side description of it.
metadata = MetaData()
libraries = Table("catalog_libraries", metadata, Column("name", Text, primary_key=True))
library_versions = Table(
    "catalog_library_versions",
    metadata,
    Column(
        "library_name",
        Text,
        ForeignKey("catalog_libraries.name", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("version", Text, primary_key=True),
)


@dataclass(frozen=True, slots=True)
class SqliteLibraryRepository:
    """Implements ``ports.driven.LibraryRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        query = select(libraries.c.name, library_versions.c.version).select_from(
            libraries.outerjoin(library_versions)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return _libraries(rows)

    async def get(self, name: LibraryName) -> Library | None:
        """Return the library with this exact name, or ``None``."""
        query = (
            select(libraries.c.name, library_versions.c.version)
            .select_from(libraries.outerjoin(library_versions))
            .where(libraries.c.name == name)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return next(iter(_libraries(rows)), None)

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same name."""
        async with self.engine.begin() as connection:
            await connection.execute(
                sqlite_insert(libraries).values(name=library.name).on_conflict_do_nothing()
            )
            await connection.execute(
                delete(library_versions).where(library_versions.c.library_name == library.name)
            )
            if library.versions:
                await connection.execute(
                    insert(library_versions),
                    [{"library_name": library.name, "version": v.value} for v in library.versions],
                )


def _libraries(rows: Sequence[tuple[str, str | None]]) -> Sequence[Library]:
    versions: dict[str, set[Version]] = {}
    for name, version in rows:
        found = versions.setdefault(name, set())  # a library without versions still appears
        if version is not None:
            found.add(Version(version))
    return tuple(
        Library(name=LibraryName(name), versions=frozenset(found))
        for name, found in versions.items()
    )
