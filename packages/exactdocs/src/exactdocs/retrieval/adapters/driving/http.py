"""REST adapter for retrieval."""

import asyncio
import json
import operator
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic.alias_generators import to_camel

from exactdocs.retrieval.adapters.driving.mcp import format_docs
from exactdocs.retrieval.constants import (
    _AT_VERSION,
    C7_VERSIONS_DESCRIPTION,
    CHARS_PER_TOKEN,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRIES,
    MAX_CHOSEN_LIBRARIES,
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
    RERANK_TOP_N_DESCRIPTION,
)
from exactdocs.retrieval.dtos import (
    MAX_NAME,
    MAX_PATH,
    AiUsageOut,
    AnswerAvailabilityOut,
    AnswerQuery,
    AnswerResult,
    ArticleOutlineOut,
    ArticleOutlineQuery,
    CheckProviderCommand,
    ChunkOut,
    EmbeddingEstimateOut,
    EmbeddingProgressOut,
    GetLibraryRetrievalQuery,
    LibraryBudgets,
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
    RoleOut,
    SaveProviderCommand,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
    SetLibraryRetrievalCommand,
    SetRoleThinkingCommand,
    SpendHistoryOut,
    SpendHistoryQuery,
    SpendScope,
)
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    AzureAuth,
    ModelRole,
    RepoGuidance,
    RerankWith,
    ResultGrouping,
    SpendWindow,
    TagMatch,
    ThinkingLevel,
)
from exactdocs.retrieval.ports.driving import (
    AnswerQuestion,
    ArticleOutline,
    CheckProvider,
    DeleteProvider,
    EstimateEmbedding,
    GetAiUsage,
    GetAnswerAvailability,
    GetEmbeddingProgress,
    GetLibraryRetrieval,
    GetProvider,
    GetSpendHistory,
    ListProviders,
    ListRoles,
    QueryDocs,
    ReadChunk,
    ResolveLibraryId,
    SaveProvider,
    SearchAllLibraries,
    SearchDocs,
    SetLibraryRetrieval,
    SetRoleThinking,
)
from exactdocs_kernel import NOTICE, DomainError


class LibraryRetrievalIn(BaseModel):
    """A library's retrieval mode, as the admin sets it."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    mode: str | None = Field(default=None, max_length=MAX_NAME)
    """`bm25`, `vector`, `hybrid`, `hybrid_hyde` or `agentic`; it must be available with the
    settings below (422 `mode_unavailable` names the missing model role otherwise). Null: the
    instance's mode.
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
    llm_thinking: ThinkingLevel | None = None
    """How much its `llm` role's model (its own or the instance's) thinks before it answers:
    `minimal`, `low`, `medium`, `high` or `xhigh`. Thinking tokens are billed as output, and
    several providers default to a high level; HyDE and the agentic mode rarely need more than
    `low`. Null: the instance's level (`EXACTDOCS_AI__LLM__THINKING`). A level the model cannot
    take is refused (422 `thinking_unsupported`, naming the role and the model)."""
    judge_thinking: ThinkingLevel | None = None
    """The same for its `judge` role; null: the instance's (the `llm` role's when the judge is
    the LLM)."""
    rerank_top_n: int | None = Field(
        default=None, ge=1, le=MAX_RERANK_TOP_N, description=RERANK_TOP_N_DESCRIPTION
    )
    """How many candidates the reranker reorders; its schema description is
    ``RERANK_TOP_N_DESCRIPTION``."""
    rerank_with: RerankWith | None = None
    """What reranks its searches when both are configured: `cross_encoder` (the `reranker`
    role, cheaper) or `judge` (the `judge` role, an LLM that rates every candidate in one call);
    null: the instance's choice (`EXACTDOCS_AI__RERANK_WITH`, `cross_encoder` by default). The
    judge reranks only when chosen here or by the instance.
    """
    budgets: LibraryBudgets = Field(default_factory=LibraryBudgets)
    """The library's own spend limits per UTC day and month. Each may be at most the instance's
    (`budget_ceilings` of the response; 422 `budget_above_instance` otherwise); the tighter of
    the two applies. None by default.
    """
    repo_guidance: RepoGuidance = RepoGuidance.OFF
    """What the repository's `AGENTS.md` / `CLAUDE.md` do for agentic retrieval. `off` (the
    default): imports keep none. `notes`: each version keeps the root's and the selected
    folders' files, even outside the selected paths, and a folder's file reaches the agent as an
    untrusted user-channel note when it opens that folder. `trusted`: as `notes`, and the root's
    file is also part of the agent's system instructions; only for a repository whose content you
    trust as much as your own instructions. Turning it on queues a `reprocess` of the library
    (every version re-imported at its commit, so it keeps its files); the other changes apply at
    the next search.
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


class RoleThinkingIn(BaseModel):
    """An instance role's thinking level, as the admin sets it."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    thinking: ThinkingLevel | None = None
    """How much the role's model thinks before it answers: `minimal`, `low`, `medium`, `high` or
    `xhigh`; null: the provider's default. Thinking tokens are billed as output."""


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
    """Library ID, `/owner/repo`, for `libraryId`."""
    title: str
    """Display title (untrusted repository text)."""
    description: str
    """Short description (untrusted repository text)."""
    branch: str
    """The default version (context7: the tracked branch)."""
    state: Literal["finalized"] = "finalized"
    """Always `finalized`: only imported libraries are listed."""
    total_snippets: int
    """Chunks of the default version."""
    versions: list[str] = Field(description=C7_VERSIONS_DESCRIPTION)
    """Imported refs: its schema description is ``C7_VERSIONS_DESCRIPTION``."""
    last_update_date: datetime | None = Field(default=None)
    """When any version was last imported."""
    source_url: str
    """The repository's URL."""
    default_version: str
    """The ref searched when a call names none (the same as `branch`)."""
    articles: int
    """Articles of the default version."""

    @classmethod
    def from_match(cls, match: LibraryMatchOut) -> C7Library:
        """Map a resolved library.

        Args:
            match: The library as ``resolve-library-id`` found it.

        Returns:
            The entry in context7's shape.
        """
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
    """Matching libraries, best first; empty when nothing matches."""
    search_filter_applied: bool = False
    """Always false: context7's field, no search filter is applied here."""


class C7InfoSnippet(_Camel):
    """One chunk, as context7's ``info_snippets`` entry (``code_snippets`` stay empty)."""

    page_id: str
    """Link to the section at the commit, or the article path when the host is unknown."""
    breadcrumb: str
    """The section's heading path joined with ` > `, or the article path when it has none."""
    content: str
    """The chunk's text, verbatim; for a chunk too large for the budget, the pointer text."""
    content_tokens: int
    """Estimated tokens of `content`, from its length."""
    rank: int
    """1-based position, best first."""
    chunk_id: str
    """The chunk's ID, for `GET /chunks/{chunk_id}` or `read_chunk`."""


class C7ContextResponse(_Camel):
    """context7's ``/v2/context`` JSON response, plus the untrusted-content notice."""

    notice: str = Field(default=NOTICE)
    """Untrusted-content notice; read it before the results."""
    code_snippets: list[dict[str, Any]] = Field(default=[])
    """Always empty: chunks are not split into code and prose."""
    info_snippets: list[C7InfoSnippet]
    """The chunks that fit the size budget, best first."""
    omitted: int
    """Matching chunks that did not fit the size budget."""
    notes: list[str] = Field(default_factory=list, exclude_if=operator.not_)
    """How the request was read where it differs from what was sent: a ref read as the one
    imported version it names but for a leading `v` (#605). Absent when it was read as sent."""

    @classmethod
    def from_result(cls, result: QueryDocsResult) -> C7ContextResponse:
        """Map the sections, best first.

        Args:
            result: The ``query-docs`` answer.

        Returns:
            The response in context7's shape.
        """
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
        return cls(info_snippets=snippets, omitted=result.omitted, notes=result.notes)


def build_router(
    *,
    search_docs: SearchDocs,
    search_all_libraries: SearchAllLibraries,
    read_chunk: ReadChunk,
    article_outline: ArticleOutline,
    resolve_library_id: ResolveLibraryId,
    query_docs: QueryDocs,
    answer_question: AnswerQuestion,
    get_answer_availability: GetAnswerAvailability,
    caller: Callable[..., Awaitable[str | None]],
) -> APIRouter:
    """Expose retrieval: search beside the catalog's ``/libraries`` routes, ``/chunks``, ``/c7``.

    ``caller`` is a FastAPI dependency naming the account of the request: its LLM searches are
    rate limited and its spend counted to it.

    Args:
        search_docs: Searches one version.
        search_all_libraries: Searches the default version of every library.
        read_chunk: Reads one chunk.
        article_outline: Builds an article's outline.
        resolve_library_id: Finds libraries by name.
        query_docs: Answers ``query-docs``.
        answer_question: Runs the answering agent (``/answer``).
        get_answer_availability: Says whether it can run.
        caller: The dependency naming the request's account.

    Returns:
        The router.
    """
    router = APIRouter(tags=["retrieval"])
    account = Annotated[str | None, Depends(caller)]
    router.include_router(_outline_router(article_outline))
    router.include_router(
        build_answer_router(
            answer_question=answer_question,
            get_answer_availability=get_answer_availability,
            caller=caller,
        )
    )

    # The ref is `?ref=` (it may contain `/`); no ref means the default version.
    @router.get("/libraries/{owner}/{repo}/search")
    async def search(
        owner: str,
        repo: str,
        searcher: account,
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
                    "`bm25`, `vector`, `hybrid`, `hybrid_hyde` or `agentic`, if available (422 "
                    "`mode_unavailable` otherwise). Default: the library's mode, else the "
                    "instance's, else the best one configured."
                ),
            ),
        ] = None,
        group_by: Annotated[
            ResultGrouping,
            Query(
                description=(
                    "`chunk` (default here): the results best first. `article`: the same results "
                    "grouped by article, as MCP's `search_docs` returns them (each result's "
                    "`group`)."
                )
            ),
        ] = ResultGrouping.CHUNK,
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
            group_by: `chunk` (best first) or `article` (grouped by article).
            searcher: The account searching.

        Returns:
            The results of that version.

        Raises:
            RequestValidationError: The query does not validate (a 422, like the request's own).
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
                group_by=group_by,
            )
        except ValidationError as error:  # what the Query() bounds above cannot see
            raise RequestValidationError(error.errors()) from error
        return await search_docs(query, caller=searcher)

    @router.get("/search")
    async def search_all(
        searcher: account,
        q: Annotated[
            str,
            Query(min_length=1, max_length=MAX_QUERY, description="Identifier, error or question."),
        ],
        library: Annotated[
            list[Annotated[str, Query(max_length=MAX_NAME)]] | None,
            Query(
                max_length=MAX_CHOSEN_LIBRARIES,
                description=(
                    "`/owner/repo` of a library to search; repeat or comma-separate for "
                    "several. None: every library you may read."
                ),
            ),
        ] = None,
        tags: Annotated[
            list[Annotated[str, Query(max_length=MAX_TAG)]] | None,
            Query(max_length=MAX_TAGS, description="Repeat or comma-separate."),
        ] = None,
        tags_match: TagMatch = TagMatch.ANY,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
        mode: Annotated[
            str | None,
            Query(
                max_length=MAX_NAME,
                description=(
                    "`bm25` (default), `vector` or `hybrid`; the vector modes need an embedding "
                    "model (422 `mode_unavailable` otherwise)."
                ),
            ),
        ] = None,
        group_by: Annotated[
            ResultGrouping,
            Query(
                description=(
                    "`chunk` (default here): the results best first. `article`: the same results "
                    "grouped by library and article, as MCP's `search_all_docs` returns them."
                )
            ),
        ] = ResultGrouping.CHUNK,
    ) -> SearchAllResult:
        """Search the default version of every library, or of the chosen ones, in one ranking.

        `libraries` counts the BM25 matches per library. Each result carries its `bm25_rank` and
        `vector_rank`; `retrieval_mode` says which mode answered and `fallback_reason` why BM25
        answered a vector search.

        Args:
            q: The query.
            library: Only these libraries' results.
            tags: Only chunks of articles so tagged.
            tags_match: `any` or `all` of the tags.
            limit: How many results at most.
            mode: The retrieval mode; `bm25` without one.
            group_by: `chunk` (best first) or `article` (grouped by library and article).
            searcher: The account searching.

        Returns:
            The results across libraries.

        Raises:
            RequestValidationError: The query does not validate.
        """
        try:
            query = SearchAllQuery(
                query=q,
                libraries=library or [],
                tags=tags or [],
                tags_match=tags_match,
                limit=limit,
                mode=mode,
                group_by=group_by,
            )
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        return await search_all_libraries(query, caller=searcher)

    @router.get("/chunks/{chunk_id}")
    async def get_chunk(chunk_id: Annotated[str, Path(max_length=MAX_NAME)]) -> ChunkOut:
        """Read a chunk verbatim by the ID of a search result.

        404 `not_found` when no version serves the ID; 409 `stale_chunk` when its version was
        re-synced since: search the version again for current IDs.

        Args:
            chunk_id: The chunk's ID.

        Returns:
            The chunk.
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

        Args:
            library_name: The library's name.
            query: What the caller wants to look up.

        Returns:
            The matching libraries, in context7's shape.
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
        asker: account,
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

        Args:
            asker: The account asking.
            library_id: The library ID, with or without a ref.
            query: What to look up.
            language: Programming language whose chunks come first.
            fmt: `txt` for the text, `json` for context7's JSON.

        Returns:
            The text, or the JSON response.

        Raises:
            RequestValidationError: The library ID or query does not validate.
        """
        try:
            request = QueryDocsQuery(
                library_id=_AT_VERSION.sub(r"\1/\2", library_id), query=query, language=language
            )
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        found = await query_docs(request, caller=asker)
        if fmt == "json":
            return C7ContextResponse.from_result(found)
        # The notice leads the body, as it leads the MCP result, and repeats in a header; the
        # notes (#605) close it, as they close the MCP result.
        notes = f"\n\nNotes: {' '.join(found.notes)}" if found.notes else ""
        return PlainTextResponse(
            f"{NOTICE}\n\n{format_docs(found)}{notes}", headers={NOTICE_HEADER: NOTICE}
        )

    return router


type _Event = tuple[str, dict[str, Any]]
"""A server-sent event: its name and its JSON data."""


class _QueuedProgress:
    """Implements ``ports.driven.AnswerProgress`` by queueing a ``progress`` event per call."""

    def __init__(self, queue: asyncio.Queue[_Event]) -> None:
        """Queue onto ``queue``.

        Args:
            queue: Where the events go.
        """
        self.queue = queue

    def tool_call(self, made: int, limit: int) -> None:
        """Queue a progress event.

        Args:
            made: Tool calls made so far.
            limit: The most the run may make.
        """
        self.queue.put_nowait(("progress", {"tool_calls": made, "max_tool_calls": limit}))


def _sse(event: _Event) -> str:
    """Write one server-sent event.

    Args:
        event: Its name and data.

    Returns:
        The event's text, ``event:`` and ``data:`` lines and a blank line.
    """
    name, data = event
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def _answer_events(
    task: asyncio.Task[AnswerResult], queue: asyncio.Queue[_Event]
) -> AsyncIterator[str]:
    """Stream an answer's progress, then the answer (or the error), as server-sent events.

    The run is cancelled when the client goes away.

    Args:
        task: The running answer.
        queue: Its progress events.

    Yields:
        ``progress`` events, then one ``answer`` (the ``AnswerResult``) or ``error`` event.
    """
    try:
        while True:
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter not in done:
                getter.cancel()
                break
            yield _sse(getter.result())
        while not queue.empty():
            yield _sse(queue.get_nowait())
        try:
            result = task.result()
        except DomainError as error:
            yield _sse(("error", {"error": error.code, "detail": str(error)}))
            return
        yield _sse(("answer", result.model_dump(mode="json")))
    finally:
        task.cancel()


def build_answer_router(
    *,
    answer_question: AnswerQuestion,
    get_answer_availability: GetAnswerAvailability,
    caller: Callable[..., Awaitable[str | None]],
) -> APIRouter:
    """Expose agentic answers over chosen libraries (#428): ``/answer``.

    Args:
        answer_question: Runs the answering agent.
        get_answer_availability: Says whether it can run.
        caller: The dependency naming the request's account (its spend and rate limit).

    Returns:
        The router.
    """
    router = APIRouter(tags=["retrieval"])
    account = Annotated[str | None, Depends(caller)]

    @router.get("/answer", name="get_answer_availability")
    async def availability() -> AnswerAvailabilityOut:
        """Say whether agentic answers can run now (an `llm` role is configured), and why not.

        Returns:
            Whether they can, why not, and the tool-call limit.
        """
        return await get_answer_availability()

    @router.post("/answer", name="answer_question")
    async def answer(body: AnswerQuery, asker: account) -> AnswerResult:
        """Answer a question from the default versions of chosen libraries with an agent.

        The agent reads only libraries you may read (and your API token's scope allows) with AI
        on, within `[ai.agentic]`'s limits, the budgets and the LLM search rate limit. Every
        source is checked against those libraries; `fallback_reason` says why there is no answer.
        422 `mode_unavailable` without an `llm` role; 404 for a chosen library you cannot read.

        Args:
            body: The question, the libraries and the filters.
            asker: The account asking.

        Returns:
            The answer, its sources and what the run used.
        """
        return await answer_question(body, caller=asker)

    @router.post(
        "/answer/stream",
        name="answer_question_stream",
        response_class=StreamingResponse,
        responses={
            200: {
                "content": {"text/event-stream": {}},
                "description": (
                    "Server-sent events: `progress` (`{tool_calls, max_tool_calls}`) after each "
                    "tool call, then one `answer` (an `AnswerResult`) or `error` "
                    "(`{error, detail}`, the error shape of the API)."
                ),
            }
        },
    )
    async def answer_stream(body: AnswerQuery, asker: account) -> StreamingResponse:
        """Answer as `POST /answer` does, streaming the agent's progress (server-sent events).

        Args:
            body: The question, the libraries and the filters.
            asker: The account asking.

        Returns:
            The event stream; closing it cancels the run.
        """
        queue: asyncio.Queue[_Event] = asyncio.Queue()
        task = asyncio.create_task(
            answer_question(body, caller=asker, progress=_QueuedProgress(queue))
        )
        return StreamingResponse(
            _answer_events(task, queue),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
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

        Raises:
            RequestValidationError: The library ID or path does not validate (a 422).
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


def _embedding_routes(
    router: APIRouter,
    estimate_embedding: EstimateEmbedding,
    get_embedding_progress: GetEmbeddingProgress,
) -> None:
    """Add the embedding routes to the AI router: the estimate and the progress per space.

    Args:
        router: The AI router.
        estimate_embedding: Estimates what embedding the versions not embedded yet costs.
        get_embedding_progress: Shows how far each embedding space has got.
    """

    @router.get("/embedding/estimate", name="estimate_embedding")
    async def estimate() -> EmbeddingEstimateOut:
        """Estimate the chunks, tokens and US dollars of embedding what is not embedded yet.

        Counts the distinct chunks of every active version (of libraries with AI on) that have no
        vector from the configured embedding model, counting tokens from characters, priced
        with the bundled price list. Calls no model and no tokenizer: an estimate, as `note` says.
        The REST form of `exactdocs ai estimate`.

        Returns:
            The estimate; `model` is null when no embedding model is configured.
        """
        return await estimate_embedding()

    @router.get("/embedding", name="get_embedding_progress")
    async def embedding_progress() -> EmbeddingProgressOut:
        """Show the configured embedding model and how far each embedding space has got.

        One entry per space that is not retired, oldest first: the active versions (of
        libraries with AI on) and their chunks, and how many of each it has vectors for. While
        a new model embeds, its space is `building` and the old one still answers searches.

        Returns:
            The progress; no space without a vector store.
        """
        return await get_embedding_progress()


def _usage_routes(
    router: APIRouter, get_ai_usage: GetAiUsage, get_spend_history: GetSpendHistory
) -> None:
    """Add the spend routes to the AI router: the usage and budgets now, and the history.

    Args:
        router: The AI router.
        get_ai_usage: Shows spend and budget left per scope.
        get_spend_history: Shows one scope's spend per UTC day or month.
    """

    @router.get("/usage", name="get_ai_usage")
    async def usage() -> AiUsageOut:
        """Show what AI calls spent today and this month, and the budget left, per scope.

        Scopes: the instance, embedding runs (instance-wide), then every library and account
        that spent something this month. Windows are UTC days and months. Tokens and requests
        are what the providers reported; `unpriced_requests` were calls to a model without a
        known price.

        Returns:
            The usage.
        """
        return await get_ai_usage()

    @router.get("/usage/history", name="get_ai_spend_history")
    async def usage_history(
        scope: SpendScope = "instance",
        scope_id: Annotated[
            str,
            Query(alias="id", max_length=MAX_NAME, description="Library or account ID."),
        ] = "",
        window: SpendWindow = SpendWindow.DAY,
        first: Annotated[
            date | None, Query(alias="from", description="A day of the first window (UTC).")
        ] = None,
        last: Annotated[
            date | None, Query(alias="to", description="A day of the last window (UTC).")
        ] = None,
    ) -> SpendHistoryOut:
        """Show what one scope spent per UTC day or month: one entry per window, zero-filled.

        `scope` and `id` name a scope as `GET /ai/usage` does (`library` and `user` need an
        `id`; `instance` and `embedding` take none). Any day of a month stands for the month.
        Without `to` the range ends today; without `from` it holds 30 days or 12 months. At
        most 366 days or 60 months (422 `invalid_spend_history`, also when `to` is before
        `from` or the `id` does not fit the scope).

        Args:
            scope: The scope kind.
            scope_id: The library or account ID.
            window: `day` or `month`.
            first: A day of the first window.
            last: A day of the last window.

        Returns:
            The entries, oldest first.
        """
        query = _command(
            lambda: SpendHistoryQuery(
                scope=scope, id=scope_id, window=window, first=first, last=last
            )
        )
        return await get_spend_history(query)


def build_ai_router(
    *,
    list_providers: ListProviders,
    get_provider: GetProvider,
    save_provider: SaveProvider,
    delete_provider: DeleteProvider,
    check_provider: CheckProvider,
    list_roles: ListRoles,
    set_role_thinking: SetRoleThinking,
    estimate_embedding: EstimateEmbedding,
    get_embedding_progress: GetEmbeddingProgress,
    get_ai_usage: GetAiUsage,
    get_spend_history: GetSpendHistory,
) -> APIRouter:
    """Build the routes of the AI provider profiles and roles (RET-01..03), admins only.

    Args:
        list_providers: Lists the profiles.
        get_provider: Reads one.
        save_provider: Creates or replaces one.
        delete_provider: Deletes one.
        check_provider: Makes one minimal call per role that uses one.
        list_roles: Shows the instance's roles.
        set_role_thinking: Sets an instance role's thinking level.
        estimate_embedding: Estimates what embedding the versions not embedded yet costs.
        get_embedding_progress: Shows how far each embedding space has got.
        get_ai_usage: Shows spend and budget left per scope.
        get_spend_history: Shows one scope's spend per UTC day or month.

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

    @router.put("/roles/{role}", name="set_role_thinking")
    async def set_thinking(role: ModelRole, body: RoleThinkingIn) -> RoleOut:
        """Set (or clear, with null) the thinking level of the `llm` or `judge` role.

        The level is sent as the provider's own setting at the next call: Google's thinking level
        or budget, Claude's effort or budget, OpenAI's `reasoning_effort`. A level set in the
        environment or the configuration file (`EXACTDOCS_AI__<ROLE>__THINKING`) cannot be
        changed here (409 `role_configured`); another role takes none (422
        `role_takes_no_thinking`); a level the role's model cannot take is refused (422
        `thinking_unsupported`, naming the role and the model).

        Args:
            role: `llm` or `judge`.
            body: The level.

        Returns:
            The role as it is now.
        """
        command = _command(lambda: SetRoleThinkingCommand(role=role, thinking=body.thinking))
        return await set_role_thinking(command)

    _embedding_routes(router, estimate_embedding, get_embedding_progress)

    _usage_routes(router, get_ai_usage, get_spend_history)

    return router
