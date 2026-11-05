"""A killed import resumes at its first unfinished step (``Checkpoints``), with no duplicates."""

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryCheckpoints,
    InMemoryCredentialVault,
    InMemoryJobRepository,
)
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    ArticleChunk,
    ArticleTags,
    GitRename,
    ImportedRef,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    ParsedArticle,
    PathSelection,
    ProposedId,
    RefKind,
    RepositoryHost,
    RepositoryUrl,
)
from exactdocs.ingestion.use_cases import ImportVersionUseCase, _Progress

SHA = "c" * 40
FILES = 200
BATCH = 20
URL = RepositoryUrl(
    url="https://example.com/acme/docs", host_kind=RepositoryHost.GIT, library_id=ProposedId("/a/b")
)


class Killed(BaseException):
    """The process died: nothing after this point of the run happens (no clean-up either)."""


@dataclass(slots=True)
class Repository:
    """A ``GitGateway`` whose commit has ``FILES`` articles; counts the fetches."""

    tmp: Path
    fetches: int = 0

    @asynccontextmanager
    async def fetch(self, *_: object, **__: object) -> AsyncGenerator[Path]:
        self.fetches += 1
        folder = self.tmp / f"checkout-{self.fetches}"
        for n in range(1, FILES + 1):
            path = folder / "docs" / f"page-{n:03}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Page {n}\n\nText of page {n}.\n")
        yield folder

    @asynccontextmanager
    async def fetch_files(self, *_: object, **__: object) -> AsyncGenerator[Path]:
        yield self.tmp  # never asked for: the articles reference no image


@dataclass(slots=True)
class CountingChunker:
    """The real chunker, counting what it cuts; the process dies before cutting ``kill_at``."""

    kill_at: str | None = None
    cut: list[str] = field(default_factory=list)
    inner: MarkdownChunker = field(default_factory=MarkdownChunker)

    @property
    def config_hash(self) -> str:
        return self.inner.config_hash

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        if article.path == self.kill_at:
            raise Killed
        self.cut.append(article.path)
        return self.inner.chunk(article)


class Sources:
    async def get(self, library: str) -> ImportSource:
        del library
        return ImportSource(url=URL, selection=PathSelection(include=("docs/",)))

    async def imported_versions(self, library: str) -> list[ImportedRef]:
        del library
        return []

    async def renames_of(self, library: str, ref: str) -> list[GitRename]:
        del library, ref
        return []


@dataclass(slots=True)
class Catalog:
    """``VersionPublisher`` and ``ChunkIndex`` in one, logging the calls."""

    log: list[str] = field(default_factory=list)
    stored: list[ImportedVersion] = field(default_factory=list)
    kill_at: str | None = None

    def _call(self, name: str) -> None:
        self.log.append(name)
        if name == self.kill_at:
            raise Killed

    async def store(self, version: ImportedVersion) -> str:
        self._call("store")
        self.stored.append(version)
        return f"m{len(self.stored)}"

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        del version
        self._call(f"index {manifest_id}")

    async def activate(self, manifest_id: str) -> None:
        self._call(f"activate {manifest_id}")

    async def apply_manual_tags(self, manifest_id: str) -> ArticleTags:
        del manifest_id
        return {}

    async def retag(self, manifest_id: str, tags: ArticleTags) -> None:
        del manifest_id, tags

    async def describe(self, **_: object) -> None:
        self._call("describe")

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        del library
        self._call(f"discard {manifest_id}")

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        del config_hash, blob_shas
        return {}

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        del manifest_ids


def importer(
    repository: Repository, chunker: CountingChunker, catalog: Catalog, checkpoints
) -> ImportVersionUseCase:
    return ImportVersionUseCase(
        gateway=repository,
        chunker=chunker,
        sources=Sources(),
        versions=catalog,
        index=catalog,
        vault=InMemoryCredentialVault(),
        checkpoints=checkpoints,
        batch_files=BATCH,
    )


async def run(use_case: ImportVersionUseCase, jobs: InMemoryJobRepository) -> Job:
    job = Job.queued(
        job_id=JobId("j1"),
        kind=IMPORT_JOB,
        library="/a/b",
        version="main",
        commit_sha=SHA,
        ref_kind=RefKind.BRANCH,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    ).started(datetime(2026, 1, 1, tzinfo=UTC))
    await jobs.add(job)
    progress = _Progress(jobs, job)
    await use_case(job, progress)
    return progress.job


def page(n: int) -> str:
    return f"docs/page-{n:03}.md"


async def test_an_import_killed_after_120_files_finishes_from_file_121(tmp_path: Path) -> None:
    repository, catalog, checkpoints = Repository(tmp_path), Catalog(), InMemoryCheckpoints()
    first = CountingChunker(kill_at=page(121))
    with pytest.raises(Killed):
        await run(importer(repository, first, catalog, checkpoints), InMemoryJobRepository())
    assert first.cut == [page(n) for n in range(1, 121)]

    again = CountingChunker()
    job = await run(
        importer(repository, again, catalog, checkpoints.resumed()), InMemoryJobRepository()
    )

    assert again.cut == [page(n) for n in range(121, FILES + 1)]
    [version] = catalog.stored
    paths = [article.path for article in version.articles]
    assert paths == [page(n) for n in range(1, FILES + 1)]  # each article exactly once
    assert all(article.chunks for article in version.articles)
    assert (job.done, job.total, job.chunked, job.reused) == (FILES, FILES, FILES, 0)


async def test_a_replayed_step_rebuilds_the_progress_and_problems_of_the_first_run(
    tmp_path: Path,
) -> None:
    repository, catalog, checkpoints = Repository(tmp_path), Catalog(), InMemoryCheckpoints()
    first = await run(
        importer(repository, CountingChunker(), catalog, checkpoints), InMemoryJobRepository()
    )

    # Every step is replayed: nothing is fetched, parsed or chunked, the job ends the same.
    replayed = CountingChunker()
    resumed = checkpoints.resumed()
    again = await run(importer(repository, replayed, catalog, resumed), InMemoryJobRepository())

    assert (repository.fetches, replayed.cut, resumed.ran) == (1, [], [])
    assert (again.done, again.total, again.problems) == (first.done, first.total, first.problems)


async def test_a_resume_with_only_publishing_left_fetches_nothing_and_publishes_once(
    tmp_path: Path,
) -> None:
    repository, checkpoints = Repository(tmp_path), InMemoryCheckpoints()
    catalog = Catalog(kill_at="index m1")
    with pytest.raises(Killed):
        await run(
            importer(repository, CountingChunker(), catalog, checkpoints), InMemoryJobRepository()
        )
    catalog.kill_at, catalog.log = None, []

    again = CountingChunker()
    await run(importer(repository, again, catalog, checkpoints.resumed()), InMemoryJobRepository())

    assert (repository.fetches, again.cut) == (1, [])
    assert catalog.log == ["store", "index m2", "activate m2", "describe"]
