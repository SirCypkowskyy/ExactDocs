"""Replay of a recorded context7 session: both tools, the arguments a real client sent."""

import hashlib
import json
from pathlib import Path

from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, VersionRef
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand
from exactdocs_kernel import NOTICE

SESSION = json.loads(
    (Path(__file__).parents[1] / "contracts" / "context7" / "session.json").read_text("utf-8")
)
LIBRARY = "/vercel/next.js"
REF = "v15.1.8"
PATH = "docs/app/building-your-application/routing/middleware.mdx"
MIDDLEWARE = (
    "Use middleware to protect routes: check the session, then redirect.\n\n"
    "```typescript\nexport const config = { matcher: ['/dashboard/:path*'] }\n```"
)


async def import_next(container: Container) -> None:
    await SqliteLibraryRepository(container.engine).save(
        Library(
            id=LibraryId(LIBRARY),
            title="Next.js",
            description="The React framework",
            source_url="https://github.com/vercel/next.js",
            host=HostKind.GITHUB,
            default_branch=VersionRef("canary"),
        )
    )
    blob = hashlib.sha1(PATH.encode(), usedforsecurity=False).hexdigest()
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=LIBRARY,
            ref=REF,
            kind=RefKind.TAG,
            commit_sha="c" * 40,
            articles=[
                ArticleIn(
                    path=PATH,
                    blob_sha=blob,
                    content_version=1,
                    title="Middleware",
                    tags=[],
                    content="# Middleware",
                )
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=LIBRARY,
            ref=REF,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=PATH,
                    blob_sha=blob,
                    chunks=[
                        ChunkIn(
                            heading_path=["Middleware"],
                            occurrence_index=0,
                            content=MIDDLEWARE,
                            content_hash="h",
                            anchor="middleware",
                            code_languages=["typescript"],
                        )
                    ],
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def test_a_recorded_context7_session_runs_without_errors() -> None:
    container = Container.build(Settings())
    async with container.running(), Client(build_mcp(container)) as mcp:
        await import_next(container)
        results = [await mcp.call_tool(c["tool"], c["arguments"]) for c in SESSION["calls"]]

    assert [r.is_error for r in results] == [False] * len(SESSION["calls"])
    assert all(r.content[0].text == NOTICE for r in results)
    resolved = results[0].content[1].text
    # The ID the first call hands out is the one the recorded client then queries.
    assert f"- Context7-compatible library ID: {LIBRARY}\n" in resolved
    for docs in results[1:]:
        assert MIDDLEWARE in docs.content[1].text
