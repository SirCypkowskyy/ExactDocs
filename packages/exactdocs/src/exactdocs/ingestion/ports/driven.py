"""Driven (secondary) ports of ingestion: what it needs from git, storage and other domains."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from exactdocs.ingestion.models import (
    ArticleChunk,
    ArticleTags,
    AutoSync,
    ChunkingConfig,
    Collected,
    CopiedVersion,
    Credential,
    EmbeddedBatch,
    EmbedPlan,
    FetchedFile,
    GitRename,
    ImportedRef,
    ImportedVersion,
    ImportSource,
    InstructionPolicy,
    Job,
    JobId,
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
)


class JobRepository(Protocol):
    """Persistence for jobs."""

    async def add(self, job: Job) -> None:
        """Store a new job.

        Raises ``VersionImportingError`` when it is an unfinished import of a (library, ref)
        that already has one: the repository enforces this atomically.
        """
        ...

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID."""
        ...

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``."""
        ...

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered)."""
        ...

    async def list_latest(self) -> Sequence[Job]:
        """Return the newest job of every (library, version), ordered by library and version."""
        ...

    async def delete_for(self, library: str, version: str | None = None) -> None:
        """Delete the library's jobs (only those of ``version`` when given). Not running ones."""
        ...

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state."""
        ...

    async def list_queued(self) -> Sequence[Job]:
        """Return every job in the ``queued`` state, oldest first."""
        ...

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job.

        Returns it in the ``running`` state with ``started_at`` set, or ``None`` when nothing
        may run. This is what keeps two jobs of one library from ever running together.
        """
        ...


class JobProgress(Protocol):
    """What a running job reports to; stored soon (not at every call), and at the job's end."""

    async def report(self, *, done: int, total: int) -> None:
        """``done`` of ``total`` files processed."""
        ...

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        """Record a problem with a file (skipped or imported with a note); the job goes on."""
        ...

    async def chunking(self, *, chunked: int, reused: int) -> None:
        """``chunked`` articles were cut into chunks, ``reused`` took the chunks stored before."""
        ...

    async def parsing(self, *, parsed: int, taken: int) -> None:
        """Record how many articles were parsed and how many taken as an import stored them."""
        ...


class JobRunner(Protocol):
    """Whatever runs queued jobs (a durable workflow engine), told about each new one."""

    async def submit(self, job: Job) -> None:
        """Hand over a job that was just queued; it runs when its library has no running job.

        Best effort, never raises: a job that cannot be handed over now stays queued and is
        handed over again when the runner starts (see ``RecoverJobs``).
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
        """
        ...


class JobHandler(Protocol):
    """Runs jobs of one kind. Raising fails the job; the error text is shown to users."""

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the job from the beginning."""
        ...


class RecoveryHook(Protocol):
    """Cleans up after a job of one kind that was ``running`` when the app stopped."""

    async def __call__(self, job: Job, /) -> None:
        """Undo what the interrupted run left half done."""
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
        """
        ...

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        """Return the ``SHA256:...`` fingerprint of the SSH host key remembered for the host.

        ``None`` for a URL that is not SSH, or when no key is known (yet).
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
        """Return the ``.md`` / ``.mdx`` files (any letter case) git sees as renamed.

        Only the two commits' trees are fetched (no history, no blobs); git then asks for the
        few blobs that renames with edits need to be told apart. Everything is bounded: one
        fetch slot, its own deadline, a size cap and git's rename limit (which bounds CPU; the
        download is bounded by the size cap and the deadline). Raises what
        ``GitGateway.fetch`` raises (callers treat any failure as "no renames known").
        ``refs`` are tried only when the server refuses a request for a bare SHA.
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
        """
        ...


class LibraryIds(Protocol):
    """What ingestion needs to know about the catalog, in its own words."""

    async def is_taken(self, library_id: ProposedId) -> bool:
        """Tell whether a library with this ``/owner/repo`` ID already exists."""
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
        """
        ...

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        """Return the chunks in reading order; their contents joined are ``article.body``.

        An empty body has no chunks. This is CPU-bound and synchronous: the import use case
        should call it through ``asyncio.to_thread``. ``max_chars`` bounds a chunk only where
        a heading allows a cut: a section without deeper headings stays whole, however long.
        """
        ...


class NewLibraries(Protocol):
    """Where ingestion puts a library it was asked to add (the catalog, in its own words)."""

    async def add(self, library: NewLibrary) -> str:
        """Store the library and return its canonical ID.

        Raises a conflict when the ID is taken and a validation error when it is not a valid ID.
        """
        ...

    async def discard(self, library_id: str) -> None:
        """Remove a library that was just added and has no versions (the undo of ``add``)."""
        ...


class LibrarySources(Protocol):
    """Where a library's articles come from (the catalog, in ingestion's words)."""

    async def imported_versions(self, library: str) -> Sequence[ImportedRef]:
        """Return the library's versions (ref, kind, commit SHA); raises ``NotFoundError``.

        ``library`` is a canonical (lower-case) ID.
        """
        ...

    async def get(self, library: str) -> ImportSource:
        """Return the repository and path selection of a library; raises when it is unknown."""
        ...

    async def renames_of(self, library: str, ref: str) -> Sequence[GitRename]:
        """Return the rename map the version serves now (empty when it has none or is unknown)."""
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
        """
        ...


class ImportedTagStore(Protocol):
    """The imported tags of what a version serves (the catalog, in ingestion's words)."""

    async def stored_tags(self, library: str, ref: str) -> StoredTags | None:
        """Return the active manifest of the version with its articles' tag sources.

        ``None`` when the library or the version is unknown, or the version serves nothing.
        """
        ...

    async def set_imported_tags(self, manifest_id: str, tags: ArticleTags) -> ArticleTags:
        """Replace the imported tags of these articles of the manifest, in one transaction.

        Only what differs is written; manual tags are kept. Returns every tag (imported and
        manual) of each given article the manifest has, changed or not: the chunk index must
        get the same.
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
        """
        ...


class VersionPublisher(Protocol):
    """Publishes a version into the catalog in two steps: store (invisible), then activate."""

    async def store(self, version: ImportedVersion) -> str:
        """Store the version's articles as a pending manifest; return its ID. Nothing is served."""
        ...

    async def activate(self, manifest_id: str) -> None:
        """Make the pending manifest what its version serves, all at once."""
        ...

    async def apply_manual_tags(self, manifest_id: str) -> ArticleTags:
        """Give the pending manifest the manual tags its library has now (renames followed).

        Returns the articles that carry manual tags, with every tag they carry: the chunk index
        must get the same.
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
        """
        ...

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete the library's pending manifests (only ``manifest_id``'s when given)."""
        ...


class ChunkIndex(Protocol):
    """Where chunks are stored and searched (retrieval, in ingestion's words)."""

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        """Return the stored chunks of blobs chunked under ``config_hash``; others are left out."""
        ...

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        """Store and index the version's chunks of a pending manifest (before it is activated)."""
        ...

    async def retag(self, manifest_id: str, tags: ArticleTags) -> None:
        """Make the chunks of these articles of the manifest carry these tags; no re-chunking."""
        ...

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete the library's pending chunks (only ``manifest_id``'s when given).

        Call it before the catalog's discard: it needs the catalog to still say "pending".
        """
        ...

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        """Delete the chunks of manifests the catalog has just deleted (and unused chunk sets)."""
        ...


class Removals(Protocol):
    """Removes versions and libraries from the catalog (in ingestion's words)."""

    async def remove_version(self, library: str, ref: str) -> Removed:
        """Delete the version and its manifests at once; raises ``NotFoundError`` if unknown."""
        ...

    async def remove_library(self, library: str) -> Removed:
        """Delete the library, its versions and manifests; raises ``NotFoundError`` if unknown."""
        ...


class Collector(Protocol):
    """Frees what one domain no longer needs; the collection job runs them in order."""

    async def collect(self, *, grace_seconds: int) -> Collected:
        """Delete what is unused and older than the grace period; say how many things."""


class CredentialVault(Protocol):
    """Where the credentials of private libraries are kept (encrypted at rest)."""

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        """Store the library's credential for ``scope`` (``RepositoryUrl.credential_scope``)."""
        ...

    async def load(self, library: str, scope: str) -> Credential | None:
        """Return the library's credential, or ``None`` when it has none.

        Raises ``CredentialsRequiredError`` when one is stored but cannot be read (the secret
        key is not the one it was sealed with) or was stored for another ``scope``.
        """
        ...

    async def delete(self, library: str) -> None:
        """Forget the library's credential (nothing happens when it has none)."""
        ...

    async def has(self, library: str) -> bool:
        """Whether the library has a stored credential (without opening it)."""
        ...


class SecretBox(Protocol):
    """Authenticated encryption of one short text with the instance's secret key."""

    def seal(self, plaintext: str) -> str:
        """Return the text encrypted, as printable characters."""
        ...

    def open(self, sealed: str) -> str:
        """Return the original text.

        Raises ``exactdocs_kernel.SealedTextUnreadableError`` when it cannot be read (another
        secret key or purpose sealed it, or it was altered); the vault reports that as
        ``CredentialsRequiredError``.
        """
        ...


class ManualTagStore(Protocol):
    """Where the tags users set by hand on an article path are kept (the catalog)."""

    async def set_tags(self, library: str, path: str, tags: Sequence[str]) -> TaggedPath:
        """Replace the path's manual tags for every version; re-tag the pending and active ones.

        Raises a not-found error for an unknown library and a validation error for a bad path or
        tag.
        """
        ...


class AutoSyncStore(Protocol):
    """Where the libraries' scheduled checks are kept (``AutoSync``, one per library)."""

    async def get(self, library: str) -> AutoSync | None:
        """Return the library's schedule, or ``None`` when it is not checked on its own."""
        ...

    async def save(self, auto_sync: AutoSync) -> None:
        """Store the schedule, replacing the library's earlier one."""
        ...

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        """Store a check's result if the schedule is still the one it read; say whether it was.

        ``checked``'s ``checked_at`` and ``last_error`` are stored in one atomic step only when
        the stored ``revision`` and ``checked_at`` are ``read``'s: a schedule saved or removed
        meanwhile is left alone.
        """
        ...

    async def delete(self, library: str) -> None:
        """Forget the library's schedule (nothing happens when it has none)."""
        ...

    async def list_all(self) -> Sequence[AutoSync]:
        """Return every stored schedule, by library."""
        ...


class ScheduleSwitch(Protocol):
    """Turns the scheduled check's tick on or off: with no schedule, nothing is written."""

    async def turn(self, *, on: bool) -> None:
        """Make the tick run (``on``) or stop; best effort, never raises.

        The worker sets it again from the stored schedules when it starts.
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
