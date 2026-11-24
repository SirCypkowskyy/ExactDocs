"""REST adapter for the catalog (consumed by the web UI)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from exactdocs.catalog.constants import _ASSET_HEADERS, _SVG, ARTICLE_SORT_FIELDS
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
    ListVersionsQuery,
    Offset,
    PinDefaultVersionCommand,
    RenameAnswer,
    RenameDirection,
    ResolvedVersion,
    ResolveRenamedPathQuery,
    ResolveVersionQuery,
    TagFilter,
    TagList,
    UpdateLibraryCommand,
    VersionList,
    VersionListQuery,
)
from exactdocs.catalog.models import TagMatch
from exactdocs.catalog.ports.driving import (
    GetArticle,
    GetAsset,
    GetLibrary,
    ListArticles,
    ListLibraries,
    ListTags,
    ListVersions,
    PinDefaultVersion,
    ResolveRenamedPath,
    ResolveVersion,
    UpdateLibrary,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_NAME, MAX_PATH, MAX_TAG_LENGTH, MAX_TAGS


def build_router(
    *,
    list_libraries: ListLibraries,
    get_library: GetLibrary,
    resolve_version: ResolveVersion,
    list_versions: ListVersions,
    list_articles: ListArticles,
    list_tags: ListTags,
    get_article: GetArticle,
    resolve_renamed_path: ResolveRenamedPath,
    get_asset: GetAsset,
    update_library: UpdateLibrary,
    pin_default_version: PinDefaultVersion,
) -> APIRouter:
    """Expose the catalog's driving ports under ``/libraries``.

    Args:
        list_libraries: Lists the libraries, a page at a time.
        get_library: Reads one library.
        resolve_version: Resolves a library ID with a ref.
        list_versions: Lists a library's versions.
        list_articles: Lists a version's articles.
        list_tags: Lists a version's tags.
        get_article: Reads one article.
        resolve_renamed_path: Follows a path across a version's renames.
        get_asset: Reads one image.
        update_library: Sets a library's title or description.
        pin_default_version: Pins or unpins a library's default version.

    Returns:
        The router.
    """
    router = APIRouter(prefix="/libraries", tags=["catalog"])
    router.include_router(_asset_router(get_asset))
    router.include_router(_default_router(pin_default_version))
    router.include_router(_versions_router(list_versions))

    @router.get("")
    async def list_all(query: Annotated[ListLibrariesQuery, Query()]) -> LibraryList:
        """List the libraries the caller may read, a page at a time; sort by ID unless told.

        Filter with `q`, `has_versions`, `ai_enabled`, `updated_after` and `updated_before`;
        `total` counts every match (never a library hidden from the caller).

        Args:
            query: The filters, the sort, the page size and the cursor of the previous page.

        Returns:
            The page, with its next cursor and the total.
        """
        return await list_libraries(query)

    # Library IDs are `/owner/repo`; the ref comes last because it may contain slashes
    # (`release/1.4`) and the server decodes `%2F` before routing.
    @router.get("/{owner}/{repo}")
    async def get_one(owner: str, repo: str) -> LibraryDetail:
        """Read a library: its settings, every imported version and its default version.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.

        Returns:
            The library.
        """
        return await get_library(GetLibraryQuery(id=f"/{owner}/{repo}"))

    @router.patch("/{owner}/{repo}")
    async def update_one(owner: str, repo: str, patch: LibraryPatch) -> LibraryDetail:
        """Set the title and/or description; an edited field is no longer taken from the README.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            patch: The fields to change.

        Returns:
            The library as it is now.
        """
        return await update_library(
            UpdateLibraryCommand(id=f"/{owner}/{repo}", **patch.model_dump(exclude_unset=True))
        )

    @router.get("/{owner}/{repo}/versions/{ref:path}")
    async def get_version(owner: str, repo: str, ref: str) -> ResolvedVersion:
        """Resolve an exact ref (or a unique short commit SHA) of a library to its version.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            ref: The ref; it may contain `/`.

        Returns:
            The version.

        Raises:
            HTTPException: A 404 for a ref ending in `/`.
        """
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
        q: Annotated[
            str | None,
            Query(
                max_length=MAX_NAME,
                description="Only articles whose path or title contains this text (any case).",
            ),
        ] = None,
        sort: Annotated[
            str | None,
            Query(
                max_length=MAX_NAME,
                description=(
                    f"Sort by one of {', '.join(ARTICLE_SORT_FIELDS)}; prefix `-` for "
                    "descending. Default: `path`. An unknown field is a 422."
                ),
            ),
        ] = None,
        limit: Limit = DEFAULT_LIMIT,
        cursor: str | None = None,
        offset: Annotated[
            Offset | None,
            Query(
                description=(
                    "Jump to a page: skip this many matches, in the order and with the filters "
                    "of the cursor walk. Not with `cursor`; the page's `next_cursor` goes on "
                    "from it."
                )
            ),
        ] = None,
    ) -> ArticleList:
        """List a version's articles (no ref: the default version), sorted by path.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            ref: Exact imported ref; none: the default version.
            path_prefix: Only paths inside this directory.
            tags: Only articles with these tags.
            tags_match: `any` or `all` of the tags.
            q: Text the path or title contains.
            sort: The sort field, `-` for descending.
            limit: How many articles per page.
            cursor: The previous page's `next_cursor`.
            offset: How many matches to skip instead of a cursor.

        Returns:
            The page, with its next cursor.
        """
        query = ListArticlesQuery(
            library=f"/{owner}/{repo}",
            ref=ref,
            path_prefix=path_prefix,
            tag_filter=TagFilter(
                tags=[t for value in tags or [] for t in value.split(",") if t.strip()],
                match=tags_match,
            ),
            q=q,
            sort=sort,
            limit=limit,
            cursor=cursor,
            offset=offset,
        )
        return await list_articles(query)

    @router.get("/{owner}/{repo}/tags")
    async def list_version_tags(owner: str, repo: str, ref: str | None = None) -> TagList:
        """List the most used tags of a version's articles (no ref: the default version).

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            ref: Exact imported ref; none: the default version.

        Returns:
            The tags with their counts.
        """
        return await list_tags(ListTagsQuery(library=f"/{owner}/{repo}", ref=ref))

    @router.get("/{owner}/{repo}/article")
    async def get_one_article(
        owner: str,
        repo: str,
        path: Annotated[str, Query(min_length=1, max_length=MAX_PATH)],
        ref: str | None = None,
    ) -> Article:
        """Read one article of a version (no ref: the default version), verbatim as imported.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            path: The article's path in the repository.
            ref: Exact imported ref; none: the default version.

        Returns:
            The article with its metadata.
        """
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
                    "With `from`: the article's path in `from`. Otherwise `forward`: its path in "
                    "the version imported before `ref`; `back`: its path in `ref`."
                ),
            ),
        ],
        ref: str | None = None,
        direction: Annotated[
            RenameDirection,
            Query(
                description=(
                    "`forward` (default): old to new path; `back`: new to old. Ignored with `from`."
                )
            ),
        ] = RenameDirection.FORWARD,
        from_ref: Annotated[
            str | None,
            Query(
                alias="from",
                description=(
                    "The exact imported ref `path` is from: the renames of every version between "
                    "it and `ref` are followed, either way. None: one hop by `direction`."
                ),
            ),
        ] = None,
    ) -> RenameAnswer:
        """Follow `path` across the renames git saw when versions were imported.

        With `from`, `path` is from that version, and the rename maps between it and `ref` are
        followed hop by hop (older to newer or back): `new_path` is its path in `ref`. Versions
        with no import link between them (another branch, a version removed in between) give
        `null`. Without `from`, one hop across the renames git saw when `ref` was imported.

        `renamed` is `null` when it was not moved (or no renames are known). An unknown library
        or version, or a version without an active manifest, is a 404 instead.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            path: The path to follow.
            ref: Exact imported ref; none: the default version.
            direction: `forward` or `back`.
            from_ref: The version `path` is from; none: one hop by `direction`.

        Returns:
            The move, or `null` in `renamed`.
        """
        found = await resolve_renamed_path(
            ResolveRenamedPathQuery(
                library=f"/{owner}/{repo}",
                ref=ref,
                path=path,
                direction=direction,
                from_ref=from_ref,
            )
        )
        return RenameAnswer(renamed=found)

    return router


def _versions_router(list_versions: ListVersions) -> APIRouter:
    """Build the route that lists a library's versions.

    Args:
        list_versions: Lists a library's versions.

    Returns:
        The router.
    """
    router = APIRouter(tags=["catalog"])

    @router.get("/{owner}/{repo}/versions")
    async def list_all_versions(
        owner: str, repo: str, query: Annotated[VersionListQuery, Query()]
    ) -> VersionList:
        """List a library's versions, sorted by ref unless told, a page at a time.

        Filter with `q`, `kind`, `origin`, `imported_after` and `imported_before`; `total` counts
        every match.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            query: The filters, the sort, the page size and the cursor of the previous page.

        Returns:
            The page, its next cursor and the total.
        """
        return await list_versions(
            ListVersionsQuery(id=f"/{owner}/{repo}", **query.model_dump(exclude_unset=True))
        )

    return router


def _default_router(pin_default_version: PinDefaultVersion) -> APIRouter:
    """Build the routes that pin and unpin a library's default version (LIB-10).

    Args:
        pin_default_version: Pins or unpins the default version.

    Returns:
        The router.
    """
    router = APIRouter(tags=["catalog"])

    @router.put("/{owner}/{repo}/default-version")
    async def pin_default(owner: str, repo: str, pin: DefaultVersionPin) -> LibraryDetail:
        """Pin the default version: `/owner/repo` keeps meaning `ref` when higher tags arrive.

        `ref` must be an imported version (404 otherwise). Removing that version unpins.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.
            pin: The version to pin.

        Returns:
            The library as it is now.
        """
        return await pin_default_version(
            PinDefaultVersionCommand(library=f"/{owner}/{repo}", ref=pin.ref)
        )

    @router.delete("/{owner}/{repo}/default-version")
    async def unpin_default(owner: str, repo: str) -> LibraryDetail:
        """Unpin the default version: it follows the default-version rule again.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository.

        Returns:
            The library as it is now.
        """
        return await pin_default_version(PinDefaultVersionCommand(library=f"/{owner}/{repo}"))

    return router


def _asset_router(get_asset: GetAsset) -> APIRouter:
    """Build the route that serves the images of a version (see ``_ASSET_HEADERS``).

    Args:
        get_asset: Reads one image.

    Returns:
        The router.
    """
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

        Args:
            request: The request, for its `If-None-Match` header.
            owner: The library ID's owner.
            repo: The library ID's repository.
            path: The image's path in the repository.
            ref: Exact imported ref; none: the default version.

        Returns:
            The image's bytes, or a 304 when the caller's copy is current.
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
