"""REST adapter for ingestion jobs (consumed by the web UI)."""

from typing import Annotated

from fastapi import APIRouter, Query

from exactdocs.ingestion.dtos import GetJobQuery, JobList, JobSummary, ListLibraryJobsQuery
from exactdocs.ingestion.ports.driving import GetJob, ListLibraryJobs
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT


def build_router(*, get_job: GetJob, list_library_jobs: ListLibraryJobs) -> APIRouter:
    """Expose the job read side: one job, and the jobs of a library."""
    router = APIRouter(tags=["ingestion"])

    @router.get("/jobs/{job_id}")
    async def get_one(job_id: str) -> JobSummary:
        return await get_job(GetJobQuery(job_id=job_id))

    @router.get("/libraries/{owner}/{repo}/jobs")
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
