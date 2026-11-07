"""Import the fixture docs repository into a container with the real importer, every version.

Shared by the ranking suite (``tests/retrieval/ranking``) and the retrieval eval suite
(``packages/exactdocs/evals``): both search the same three imported versions.
"""

from exactdocs.bootstrap.bridges import (
    CatalogLibrarySources,
    CatalogVersionPublisher,
    RetrievalChunkIndex,
)
from exactdocs.bootstrap.container import Container
from exactdocs.catalog.dtos import CreateLibraryCommand, HostKind
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.memory import InMemoryCredentialVault
from exactdocs.ingestion.constants import IMPORT_JOB
from exactdocs.ingestion.models import Job, JobId, RefKind
from exactdocs.ingestion.use_cases import ImportVersionUseCase
from exactdocs_kernel import SystemClock
from fixture_repo import DocsRepo, git

LIBRARY = "/fixture/docs-repo"
"""The library ID the fixture repository is imported under."""
VERSIONS = {"v1.3.0": RefKind.TAG, "v1.4.0": RefKind.TAG, "next": RefKind.BRANCH}
"""The versions imported, and what kind of ref each is."""


class _Progress:
    async def report(self, *, done: int, total: int) -> None: ...

    async def problem(self, path: str, code: object, reason: str) -> None: ...

    async def chunking(self, *, chunked: int, reused: int) -> None: ...

    async def parsing(self, *, parsed: int, taken: int) -> None: ...


def commits(docs_repo: DocsRepo) -> dict[str, str]:
    """Return the commit SHA each imported version points at."""
    return {ref: git("rev-parse", f"{ref}^{{commit}}", cwd=docs_repo.path) for ref in VERSIONS}


async def import_fixture(container: Container, docs_repo: DocsRepo) -> None:
    """Create the library and import every version into ``container``, which must be running."""
    await container.catalog.create_library(
        CreateLibraryCommand(
            id=LIBRARY,
            title="Docs",
            source_url=docs_repo.file_url,
            host=HostKind.GIT,
            default_branch="main",
            include_paths=["docs/"],
        )
    )
    importer = ImportVersionUseCase(
        gateway=GitCli.locate(),
        chunker=MarkdownChunker(),
        sources=CatalogLibrarySources(
            get_library=container.catalog.get_library,
            list_renames=container.catalog.list_renames,
        ),
        versions=CatalogVersionPublisher(
            store_manifest=container.catalog.store_manifest,
            activate_manifest=container.catalog.activate_manifest,
            discard_pending_manifests=container.catalog.discard_pending_manifests,
            apply_readme=container.catalog.apply_readme,
            apply_manual_tags_to=container.catalog.apply_manual_tags,
            replace_renames_of=container.catalog.replace_renames,
        ),
        index=RetrievalChunkIndex(
            index_manifest=container.retrieval.index_manifest,
            get_chunk_sets=container.retrieval.get_chunk_sets,
            discard_pending_chunks=container.retrieval.discard_pending_chunks,
            remove_chunks=container.retrieval.remove_chunks,
            retag_articles=container.retrieval.retag_articles,
        ),
        vault=InMemoryCredentialVault(),
    )
    shas = commits(docs_repo)
    for ref, kind in VERSIONS.items():
        job = Job.queued(
            job_id=JobId(f"import-{ref}"),
            kind=IMPORT_JOB,
            library=LIBRARY,
            version=ref,
            commit_sha=shas[ref],
            ref_kind=kind,
            now=SystemClock().now(),
        )
        await importer(job, _Progress())
