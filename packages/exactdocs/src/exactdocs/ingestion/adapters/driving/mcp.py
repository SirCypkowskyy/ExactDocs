"""MCP adapter for ingestion (#613): people who may create libraries add them from their agent.

Two tools, ``add_docs`` and ``import_status``, over the driving ports the REST adapter uses
(``add_library``, ``add_version``, ``sync_library``, ``get_job``, ``list_jobs``). Both carry
FastMCP's component-level ``auth``: a caller it refuses does not see them in ``tools/list``, and a
call by name answers as for a tool that does not exist.

An agent's arguments may come from a prompt injection in docs it read, so a source is checked
before anything is fetched: an ``https://`` URL without credentials or a port, on a host of the
allowlist, whose name resolves to public addresses only; or a library that exists. There is no
credential argument and nothing here removes anything. Answers are a line per job and start with
the untrusted-content notice: they repeat ref names, which come from the repositories.
"""

import asyncio
import re
import socket
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.server.auth import AuthCheck
from fastmcp.tools import ToolResult
from mcp.types import TextContent, ToolAnnotations
from pydantic import Field

from exactdocs.ingestion.constants import (
    ACTIVE_JOB_STATES,
    HTTPS_PORT,
    MAX_ANSWER_REF,
    MAX_MCP_PATH,
    MAX_MCP_PATHS,
    MAX_MCP_SOURCE,
    MAX_STATUS_JOBS,
    SHORTHAND_HOST,
    STATUS_SCAN,
)
from exactdocs.ingestion.constants._mcp import _SHORTHAND
from exactdocs.ingestion.dtos import (
    AddLibraryCommand,
    AddVersionCommand,
    GetJobQuery,
    JobSummary,
    ListJobsQuery,
    ListLibraryJobsQuery,
    SyncedVersion,
    SyncLibraryCommand,
)
from exactdocs.ingestion.errors import (
    InvalidRepositoryUrlError,
    LibraryExistsError,
    LibraryIdTakenError,
    SourceNotAllowedError,
    SourceProblem,
    UnknownLibraryError,
    UnknownRefError,
    VersionExistsError,
    VersionImportingError,
)
from exactdocs.ingestion.models import RepositoryUrl, SyncStatus
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    AddVersion,
    GetJob,
    ListJobs,
    ListLibraryJobs,
    SyncLibrary,
)
from exactdocs_kernel import (
    LIBRARY_ID_PATTERN,
    MAX_NAME,
    NOTICE,
    ValidationError,
    is_public_address,
    respelled,
)

type ResolveHost = Callable[[str], Awaitable[Sequence[str]]]
"""Resolves a host name to its IP addresses."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Source:
    """What an ``add_docs`` source names: a repository URL, a library ID, or a library name."""

    url: str | None = None
    """The ``https://`` URL to import from; ``None`` for an existing library."""
    library: str | None = None
    """The library ID: proposed by the URL, or given."""
    name: str | None = None
    """A library name to resolve to its ID."""


@dataclass(frozen=True, slots=True, kw_only=True)
class KnownLibrary:
    """A library that exists, as ``add_docs`` needs it."""

    id: str
    """Its canonical ID."""
    source_url: str
    """The repository it imports from."""
    versions: Mapping[str, str] = field(default_factory=dict)
    """The commit of each imported version, by ref."""


def parse_source(text: str, *, hosts: Collection[str]) -> Source:
    """Read an ``add_docs`` source; refuse every URL an agent may not import from.

    Args:
        text: The source as the agent sent it.
        hosts: The lower-case hosts imports over MCP may use.

    Returns:
        The URL and its proposed ID, a library ID, or a name.

    Raises:
        SourceNotAllowedError: A library ID that is not ``/owner/repo``.
    """
    source = text.strip()
    if source.startswith("/") and "://" not in source:
        if not re.fullmatch(LIBRARY_ID_PATTERN, source):
            raise SourceNotAllowedError(SourceProblem.LIBRARY_ID)
        return Source(library=source)
    if _SHORTHAND.fullmatch(source):
        return _allowed_url(f"https://{SHORTHAND_HOST}/{source}", hosts)
    if not any(c in source for c in "/:@"):
        return Source(name=source)
    return _allowed_url(source, hosts)


def _allowed_url(url: str, hosts: Collection[str]) -> Source:
    """Check a URL an agent sent: ``https://``, no credentials or port, an allowed host.

    Args:
        url: The URL, trimmed.
        hosts: The lower-case hosts imports over MCP may use.

    Returns:
        The URL and the library ID it proposes.

    Raises:
        SourceNotAllowedError: Anything else, or a URL ``POST /libraries`` would refuse.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise SourceNotAllowedError(SourceProblem.MALFORMED) from None
    problem = None
    if parts.scheme.lower() != "https":
        problem = SourceProblem.SCHEME
    elif "@" in parts.netloc:
        problem = SourceProblem.CREDENTIALS
    elif port not in {None, HTTPS_PORT}:
        problem = SourceProblem.PORT
    elif (parts.hostname or "").lower() not in hosts:
        problem = SourceProblem.HOST
    if problem is not None:
        raise SourceNotAllowedError(problem)
    try:
        repository = RepositoryUrl.parse(url)
    except InvalidRepositoryUrlError as exc:
        raise SourceNotAllowedError(exc.problem) from None
    return Source(url=repository.url, library=str(repository.library_id))


async def check_addresses(host: str, resolve: ResolveHost) -> None:
    """Refuse a host unless every address its name resolves to now is public.

    Args:
        host: The host name.
        resolve: Resolves it.

    Raises:
        SourceNotAllowedError: It does not resolve, or an address is loopback, private,
            link-local (the metadata endpoints) or otherwise not public.
    """
    try:
        addresses = await resolve(host)
    except OSError:
        raise SourceNotAllowedError(SourceProblem.UNRESOLVED) from None
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise SourceNotAllowedError(SourceProblem.PRIVATE)


async def resolve_addresses(host: str) -> list[str]:
    """Resolve a host name with the system resolver, as git will a moment later.

    Args:
        host: The host name.

    Returns:
        Every address it resolves to for HTTPS.
    """
    infos = await asyncio.get_running_loop().getaddrinfo(host, HTTPS_PORT, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def register_tools(
    mcp: FastMCP,
    *,
    add_library: AddLibrary,
    add_version: AddVersion,
    sync_library: SyncLibrary,
    get_job: GetJob,
    list_jobs: ListJobs,
    list_library_jobs: ListLibraryJobs,
    find_library: Callable[[str], Awaitable[KnownLibrary | None]],
    resolve_library_name: Callable[[str], Awaitable[str]],
    hosts: Collection[str],
    resolve_host: ResolveHost,
    caller: Callable[[], str | None],
    auth: AuthCheck,
) -> None:
    """Register ``add_docs`` and ``import_status`` on ``mcp``, both behind ``auth``.

    Args:
        mcp: The server to register the tools on.
        add_library: Creates a library and queues its import.
        add_version: Queues the import of another version.
        sync_library: Re-syncs a library's branches.
        get_job: Reads one job.
        list_jobs: Lists the newest jobs the caller may read.
        list_library_jobs: Lists a library's jobs, for the import already in progress.
        find_library: The library of an ID, ``None`` when there is none the caller may read.
        resolve_library_name: The ID of the one library a name means.
        hosts: The lower-case hosts imports over MCP may use.
        resolve_host: Resolves a host name, for the address check.
        caller: The account ID of the current request.
        auth: Whether the caller may see and call the tools: may they create libraries.
    """
    adder = _Adder(
        add_library=add_library,
        add_version=add_version,
        sync_library=sync_library,
        list_library_jobs=list_library_jobs,
        find_library=find_library,
        resolve_library_name=resolve_library_name,
        hosts=frozenset(h.lower() for h in hosts),
        resolve_host=resolve_host,
    )

    @mcp.tool(
        name="add_docs",
        annotations=ToolAnnotations(
            title="Add docs to the index",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        output_schema=None,
        auth=auth,
    )
    async def add_docs_tool(
        source: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_MCP_SOURCE,
                description=(
                    "An https:// git URL, 'owner/repo' on GitHub, or an indexed library's ID "
                    "or name"
                ),
            ),
        ],
        ref: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=255,
                description=(
                    "Tag, branch or commit; empty: the default branch of a new library, a "
                    "re-sync of an indexed one"
                ),
            ),
        ] = None,
        paths: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=MAX_MCP_PATH)]] | None,
            Field(
                max_length=MAX_MCP_PATHS,
                description="Include globs for a new library; empty: its context7.json's",
            ),
        ] = None,
    ) -> ToolResult:
        """Queue the import of a library, or of a version of one, when docs are missing or stale.

        A new repository becomes a library; a ref of an indexed library becomes a version; no ref
        re-syncs its moved branches. A repeated call queues nothing and names what is there. The
        import runs in the background: follow it with `import_status`.

        Args:
            source: The repository or the library.
            ref: The version to add.
            paths: What a new library imports.

        Returns:
            The notice, then one line per version.
        """
        return _answer(await adder(source, ref, paths))

    @mcp.tool(
        name="import_status",
        annotations=ToolAnnotations(
            title="Follow imports",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        output_schema=None,
        auth=auth,
    )
    async def import_status_tool(
        job_id: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=MAX_NAME,
                description="A job ID from add_docs; empty: your latest jobs",
            ),
        ] = None,
    ) -> ToolResult:
        """Say how an import goes: its state, files done of total, and the error code if it failed.

        Search the version once it is `succeeded`.

        Args:
            job_id: The job.

        Returns:
            The notice, then one line per job.
        """
        if job_id is not None:
            return _answer([_status(await get_job(GetJobQuery(job_id=job_id)))])
        account = caller()
        page = await list_jobs(ListJobsQuery(limit=STATUS_SCAN))
        # shortcut: only the newest STATUS_SCAN jobs are looked at; filter by person in the
        # query when list_jobs learns to.
        mine = [
            job
            for job in page.jobs
            if account is not None and job.created_by is not None and job.created_by.id == account
        ][:MAX_STATUS_JOBS]
        return _answer([_status(job, with_id=True) for job in mine] or ["no jobs of yours"])


@dataclass(frozen=True, slots=True, kw_only=True)
class _Adder:
    """``add_docs``: picks ``add_library``, ``add_version`` or ``sync_library`` for a source."""

    add_library: AddLibrary
    """Creates a library and queues its import."""
    add_version: AddVersion
    """Queues the import of another version."""
    sync_library: SyncLibrary
    """Re-syncs a library's branches."""
    list_library_jobs: ListLibraryJobs
    """Lists a library's jobs."""
    find_library: Callable[[str], Awaitable[KnownLibrary | None]]
    """The library of an ID, if the caller may read one."""
    resolve_library_name: Callable[[str], Awaitable[str]]
    """The ID of the one library a name means."""
    hosts: frozenset[str]
    """The hosts imports may use."""
    resolve_host: ResolveHost
    """Resolves a host name."""

    async def __call__(self, text: str, ref: str | None, paths: list[str] | None) -> list[str]:
        """Add what the source names, as the module docstring says.

        Args:
            text: The source.
            ref: The version, if any.
            paths: Include globs for a new library, if any.

        Returns:
            One line per version.

        Raises:
            UnknownLibraryError: The source names no library the caller may read.
            LibraryExistsError: The URL's library ID is another repository's, or a library's the
                caller cannot read.
            ValidationError: Paths were given for a library that exists.
        """
        source = parse_source(text, hosts=self.hosts)
        library = source.library or await self.resolve_library_name(source.name or "")
        known = await self.find_library(library)
        if source.url is not None:
            await check_addresses(urlsplit(source.url).hostname or "", self.resolve_host)
            if known is None:
                try:
                    return await self._create(source.url, library, ref, paths or [])
                except LibraryIdTakenError:
                    # Created a moment ago (a repeated call), or a library hidden from the caller.
                    known = await self.find_library(library)
                    if known is None:
                        raise LibraryExistsError(library) from None
            if _repository(known.source_url) != _repository(source.url):
                raise LibraryExistsError(known.id)
        elif known is None:
            raise UnknownLibraryError(library)
        if paths:
            message = "paths apply to a new library only: change them in the web UI"
            raise ValidationError(message)
        if ref is None:
            return await self._sync(known)
        return await self._add_version(known, ref)

    async def _create(self, url: str, library: str, ref: str | None, paths: list[str]) -> list[str]:
        """Create the library and queue its import.

        Args:
            url: The repository.
            library: The proposed library ID.
            ref: The version, or the default branch.
            paths: Include globs; none takes those of ``context7.json``.

        Returns:
            The queued import.

        """
        added = await _respelling(
            ref,
            lambda r: self.add_library(
                AddLibraryCommand(url=url, library_id=library, ref=r, include_paths=paths)
            ),
        )
        return [_queued(added.library_id, added.ref, added.commit_sha, added.job_id)]

    async def _add_version(self, known: KnownLibrary, ref: str) -> list[str]:
        """Queue a version unless it is indexed or importing already.

        Args:
            known: The library.
            ref: The version.

        Returns:
            The queued import, the indexed version, or the import in progress.
        """
        indexed = ref if ref in known.versions else respelled(ref, known.versions)
        if indexed is not None:
            return [_indexed(known, indexed)]
        try:
            added = await _respelling(
                ref,
                lambda r: self.add_version(AddVersionCommand(library=known.id, ref=r or ref)),
            )
        except VersionExistsError as exc:
            return [_indexed(known, exc.ref)]
        except VersionImportingError as exc:
            return await self._busy(known.id, exc.ref)
        return [_queued(added.library_id, added.ref, added.commit_sha, added.job_id)]

    async def _sync(self, known: KnownLibrary) -> list[str]:
        """Re-sync the library's branches.

        Args:
            known: The library.

        Returns:
            Each version's status, or the imports in progress when it has no version yet.
        """
        try:
            synced = await self.sync_library(SyncLibraryCommand(library=known.id))
        except VersionImportingError:
            return await self._busy(known.id, None)
        if not synced.versions:
            return await self._busy(known.id, None)
        return [_synced(v) for v in synced.versions]

    async def _busy(self, library: str, ref: str | None) -> list[str]:
        """Name the imports of the library (of one ref) that are queued or running.

        Args:
            library: The library ID.
            ref: The version; ``None`` for every one.

        Returns:
            One line per import in progress.
        """
        page = await self.list_library_jobs(
            ListLibraryJobsQuery(
                library=library, state=list(ACTIVE_JOB_STATES), version=ref, limit=MAX_STATUS_JOBS
            )
        )
        return [
            f"already importing: {library}@{_ref(job.version or '')}, job {job.id} ({job.state})"
            for job in page.jobs
        ] or [f"nothing to sync: {library} has no version yet and no import in progress"]


async def _respelling[T](ref: str | None, call: Callable[[str | None], Awaitable[T]]) -> T:
    """Call with ``ref``; a ref the remote does not have is tried again without or with a ``v``.

    Args:
        ref: The ref asked for.
        call: Adds the library or the version.

    Returns:
        What the call returns.

    Raises:
        UnknownRefError: Neither spelling names a ref.
    """
    try:
        return await call(ref)
    except UnknownRefError:
        other = _other_spelling(ref)
        if other is None:
            raise
        return await call(other)


def _other_spelling(ref: str | None) -> str | None:
    """The ref without its leading ``v`` before a digit, or with one (#606).

    Args:
        ref: A ref.

    Returns:
        The other spelling; ``None`` when ``ref`` has no version number to respell.
    """
    if not ref or not (ref[0].isdigit() or (len(ref) > 1 and ref[0] in "vV" and ref[1].isdigit())):
        return None
    return f"v{ref}" if ref[0].isdigit() else ref[1:]


def _repository(url: str) -> tuple[str, str]:
    """Key a repository URL by its host and path, so two spellings of one repository match.

    Args:
        url: A repository URL.

    Returns:
        The lower-case host and path, without a trailing ``/`` or ``.git``.
    """
    try:
        host = RepositoryUrl.parse(url).hostname
    except InvalidRepositoryUrlError:
        return "", url
    path = urlsplit(url).path if "://" in url else url.partition(":")[2]  # user@host:path
    return host, "/" + path.lower().strip("/").removesuffix(".git")


def _ref(ref: str) -> str:
    """Repeat an untrusted ref name on one line, at most ``MAX_ANSWER_REF`` characters.

    Args:
        ref: The ref.

    Returns:
        The ref, whitespace collapsed and cut.
    """
    return " ".join(ref.split())[:MAX_ANSWER_REF]


def _queued(library: str, ref: str, commit_sha: str, job_id: str) -> str:
    """Say an import was queued.

    Args:
        library: The library ID.
        ref: The version.
        commit_sha: The commit it was pinned to.
        job_id: The import.

    Returns:
        The line.
    """
    return f"queued {library}@{_ref(ref)} ({commit_sha[:7]}), job {job_id}"


def _indexed(known: KnownLibrary, ref: str) -> str:
    """Say a version is indexed already.

    Args:
        known: The library.
        ref: The version.

    Returns:
        The line.
    """
    sha = known.versions.get(ref, "")[:7]
    return f"already indexed: {known.id}@{_ref(ref)}" + (f" ({sha})" if sha else "")


def _synced(version: SyncedVersion) -> str:
    """One line for a version a re-sync looked at: its status, its job, the error code.

    Args:
        version: What the re-sync did with it.

    Returns:
        The line.
    """
    parts = [f"{_ref(version.ref)}: {version.status}"]
    if version.job_id and version.status is not SyncStatus.UP_TO_DATE:
        parts.append(f"job {version.job_id}")
    if version.error_code:
        parts.append(version.error_code)
    return ", ".join(parts)


def _status(job: JobSummary, *, with_id: bool = False) -> str:
    """One line for a job: state, library and version, files done of total, the error code.

    Args:
        job: The job.
        with_id: Name the job too (in a list).

    Returns:
        The line.
    """
    target = job.library + (f"@{_ref(job.version)}" if job.version else "")
    parts = [f"{job.state}: {target}", f"files {job.done}/{job.total}"]
    if job.error_code:
        parts.append(job.error_code)
    if with_id:
        parts.append(f"job {job.id}")
    return ", ".join(parts)


def _answer(lines: Sequence[str]) -> ToolResult:
    """The notice, then the lines.

    Args:
        lines: The answer.

    Returns:
        The tool result.
    """
    return ToolResult(
        content=[
            TextContent(type="text", text=NOTICE),
            TextContent(type="text", text="\n".join(lines)),
        ]
    )
