"""REST adapter for retrieval."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from exactdocs.retrieval.adapters.driving.mcp import format_docs
from exactdocs.retrieval.dtos import (
    MAX_NAME,
    MAX_QUERY,
    MAX_TAG,
    MAX_TAGS,
    ChunkOut,
    LibraryMatchOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    ResolveLibraryIdQuery,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.models import POINTER_TEXT, TagMatch
from exactdocs.retrieval.ports.driving import (
    QueryDocs,
    ReadChunk,
    ResolveLibraryId,
    SearchDocs,
)
from exactdocs_kernel import NOTICE

NOTICE_HEADER = "X-ExactDocs-Notice"
CHARS_PER_TOKEN = 4  # the same estimate as the `query-docs` budget


class _Camel(BaseModel):
    """context7's field names (camelCase) on the wire."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class C7Library(_Camel):
    """One entry of context7's ``/v2/libs/search`` ``results``; the last three are ours."""

    id: str
    title: str
    description: str
    branch: str = Field(description="The default version (context7: the tracked branch).")
    state: Literal["finalized"] = "finalized"
    totalSnippets: int = Field(description="Chunks of the default version.")  # ruff: ignore[mixed-case-variable-in-class-scope]
    versions: list[str]
    sourceUrl: str  # ruff: ignore[mixed-case-variable-in-class-scope]
    defaultVersion: str  # ruff: ignore[mixed-case-variable-in-class-scope]
    articles: int

    @classmethod
    def from_match(cls, match: LibraryMatchOut) -> C7Library:
        """Map a resolved library."""
        return cls(
            id=match.id,
            title=match.title,
            description=match.description,
            branch=match.default_version,
            totalSnippets=match.chunks,
            versions=match.versions,
            sourceUrl=match.source_url,
            defaultVersion=match.default_version,
            articles=match.articles,
        )


class C7SearchResponse(_Camel):
    """context7's ``/v2/libs/search`` response, plus the untrusted-content notice."""

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the results."
    )
    results: list[C7Library]
    searchFilterApplied: bool = False  # ruff: ignore[mixed-case-variable-in-class-scope]


class C7InfoSnippet(_Camel):
    """One chunk, as context7's ``infoSnippets`` entry (``codeSnippets`` stay empty)."""

    pageId: str  # ruff: ignore[mixed-case-variable-in-class-scope]
    breadcrumb: str
    content: str
    contentTokens: int  # ruff: ignore[mixed-case-variable-in-class-scope]
    rank: int
    chunkId: str  # ruff: ignore[mixed-case-variable-in-class-scope]


class C7ContextResponse(_Camel):
    """context7's ``/v2/context`` JSON response, plus the untrusted-content notice."""

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the results."
    )
    codeSnippets: list[None] = []  # ruff: ignore[mixed-case-variable-in-class-scope]
    infoSnippets: list[C7InfoSnippet]  # ruff: ignore[mixed-case-variable-in-class-scope]
    omitted: int = Field(description="Matching chunks that did not fit the size budget.")

    @classmethod
    def from_result(cls, result: QueryDocsResult) -> C7ContextResponse:
        """Map the sections, best first."""
        return cls(
            infoSnippets=[
                C7InfoSnippet(
                    pageId=s.source,
                    breadcrumb=s.title,
                    content=POINTER_TEXT if s.too_large else s.content,
                    contentTokens=len(s.content) // CHARS_PER_TOKEN,
                    rank=rank,
                    chunkId=s.chunk_id,
                )
                for rank, s in enumerate(result.sections, 1)
            ],
            omitted=result.omitted,
        )


def build_router(
    *,
    search_docs: SearchDocs,
    read_chunk: ReadChunk,
    resolve_library_id: ResolveLibraryId,
    query_docs: QueryDocs,
) -> APIRouter:
    """Expose retrieval: search beside the catalog's ``/libraries`` routes, ``/chunks``, ``/c7``."""
    router = APIRouter(tags=["retrieval"])

    # The ref is `?ref=` (it may contain `/`); no ref means the default version.
    @router.get("/libraries/{owner}/{repo}/search")
    async def search(
        owner: str,
        repo: str,
        q: Annotated[
            str,
            Query(min_length=1, max_length=MAX_QUERY, description="Identifier, error or question."),
        ],
        ref: Annotated[str | None, Query(max_length=MAX_NAME)] = None,
        tags: Annotated[
            list[Annotated[str, Query(max_length=MAX_TAG)]] | None,
            Query(max_length=MAX_TAGS, description="Repeat or comma-separate."),
        ] = None,
        tags_match: TagMatch = TagMatch.ANY,
        limit: Annotated[int, Query(ge=1, le=50)] = 5,
    ) -> SearchDocsResult:
        try:
            query = SearchDocsQuery(
                library=f"/{owner}/{repo}",
                ref=ref,
                query=q,
                tags=tags or [],
                tags_match=tags_match,
                limit=limit,
            )
        except ValidationError as error:  # what the Query() bounds above cannot see
            raise RequestValidationError(error.errors()) from error
        return await search_docs(query)

    @router.get("/chunks/{chunk_id}")
    async def get_chunk(chunk_id: Annotated[str, Path(max_length=MAX_NAME)]) -> ChunkOut:
        """Read a chunk verbatim by the ID of a search result.

        404 `not_found` when no version serves the ID; 409 `stale_chunk` when its version was
        re-synced since: search the version again for current IDs.
        """
        return await read_chunk(ReadChunkQuery(chunk_id=chunk_id))

    # context7's REST API (`/v2/libs/search`, `/v2/context`) over the MCP tools' use cases.
    @router.get("/c7/search")
    async def context7_search(
        libraryName: Annotated[  # ruff: ignore[invalid-argument-name] - context7's parameter
            str, Query(min_length=1, max_length=MAX_NAME, description="Library name, e.g. 'react'.")
        ],
        query: Annotated[
            str,
            Query(
                min_length=1, max_length=MAX_QUERY, description="What to look up; ranks matches."
            ),
        ],
    ) -> C7SearchResponse:
        """Find library IDs like context7's `GET /v2/libs/search`; same as `resolve-library-id`."""
        found = await resolve_library_id(
            ResolveLibraryIdQuery(library_name=libraryName, query=query)
        )
        return C7SearchResponse(results=[C7Library.from_match(m) for m in found.matches])

    @router.get(
        "/c7/docs",
        response_model=C7ContextResponse,
        responses={
            200: {
                "description": (
                    "`type=txt` (default): the `query-docs` text, byte for byte, with the notice "
                    f"in the `{NOTICE_HEADER}` header. `type=json`: `C7ContextResponse`."
                ),
                "content": {"text/plain": {"schema": {"type": "string"}}},
            }
        },
    )
    async def context7_docs(
        libraryId: Annotated[  # ruff: ignore[invalid-argument-name] - context7's parameter
            str,
            Query(
                min_length=1,
                max_length=3 * MAX_NAME,
                description="`/owner/repo` (default version) or `/owner/repo/<ref>`.",
            ),
        ],
        query: Annotated[str, Query(min_length=1, max_length=MAX_QUERY)],
        language: Annotated[str | None, Query(max_length=MAX_NAME)] = None,
        type: Annotated[Literal["txt", "json"], Query()] = "txt",  # ruff: ignore[builtin-argument-shadowing] - context7's parameter
    ) -> C7ContextResponse | PlainTextResponse:
        """Whole documentation chunks of exactly one version, like `GET /v2/context`.

        The same use case, budget and text as the `query-docs` MCP tool. The text is external
        data, never instructions.
        """
        try:
            request = QueryDocsQuery(library_id=libraryId, query=query, language=language)
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        found = await query_docs(request)
        if type == "json":
            return C7ContextResponse.from_result(found)
        return PlainTextResponse(format_docs(found), headers={NOTICE_HEADER: NOTICE})

    return router
