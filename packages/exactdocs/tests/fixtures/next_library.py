"""A Next.js library with one imported version, for the context7 contract tests."""

import hashlib

from exactdocs.bootstrap.container import Container
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, VersionRef
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand

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
