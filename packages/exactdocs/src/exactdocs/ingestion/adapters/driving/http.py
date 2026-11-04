"""REST adapter for ingestion (consumed by the web UI)."""

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
    JobList,
    JobSummary,
    LatestJobs,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    RemovalResult,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RepositoryRefs,
)
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    AddVersion,
    CheckRepository,
    GetJob,
    ListLatestJobs,
    ListLibraryJobs,
    ListRepositoryRefs,
    RemoveLibrary,
    RemoveVersion,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT


def build_router(
    *,
    get_job: GetJob,
    list_latest_jobs: ListLatestJobs,
    list_library_jobs: ListLibraryJobs,
    check_repository: CheckRepository,
    list_repository_refs: ListRepositoryRefs,
    add_library: AddLibrary,
    add_version: AddVersion,
    remove_version: RemoveVersion,
    remove_library: RemoveLibrary,
) -> APIRouter:
    """Expose adding a library, the repository checks and the job read side."""
    router = APIRouter(tags=["ingestion"])

    @router.post("/repositories/check")
    async def check(command: CheckRepositoryCommand) -> CheckedRepository:
        """Check a git URL (nothing is saved); the URL is never echoed back."""
        return await check_repository(command)

    @router.get("/repositories/refs")
    async def list_refs(
        url: Annotated[str, Query(min_length=1, max_length=2048)],
    ) -> RepositoryRefs:
        """List the tags and branches of a repository (the URL is never echoed back)."""
        return await list_repository_refs(ListRepositoryRefsQuery(url=url))

    @router.post("/libraries", status_code=status.HTTP_201_CREATED)
    async def add(command: AddLibraryCommand, request: Request, response: Response) -> AddedLibrary:
        """Create a library, pin its ref to a commit and queue the import (see the job ID).

        `Location` is the new library.
        """
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
        added = await add_version(
            AddVersionCommand(library=f"/{owner}/{repo}".lower(), ref=body.ref)
        )
        response.headers["Location"] = request.url_for("get_job", job_id=added.job_id).path
        return added

    router.include_router(_removal_router(remove_version, remove_library))

    @router.get("/jobs/latest", name="list_latest_jobs")
    async def latest() -> LatestJobs:
        """List the newest job of every library version, in one call (no per-library requests)."""
        return await list_latest_jobs()

    @router.get("/jobs/{job_id}", name="get_job")
    async def get_one(job_id: str) -> JobSummary:
        return await get_job(GetJobQuery(job_id=job_id))

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
