import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlalchemy import (
    Column,
    ColumnElement,
    ForeignKey,
    Integer,
    MetaData,
    Row,
    Table,
    Text,
    delete,
    exists,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.catalog.errors import ManifestNotFoundError, ManifestNotPendingError
from exactdocs.catalog.models import (
    GarbageCollected,
    HostKind,
    Library,
    LibraryId,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestState,
    RefKind,
    StoredArticle,
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

manifests = Table(
    "catalog_manifests",
    metadata,
    Column("id", Text, primary_key=True),
    Column(
        "library_id", Text, ForeignKey("catalog_libraries.id", ondelete="CASCADE"), nullable=False
    ),
    Column("ref", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("commit_sha", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("superseded_at", Text),
)
article_contents = Table(
    "catalog_article_contents",
    metadata,
    Column("blob_sha", Text, primary_key=True),
    Column("content", Text, nullable=False),
)
manifest_entries = Table(
    "catalog_manifest_entries",
    metadata,
    Column(
        "manifest_id",
        Text,
        ForeignKey("catalog_manifests.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("path", Text, primary_key=True),
    Column("blob_sha", Text, ForeignKey("catalog_article_contents.blob_sha"), nullable=False),
    Column("title", Text, nullable=False),
    Column("tags", Text, nullable=False),  # JSON list
    Column("front_matter", Text, nullable=False),  # JSON object
    Column("size", Integer, nullable=False),
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


def _iso(moment: datetime) -> str:
    """UTC ISO 8601, so stored timestamps compare as text."""
    return moment.astimezone(UTC).isoformat()


def _entry(row: Row) -> ManifestEntry:
    return ManifestEntry(
        path=row.path,
        blob_sha=row.blob_sha,
        title=row.title,
        tags=tuple(json.loads(row.tags)),
        front_matter=json.loads(row.front_matter),
        size=row.size,
    )


@dataclass(frozen=True, slots=True)
class SqliteManifestRepository:
    """Implements ``ports.driven.ManifestRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    def _write(self) -> AbstractAsyncContextManager[AsyncConnection]:
        # BEGIN IMMEDIATE: a transaction that reads before it writes takes the write lock up
        # front instead of failing with "database is locked" when it upgrades later.
        return self.engine.execution_options(begin_immediate=True).begin()

    async def add(self, manifest: Manifest, contents: Mapping[str, str]) -> None:
        """Store a pending manifest and the contents it needs; stored contents stay as they are."""
        async with self._write() as connection:
            if contents:
                await connection.execute(
                    sqlite_insert(article_contents).on_conflict_do_nothing(),
                    [{"blob_sha": sha, "content": text} for sha, text in contents.items()],
                )
            await connection.execute(
                insert(manifests).values(
                    id=manifest.id,
                    library_id=manifest.library.value,
                    ref=manifest.ref.value,
                    kind=manifest.kind.value,
                    commit_sha=manifest.commit_sha,
                    state=manifest.state.value,
                    created_at=_iso(manifest.created_at),
                )
            )
            if manifest.entries:
                await connection.execute(
                    insert(manifest_entries),
                    [
                        {
                            "manifest_id": manifest.id,
                            "path": e.path,
                            "blob_sha": e.blob_sha,
                            "title": e.title,
                            "tags": json.dumps(e.tags),
                            "front_matter": json.dumps(e.front_matter),
                            "size": e.size,
                        }
                        for e in manifest.entries
                    ],
                )

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest with its entries sorted by path, or ``None``."""
        return await self._load(manifests.c.id == manifest_id)

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the active manifest of this version, or ``None``."""
        return await self._load(
            manifests.c.library_id == library_id.value,
            manifests.c.ref == ref.value,
            manifests.c.state == ManifestState.ACTIVE.value,
        )

    async def get_article(
        self, library_id: LibraryId, ref: VersionRef, path: str
    ) -> StoredArticle | None:
        """Return one article of the version's active manifest, or ``None``."""
        query = (
            select(
                manifests.c.id, manifests.c.commit_sha, manifest_entries, article_contents.c.content
            )
            .select_from(
                manifests.join(
                    manifest_entries, manifest_entries.c.manifest_id == manifests.c.id
                ).join(article_contents, article_contents.c.blob_sha == manifest_entries.c.blob_sha)
            )
            .where(
                manifests.c.library_id == library_id.value,
                manifests.c.ref == ref.value,
                manifests.c.state == ManifestState.ACTIVE.value,
                manifest_entries.c.path == path,
            )
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        if row is None:
            return None
        return StoredArticle(
            manifest_id=ManifestId(row.id),
            commit_sha=row.commit_sha,
            entry=_entry(row),
            content=row.content,
        )

    async def activate(self, manifest_id: ManifestId, *, at: datetime) -> Version:
        """Make a pending manifest the version's active one, in one transaction."""
        async with self._write() as connection:
            row = (
                await connection.execute(select(manifests).where(manifests.c.id == manifest_id))
            ).first()
            if row is None:
                raise ManifestNotFoundError(manifest_id)
            if row.state != ManifestState.PENDING.value:
                raise ManifestNotPendingError(manifest_id, row.state)
            # The previous one first: at most one manifest per version may be active.
            await connection.execute(
                update(manifests)
                .where(
                    manifests.c.library_id == row.library_id,
                    manifests.c.ref == row.ref,
                    manifests.c.state == ManifestState.ACTIVE.value,
                )
                .values(state=ManifestState.SUPERSEDED.value, superseded_at=_iso(at))
            )
            await connection.execute(
                update(manifests)
                .where(manifests.c.id == manifest_id)
                .values(state=ManifestState.ACTIVE.value)
            )
            moved = {"kind": row.kind, "commit_sha": row.commit_sha, "imported_at": at.isoformat()}
            await connection.execute(
                sqlite_insert(library_versions)
                .values(library_id=row.library_id, ref=row.ref, **moved)
                .on_conflict_do_update(
                    index_elements=[library_versions.c.library_id, library_versions.c.ref],
                    set_=moved,
                )
            )
        return Version(
            ref=VersionRef(row.ref),
            kind=RefKind(row.kind),
            commit_sha=row.commit_sha,
            imported_at=at,
        )

    async def discard_pending(self, manifest_id: ManifestId | None) -> int:
        """Delete one pending manifest, or every pending one for ``None``."""
        pending = delete(manifests).where(manifests.c.state == ManifestState.PENDING.value)
        if manifest_id is not None:
            pending = pending.where(manifests.c.id == manifest_id)
        async with self._write() as connection:
            return (await connection.execute(pending)).rowcount

    async def collect_garbage(self, *, superseded_before: datetime) -> GarbageCollected:
        """Delete manifests superseded before the cutoff, then contents no manifest uses."""
        async with self._write() as connection:
            old = await connection.execute(
                delete(manifests).where(
                    manifests.c.state == ManifestState.SUPERSEDED.value,
                    manifests.c.superseded_at < _iso(superseded_before),
                )
            )
            unused = await connection.execute(
                delete(article_contents).where(
                    ~exists().where(manifest_entries.c.blob_sha == article_contents.c.blob_sha)
                )
            )
        return GarbageCollected(manifests=old.rowcount, contents=unused.rowcount)

    async def _load(self, *where: ColumnElement[bool]) -> Manifest | None:
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(manifests).where(*where))).first()
            if row is None:
                return None
            entries = (
                await connection.execute(
                    select(manifest_entries)
                    .where(manifest_entries.c.manifest_id == row.id)
                    .order_by(manifest_entries.c.path)
                )
            ).all()
        return Manifest(
            id=ManifestId(row.id),
            library=LibraryId(row.library_id),
            ref=VersionRef(row.ref),
            kind=RefKind(row.kind),
            commit_sha=row.commit_sha,
            created_at=datetime.fromisoformat(row.created_at),
            entries=tuple(_entry(e) for e in entries),
            state=ManifestState(row.state),
            superseded_at=(
                datetime.fromisoformat(row.superseded_at) if row.superseded_at else None
            ),
        )
