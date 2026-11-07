"""RET-01: the composition root queues the embedding when the embedding space may change.

Saving, over REST, the profile the embedding role uses (a new one, another kind or endpoint) can
make a new space: every version is queued at once, not at the next start or import. The bridge
also tells ingestion which failed batches to try again.
"""

import pytest

from exactdocs.bootstrap.bridges import RetrievalVersionEmbedder
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.embedding import SaveProviderThenEmbed
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, VersionRef
from exactdocs.ingestion.dtos import ListLibraryJobsQuery, QueuedEmbedding, QueueEmbeddingCommand
from exactdocs.ingestion.errors import EmbeddingUnavailableError
from exactdocs.ingestion.models import EmbedPlan
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    EmbedBatchCommand,
    EmbeddedBatchOut,
    EmbeddingPlanOut,
    EmbedVersionCommand,
    FinishedEmbeddingOut,
    FinishEmbeddingCommand,
    IndexManifestCommand,
    ProviderOut,
    SaveProviderCommand,
    UnembeddedVersionsOut,
    UnembeddedVersionsQuery,
)
from exactdocs.retrieval.errors import EmbeddingFailedError
from exactdocs.retrieval.models import ModelRole, ProfileOrigin, ProviderKind, ProviderProfile

LIBRARY = "/acme/docs"
MODEL = "gw:e5"
BLOB = "b" * 40
GATEWAY = SaveProviderCommand(name="gw", kind="openai-compatible", base_url="http://127.0.0.1:9/v1")


def _saved(roles: list[ModelRole]) -> ProviderOut:
    profile = ProviderProfile(
        name="gw",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        origin=ProfileOrigin.API,
        base_url="http://127.0.0.1:9/v1",
    )
    return ProviderOut.from_model(profile, roles, None)


class Queue:
    def __init__(self, *, fails: bool = False) -> None:
        self.calls: list[QueueEmbeddingCommand] = []
        self.fails = fails

    async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
        self.calls.append(command)
        if self.fails:
            raise RuntimeError
        return QueuedEmbedding(queued=2)


@pytest.mark.parametrize(("roles", "queued"), [([ModelRole.EMBEDDING], 1), ([ModelRole.LLM], 0)])
async def test_saving_the_embedding_roles_profile_queues_the_embedding(
    roles: list[ModelRole], queued: int
) -> None:
    queue = Queue()

    async def save(command: SaveProviderCommand) -> ProviderOut:
        del command
        return _saved(roles)

    saved = await SaveProviderThenEmbed(save_provider=save, queue_embedding=queue)(GATEWAY)

    assert saved.name == "gw"
    assert len(queue.calls) == queued


async def test_a_failure_to_queue_never_fails_the_save() -> None:
    async def save(command: SaveProviderCommand) -> ProviderOut:
        del command
        return _saved([ModelRole.EMBEDDING])

    hook = SaveProviderThenEmbed(save_provider=save, queue_embedding=Queue(fails=True))

    assert (await hook(GATEWAY)).name == "gw"


async def test_a_profile_saved_over_rest_for_the_embedding_role_queues_every_version() -> None:
    ai = AiSettings.model_validate({"embedding": {"model": "gw:e5"}})  # gw does not exist yet
    container = Container.build(Settings(ai=ai))
    async with container.running(jobs=False):
        await _import(container, "v1")
        await _import(container, "v2")

        await container.save_provider(GATEWAY)  # what `PUT /api/v1/ai/providers/gw` calls
        jobs = await container.ingestion.list_library_jobs(ListLibraryJobsQuery(library=LIBRARY))

    embeds = sorted((j.kind, j.version, j.state.value) for j in jobs.jobs if j.kind == "embed")
    assert embeds == [("embed", "v1", "queued"), ("embed", "v2", "queued")]


async def _import(container: Container, ref: str) -> None:
    """Store, index and activate one version of one article."""
    repository = SqliteLibraryRepository(engine=container.engine)
    if await repository.get(LibraryId(LIBRARY)) is None:
        await repository.save(
            Library(
                id=LibraryId(LIBRARY),
                title="Docs",
                source_url="https://github.com/acme/docs",
                host=HostKind.GITHUB,
                default_branch=VersionRef("main"),
            )
        )
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=LIBRARY,
            ref=ref,
            kind=RefKind.TAG,
            commit_sha="a" * 40,
            articles=[
                ArticleIn(
                    path="docs/a.md",
                    blob_sha=BLOB,
                    content_version=1,
                    title="Alpha",
                    tags=[],
                    content="# Alpha\n\nText.",
                )
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=LIBRARY,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path="docs/a.md",
                    blob_sha=BLOB,
                    chunks=[
                        ChunkIn(
                            heading_path=["Alpha"],
                            occurrence_index=0,
                            content="Text.",
                            content_hash="h",
                            anchor="alpha",
                        )
                    ],
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


@pytest.mark.parametrize(
    ("transient", "raised"), [(True, EmbeddingUnavailableError), (False, EmbeddingFailedError)]
)
async def test_the_bridge_marks_the_batches_worth_trying_again(
    *, transient: bool, raised: type[Exception]
) -> None:
    async def fails(command: EmbedBatchCommand) -> EmbeddedBatchOut:
        del command
        reason = "ModelHTTPError 429"
        raise EmbeddingFailedError(MODEL, reason, transient=transient)

    async def plan(command: EmbedVersionCommand) -> EmbeddingPlanOut:
        raise AssertionError(command)

    async def finish(command: FinishEmbeddingCommand) -> FinishedEmbeddingOut:
        raise AssertionError(command)

    async def unembedded(query: UnembeddedVersionsQuery) -> UnembeddedVersionsOut:
        raise AssertionError(query)

    bridge = RetrievalVersionEmbedder(
        plan_embedding=plan,
        embed_batch_of=fails,
        finish_embedding=finish,
        list_unembedded_versions=unembedded,
    )
    planned = EmbedPlan(space_id=1, manifest_id="m1", missing=1, created=False, skipped=None)

    with pytest.raises(raised):
        await bridge.embed_batch(LIBRARY, "v1", planned)
