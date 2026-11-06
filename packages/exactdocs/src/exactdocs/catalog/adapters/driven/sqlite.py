import json
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlalchemy import (
    Boolean,
    Column,
    ColumnElement,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Row,
    Select,
    Table,
    Text,
    and_,
    case,
    column,
    delete,
    exists,
    insert,
    literal,
    or_,
    select,
    text,
    tuple_,
    update,
    values,
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
    StoredContentOutdatedError,
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
    ManualTag,
    ManualTags,
    RefKind,
    RenameDirection,
    StoredArticle,
    StoredImage,
    TagMatch,
    TagSelection,
    Version,
    VersionOrigin,
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
    Column("pinned_version", Text),  # LIB-10: written only by `pin_default`, never by `save`
    Column("settings", Text, nullable=False),
    Column("title_edited", Boolean, nullable=False, server_default="0"),
    Column("description_edited", Boolean, nullable=False, server_default="0"),
    # LIB-06: a JSON list, written only by `follow_readme`, never by `save`
    Column("rules", Text, nullable=False, server_default="[]"),
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
    Column("origin", Text, nullable=False, server_default="manual"),  # set once, at creation
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
    Column("origin", Text, nullable=False, server_default="manual"),  # for a new version
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
    Column("tags", Text, nullable=False),  # JSON list: every tag (`ManifestEntry.all_tags`)
    Column("front_matter", Text, nullable=False),  # JSON object
    Column("size", Integer, nullable=False),
    # JSON list of {"tag", "path"}: path is where the tag was set (this one or an older name)
    Column("manual_tags", Text, nullable=False, server_default="[]"),
    Column("imported_tags", Text),  # JSON list; NULL without manual tags (then it is `tags`)
    ForeignKeyConstraint(
        ["blob_sha", "content_version"],
        ["catalog_article_contents.blob_sha", "catalog_article_contents.content_version"],
    ),
    # Created by migration 5f87041a0ed2; named here so the metadata says what the queries use:
    # garbage collection, and ``SqliteStoredArticles`` finding a file by its content.
    Index("ix_catalog_manifest_entries_content", "blob_sha", "content_version"),
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
manual_tags = Table(
    "catalog_manual_tags",
    metadata,
    Column(
        "library_id", Text, ForeignKey("catalog_libraries.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("path", Text, primary_key=True),
    Column("tags", Text, nullable=False),  # JSON list, never empty
)
image_blobs = Table(
    "catalog_image_blobs",
    metadata,
    Column("blob_sha", Text, primary_key=True),
    Column("content_type", Text, nullable=False),
    Column("data", LargeBinary, nullable=False),
)
manifest_images = Table(
    "catalog_manifest_images",
    metadata,
    Column(
        "manifest_id",
        Text,
        ForeignKey("catalog_manifests.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("path", Text, primary_key=True),
    Column("blob_sha", Text, ForeignKey("catalog_image_blobs.blob_sha"), nullable=False),
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
    libraries.c.pinned_version,
    libraries.c.rules,
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

    async def set_settings(self, library_id: LibraryId, settings: LibrarySettings) -> None:
        """Update only the settings column."""
        async with self.engine.begin() as connection:
            await connection.execute(
                update(libraries)
                .where(libraries.c.id == library_id.value)
                .values(settings=_SETTINGS.dump_json(settings).decode())
            )

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

    async def pin_default(self, library_id: LibraryId, ref: VersionRef | None) -> bool:
        """One UPDATE; with a ref it applies only while that version row exists."""
        where = [libraries.c.id == library_id.value]
        if ref is not None:
            where.append(
                exists().where(
                    library_versions.c.library_id == library_id.value,
                    library_versions.c.ref == ref.value,
                )
            )
        async with self.engine.begin() as connection:
            done = await connection.execute(
                update(libraries)
                .where(*where)
                .values(pinned_version=None if ref is None else ref.value)
            )
        return done.rowcount > 0

    async def follow_readme(
        self, library_id: LibraryId, *, title: str, description: str, rules: Sequence[str]
    ) -> None:
        """One UPDATE that keeps every field whose edited flag is set, and sets the rules."""
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
                    rules=json.dumps(list(rules)),
                )
            )

    async def get_manual_tags(self, library_id: LibraryId) -> Mapping[str, tuple[str, ...]]:
        """Return the library's manual tags by path."""
        query = select(manual_tags.c.path, manual_tags.c.tags).where(
            manual_tags.c.library_id == library_id.value
        )
        async with self.engine.connect() as connection:
            rows = await connection.execute(query)
            return {row.path: tuple(json.loads(row.tags)) for row in rows}

    async def set_manual_tags(self, library_id: LibraryId, tags: ManualTags) -> None:
        """Upsert the path's row, or delete it for no tags; the library's row must exist."""
        where = (manual_tags.c.library_id == library_id.value, manual_tags.c.path == tags.path)
        async with self.engine.begin() as connection:
            if not tags.tags:
                await connection.execute(delete(manual_tags).where(*where))
                return
            known = select(libraries.c.id).where(libraries.c.id == library_id.value)
            if (await connection.execute(known)).first() is None:
                return
            values = {"tags": json.dumps(tags.tags)}
            await connection.execute(
                sqlite_insert(manual_tags)
                .values(library_id=library_id.value, path=tags.path, **values)
                .on_conflict_do_update(
                    index_elements=[manual_tags.c.library_id, manual_tags.c.path], set_=values
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
                    origin=_origin(row.origin),
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
                pinned_version=VersionRef(row.pinned_version) if row.pinned_version else None,
                rules=tuple(json.loads(row.rules)),
            )
            for row in rows
        )


def _iso(moment: datetime) -> str:
    """UTC ISO 8601, so stored timestamps compare as text."""
    return moment.astimezone(UTC).isoformat()


def _entry(row: Row) -> ManifestEntry:
    imported = row.tags if row.imported_tags is None else row.imported_tags
    return ManifestEntry(
        path=row.path,
        blob_sha=row.blob_sha,
        content_version=row.content_version,
        title=row.title,
        tags=tuple(json.loads(imported)),
        front_matter=json.loads(row.front_matter),
        size=row.size,
        manual_tags=tuple(ManualTag(t["tag"], t["path"]) for t in json.loads(row.manual_tags)),
    )


def _tag_columns(entry: ManifestEntry) -> dict[str, str | None]:
    """Return the three tag columns of an entry row (see the table)."""
    return {
        "tags": json.dumps(entry.all_tags),
        "manual_tags": json.dumps([{"tag": t.tag, "path": t.path} for t in entry.manual_tags]),
        "imported_tags": json.dumps(entry.tags) if entry.manual_tags else None,
    }


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
        images: Mapping[str, StoredImage] | None = None,
        version_must_exist: bool = False,
    ) -> None:
        """Store a pending manifest, its texts and image blobs; stored ones stay as they are."""
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
            if images:
                await connection.execute(
                    sqlite_insert(image_blobs).on_conflict_do_nothing(),
                    [
                        {"blob_sha": sha, "content_type": i.content_type, "data": i.data}
                        for sha, i in images.items()
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
                    origin=manifest.origin.value,
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
                            "front_matter": json.dumps(e.front_matter),
                            "size": e.size,
                        }
                        | _tag_columns(e)
                        for e in manifest.entries
                    ],
                )
            if manifest.images:
                await connection.execute(
                    insert(manifest_images),
                    [
                        {"manifest_id": manifest.id, "path": i.path, "blob_sha": i.blob_sha}
                        for i in manifest.images
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

    async def find_rename(
        self,
        manifest_id: ManifestId,
        path: str,
        direction: RenameDirection = RenameDirection.FORWARD,
    ) -> ManifestRename | None:
        """Return the rename of the old path, or (``BACK``) the first one into the new path."""
        back = direction is RenameDirection.BACK
        column = manifest_renames.c.new_path if back else manifest_renames.c.old_path
        return await self._one_rename(manifest_id, column == path)

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

    async def replace_renames(
        self, manifest_id: ManifestId, renames: Sequence[ManifestRename]
    ) -> None:
        """Delete the manifest's renames, then add those into its entries; one transaction."""
        wanted = sorted({r.new_path for r in renames})
        async with self._write() as connection:
            await connection.execute(
                delete(manifest_renames).where(manifest_renames.c.manifest_id == manifest_id)
            )
            paths: set[str] = set()
            for start in range(0, len(wanted), 500):  # stay under SQLite's bound-variable limit
                rows = await connection.execute(
                    select(manifest_entries.c.path).where(
                        manifest_entries.c.manifest_id == manifest_id,
                        manifest_entries.c.path.in_(wanted[start : start + 500]),
                    )
                )
                paths.update(row.path for row in rows)
            kept: dict[str, ManifestRename] = {}
            for r in renames:
                if r.new_path in paths:
                    kept.setdefault(r.old_path, r)
            if kept:
                await connection.execute(
                    insert(manifest_renames),
                    [
                        {
                            "manifest_id": manifest_id,
                            "old_path": r.old_path,
                            "from_ref": r.from_ref.value,
                            "new_path": r.new_path,
                            "similarity": r.similarity,
                        }
                        for r in kept.values()
                    ],
                )

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

    async def list_live(self, library_id: LibraryId) -> Sequence[Manifest]:
        """Return the library's pending and active manifests, without entries."""
        query = select(manifests).where(
            manifests.c.library_id == library_id.value,
            manifests.c.state.in_([ManifestState.PENDING.value, ManifestState.ACTIVE.value]),
        )
        async with self.engine.connect() as connection:
            return tuple(_manifest(row) for row in await connection.execute(query))

    async def set_manual_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, tuple[ManualTag, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Read the entries that have or get manual tags, write those that change; one transaction.

        Entries without manual tags before or after are not read: on a large version only the
        few tagged ones cost anything.
        """
        entries = manifest_entries.c
        query = select(manifest_entries).where(
            entries.manifest_id == manifest_id,
            or_(entries.manual_tags != "[]", entries.path.in_(list(tags))),
        )
        touched: dict[str, tuple[str, ...]] = {}
        async with self._write() as connection:
            for row in (await connection.execute(query)).all():
                before = _entry(row)
                after = replace(before, manual_tags=tags.get(before.path, ()))
                touched[after.path] = after.all_tags
                if after != before:
                    await connection.execute(
                        update(manifest_entries)
                        .where(entries.manifest_id == manifest_id, entries.path == after.path)
                        .values(**_tag_columns(after))
                    )
        return touched

    async def get_active_many(
        self, versions: Sequence[tuple[LibraryId, VersionRef]]
    ) -> Mapping[tuple[LibraryId, VersionRef], Manifest]:
        """Return the active manifests (without entries) of these versions, by (library, ref)."""
        found: dict[tuple[LibraryId, VersionRef], Manifest] = {}
        async with self.engine.connect() as connection:
            for start in range(0, len(versions), 400):  # two bound variables per version
                batch = [(lib.value, ref.value) for lib, ref in versions[start : start + 400]]
                rows = await connection.execute(
                    select(manifests).where(
                        tuple_(manifests.c.library_id, manifests.c.ref).in_(batch),
                        manifests.c.state == ManifestState.ACTIVE.value,
                    )
                )
                for row in rows:
                    manifest = _manifest(row)
                    found[manifest.library, manifest.ref] = manifest
        return found

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

    async def get_image(
        self, library_id: LibraryId, ref: VersionRef, path: str, *, with_data: bool = True
    ) -> StoredImage | None:
        """Return the image at ``path`` of the version's active manifest, or ``None``."""
        joined = manifests.join(manifest_images, manifest_images.c.manifest_id == manifests.c.id)
        query = (
            select(
                image_blobs.c.blob_sha,
                image_blobs.c.content_type,
                image_blobs.c.data if with_data else literal(b"").label("data"),
            )
            .select_from(
                joined.join(image_blobs, image_blobs.c.blob_sha == manifest_images.c.blob_sha)
            )
            .where(
                manifests.c.library_id == library_id.value,
                manifests.c.ref == ref.value,
                manifests.c.state == ManifestState.ACTIVE.value,
                manifest_images.c.path == path,
            )
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        if row is None:
            return None
        return StoredImage(blob_sha=row.blob_sha, content_type=row.content_type, data=row.data)

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
                .values(library_id=row.library_id, ref=row.ref, origin=row.origin, **moved)
                .on_conflict_do_update(  # the origin stays the one the version was created with
                    index_elements=[library_versions.c.library_id, library_versions.c.ref],
                    set_=moved,
                )
            )
            return await _stored_version(connection, row)

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
        """Delete manifests superseded before the cutoff, then texts and images no manifest uses."""
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
            loose = await connection.execute(
                delete(image_blobs).where(
                    ~exists().where(manifest_images.c.blob_sha == image_blobs.c.blob_sha)
                )
            )
        return GarbageCollected(
            manifests=old.rowcount, contents=unused.rowcount, images=loose.rowcount
        )

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
            await connection.execute(
                update(libraries)
                .where(libraries.c.id == library_id.value, libraries.c.pinned_version == ref.value)
                .values(pinned_version=None)
            )
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
        origin=_origin(row.origin),
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
        origin=_origin(row.origin),
    )


def _origin(stored: str) -> VersionOrigin:
    """Read a stored origin; an unknown one (a newer release) counts as ``manual``: kept."""
    try:
        return VersionOrigin(stored)
    except ValueError:
        return VersionOrigin.MANUAL


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
                    "origin": v.origin.value,
                }
                for v in library.versions
            ],
        )


@dataclass(frozen=True, slots=True)
class SqliteImportedTags:
    """Implements ``ports.driven.ImportedTagWriter`` on the catalog's SQLite tables."""

    engine: AsyncEngine

    async def set_imported_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, tuple[str, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Read the named entries in batches, write those whose tags change; one transaction.

        Every named entry is reported, changed or not (see the port).
        """
        entries = manifest_entries.c
        paths = list(tags)
        touched: dict[str, tuple[str, ...]] = {}
        # BEGIN IMMEDIATE, as in ``SqliteManifestRepository._write``: it reads, then writes.
        async with self.engine.execution_options(begin_immediate=True).begin() as connection:
            for start in range(0, len(paths), _PATHS_PER_QUERY):
                rows = await connection.execute(
                    select(manifest_entries).where(
                        entries.manifest_id == manifest_id,
                        entries.path.in_(paths[start : start + _PATHS_PER_QUERY]),
                    )
                )
                for row in rows.all():
                    before = _entry(row)
                    after = replace(before, tags=tags[before.path])
                    touched[after.path] = after.all_tags
                    if after.tags != before.tags:
                        await connection.execute(
                            update(manifest_entries)
                            .where(entries.manifest_id == manifest_id, entries.path == after.path)
                            .values(**_tag_columns(after))
                        )
        return touched


_PATHS_PER_QUERY = 500  # bound variables per statement stay far below SQLite's limit


@dataclass(frozen=True, slots=True)
class SqliteStoredArticles:
    """Implements ``ports.driven.StoredArticleFinder`` on the catalog's SQLite tables."""

    engine: AsyncEngine

    async def find_articles(
        self,
        library_id: LibraryId,
        ref: VersionRef | None,
        content_version: int,
        files: Collection[tuple[str, str]],
    ) -> Sequence[StoredArticle]:
        """Look in the version's active manifest first, then in the library's other manifests.

        The first lookup goes by primary key (manifest, path): a re-sync finds most of its
        unchanged files there. The rest go by blob SHA through
        ``ix_catalog_manifest_entries_content`` (blob_sha, content_version; it exists for the
        garbage collection), one manifest per file (``LIMIT 1``), never once per manifest that
        holds them. Texts are read once per blob.
        """
        asked = set(files)
        found: dict[tuple[str, str], Row] = {}
        async with self.engine.connect() as connection:
            if ref is not None:
                active = await connection.scalar(
                    select(manifests.c.id).where(
                        manifests.c.library_id == library_id.value,
                        manifests.c.ref == ref.value,
                        manifests.c.state == ManifestState.ACTIVE.value,
                    )
                )
                if active is not None:
                    await self._collect(
                        connection, found, list(asked), _in_manifest(active, content_version)
                    )
            rest = [key for key in asked if key not in found]
            if rest:
                await self._collect(
                    connection, found, rest, _in_library(library_id, content_version)
                )
            texts = await _texts(connection, {sha for _, sha in found}, content_version)
        return [
            StoredArticle(
                manifest_id=ManifestId(row.id),
                commit_sha=row.commit_sha,
                entry=_entry(row),
                content=texts[row.blob_sha],
            )
            for row in found.values()
        ]

    @staticmethod
    async def _collect(
        connection: AsyncConnection,
        found: dict[tuple[str, str], Row],
        files: Sequence[tuple[str, str]],
        query: Callable[[Sequence[tuple[str, str]]], Select],
    ) -> None:
        for start in range(0, len(files), _FILES_PER_QUERY):
            rows = await connection.execute(query(files[start : start + _FILES_PER_QUERY]))
            for row in rows.all():
                found.setdefault((row.path, row.blob_sha), row)


def _in_manifest(
    manifest_id: str, content_version: int
) -> Callable[[Sequence[tuple[str, str]]], Select]:
    """Entries of one manifest, by primary key: ``(manifest_id, path)``."""
    entries = manifest_entries.c

    def query(files: Sequence[tuple[str, str]]) -> Select:
        return (
            select(manifests.c.id, manifests.c.commit_sha, manifest_entries)
            .select_from(manifests.join(manifest_entries, entries.manifest_id == manifests.c.id))
            .where(
                manifests.c.id == manifest_id,
                entries.content_version == content_version,
                entries.path.in_({path for path, _ in files}),
                tuple_(entries.path, entries.blob_sha).in_(files),
            )
        )

    return query


def _in_library(
    library_id: LibraryId, content_version: int
) -> Callable[[Sequence[tuple[str, str]]], Select]:
    """One entry per file among the library's manifests: the first one found by blob SHA.

    Each file picks one manifest with a correlated ``LIMIT 1`` over
    ``ix_catalog_manifest_entries_content``, so a file the library holds in hundreds of
    manifests costs one index probe, not one row per manifest.
    """
    entries = manifest_entries.c

    def query(files: Sequence[tuple[str, str]]) -> Select:
        # A CTE: SQLite cannot name the columns of a VALUES subquery (``AS wanted (path, ...)``).
        wanted = (
            values(column("path", Text), column("blob_sha", Text), name="wanted")
            .data(list(files))
            .cte("wanted")
        )
        pick = (
            select(entries.manifest_id)
            .select_from(manifest_entries.join(manifests, manifests.c.id == entries.manifest_id))
            .where(
                entries.blob_sha == wanted.c.blob_sha,
                entries.content_version == content_version,
                entries.path == wanted.c.path,
                manifests.c.library_id == library_id.value,
            )
            .limit(1)
            .scalar_subquery()
        )
        first = select(wanted.c.path, wanted.c.blob_sha, pick.label("manifest_id")).subquery()
        return select(manifests.c.id, manifests.c.commit_sha, manifest_entries).select_from(
            first.join(
                manifest_entries,
                and_(
                    entries.manifest_id == first.c.manifest_id,
                    entries.path == first.c.path,
                ),
            ).join(manifests, manifests.c.id == entries.manifest_id)
        )

    return query


async def _texts(
    connection: AsyncConnection, shas: Collection[str], content_version: int
) -> dict[str, str]:
    asked, texts = list(shas), {}
    for start in range(0, len(asked), _PATHS_PER_QUERY):
        rows = await connection.execute(
            select(article_contents.c.blob_sha, article_contents.c.content).where(
                article_contents.c.content_version == content_version,
                article_contents.c.blob_sha.in_(asked[start : start + _PATHS_PER_QUERY]),
            )
        )
        texts |= {row.blob_sha: row.content for row in rows.all()}
    return texts


_FILES_PER_QUERY = 250  # three bound variables per file at most


@dataclass(frozen=True, slots=True)
class SqliteManifestCopier:
    """Implements ``ports.driven.ManifestCopier`` on the catalog's SQLite tables."""

    engine: AsyncEngine

    async def copy_active(
        self,
        library_id: LibraryId,
        ref: VersionRef,
        new_id: ManifestId,
        *,
        at: datetime,
        content_version: int,
    ) -> tuple[Manifest, Sequence[StoredArticle]] | None:
        """Copy the rows of the active manifest with ``INSERT ... SELECT``; one transaction."""
        # BEGIN IMMEDIATE, as in ``SqliteManifestRepository._write``: it reads, then writes.
        async with self.engine.execution_options(begin_immediate=True).begin() as connection:
            row = (
                await connection.execute(
                    select(manifests).where(
                        manifests.c.library_id == library_id.value,
                        manifests.c.ref == ref.value,
                        manifests.c.state == ManifestState.ACTIVE.value,
                    )
                )
            ).first()
            if row is None:
                return None
            outdated = await connection.execute(
                select(literal(1)).where(
                    manifest_entries.c.manifest_id == row.id,
                    manifest_entries.c.content_version != content_version,
                )
            )
            if outdated.first() is not None:
                raise StoredContentOutdatedError(str(library_id), str(ref))
            await connection.execute(
                insert(manifests).values(
                    id=new_id,
                    library_id=row.library_id,
                    ref=row.ref,
                    kind=row.kind,
                    commit_sha=row.commit_sha,
                    state=ManifestState.PENDING.value,
                    created_at=_iso(at),
                    origin=row.origin,
                )
            )
            for table in (manifest_entries, manifest_images, manifest_renames):
                columns = [c for c in table.c if c.name != "manifest_id"]
                await connection.execute(
                    insert(table).from_select(
                        ["manifest_id", *(c.name for c in columns)],
                        select(literal(new_id), *columns).where(table.c.manifest_id == row.id),
                    )
                )
            rows = await connection.execute(
                select(manifest_entries, article_contents.c.content)
                .select_from(
                    manifest_entries.join(
                        article_contents,
                        and_(
                            article_contents.c.blob_sha == manifest_entries.c.blob_sha,
                            article_contents.c.content_version
                            == manifest_entries.c.content_version,
                        ),
                    )
                )
                .where(manifest_entries.c.manifest_id == new_id)
                .order_by(manifest_entries.c.path)
            )
            articles = tuple(
                StoredArticle(
                    manifest_id=new_id,
                    commit_sha=row.commit_sha,
                    entry=_entry(r),
                    content=r.content,
                )
                for r in rows
            )
        copy = replace(
            _manifest(row),
            id=new_id,
            created_at=at,
            state=ManifestState.PENDING,
            superseded_at=None,
        )
        return copy, articles
