"""Driving (primary) ports of retrieval."""

from typing import Protocol

from exactdocs.retrieval.dtos import (
    AiUsageOut,
    AnswerAvailabilityOut,
    AnswerQuery,
    AnswerResult,
    ArticleOutlineOut,
    ArticleOutlineQuery,
    CheckProviderCommand,
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
    DiscardPendingChunksCommand,
    EmbedBatchCommand,
    EmbeddedBatchOut,
    EmbeddingEstimateOut,
    EmbeddingPlanOut,
    EmbeddingProgressOut,
    EmbeddingSpaceOut,
    EmbedVersionCommand,
    ExternalIndexScope,
    FinishedEmbeddingOut,
    FinishEmbeddingCommand,
    ForgetLibraryCommand,
    GetChunkSetsQuery,
    GetLibraryRetrievalQuery,
    IndexDriftOut,
    IndexedManifestOut,
    IndexManifestCommand,
    LibraryRetrievalOut,
    ModelChecksOut,
    OpenEmbeddingSpaceCommand,
    ProviderListOut,
    ProviderNameQuery,
    ProviderOut,
    PrunedHypothesesOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    RebuiltIndexOut,
    RebuiltVersionsOut,
    RemoveChunksCommand,
    RemovedChunks,
    ResolveLibraryIdQuery,
    ResolveLibraryIdResult,
    RetagArticlesCommand,
    RetaggedChunks,
    RoleListOut,
    RoleOut,
    SaveProviderCommand,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
    SearchIndexStateOut,
    SetLibraryRetrievalCommand,
    SetRoleThinkingCommand,
    UnembeddedVersionsOut,
    UnembeddedVersionsQuery,
    VectorStoreStateOut,
)
from exactdocs.retrieval.ports.driven import AnswerProgress


class SearchDocs(Protocol):
    """Search within one library version (the default one without a ref).

    Raises ``VersionNotIndexedError`` for an unknown version; a known version without matches
    gives an empty ``results``. Never answers from another version.
    """

    async def __call__(
        self, query: SearchDocsQuery, *, caller: str | None = None
    ) -> SearchDocsResult:
        """Run the use case.

        Args:
            query: The search.
            caller: The account searching (an API token's or a session's); ``None`` for a stdio
                MCP process. Its LLM searches are rate limited and its spend counted to it.

        Returns:
            The results of the one version searched.
        """
        ...


class AnswerQuestion(Protocol):
    """Answer a question from the default versions of chosen libraries with an agent (#428).

    The agent runs on the instance's ``llm`` role, bounded like an agentic search
    (``[ai.agentic]``, the budgets, the LLM search rate limit), reading only libraries the caller
    may read (roles and the API token's scope) with AI on. Every cited chunk is checked against
    those libraries' versions. Raises ``UnavailableModeError`` without an ``llm`` role and
    ``VersionNotIndexedError`` for a chosen library without a readable default version. A limit,
    a budget, a loop or a failure never raises: the result says why in ``fallback_reason``.
    """

    async def __call__(
        self,
        query: AnswerQuery,
        *,
        caller: str | None = None,
        progress: AnswerProgress | None = None,
    ) -> AnswerResult:
        """Run the use case.

        Args:
            query: The question, the libraries and the filters.
            caller: The account asking: its spend and rate limit.
            progress: Hears each tool call (a progress stream); none by default.

        Returns:
            The answer and its sources, with what the run used.
        """
        ...


class GetAnswerAvailability(Protocol):
    """Say whether agentic answers can run now, and why not (#428)."""

    async def __call__(self) -> AnswerAvailabilityOut:
        """Run the use case.

        Returns:
            Whether they can, why not, and the tool-call limit.
        """
        ...


class SearchAllLibraries(Protocol):
    """Search the default version of every library at once (or of the chosen ones).

    Each result names its library and version, and its BM25 and vector ranks; ``libraries``
    counts the matches per library over all of them, also when ``library`` narrows the results.
    A version other than a library's default never answers. ``mode`` is ``bm25``, ``vector`` or
    ``hybrid``; a mode that cannot run raises ``UnavailableModeError``. Raises
    ``VersionNotIndexedError`` for a chosen library that has no readable default version.
    """

    async def __call__(
        self, query: SearchAllQuery, *, caller: str | None = None
    ) -> SearchAllResult:
        """Run the use case.

        Args:
            query: The query, the mode, the libraries, the filters and the limit.
            caller: The account searching (a paid query embedding counts to it).

        Returns:
            The results across libraries, best first, and the matches per library.
        """
        ...


class IndexManifest(Protocol):
    """Store the chunks of a catalog manifest, invisible until the catalog activates it.

    Idempotent: a manifest ID that is already indexed changes nothing and returns the same IDs.
    Raises ``DuplicateChunkError`` when two chunks of an article would share an ID.
    """

    async def __call__(self, command: IndexManifestCommand) -> IndexedManifestOut:
        """Run the use case.

        Args:
            command: The manifest and the chunks of each of its articles.

        Returns:
            The chunk IDs of every article and how many chunk sets were new.
        """
        ...


class GetChunkSets(Protocol):
    """Return the stored chunks of blobs chunked under one config; unknown blobs are left out.

    This is how an importer skips chunking a blob that an earlier import already chunked.
    """

    async def __call__(self, query: GetChunkSetsQuery) -> ChunkSetsOut:
        """Run the use case.

        Args:
            query: The chunking config and the blobs.

        Returns:
            The stored chunks of each blob that has them.
        """
        ...


class ReadChunk(Protocol):
    """Read one chunk verbatim by its ID; the ID names its version, so nothing else is needed.

    Only the version's active manifest is served. Raises ``StaleChunkError`` for an ID of a
    superseded manifest of a version that still exists, and ``ChunkNotFoundError`` for an ID
    nobody serves (unknown, still pending, or collected).
    """

    async def __call__(self, query: ReadChunkQuery) -> ChunkOut:
        """Run the use case.

        Args:
            query: The chunk ID.

        Returns:
            The chunk verbatim, with its place in the article and its version.
        """
        ...


class ArticleOutline(Protocol):
    """Return an article's heading tree with the chunk ID of each heading, without any text.

    Version is a hard filter: raises ``VersionNotIndexedError`` for a version that is not
    imported and ``ArticleNotFoundError`` for a path the version does not have, never answering
    from another version. Needs no AI configuration: it reads only stored chunk rows.
    """

    async def __call__(self, query: ArticleOutlineQuery) -> ArticleOutlineOut:
        """Run the use case.

        Args:
            query: The library, the exact ref (or none for the default version) and the path.

        Returns:
            The heading tree with a chunk ID per heading and the version that answered.
        """
        ...


class DiscardPendingChunks(Protocol):
    """Delete the chunk rows of manifests that never became active (never "all")."""

    async def __call__(self, command: DiscardPendingChunksCommand) -> RemovedChunks:
        """Run the use case.

        Args:
            command: Which manifests: by ID, by library or by age.

        Returns:
            What was deleted.
        """
        ...


class CollectChunks(Protocol):
    """Delete chunk rows of manifests the catalog collected, then unused chunk sets."""

    async def __call__(self, command: CollectChunksCommand) -> RemovedChunks:
        """Run the use case.

        Args:
            command: The grace period.

        Returns:
            What was deleted.
        """
        ...


class RemoveChunks(Protocol):
    """Delete the chunk rows and unused chunk sets of manifests the catalog no longer knows.

    A manifest the catalog still knows (in any state) is kept, whatever the caller says. Unlike
    ``CollectChunks`` it needs no grace period: the caller names IDs the catalog just deleted.
    """

    async def __call__(self, command: RemoveChunksCommand) -> RemovedChunks:
        """Run the use case.

        Args:
            command: The manifests the catalog deleted.

        Returns:
            What was deleted.
        """
        ...


class ResolveLibraryId(Protocol):
    """Find libraries by name, like context7's ``resolve-library-id``.

    Matches the name against library IDs, titles and descriptions in memory, then ranks the best
    candidates by how many chunks of their default version match ``query``. Never searches a
    version other than the default one.
    """

    async def __call__(self, query: ResolveLibraryIdQuery) -> ResolveLibraryIdResult:
        """Run the use case.

        Args:
            query: The library name and what the caller wants to look up.

        Returns:
            The matching libraries, best first.
        """
        ...


class QueryDocs(Protocol):
    """Return documentation for a context7-style library ID, within a size budget.

    `/owner/repo` is the default version, `/owner/repo/<ref>` exactly that ref; raises
    ``VersionNotIndexedError`` for a version that is not imported and never answers from another.
    Only whole chunks are returned, best first, within the configured budget; one too large to fit
    is listed as a pointer for ``read_chunk``. ``language`` only reorders the best matches (chunks
    with code in it first); it never filters, and a chunk ranked beyond the candidates is not seen.
    """

    async def __call__(
        self, query: QueryDocsQuery, *, caller: str | None = None
    ) -> QueryDocsResult:
        """Run the use case.

        Args:
            query: The library ID and the question.
            caller: The account asking; ``None`` for a stdio MCP process.

        Returns:
            Whole chunks of the one version, best first, within the budget.
        """
        ...


class RetagArticles(Protocol):
    """Copy an article's current tags onto its chunk rows in one manifest (no re-chunking).

    Tags change outside an import (a user tags an article by hand); the chunk rows hold a copy
    so a search can filter by tag. Unknown manifests and paths change nothing.
    """

    async def __call__(self, command: RetagArticlesCommand) -> RetaggedChunks:
        """Run the use case.

        Args:
            command: The manifest and each article's current tags.

        Returns:
            How many chunk rows got other tags.
        """
        ...


class GetSearchIndexState(Protocol):
    """Say which format the search index is in and whether ``RebuildSearchIndex`` is needed."""

    async def __call__(self) -> SearchIndexStateOut:
        """Run the use case.

        Returns:
            The stored and current formats, and the engine that answers.
        """
        ...


class GetVectorStoreState(Protocol):
    """Say whether the vector store can search, once an embedding model is configured."""

    async def __call__(self) -> VectorStoreStateOut:
        """Run the use case.

        Returns:
            What the store needs, and whether it has it (not checked without an embedding model).
        """
        ...


class RebuildSearchIndex(Protocol):
    """Rebuild the search index from the stored chunks while the old one keeps answering.

    No import runs again: the chunks are already stored. Needed after a release whose notes say
    "requires reindex"; harmless otherwise.
    """

    async def __call__(self) -> RebuiltIndexOut:
        """Run the use case.

        Returns:
            The format the index is now in and how many chunks it holds.
        """
        ...


class CheckExternalIndexes(Protocol):
    """Compare the external search and vector backends with the stored chunks (#352).

    Reports every version a backend lost (``missing``), holds only in part (``incomplete``) or
    still holds after the database removed it (``orphaned``). Nothing is checked, and nothing
    drifts, when every index lives in the database.
    """

    async def __call__(self, scope: ExternalIndexScope) -> IndexDriftOut:
        """Run the use case.

        Args:
            scope: Which versions to check.

        Returns:
            What drifted.
        """
        ...


class RebuildExternalIndexes(Protocol):
    """Write the stored chunks (and their stored vectors) to the external backends again (#352).

    Every indexed version, or one library's, or one version's; versions the database no longer
    has are deleted from the backends when nothing narrows the scope. Nothing is imported or
    embedded again: everything comes from the database. Safe while serving and to repeat.
    """

    async def __call__(self, scope: ExternalIndexScope) -> RebuiltVersionsOut:
        """Run the use case.

        Args:
            scope: Which versions to write.

        Returns:
            What was written.

        Raises:
            UnknownIndexVersionError: ``scope.version`` names no indexed version.
        """
        ...


class GetLibraryRetrieval(Protocol):
    """Read a library's retrieval mode and the mode its searches use now.

    Raises ``UnknownLibraryError`` when there is no such library.
    """

    async def __call__(self, query: GetLibraryRetrievalQuery) -> LibraryRetrievalOut:
        """Run the use case.

        Args:
            query: The library.

        Returns:
            Its setting, the mode its searches use now, and the modes available.
        """
        ...


class SetLibraryRetrieval(Protocol):
    """Set or clear a library's retrieval mode; it must be a mode that can run now.

    Raises ``UnknownLibraryError`` when there is no such library, ``UnavailableModeError`` when
    the mode is unknown or a model role it needs is not configured.
    """

    async def __call__(self, command: SetLibraryRetrievalCommand) -> LibraryRetrievalOut:
        """Run the use case.

        Args:
            command: The library and its mode (none: clear it).

        Returns:
            The stored setting, the mode its searches use now, and the modes available.
        """
        ...


class ForgetLibrary(Protocol):
    """Drop what retrieval keeps for a removed library (its mode); a no-op for an unknown one."""

    async def __call__(self, command: ForgetLibraryCommand) -> None:
        """Run the use case.

        Args:
            command: The removed library.
        """
        ...


class ListProviders(Protocol):
    """List every AI provider profile: configured ones (read-only) and stored ones."""

    async def __call__(self) -> ProviderListOut:
        """Run the use case.

        Returns:
            The profiles, without keys or header values.
        """
        ...


class GetProvider(Protocol):
    """Read one AI provider profile. Raises ``UnknownProviderError``."""

    async def __call__(self, query: ProviderNameQuery) -> ProviderOut:
        """Run the use case.

        Args:
            query: The profile's name.

        Returns:
            The profile, without its key or header values.
        """
        ...


class SaveProvider(Protocol):
    """Create or replace a profile over the REST API; its key is sealed, never returned.

    Raises ``InvalidProviderError``, ``ProviderExistsError`` (create), ``ProviderReadOnlyError``
    (a configured name), ``ProviderUnsupportedError`` and ``SecretKeyRequiredError``.
    """

    async def __call__(self, command: SaveProviderCommand) -> ProviderOut:
        """Run the use case.

        Args:
            command: The profile.

        Returns:
            The stored profile, without its key.
        """
        ...


class DeleteProvider(Protocol):
    """Delete a stored profile.

    Raises ``UnknownProviderError``, ``ProviderReadOnlyError`` and ``ProviderInUseError`` (an
    instance role uses it).
    """

    async def __call__(self, command: ProviderNameQuery) -> None:
        """Run the use case.

        Args:
            command: The profile's name.
        """
        ...


class CheckProvider(Protocol):
    """Make one minimal call per role that uses a profile (or to a model named).

    Raises ``UnknownProviderError`` and ``NothingToCheckError``.
    """

    async def __call__(self, command: CheckProviderCommand) -> ModelChecksOut:
        """Run the use case.

        Args:
            command: The profile, and optionally a role and a model.

        Returns:
            One check per call.
        """
        ...


class CheckRoles(Protocol):
    """Make one minimal call per configured instance role (``exactdocs ai check``)."""

    async def __call__(self) -> ModelChecksOut:
        """Run the use case.

        Returns:
            One check per role that is set; none when no role is.
        """
        ...


class ListRoles(Protocol):
    """Show the instance's roles and the model each uses."""

    async def __call__(self) -> RoleListOut:
        """Run the use case.

        Returns:
            One entry per role.
        """
        ...


class SetRoleThinking(Protocol):
    """Set or clear an instance role's thinking level over the REST API (#421).

    Raises ``RoleTakesNoThinkingError`` (not ``llm`` or ``judge``), ``RoleConfiguredError``
    (the level is set in the environment or the configuration file) and
    ``ThinkingUnsupportedError`` (the role's model cannot take a level).
    """

    async def __call__(self, command: SetRoleThinkingCommand) -> RoleOut:
        """Run the use case.

        Args:
            command: The role and its level.

        Returns:
            The role as it is now.
        """
        ...


class OpenEmbeddingSpace(Protocol):
    """Find the embedding space of a model, or create one when the model changed (RET-01).

    A space is one (profile kind, model, dimensions, input format): a different model never
    reuses another's space, so its vectors are never compared with another model's. A new space
    starts ``building``; switching to it and retiring the old one is the embedding job's.
    """

    async def __call__(self, command: OpenEmbeddingSpaceCommand) -> EmbeddingSpaceOut:
        """Run the use case.

        Args:
            command: The model the instance embeds with now.

        Returns:
            The space that is not retired for it, created if there was none.
        """
        ...


class PlanEmbedding(Protocol):
    """Start an ``embed`` job of one version: pick its space and say how much is missing.

    Sends nothing of the library when it has AI off. Creates the space of the configured model
    when it has none (asking the model its dimensions once, with a fixed text, unless they are
    configured), and says so: every other version then needs embedding too.
    """

    async def __call__(self, command: EmbedVersionCommand) -> EmbeddingPlanOut:
        """Run the use case.

        Args:
            command: The version.

        Returns:
            The plan; ``skipped`` says why nothing is to be sent.
        """
        ...


class EmbedBatch(Protocol):
    """Embed the next chunks of a manifest that have no vector in the space (one durable step).

    Reads the library's AI setting and the configured model again first: a library switched off,
    or a model changed, meanwhile stops the job with nothing sent. Records the usage the provider
    returned in the spend ledger.
    """

    async def __call__(self, command: EmbedBatchCommand) -> EmbeddedBatchOut:
        """Run the use case.

        Args:
            command: The plan's version, manifest and space.

        Returns:
            What was embedded, and whether the manifest is done.
        """
        ...


class FinishEmbedding(Protocol):
    """Make a space active once it covers every version, and retire the spaces it replaces."""

    async def __call__(self, command: FinishEmbeddingCommand) -> FinishedEmbeddingOut:
        """Run the use case.

        Args:
            command: The space a job embedded into.

        Returns:
            Its state, and the spaces retired.
        """
        ...


class ListUnembeddedVersions(Protocol):
    """Name the versions the configured embedding model has not fully embedded (no call made)."""

    async def __call__(self, query: UnembeddedVersionsQuery) -> UnembeddedVersionsOut:
        """Run the use case.

        Args:
            query: Every library, or one.

        Returns:
            The versions to queue ``embed`` jobs for.
        """
        ...


class EstimateEmbedding(Protocol):
    """Estimate the chunks, tokens and US dollars of embedding what is not embedded yet.

    Never calls the model or a tokenizer: 4 characters per token, and the bundled price list.
    """

    async def __call__(self) -> EmbeddingEstimateOut:
        """Run the use case.

        Returns:
            The estimate.
        """
        ...


class GetEmbeddingProgress(Protocol):
    """Show how far each embedding space has got: versions and chunks with vectors (admins)."""

    async def __call__(self) -> EmbeddingProgressOut:
        """Run the use case.

        Returns:
            The configured model and every space that is not retired.
        """
        ...


class GetAiUsage(Protocol):
    """Show what AI calls spent per scope today and this month, and the budgets left (admins)."""

    async def __call__(self) -> AiUsageOut:
        """Run the use case.

        Returns:
            The instance, the embedding budget, then every library and user that spent this month.
        """
        ...


class PruneHypotheses(Protocol):
    """Delete HyDE's and the agentic cache's answers past their TTL or of retired models.

    Run once a day by the server (one process on PostgreSQL), and by every collection.
    """

    async def __call__(self) -> PrunedHypothesesOut:
        """Run the use case.

        Returns:
            How many answers were deleted.
        """
        ...
