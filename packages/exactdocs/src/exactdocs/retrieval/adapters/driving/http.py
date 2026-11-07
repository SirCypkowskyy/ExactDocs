"""REST adapter for retrieval."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic.alias_generators import to_camel

from exactdocs.retrieval.adapters.driving.mcp import format_docs
from exactdocs.retrieval.constants import (
    _AT_VERSION,
    CHARS_PER_TOKEN,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRIES,
    MAX_KEY,
    MAX_LIBRARY_ID,
    MAX_MODEL_NAME,
    MAX_MODEL_REF,
    MAX_QUERY,
    MAX_RERANK_TOP_N,
    MAX_TAG,
    MAX_TAGS,
    MAX_URL,
    NOTICE_HEADER,
    POINTER_TEXT,
    PROFILE_NAME_PATTERN,
)
from exactdocs.retrieval.dtos import (
    MAX_NAME,
    MAX_PATH,
    ArticleOutlineOut,
    ArticleOutlineQuery,
    CheckProviderCommand,
    ChunkOut,
    GetLibraryRetrievalQuery,
    LibraryMatchOut,
    LibraryRetrievalOut,
    ModelChecksOut,
    ProviderListOut,
    ProviderNameQuery,
    ProviderOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    ResolveLibraryIdQuery,
    RoleListOut,
    SaveProviderCommand,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.models import AnthropicPlatform, AzureAuth, ModelRole, TagMatch
from exactdocs.retrieval.ports.driving import (
    ArticleOutline,
    CheckProvider,
    DeleteProvider,
    GetLibraryRetrieval,
    GetProvider,
    ListProviders,
    ListRoles,
    QueryDocs,
    ReadChunk,
    ResolveLibraryId,
    SaveProvider,
    SearchAllLibraries,
    SearchDocs,
    SetLibraryRetrieval,
)
from exactdocs_kernel import NOTICE


class LibraryRetrievalIn(BaseModel):
    """A library's retrieval mode, as the admin sets it."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    mode: str | None = Field(default=None, max_length=MAX_NAME)
    """`bm25`, `hybrid`, `hybrid_hyde` or `agentic`; it must be available with the settings below
    (422 `mode_unavailable` names the missing model role otherwise). Null: the instance's mode.
    """
    ai_enabled: bool = True
    """False: nothing of the library is ever sent to an AI provider; its searches are BM25."""
    llm: str | None = Field(default=None, max_length=MAX_MODEL_REF)
    """The library's own LLM, `<profile>:<model>`; null: the instance's `llm` role."""
    judge: str | None = Field(default=None, max_length=MAX_MODEL_REF)
    """The library's own judge, `<profile>:<model>`; null: the instance's (else the LLM)."""
    reranker: str | None = Field(default=None, max_length=MAX_MODEL_REF)
    """The library's own reranker, `<profile>:<model>`; null: the instance's. The embedding model
    is instance-wide only and cannot be set here.
    """
    rerank_top_n: int | None = Field(default=None, ge=1, le=MAX_RERANK_TOP_N)
    """How many of its best candidates the reranker reorders (1 to 200); null: the instance's
    (`EXACTDOCS_AI__RERANKER__TOP_N`, 32 by default).
    """


class ProviderIn(BaseModel):
    """An AI provider profile managed over the REST API. Its key is write-only."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    kind: str = Field(max_length=MAX_NAME)
    """`openai-compatible`, `openai`, `openrouter`, `anthropic`, `azure`, `google-vertex`,
    `google`, `ollama`, `vllm`, `litellm`, `local`, or one of pydantic-ai's OpenAI-API providers
    (`deepseek`, `together`, `fireworks`, `cerebras`, `github`, `vercel`, `moonshotai`, `heroku`,
    `nebius`, `ovhcloud`, `sambanova`, `alibaba`).
    """
    base_url: str | None = Field(default=None, max_length=MAX_URL)
    """The endpoint; required for `openai-compatible`, `ollama`, `vllm`, `litellm` and `azure`."""
    api_key: SecretStr | None = Field(default=None, max_length=MAX_KEY)
    """Sealed with the instance's secret key and never returned (422 `secret_key_required`
    without one). Omitted: the stored key is kept while the endpoint stays the same.
    """
    keep_key: bool = True
    """When `api_key` is omitted: keep the stored key (false removes it)."""
    headers: dict[str, str] = Field(default_factory=dict)
    """Extra headers of every call (never returned or logged). No credentials: `Authorization`,
    `Cookie`, `*-key`, `*-token` and the like are refused; the key goes in `api_key`.
    """
    proxy: str | None = Field(default=None, max_length=MAX_URL)
    """An HTTP(S) proxy for this profile only."""
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    """Overall timeout of one call, in seconds."""
    max_retries: int = DEFAULT_RETRIES
    """Retries of one call."""
    api_version: str | None = Field(default=None, max_length=MAX_NAME)
    """Azure OpenAI's API version."""
    project: str | None = Field(default=None, max_length=MAX_NAME)
    """Google Cloud project (`google-vertex`, `anthropic` on `vertex`)."""
    location: str | None = Field(default=None, max_length=MAX_NAME)
    """Google Cloud location, or the AWS region of Claude on Bedrock."""
    credentials_file: str | None = Field(default=None, max_length=MAX_PATH)
    """Refused here (422 `invalid_provider`): the server's own cloud identity is configured in
    the environment or the configuration file only.
    """
    credentials: Literal["adc"] | None = None
    """Refused here, as `credentials_file`: configuration only."""
    platform: AnthropicPlatform | None = None
    """`anthropic` only: `api` (default), `vertex`, `foundry` or `bedrock`."""
    auth: AzureAuth | None = None
    """`key` (the default); `entra` (Entra ID) is refused here: configuration only."""
    resource: str | None = Field(default=None, max_length=MAX_NAME)
    """Azure OpenAI or Claude on Azure AI Foundry: the resource name, instead of `base_url`."""


class NewProviderIn(ProviderIn):
    """A new AI provider profile."""

    name: str = Field(pattern=PROFILE_NAME_PATTERN)
    """Used in roles as `<name>:<model>`: lower case, digits, `_` and `-`."""


class ProviderCheckIn(BaseModel):
    """What to check: a role and a model, or (empty) the roles that use the profile."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    role: ModelRole | None = None
    """How to call `model`: `llm`/`judge` (a chat turn), `embedding` or `reranker`."""
    model: str | None = Field(default=None, max_length=MAX_MODEL_NAME)
    """The model to check (needs `role`)."""


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
    branch: str
    """The default version (context7: the tracked branch)."""
    state: Literal["finalized"] = "finalized"
    total_snippets: int
    """Chunks of the default version."""
    versions: list[str]
    last_update_date: datetime | None = Field(default=None)
    """When any version was last imported."""
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

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the results."""
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

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the results."""
    code_snippets: list[dict[str, Any]] = Field(default=[])
    """Always empty: chunks are not split into code and prose."""
    info_snippets: list[C7InfoSnippet]
    omitted: int
    """Matching chunks that did not fit the size budget."""

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
    article_outline: ArticleOutline,
    resolve_library_id: ResolveLibraryId,
    query_docs: QueryDocs,
) -> APIRouter:
    """Expose retrieval: search beside the catalog's ``/libraries`` routes, ``/chunks``, ``/c7``."""
    router = APIRouter(tags=["retrieval"])
    router.include_router(_outline_router(article_outline))

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
        mode: Annotated[
            str | None,
            Query(
                max_length=MAX_NAME,
                description=(
                    "`bm25`, `hybrid`, `hybrid_hyde` or `agentic`, if available (422 "
                    "`mode_unavailable` otherwise). Default: the library's mode, else the "
                    "instance's, else the best one configured."
                ),
            ),
        ] = None,
    ) -> SearchDocsResult:
        """Search one exact version; never another one.

        `retrieval_mode` says which mode answered and `fallback_reason` why a cheaper one did.

        Args:
            owner: The library's owner.
            repo: The library's repository name.
            q: The query.
            ref: The exact version; the default version without one.
            tags: Only chunks of articles so tagged.
            tags_match: `any` or `all` of the tags.
            limit: How many results at most.
            mode: The retrieval mode; the default without one.

        Returns:
            The results of that version.
        """
        try:
            query = SearchDocsQuery(
                library=f"/{owner}/{repo}",
                ref=ref,
                query=q,
                tags=tags or [],
                tags_match=tags_match,
                limit=limit,
                mode=mode,
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


def build_library_retrieval_router(
    *, get_library_retrieval: GetLibraryRetrieval, set_library_retrieval: SetLibraryRetrieval
) -> APIRouter:
    """Build the routes of a library's retrieval mode (RET-06).

    Args:
        get_library_retrieval: Reads a library's mode.
        set_library_retrieval: Sets or clears it.

    Returns:
        The router.
    """
    router = APIRouter(tags=["retrieval"])

    @router.get("/libraries/{owner}/{repo}/retrieval", name="get_library_retrieval")
    async def get_retrieval(owner: str, repo: str) -> LibraryRetrievalOut:
        """Read the library's retrieval mode and the mode a search without `mode` runs in now.

        Args:
            owner: The library's owner.
            repo: The library's repository name.

        Returns:
            The setting, the effective mode and the modes available.
        """
        return await get_library_retrieval(GetLibraryRetrievalQuery(library=f"/{owner}/{repo}"))

    @router.put("/libraries/{owner}/{repo}/retrieval", name="set_library_retrieval")
    async def set_retrieval(owner: str, repo: str, body: LibraryRetrievalIn) -> LibraryRetrievalOut:
        """Set the library's retrieval mode and AI overrides (RET-06), replacing what it had.

        A call's `mode` still wins; the instance's mode (`EXACTDOCS_AI__MODE`) applies to
        libraries without one. A mode set here that later cannot run (a model role was removed)
        does not fail searches: they fall back with `fallback_reason` `mode_unavailable`. With
        `ai_enabled` false, nothing of the library is sent to any AI provider. Admins only.

        Args:
            owner: The library's owner.
            repo: The library's repository name.
            body: The mode, or null to clear it.

        Returns:
            The setting, the effective mode and the modes available.
        """
        return await set_library_retrieval(
            SetLibraryRetrievalCommand(library=f"/{owner}/{repo}", **body.model_dump())
        )

    return router


def _outline_router(article_outline: ArticleOutline) -> APIRouter:
    """Expose ``GET /libraries/{owner}/{repo}/outline``, beside the catalog's article route.

    Args:
        article_outline: The driving port that builds the outline.

    Returns:
        A router with the one route.
    """
    router = APIRouter(tags=["retrieval"])

    @router.get("/libraries/{owner}/{repo}/outline")
    async def outline(
        owner: str,
        repo: str,
        path: Annotated[str, Query(min_length=1, max_length=MAX_PATH)],
        ref: Annotated[str | None, Query(max_length=MAX_NAME)] = None,
    ) -> ArticleOutlineOut:
        """An article's heading tree with a chunk ID per heading, without its text.

        404 `not_found` for a version that is not imported or a path it does not have.

        Args:
            owner: Repository owner, the first part of the library ID.
            repo: Repository name, the second part of the library ID.
            path: Article path in that version.
            ref: Exact imported ref; the default version when absent.

        Returns:
            The outline and the version that answered.
        """
        try:
            query = ArticleOutlineQuery(library=f"/{owner}/{repo}", ref=ref, path=path)
        except ValidationError as error:  # what the Query() bounds above cannot see
            raise RequestValidationError(error.errors()) from error
        return await article_outline(query)

    return router


def _command[T](build: Callable[[], T]) -> T:
    """Build a domain command; its validation errors become a 422 like the request's own.

    Args:
        build: Builds the command.

    Returns:
        The command.

    Raises:
        RequestValidationError: The command does not validate.
    """
    try:
        return build()
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


def build_ai_router(
    *,
    list_providers: ListProviders,
    get_provider: GetProvider,
    save_provider: SaveProvider,
    delete_provider: DeleteProvider,
    check_provider: CheckProvider,
    list_roles: ListRoles,
) -> APIRouter:
    """Build the routes of the AI provider profiles and roles (RET-01..03), admins only.

    Args:
        list_providers: Lists the profiles.
        get_provider: Reads one.
        save_provider: Creates or replaces one.
        delete_provider: Deletes one.
        check_provider: Makes one minimal call per role that uses one.
        list_roles: Shows the instance's roles.

    Returns:
        The router.
    """
    router = APIRouter(prefix="/ai", tags=["ai"])

    @router.get("/providers", name="list_providers")
    async def list_all() -> ProviderListOut:
        """List every AI provider profile: configured ones (read-only), then stored ones.

        Keys and header values are never shown; `key` says where a key comes from.

        Returns:
            The profiles.
        """
        return await list_providers()

    @router.post(
        "/providers",
        name="create_provider",
        status_code=status.HTTP_201_CREATED,
    )
    async def create(body: NewProviderIn) -> ProviderOut:
        """Create an AI provider profile; its key is sealed and never returned.

        Args:
            body: The profile.

        Returns:
            The profile, without its key.
        """
        fields = body.model_dump(exclude={"name"})
        command = _command(lambda: SaveProviderCommand(name=body.name, create=True, **fields))
        return await save_provider(command)

    @router.get("/providers/{name}", name="get_provider")
    async def get_one(name: Annotated[str, Path(max_length=MAX_NAME)]) -> ProviderOut:
        """Read one AI provider profile.

        Args:
            name: The profile.

        Returns:
            The profile, without its key or header values.
        """
        return await get_provider(_command(lambda: ProviderNameQuery(name=name)))

    @router.put("/providers/{name}", name="save_provider")
    async def save(
        name: Annotated[str, Path(max_length=MAX_NAME)], body: ProviderIn
    ) -> ProviderOut:
        """Create or replace an AI provider profile; the change counts at the next call.

        A profile from the environment or the configuration file is read-only (409). Without
        `api_key` the stored key is kept, unless the endpoint changed (then send it again).

        Args:
            name: The profile.
            body: Its settings.

        Returns:
            The profile, without its key.
        """
        fields = body.model_dump()
        return await save_provider(_command(lambda: SaveProviderCommand(name=name, **fields)))

    @router.delete(
        "/providers/{name}", name="delete_provider", status_code=status.HTTP_204_NO_CONTENT
    )
    async def delete(name: Annotated[str, Path(max_length=MAX_NAME)]) -> None:
        """Delete a stored AI provider profile that no instance role uses.

        Args:
            name: The profile.
        """
        await delete_provider(_command(lambda: ProviderNameQuery(name=name)))

    @router.post("/providers/{name}/check", name="check_provider")
    async def check(
        name: Annotated[str, Path(max_length=MAX_NAME)], body: ProviderCheckIn | None = None
    ) -> ModelChecksOut:
        """Make one minimal call per role that uses the profile (or to the model named).

        Reports each call's latency, the model that answered and an embedding's dimensions.
        A failed call is a check with `status` `error`, not a failed request.

        Args:
            name: The profile.
            body: A role and a model to check instead of the roles that use it.

        Returns:
            One check per call.
        """
        role = None if body is None else body.role
        model = None if body is None else body.model
        command = _command(lambda: CheckProviderCommand(name=name, role=role, model=model))
        return await check_provider(command)

    @router.get("/roles", name="list_roles")
    async def roles() -> RoleListOut:
        """Show the instance's model roles (set in the environment or the configuration file).

        Returns:
            One entry per role.
        """
        return await list_roles()

    return router
