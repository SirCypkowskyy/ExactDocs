"""Ingestion use cases. Each one satisfies a driving port structurally, without inheriting it."""

import asyncio
import logging
import os
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddLibraryCommand,
    CheckedRepository,
    CheckRepositoryCommand,
    EnqueueJobCommand,
    GetJobQuery,
    JobList,
    JobSummary,
    LatestJob,
    LatestJobs,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    RefOut,
    RepositoryRefs,
)
from exactdocs.ingestion.errors import (
    ImportNotPinnedError,
    JobNotFoundError,
    LibraryIdTakenError,
    NoArticlesError,
    UnknownJobKindError,
    UnknownRefError,
)
from exactdocs.ingestion.models import (
    DEFAULT_MAX_ARTICLE_BYTES,
    IMPORT_JOB,
    ArticleChunk,
    ImportedArticle,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    JobKind,
    NewLibrary,
    ParsedArticle,
    PathSelection,
    ProposedId,
    RefKind,
    RepositoryUrl,
    TagRule,
    article_tags,
    git_blob_sha,
    parse_article,
    ref_tips,
    resolve_ref,
)
from exactdocs.ingestion.ports.driven import (
    Chunker,
    ChunkIndex,
    GitGateway,
    GitRemote,
    JobHandler,
    JobProgress,
    JobRepository,
    LibraryIds,
    LibrarySources,
    NewLibraries,
    RecoveryHook,
    VersionPublisher,
)
from exactdocs.ingestion.ports.driving import EnqueueJob
from exactdocs_kernel import Clock, DomainError, paginate

log = logging.getLogger(__name__)

MAX_LISTED_REFS = 1000
"""Branches and tags listed each; a repository with more is cut and flagged ``truncated``."""


@dataclass(frozen=True, slots=True)
class EnqueueJobUseCase:
    """Implements ``ports.driving.EnqueueJob``."""

    jobs: JobRepository
    clock: Clock
    handlers: Mapping[JobKind, JobHandler]

    async def __call__(self, command: EnqueueJobCommand) -> JobSummary:
        """Queue the job; the worker picks it up."""
        kind = JobKind(command.kind)
        if kind not in self.handlers:
            raise UnknownJobKindError(kind)
        job = Job.queued(
            job_id=JobId(str(uuid.uuid7())),  # time-ordered, so IDs sort like creation time
            kind=kind,
            library=command.library,
            version=command.version,
            commit_sha=command.commit_sha,
            now=self.clock.now(),
        )
        await self.jobs.add(job)
        return JobSummary.from_model(job)


@dataclass(frozen=True, slots=True)
class GetJobUseCase:
    """Implements ``ports.driving.GetJob``."""

    jobs: JobRepository

    async def __call__(self, query: GetJobQuery) -> JobSummary:
        """Fetch one job by its ID."""
        job = await self.jobs.get(JobId(query.job_id))
        if job is None:
            raise JobNotFoundError(query.job_id)
        return JobSummary.from_model(job)


@dataclass(frozen=True, slots=True)
class ListLibraryJobsUseCase:
    """Implements ``ports.driving.ListLibraryJobs``."""

    jobs: JobRepository

    async def __call__(self, query: ListLibraryJobsQuery) -> JobList:
        """List a page of the library's jobs, newest first."""
        # ponytail: loads all of the library's jobs, then pages in memory; a keyset query in
        # the repository once a library has thousands of jobs.
        jobs = await self.jobs.list_for_library(query.library)
        page = paginate(
            jobs, key=lambda job: job.id, limit=query.limit, cursor=query.cursor, descending=True
        )
        return JobList.from_page(page)


@dataclass(frozen=True, slots=True)
class ListLatestJobsUseCase:
    """Implements ``ports.driving.ListLatestJobs``."""

    jobs: JobRepository

    async def __call__(self) -> LatestJobs:
        """List the newest job of every (library, version), without their skipped files."""
        # ponytail: not paged; one row per imported version, fine until thousands exist.
        return LatestJobs(jobs=[LatestJob.from_model(job) for job in await self.jobs.list_latest()])


@dataclass(frozen=True, slots=True)
class RecoverJobsUseCase:
    """Implements ``ports.driving.RecoverJobs``."""

    jobs: JobRepository
    clock: Clock
    hooks: Mapping[JobKind, RecoveryHook]

    async def __call__(self) -> None:
        """Run the hook of every job left ``running``, then queue it again to run from scratch.

        A kind without a hook has nothing to clean up. A hook that raises fails its job instead
        of keeping the app from starting, because re-running over unclean state would be worse.
        """
        # ponytail: assumes one live process runs jobs on the database (the HTTP server; stdio
        # does not). Several would re-queue each other's running jobs: add a lease/heartbeat
        # column and re-queue only expired leases if that ever changes.
        for job in await self.jobs.list_running():
            hook = self.hooks.get(job.kind)
            try:
                if hook is not None:
                    await hook(job)
            except Exception as error:
                log.exception("recovery of job %s (%s) failed", job.id, job.kind)
                await self.jobs.save(
                    job.failed(f"recovery failed: {_describe(error)}", self.clock.now())
                )
            else:
                await self.jobs.save(job.requeued())


@dataclass(frozen=True, slots=True)
class RunNextJobUseCase:
    """Implements ``ports.driving.RunNextJob``."""

    jobs: JobRepository
    clock: Clock
    handlers: Mapping[JobKind, JobHandler]

    async def __call__(self) -> bool:
        """Claim the next job that may run, run it, and record how it ended."""
        job = await self.jobs.claim_next(self.clock.now())
        if job is None:
            return False
        progress = _Progress(self.jobs, job)
        handler = self.handlers.get(job.kind)
        try:
            if handler is None:
                failure = f"no handler is registered for job kind {job.kind!r}"
            else:
                await handler(job, progress)
                failure = None
        except Exception as error:
            log.exception("job %s (%s) failed", job.id, job.kind)
            failure = _describe(error)
        now = self.clock.now()
        final = (
            progress.job.succeeded(now) if failure is None else progress.job.failed(failure, now)
        )
        try:
            await self.jobs.save(final)
        except Exception:
            log.exception("could not store the end of job %s (%s)", job.id, job.kind)
            raise
        return True


@dataclass(slots=True)
class _Progress:
    """Implements ``ports.driven.JobProgress``: keeps the latest job and stores every change."""

    jobs: JobRepository
    job: Job

    async def report(self, *, done: int, total: int) -> None:
        self.job = self.job.progressed(done=done, total=total)
        await self.jobs.save(self.job)

    async def problem(self, path: str, reason: str) -> None:
        self.job = self.job.with_problem(path, reason)
        await self.jobs.save(self.job)


def _describe(error: Exception) -> str:
    """Return the text users see: a domain error says what is wrong, else only its type."""
    return str(error) if isinstance(error, DomainError) else f"unexpected {type(error).__name__}"


@dataclass(frozen=True, slots=True)
class CheckRepositoryUseCase:
    """Implements ``ports.driving.CheckRepository``."""

    remote: GitRemote
    library_ids: LibraryIds

    async def __call__(self, command: CheckRepositoryCommand) -> CheckedRepository:
        """Parse the URL, refuse a taken ID, then ask the remote for its default branch."""
        repository = RepositoryUrl.parse(command.url)
        if await self.library_ids.is_taken(repository.library_id):
            raise LibraryIdTakenError(repository.library_id)
        refs = await self.remote.list_refs(repository, "HEAD")
        return CheckedRepository(
            host=repository.host_kind,
            library_id=repository.library_id,
            default_branch=refs.default_branch,
        )


@dataclass(frozen=True, slots=True)
class ListRepositoryRefsUseCase:
    """Implements ``ports.driving.ListRepositoryRefs``."""

    remote: GitRemote

    async def __call__(self, query: ListRepositoryRefsQuery) -> RepositoryRefs:
        """Parse the URL and list what the remote advertises, at most ``MAX_LISTED_REFS`` each."""
        refs = await self.remote.list_refs(RepositoryUrl.parse(query.url))
        tips = ref_tips(refs)
        branches = [
            RefOut(name=t.name, commit_sha=t.commit_sha) for t in tips if t.kind is RefKind.BRANCH
        ]
        tags = [RefOut(name=t.name, commit_sha=t.commit_sha) for t in tips if t.kind is RefKind.TAG]
        return RepositoryRefs(
            default_branch=refs.default_branch,
            branches=branches[:MAX_LISTED_REFS],
            tags=tags[:MAX_LISTED_REFS],
            truncated=max(len(branches), len(tags)) > MAX_LISTED_REFS,
        )


@dataclass(frozen=True, slots=True)
class AddLibraryUseCase:
    """Implements ``ports.driving.AddLibrary``."""

    remote: GitRemote
    library_ids: LibraryIds
    libraries: NewLibraries
    enqueue_job: EnqueueJob

    async def __call__(self, command: AddLibraryCommand) -> AddedLibrary:
        """Check everything that can be checked first, then store the library and queue its import.

        If queueing fails, the new library is removed again, so a retry is not met with a 409.
        """
        repository = RepositoryUrl.parse(command.url)
        selection = PathSelection.of(command.include_paths, command.exclude_paths)
        tag_rules = TagRule.many([(r.pattern, r.tag) for r in command.tag_rules])
        library_id = ProposedId(command.library_id or repository.library_id)
        if await self.library_ids.is_taken(library_id):
            raise LibraryIdTakenError(library_id)
        refs = await self.remote.list_refs(repository)
        resolved = resolve_ref(refs, command.ref)
        created = await self.libraries.add(
            NewLibrary(
                library_id=library_id,
                title=library_id.rsplit("/", 1)[-1],
                source_url=repository.url,
                host=repository.host_kind,
                default_branch=refs.default_branch,
                selection=selection,
                tag_rules=tag_rules,
            )
        )
        try:
            job = await self.enqueue_job(
                EnqueueJobCommand(
                    kind=IMPORT_JOB,
                    library=created,
                    version=resolved.name,
                    commit_sha=resolved.commit_sha,
                )
            )
        except BaseException:
            try:
                await self.libraries.discard(created)
            except Exception:
                log.exception(
                    "could not remove library %s after its import failed to queue", created
                )
            raise
        return AddedLibrary.of(created, resolved, job)


@dataclass(frozen=True, slots=True)
class ImportVersionUseCase:
    """Implements ``ports.driven.JobHandler`` for ``IMPORT_JOB``: a whole version or nothing.

    Fetch the pinned commit, read and parse every selected file, chunk the blobs no earlier
    import chunked, store everything as a pending manifest, index its chunks, then activate it.
    Readers see the previous state until the last step; any failure (also a cancellation)
    discards what was stored, so a version never shows half of its articles.
    """

    gateway: GitGateway
    remote: GitRemote
    chunker: Chunker
    sources: LibrarySources
    versions: VersionPublisher
    index: ChunkIndex
    max_article_bytes: int = DEFAULT_MAX_ARTICLE_BYTES

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the import from the beginning; raising fails the job."""
        if job.version is None or job.commit_sha is None:
            raise ImportNotPinnedError
        source = await self.sources.get(job.library)
        kind = await self._kind(source.url, job.version, job.commit_sha)
        full_ref = {RefKind.TAG: "refs/tags/", RefKind.BRANCH: "refs/heads/"}.get(kind)
        refs = [] if full_ref is None else [full_ref + job.version]
        config_hash = self.chunker.config_hash
        async with self.gateway.fetch(
            source.url, job.commit_sha, source.selection, refs=refs
        ) as folder:
            articles = await self._articles(folder, source, config_hash, progress)
        if not articles:
            raise NoArticlesError
        version = ImportedVersion(
            library=job.library,
            ref=job.version,
            kind=kind,
            commit_sha=job.commit_sha,
            config_hash=config_hash,
            articles=tuple(articles),
        )
        manifest_id: str | None = None
        try:
            manifest_id = await self.versions.store(version)
            await self.index.index(manifest_id, version)
            await self.versions.activate(manifest_id)
        except BaseException:
            # Shielded, so that the cancellation that got us here cannot cut the clean-up short.
            await asyncio.shield(self._discard(job.library, manifest_id))
            raise

    async def _kind(self, url: RepositoryUrl, version: str, commit_sha: str) -> RefKind:
        """Tell what ``version`` is: AddLibrary pins a bare commit by its full SHA."""
        if version == commit_sha:
            return RefKind.COMMIT
        named = {t.kind: t for t in ref_tips(await self.remote.list_refs(url)) if t.name == version}
        found = named.get(RefKind.TAG) or named.get(RefKind.BRANCH)
        if found is None:
            raise UnknownRefError(version)
        return found.kind

    async def _articles(
        self, folder: Path, source: ImportSource, config_hash: str, progress: JobProgress
    ) -> list[ImportedArticle]:
        paths = await asyncio.to_thread(_selected_files, folder, source.selection)
        await progress.report(done=0, total=len(paths))
        # ponytail: every article of the version is held in memory until it is stored; the fetch
        # caps bound it. Store in batches (the catalog needs a "append to pending" step) if needed.
        chunks: dict[str, tuple[ArticleChunk, ...]] = {}  # by blob: one blob, one chunk set
        articles = []
        for done, path in enumerate(paths, 1):
            loaded = await asyncio.to_thread(_load, folder, path, self.max_article_bytes)
            if isinstance(loaded, str):  # why the file was skipped; E3-05b grades these
                await progress.problem(path, loaded)
            else:
                blob_sha, parsed = loaded
                if blob_sha not in chunks:
                    chunks |= await self.index.known(config_hash, [blob_sha])
                if blob_sha not in chunks:
                    chunks[blob_sha] = tuple(await asyncio.to_thread(self.chunker.chunk, parsed))
                articles.append(
                    ImportedArticle(
                        path=path,
                        blob_sha=blob_sha,
                        title=parsed.title,
                        tags=article_tags(path, parsed.tags, source.tag_rules),
                        front_matter=parsed.front_matter,
                        content=parsed.body,
                        chunks=chunks[blob_sha],
                    )
                )
            await progress.report(done=done, total=len(paths))
        return articles

    async def _discard(self, library: str, manifest_id: str | None) -> None:
        try:
            await _discard_pending(self.versions, self.index, library, manifest_id)
        except Exception:
            log.exception("could not discard the pending import of %s", library)


@dataclass(frozen=True, slots=True)
class DiscardInterruptedImportUseCase:
    """Implements ``ports.driven.RecoveryHook`` for ``IMPORT_JOB``."""

    versions: VersionPublisher
    index: ChunkIndex

    async def __call__(self, job: Job, /) -> None:
        """Drop what the interrupted run stored; a library has one running import at a time."""
        await _discard_pending(self.versions, self.index, job.library, None)


async def _discard_pending(
    versions: VersionPublisher, index: ChunkIndex, library: str, manifest_id: str | None
) -> None:
    """Delete the pending chunks, then the pending manifests (the order matters, see the port)."""
    await index.discard(manifest_id=manifest_id, library=library)
    await versions.discard(manifest_id=manifest_id, library=library)


def _selected_files(folder: Path, selection: PathSelection) -> list[str]:
    """List the checked-out files the library takes, repository-relative, sorted."""
    found = []
    for root, dirs, files in os.walk(folder):  # symlinked folders are listed in `dirs`, not entered
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = (Path(root) / name).relative_to(folder).as_posix()
            if selection.selects(path):
                found.append(path)
    return sorted(found)


def _load(folder: Path, path: str, limit: int) -> tuple[str, ParsedArticle] | str:
    """Read and parse one file, or say why it is skipped (never echoing its content).

    A file over ``limit`` bytes is not read at all. Anything that is not a plain file (a symlink
    could point outside the checkout) or not UTF-8 is skipped; decoding other charsets is E3-05b.
    ponytail: the blob SHA is hashed from the checked-out bytes, which equals git's unless the
    repository's attributes convert line endings; it is only ever a content key.
    """
    file = folder / path
    info = file.lstat()
    if not stat.S_ISREG(info.st_mode):
        return "not a regular file"
    if info.st_size > limit:
        return f"larger than {limit} bytes"
    with os.fdopen(os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        return f"larger than {limit} bytes"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "not valid UTF-8"
    return git_blob_sha(data), parse_article(path, text)
