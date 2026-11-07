"""REST adapter for the catalog (consumed by the web UI)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from exactdocs.catalog.constants import _ASSET_HEADERS, _SVG
from exactdocs.catalog.dtos import (
    Article,
    ArticleList,
    DefaultVersionPin,
    GetArticleQuery,
    GetAssetQuery,
    GetLibraryQuery,
    LibraryDetail,
    LibraryList,
    LibraryPatch,
    Limit,
    ListArticlesQuery,
    ListLibrariesQuery,
    ListTagsQuery,
    PinDefaultVersionCommand,
    RenameAnswer,
    RenameDirection,
    ResolvedVersion,
    ResolveRenamedPathQuery,
    ResolveVersionQuery,
    TagFilter,
    TagList,
    UpdateLibraryCommand,
)
from exactdocs.catalog.models import TagMatch
from exactdocs.catalog.ports.driving import (
    GetArticle,
    GetAsset,
    GetLibrary,
    ListArticles,
    ListLibraries,
    ListTags,
    PinDefaultVersion,
    ResolveRenamedPath,
    ResolveVersion,
    UpdateLibrary,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_PATH, MAX_TAG_LENGTH, MAX_TAGS


def build_router(
    *,
    list_libraries: ListLibraries,
    get_library: GetLibrary,
    resolve_version: ResolveVersion,
    list_articles: ListArticles,
    list_tags: ListTags,
    get_article: GetArticle,
    resolve_renamed_path: ResolveRenamedPath,
    get_asset: GetAsset,
    update_library: UpdateLibrary,
    pin_default_version: PinDefaultVersion,
) -> APIRouter:
    """Expose the catalog's driving ports under ``/libraries``."""
    router = APIRouter(prefix="/libraries", tags=["catalog"])
    router.include_router(_asset_router(get_asset))
    router.include_router(_default_router(pin_default_version))

    @router.get("")
    async def list_all(query: Annotated[ListLibrariesQuery, Query()]) -> LibraryList:
        return await list_libraries(query)

    # Library IDs are `/owner/repo`; the ref comes last because it may contain slashes
    # (`release/1.4`) and the server decodes `%2F` before routing.
    @router.get("/{owner}/{repo}")
    async def get_one(owner: str, repo: str) -> LibraryDetail:
        return await get_library(GetLibraryQuery(id=f"/{owner}/{repo}"))

    @router.patch("/{owner}/{repo}")
    async def update_one(owner: str, repo: str, patch: LibraryPatch) -> LibraryDetail:
        """Set the title and/or description; an edited field is no longer taken from the README."""
        return await update_library(
            UpdateLibraryCommand(id=f"/{owner}/{repo}", **patch.model_dump(exclude_unset=True))
        )

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
        tags: Annotated[
            list[Annotated[str, Query(max_length=MAX_TAGS * (MAX_TAG_LENGTH + 1))]] | None,
            Query(
                max_length=MAX_TAGS,
                description=(
                    "Only articles with these tags: comma-separated, or repeat the parameter. "
                    "Case does not matter."
                ),
            ),
        ] = None,
        tags_match: Annotated[
            TagMatch, Query(description="`any` (default): one of the tags; `all`: every tag.")
        ] = TagMatch.ANY,
        limit: Limit = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> ArticleList:
        query = ListArticlesQuery(
            library=f"/{owner}/{repo}",
            ref=ref,
            path_prefix=path_prefix,
            tag_filter=TagFilter(
                tags=[t for value in tags or [] for t in value.split(",") if t.strip()],
                match=tags_match,
            ),
            limit=limit,
            cursor=cursor,
        )
        return await list_articles(query)

    @router.get("/{owner}/{repo}/tags")
    async def list_version_tags(owner: str, repo: str, ref: str | None = None) -> TagList:
        return await list_tags(ListTagsQuery(library=f"/{owner}/{repo}", ref=ref))

    @router.get("/{owner}/{repo}/article")
    async def get_one_article(
        owner: str,
        repo: str,
        path: Annotated[str, Query(min_length=1, max_length=MAX_PATH)],
        ref: str | None = None,
    ) -> Article:
        return await get_article(GetArticleQuery(library=f"/{owner}/{repo}", ref=ref, path=path))

    @router.get("/{owner}/{repo}/renamed-path")
    async def get_renamed_path(
        owner: str,
        repo: str,
        path: Annotated[
            str,
            Query(
                min_length=1,
                max_length=MAX_PATH,
                description=(
                    "`forward`: the article's path in the version imported before `ref`. "
                    "`back`: its path in `ref`."
                ),
            ),
        ],
        ref: str | None = None,
        direction: Annotated[
            RenameDirection,
            Query(description="`forward` (default): old to new path; `back`: new to old."),
        ] = RenameDirection.FORWARD,
    ) -> RenameAnswer:
        """Follow `path` one hop across the renames git saw when `ref` was imported.

        `renamed` is `null` when it was not moved (or no renames are known). An unknown library
        or version, or a version without an active manifest, is a 404 instead.
        """
        found = await resolve_renamed_path(
            ResolveRenamedPathQuery(
                library=f"/{owner}/{repo}", ref=ref, path=path, direction=direction
            )
        )
        return RenameAnswer(renamed=found)

    return router


def _default_router(pin_default_version: PinDefaultVersion) -> APIRouter:
    """Build the routes that pin and unpin a library's default version (LIB-10)."""
    router = APIRouter(tags=["catalog"])

    @router.put("/{owner}/{repo}/default-version")
    async def pin_default(owner: str, repo: str, pin: DefaultVersionPin) -> LibraryDetail:
        """Pin the default version: `/owner/repo` keeps meaning `ref` when higher tags arrive.

        `ref` must be an imported version (404 otherwise). Removing that version unpins.
        """
        return await pin_default_version(
            PinDefaultVersionCommand(library=f"/{owner}/{repo}", ref=pin.ref)
        )

    @router.delete("/{owner}/{repo}/default-version")
    async def unpin_default(owner: str, repo: str) -> LibraryDetail:
        """Unpin the default version: it follows the default-version rule again."""
        return await pin_default_version(PinDefaultVersionCommand(library=f"/{owner}/{repo}"))

    return router


def _asset_router(get_asset: GetAsset) -> APIRouter:
    """Build the route that serves the images of a version (see ``_ASSET_HEADERS``)."""
    router = APIRouter(tags=["catalog"])

    @router.get(
        "/{owner}/{repo}/asset",
        response_class=Response,
        responses={
            200: {
                "description": "The image's bytes, with the type sniffed when it was imported.",
                "content": {
                    "image/png": {},
                    "image/jpeg": {},
                    "image/gif": {},
                    "image/webp": {},
                    _SVG: {},
                },
            },
            304: {"description": "The caller's copy (`If-None-Match`) is current."},
        },
    )
    async def get_version_asset(
        request: Request,
        owner: str,
        repo: str,
        path: Annotated[
            str,
            Query(
                min_length=1,
                max_length=MAX_PATH,
                description="Repository path of the image, as the article resolves it.",
            ),
        ],
        ref: str | None = None,
    ) -> Response:
        """Serve an image an article of the version references (no ref: the default version).

        Content-addressed: the `ETag` is the git blob SHA. An SVG is served as an attachment (an
        `<img>` still shows it) under a CSP that forbids scripts and any request.
        """
        sent = request.headers.get("if-none-match", "")
        known = [t.strip().removeprefix("W/").strip('"') for t in sent.split(",") if t.strip()]
        asset = await get_asset(
            GetAssetQuery(library=f"/{owner}/{repo}", ref=ref, path=path, known_blob_shas=known)
        )
        etag = f'"{asset.blob_sha}"'
        headers = {**_ASSET_HEADERS, "ETag": etag}
        if asset.content_type == _SVG:
            headers["Content-Disposition"] = 'attachment; filename="image.svg"'
        if asset.unchanged:
            return Response(status_code=304, headers=headers)
        return Response(asset.data, media_type=asset.content_type, headers=headers)

    return router
