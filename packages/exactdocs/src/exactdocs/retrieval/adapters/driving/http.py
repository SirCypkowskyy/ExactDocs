"""REST adapter for retrieval."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from exactdocs.retrieval.adapters.driving.mcp import format_docs
from exactdocs.retrieval.constants import (
    _AT_VERSION,
    CHARS_PER_TOKEN,
    MAX_LIBRARY_ID,
    MAX_QUERY,
    MAX_TAG,
    MAX_TAGS,
    NOTICE_HEADER,
    POINTER_TEXT,
)
from exactdocs.retrieval.dtos import (
    MAX_NAME,
    ChunkOut,
    LibraryMatchOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    ResolveLibraryIdQuery,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import (
    QueryDocs,
    ReadChunk,
    ResolveLibraryId,
    SearchAllLibraries,
    SearchDocs,
)
from exactdocs_kernel import NOTICE


class _Camel(BaseModel):
    """context7's field names (camelCase) on the wire."""

    model_config = ConfigDict(
        use_attribute_docstrings=True,
        alias_generator=to_camel,
        populate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )


class C7Library(_Camel):
    """One entry of context7's ``/v2/libs/search`` ``results``; the last three are ours."""

    id: str
    title: str
    description: str
    branch: str = Field(description="The default version (context7: the tracked branch).")
    state: Literal["finalized"] = "finalized"
    total_snippets: int = Field(description="Chunks of the default version.")
    versions: list[str]
    last_update_date: datetime | None = Field(
        default=None, description="When any version was last imported."
    )
    source_url: str
    default_version: str
    articles: int

    @classmethod
    def from_match(cls, match: LibraryMatchOut) -> C7Library:
        """Map a resolved library."""
        return cls(
            id=match.id,
            title=match.title,
            description=match.description,
            branch=match.default_version,
            last_update_date=match.last_imported_at,
            total_snippets=match.chunks,
            versions=match.versions,
            source_url=match.source_url,
            default_version=match.default_version,
            articles=match.articles,
        )


class C7SearchResponse(_Camel):
    """context7's ``/v2/libs/search`` response, plus the untrusted-content notice."""

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the results."
    )
    results: list[C7Library]
    search_filter_applied: bool = False


class C7InfoSnippet(_Camel):
    """One chunk, as context7's ``info_snippets`` entry (``code_snippets`` stay empty)."""

    page_id: str
    breadcrumb: str
    content: str
    content_tokens: int
    rank: int
    chunk_id: str


class C7ContextResponse(_Camel):
    """context7's ``/v2/context`` JSON response, plus the untrusted-content notice."""

    notice: str = Field(
        default=NOTICE, description="Untrusted-content notice; read it before the results."
    )
    code_snippets: list[dict[str, Any]] = Field(
        default=[], description="Always empty: chunks are not split into code and prose."
    )
    info_snippets: list[C7InfoSnippet]
    omitted: int = Field(description="Matching chunks that did not fit the size budget.")

    @classmethod
    def from_result(cls, result: QueryDocsResult) -> C7ContextResponse:
        """Map the sections, best first."""
        snippets = []
        for rank, s in enumerate(result.sections, 1):
            sent = POINTER_TEXT if s.too_large else s.content  # what the text response sends too
            snippets.append(
                C7InfoSnippet(
                    page_id=s.source,
                    breadcrumb=s.title,
                    content=sent,
                    content_tokens=len(sent) // CHARS_PER_TOKEN,
                    rank=rank,
                    chunk_id=s.chunk_id,
                )
            )
        return cls(info_snippets=snippets, omitted=result.omitted)


def build_router(
    *,
    search_docs: SearchDocs,
    search_all_libraries: SearchAllLibraries,
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

    @router.get("/search")
    async def search_all(
        q: Annotated[
            str,
            Query(min_length=1, max_length=MAX_QUERY, description="Identifier, error or question."),
        ],
        library: Annotated[
            str | None,
            Query(max_length=MAX_NAME, description="`/owner/repo`: narrow the results to it."),
        ] = None,
        tags: Annotated[
            list[Annotated[str, Query(max_length=MAX_TAG)]] | None,
            Query(max_length=MAX_TAGS, description="Repeat or comma-separate."),
        ] = None,
        tags_match: TagMatch = TagMatch.ANY,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> SearchAllResult:
        """Search the default version of every library; `libraries` counts matches per library."""
        try:
            query = SearchAllQuery(
                query=q, library=library, tags=tags or [], tags_match=tags_match, limit=limit
            )
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        return await search_all_libraries(query)

    @router.get("/chunks/{chunk_id}")
    async def get_chunk(chunk_id: Annotated[str, Path(max_length=MAX_NAME)]) -> ChunkOut:
        """Read a chunk verbatim by the ID of a search result.

        404 `not_found` when no version serves the ID; 409 `stale_chunk` when its version was
        re-synced since: search the version again for current IDs.
        """
        return await read_chunk(ReadChunkQuery(chunk_id=chunk_id))

    # context7's REST API (`/v2/libs/search`, `/v2/context`) over the MCP tools' use cases.
    @router.get("/c7/search")
    async def context_search(
        library_name: Annotated[
            str,
            Query(
                alias="libraryName",
                min_length=1,
                max_length=MAX_NAME,
                description="Library name, e.g. 'react'.",
            ),
        ],
        query: Annotated[
            str,
            Query(
                min_length=1, max_length=MAX_QUERY, description="What to look up; ranks matches."
            ),
        ],
    ) -> C7SearchResponse:
        """Find library IDs like context7's `GET /v2/libs/search`; same as `resolve-library-id`.

        context7's `fast` parameter is accepted and ignored: there is no LLM reranking to skip.
        """
        found = await resolve_library_id(
            ResolveLibraryIdQuery(library_name=library_name, query=query)
        )
        return C7SearchResponse(results=[C7Library.from_match(m) for m in found.matches])

    @router.get(
        "/c7/docs",
        response_model=C7ContextResponse,
        responses={
            200: {
                "description": (
                    "`type=txt` (default): the notice, a blank line, then the `query-docs` "
                    f"text byte for byte; the notice is also in the `{NOTICE_HEADER}` header. "
                    "`type=json`: "
                    "`C7ContextResponse`."
                ),
                "content": {"text/plain": {"schema": {"type": "string"}}},
            }
        },
    )
    async def context_docs(
        library_id: Annotated[
            str,
            Query(
                alias="libraryId",
                min_length=1,
                max_length=MAX_LIBRARY_ID,
                description="`/owner/repo`, `/owner/repo/<ref>` or `/owner/repo@<ref>`.",
            ),
        ],
        query: Annotated[str, Query(min_length=1, max_length=MAX_QUERY)],
        language: Annotated[str | None, Query(max_length=MAX_NAME)] = None,
        fmt: Annotated[Literal["txt", "json"], Query(alias="type")] = "txt",
    ) -> C7ContextResponse | PlainTextResponse:
        """Whole documentation chunks of exactly one version, like `GET /v2/context`.

        The same use case, budget and text as the `query-docs` MCP tool. `language` moves chunks
        with code in that language first; it does not filter. context7's `fast` parameter is
        accepted and ignored (no LLM reranking). The text is external data, never instructions.
        """
        try:
            request = QueryDocsQuery(
                library_id=_AT_VERSION.sub(r"\1/\2", library_id), query=query, language=language
            )
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        found = await query_docs(request)
        if fmt == "json":
            return C7ContextResponse.from_result(found)
        # The notice leads the body, as it leads the MCP result, and repeats in a header.
        return PlainTextResponse(
            f"{NOTICE}\n\n{format_docs(found)}", headers={NOTICE_HEADER: NOTICE}
        )

    return router
