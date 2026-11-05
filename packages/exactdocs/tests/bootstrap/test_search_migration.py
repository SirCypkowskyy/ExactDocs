"""The search revision over a database that already holds chunks, and what VACUUM does to it."""

import json
from pathlib import Path

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from exactdocs.bootstrap.database import alembic_config
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs.retrieval.models import TagFilter

BEFORE, AFTER = "c4d8e2f6a1b7", "a91c4e7b3d02"


def _alembic(connection, action: str, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


async def _engine(tmp_path: Path) -> AsyncEngine:
    return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")


async def test_chunks_stored_before_the_revision_are_searchable_after_it(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    async with engine.begin() as connection:
        await connection.run_sync(_alembic, "upgrade", BEFORE)
        await connection.execute(
            text("INSERT INTO retrieval_manifests VALUES ('m1', '/a/b/main', '/a/b', '2026-11-04')")
        )
        await connection.execute(text("INSERT INTO retrieval_chunk_sets VALUES ('b', 'c', 'd')"))
        for position, content in enumerate(["The retry_policy setting.", "Other words."]):
            await connection.execute(
                text(
                    "INSERT INTO retrieval_chunks VALUES ('b', 'c', :p, :h, 0, :c, 'x', 'a', '[]')"
                ),
                {"p": position, "h": json.dumps(["Doc"]), "c": content},
            )
            await connection.execute(
                text(
                    "INSERT INTO retrieval_manifest_chunks VALUES "
                    "('m1', :id, 'a.md', :p, 2, NULL, NULL, '[]', 'b', 'c')"
                ),
                {"id": f"chunk{position}", "p": position},
            )
        await connection.run_sync(_alembic, "upgrade", AFTER)

    hits = await SqliteSearchIndex(engine).search("m1", "retry_policy", TagFilter(), 5)

    assert [h.chunk_id for h in hits] == ["chunk0"]
    async with engine.begin() as connection:
        await connection.run_sync(_alembic, "downgrade", BEFORE)
        kept = (
            await connection.execute(text("SELECT count(*) FROM retrieval_chunks"))
        ).scalar_one()
    assert kept == 2
    await engine.dispose()


async def test_search_still_finds_the_right_chunk_after_vacuum(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    async with engine.begin() as connection:
        await connection.run_sync(_alembic, "upgrade", AFTER)
        await connection.execute(
            text("INSERT INTO retrieval_manifests VALUES ('m1', '/a/b/main', '/a/b', '2026-11-04')")
        )
        for blob in ("b0", "b1", "b2"):
            await connection.execute(
                text("INSERT INTO retrieval_chunk_sets VALUES (:b, 'c', 'd')"), {"b": blob}
            )
            await connection.execute(
                text(
                    "INSERT INTO retrieval_chunks (blob_sha, config_hash, position, heading_path, "
                    "occurrence_index, content, content_hash, anchor, code_languages) "
                    "VALUES (:b, 'c', 0, '[]', 0, :c, 'x', 'a', '[]')"
                ),
                {"b": blob, "c": f"word{blob}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO retrieval_manifest_chunks VALUES "
                    "('m1', :id, 'a.md', 0, 1, NULL, NULL, '[]', :b, 'c')"
                ),
                {"id": f"chunk-{blob}", "b": blob},
            )
            rowid = (
                await connection.execute(
                    text("SELECT id FROM retrieval_chunks WHERE blob_sha = :b"), {"b": blob}
                )
            ).scalar_one()
            await connection.execute(
                text(
                    "INSERT INTO retrieval_search (rowid, heading, text, identifiers) "
                    "VALUES (:r, '', :c, :c)"
                ),
                {"r": rowid, "c": f"word{blob}"},
            )
        await connection.execute(text("DELETE FROM retrieval_chunk_sets WHERE blob_sha = 'b0'"))
    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.exec_driver_sql("VACUUM")

    hits = await SqliteSearchIndex(engine).search("m1", "wordb2", TagFilter(), 5)

    assert [h.chunk_id for h in hits] == ["chunk-b2"]
    await engine.dispose()


MIDDLE = "3b8f0d6e2a71"


async def test_the_path_revision_reindexes_nested_headings_and_round_trips(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    sections = [
        (["Guide", "Docker"], "Pull the image, then docker run it."),
        (["Guide", "Docker", "Troubleshooting"], "If the port is taken, pick another one."),
        (["Guide", "Other"], "Unrelated words."),
    ]
    async with engine.begin() as connection:
        await connection.run_sync(_alembic, "upgrade", MIDDLE)
        await connection.execute(
            text("INSERT INTO retrieval_manifests VALUES ('m1', '/a/b/main', '/a/b', '2026-11-04')")
        )
        await connection.execute(text("INSERT INTO retrieval_chunk_sets VALUES ('b', 'c', 'd')"))
        for position, (heading_path, content) in enumerate(sections):
            await connection.execute(
                text(
                    "INSERT INTO retrieval_chunks (blob_sha, config_hash, position, heading_path,"
                    " occurrence_index, content, content_hash, anchor, code_languages)"
                    " VALUES ('b', 'c', :p, :h, 0, :c, 'x', 'a', '[]')"
                ),
                {"p": position, "h": json.dumps(heading_path), "c": content},
            )
            await connection.execute(
                text(
                    "INSERT INTO retrieval_manifest_chunks VALUES "
                    "('m1', :id, 'a.md', :p, 3, NULL, NULL, '[]', 'b', 'c')"
                ),
                {"id": f"chunk{position}", "p": position},
            )
        await connection.run_sync(_alembic, "upgrade", AFTER)

    async def first(query: str) -> str:
        hits = await SqliteSearchIndex(engine).search("m1", query, TagFilter(), 5)
        return hits[0].chunk_id

    assert await first("docker") == "chunk0"  # the own heading beats the child under it
    assert await first("docker troubleshooting") == "chunk1"  # the ancestors still count

    async def entries() -> int:
        async with engine.connect() as connection:
            return (
                await connection.execute(text("SELECT count(*) FROM retrieval_search"))
            ).scalar_one()

    assert await entries() == 3
    async with engine.begin() as connection:  # the delete trigger survived the rebuild
        await connection.execute(text("DELETE FROM retrieval_chunks"))
    assert await entries() == 0

    async with engine.begin() as connection:  # downgrade and upgrade again
        await connection.run_sync(_alembic, "downgrade", MIDDLE)
        await connection.run_sync(_alembic, "upgrade", AFTER)
    await engine.dispose()


FORMAT_REVISION = "d4f8b2c6e9a3"


async def test_the_format_revision_records_the_format_the_index_was_built_in(
    tmp_path: Path,
) -> None:
    engine = await _engine(tmp_path)
    async with engine.begin() as connection:
        await connection.run_sync(_alembic, "upgrade", FORMAT_REVISION)

    state = await SqliteSearchIndex(engine).state()

    assert (state.stored_format, state.needs_rebuild) == (2, False)
    async with engine.begin() as connection:
        await connection.run_sync(_alembic, "downgrade", AFTER)
        await connection.run_sync(_alembic, "upgrade", FORMAT_REVISION)
    await engine.dispose()
