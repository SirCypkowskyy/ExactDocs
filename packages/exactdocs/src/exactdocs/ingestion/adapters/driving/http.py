"""REST adapter for ingestion (consumed by the web UI)."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddLibraryCommand,
    CheckedRepository,
    CheckRepositoryCommand,
    GetJobQuery,
    JobList,
    JobSummary,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    RepositoryRefs,
)
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    CheckRepository,
    GetJob,
    ListLibraryJobs,
    ListRepositoryRefs,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT


def build_router(
    *,
    get_job: GetJob,
    list_library_jobs: ListLibraryJobs,
    check_repository: CheckRepository,
    list_repository_refs: ListRepositoryRefs,
    add_library: AddLibrary,
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
    async def add(command: AddLibraryCommand) -> AddedLibrary:
        """Create a library, pin its ref to a commit and queue the import (see the job ID)."""
        return await add_library(command)

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
