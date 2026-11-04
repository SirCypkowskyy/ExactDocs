"""Ingestion use cases. Each one satisfies a driving port structurally, without inheriting it."""

import asyncio
import codecs
import logging
import os
import stat
import time
import uuid
from collections.abc import Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddedVersion,
    AddLibraryCommand,
    AddVersionCommand,
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
    CheckoutUnreadableError,
    ImportNotPinnedError,
    ImportTooLargeError,
    JobNotFoundError,
    LibraryIdTakenError,
    NoArticlesError,
    UnknownJobKindError,
    VersionExistsError,
)
from exactdocs.ingestion.models import (
    DEFAULT_MAX_ARTICLE_BYTES,
    DEFAULT_MAX_IMPORT_BYTES,
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
    ProblemCode,
    ProposedId,
    ReadmeSummary,
    RefKind,
    RepositoryUrl,
    ResolvedRef,
    TagRule,
    article_tags,
    git_blob_sha,
    parse_article,
    readme_summary,
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
            ref_kind=command.ref_kind,
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


SAVE_EVERY_FILES = 100
SAVE_EVERY_SECONDS = 0.25


@dataclass(slots=True)
class _Progress:
    """Implements ``ports.driven.JobProgress``: keeps the latest job, stores it every so often.

    A job over thousands of files would otherwise rewrite its row (and its problem list) for
    each one. The first and the last report are always stored, and ``RunNextJob`` stores the end.
    """

    jobs: JobRepository
    job: Job
    saved_done: int = 0
    reported: bool = False
    saved_at: float = field(default_factory=time.monotonic)

    async def report(self, *, done: int, total: int) -> None:
        self.job = self.job.progressed(done=done, total=total)
        first, self.reported = not self.reported, True
        if first or done == total or done - self.saved_done >= SAVE_EVERY_FILES:
            await self._save()
        else:
            await self._save_if_due()

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        self.job = self.job.with_problem(path, code, reason)
        await self._save_if_due()

    async def _save_if_due(self) -> None:
        if time.monotonic() - self.saved_at >= SAVE_EVERY_SECONDS:
            await self._save()

    async def _save(self) -> None:
        self.saved_done, self.saved_at = self.job.done, time.monotonic()
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
            job = await _enqueue_import(self.enqueue_job, created, resolved)
        except BaseException:
            try:
                await self.libraries.discard(created)
            except Exception:
                log.exception(
                    "could not remove library %s after its import failed to queue", created
                )
            raise
        return AddedLibrary.of(created, resolved, job)


async def _enqueue_import(
    enqueue_job: EnqueueJob, library: str, resolved: ResolvedRef
) -> JobSummary:
    """Queue the import of a ref already pinned to its commit."""
    return await enqueue_job(
        EnqueueJobCommand(
            kind=IMPORT_JOB,
            library=library,
            version=resolved.name,
            commit_sha=resolved.commit_sha,
            ref_kind=resolved.kind,
        )
    )


@dataclass(frozen=True, slots=True)
class AddVersionUseCase:
    """Implements ``ports.driving.AddVersion``."""

    remote: GitRemote
    sources: LibrarySources
    enqueue_job: EnqueueJob

    async def __call__(self, command: AddVersionCommand) -> AddedVersion:
        """Pin the ref like ``AddLibrary`` does and queue the import with the library's settings.

        The import job reads the library's selection and tag rules when it runs, so the version
        is built exactly like the ones before it. A ref the library already has is refused, not
        re-imported (re-syncing is a different action).
        """
        library = command.library.lower()  # library IDs are stored lower-case
        source = await self.sources.get(library)
        resolved = resolve_ref(await self.remote.list_refs(source.url), command.ref)
        if resolved.name in source.imported_refs:
            raise VersionExistsError(library, resolved.name)
        job = await _enqueue_import(self.enqueue_job, library, resolved)
        return AddedVersion.of(library, resolved, job)


@dataclass(frozen=True, slots=True)
class ImportVersionUseCase:
    """Implements ``ports.driven.JobHandler`` for ``IMPORT_JOB``: a whole version or nothing.

    Fetch the pinned commit, read and parse every selected file, chunk the blobs no earlier
    import chunked, store everything as a pending manifest, index its chunks, then activate it.
    Readers see the previous state until the last step; any failure (also a cancellation)
    discards what was stored, so a version never shows half of its articles.

    Memory: the selected text of the version is held in memory until it is stored, and again as
    chunks, as DTOs in the bridges and as SQL parameters, so a job needs several times
    ``max_import_bytes`` at its peak (and the worker runs two jobs at once). The budget makes the
    import fail with a clear error instead of the process being killed. Batched storing (the
    catalog would need an "append to a pending manifest" step) would lift the limit.
    """

    gateway: GitGateway
    chunker: Chunker
    sources: LibrarySources
    versions: VersionPublisher
    index: ChunkIndex
    max_article_bytes: int = DEFAULT_MAX_ARTICLE_BYTES
    max_import_bytes: int = DEFAULT_MAX_IMPORT_BYTES

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the import from the beginning; raising fails the job."""
        if job.version is None or job.commit_sha is None:
            raise ImportNotPinnedError
        source = await self.sources.get(job.library)
        # A job queued without a kind is imported as a bare commit: the SHA is what is fetched.
        kind = job.ref_kind or RefKind.COMMIT
        full_ref = {RefKind.TAG: "refs/tags/", RefKind.BRANCH: "refs/heads/"}.get(kind)
        refs = [] if full_ref is None else [full_ref + job.version]
        config_hash = self.chunker.config_hash
        async with self.gateway.fetch(
            source.url, job.commit_sha, source.selection, refs=refs
        ) as folder:
            articles = await self._articles(folder, source, config_hash, progress)
            readme = await asyncio.to_thread(_readme, folder, self.max_article_bytes)
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
            # Run as a task of its own and shielded, so that the cancellation that got us here
            # cannot cut the clean-up short. A failing clean-up is logged, never hides the cause.
            cleanup = asyncio.ensure_future(self._discard(job.library, manifest_id))
            _cleanups.add(cleanup)
            cleanup.add_done_callback(_cleanups.discard)
            await asyncio.shield(cleanup)
            raise
        # The version is live now: a catalog that cannot take the README's text must not fail it.
        try:
            await self.versions.describe(
                library=job.library,
                ref=job.version,
                title=readme.title,
                description=readme.description,
            )
        except Exception:
            log.exception("could not apply the README of %s %s", job.library, job.version)

    async def _articles(
        self, folder: Path, source: ImportSource, config_hash: str, progress: JobProgress
    ) -> list[ImportedArticle]:
        try:
            paths = await asyncio.to_thread(_selected_files, folder, source.selection)
        except OSError as error:
            raise CheckoutUnreadableError from error
        await progress.report(done=0, total=len(paths))
        loaded: list[tuple[str, str, ParsedArticle]] = []
        used = 0
        for done, path in enumerate(paths, 1):
            result = await asyncio.to_thread(_load, folder, path, self.max_article_bytes)
            shown = path.encode(errors="replace").decode()
            if isinstance(result, Skip):
                await progress.problem(shown, result.code, result.reason)
            else:
                blob_sha, parsed, size = result
                used += size
                if used > self.max_import_bytes:
                    raise ImportTooLargeError(self.max_import_bytes)
                loaded.append((path, blob_sha, parsed))
                for problem in parsed.problems:  # the article is imported; the note is listed
                    await progress.problem(shown, ProblemCode.FRONT_MATTER, problem)
            await progress.report(done=done, total=len(paths))
        blobs = list(dict.fromkeys(blob_sha for _, blob_sha, _ in loaded))
        chunks: dict[str, tuple[ArticleChunk, ...]] = {}
        for start in range(0, len(blobs), KNOWN_BATCH):
            chunks |= await self.index.known(config_hash, blobs[start : start + KNOWN_BATCH])
        unknown: dict[str, ParsedArticle] = {}
        for _, blob_sha, parsed in loaded:
            if blob_sha not in chunks:
                unknown.setdefault(blob_sha, parsed)
        chunks |= await asyncio.to_thread(self._cut, unknown)
        return [
            ImportedArticle(
                path=path,
                blob_sha=blob_sha,
                title=parsed.title,
                tags=article_tags(path, parsed.tags, source.tag_rules),
                front_matter=parsed.front_matter,
                content=parsed.body,
                chunks=chunks[blob_sha],
            )
            for path, blob_sha, parsed in loaded
        ]

    def _cut(self, articles: Mapping[str, ParsedArticle]) -> dict[str, tuple[ArticleChunk, ...]]:
        return {sha: tuple(self.chunker.chunk(a)) for sha, a in articles.items()}

    async def _discard(self, library: str, manifest_id: str | None) -> None:
        try:
            await _discard_pending(self.versions, self.index, library, manifest_id)
        except Exception:
            log.exception("could not discard the pending import of %s", library)


KNOWN_BATCH = 500
_cleanups: set[asyncio.Future[None]] = set()  # the loop holds tasks weakly


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
    """Delete the pending chunks, then the pending manifests (the order matters, see the port).

    Both are attempted whatever happens to the first; the first error is raised afterwards.
    """
    errors: list[Exception] = []
    for discard in (index.discard, versions.discard):
        try:
            await discard(manifest_id=manifest_id, library=library)
        except Exception as error:
            log.exception("discarding pending data of %s failed", library)
            errors.append(error)
    if errors:
        raise errors[0]


def _selected_files(folder: Path, selection: PathSelection) -> list[str]:
    """List the checked-out files the library takes, repository-relative, sorted.

    A folder that cannot be listed raises, so that a version is never published without it.
    """

    def fail(error: OSError) -> None:
        raise error

    found = []
    # symlinked folders are listed in `dirs`, not entered
    for root, dirs, files in os.walk(folder, onerror=fail):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = (Path(root) / name).relative_to(folder).as_posix()
            if selection.selects(path):
                found.append(path)
    return sorted(found)


def _readme(folder: Path, limit: int) -> ReadmeSummary:
    """Summarize the root README (``README.md``, else ``README.mdx``); nothing if there is none.

    It is read whatever the path selection says (the git gateway always fetches it) and is as
    untrusted as any article. A README that is a symlink, not a plain file, too big or not
    UTF-8 counts as absent (the first of the two names that exists decides). This never raises:
    the summary is a nicety and must not fail an import whose articles are fine.
    """
    for name in ("README.md", "README.mdx"):
        try:
            data = _read(folder / name, limit)
            return ReadmeSummary() if isinstance(data, Skip) else readme_summary(data.decode())
        except FileNotFoundError:
            continue
        except Exception:
            log.exception("could not summarize the README of a checkout")
            return ReadmeSummary()
    return ReadmeSummary()


@dataclass(frozen=True, slots=True)
class Skip:
    """Why a file is left out of the version (never echoes its content)."""

    code: ProblemCode
    reason: str


def _load(folder: Path, path: str, limit: int) -> tuple[str, ParsedArticle, int] | Skip:
    """Read, decode and parse one file, or say why it is skipped.

    Returns the blob SHA, the article and the byte size. A file over ``limit`` bytes is not read
    at all. Anything that is not a plain file (a symlink could point outside the checkout) or not
    readable is skipped, as is text that no supported encoding decodes.
    The blob SHA is hashed from the checked-out bytes, which equals git's because the
    ``GitGateway`` must check files out verbatim (no eol or filter conversion).
    Chunk sets are reused by blob SHA, so changing ``_decode`` leaves already-imported blobs
    with their old text until they change; a UTF-8 BOM is stripped now (``utf-8-sig``), so
    blobs imported before that may still carry U+FEFF in their chunks.
    """
    try:
        path.encode()
    except UnicodeEncodeError:
        return Skip(ProblemCode.BAD_FILE_NAME, "file name is not valid UTF-8")
    try:
        data = _read(folder / path, limit)
    except OSError:
        return Skip(ProblemCode.UNREADABLE, "unreadable")
    if isinstance(data, Skip):
        return data
    text = _decode(data)
    if isinstance(text, Skip):
        return text
    return git_blob_sha(data), parse_article(path, text), len(data)


# FF FE 00 00 is also a UTF-16-LE file starting with U+0000; UTF-32 is tried first, and a file
# that then fails to decode is reported undecodable, which is right for such a file anyway.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
MAX_CONTROL_RATIO = 0.02


def _decode(data: bytes) -> str | Skip:
    """UTF-8, else UTF-16/32 announced by a BOM, else Windows-1252; NUL bytes mean binary.

    Windows-1252 stands in for Latin-1 (it is a superset where text lives); bytes it leaves
    undefined, or more than 2% control characters, make the file undecodable. Not detected:
    UTF-16/32 without a BOM (reported as binary, or imported as mojibake when it has no NULs),
    and other legacy charsets (CJK, Cyrillic) that happen to pass as Windows-1252. A real
    charset detector is not worth a dependency.
    """
    for bom, codec in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(codec)
            except UnicodeDecodeError:
                return Skip(ProblemCode.UNDECODABLE, _NOT_TEXT)
    if b"\0" in data:
        return Skip(ProblemCode.BINARY, "binary file")
    with suppress(UnicodeDecodeError):
        return data.decode("utf-8-sig")
    with suppress(UnicodeDecodeError):
        text = data.decode("cp1252")
        controls = sum(c < " " and c not in "\t\n\r\f" for c in text)
        if controls <= len(text) * MAX_CONTROL_RATIO:
            return text
    return Skip(ProblemCode.UNDECODABLE, _NOT_TEXT)


_NOT_TEXT = "not text in any supported encoding"


def _read(file: Path, limit: int) -> bytes | Skip:
    """Return the bytes of a plain file of up to ``limit`` bytes, else why it is skipped."""
    too_big = Skip(ProblemCode.TOO_LARGE, f"larger than {limit} bytes")
    not_a_file = Skip(ProblemCode.NOT_A_FILE, "not a regular file")
    info = file.lstat()
    if not stat.S_ISREG(info.st_mode):
        return not_a_file
    if info.st_size > limit:
        return too_big
    with _open_plain(file) as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):  # swapped since lstat
            return not_a_file
        data = handle.read(limit + 1)
    return data if len(data) <= limit else too_big


@contextmanager
def _open_plain(file: Path) -> Generator[BinaryIO]:
    """Open for reading without following a symlink; the descriptor is always closed.

    Yields:
        The binary file object.

    """
    fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        handle = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        yield handle
