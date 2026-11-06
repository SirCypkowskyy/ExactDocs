"""Re-process a library in a process of its own, so that a test can kill it (``kill -9``) halfway.

``python reprocess_child.py <data dir> <repository URL> <store log> [kill at N]``

A run with ``kill at N`` adds the library, imports the tags ``v1`` and ``v2`` of ``main``,
then edits the library's paths (``EXCLUDED`` left out), which queues a ``reprocess`` job. A run
without it only starts ExactDocs again. Either waits for the ``reprocess`` job to end and prints
it as JSON with each version's article paths. Every version stored is appended to the store log
(its ref); with ``kill at N`` the process kills itself (SIGKILL: no clean-up of any kind) when
the catalog is about to store a version for the N-th time.

Tests use ``tagged_repository`` and ``run``.
"""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from exactdocs.bootstrap.bridges import CatalogVersionPublisher
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import CreateLibraryCommand, HostKind, ListArticlesQuery
from exactdocs.ingestion.dtos import (
    EnqueueJobCommand,
    GetJobQuery,
    ListLibraryJobsQuery,
    UpdateLibrarySettingsCommand,
)
from exactdocs.ingestion.models import ImportedVersion, RefKind
from fixture_repo import git
from import_child import big_repository

LIBRARY = "/acme/big-docs"
TAGS = ("v1", "v2")
EXCLUDED = "docs/page-00*.md"
CHILD = Path(__file__)


def tagged_repository(path: Path, files: int) -> str:
    """A ``big_repository`` whose ``main`` is tagged ``v1`` and ``v2``; return its URL."""
    url, _ = big_repository(path, files)
    for tag in TAGS:
        git("tag", tag, cwd=path)
    return url


async def run(*args: str) -> tuple[int, str, str]:
    """Run this script with ``args`` to its end; return its exit code, stdout and stderr."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(CHILD),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(300):
        out, err = await process.communicate()
    assert process.returncode is not None
    return process.returncode, out.decode(), err.decode()


def _log_stores(log: Path, kill_at: int | None) -> None:
    store = CatalogVersionPublisher.store
    seen = 0

    async def logged(self: CatalogVersionPublisher, version: ImportedVersion) -> str:
        nonlocal seen
        seen += 1
        if kill_at is not None and seen == kill_at:
            os.kill(os.getpid(), signal.SIGKILL)
        with log.open("a", encoding="utf-8") as out:
            out.write(f"{version.ref}\n")
        return await store(self, version)

    CatalogVersionPublisher.store = logged


async def _articles(container: Container, ref: str) -> list[str]:
    paths: list[str] = []
    cursor = None
    while True:
        page = await container.catalog.list_articles(
            ListArticlesQuery(library=LIBRARY, ref=ref, limit=100, cursor=cursor)
        )
        paths += [article.path for article in page.articles]
        if page.next_cursor is None:
            return paths
        cursor = page.next_cursor


async def _finished(container: Container, job_id: str):
    job = await container.ingestion.get_job(GetJobQuery(job_id=job_id))
    while job.state in {"queued", "running"}:
        await asyncio.sleep(0.05)
        job = await container.ingestion.get_job(GetJobQuery(job_id=job_id))
    return job


async def _set_up(container: Container, url: str) -> None:
    await container.catalog.create_library(
        CreateLibraryCommand(
            id=LIBRARY,
            title="Big docs",
            source_url=url,
            host=HostKind.GIT,
            default_branch="main",
            include_paths=["docs/"],
        )
    )
    commit = git("ls-remote", url, "refs/heads/main").split()[0]
    for tag in TAGS:
        job = await container.ingestion.enqueue_job(
            EnqueueJobCommand(
                kind="import",
                library=LIBRARY,
                version=tag,
                commit_sha=commit,
                ref_kind=RefKind.TAG,
            )
        )
        assert (await _finished(container, job.id)).state == "succeeded"
    await container.ingestion.update_library_settings(
        UpdateLibrarySettingsCommand(
            library=LIBRARY, include_paths=["docs/"], exclude_paths=[EXCLUDED]
        )
    )


async def main(data_dir: Path, url: str, first: bool) -> None:
    container = Container.build(Settings(data_dir=data_dir))
    async with container.running():
        if first:
            await _set_up(container, url)
        jobs = await container.ingestion.list_library_jobs(ListLibraryJobsQuery(library=LIBRARY))
        [reprocess] = [job for job in jobs.jobs if job.kind == "reprocess"]
        job = await _finished(container, reprocess.id)
        result = {"state": job.state, "error": job.error, "done": job.done, "total": job.total}
        versions = {tag: await _articles(container, tag) for tag in TAGS}
        sys.stdout.write(json.dumps(result | {"versions": versions}))


if __name__ == "__main__":
    folder, repository, store_log, *kill = sys.argv[1:]
    _log_stores(Path(store_log), int(kill[0]) if kill else None)
    asyncio.run(main(Path(folder), repository, first=bool(kill)))
