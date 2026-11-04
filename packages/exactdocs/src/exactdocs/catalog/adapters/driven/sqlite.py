import json
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlalchemy import (
    Boolean,
    Column,
    ColumnElement,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    Row,
    Table,
    Text,
    and_,
    case,
    delete,
    exists,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.sql.elements import TextClause

from exactdocs.catalog.errors import (
    LibraryAlreadyExistsError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    ManifestNotPendingError,
    ManifestOutdatedError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    ContentKey,
    GarbageCollected,
    HostKind,
    Library,
    LibraryId,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestRename,
    ManifestState,
    RefKind,
    StoredArticle,
    TagMatch,
    TagSelection,
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
    Column("title_edited", Boolean, nullable=False, server_default="0"),
    Column("description_edited", Boolean, nullable=False, server_default="0"),
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
    Column("content_version", Integer, primary_key=True),
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
    Column("blob_sha", Text, nullable=False),
    Column("content_version", Integer, nullable=False),
    Column("title", Text, nullable=False),
    Column("tags", Text, nullable=False),  # JSON list
    Column("front_matter", Text, nullable=False),  # JSON object
    Column("size", Integer, nullable=False),
    ForeignKeyConstraint(
        ["blob_sha", "content_version"],
        ["catalog_article_contents.blob_sha", "catalog_article_contents.content_version"],
    ),
)

manifest_renames = Table(
    "catalog_manifest_renames",
    metadata,
    Column(
        "manifest_id",
        Text,
        ForeignKey("catalog_manifests.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("old_path", Text, primary_key=True),
    Column("from_ref", Text, nullable=False),
    Column("new_path", Text, nullable=False),
    Column("similarity", Integer, nullable=False),
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
    libraries.c.title_edited,
    libraries.c.description_edited,
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

    async def add(self, library: Library) -> None:
        """Insert the library; the primary key decides whether the ID is taken."""
        try:
            async with self.engine.begin() as connection:
                await connection.execute(
                    insert(libraries).values(id=library.id.value, **_library_values(library))
                )
                await _insert_versions(connection, library)
        except IntegrityError:
            raise LibraryAlreadyExistsError(library.id.value) from None

    async def delete(self, library_id: LibraryId) -> None:
        """Remove the library; its versions and manifests go with it (foreign keys cascade)."""
        async with self.engine.begin() as connection:
            await connection.execute(delete(libraries).where(libraries.c.id == library_id.value))

    async def save(self, library: Library) -> None:
        """Store the library; versions it already has are kept as they are, new ones are added.

        Activating a manifest also writes version rows, so a library saved from an older read
        must not overwrite or drop them: existing rows are left alone (insert or ignore).
        """
        async with self.engine.begin() as connection:
            values = _library_values(library)
            await connection.execute(
                sqlite_insert(libraries)
                .values(id=library.id.value, **values)
                .on_conflict_do_update(index_elements=[libraries.c.id], set_=values)
            )
            await _insert_versions(connection, library)

    async def set_text(
        self, library_id: LibraryId, *, title: str | None, description: str | None
    ) -> None:
        """Update only the given columns and their edited flags."""
        values: dict[str, str | bool] = {}
        if title is not None:
            values |= {"title": title, "title_edited": True}
        if description is not None:
            values |= {"description": description, "description_edited": True}
        if not values:
            return
        async with self.engine.begin() as connection:
            await connection.execute(
                update(libraries).where(libraries.c.id == library_id.value).values(**values)
            )

    async def follow_readme(self, library_id: LibraryId, *, title: str, description: str) -> None:
        """One UPDATE that keeps every field whose edited flag is set."""
        async with self.engine.begin() as connection:
            await connection.execute(
                update(libraries)
                .where(libraries.c.id == library_id.value)
                .values(
                    title=case((libraries.c.title_edited, libraries.c.title), else_=title),
                    description=case(
                        (libraries.c.description_edited, libraries.c.description),
                        else_=description,
                    ),
                )
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
                title_edited=row.title_edited,
                description_edited=row.description_edited,
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
        content_version=row.content_version,
        title=row.title,
        tags=tuple(json.loads(row.tags)),
        front_matter=json.loads(row.front_matter),
        size=row.size,
    )


# ponytail: a correlated json_each per row of the manifest, so a sparse tag on a huge manifest
# scans it all; upgrade to a catalog_manifest_entry_tags(manifest_id, tag, path) side table.
_HAS_ANY_TAG = text(
    "EXISTS (SELECT 1 FROM json_each(catalog_manifest_entries.tags)"
    " WHERE value IN (SELECT value FROM json_each(:tags)))"
)
_HAS_ALL_TAGS = text(
    "NOT EXISTS (SELECT 1 FROM json_each(:tags)"
    " WHERE value NOT IN (SELECT value FROM json_each(catalog_manifest_entries.tags)))"
)


def _tag_condition(selection: TagSelection) -> TextClause:
    """Match the tags JSON list of the entry against the filter's, inside SQLite."""
    condition = _HAS_ALL_TAGS if selection.match is TagMatch.ALL else _HAS_ANY_TAG
    return condition.bindparams(tags=json.dumps(sorted(selection.tags)))


@dataclass(frozen=True, slots=True)
class SqliteManifestRepository:
    """Implements ``ports.driven.ManifestRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    def _write(self) -> AbstractAsyncContextManager[AsyncConnection]:
        # BEGIN IMMEDIATE: a transaction that reads before it writes takes the write lock up
        # front instead of failing with "database is locked" when it upgrades later.
        return self.engine.execution_options(begin_immediate=True).begin()

    async def add(
        self,
        manifest: Manifest,
        contents: Mapping[ContentKey, str],
        *,
        version_must_exist: bool = False,
    ) -> None:
        """Store a pending manifest and the texts it needs; stored texts stay as they are."""
        async with self._write() as connection:
            if version_must_exist:
                found = await connection.execute(
                    select(library_versions.c.ref).where(
                        library_versions.c.library_id == manifest.library.value,
                        library_versions.c.ref == manifest.ref.value,
                    )
                )
                if found.first() is None:
                    raise VersionNotFoundError(str(manifest.library), str(manifest.ref))
            if contents:
                await connection.execute(
                    sqlite_insert(article_contents).on_conflict_do_nothing(),
                    [
                        {"blob_sha": sha, "content_version": version, "content": text}
                        for (sha, version), text in contents.items()
                    ],
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
                            "content_version": e.content_version,
                            "title": e.title,
                            "tags": json.dumps(e.tags),
                            "front_matter": json.dumps(e.front_matter),
                            "size": e.size,
                        }
                        for e in manifest.entries
                    ],
                )

            if manifest.renames:
                await connection.execute(
                    insert(manifest_renames),
                    [
                        {
                            "manifest_id": manifest.id,
                            "old_path": r.old_path,
                            "from_ref": r.from_ref.value,
                            "new_path": r.new_path,
                            "similarity": r.similarity,
                        }
                        for r in manifest.renames
                    ],
                )

    async def find_rename(self, manifest_id: ManifestId, old_path: str) -> ManifestRename | None:
        """Return the rename of ``old_path`` stored with the manifest, or ``None``."""
        return await self._one_rename(manifest_id, manifest_renames.c.old_path == old_path)

    async def find_rename_to(self, manifest_id: ManifestId, new_path: str) -> ManifestRename | None:
        """Return the rename that made ``new_path`` (the first by old path), or ``None``."""
        return await self._one_rename(manifest_id, manifest_renames.c.new_path == new_path)

    async def list_renames(
        self, manifest_id: ManifestId, *, limit: int
    ) -> Sequence[ManifestRename]:
        """Return up to ``limit`` renames of the manifest, sorted by old path."""
        async with self.engine.connect() as connection:
            rows = await connection.execute(
                select(manifest_renames)
                .where(manifest_renames.c.manifest_id == manifest_id)
                .order_by(manifest_renames.c.old_path)
                .limit(limit)
            )
            return tuple(_rename(row) for row in rows)

    async def _one_rename(
        self, manifest_id: ManifestId, *where: ColumnElement[bool]
    ) -> ManifestRename | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(manifest_renames)
                    .where(manifest_renames.c.manifest_id == manifest_id, *where)
                    .order_by(manifest_renames.c.old_path)
                    .limit(1)
                )
            ).first()
        return None if row is None else _rename(row)

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest without its entries, or ``None``."""
        return await self._load(manifests.c.id == manifest_id)

    async def get_many(self, manifest_ids: Collection[ManifestId]) -> Mapping[ManifestId, Manifest]:
        """Return the manifests (without entries) that exist, by ID; unknown IDs are left out."""
        ids = list(manifest_ids)
        found: dict[ManifestId, Manifest] = {}
        async with self.engine.connect() as connection:
            for start in range(0, len(ids), 500):  # stay under SQLite's bound-variable limit
                query = select(manifests).where(manifests.c.id.in_(ids[start : start + 500]))
                for row in await connection.execute(query):
                    found[ManifestId(row.id)] = _manifest(row)
        return found

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the version's active manifest without its entries, or ``None``."""
        return await self._load(
            manifests.c.library_id == library_id.value,
            manifests.c.ref == ref.value,
            manifests.c.state == ManifestState.ACTIVE.value,
        )

    async def list_entries(
        self,
        manifest_id: ManifestId,
        *,
        prefix: str,
        tags: TagSelection,
        after: str | None,
        limit: int,
    ) -> Sequence[ManifestEntry]:
        """Return up to ``limit`` entries inside ``prefix`` sorted by path, after the path."""
        query = select(manifest_entries).where(manifest_entries.c.manifest_id == manifest_id)
        path = manifest_entries.c.path
        if prefix:
            # Range scan on the primary key, no LIKE: "guide/" <= path < "guide0" ('0' follows '/').
            query = query.where(
                or_(path == prefix, and_(path >= f"{prefix}/", path < f"{prefix}0"))
            )
        if tags.tags:
            query = query.where(_tag_condition(tags))
        if after is not None:
            query = query.where(path > after)
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query.order_by(path).limit(limit))).all()
        return tuple(_entry(row) for row in rows)

    async def list_paths(self, manifest_id: ManifestId, *, limit: int) -> Sequence[str]:
        """Return up to ``limit`` article paths of the manifest, sorted."""
        query = (
            select(manifest_entries.c.path)
            .where(manifest_entries.c.manifest_id == manifest_id)
            .order_by(manifest_entries.c.path)
            .limit(limit)
        )
        async with self.engine.connect() as connection:
            return tuple((await connection.execute(query)).scalars())

    async def count_tags(self, manifest_id: ManifestId, *, limit: int) -> Sequence[tuple[str, int]]:
        """Return up to ``limit`` ``(tag, article count)`` pairs, most used first, then by name."""
        # ponytail: scans the manifest's entries; add a tag side table with the one planned for
        # the tag filter (see `_tag_condition`) when versions are large enough to notice.
        query = text(
            "SELECT tag.value AS name, COUNT(DISTINCT e.path) AS n"
            " FROM catalog_manifest_entries e, json_each(e.tags) AS tag"
            " WHERE e.manifest_id = :manifest_id"
            " GROUP BY tag.value ORDER BY n DESC, name LIMIT :limit"
        )
        async with self.engine.connect() as connection:
            rows = await connection.execute(query, {"manifest_id": manifest_id, "limit": limit})
            return tuple((row.name, row.n) for row in rows)

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
                ).join(
                    article_contents,
                    and_(
                        article_contents.c.blob_sha == manifest_entries.c.blob_sha,
                        article_contents.c.content_version == manifest_entries.c.content_version,
                    ),
                )
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
            if row.state == ManifestState.ACTIVE.value:  # a replay: already done
                return await _stored_version(connection, row)
            if row.state != ManifestState.PENDING.value:
                raise ManifestNotPendingError(manifest_id, row.state)
            same_version = (
                manifests.c.library_id == row.library_id,
                manifests.c.ref == row.ref,
                manifests.c.state == ManifestState.ACTIVE.value,
            )
            newer = await connection.execute(
                select(manifests.c.id).where(*same_version, manifests.c.created_at > row.created_at)
            )
            if newer.first() is not None:
                raise ManifestOutdatedError(manifest_id)
            # The previous one first: at most one manifest per version may be active.
            await connection.execute(
                update(manifests)
                .where(*same_version)
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

    async def discard_pending(
        self,
        *,
        manifest_id: ManifestId | None,
        library_id: LibraryId | None,
        created_before: datetime | None,
    ) -> int:
        """Delete the pending manifests that match every given filter."""
        doomed = delete(manifests).where(manifests.c.state == ManifestState.PENDING.value)
        if manifest_id is not None:
            doomed = doomed.where(manifests.c.id == manifest_id)
        if library_id is not None:
            doomed = doomed.where(manifests.c.library_id == library_id.value)
        if created_before is not None:
            doomed = doomed.where(manifests.c.created_at < _iso(created_before))
        async with self._write() as connection:
            return (await connection.execute(doomed)).rowcount

    async def collect_garbage(self, *, superseded_before: datetime) -> GarbageCollected:
        """Delete manifests superseded before the cutoff, then texts no manifest uses."""
        async with self._write() as connection:
            old = await connection.execute(
                delete(manifests).where(
                    manifests.c.state == ManifestState.SUPERSEDED.value,
                    manifests.c.superseded_at < _iso(superseded_before),
                )
            )
            unused = await connection.execute(
                delete(article_contents).where(
                    ~exists().where(
                        manifest_entries.c.blob_sha == article_contents.c.blob_sha,
                        manifest_entries.c.content_version == article_contents.c.content_version,
                    )
                )
            )
        return GarbageCollected(manifests=old.rowcount, contents=unused.rowcount)

    async def remove_version(self, library_id: LibraryId, ref: VersionRef) -> Sequence[ManifestId]:
        """Delete the version row and the manifests of the ref (their entries cascade)."""
        async with self._write() as connection:
            version = (
                library_versions.c.library_id == library_id.value,
                library_versions.c.ref == ref.value,
            )
            gone = await connection.execute(delete(library_versions).where(*version))
            if gone.rowcount == 0:
                raise VersionNotFoundError(str(library_id), str(ref))
            ids = await connection.execute(
                delete(manifests)
                .where(manifests.c.library_id == library_id.value, manifests.c.ref == ref.value)
                .returning(manifests.c.id)
            )
            return [ManifestId(row.id) for row in ids]

    async def remove_library(self, library_id: LibraryId) -> Sequence[ManifestId]:
        """Delete the library; its versions, manifests and entries cascade."""
        async with self._write() as connection:
            ids = [
                ManifestId(row.id)
                for row in await connection.execute(
                    select(manifests.c.id).where(manifests.c.library_id == library_id.value)
                )
            ]
            gone = await connection.execute(
                delete(libraries).where(libraries.c.id == library_id.value)
            )
            if gone.rowcount == 0:
                raise LibraryNotFoundError(str(library_id))
            return ids

    async def _load(self, *where: ColumnElement[bool]) -> Manifest | None:
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(manifests).where(*where))).first()
        if row is None:
            return None
        return _manifest(row)


def _rename(row: Row) -> ManifestRename:
    return ManifestRename(
        from_ref=VersionRef(row.from_ref),
        old_path=row.old_path,
        new_path=row.new_path,
        similarity=row.similarity,
    )


def _manifest(row: Row) -> Manifest:
    return Manifest(
        id=ManifestId(row.id),
        library=LibraryId(row.library_id),
        ref=VersionRef(row.ref),
        kind=RefKind(row.kind),
        commit_sha=row.commit_sha,
        created_at=datetime.fromisoformat(row.created_at),
        state=ManifestState(row.state),
        superseded_at=(datetime.fromisoformat(row.superseded_at) if row.superseded_at else None),
    )


async def _stored_version(connection: AsyncConnection, manifest: Row) -> Version:
    row = (
        await connection.execute(
            select(library_versions).where(
                library_versions.c.library_id == manifest.library_id,
                library_versions.c.ref == manifest.ref,
            )
        )
    ).one()
    return Version(
        ref=VersionRef(row.ref),
        kind=RefKind(row.kind),
        commit_sha=row.commit_sha,
        imported_at=datetime.fromisoformat(row.imported_at),
    )


def _library_values(library: Library) -> dict[str, str | bool | None]:
    return {
        "title": library.title,
        "description": library.description,
        "source_url": library.source_url,
        "host": library.host.value,
        "default_branch": None if library.default_branch is None else library.default_branch.value,
        "settings": _SETTINGS.dump_json(library.settings).decode(),
        "title_edited": library.title_edited,
        "description_edited": library.description_edited,
    }


async def _insert_versions(connection: AsyncConnection, library: Library) -> None:
    """Add the library's versions; rows that exist are left alone (insert or ignore)."""
    if library.versions:
        await connection.execute(
            sqlite_insert(library_versions).on_conflict_do_nothing(),
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
