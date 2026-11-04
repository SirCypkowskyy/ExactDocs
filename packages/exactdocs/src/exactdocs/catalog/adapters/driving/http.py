"""REST adapter for the catalog (consumed by the web UI)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from exactdocs.catalog.dtos import (
    Article,
    ArticleList,
    GetArticleQuery,
    GetLibraryQuery,
    LibraryDetail,
    LibraryList,
    Limit,
    ListArticlesQuery,
    ListLibrariesQuery,
    ResolvedVersion,
    ResolveVersionQuery,
)
from exactdocs.catalog.ports.driving import (
    GetArticle,
    GetLibrary,
    ListArticles,
    ListLibraries,
    ResolveVersion,
)
from exactdocs_kernel import DEFAULT_LIMIT


def build_router(
    *,
    list_libraries: ListLibraries,
    get_library: GetLibrary,
    resolve_version: ResolveVersion,
    list_articles: ListArticles,
    get_article: GetArticle,
) -> APIRouter:
    """Expose the catalog's driving ports under ``/libraries``."""
    router = APIRouter(prefix="/libraries", tags=["catalog"])

    @router.get("")
    async def list_all(query: Annotated[ListLibrariesQuery, Query()]) -> LibraryList:
        return await list_libraries(query)

    # Library IDs are `/owner/repo`; the ref comes last because it may contain slashes
    # (`release/1.4`) and the server decodes `%2F` before routing.
    @router.get("/{owner}/{repo}")
    async def get_one(owner: str, repo: str) -> LibraryDetail:
        return await get_library(GetLibraryQuery(id=f"/{owner}/{repo}"))

    @router.get("/{owner}/{repo}/versions/{ref:path}")
    async def get_version(owner: str, repo: str, ref: str) -> ResolvedVersion:
        if ref.endswith("/"):  # `/versions/v1.4.0/` is another URL, not a malformed ref
            raise HTTPException(status_code=404)
        return await resolve_version(ResolveVersionQuery(id=f"/{owner}/{repo}/{ref}"))

    # Both article routes take the ref as `?ref=` (it may contain `/`); no ref means the
    # default version. They come after `/versions/{ref:path}` and cannot be mistaken for it.
    @router.get("/{owner}/{repo}/articles")
    async def list_version_articles(
        owner: str,
        repo: str,
        ref: str | None = None,
        path_prefix: Annotated[
            str,
            Query(
                description=(
                    "Only paths inside this directory: `guide` matches `guide/install.md`, "
                    "not `guide-old/x.md`. Empty lists everything."
                )
            ),
        ] = "",
        limit: Limit = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> ArticleList:
        query = ListArticlesQuery(
            library=f"/{owner}/{repo}",
            ref=ref,
            path_prefix=path_prefix,
            limit=limit,
            cursor=cursor,
        )
        return await list_articles(query)

    @router.get("/{owner}/{repo}/article")
    async def get_one_article(
        owner: str, repo: str, path: Annotated[str, Query(min_length=1)], ref: str | None = None
    ) -> Article:
        return await get_article(GetArticleQuery(library=f"/{owner}/{repo}", ref=ref, path=path))

    return router
