"""Driven (secondary) ports of ingestion: what it needs from git, storage and other domains."""

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.models import (
    Access,
    ArticleChunk,
    ArticleTags,
    AutoSync,
    ChunkingConfig,
    Collected,
    ConvertedArticle,
    CopiedVersion,
    Credential,
    EmbeddedBatch,
    EmbedPlan,
    FetchedFile,
    GitRename,
    ImportedRef,
    ImportedTags,
    ImportedVersion,
    ImportSource,
    IncludeRefused,
    InstructionPolicy,
    Job,
    JobFilter,
    JobId,
    KnownLibrary,
    NewLibrary,
    ParsedArticle,
    PathSelection,
    ProblemCode,
    ProposedId,
    RemoteRefs,
    Removed,
    RepositoryUrl,
    StoredArticle,
    StoredTags,
    TaggedPath,
    TagRule,
    VersionToEmbed,
    Webhook,
    WebhookDelivery,
)
from exactdocs_kernel import Sort, SortValue


class JobRepository(Protocol):
    """Persistence for jobs."""

    async def add(self, job: Job) -> None:
        """Store a new job.

        Raises ``VersionImportingError`` when it is an unfinished import of a (library, ref)
        that already has one, and ``PushQueuedError`` when it is a queued ``push`` of a
        (library, ref, ref kind) that already has one queued: the repository enforces both
        atomically.

        Args:
            job: The new job.
        """
        ...

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID, unless it is ``cancelled``.

        The cancellation fields (``cancelled_by``, ``cancelled_at``) are not written: only
        ``cancel`` sets them, so a running job's progress never wipes a cancellation out.

        Args:
            job: The job as it is now.
        """
        ...

    async def cancel(self, job_id: JobId, *, by: str | None, now: datetime) -> Job | None:
        """Atomically ask to cancel a queued or running job, once.

        A ``queued`` job becomes ``cancelled`` (``finished_at``, ``cancelled_by`` and
        ``cancelled_at`` set); a ``running`` one only gets ``cancelled_by`` and ``cancelled_at``
        and stops at its next step boundary. A finished job, or one already asked, is left as
        it is. ``save`` never changes these two fields, nor a ``cancelled`` job at all.

        Args:
            job_id: The job's ID.
            by: Who cancels it (a user name); ``None`` for the instance itself.
            now: The time of the request.

        Returns:
            The job as it is after the request, or ``None`` when no job has this ID.
        """
        ...

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``.

        Args:
            job_id: The job's ID.

        Returns:
            The job with its problems, or ``None`` when no job has this ID.
        """
        ...

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered).

        Args:
            library: The library ID.

        Returns:
            Every job of the library, with its problems.
        """
        ...

    async def list_unfinished_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's ``queued`` and ``running`` jobs, newest first.

        Reads only those jobs, however many finished ones the library has: telling whether a
        ref is busy, and reusing a job that still waits, need nothing else.

        Args:
            library: The library ID.

        Returns:
            The library's unfinished jobs, with their problems, highest ID first.
        """
        ...

    async def list_newest_of_kind(self, library: str, kind: JobKind) -> Sequence[Job]:
        """Return the newest job of ``kind`` of each version of the library, without the others.

        Args:
            library: The library ID.
            kind: The job kind.

        Returns:
            One job per version (the newest), in no particular order.
        """
        ...

    async def list_page_for_library(
        self, library: str, *, before: str | None, limit: int
    ) -> Sequence[Job]:
        """Return one page of the library's jobs, newest first, without loading the others.

        Args:
            library: The library whose jobs are listed.
            before: Only jobs whose ID sorts before this one (the last job of the previous
                page, compared by code point); ``None`` starts at the newest job.
            limit: At most this many jobs.

        Returns:
            Up to ``limit`` jobs, with their problems, highest ID first.
        """
        ...

    async def search(
        self,
        job_filter: JobFilter,
        *,
        sort: Sort,
        after: tuple[SortValue, str] | None,
        limit: int,
    ) -> Sequence[Job]:
        """Return up to ``limit`` of the jobs that pass the filter, in ``sort`` order.

        A keyset page: ``(sort value, job ID)`` after ``after``, in the sort's direction; the ID
        breaks ties. ``sort.field`` is ``id``, ``created_at``, ``state``, ``kind`` or ``library``.

        Args:
            job_filter: Which jobs.
            sort: The order.
            after: The sort value and ID of the last job of the previous page; ``None`` starts.
            limit: At most this many jobs.

        Returns:
            The jobs in order, with their problems.
        """
        ...

    async def count(self, job_filter: JobFilter) -> int:
        """Count the jobs that pass the filter.

        Args:
            job_filter: Which jobs.

        Returns:
            How many there are.
        """
        ...

    async def libraries(self) -> Sequence[str]:
        """Return every library that has a job, as spelled in the jobs.

        Returns:
            The distinct library IDs, in no particular order.
        """
        ...

    async def list_latest(self) -> Sequence[Job]:
        """Return the newest job of every (library, version), ordered by library and version.

        ``push`` jobs are left out: they name a ref but say nothing about how its version fared.

        Returns:
            One job per pair; the jobs without a version count as one pair per library.
        """
        ...

    async def delete_for(self, library: str, version: str | None = None) -> None:
        """Delete the library's jobs (only those of ``version`` when given). Not running ones.

        Args:
            library: The library ID.
            version: Only the jobs of this ref; ``None`` deletes every job of the library.
        """
        ...

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state.

        Returns:
            The running jobs.
        """
        ...

    async def list_queued(self) -> Sequence[Job]:
        """Return every job in the ``queued`` state, oldest first.

        Returns:
            The queued jobs.
        """
        ...

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job.

        Returns it in the ``running`` state with ``started_at`` set, or ``None`` when nothing
        may run. This is what keeps two jobs of one library from ever running together.

        Args:
            now: The time recorded as the job's ``started_at``.

        Returns:
            The started job, or ``None``.
        """
        ...


class JobProgress(Protocol):
    """What a running job reports to; stored soon (not at every call), and at the job's end."""

    async def report(self, *, done: int, total: int) -> None:
        """``done`` of ``total`` files processed.

        Args:
            done: Files processed so far.
            total: Files to process in all.
        """
        ...

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        """Record a problem with a file (skipped or imported with a note); the job goes on.

        Args:
            path: The file's repository path.
            code: What kind of problem it is.
            reason: What happened, in words for users.
        """
        ...

    async def chunking(self, *, chunked: int, reused: int) -> None:
        """``chunked`` articles were cut into chunks, ``reused`` took the chunks stored before.

        Args:
            chunked: Articles cut into chunks by this import.
            reused: Articles whose chunks were already stored under the same chunking.
        """
        ...

    async def parsing(self, *, parsed: int, taken: int) -> None:
        """Record how many articles were parsed and how many taken as an import stored them.

        Args:
            parsed: Articles parsed by this import.
            taken: Articles whose parsed text an earlier import stored, taken as they were.
        """
        ...


class JobRunner(Protocol):
    """Whatever runs queued jobs (a durable workflow engine), told about each new one."""

    async def submit(self, job: Job) -> None:
        """Hand over a job that was just queued; it runs when its library has no running job.

        Best effort, never raises: a job that cannot be handed over now stays queued and is
        handed over again when the runner starts (see ``RecoverJobs``).

        Args:
            job: The queued job.
        """
        ...


class Checkpoints(Protocol):
    """Durable steps: what a job did before a crash is not done again when it resumes."""

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        """Return what ``run`` returns, running it at most once per job to completion.

        A job that resumes after a crash gets the results of the steps it completed before,
        in the same order and without running them; the first step it had not completed runs
        again from its start. A job must therefore take the same steps in the same order on
        every run, and a step must be safe to run twice (its writes keyed by content). Results
        are stored, so they must be plain, picklable data.

        Args:
            name: The step's name, unique within the job.
            run: Runs the step.

        Returns:
            What ``run`` returned, now or on the run that completed the step.
        """
        ...


class JobHandler(Protocol):
    """Runs jobs of one kind. Raising fails the job; the error text is shown to users."""

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the job from the beginning.

        Args:
            job: The job, in the ``running`` state.
            progress: Where the job reports its progress and problems.
        """
        ...


class RecoveryHook(Protocol):
    """Cleans up after a job of one kind that was ``running`` when the app stopped."""

    async def __call__(self, job: Job, /) -> None:
        """Undo what the interrupted run left half done.

        Args:
            job: The job that was interrupted.
        """
        ...


class GitRemote(Protocol):
    """Talk to a remote git repository (the system ``git``; no hosting APIs)."""

    async def list_refs(
        self,
        repository: RepositoryUrl,
        *patterns: str,
        credential: Credential | None = None,
    ) -> RemoteRefs:
        """List the remote's refs (``git ls-remote``), narrowed by ref patterns such as ``HEAD``.

        Never prompts. ``credential`` is offered to the repository's own host only (never in the
        URL or the command line). Raises ``NotAGitRepositoryError``,
        ``RepositoryUnreachableError`` (including a timeout), ``RepositoryAuthRequiredError`` or
        ``HostKeyChangedError``.

        Args:
            repository: The repository.
            *patterns: Ref patterns to list (``HEAD``, ``refs/tags/*``...); every ref when empty.
            credential: The library's credential, if any.

        Returns:
            The refs found, with the default branch when ``HEAD`` was asked for.
        """
        ...

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        """Return the ``SHA256:...`` fingerprint of the SSH host key remembered for the host.

        ``None`` for a URL that is not SSH, or when no key is known (yet).

        Args:
            repository: The repository.

        Returns:
            The fingerprint, or ``None``.
        """
        ...


class GitGateway(Protocol):
    """Fetch the files of one commit: shallow, without unselected blobs, into a managed folder."""

    def fetch(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        selection: PathSelection,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> AbstractAsyncContextManager[Path]:
        """Check out ``commit_sha``: only the files ``selection`` may pick, plus the root README.

        Use as ``async with gateway.fetch(...) as folder``. The folder is private to this call and
        is removed on exit, also when the body or the fetch failed. It is a git work tree with no
        history: nothing older than the commit is fetched. ``refs`` (full names such as
        ``refs/tags/v1``) are tried only when the server refuses a request for a bare SHA.

        The files must be checked out verbatim (no eol, filter or encoding conversion): the import
        derives each file's git blob SHA from the bytes it reads.
        ``credential`` is offered to the repository's own host only, never in the URL or the
        command line. Never prompts, runs hooks or follows submodules. Raises
        ``RepositoryUnreachableError`` (including a timeout), ``RepositoryAuthRequiredError``,
        ``NotAGitRepositoryError``, ``CommitUnavailableError``, ``HostKeyChangedError`` or
        ``RepositoryTooLargeError``.

        Args:
            repository: The repository.
            commit_sha: The full SHA of the commit to check out.
            selection: Which files to check out.
            refs: Full ref names to try when a bare SHA is refused.
            credential: The library's credential, if any.

        Returns:
            An async context manager that yields the folder of the checked-out files.
        """
        ...

    def fetch_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        paths: Sequence[str],
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> AbstractAsyncContextManager[Path]:
        """Check out exactly these repository paths of ``commit_sha`` (the files that exist).

        Like ``fetch`` (same folder rules, verbatim files, credentials, errors), but nothing else
        is checked out, not even the README, and the download is bounded by ``max_bytes``:
        ``RepositoryTooLargeError`` when a server sends more. Paths are literal, never patterns.
        A path the commit does not have is simply absent from the folder.

        Args:
            repository: The repository.
            commit_sha: The full SHA of the commit.
            paths: Literal repository paths.
            max_bytes: The most bytes the download may bring in.
            refs: Full ref names to try when a bare SHA is refused.
            credential: The library's credential, if any.

        Returns:
            An async context manager that yields the folder of the checked-out files.
        """
        ...


class RepositoryFiles(Protocol):
    """Read a few files of one commit by path, each on its own (the instruction files, RET-08)."""

    async def read_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        paths: Sequence[str],
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> Mapping[str, FetchedFile]:
        """Read these literal repository paths of ``commit_sha``, at most ``max_bytes`` each.

        Only the commit's trees are fetched, then each existing file's blob. A path the commit
        does not have is left out. One that is too big, not a regular file, or a link that does
        not lead (in one hop, inside the repository) to a regular file has a ``problem`` and a
        ``code``, and the others are still read; a link that does is read as its target. Runs
        under an import's fetch slot. ``refs`` and ``credential`` are as in ``GitGateway.fetch``;
        raises what it raises.

        Args:
            repository: The repository.
            commit_sha: The pinned commit.
            paths: Literal repository paths.
            max_bytes: The most one file may be.
            refs: Full ref names to try when a bare SHA is refused.
            credential: The library's credential, if any.

        Returns:
            What was found, by path; a path the commit does not have is left out.
        """
        ...


class RenameSource(Protocol):
    """Ask git which files were moved between two commits, cheaply."""

    async def renames(
        self,
        repository: RepositoryUrl,
        old_sha: str,
        new_sha: str,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> Sequence[GitRename]:
        """Return the article files (``.md``, ``.mdx``, ``.rst``, ``.txt``) git sees as renamed.

        Only the two commits' trees are fetched (no history, no blobs); git then asks for the
        few blobs that renames with edits need to be told apart. Everything is bounded: one
        fetch slot, its own deadline, a size cap and git's rename limit (which bounds CPU; the
        download is bounded by the size cap and the deadline). Raises what
        ``GitGateway.fetch`` raises (callers treat any failure as "no renames known").
        ``refs`` are tried only when the server refuses a request for a bare SHA.

        Args:
            repository: The repository.
            old_sha: The commit the version served before.
            new_sha: The commit it serves now.
            refs: Full ref names to try when a bare SHA is refused.
            credential: The library's credential, if any.

        Returns:
            Each rename, old path to new path, with how similar the two files are.
        """
        ...


class RepositoryTree(Protocol):
    """Look at one commit's tree, and at most one small file of it, without a checkout.

    Both methods run apart from imports (preview slots, never ``GitGateway`` fetch slots), so a
    preview or an add never waits for a long import, and wait a bounded time for a slot.
    """

    async def list_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> Sequence[str]:
        """Return the repository-relative path of every file in the commit's tree.

        Only the commit and its trees are fetched (``--filter=blob:none``, depth 1), never a
        blob, and nothing is checked out. The paths are untrusted text from the repository
        (lossy-decoded, any characters). ``refs`` and ``credential`` are as in ``GitGateway.fetch``.
        Raises what ``GitGateway.fetch`` raises, ``TreeTooLargeError`` for a listing over the
        output cap and ``PreviewBusyError`` when no preview slot frees up in time.

        Args:
            repository: The repository.
            commit_sha: The full SHA of the commit.
            refs: Full ref names to try when a bare SHA is refused.
            credential: The library's credential, if any.

        Returns:
            Every file's path, folders left out.
        """
        ...

    async def read_file(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> FetchedFile:
        """Read one file at the root of the commit (``path`` is a plain name) by itself.

        The trees are fetched as by ``list_files``, then only that file's blob. A missing file
        is an empty ``FetchedFile``; one that is not a regular file (a link, a folder) or is
        larger than ``max_bytes`` has a ``problem`` and no data (a larger one is cut off while
        it downloads). Raises what ``list_files`` raises.

        Args:
            repository: The repository.
            commit_sha: The full SHA of the commit.
            path: A file name at the repository's root.
            max_bytes: The most the file may be.
            refs: Full ref names to try when a bare SHA is refused.
            credential: The library's credential, if any.

        Returns:
            The file's bytes, or why it was not read.
        """
        ...


class LibraryIds(Protocol):
    """What ingestion needs to know about the catalog, in its own words."""

    async def is_taken(self, library_id: ProposedId) -> bool:
        """Tell whether a library with this ``/owner/repo`` ID already exists.

        Args:
            library_id: The ID a new library would get.

        Returns:
            True when the catalog has a library with that ID, in any letter case.
        """
        ...


class Chunker(Protocol):
    """Cuts a parsed article into chunks at its headings, never inside a code block or table."""

    @property
    def config_hash(self) -> str:
        """Key for chunk sets: changes with the chunker's config, its version and the parser's."""
        ...

    def configured(self, config: ChunkingConfig) -> Chunker:
        """Return a chunker that cuts with a library's ``config`` (its own ``config_hash``).

        Raises ``InvalidChunkingConfigError`` for a ``config.chunker`` it does not provide.

        Args:
            config: The library's chunking settings.

        Returns:
            A chunker for that config; this one is unchanged.
        """
        ...

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        """Return the chunks in reading order; their contents joined are ``article.body``.

        An empty body has no chunks. This is CPU-bound and synchronous: the import use case
        should call it through ``asyncio.to_thread``. ``max_chars`` bounds a chunk only where
        a heading allows a cut: a section without deeper headings stays whole, however long.
        ``max_section_chars`` also splits such a section between its top-level blocks; only a
        single block longer than it makes a longer chunk.

        Args:
            article: The parsed article.

        Returns:
            The chunks, in order.
        """
        ...


class IncludedFiles(Protocol):
    """Reads the repository files a reStructuredText article includes, within import limits."""

    def read(self, path: str) -> str | IncludeRefused:
        """Return a file's text, or why it is not read.

        A file outside the fetched files, not a plain file, too large, not text, or over the
        article's budget of includes is refused. Synchronous: it runs in the converter's thread.

        Args:
            path: A repository path (resolved, inside the repository).

        Returns:
            The text, or the refusal.
        """
        ...


class MarkupConverter(Protocol):
    """Writes an article in another markup (reStructuredText) as the Markdown the chunker takes."""

    @property
    def version(self) -> str:
        """The converter's identity: in a converted article's key, so a new one converts again."""
        ...

    def convert(self, path: str, source: str, files: IncludedFiles) -> ConvertedArticle:
        """Convert one file; never raises for what the file holds (a problem says what was lost).

        CPU-bound and synchronous: the import use case calls it through ``asyncio.to_thread``.

        Args:
            path: The article's repository path.
            source: Its text.
            files: Reads the files its includes name.

        Returns:
            The Markdown body and the problems.
        """
        ...


class NewLibraries(Protocol):
    """Where ingestion puts a library it was asked to add (the catalog, in its own words)."""

    async def add(self, library: NewLibrary) -> str:
        """Store the library and return its canonical ID.

        Raises a conflict when the ID is taken and a validation error when it is not a valid ID.

        Args:
            library: What to add.

        Returns:
            The library's ID as stored.
        """
        ...

    async def discard(self, library_id: str) -> None:
        """Remove a library that was just added and has no versions (the undo of ``add``).

        Args:
            library_id: The ID ``add`` returned.
        """
        ...


class KnownLibraries(Protocol):
    """Which libraries the instance has (the catalog, in ingestion's words)."""

    async def all(self) -> Sequence[KnownLibrary]:
        """Return every library, with versions or not.

        Returns:
            The libraries.
        """
        ...


class LibrarySources(Protocol):
    """Where a library's articles come from (the catalog, in ingestion's words)."""

    async def imported_versions(self, library: str) -> Sequence[ImportedRef]:
        """Return the library's versions (ref, kind, commit SHA); raises ``NotFoundError``.

        ``library`` is a canonical (lower-case) ID.

        Args:
            library: The library ID.

        Returns:
            Every imported version.
        """
        ...

    async def get(self, library: str) -> ImportSource:
        """Return the repository and path selection of a library; raises when it is unknown.

        Args:
            library: The library ID.

        Returns:
            Where the library's articles come from and how they are selected, tagged and cut.
        """
        ...

    async def renames_of(self, library: str, ref: str) -> Sequence[GitRename]:
        """Return the rename map the version serves now (empty when it has none or is unknown).

        Args:
            library: The library ID.
            ref: The version's ref.

        Returns:
            The renames, old path to new path.
        """
        ...


class LibrarySettingsStore(Protocol):
    """Where a library's paths and tag rules are kept (the catalog, in ingestion's words)."""

    async def save(
        self,
        library: str,
        selection: PathSelection,
        tag_rules: Sequence[TagRule],
        chunking: ChunkingConfig,
    ) -> None:
        """Replace the library's paths, tag rules and chunking; raises if it is unknown.

        Imports read them when they run, so every import queued or running after this uses them.

        Args:
            library: The library ID.
            selection: The paths to import.
            tag_rules: Tags given to articles by path.
            chunking: How articles are cut into chunks.
        """
        ...


class VersionCopier(Protocol):
    """Copies what a version serves into a new pending manifest (the catalog, in its words)."""

    async def copy(self, library: str, ref: str, *, content_version: int) -> CopiedVersion | None:
        """Copy the version's active manifest (entries, tags, images, renames) as a pending one.

        Returns the copy with each article's stored text; ``None`` when the library or the
        version is unknown or serves nothing. Raises ``StoredTextOutdatedError``, copying
        nothing, when the articles were stored by another parser version than
        ``content_version``: their text is not what the parser gives now.

        Args:
            library: The library ID.
            ref: The version's ref.
            content_version: The parser version the copied text must have been stored by.

        Returns:
            The pending copy, or ``None``.
        """
        ...


class ImportedTagStore(Protocol):
    """The imported tags of what a version serves (the catalog, in ingestion's words)."""

    async def stored_tags(self, library: str, ref: str) -> StoredTags | None:
        """Return the active manifest of the version with its articles' tag sources.

        ``None`` when the library or the version is unknown, or the version serves nothing.

        Args:
            library: The library ID.
            ref: The version's ref.

        Returns:
            The manifest's ID and the tag sources of each article, or ``None``.
        """
        ...

    async def set_imported_tags(
        self, manifest_id: str, tags: Mapping[str, ImportedTags]
    ) -> ArticleTags:
        """Replace the imported tags and their sources of these articles, in one transaction.

        Only what differs is written; manual tags are kept. Returns every tag (imported and
        manual) of each given article the manifest has, changed or not: the chunk index must
        get the same.

        Args:
            manifest_id: The manifest.
            tags: The new imported tags with their sources, by article path.

        Returns:
            Every tag of each given article, by path.
        """
        ...


class GuidancePolicy(Protocol):
    """Whether a library keeps its instruction files (retrieval's repo guidance, RET-08)."""

    async def instruction_policy(self, library: str) -> InstructionPolicy:
        """Say whether imports of the library keep its ``AGENTS.md`` / ``CLAUDE.md`` files.

        Args:
            library: ``/owner/repo``, any letter case.

        Returns:
            ``KEEP`` when the library's repo guidance is on; ``DROP`` (the default) otherwise.
        """
        ...


class StoredArticleSource(Protocol):
    """What earlier imports stored for a file (the catalog, in ingestion's words)."""

    async def find(
        self, library: str, ref: str, parser_version: int, files: Sequence[tuple[str, str]]
    ) -> Sequence[StoredArticle]:
        """Return what the library stored for these ``(path, blob SHA)`` files with this parser.

        ``ref`` is the version being imported: what it serves now is the likeliest match.

        Files nothing was stored for that way are left out. The importer asks for at most 500
        files per call.

        Args:
            library: The library ID.
            ref: The version being imported.
            parser_version: Only text stored by this parser version is returned.
            files: ``(path, blob SHA)`` of each file the import found.

        Returns:
            One stored article per file found, with its parsed text.
        """
        ...


class VersionPublisher(Protocol):
    """Publishes a version into the catalog in two steps: store (invisible), then activate."""

    async def store(self, version: ImportedVersion) -> str:
        """Store the version's articles as a pending manifest; return its ID. Nothing is served.

        Args:
            version: The imported version with its articles.

        Returns:
            The pending manifest's ID.
        """
        ...

    async def activate(self, manifest_id: str) -> None:
        """Make the pending manifest what its version serves, all at once.

        Args:
            manifest_id: The pending manifest.
        """
        ...

    async def apply_manual_tags(self, manifest_id: str) -> ArticleTags:
        """Give the pending manifest the manual tags its library has now (renames followed).

        Returns the articles that carry manual tags, with every tag they carry: the chunk index
        must get the same.

        Args:
            manifest_id: The pending manifest.

        Returns:
            Every tag of each article that has manual tags, by path.
        """
        ...

    async def replace_renames(
        self, library: str, ref: str, *, from_ref: str, renames: Sequence[GitRename]
    ) -> Mapping[str, ArticleTags]:
        """Make ``renames`` (from ``from_ref``) the rename map ``ref`` serves; re-tag the library.

        Renames into a path that is not an article of the version are left out. Every live
        manifest of the library is re-tagged (later versions follow the map too). Returns, per
        manifest ID, the articles that carry manual tags (or carried some) with their tags now,
        for the chunk index; empty when ``ref`` serves nothing.

        Args:
            library: The library ID.
            ref: The version whose rename map is replaced.
            from_ref: The version the renames start from.
            renames: The renames, old path to new path.

        Returns:
            The re-tagged articles, by manifest ID.
        """
        ...

    async def describe(
        self,
        *,
        library: str,
        ref: str,
        title: str | None,
        description: str | None,
        rules: Sequence[str],
    ) -> None:
        """Offer the title, description and rules found in an activated version.

        Title and description come from its ``context7.json``, else from the root README's
        heading and first paragraph; ``None`` means neither had one. ``rules`` are the
        ``context7.json`` rules (empty without a usable file). The catalog decides what to do
        with them: it only takes the default version's, and never replaces a title or
        description a user edited.

        Args:
            library: The library ID.
            ref: The activated version.
            title: The title found, or ``None``.
            description: The description found, or ``None``.
            rules: The ``context7.json`` rules.
        """
        ...

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete the library's pending manifests (only ``manifest_id``'s when given).

        Args:
            manifest_id: Only this pending manifest; ``None`` discards all of the library's.
            library: The library ID.
        """
        ...


class ChunkIndex(Protocol):
    """Where chunks are stored and searched (retrieval, in ingestion's words)."""

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        """Return the stored chunks of blobs chunked under ``config_hash``; others are left out.

        Args:
            config_hash: The chunker's ``config_hash``.
            blob_shas: Git blob SHAs of the articles.

        Returns:
            The chunks, by blob SHA.
        """
        ...

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        """Store and index the version's chunks of a pending manifest (before it is activated).

        Args:
            manifest_id: The pending manifest.
            version: The imported version with its chunked articles.
        """
        ...

    async def retag(self, manifest_id: str, tags: ArticleTags) -> None:
        """Make the chunks of these articles of the manifest carry these tags; no re-chunking.

        Args:
            manifest_id: The manifest.
            tags: Every tag of each article, by path.
        """
        ...

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete the library's pending chunks (only ``manifest_id``'s when given).

        Call it before the catalog's discard: it needs the catalog to still say "pending".

        Args:
            manifest_id: Only this pending manifest's; ``None`` discards all of the library's.
            library: The library ID.
        """
        ...

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        """Delete the chunks of manifests the catalog has just deleted (and unused chunk sets).

        Args:
            manifest_ids: The deleted manifests.
        """
        ...


class Removals(Protocol):
    """Removes versions and libraries from the catalog (in ingestion's words)."""

    async def remove_version(self, library: str, ref: str) -> Removed:
        """Delete the version and its manifests at once; raises ``NotFoundError`` if unknown.

        Args:
            library: The library ID.
            ref: The version's ref.

        Returns:
            The manifests deleted, for the chunk index.
        """
        ...

    async def remove_library(self, library: str) -> Removed:
        """Delete the library, its versions and manifests; raises ``NotFoundError`` if unknown.

        Args:
            library: The library ID.

        Returns:
            The manifests deleted, for the chunk index.
        """
        ...


class Collector(Protocol):
    """Frees what one domain no longer needs; the collection job runs them in order."""

    async def collect(self, *, grace_seconds: int) -> Collected:
        """Delete what is unused and older than the grace period; say how many things.

        Args:
            grace_seconds: How long something stays after it became unused.

        Returns:
            How many things of each kind were deleted.
        """


class CredentialVault(Protocol):
    """Where the credentials of private libraries are kept (encrypted at rest)."""

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        """Store the library's credential for ``scope`` (``RepositoryUrl.credential_scope``).

        Args:
            library: The library ID.
            scope: Where the credential may be offered.
            credential: The token or deploy key.
        """
        ...

    async def load(self, library: str, scope: str) -> Credential | None:
        """Return the library's credential, or ``None`` when it has none.

        Raises ``CredentialsRequiredError`` when one is stored but cannot be read (the secret
        key is not the one it was sealed with) or was stored for another ``scope``.

        Args:
            library: The library ID.
            scope: The library's ``credential_scope`` now.

        Returns:
            The credential, or ``None``.
        """
        ...

    async def delete(self, library: str) -> None:
        """Forget the library's credential (nothing happens when it has none).

        Args:
            library: The library ID.
        """
        ...

    async def has(self, library: str) -> bool:
        """Whether the library has a stored credential (without opening it).

        Args:
            library: The library ID.

        Returns:
            True when one is stored, readable or not.
        """
        ...


class SecretBox(Protocol):
    """Authenticated encryption of one short text with the instance's secret key."""

    def seal(self, plaintext: str) -> str:
        """Return the text encrypted, as printable characters.

        Args:
            plaintext: The text to seal.

        Returns:
            The sealed text.
        """
        ...

    def open(self, sealed: str) -> str:
        """Return the original text.

        Raises ``exactdocs_kernel.SealedTextUnreadableError`` when it cannot be read (another
        secret key or purpose sealed it, or it was altered); the vault reports that as
        ``CredentialsRequiredError``.

        Args:
            sealed: What ``seal`` returned.

        Returns:
            The plaintext.
        """
        ...


class ManualTagStore(Protocol):
    """Where the tags users set by hand on an article path are kept (the catalog)."""

    async def set_tags(self, library: str, path: str, tags: Sequence[str]) -> TaggedPath:
        """Replace the path's manual tags for every version; re-tag the pending and active ones.

        Raises a not-found error for an unknown library and a validation error for a bad path or
        tag.

        Args:
            library: The library ID.
            path: The article's repository path.
            tags: The new manual tags; empty removes them.

        Returns:
            The path with its manual tags now.
        """
        ...


class AutoSyncStore(Protocol):
    """Where the libraries' scheduled checks are kept (``AutoSync``, one per library)."""

    async def get(self, library: str) -> AutoSync | None:
        """Return the library's schedule, or ``None`` when it is not checked on its own.

        Args:
            library: The library ID.

        Returns:
            The schedule, or ``None``.
        """
        ...

    async def save(self, auto_sync: AutoSync) -> None:
        """Store the schedule, replacing the library's earlier one.

        Args:
            auto_sync: The schedule.
        """
        ...

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        """Store a check's result if the schedule is still the one it read; say whether it was.

        ``checked``'s ``checked_at`` and ``last_error`` are stored in one atomic step only when
        the stored ``revision`` and ``checked_at`` are ``read``'s: a schedule saved or removed
        meanwhile is left alone.

        Args:
            read: The schedule as the check read it.
            checked: The same schedule with the check's result.

        Returns:
            True when the result was stored.
        """
        ...

    async def delete(self, library: str) -> None:
        """Forget the library's schedule (nothing happens when it has none).

        Args:
            library: The library ID.
        """
        ...

    async def list_all(self) -> Sequence[AutoSync]:
        """Return every stored schedule, by library.

        Returns:
            The schedules.
        """
        ...


class ScheduleSwitch(Protocol):
    """Turns the scheduled check's tick on or off: with no schedule, nothing is written."""

    async def turn(self, *, on: bool) -> None:
        """Make the tick run (``on``) or stop; best effort, never raises.

        The worker sets it again from the stored schedules when it starts.

        Args:
            on: True makes the tick run, False stops it.
        """
        ...


class VersionEmbedder(Protocol):
    """Embeds versions with the instance's embedding model (retrieval, in ingestion's words).

    Nothing of a library with AI off is ever sent: its plans are skipped.
    """

    async def plan(self, library: str, ref: str) -> EmbedPlan:
        """Pick the version's embedding space (a new model gets a new one) and count the gap.

        Args:
            library: The library ID.
            ref: The version.

        Returns:
            The plan; ``space_id`` is ``None`` when nothing is to be sent.
        """
        ...

    async def embed_batch(self, library: str, ref: str, plan: EmbedPlan) -> EmbeddedBatch:
        """Embed the next batch of the version's chunks that have no vector.

        Args:
            library: The library ID.
            ref: The version.
            plan: The job's plan.

        Returns:
            What it embedded, and whether the version is done.
        """
        ...

    async def finish(self, plan: EmbedPlan) -> None:
        """Switch to the plan's space once it covers every version, retiring the older ones.

        Args:
            plan: The job's plan.
        """
        ...

    async def unembedded(self, library: str | None) -> Sequence[VersionToEmbed]:
        """Name the versions not fully embedded (of one library, or all); none without a model.

        Args:
            library: Only this library's; every library's when ``None``.

        Returns:
            The versions.
        """
        ...


class LibraryLocks(Protocol):
    """One lock per library: work under it never overlaps other work under the same library's.

    ``TagLocks`` (in-process ``asyncio.Lock`` objects) is enough while one process runs jobs
    and serves the API; processes sharing a database need a lock that database holds for them
    (a PostgreSQL advisory lock per library). Each purpose (re-tagging, settings edits) has its
    own object, so they never wait on each other.
    """

    def of(self, library: str) -> AbstractAsyncContextManager[None]:
        """Return the lock of ``library`` (`/owner/repo`, any letter case), to ``async with``.

        Args:
            library: The library's ID.

        Returns:
            An async context manager that holds the lock while it is entered.
        """
        ...


class WebhookSecrets(Protocol):
    """Where the libraries' webhook secrets are kept (sealed at rest, one per library)."""

    async def save(self, webhook: Webhook) -> None:
        """Store the library's webhook, replacing the one it had.

        Args:
            webhook: The library's webhook and its secret.
        """
        ...

    async def get(self, library: str) -> Webhook | None:
        """Return the library's webhook with its secret, or ``None`` when it has none.

        Raises ``WebhookSecretUnreadableError`` when one is stored but does not open (the
        instance's secret key is not the one it was sealed with).

        Args:
            library: The library ID.

        Returns:
            The webhook, or ``None``.
        """
        ...

    async def created_at(self, library: str) -> datetime | None:
        """Say when the library's webhook was created, without opening its secret.

        Args:
            library: The library ID.

        Returns:
            When it was created, or ``None`` when the library has none.
        """
        ...

    async def delete(self, library: str) -> None:
        """Forget the library's webhook (nothing happens when it has none).

        Args:
            library: The library ID.
        """
        ...


class WebhookDeliveries(Protocol):
    """The deliveries accepted lately, so a redelivery is answered ``duplicate``."""

    async def record(self, delivery: WebhookDelivery, *, prune_before: datetime) -> bool:
        """Remember the delivery unless it is known; say whether it was new.

        Atomic across processes (``INSERT ... ON CONFLICT DO NOTHING`` on PostgreSQL): of two
        concurrent records of one (library, provider, delivery ID), exactly one is new.
        Deliveries received before ``prune_before`` are forgotten in the same write.

        Args:
            delivery: The delivery.
            prune_before: Older deliveries are forgotten.

        Returns:
            True when it was not known.
        """
        ...

    async def forget(self, delivery: WebhookDelivery) -> None:
        """Forget the delivery, so the forge's retry of it is acted on.

        Args:
            delivery: The delivery whose job could not be queued.
        """
        ...

    async def delete_for(self, library: str) -> None:
        """Forget every delivery of the library.

        Args:
            library: The library ID.
        """
        ...


class AccessPolicy(Protocol):
    """Library roles: what the caller may do with a library (a bridge to identity)."""

    async def can_create(self, library: str | None = None) -> bool:
        """Tell whether the caller has the instance-wide library creation permission.

        Args:
            library: Proposed ID when known; None before one is available.

        Returns:
            Whether creation is permitted.
        """
        ...

    async def allows(self, library: str, access: Access) -> bool:
        """Tell whether the caller may do what ``access`` stands for with the library.

        Args:
            library: The library ID (``/owner/repo``), any case.
            access: The role the action needs.

        Returns:
            ``True`` when the caller's effective role on the library is that or higher.
        """
        ...

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        """Return the libraries the caller may read.

        Args:
            libraries: Library IDs.

        Returns:
            The lower-case IDs among them the caller may read.
        """
        ...
