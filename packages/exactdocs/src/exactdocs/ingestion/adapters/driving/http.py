"""REST adapter for ingestion (consumed by the web UI)."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddedVersion,
    AddLibraryCommand,
    AddVersionBody,
    AddVersionCommand,
    CheckedRepository,
    CheckRepositoryCommand,
    GetJobQuery,
    GetLibraryAccessQuery,
    JobList,
    JobSummary,
    LatestJobs,
    LibraryAccess,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    PreviewRepositoryCommand,
    RemovalResult,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RepositoryPreview,
    RepositoryRefs,
    SyncedLibrary,
    SyncLibraryCommand,
)
from exactdocs.ingestion.models import SyncStatus
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    AddVersion,
    CheckRepository,
    GetJob,
    GetLibraryAccess,
    ListLatestJobs,
    ListLibraryJobs,
    ListRepositoryRefs,
    PreviewRepository,
    RemoveLibrary,
    RemoveVersion,
    SyncLibrary,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT


async def _session_for(
    require_session: Callable[[Request], Awaitable[object]], credential: object, request: Request
) -> None:
    """Demand a signed-in session when the request carries a credential."""
    if credential is not None:
        await require_session(request)


def build_router(
    *,
    get_job: GetJob,
    get_library_access: GetLibraryAccess,
    list_latest_jobs: ListLatestJobs,
    list_library_jobs: ListLibraryJobs,
    check_repository: CheckRepository,
    list_repository_refs: ListRepositoryRefs,
    preview_repository: PreviewRepository,
    add_library: AddLibrary,
    add_version: AddVersion,
    remove_version: RemoveVersion,
    remove_library: RemoveLibrary,
    sync_library: SyncLibrary,
    require_session: Callable[[Request], Awaitable[object]],
) -> APIRouter:
    """Expose adding a library, the repository checks and the job read side.

    ``require_session`` refuses (401) a request that is not signed in with a session cookie. A
    request that carries a ``credential`` needs one: an API token (an MCP client's, say) may
    read and add public docs, but must not set or replace what is used to read a private repo.
    """
    router = APIRouter(tags=["ingestion"])

    @router.post("/repositories/check")
    async def check(command: CheckRepositoryCommand, request: Request) -> CheckedRepository:
        """Check a git URL (nothing is saved); the URL is never echoed back.

        A `credential` needs a signed-in session, not an API token.
        """
        await _session_for(require_session, command.credential, request)
        return await check_repository(command)

    @router.get("/repositories/refs")
    async def list_refs(
        url: Annotated[str, Query(min_length=1, max_length=2048)],
    ) -> RepositoryRefs:
        """List the tags and branches of a repository (the URL is never echoed back)."""
        return await list_repository_refs(ListRepositoryRefsQuery(url=url))

    @router.post("/repositories/preview")
    async def preview(command: PreviewRepositoryCommand, request: Request) -> RepositoryPreview:
        """List the articles an import of this URL, ref and patterns would take (a dry run).

        Only the commit's tree is fetched, no file content, and nothing is stored. `files` has
        at most 1000 paths; `total` counts all matches and `truncated` says they were cut. Paths
        are untrusted text. A `credential` needs a signed-in session, not an API token.
        """
        await _session_for(require_session, command.credential, request)
        return await preview_repository(command)

    @router.post("/libraries", status_code=status.HTTP_201_CREATED)
    async def add(command: AddLibraryCommand, request: Request, response: Response) -> AddedLibrary:
        """Create a library, pin its ref to a commit and queue the import (see the job ID).

        `Location` is the new library.
        """
        await _session_for(require_session, command.credential, request)
        added = await add_library(command)
        response.headers["Location"] = f"{request.url.path.rstrip('/')}{added.library_id}"
        return added

    @router.post(
        "/libraries/{owner}/{repo}/versions",
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            status.HTTP_202_ACCEPTED: {
                "headers": {
                    "Location": {
                        "description": "The import job: `/api/v1/jobs/{job_id}`.",
                        "schema": {"type": "string"},
                    }
                }
            }
        },
    )
    async def add_another_version(
        owner: str, repo: str, body: AddVersionBody, request: Request, response: Response
    ) -> AddedVersion:
        """Import another version of the library with the library's own settings.

        The import is queued: `Location` is its job. A ref the library already has is a 409.
        """
        await _session_for(require_session, body.credential, request)
        added = await add_version(
            AddVersionCommand(
                library=f"/{owner}/{repo}".lower(), ref=body.ref, credential=body.credential
            )
        )
        response.headers["Location"] = request.url_for("get_job", job_id=added.job_id).path
        return added

    router.include_router(_removal_router(remove_version, remove_library))

    @router.post(
        "/libraries/{owner}/{repo}/sync",
        responses={
            status.HTTP_200_OK: {"description": "Nothing was queued: every version is up to date."},
            status.HTTP_202_ACCEPTED: {
                "description": "Imports of the moved branches are queued.",
                "headers": {
                    "Location": {
                        "description": (
                            "The import job (`/api/v1/jobs/{job_id}`) when one was queued, else "
                            "the library's jobs (`/api/v1/libraries/{owner}/{repo}/jobs`)."
                        ),
                        "schema": {"type": "string"},
                    }
                },
            },
        },
    )
    async def sync(owner: str, repo: str, request: Request, response: Response) -> SyncedLibrary:
        """Re-sync the library's branch versions: import the ones whose tip moved.

        Only changed articles are re-chunked. Tags and commits are never moved (`pinned`). Read
        each version's `status`, not the HTTP status, for what happened to it: `up_to_date`,
        `queued`, `importing` (an import of it is already queued or running), `failed` (the
        branch is gone upstream, or its import could not be queued). Queued imports answer 202,
        anything else 200. 409 `version_importing` when a running import left nothing queued;
        422 with the remote's error code when the remote cannot be read (deliberate, E9-02 owns
        distinct codes): the failed jobs recorded for it are named in the message.
        """
        synced = await sync_library(SyncLibraryCommand(library=f"/{owner}/{repo}".lower()))
        queued = [v.job_id for v in synced.versions if v.status is SyncStatus.QUEUED]
        if queued:
            response.status_code = status.HTTP_202_ACCEPTED
            response.headers["Location"] = (
                request.url_for("get_job", job_id=queued[0]).path
                if len(queued) == 1
                else request.url_for("list_library_jobs", owner=owner, repo=repo).path
            )
        return synced

    router.include_router(
        _read_router(get_job, list_latest_jobs, list_library_jobs, get_library_access)
    )

    return router


def _read_router(
    get_job: GetJob,
    list_latest_jobs: ListLatestJobs,
    list_library_jobs: ListLibraryJobs,
    get_library_access: GetLibraryAccess,
) -> APIRouter:
    """Build the GET routes: jobs and whether a library is private."""
    router = APIRouter(tags=["ingestion"])

    @router.get("/jobs/latest", name="list_latest_jobs")
    async def latest() -> LatestJobs:
        """List the newest job of every library version, in one call (no per-library requests)."""
        return await list_latest_jobs()

    @router.get("/jobs/{job_id}", name="get_job")
    async def get_one(job_id: str) -> JobSummary:
        return await get_job(GetJobQuery(job_id=job_id))

    @router.get("/libraries/{owner}/{repo}/access", name="get_library_access")
    async def access(owner: str, repo: str) -> LibraryAccess:
        """Say whether the library's repository is private (it has a stored credential)."""
        return await get_library_access(GetLibraryAccessQuery(library=f"/{owner}/{repo}"))

    @router.get("/libraries/{owner}/{repo}/jobs", name="list_library_jobs")
    async def list_for_library(
        owner: str,
        repo: str,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> JobList:
        return await list_library_jobs(
            ListLibraryJobsQuery(library=f"/{owner}/{repo}", limit=limit, cursor=cursor)
        )

    return router


def _removal_router(remove_version: RemoveVersion, remove_library: RemoveLibrary) -> APIRouter:
    """Build the DELETE routes for a version and for a whole library."""
    router = APIRouter(tags=["ingestion"])

    @router.delete("/libraries/{owner}/{repo}", name="remove_library")
    async def remove_whole_library(owner: str, repo: str) -> RemovalResult:
        """Remove a library and all its versions at once; a job frees the content.

        Refused with 409 `import_in_progress` while an import of the library is queued or running.
        """
        return await remove_library(RemoveLibraryCommand(library=f"/{owner}/{repo}"))

    # The ref comes last because it may contain slashes (`release/1.4`), as in the catalog's GET.
    @router.delete("/libraries/{owner}/{repo}/versions/{ref:path}", name="remove_version")
    async def remove_one_version(owner: str, repo: str, ref: str) -> RemovalResult:
        """Remove one version everywhere at once; a job frees the content nothing else uses.

        Refused with 409 `import_in_progress` while an import of that version is queued or
        running. Removing the default version moves the default; removing the last leaves the
        library without versions.
        """
        if ref.endswith("/"):  # `/versions/v1.4.0/` is another URL, not a malformed ref
            raise HTTPException(status_code=404)
        return await remove_version(RemoveVersionCommand(library=f"/{owner}/{repo}", ref=ref))

    return router
