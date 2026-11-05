import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from exactdocs.retrieval.dtos import (
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
    CoverageOut,
    DiscardPendingChunksCommand,
    DocSectionOut,
    GetChunkSetsQuery,
    IndexedManifestOut,
    IndexManifestCommand,
    LibraryFacetOut,
    LibraryMatchOut,
    LibrarySearchResultOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
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
    SearchResultOut,
    SetChunkOut,
)
from exactdocs.retrieval.errors import (
    ChunkNotFoundError,
    MovedSection,
    StaleChunkError,
    UnavailableModeError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    CHARS_PER_TOKEN,
    FOOTER_CHARS,
    POINTER_TEXT,
    SECTION_FRAMING_CHARS,
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
    NameMatch,
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
    RenamedPaths,
    SearchableVersions,
    SearchIndex,
)
from exactdocs_kernel import NOTICE, Clock

# A manifest the catalog does not know may just not have been stored there yet (the order is
# Store -> Index -> Activate, but the calls are not one transaction), so it is removed only once
# it is this old.
UNKNOWN_MANIFEST_GRACE = timedelta(minutes=5)


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


@dataclass(frozen=True, slots=True)
class SearchDocsUseCase:
    """Implements ``ports.driving.SearchDocs``."""

    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
        """Search the active manifest of one exact version; never fall back to another version."""
        # Built only to refuse a whitespace-only query (EmptySearchTextError).
        text = SearchText(value=query.query)
        # E11: replace with the modes this instance has configured.
        available = [m.value for m in RetrievalMode]
        if query.mode is not None and query.mode.strip().lower() not in available:
            raise UnavailableModeError(query.mode, available)
        version = await self.versions.find(query.library, query.ref)
        if version is None:
            raise VersionNotIndexedError(query.library, query.ref or "(default version)")
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        # One more than asked for tells whether the answer was cut short.
        found = await self.search.search(
            version.manifest_id, text.value, tag_filter, query.limit + 1
        )
        shown = found[: query.limit]
        stored = await self.chunks.get_many(version.manifest_id, [h.chunk_id for h in shown])
        # A chunk gone since the search (the manifest was collected) leaves no result, and is not
        # counted as a candidate either, so results and coverage stay consistent.
        results = [
            SearchResultOut.from_models(version, stored[hit.chunk_id], hit)
            for hit in shown
            if hit.chunk_id in stored
        ]
        vanished = len(shown) - len(results)
        return SearchDocsResult(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            retrieval_mode=RetrievalMode.BM25,
            reranked=False,
            coverage=CoverageOut(
                candidates=len(found) - vanished, reranked=0, complete=len(found) <= query.limit
            ),
            results=results,
        )


# Libraries searched at once: bounds the size of the one FTS query.
MAX_SEARCHED_LIBRARIES = 500


@dataclass(frozen=True, slots=True)
class SearchAllLibrariesUseCase:
    """Implements ``ports.driving.SearchAllLibraries``."""

    defaults: DefaultVersions
    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository

    async def __call__(self, query: SearchAllQuery) -> SearchAllResult:
        """Rank the chunks of all default versions together; count the matches per library.

        There is no ``mode`` (BM25 only until E11), unlike ``search_docs``. With ``library`` set
        every library is still resolved: the counts stay global, which a facet needs.
        """
        text = SearchText(value=query.query)
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        every = await self.defaults.all()
        searched = {v.manifest_id: v for v in every[:MAX_SEARCHED_LIBRARIES]}
        omitted = len(every) - len(searched)
        scope = searched
        if query.library is not None:
            only = await self.versions.find(query.library, None)
            if only is None:
                raise VersionNotIndexedError(query.library, "(default version)")
            if only.manifest_id not in searched:  # beyond the cap: searched, so no longer omitted
                searched[only.manifest_id] = only
                omitted -= 1
            scope = {only.manifest_id: only}
        # One more than asked for tells whether the answer was cut short.
        found_hits, counts = await asyncio.gather(
            self.search.search_many(list(scope), text.value, tag_filter, query.limit + 1),
            self.search.count_many(list(searched), text.value, tag_filter),
        )
        shown = found_hits[: query.limit]
        wanted: dict[str, list[ChunkId]] = {}
        for found_hit in shown:
            wanted.setdefault(found_hit.manifest_id, []).append(found_hit.hit.chunk_id)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class RetagArticlesUseCase:
    """Implements ``ports.driving.RetagArticles``."""

    chunks: ChunkRepository

    async def __call__(self, command: RetagArticlesCommand) -> RetaggedChunks:
        """Overwrite the tag copies of the named articles' chunk rows."""
        tags = {a.path: tuple(dict.fromkeys(a.tags)) for a in command.articles}
        return RetaggedChunks(chunks=await self.chunks.set_tags(command.manifest_id, tags))


# Only the best name matches are looked at: each costs a search. Results are capped to the same.
MAX_RESOLVED = 10
# How many matching chunks count as "documents it"; enough to tell libraries apart, cheap to get.
QUERY_HITS_CAP = 5


@dataclass(frozen=True, slots=True)
class ResolveLibraryIdUseCase:
    """Implements ``ports.driving.ResolveLibraryId``."""

    libraries: Libraries
    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository

    async def __call__(self, query: ResolveLibraryIdQuery) -> ResolveLibraryIdResult:
        """Match the name, then let the default versions' hits for ``query`` re-rank the matches."""
        # Both refuse blank text the same way (EmptySearchTextError).
        text, name = SearchText(value=query.query), SearchText(value=query.library_name)
        named = [
            (lib, found)
            for lib in await self.libraries.all()
            if (found := name_match(name.value, lib)) is not None
        ]
        # Pre-order by name only, so the cut keeps the best names; hits re-rank within it.
        named.sort(key=lambda m: (m[1], m[0].id))
        readable = await self._readable(named)
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


# Matching chunks looked at per call; the budget decides how many of them are returned.
QUERY_DOCS_CANDIDATES = 50
DEFAULT_QUERY_DOCS_TOKEN_BUDGET = 10_000


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


@dataclass(frozen=True, slots=True)
class QueryDocsUseCase:
    """Implements ``ports.driving.QueryDocs``."""

    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository
    token_budget: int = DEFAULT_QUERY_DOCS_TOKEN_BUDGET

    async def __call__(self, query: QueryDocsQuery) -> QueryDocsResult:
        """Answer from exactly one version, with whole chunks that fit the budget, best first.

        The budget covers the whole payload: the notice, the sections and the closing line. A
        chunk that could never fit is listed as a pointer (no text, ``too_large``) so the agent
        can fetch it; one that merely found no room left is counted in ``omitted``.
        """
        text = SearchText(value=query.query)
        # `/owner/repo` or `/owner/repo/<ref>`; a ref may itself contain slashes.
        _, owner, repo, *rest = query.library_id.split("/", 3)
        ref = rest[0] if rest else None
        library = f"/{owner}/{repo}"
        version = await self.versions.find(library, ref)
        if version is None:
            raise VersionNotIndexedError(library, ref or "(default version)")
        found = await self.search.search(
            version.manifest_id,
            text.value,
            TagFilter(tags=(), match=TagMatch.ANY),
            QUERY_DOCS_CANDIDATES,
        )
        stored = await self.chunks.get_many(version.manifest_id, [h.chunk_id for h in found])
        sections = [
            DocSectionOut.from_stored(version, stored[hit.chunk_id])
            for hit in found
            if hit.chunk_id in stored
        ]
        if query.language:
            sections = language_first(sections, lambda s: s.code_languages, query.language)
        budget = self.token_budget * CHARS_PER_TOKEN
        kept = _pack(sections, budget - len(NOTICE) - FOOTER_CHARS)
        return QueryDocsResult(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            retrieval_mode=RetrievalMode.BM25,
            sections=kept,
            omitted=len(sections) - len(kept),
            budget_chars=budget,
        )
