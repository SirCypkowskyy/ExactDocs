"""REST adapter for ingestion (consumed by the web UI)."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from exactdocs.ingestion.constants import MAX_WEBHOOK_BYTES, SET_AUTO_SYNC_DESCRIPTION
from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddedVersion,
    AddLibraryCommand,
    AddVersionBody,
    AddVersionCommand,
    AutoSyncIn,
    AutoSyncOut,
    CheckedRepository,
    CheckRepositoryCommand,
    DisableAutoSyncCommand,
    GetAutoSyncQuery,
    GetJobQuery,
    GetLibraryAccessQuery,
    JobList,
    JobSummary,
    LatestJobs,
    LibraryAccess,
    LibrarySettingsIn,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    ManualTagsIn,
    PreviewRepositoryCommand,
    ReceiveWebhookCommand,
    ReimportedVersion,
    ReimportVersionBody,
    ReimportVersionCommand,
    RemovalResult,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RepositoryPreview,
    RepositoryRefs,
    SetAutoSyncCommand,
    SyncedLibrary,
    SyncLibraryCommand,
    TagArticleCommand,
    TaggedArticle,
    UpdatedLibrarySettings,
    UpdateLibrarySettingsCommand,
    WebhookCreated,
    WebhookOut,
    WebhookQuery,
    WebhookReceipt,
)
from exactdocs.ingestion.models import SyncStatus
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    AddVersion,
    CheckRepository,
    DisableAutoSync,
    DisableWebhook,
    GetAutoSync,
    GetJob,
    GetLibraryAccess,
    GetWebhook,
    ListLatestJobs,
    ListLibraryJobs,
    ListRepositoryRefs,
    PreviewRepository,
    ReceiveWebhook,
    ReimportVersion,
    RemoveLibrary,
    RemoveVersion,
    SetAutoSync,
    SetWebhook,
    SyncLibrary,
    TagArticle,
    UpdateLibrarySettings,
)
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, MAX_PATH


async def _session_for(
    require_session: Callable[[Request], Awaitable[object]], credential: object, request: Request
) -> None:
    """Demand a signed-in session when the request carries a credential.

    Args:
        require_session: Refuses (401) a request without a session cookie.
        credential: The credential the request carries, if any.
        request: The HTTP request.
    """
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
    reimport_version: ReimportVersion,
    tag_article: TagArticle,
    update_library_settings: UpdateLibrarySettings,
    require_session: Callable[[Request], Awaitable[object]],
) -> APIRouter:
    """Expose adding a library, the repository checks and the job read side.

    ``require_session`` refuses (401) a request that is not signed in with a session cookie. A
    request that carries a ``credential`` needs one: an API token (an MCP client's, say) may
    read and add public docs, but must not set or replace what is used to read a private repo.

    Args:
        get_job: Reads one job.
        get_library_access: Says whether a library has a stored credential.
        list_latest_jobs: Lists the newest job of every (library, version).
        list_library_jobs: Lists a page of a library's jobs.
        check_repository: Validates a git URL.
        list_repository_refs: Lists a repository's branches and tags.
        preview_repository: Lists the files an import would take.
        add_library: Creates a library and queues its import.
        add_version: Pins another ref of a library and queues its import.
        remove_version: Removes a version.
        remove_library: Removes a library.
        sync_library: Re-syncs a library's branch versions.
        reimport_version: Re-imports a tag version that moved upstream.
        tag_article: Sets an article path's manual tags.
        update_library_settings: Replaces a library's settings.
        require_session: Refuses (401) a request without a session cookie.

    Returns:
        The router, with the job, removal, manual-tag and settings routes included.
    """
    router = APIRouter(tags=["ingestion"])
    router.include_router(_manual_tags_router(tag_article))
    router.include_router(_settings_router(update_library_settings))

    @router.post("/repositories/check")
    async def check(command: CheckRepositoryCommand, request: Request) -> CheckedRepository:
        """Check a git URL (nothing is saved); the URL is never echoed back.

        A `credential` needs a signed-in session, not an API token.

        Args:
            command: The URL and, optionally, the library ID and credential.
            request: The HTTP request, for the caller's session.

        Returns:
            What a new library from the repository would look like.
        """
        await _session_for(require_session, command.credential, request)
        return await check_repository(command)

    @router.get("/repositories/refs")
    async def list_refs(
        url: Annotated[str, Query(min_length=1, max_length=2048)],
    ) -> RepositoryRefs:
        """List the tags and branches of a public repository (the URL is never echoed back).

        A private repository uses `POST /repositories/refs`: a credential never goes in a URL.

        Args:
            url: The repository URL.

        Returns:
            The repository's refs.
        """
        return await list_repository_refs(ListRepositoryRefsQuery(url=url))

    @router.post("/repositories/refs")
    async def list_refs_with_credential(
        query: ListRepositoryRefsQuery, request: Request
    ) -> RepositoryRefs:
        """List the tags and branches of a repository, private ones with a `credential`.

        The same answer as `GET /repositories/refs`; the body keeps the credential out of URLs
        and logs, and nothing is stored. A `credential` needs a signed-in session, not an API
        token.

        Args:
            query: The repository URL and, for a private one, the credential.
            request: The HTTP request, for the caller's session.

        Returns:
            The repository's refs.
        """
        await _session_for(require_session, query.credential, request)
        return await list_repository_refs(query)

    @router.post(
        "/repositories/preview",
        responses={
            # The envelope schema lives in bootstrap (every /api/v1 route documents it): only
            # its name is referenced here, the domain does not import bootstrap.
            status.HTTP_429_TOO_MANY_REQUESTS: {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
                },
                "description": "Every preview slot is taken (`preview_busy`); try again shortly.",
                "headers": {
                    "Retry-After": {
                        "description": "Seconds to wait before trying again.",
                        "schema": {"type": "integer"},
                    }
                },
            }
        },
    )
    async def preview(command: PreviewRepositoryCommand, request: Request) -> RepositoryPreview:
        """List the articles an import of this URL, ref and patterns would take (a dry run).

        Only the commit's tree is fetched, plus the root `context7.json` alone (no other file
        content), and nothing is stored. Without paths, the file's folders and exclusions are
        applied (see `include_paths`, `exclude_paths`, `context7`). `files` lists the first
        matching paths; `total` counts all matches and `truncated` says they were cut. Paths are
        untrusted text. A `credential` needs a signed-in session, not an API token.

        Args:
            command: The URL, the ref and the paths.
            request: The HTTP request, for the caller's session.

        Returns:
            The files the import would take.
        """
        await _session_for(require_session, command.credential, request)
        return await preview_repository(command)

    @router.post(
        "/libraries",
        status_code=status.HTTP_201_CREATED,
        responses={
            status.HTTP_429_TOO_MANY_REQUESTS: {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
                },
                "description": "Sent without paths while every preview slot is taken, so the "
                "repository's `context7.json` could not be read (`preview_busy`); nothing is "
                "stored. Try again shortly.",
                "headers": {
                    "Retry-After": {
                        "description": "Seconds to wait before trying again.",
                        "schema": {"type": "integer"},
                    }
                },
            }
        },
    )
    async def add(command: AddLibraryCommand, request: Request, response: Response) -> AddedLibrary:
        """Create a library, pin its ref to a commit and queue the import (see the job ID).

        `Location` is the new library. Without paths, those of the repository's `context7.json`
        are taken; if every preview slot stays busy so it cannot be read, the answer is 429
        `preview_busy` and nothing is stored.

        Args:
            command: The repository, the ref, the paths and the settings.
            request: The HTTP request, for the caller's session and the `Location`.
            response: The HTTP response, for the `Location` header.

        Returns:
            The new library and its queued import.
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

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            body: The ref and, optionally, a credential.
            request: The HTTP request, for the caller's session and the job's URL.
            response: The HTTP response, for the `Location` header.

        Returns:
            The pinned version and its queued import.
        """
        await _session_for(require_session, body.credential, request)
        added = await add_version(
            AddVersionCommand(
                library=f"/{owner}/{repo}".lower(), ref=body.ref, credential=body.credential
            )
        )
        response.headers["Location"] = request.url_for("get_job", job_id=added.job_id).path
        return added

    # Not `/versions/{ref}/reimport`: a ref may hold slashes, so nothing can follow it in a path.
    @router.post(
        "/libraries/{owner}/{repo}/versions/reimport",
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
    async def reimport(
        owner: str, repo: str, body: ReimportVersionBody, request: Request, response: Response
    ) -> ReimportedVersion:
        """Re-import a tag version that moved upstream, at the commit the tag names now.

        This is the confirmation a sync's `tag_moved` asks for: the tag is checked again and its
        import queued (`Location` is the job); the version keeps serving the old commit until the
        import has finished, and its error clears with it. 404 for an unknown library or version,
        422 `not_a_tag` for a branch (a sync follows it) or a commit, 409 `tag_not_moved` when the
        tag still names the commit the version serves, 422 `ref_deleted` when the tag is gone
        upstream, 409 `version_importing` when an import of it is queued or running, and the 422
        codes of reading a repository (`repository_unreachable`, `credentials_required`, ...).

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            body: The tag version.
            request: The HTTP request, for the job's URL.
            response: The HTTP response, for the `Location` header.

        Returns:
            The commits the version moves between and the queued import.
        """
        reimported = await reimport_version(
            ReimportVersionCommand(library=f"/{owner}/{repo}".lower(), ref=body.ref)
        )
        response.headers["Location"] = request.url_for("get_job", job_id=reimported.job_id).path
        return reimported

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

        Only changed articles are re-chunked. Commits are never checked and tags never moved:
        a tag that still names its commit is `pinned`. Read each version's `status`, not the HTTP
        status, for what happened to it: `up_to_date`, `queued`, `importing` (an import of it is
        already queued or running), `failed` with an `error_code`: `ref_deleted` (the branch or
        tag is gone upstream), `tag_moved` (the tag names another commit now; it is reported,
        and re-imported only when confirmed with `versions/reimport`) or `unexpected` (its
        import could not be queued). Every version keeps what it served. Queued imports answer
        202, anything else 200. 409 `version_importing` when a running import left nothing
        queued. 422 when the remote cannot be read, mostly `repo_unreachable` (deleted, private,
        moved or down; also a login prompt for a library without a credential) or `auth_failed`
        (the credential was refused or cannot be read).
        Other codes are possible: `host_key_changed` (the SSH host key changed, possibly a man
        in the middle) and `git_not_installed`; any 422 means nothing was fetched. The failed
        jobs recorded for it are named in the message.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            request: The HTTP request, for the jobs' URLs.
            response: The HTTP response, for the status and the `Location` header.

        Returns:
            What happened to each version.
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
    """Build the GET routes: jobs and whether a library is private.

    Args:
        get_job: Reads one job.
        list_latest_jobs: Lists the newest job of every (library, version).
        list_library_jobs: Lists a page of a library's jobs.
        get_library_access: Says whether a library has a stored credential.

    Returns:
        The router.
    """
    router = APIRouter(tags=["ingestion"])

    @router.get("/jobs/latest", name="list_latest_jobs")
    async def latest() -> LatestJobs:
        """List the newest job of every library version, in one call (no per-library requests).

        Returns:
            The newest job of each (library, version).
        """
        return await list_latest_jobs()

    @router.get("/jobs/{job_id}", name="get_job")
    async def get_one(job_id: str) -> JobSummary:
        """Read a job: its state, its progress and the problems of its files.

        Args:
            job_id: The job ID.

        Returns:
            The job.
        """
        return await get_job(GetJobQuery(job_id=job_id))

    @router.get("/libraries/{owner}/{repo}/access", name="get_library_access")
    async def access(owner: str, repo: str) -> LibraryAccess:
        """Say whether the library's repository is private (it has a stored credential).

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.

        Returns:
            Whether the library is private.
        """
        return await get_library_access(GetLibraryAccessQuery(library=f"/{owner}/{repo}"))

    @router.get("/libraries/{owner}/{repo}/jobs", name="list_library_jobs")
    async def list_for_library(
        owner: str,
        repo: str,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> JobList:
        """List the library's jobs, newest first, a page at a time.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            limit: How many jobs the page holds at most.
            cursor: The `next_cursor` of the previous page; none for the first page.

        Returns:
            The page and the cursor of the next one.
        """
        return await list_library_jobs(
            ListLibraryJobsQuery(library=f"/{owner}/{repo}", limit=limit, cursor=cursor)
        )

    return router


def _removal_router(remove_version: RemoveVersion, remove_library: RemoveLibrary) -> APIRouter:
    """Build the DELETE routes for a version and for a whole library.

    Args:
        remove_version: Removes a version.
        remove_library: Removes a library.

    Returns:
        The router.
    """
    router = APIRouter(tags=["ingestion"])

    @router.delete("/libraries/{owner}/{repo}", name="remove_library")
    async def remove_whole_library(owner: str, repo: str) -> RemovalResult:
        """Remove a library and all its versions at once; a job frees the content.

        Refused with 409 `import_in_progress` while an import of the library is queued or running.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.

        Returns:
            What was removed and the job that frees the content.
        """
        return await remove_library(RemoveLibraryCommand(library=f"/{owner}/{repo}"))

    # The ref comes last because it may contain slashes (`release/1.4`), as in the catalog's GET.
    @router.delete("/libraries/{owner}/{repo}/versions/{ref:path}", name="remove_version")
    async def remove_one_version(owner: str, repo: str, ref: str) -> RemovalResult:
        """Remove one version everywhere at once; a job frees the content nothing else uses.

        Refused with 409 `import_in_progress` while an import of that version is queued or
        running. Removing the default version moves the default; removing the last leaves the
        library without versions.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            ref: The version's ref; it may hold slashes.

        Returns:
            What was removed, the default version now and the job that frees the content.

        Raises:
            HTTPException: 404 for a ref that ends with a slash: another URL.
        """
        if ref.endswith("/"):  # `/versions/v1.4.0/` is another URL, not a malformed ref
            raise HTTPException(status_code=404)
        return await remove_version(RemoveVersionCommand(library=f"/{owner}/{repo}", ref=ref))

    return router


_ArticlePath = Annotated[
    str,
    Query(
        min_length=1,
        max_length=MAX_PATH,
        description="An article path, as in any version; the articles renamed from it follow.",
    ),
]


def _manual_tags_router(tag_article: TagArticle) -> APIRouter:
    """Build the routes that set and remove the tags users give an article path by hand.

    Args:
        tag_article: Sets an article path's manual tags.

    Returns:
        The router.
    """
    router = APIRouter(tags=["ingestion"])

    # Next to the catalog's `GET .../tags` (a version's tag counts): these write the library's.
    @router.put("/libraries/{owner}/{repo}/tags", name="set_manual_tags")
    async def set_path_tags(
        owner: str, repo: str, path: _ArticlePath, body: ManualTagsIn
    ) -> TaggedArticle:
        """Tag an article path by hand, for every version of the library.

        The tags replace the path's manual tags and combine with the imported ones (front matter,
        path rules) of the article at `path` in every version, and of the article git saw it
        renamed to in later versions. Listings, tag counts and search see them on return; nothing
        is imported or chunked again.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            path: The article's path.
            body: The new manual tags.

        Returns:
            The path with its manual tags now.
        """
        return await tag_article(
            TagArticleCommand(library=f"/{owner}/{repo}", path=path, tags=body.tags)
        )

    @router.delete(
        "/libraries/{owner}/{repo}/tags",
        name="remove_manual_tags",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_path_tags(owner: str, repo: str, path: _ArticlePath) -> None:
        """Remove every manual tag of an article path; the imported tags stay.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            path: The article's path.
        """
        await tag_article(TagArticleCommand(library=f"/{owner}/{repo}", path=path, tags=[]))

    return router


def build_auto_sync_router(
    *, get_auto_sync: GetAutoSync, set_auto_sync: SetAutoSync, disable_auto_sync: DisableAutoSync
) -> APIRouter:
    """Build the routes of a library's scheduled check (SYNC-02).

    Args:
        get_auto_sync: Reads a library's scheduled check.
        set_auto_sync: Turns it on, or changes it.
        disable_auto_sync: Turns it off.

    Returns:
        The router.
    """
    router = APIRouter(tags=["ingestion"])
    path = "/libraries/{owner}/{repo}/auto-sync"

    @router.get(path, name="get_auto_sync")
    async def get_schedule(owner: str, repo: str) -> AutoSyncOut:
        """Say how the library is checked on its own (`enabled` false: never) and how it went.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.

        Returns:
            The library's schedule.
        """
        return await get_auto_sync(GetAutoSyncQuery(library=f"/{owner}/{repo}"))

    @router.put(path, name="set_auto_sync", description=SET_AUTO_SYNC_DESCRIPTION)
    async def set_schedule(owner: str, repo: str, body: AutoSyncIn) -> AutoSyncOut:
        """Check the library on its own; the route's description is ``SET_AUTO_SYNC_DESCRIPTION``.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            body: The whole schedule.

        Returns:
            The schedule as stored.
        """
        return await set_auto_sync(
            SetAutoSyncCommand(library=f"/{owner}/{repo}", **body.model_dump())
        )

    @router.delete(path, name="disable_auto_sync")
    async def disable_schedule(owner: str, repo: str) -> AutoSyncOut:
        """Stop checking the library on its own; every version, `auto` ones too, stays.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.

        Returns:
            The schedule, now off.
        """
        return await disable_auto_sync(DisableAutoSyncCommand(library=f"/{owner}/{repo}"))

    return router


def _settings_router(update_library_settings: UpdateLibrarySettings) -> APIRouter:
    """Build the route that edits a library's paths, tag rules and chunking.

    Args:
        update_library_settings: Replaces a library's settings.

    Returns:
        The router.
    """
    router = APIRouter(tags=["ingestion"])

    @router.put(
        "/libraries/{owner}/{repo}/settings",
        name="update_library_settings",
        responses={
            status.HTTP_200_OK: {
                "description": "Nothing changed and nothing failed: nothing is re-processed."
            },
            status.HTTP_202_ACCEPTED: {
                "description": "Stored; a job re-processes every version.",
                "headers": {
                    "Location": {
                        "description": "The job: `/api/v1/jobs/{job_id}`.",
                        "schema": {"type": "string"},
                    }
                },
            },
        },
    )
    async def update_settings(
        owner: str, repo: str, body: LibrarySettingsIn, request: Request, response: Response
    ) -> UpdatedLibrarySettings:
        """Replace the library's paths, tag rules and chunking; every version is then re-processed.

        Send the whole set of paths and tag rules (`GET /libraries/{owner}/{repo}` has the current
        `settings`): what is left out is cleared. `chunking` left out (or null) keeps the stored
        one. Changed paths queue a `reprocess`
        job that fetches every version again at the commit it serves (a branch is not synced)
        and re-imports it; a changed chunking queues a `rechunk` job that cuts the stored
        articles again (and re-tags them), fetching nothing unless a version was stored by an
        older parser (that one is re-imported); only tag rules changed queue a `retag` job that
        re-tags the stored articles, fetching nothing. Each
        version keeps serving its old state until its new one is complete, then switches at
        once (after a `retag`, search's tag filters follow the listings a moment later); one
        that fails keeps the old state and the job fails naming it. Sending the same settings
        again re-runs that failed job. Answers 202 with the job in `Location`, or 200 with no
        job when the settings are unchanged and the last re-processing did not fail (or there
        is no version yet: imports to come use them). 422 for an invalid pattern, tag or chunking
        setting (nothing is stored), 404 for an unknown library.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            body: The whole set of paths and tag rules, and the chunking.
            request: The HTTP request, for the job's URL.
            response: The HTTP response, for the status and the `Location` header.

        Returns:
            The settings as stored and the job, if one was queued.
        """
        updated = await update_library_settings(
            UpdateLibrarySettingsCommand(
                library=f"/{owner}/{repo}",
                include_paths=body.include_paths,
                exclude_paths=body.exclude_paths,
                tag_rules=body.tag_rules,
                chunking=body.chunking,
            )
        )
        if updated.job_id is not None:
            response.status_code = status.HTTP_202_ACCEPTED
            response.headers["Location"] = request.url_for("get_job", job_id=updated.job_id).path
        return updated

    return router


async def _capped_body(request: Request) -> bytes:
    """Read the raw body, refusing (413) one above ``MAX_WEBHOOK_BYTES`` before reading it all.

    Args:
        request: The HTTP request.

    Returns:
        The body, exactly as sent.

    Raises:
        HTTPException: 413 when the body (or its announced length) is too large.
    """
    detail = f"a webhook body is at most {MAX_WEBHOOK_BYTES} bytes"
    announced = request.headers.get("content-length", "")
    if announced.isdigit() and int(announced) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail)
    return bytes(body)


def build_webhook_router(*, receive_webhook: ReceiveWebhook) -> APIRouter:
    """Build the route forges send their pushes to; it needs no caller, only the secret.

    Args:
        receive_webhook: Verifies a delivery and queues its ``push`` jobs.

    Returns:
        The router.
    """
    router = APIRouter(tags=["ingestion"])

    @router.post(
        "/webhooks/{owner}/{repo}",
        name="receive_webhook",
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            status.HTTP_413_CONTENT_TOO_LARGE: {
                "description": f"The body is larger than {MAX_WEBHOOK_BYTES} bytes."
            }
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "description": "The forge's push payload, signed as it was sent.",
                "content": {"application/json": {"schema": {"type": "object"}}},
            }
        },
    )
    async def receive(owner: str, repo: str, request: Request) -> WebhookReceipt:
        """Receive a push from GitHub, GitLab or Bitbucket; the sync runs later, as a job.

        Set this URL in the forge's webhook settings, with the secret from `PUT
        /libraries/{owner}/{repo}/webhook`, for push events (and tag pushes). The signature is
        checked over the raw body: GitHub's `X-Hub-Signature-256`, Bitbucket's
        `X-Hub-Signature` (both `sha256=`, HMAC-SHA256), GitLab's `X-Gitlab-Token`. Every
        refusal is the same 401 `invalid_signature`: no or a wrong signature, an unknown forge, a
        library without a webhook, or no such library. 413 above the size cap, 400
        `missing_delivery_id` for a signed delivery without a delivery ID. A push to a branch
        version queues a sync of that branch, a tag the library's auto-sync `tag_pattern`
        matches queues its auto-import: 202 `queued`. A delivery seen before answers 202
        `duplicate`, anything else (an untracked branch, a tag without auto-import, a ping) 202
        `ignored`. Only ref names are read from the payload: the job asks the repository itself.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            request: The HTTP request: its headers and raw body.

        Returns:
            What the delivery led to.
        """
        body = await _capped_body(request)
        return await receive_webhook(
            ReceiveWebhookCommand(
                library=f"/{owner}/{repo}", headers=dict(request.headers.items()), body=body
            )
        )

    return router


def build_webhook_settings_router(
    *,
    get_webhook: GetWebhook,
    set_webhook: SetWebhook,
    disable_webhook: DisableWebhook,
    require_operator: Callable[[Request], Awaitable[object]],
) -> APIRouter:
    """Build the routes that turn a library's push webhook on, rotate and off (operators only).

    Every route needs an operator signed in with a session, not an API token: the answer of
    `PUT` holds a secret.

    Args:
        get_webhook: Says whether a library's webhook is on.
        set_webhook: Creates or rotates the secret.
        disable_webhook: Forgets the secret.
        require_operator: Refuses a request without a session cookie (401) or of a caller who
            is not an operator (403).

    Returns:
        The router.
    """
    router = APIRouter(tags=["ingestion"], dependencies=[Depends(require_operator)])
    path = "/libraries/{owner}/{repo}/webhook"

    def url_of(request: Request, owner: str, repo: str) -> str:
        """Return where the forge sends this library's pushes.

        Args:
            request: The HTTP request, for the server's address.
            owner: The library ID's owner.
            repo: The library ID's repository name.

        Returns:
            The absolute URL of the receiving route.
        """
        return str(request.url_for("receive_webhook", owner=owner.lower(), repo=repo.lower()))

    @router.get(path, name="get_webhook")
    async def get_one(owner: str, repo: str, request: Request) -> WebhookOut:
        """Say whether the library's push webhook is on, its URL and when its secret was made.

        The secret is never returned again: rotate it with `PUT` if it was lost.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            request: The HTTP request, for the webhook's URL.

        Returns:
            The webhook, without its secret.
        """
        found = await get_webhook(WebhookQuery(library=f"/{owner}/{repo}"))
        if not found.enabled:
            return found
        return found.model_copy(update={"url": url_of(request, owner, repo)})

    @router.put(path, name="set_webhook")
    async def set_one(owner: str, repo: str, request: Request) -> WebhookCreated:
        """Create or rotate the library's webhook secret; the old one stops working at once.

        The answer holds the secret (32 random bytes, URL-safe) and the URL to set in the
        forge's webhook settings. It is shown this once: `GET` never returns it.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.
            request: The HTTP request, for the webhook's URL.

        Returns:
            The webhook with its secret.
        """
        created = await set_webhook(WebhookQuery(library=f"/{owner}/{repo}"))
        return created.model_copy(update={"url": url_of(request, owner, repo)})

    @router.delete(path, name="disable_webhook")
    async def disable(owner: str, repo: str) -> WebhookOut:
        """Turn the library's push webhook off: every delivery is refused from now on.

        Args:
            owner: The library ID's owner.
            repo: The library ID's repository name.

        Returns:
            The webhook, now off.
        """
        return await disable_webhook(WebhookQuery(library=f"/{owner}/{repo}"))

    return router
