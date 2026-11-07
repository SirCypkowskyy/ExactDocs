import asyncio
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from exactdocs.retrieval.constants import (
    CHARS_PER_TOKEN,
    DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
    FOOTER_CHARS,
    MAX_RESOLVED,
    MAX_SEARCHED_LIBRARIES,
    POINTER_TEXT,
    QUERY_DOCS_CANDIDATES,
    QUERY_HITS_CAP,
    RULE_FRAMING_CHARS,
    RULES_FRAMING_CHARS,
    RULES_SHARE,
    SECTION_FRAMING_CHARS,
    UNKNOWN_MANIFEST_GRACE,
)
from exactdocs.retrieval.dtos import (
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
    CoverageOut,
    DiscardPendingChunksCommand,
    DocSectionOut,
    GetChunkSetsQuery,
    GetLibraryRetrievalQuery,
    IndexedManifestOut,
    IndexManifestCommand,
    LibraryFacetOut,
    LibraryMatchOut,
    LibraryRetrievalOut,
    LibrarySearchResultOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    RebuiltIndexOut,
    RemoveChunksCommand,
    RemovedChunks,
    ResolveLibraryIdQuery,
    ResolveLibraryIdResult,
    RetagArticlesCommand,
    RetaggedChunks,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
    SearchIndexStateOut,
    SearchResultOut,
    SetChunkOut,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.errors import (
    ChunkNotFoundError,
    MovedSection,
    StaleChunkError,
    UnknownLibraryError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    Candidate,
    CatalogLibrary,
    Chunk,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    IndexedManifest,
    ManifestChunk,
    ManifestStatus,
    ModeChoice,
    ModelRole,
    ModeRegistry,
    NameMatch,
    PipelineAnswer,
    PipelineRequest,
    RetrievalMode,
    SearchableVersion,
    SearchText,
    SectionRef,
    TagFilter,
    TagMatch,
    article_chunk_rows,
    language_first,
    name_match,
    rank_matches,
)
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ChunkRepository,
    DefaultVersions,
    Libraries,
    LibraryModes,
    ModelRoles,
    RenamedPaths,
    RetrievalPipeline,
    SearchableVersions,
    SearchIndex,
    SearchIndexMaintenance,
    SearchTracer,
)
from exactdocs_kernel import NOTICE, Clock


async def _confirmed_removals(
    manifests: ActiveManifests,
    candidates: Sequence[IndexedManifest],
    *,
    now: datetime,
    pending_too: bool,
) -> list[str]:
    """Import asyncioPick the manifests safe to remove, asking the catalog twice.

    Removable: pending in the catalog (when ``pending_too``), or unknown to it and older than
    the grace period. Everything else stays, including a status we cannot name. The second
    question comes right before the delete and narrows the window in which a manifest could
    be activated; it cannot close it, as that would take a transaction across both domains.
    """
    unknown_before = now - UNKNOWN_MANIFEST_GRACE
    survivors = list(candidates)
    for _ in range(2):
        statuses = await manifests.statuses([m.manifest_id for m in survivors])
        survivors = [
            m
            for m in survivors
            if ((status := statuses.get(m.manifest_id)) is None and m.indexed_at < unknown_before)
            or (pending_too and status is ManifestStatus.PENDING)
        ]
        if not survivors:
            break
    return [m.manifest_id for m in survivors]


@dataclass(frozen=True, slots=True, kw_only=True)
class UntracedSearches:
    """Implements ``ports.driven.SearchTracer`` by recording nothing (telemetry is off)."""

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[object]:
        """Open nothing.

        Args:
            name: The search, or the search and its stage after a dot.
            mode: The retrieval mode the search runs in.
            query: The query text.
            attributes: Further labels.

        Returns:
            A context manager that does nothing.
        """
        del name, mode, query, attributes
        return nullcontext()


@dataclass(frozen=True, slots=True, kw_only=True)
class NoModelRoles:
    """Implements ``ports.driven.ModelRoles`` for an instance with no model configured."""

    async def configured(self) -> frozenset[ModelRole]:
        """Say that no role is set.

        Returns:
            The empty set: BM25 is the only mode.
        """
        return frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class Bm25Pipeline:
    """Implements ``ports.driven.RetrievalPipeline`` for ``bm25``: the full-text index alone."""

    search: SearchIndex
    """The full-text index."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        """Rank the version's chunks with BM25.

        Args:
            request: What to search; ``rerank`` is ignored until a reranker exists.

        Returns:
            The best hits, and whether more matched than the limit allowed.
        """
        # One more than asked for tells whether the answer was cut short.
        found = await self.search.search(
            request.version.manifest_id, request.query, request.tag_filter, request.limit + 1
        )
        return PipelineAnswer(
            mode=RetrievalMode.BM25,
            hits=tuple(found[: request.limit]),
            candidates=len(found),
            reranked=0,
            complete=len(found) <= request.limit,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalModes:
    """Picks the mode of a search and runs its pipeline (RET-06, MCP-05).

    The mode is the call's, else the library's, else the instance's, else the best one that can
    run: a mode can run when a pipeline is registered for it and the model roles it needs are
    configured. Roles and library settings are read at every search, so changes count at once.
    """

    pipelines: Mapping[RetrievalMode, RetrievalPipeline]
    """The pipeline of each mode this build can run; BM25 always."""
    roles: ModelRoles
    """Which model roles are configured, asked at every search."""
    library_modes: LibraryModes
    """Each library's own mode."""
    instance_mode: RetrievalMode | None = None
    """The operator's default for every library (``EXACTDOCS_RETRIEVAL_MODE``)."""

    async def registry(self) -> ModeRegistry:
        """Say which modes can run now.

        Returns:
            The registry of the configured roles and the registered pipelines.
        """
        return ModeRegistry(
            roles=await self.roles.configured(), pipelines=frozenset(self.pipelines)
        )

    async def choose(self, *, asked: str | None, library: str) -> ModeChoice:
        """Pick the mode of a search of ``library``.

        Args:
            asked: The mode the call names, if any.
            library: The library searched, any letter case.

        Returns:
            The mode, whether to rerank, and why a setting was skipped. A call that names a
            mode that cannot run now fails with ``UnavailableModeError``.
        """
        registry = await self.registry()
        if asked is not None:  # checked first: the library's setting does not matter then
            return registry.choose(asked=asked, library=None, instance=None)
        return registry.choose(
            asked=None,
            library=await self.library_modes.mode_of(library),
            instance=self.instance_mode,
        )

    async def run(
        self,
        choice: ModeChoice,
        version: SearchableVersion,
        query: str,
        tag_filter: TagFilter,
        limit: int,
    ) -> PipelineAnswer:
        """Run the chosen mode's pipeline on one version.

        Args:
            choice: The mode picked by ``choose``.
            version: The exact version searched.
            query: The query text.
            tag_filter: Which chunks may be returned.
            limit: How many hits to return at most.

        Returns:
            The pipeline's answer; the choice's fallback reason unless the pipeline gave one.
        """
        answer = await self.pipelines[choice.mode].run(
            PipelineRequest(
                version=version,
                query=query,
                tag_filter=tag_filter,
                limit=limit,
                rerank=choice.rerank,
            )
        )
        if answer.fallback_reason is None and choice.fallback_reason is not None:
            return replace(answer, fallback_reason=choice.fallback_reason)
        return answer


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchDocsUseCase:
    """Implements ``ports.driving.SearchDocs``."""

    versions: SearchableVersions
    modes: RetrievalModes
    """Picks the mode and runs its pipeline."""
    chunks: ChunkRepository
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
        """Search the active manifest of one exact version; never fall back to another version."""
        # Built only to refuse a whitespace-only query (EmptySearchTextError).
        text = SearchText(value=query.query)
        choice = await self.modes.choose(asked=query.mode, library=query.library)
        with self.tracer.span(
            "search_docs",
            mode=choice.mode.value,
            query=text.value,
            library=query.library,
            ref=query.ref,
        ):
            return await self._search(query, text, choice)

    async def _search(
        self, query: SearchDocsQuery, text: SearchText, choice: ModeChoice
    ) -> SearchDocsResult:
        """Resolve the version, rank its chunks and load the shown ones, one span per stage.

        Args:
            query: The search as asked.
            text: Its validated query text.
            choice: The retrieval mode it runs in.

        Returns:
            The results of the one version searched.
        """
        mode = choice.mode.value
        with self.tracer.span("search_docs.version", mode=mode):
            version = await self.versions.find(query.library, query.ref)
        if version is None:
            raise VersionNotIndexedError(query.library, query.ref or "(default version)")
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        with self.tracer.span("search_docs.rank", mode=mode):
            answer = await self.modes.run(choice, version, text.value, tag_filter, query.limit)
        with self.tracer.span("search_docs.chunks", mode=mode):
            stored = await self.chunks.get_many(
                version.manifest_id, [h.chunk_id for h in answer.hits]
            )
        # A chunk gone since the search (the manifest was collected) leaves no result, and is not
        # counted as a candidate either, so results and coverage stay consistent.
        results = [
            SearchResultOut.from_models(version, stored[hit.chunk_id], hit)
            for hit in answer.hits
            if hit.chunk_id in stored
        ]
        vanished = len(answer.hits) - len(results)
        return SearchDocsResult(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            retrieval_mode=answer.mode,
            reranked=answer.reranked > 0,
            coverage=CoverageOut(
                candidates=answer.candidates - vanished,
                reranked=answer.reranked,
                complete=answer.complete,
            ),
            fallback_reason=answer.fallback_reason,
            results=results,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchAllLibrariesUseCase:
    """Implements ``ports.driving.SearchAllLibraries``."""

    defaults: DefaultVersions
    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

    async def __call__(self, query: SearchAllQuery) -> SearchAllResult:
        """Rank the chunks of all default versions together; count the matches per library.

        There is no ``mode`` (BM25 only until E11), unlike ``search_docs``. With ``library`` set
        every library is still resolved: the counts stay global, which a facet needs.
        """
        text = SearchText(value=query.query)
        mode = RetrievalMode.BM25.value
        with self.tracer.span(
            "search_all_libraries", mode=mode, query=text.value, library=query.library
        ):
            return await self._search(query, text, mode)

    async def _search(self, query: SearchAllQuery, text: SearchText, mode: str) -> SearchAllResult:
        """Resolve the default versions, rank and count, then load the shown chunks.

        Args:
            query: The search as asked.
            text: Its validated query text.
            mode: The retrieval mode it runs in.

        Returns:
            The results across the libraries, with a facet per library.
        """
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        with self.tracer.span("search_all_libraries.versions", mode=mode):
            every = await self.defaults.all()
        searched = {v.manifest_id: v for v in every[:MAX_SEARCHED_LIBRARIES]}
        omitted = len(every) - len(searched)
        scope = searched
        if query.library is not None:
            with self.tracer.span("search_all_libraries.versions", mode=mode):
                only = await self.versions.find(query.library, None)
            if only is None:
                raise VersionNotIndexedError(query.library, "(default version)")
            if only.manifest_id not in searched:  # beyond the cap: searched, so no longer omitted
                searched[only.manifest_id] = only
                omitted -= 1
            scope = {only.manifest_id: only}
        # One more than asked for tells whether the answer was cut short.
        with self.tracer.span("search_all_libraries.rank", mode=mode):
            found_hits, counts = await asyncio.gather(
                self.search.search_many(list(scope), text.value, tag_filter, query.limit + 1),
                self.search.count_many(list(searched), text.value, tag_filter),
            )
        shown = found_hits[: query.limit]
        wanted: dict[str, list[ChunkId]] = {}
        for found_hit in shown:
            wanted.setdefault(found_hit.manifest_id, []).append(found_hit.hit.chunk_id)
        with self.tracer.span("search_all_libraries.chunks", mode=mode):
            stored = await self.chunks.get_across(wanted)
        # A chunk gone since the search (the manifest was collected) leaves no result.
        results = [
            LibrarySearchResultOut.of(
                searched[found_hit.manifest_id],
                stored[found_hit.manifest_id, found_hit.hit.chunk_id],
                found_hit.hit,
            )
            for found_hit in shown
            if (found_hit.manifest_id, found_hit.hit.chunk_id) in stored
        ]
        vanished = len(shown) - len(results)
        facets = sorted(
            (
                LibraryFacetOut(
                    library=searched[m].library,
                    version=searched[m].version,
                    commit_sha=searched[m].commit_sha,
                    matches=n,
                )
                for m, n in counts.items()
                if m in searched and n > 0
            ),
            key=lambda f: (-f.matches, f.library),
        )
        return SearchAllResult(
            retrieval_mode=RetrievalMode.BM25,
            reranked=False,
            coverage=CoverageOut(
                candidates=len(found_hits) - vanished,
                reranked=0,
                complete=len(found_hits) <= query.limit,
            ),
            libraries_searched=len(searched),
            libraries_omitted=omitted,
            libraries=facets,
            results=results,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexManifestUseCase:
    """Implements ``ports.driving.IndexManifest``."""

    chunks: ChunkRepository
    search: SearchIndex
    clock: Clock

    async def __call__(self, command: IndexManifestCommand) -> IndexedManifestOut:
        """Compute the chunk IDs, store the rows plus the new chunk sets, and make them searchable.

        Call it between the catalog's store (pending) and its activate, never after.
        """
        library = command.library.lower()
        manifest = IndexedManifest(
            manifest_id=command.manifest_id,
            version_id=f"{library}/{command.ref}",
            library=library,
            indexed_at=self.clock.now(),
        )
        chunk_sets, rows = await asyncio.to_thread(self._build, command, manifest)
        stored = await self.chunks.add(manifest, chunk_sets, rows)
        # Also when the manifest was already indexed: a crash between the two calls above and
        # below leaves sets without index entries, and indexing only fills gaps.
        for chunk_set in chunk_sets.values():
            await self.search.index(chunk_set)
        ids: dict[str, list[str]] = {a.path: [] for a in command.articles}
        for row in rows:
            ids[row.article_path].append(row.chunk_id)
        return IndexedManifestOut(
            manifest_id=command.manifest_id,
            chunk_ids=ids,
            chunk_sets_stored=stored or 0,
            already_indexed=stored is None,
        )

    @staticmethod
    def _build(
        command: IndexManifestCommand, manifest: IndexedManifest
    ) -> tuple[dict[ChunkSetKey, ChunkSet], list[ManifestChunk]]:
        """Make the chunk sets and rows: CPU-bound (chunk IDs are hashed), so run in a thread."""
        chunk_sets: dict[ChunkSetKey, ChunkSet] = {}
        rows: list[ManifestChunk] = []
        for article in command.articles:
            chunk_set = chunk_sets.setdefault(
                (article.blob_sha, command.config_hash),
                ChunkSet(
                    blob_sha=article.blob_sha,
                    config_hash=command.config_hash,
                    chunks=tuple(
                        Chunk(
                            heading_path=tuple(c.heading_path),
                            occurrence_index=c.occurrence_index,
                            content=c.content,
                            content_hash=c.content_hash,
                            anchor=c.anchor,
                            code_languages=tuple(c.code_languages),
                        )
                        for c in article.chunks
                    ),
                ),
            )
            rows += article_chunk_rows(
                manifest.version_id, article.path, chunk_set, tuple(article.tags)
            )
        return chunk_sets, rows


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadChunkUseCase:
    """Implements ``ports.driving.ReadChunk``."""

    versions: SearchableVersions
    manifests: ActiveManifests
    chunks: ChunkRepository
    renames: RenamedPaths | None = None

    async def __call__(self, query: ReadChunkQuery) -> ChunkOut:
        """Serve the chunk from its version's active manifest, or say why it cannot be served."""
        chunk_id = ChunkId(query.chunk_id)
        holders = await self.chunks.manifests_with_chunk(chunk_id)
        # The ID is a hash of the version it was issued for, so all holders share one version_id.
        # Anything else is not a state we understand: refuse rather than guess from the first row.
        if len({m.version_id for m in holders}) != 1:
            raise ChunkNotFoundError(query.chunk_id)
        first = holders[0]
        ref = first.version_id.removeprefix(f"{first.library}/")
        version = await self.versions.find(first.library, ref)
        ids = {m.manifest_id for m in holders}
        if version is not None and version.manifest_id in ids:
            stored = await self.chunks.get(version.manifest_id, chunk_id)
            if (
                stored is not None
                and stored.version_id == f"{version.library.lower()}/{version.version}"
            ):
                return ChunkOut.from_stored(version, stored)
        # Note: manifests the catalog already collected (E9-03) are unknown to it, so after
        # collection an old ID reports not_found, not stale, until tombstones keep them (E9-03).
        # Those must keep the old path, headings, occurrence and content hash too, or the new
        # location (E7-09) is lost with the manifest.
        statuses = await self.manifests.statuses(ids)
        superseded = [i for i, s in statuses.items() if s is ManifestStatus.SUPERSEDED]
        if superseded:
            # Any superseded holder gives the same old chunk (the ID hashes its content); the
            # smallest ID keeps the choice deterministic.
            moved = await self._moved(version, ChunkId(query.chunk_id), min(superseded))
            raise StaleChunkError(query.chunk_id, first.library, ref, moved)
        raise ChunkNotFoundError(query.chunk_id)  # only pending manifests hold it: not served yet

    async def _moved(
        self, version: SearchableVersion | None, chunk_id: ChunkId, old_manifest: str
    ) -> MovedSection | None:
        """Find the stale chunk's section in the active manifest: two reads, one rename lookup.

        The article is the old path, or where the rename map put it. The rename map covers one hop
        (the active manifest against the version before it), so an ID several re-syncs old whose
        article moved earlier gets no location. The section is then picked by ``_pick``.
        """
        old = await self.chunks.get(old_manifest, chunk_id)
        if version is None or old is None:
            return None
        path = old.row.article_path
        current = await self.chunks.article(version.manifest_id, path)
        if not current and self.renames is not None:
            target = DocTarget(library=version.library, version=version.version)
            # No rename known: keep the old path. Its article is empty, so the result is no
            # location rather than a guess.
            path = await self.renames.new_path(target, path) or path
            current = await self.chunks.article(version.manifest_id, path)
        if not current:
            return None  # the article is gone
        match = _pick(current, old.chunk, old.row.position)
        if match is None:
            return MovedSection(article_path=path)
        return MovedSection(
            article_path=path,
            chunk_id=match.chunk_id,
            heading_path=match.heading_path,
            anchor=match.anchor,
            text_changed=match.content_hash != old.chunk.content_hash,
        )


def _nearest(sections: Sequence[SectionRef], position: int) -> SectionRef | None:
    """Return the section nearest to ``position``; ``None`` when two are equally near."""
    ranked = sorted(sections, key=lambda s: abs(s.position - position))
    if len(ranked) > 1 and abs(ranked[0].position - position) == abs(ranked[1].position - position):
        return None
    return ranked[0] if ranked else None


def _pick(current: Sequence[SectionRef], was: Chunk, position: int) -> SectionRef | None:
    """Pick the section of ``current`` that ``was`` became, or ``None`` if unsure.

    In order: same headings and same text; same headings and occurrence (text edited); same text
    anywhere. Several equal candidates go to the nearest position, and a tie names no section:
    an ambiguous answer is better than a wrong ID. The occurrence alone is not trusted with the
    text unchecked, since an inserted duplicate heading shifts it onto another section.

    Known limit: if a duplicate heading is inserted above *and* the old section's text is
    edited too, the occurrence step lands on the inserted section. The match is then marked
    ``text_changed``, so the agent is told to re-check it.
    """
    same_headings = [s for s in current if s.heading_path == was.heading_path]
    same_text = [s for s in current if s.content_hash == was.content_hash]
    if both := [s for s in same_headings if s in same_text]:
        return _nearest(both, position)
    if edited := [s for s in same_headings if s.occurrence_index == was.occurrence_index]:
        return edited[0]
    return _nearest(same_text, position)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetChunkSetsUseCase:
    """Implements ``ports.driving.GetChunkSets``."""

    chunks: ChunkRepository

    async def __call__(self, query: GetChunkSetsQuery) -> ChunkSetsOut:
        """Look the sets up by (blob, config); sets that were never stored are left out."""
        found = await self.chunks.get_sets(
            [(sha, query.config_hash) for sha in dict.fromkeys(query.blob_shas)]
        )
        return ChunkSetsOut(
            chunks={
                sha: [
                    SetChunkOut(
                        heading_path=list(c.heading_path),
                        occurrence_index=c.occurrence_index,
                        content=c.content,
                        content_hash=c.content_hash,
                        anchor=c.anchor,
                        code_languages=list(c.code_languages),
                    )
                    for c in chunk_set.chunks
                ]
                for (sha, _), chunk_set in found.items()
            }
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscardPendingChunksUseCase:
    """Implements ``ports.driving.DiscardPendingChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository
    clock: Clock

    async def __call__(self, command: DiscardPendingChunksCommand) -> RemovedChunks:
        """Delete rows of matching manifests the catalog holds as pending, or dropped long ago."""
        now = self.clock.now()
        older = command.older_than_seconds
        candidates = await self.chunks.find_manifests(
            manifest_id=command.manifest_id,
            library=None if command.library is None else command.library.lower(),
            indexed_before=None if older is None else now - timedelta(seconds=older),
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=True)
        return RemovedChunks.from_model(await self.chunks.remove(doomed))


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectChunksUseCase:
    """Implements ``ports.driving.CollectChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository
    clock: Clock

    async def __call__(self, command: CollectChunksCommand) -> RemovedChunks:
        """Run after the catalog's collection: its superseded manifests are gone, so are ours."""
        now = self.clock.now()
        cutoff = now - timedelta(seconds=command.grace_seconds)
        candidates = await self.chunks.find_manifests(
            manifest_id=None, library=None, indexed_before=cutoff
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=False)
        return RemovedChunks.from_model(await self.chunks.remove(doomed))


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveChunksUseCase:
    """Implements ``ports.driving.RemoveChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository

    async def __call__(self, command: RemoveChunksCommand) -> RemovedChunks:
        """Remove what the catalog has forgotten; keep every manifest it still knows."""
        asked = list(dict.fromkeys(command.manifest_ids))
        known = await self.manifests.statuses(asked)
        return RemovedChunks.from_model(
            await self.chunks.remove([i for i in asked if i not in known])
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetagArticlesUseCase:
    """Implements ``ports.driving.RetagArticles``."""

    chunks: ChunkRepository

    async def __call__(self, command: RetagArticlesCommand) -> RetaggedChunks:
        """Overwrite the tag copies of the named articles' chunk rows."""
        tags = {a.path: tuple(dict.fromkeys(a.tags)) for a in command.articles}
        return RetaggedChunks(chunks=await self.chunks.set_tags(command.manifest_id, tags))


@dataclass(frozen=True, slots=True, kw_only=True)
class GetSearchIndexStateUseCase:
    """Implements ``ports.driving.GetSearchIndexState``."""

    maintenance: SearchIndexMaintenance

    async def __call__(self) -> SearchIndexStateOut:
        """Report the stored format against the current one."""
        return SearchIndexStateOut.from_model(await self.maintenance.state())


@dataclass(frozen=True, slots=True, kw_only=True)
class RebuildSearchIndexUseCase:
    """Implements ``ports.driving.RebuildSearchIndex``."""

    maintenance: SearchIndexMaintenance

    async def __call__(self) -> RebuiltIndexOut:
        """Build the new index beside the old one, then swap it in."""
        return RebuiltIndexOut.from_model(await self.maintenance.rebuild())


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveLibraryIdUseCase:
    """Implements ``ports.driving.ResolveLibraryId``."""

    libraries: Libraries
    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

    async def __call__(self, query: ResolveLibraryIdQuery) -> ResolveLibraryIdResult:
        """Match the name, then let the default versions' hits for ``query`` re-rank the matches."""
        # Both refuse blank text the same way (EmptySearchTextError).
        text, name = SearchText(value=query.query), SearchText(value=query.library_name)
        mode = RetrievalMode.BM25.value
        with self.tracer.span("resolve_library_id", mode=mode, query=text.value):
            return await self._resolve(text, name, mode)

    async def _resolve(
        self, text: SearchText, name: SearchText, mode: str
    ) -> ResolveLibraryIdResult:
        """Match the names, then rank them by their hits, one span per stage.

        Args:
            text: The validated query text.
            name: The validated library name.
            mode: The retrieval mode the hits are found in.

        Returns:
            The matching libraries, best first.
        """
        with self.tracer.span("resolve_library_id.versions", mode=mode):
            named = [
                (lib, found)
                for lib in await self.libraries.all()
                if (found := name_match(name.value, lib)) is not None
            ]
            # Pre-order by name only, so the cut keeps the best names; hits re-rank within it.
            named.sort(key=lambda m: (m[1], m[0].id))
            readable = await self._readable(named)
        with self.tracer.span("resolve_library_id.rank", mode=mode):
            hits = await asyncio.gather(
                *(
                    self.search.search(
                        version.manifest_id,
                        text.value,
                        TagFilter(tags=(), match=TagMatch.ANY),
                        QUERY_HITS_CAP,
                    )
                    for _, _, version in readable
                )
            )
        ranked = rank_matches(
            [
                Candidate(library=lib, match=found, hits=len(h))
                for (lib, found, _), h in zip(readable, hits, strict=True)
            ]
        )
        manifests = {lib.id: version.manifest_id for lib, _, version in readable}
        with self.tracer.span("resolve_library_id.chunks", mode=mode):
            counts = await asyncio.gather(
                *(self.chunks.counts(manifests[c.library.id]) for c in ranked)
            )
        return ResolveLibraryIdResult(
            matches=[
                LibraryMatchOut.from_candidate(c, n.articles, n.chunks)
                for c, n in zip(ranked, counts, strict=True)
            ]
        )

    async def _readable(
        self, named: Sequence[tuple[CatalogLibrary, NameMatch]]
    ) -> list[tuple[CatalogLibrary, NameMatch, SearchableVersion]]:
        """Take the best names that have a readable default version, ``MAX_RESOLVED`` at most.

        Libraries with nothing imported are dropped before the cut, so they cost no slot.
        """
        found: list[tuple[CatalogLibrary, NameMatch, SearchableVersion]] = []
        for start in range(0, len(named), MAX_RESOLVED):
            batch = named[start : start + MAX_RESOLVED]
            versions = await asyncio.gather(*(self.versions.find(lib.id, None) for lib, _ in batch))
            found += [(lib, m, v) for (lib, m), v in zip(batch, versions, strict=True) if v]
            if len(found) >= MAX_RESOLVED:
                break
        return found[:MAX_RESOLVED]


def _cost(section: DocSectionOut) -> int:
    """Characters a section takes in the payload: its parts plus the fixed framing."""
    pointer = len(POINTER_TEXT) if section.too_large else 0
    return (
        SECTION_FRAMING_CHARS
        + len(section.title)
        + len(section.source)
        + len(section.chunk_id)
        + len(section.content)
        + pointer
    )


def _pack(sections: Sequence[DocSectionOut], room: int) -> list[DocSectionOut]:
    """Take sections in order while they fit ``room``; a chunk that never could becomes a pointer.

    A chunk is never cut. One that merely finds the room used up is skipped, and a smaller one
    after it may still fit.
    """
    used, kept = 0, []
    for section in sections:
        shown = section if _cost(section) <= room else section.as_pointer()
        if used + _cost(shown) <= room:
            kept.append(shown)
            used += _cost(shown)
    return kept


def _fit_rules(rules: Sequence[str], room: int) -> list[str]:
    """Take the library's rules in order until one does not fit ``room``; they precede any chunk.

    The agent sees a prefix of what the authors wrote, never a later rule without an earlier one.
    """
    used, kept = RULES_FRAMING_CHARS, []
    for rule in rules:
        if used + RULE_FRAMING_CHARS + len(rule) > room:
            break
        kept.append(rule)
        used += RULE_FRAMING_CHARS + len(rule)
    return kept


@dataclass(frozen=True, slots=True, kw_only=True)
class QueryDocsUseCase:
    """Implements ``ports.driving.QueryDocs``."""

    versions: SearchableVersions
    modes: RetrievalModes
    """Picks the mode (the library's, else the instance's) and runs its pipeline."""
    chunks: ChunkRepository
    token_budget: int = DEFAULT_QUERY_DOCS_TOKEN_BUDGET
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

    async def __call__(self, query: QueryDocsQuery) -> QueryDocsResult:
        """Answer from exactly one version, with whole chunks that fit the budget, best first.

        The budget covers the whole payload: the notice, the sections and the closing line. A
        chunk that could never fit is listed as a pointer (no text, ``too_large``) so the agent
        can fetch it; one that merely found no room left is counted in ``omitted``. The
        library's rules (from its ``context7.json``) come first and are counted too; they take
        at most a ``RULES_SHARE``-th of the room: whole rules, a prefix of the list.
        """
        text = SearchText(value=query.query)
        # `/owner/repo` or `/owner/repo/<ref>`; a ref may itself contain slashes.
        _, owner, repo, *rest = query.library_id.split("/", 3)
        ref = rest[0] if rest else None
        library = f"/{owner}/{repo}"
        # context7's tool has no mode argument: the library's mode, else the instance's (C7-02).
        choice = await self.modes.choose(asked=None, library=library)
        with self.tracer.span(
            "query_docs", mode=choice.mode.value, query=text.value, library=library, ref=ref
        ):
            return await self._answer(query, text, library, ref, choice)

    async def _answer(
        self,
        query: QueryDocsQuery,
        text: SearchText,
        library: str,
        ref: str | None,
        choice: ModeChoice,
    ) -> QueryDocsResult:
        """Resolve the version, rank, load the chunks and pack them, one span per stage.

        Args:
            query: The request as asked.
            text: Its validated query text.
            library: The library ID it names.
            ref: The version it names; ``None`` for the default version.
            choice: The retrieval mode it runs in.

        Returns:
            The packed sections of the one version searched.
        """
        mode = choice.mode.value
        with self.tracer.span("query_docs.version", mode=mode):
            version = await self.versions.find(library, ref)
        if version is None:
            raise VersionNotIndexedError(library, ref or "(default version)")
        with self.tracer.span("query_docs.rank", mode=mode):
            answer = await self.modes.run(
                choice,
                version,
                text.value,
                TagFilter(tags=(), match=TagMatch.ANY),
                QUERY_DOCS_CANDIDATES,
            )
        with self.tracer.span("query_docs.chunks", mode=mode):
            stored = await self.chunks.get_many(
                version.manifest_id, [h.chunk_id for h in answer.hits]
            )
        sections = [
            DocSectionOut.from_stored(version, stored[hit.chunk_id])
            for hit in answer.hits
            if hit.chunk_id in stored
        ]
        if query.language:
            sections = language_first(sections, lambda s: s.code_languages, query.language)
        budget = self.token_budget * CHARS_PER_TOKEN
        room = budget - len(NOTICE) - FOOTER_CHARS
        rules = _fit_rules(version.rules, room // RULES_SHARE)
        if rules:
            room -= RULES_FRAMING_CHARS + sum(RULE_FRAMING_CHARS + len(r) for r in rules)
        kept = _pack(sections, room)
        return QueryDocsResult(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            retrieval_mode=answer.mode,
            reranked=answer.reranked > 0,
            fallback_reason=answer.fallback_reason,
            sections=kept,
            omitted=len(sections) - len(kept),
            budget_chars=budget,
            rules=rules,
        )


async def _library_retrieval(
    modes: RetrievalModes, library: str, mode: RetrievalMode | None
) -> LibraryRetrievalOut:
    """Describe a library's setting and what a search without ``mode`` would run in now.

    Args:
        modes: The instance's modes.
        library: The library's ID as the catalog spells it.
        mode: The library's setting.

    Returns:
        The setting, the effective mode and the modes on offer.
    """
    registry = await modes.registry()
    choice = registry.choose(asked=None, library=mode, instance=modes.instance_mode)
    return LibraryRetrievalOut(
        library=library,
        mode=mode,
        instance_mode=modes.instance_mode,
        effective_mode=choice.mode,
        fallback_reason=choice.fallback_reason,
        available_modes=list(registry.available()),
        configured_roles=[r for r in ModelRole if r in registry.roles],
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetLibraryRetrievalUseCase:
    """Implements ``ports.driving.GetLibraryRetrieval``."""

    libraries: Libraries
    """Spells the library ID as the catalog does."""
    modes: RetrievalModes
    """The instance's modes and the libraries' settings."""

    async def __call__(self, query: GetLibraryRetrievalQuery) -> LibraryRetrievalOut:
        """Read the library's mode and the one its searches use now.

        Args:
            query: The library.

        Returns:
            Its setting, the effective mode and the modes available.
        """
        library = await self.libraries.canonical_id(query.library)
        if library is None:
            raise UnknownLibraryError(query.library)
        mode = await self.modes.library_modes.mode_of(library)
        return await _library_retrieval(self.modes, library, mode)


@dataclass(frozen=True, slots=True, kw_only=True)
class SetLibraryRetrievalUseCase:
    """Implements ``ports.driving.SetLibraryRetrieval``."""

    libraries: Libraries
    """Spells the library ID as the catalog does."""
    modes: RetrievalModes
    """The instance's modes and the libraries' settings."""

    async def __call__(self, command: SetLibraryRetrievalCommand) -> LibraryRetrievalOut:
        """Validate the mode against what can run now, then store it (or clear it).

        Args:
            command: The library and its mode.

        Returns:
            The stored setting, the effective mode and the modes available.
        """
        library = await self.libraries.canonical_id(command.library)
        if library is None:
            raise UnknownLibraryError(command.library)
        mode = None
        if command.mode is not None:
            mode = (await self.modes.registry()).check(command.mode)
        await self.modes.library_modes.set_mode(library, mode)
        return await _library_retrieval(self.modes, library, mode)
