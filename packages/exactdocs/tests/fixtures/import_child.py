"""Import a version in a process of its own, so that a test can kill it (``kill -9``) halfway.

``python import_child.py <data dir> <repository URL> <commit> <chunk log> [kill after N]``

The first run (with a commit) adds the library and queues the import of ``main``; a run with
``-`` as the commit only starts ExactDocs again. Either waits for the import to end and prints
it as JSON with the version's article paths. Every file the chunker cuts is appended to the
chunk log; with ``kill after N``, the process kills itself (SIGKILL: no clean-up of any kind)
before cutting file N + 1.

Tests use ``big_repository`` and ``run`` (pytest and behave alike).
"""

import asyncio
import json
import os
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import CreateLibraryCommand, HostKind, ListArticlesQuery
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.dtos import EnqueueJobCommand, GetJobQuery, ListLibraryJobsQuery
from exactdocs.ingestion.models import ArticleChunk, ParsedArticle
from fixture_repo import git

LIBRARY = "/acme/big-docs"
BATCH = 20
CHILD = Path(__file__)


def page(n: int) -> str:
    """The path of article ``n`` of a ``big_repository``.

    Returns:
        The path.
    """
    return f"docs/page-{n:03}.md"


def big_repository(path: Path, files: int) -> tuple[str, str]:
    """Create a repository whose ``main`` has ``files`` articles; return its URL and commit.

    Returns:
        Its URL and the commit SHA of ``main``.
    """
    git("init", "-q", "-b", "main", "--template=", str(path))
    git("config", "uploadpack.allowFilter", "true", cwd=path)
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=path)
    for n in range(1, files + 1):
        file = path / page(n)
        file.parent.mkdir(exist_ok=True)
        file.write_text(f"# Page {n}\n\nThe text of page {n}.\n\n## Details\n\nMore about {n}.\n")
    git("add", "-A", cwd=path)
    git(
        "commit", "-q", "--no-verify", "-m", "pages", cwd=path,
        GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="a", GIT_COMMITTER_EMAIL="a@example.com",
    )  # fmt: skip
    return path.as_uri(), git("rev-parse", "HEAD", cwd=path)


async def run(*args: str) -> tuple[int, str, str]:
    """Run this script with ``args`` to its end; return its exit code, stdout and stderr.

    Returns:
        Its exit code, stdout and stderr.
    """
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


def _count_chunks(log: Path, kill_after: int | None) -> None:
    cut = MarkdownChunker.chunk
    seen = 0

    def chunk(self: MarkdownChunker, article: ParsedArticle) -> Sequence[ArticleChunk]:
        nonlocal seen
        seen += 1
        if kill_after is not None and seen > kill_after:
            os.kill(os.getpid(), signal.SIGKILL)
        with log.open("a", encoding="utf-8") as out:
            out.write(f"{article.path}\n")
        return cut(self, article)

    MarkdownChunker.chunk = chunk


async def _articles(container: Container) -> list[str]:
    paths: list[str] = []
    cursor = None
    while True:
        page = await container.catalog.list_articles(
            ListArticlesQuery(library=LIBRARY, ref="main", limit=100, cursor=cursor)
        )
        paths += [article.path for article in page.articles]
        if page.next_cursor is None:
            return paths
        cursor = page.next_cursor


async def main(data_dir: Path, url: str, commit: str) -> None:
    container = Container.build(Settings(data_dir=data_dir, import_batch_files=BATCH))
    async with container.running():
        if commit != "-":
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
            await container.ingestion.enqueue_job(
                EnqueueJobCommand(kind="import", library=LIBRARY, version="main", commit_sha=commit)
            )
        [job] = (
            await container.ingestion.list_library_jobs(ListLibraryJobsQuery(library=LIBRARY))
        ).jobs
        while job.state in {"queued", "running"}:
            await asyncio.sleep(0.05)
            job = await container.ingestion.get_job(GetJobQuery(job_id=job.id))
        result = {"state": job.state, "done": job.done, "total": job.total}
        sys.stdout.write(json.dumps(result | {"articles": await _articles(container)}))


if __name__ == "__main__":
    folder, repository, sha, chunk_log, *kill = sys.argv[1:]
    _count_chunks(Path(chunk_log), int(kill[0]) if kill else None)
    asyncio.run(main(Path(folder), repository, sha))
