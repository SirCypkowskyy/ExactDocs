"""RET-01: the composition root queues the embedding when the embedding space may change.

Saving, over REST, the profile the embedding role uses (a new one, another kind or endpoint) can
make a new space: every version is queued at once, not at the next start or import. The bridge
also tells ingestion which failed batches to try again.
"""

import asyncio

import pytest

from databases import ADMIN_URL, SECRET_KEY, postgres_database
from exactdocs.bootstrap.bridges import RetrievalVersionEmbedder
from exactdocs.bootstrap.container import Container, vector_index
from exactdocs.bootstrap.embedding import SaveProviderThenEmbed
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, VersionRef
from exactdocs.ingestion.dtos import ListLibraryJobsQuery, QueuedEmbedding, QueueEmbeddingCommand
from exactdocs.ingestion.errors import EmbeddingUnavailableError
from exactdocs.ingestion.models import EmbedPlan
from exactdocs.retrieval.adapters.driven.postgres_vectors import PostgresVectorIndex
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
from exactdocs.retrieval.models import (
    EmbeddingSkip,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    SpaceState,
)
from fake_llm import gateway

LIBRARY = "/acme/docs"
MODEL = "gw:e5"
BLOB = "b" * 40
EMBED_SECONDS = 60.0
"""How long an embed job may take here (a fake gateway answers at once)."""
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


# ---------------------------------------------------------------- PostgreSQL with pgvector (#243)


@pytest.mark.skipif(ADMIN_URL is None, reason="needs EXACTDOCS_TEST_POSTGRES_URL")
async def test_a_version_is_embedded_into_pgvector_by_its_job(on_postgres: object) -> None:
    del on_postgres
    with gateway() as endpoint:
        ai = AiSettings.model_validate(
            {
                "providers": {"gw": {"kind": "openai-compatible", "base_url": endpoint.v1}},
                "embedding": {"model": MODEL},
            }
        )
        container = Container.build(Settings(ai=ai))
        async with container.running():
            await _import(container, "v1")
            before = await container.retrieval.estimate_embedding()
            queued = await container.ingestion.queue_embedding(QueueEmbeddingCommand())
            jobs = await _wait_for_embed_jobs(container)
            after = await container.retrieval.estimate_embedding()
            spaces = await vector_index(container.engine).spaces()
            left = await container.retrieval.list_unembedded_versions(UnembeddedVersionsQuery())

    assert isinstance(vector_index(container.engine), PostgresVectorIndex)
    assert (before.chunks, queued.queued) == (1, 1)
    assert [j.state.value for j in jobs] == ["succeeded"]
    assert [(s.spec.model, s.state) for s in spaces] == [("e5", SpaceState.ACTIVE)]
    assert (after.chunks, after.space_id, left.versions) == (0, spaces[0].id, [])
    assert any(s.path.endswith("/embeddings") for s in endpoint.seen)


@pytest.mark.skipif(ADMIN_URL is None, reason="needs EXACTDOCS_TEST_POSTGRES_URL")
async def test_without_pgvector_embed_jobs_send_nothing_and_the_estimate_still_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        postgres_database(owner_without_createdb=True, without_extensions=("vector",)) as db,
        gateway() as endpoint,
    ):
        monkeypatch.setenv("EXACTDOCS_DATABASE_URL", db.url)
        monkeypatch.setenv("EXACTDOCS_SECRET_KEY", SECRET_KEY)
        ai = AiSettings.model_validate(
            {
                "providers": {"gw": {"kind": "openai-compatible", "base_url": endpoint.v1}},
                "embedding": {"model": MODEL},
            }
        )
        container = Container.build(Settings(ai=ai))
        async with container.running(jobs=False):
            await _import(container, "v1")
            plan = await container.retrieval.plan_embedding(
                EmbedVersionCommand(library=LIBRARY, ref="v1")
            )
            estimate = await container.retrieval.estimate_embedding()

    assert plan.skipped is EmbeddingSkip.VECTOR_STORE_UNAVAILABLE
    assert (estimate.chunks, estimate.space_id) == (1, None)
    assert not endpoint.seen  # not even the dimensions probe


async def _wait_for_embed_jobs(container: Container) -> list:
    """Wait until the library's embed jobs have all ended; return them.

    Returns:
        The embed jobs.
    """
    deadline = asyncio.get_running_loop().time() + EMBED_SECONDS
    while True:
        listed = await container.ingestion.list_library_jobs(ListLibraryJobsQuery(library=LIBRARY))
        jobs = [j for j in listed.jobs if j.kind == "embed"]
        ended = jobs and all(j.state.value not in {"queued", "running"} for j in jobs)
        if ended or asyncio.get_running_loop().time() > deadline:
            return jobs
        await asyncio.sleep(0.1)
