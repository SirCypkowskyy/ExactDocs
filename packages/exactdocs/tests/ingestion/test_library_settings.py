"""Editing a library's settings: which job re-processes the versions, and what each job does."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryJobRepository,
    InMemoryLibrarySources,
    NoIndex,
    NoRemovals,
)
from exactdocs.ingestion.dtos import (
    EnqueueJobCommand,
    RemoveVersionCommand,
    TagRuleIn,
    UpdateLibrarySettingsCommand,
)
from exactdocs.ingestion.errors import (
    ImportInProgressError,
    InvalidPathPatternError,
    InvalidTagError,
    NoArticlesError,
    RepositoryUnreachableError,
    ReprocessFailedError,
)
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    REFRESH_JOB,
    REPROCESS_JOB,
    RETAG_JOB,
    ImportedRef,
    ImportSource,
    Job,
    JobId,
    PathSelection,
    ProblemCode,
    ProposedId,
    RefKind,
    RepositoryHost,
    RepositoryUrl,
    SettingsChange,
    StoredArticleTags,
    StoredTags,
    TagRule,
    front_matter_tags,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs.ingestion.use_cases import (
    ReprocessLibraryUseCase,
    RetagLibraryUseCase,
    TagLocks,
)
from exactdocs_kernel import NotFoundError

LIBRARY = "/acme/docs"
URL = RepositoryUrl(
    url="https://example.com/acme/docs",
    host_kind=RepositoryHost.GIT,
    library_id=ProposedId(LIBRARY),
)
SOURCE = ImportSource(url=URL, selection=PathSelection.of(["docs/"]), tag_rules=())
VERSIONS = [
    ImportedRef(ref="v1.0.0", kind=RefKind.TAG, commit_sha="a" * 40),
    ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha="b" * 40),
]


@dataclass
class Settings:
    """Stores settings into the sources the use cases read, like the catalog does."""

    sources: InMemoryLibrarySources
    saved: list[tuple[PathSelection, tuple[TagRule, ...]]] = field(default_factory=list)

    async def save(self, library: str, selection: PathSelection, tag_rules: Sequence[TagRule]):
        self.saved.append((selection, tuple(tag_rules)))
        current = await self.sources.get(library)
        self.sources.sources[library] = replace(
            current, selection=selection, tag_rules=tuple(tag_rules)
        )


async def _noop(job: Job, progress: object, /) -> None:
    del job, progress


@pytest.fixture
def sources() -> InMemoryLibrarySources:
    return InMemoryLibrarySources({LIBRARY: SOURCE}, {LIBRARY: list(VERSIONS)})


def make_module(
    sources: InMemoryLibrarySources, jobs: InMemoryJobRepository, clock, handlers=None
) -> tuple[IngestionModule, Settings]:
    settings = Settings(sources)
    module = IngestionModule.build(
        jobs=jobs,
        clock=clock,
        remote=None,  # ty: ignore[invalid-argument-type]
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        sources=sources,
        removals=NoRemovals(),
        index=NoIndex(),
        handlers=handlers
        if handlers is not None
        else {REPROCESS_JOB: _noop, RETAG_JOB: _noop, IMPORT_JOB: _noop},
        settings=settings,
    )
    return module, settings


def command(
    include: Sequence[str] = ("docs/",),
    exclude: Sequence[str] = (),
    rules: Sequence[tuple[str, str]] = (),
    library: str = LIBRARY,
) -> UpdateLibrarySettingsCommand:
    return UpdateLibrarySettingsCommand(
        library=library,
        include_paths=list(include),
        exclude_paths=list(exclude),
        tag_rules=[TagRuleIn(pattern=p, tag=t) for p, t in rules],
    )


# ------------------------------------------------------------------ UpdateLibrarySettings


async def test_changed_paths_queue_one_reprocess_job_for_every_version(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)

    updated = await module.update_library_settings(command(exclude=["docs/archive/**"]))

    assert updated.reprocess is SettingsChange.PATHS
    assert updated.versions == ["v1.0.0", "main"]
    assert updated.exclude_paths == ["docs/archive/**"]
    queued = await jobs.list_for_library(LIBRARY)
    assert [(j.id, j.kind, j.version) for j in queued] == [(updated.job_id, REPROCESS_JOB, None)]
    assert (await sources.get(LIBRARY)).selection.exclude == ("docs/archive/**",)


async def test_only_tag_rules_changed_queue_a_retag_job(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)

    updated = await module.update_library_settings(command(rules=[("docs/api/**", " API ")]))

    assert updated.reprocess is SettingsChange.TAGS
    assert [r.tag for r in updated.tag_rules] == ["api"]  # normalized as stored
    assert [j.kind for j in await jobs.list_for_library(LIBRARY)] == [RETAG_JOB]


async def test_unchanged_settings_store_and_queue_nothing(sources, jobs, clock):
    module, settings = make_module(sources, jobs, clock)

    updated = await module.update_library_settings(command())

    assert (updated.reprocess, updated.job_id, updated.versions) == (None, None, [])
    assert settings.saved == []
    assert await jobs.list_for_library(LIBRARY) == []


@pytest.mark.parametrize(
    ("sent", "error"),
    [
        (command(exclude=["../outside"]), InvalidPathPatternError),
        (command(rules=[("docs/**", "!!")]), InvalidTagError),
    ],
)
async def test_invalid_settings_are_refused_before_anything_is_stored(
    sources, jobs, clock, sent, error
):
    module, settings = make_module(sources, jobs, clock)

    with pytest.raises(error):
        await module.update_library_settings(sent)

    assert settings.saved == []
    assert await jobs.list_for_library(LIBRARY) == []


async def test_an_unknown_library_is_not_found(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)

    with pytest.raises(NotFoundError):
        await module.update_library_settings(command(library="/acme/other"))


async def test_the_library_id_is_matched_in_any_letter_case(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)

    updated = await module.update_library_settings(command(exclude=["x/"], library="/ACME/Docs"))

    assert updated.library_id == LIBRARY
    assert updated.job_id is not None


async def test_a_queued_reprocess_job_is_reused_for_any_later_edit(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)
    first = await module.update_library_settings(command(exclude=["a/"]))

    again = await module.update_library_settings(command(exclude=["b/"]))
    tags = await module.update_library_settings(command(exclude=["b/"], rules=[("docs/**", "d")]))

    assert first.job_id == again.job_id == tags.job_id
    assert len(await jobs.list_for_library(LIBRARY)) == 1


async def test_a_queued_retag_job_does_not_stand_in_for_changed_paths(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)
    retag = await module.update_library_settings(command(rules=[("docs/**", "d")]))

    paths = await module.update_library_settings(command(exclude=["a/"], rules=[("docs/**", "d")]))

    assert paths.job_id != retag.job_id
    assert [j.kind for j in await jobs.list_for_library(LIBRARY)] == [REPROCESS_JOB, RETAG_JOB]


async def test_a_running_job_is_not_reused(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)
    first = await module.update_library_settings(command(exclude=["a/"]))
    running = await jobs.claim_next(clock.now())
    assert running is not None
    assert running.id == first.job_id

    second = await module.update_library_settings(command(exclude=["b/"]))

    assert second.job_id != first.job_id


async def test_without_versions_or_imports_the_settings_are_only_stored(sources, jobs, clock):
    sources.versions[LIBRARY] = []
    module, settings = make_module(sources, jobs, clock)

    updated = await module.update_library_settings(command(exclude=["a/"]))

    assert (updated.job_id, updated.versions) == (None, [])
    assert len(settings.saved) == 1


async def test_a_first_import_still_running_is_re_processed_after_it(sources, jobs, clock):
    sources.versions[LIBRARY] = []
    module, _ = make_module(sources, jobs, clock)
    await module.enqueue_job(
        EnqueueJobCommand(
            kind=IMPORT_JOB, library=LIBRARY, version="main", commit_sha="b" * 40,
            ref_kind=RefKind.BRANCH,
        )
    )  # fmt: skip

    updated = await module.update_library_settings(command(exclude=["a/"]))

    assert updated.job_id is not None


async def test_settings_are_put_back_when_the_job_cannot_be_queued(sources, jobs, clock):
    module, settings = make_module(sources, jobs, clock, handlers={})  # no reprocess handler

    with pytest.raises(Exception, match="reprocess"):
        await module.update_library_settings(command(exclude=["a/"]))

    assert await sources.get(LIBRARY) == SOURCE
    assert [s for s, _ in settings.saved] == [PathSelection.of(["docs/"], ["a/"]), SOURCE.selection]


async def test_removal_waits_for_a_re_processing_job(sources, jobs, clock):
    module, _ = make_module(sources, jobs, clock)
    await module.update_library_settings(command(exclude=["a/"]))

    with pytest.raises(ImportInProgressError):
        await module.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v1.0.0"))


# ------------------------------------------------------------------ ReprocessLibrary


@dataclass
class Progress:
    reports: list[tuple[int, int]] = field(default_factory=list)
    problems: list[tuple[str, ProblemCode, str]] = field(default_factory=list)
    counters: list[tuple[int, int]] = field(default_factory=list)

    async def report(self, *, done: int, total: int) -> None:
        self.reports.append((done, total))

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        self.problems.append((path, code, reason))

    async def chunking(self, *, chunked: int, reused: int) -> None:
        self.counters.append((chunked, reused))


@dataclass
class Importer:
    """Stands in for the refresh importer: records each version, fails the ones told to."""

    failures: dict[str, Exception] = field(default_factory=dict)
    seen: list[Job] = field(default_factory=list)

    async def __call__(self, job: Job, progress, /) -> None:
        self.seen.append(job)
        await progress.report(done=0, total=2)
        await progress.problem("docs/a.md", ProblemCode.BINARY, "binary file")
        await progress.chunking(chunked=1, reused=1)
        await progress.report(done=2, total=2)
        if job.version in self.failures:
            raise self.failures[job.version]


def library_job(kind=REPROCESS_JOB) -> Job:
    return Job.queued(
        job_id=JobId("job"), kind=kind, library=LIBRARY, version=None, now=datetime.now(UTC)
    ).started(datetime.now(UTC))


async def test_every_version_is_re_imported_at_its_recorded_commit(sources):
    importer = Importer()
    progress = Progress()

    await ReprocessLibraryUseCase(sources, importer)(library_job(), progress)

    assert [(j.kind, j.version, j.commit_sha, j.ref_kind) for j in importer.seen] == [
        (REFRESH_JOB, "v1.0.0", "a" * 40, RefKind.TAG),
        (REFRESH_JOB, "main", "b" * 40, RefKind.BRANCH),  # where it is, not a newer tip
    ]
    assert progress.reports[-1] == (4, 4)  # files of both versions add up
    assert progress.counters[-1] == (2, 2)
    assert [p[2] for p in progress.problems] == ["v1.0.0: binary file", "main: binary file"]


async def test_a_failing_version_does_not_stop_the_others_and_fails_the_job(sources):
    importer = Importer(failures={"v1.0.0": NoArticlesError()})

    with pytest.raises(ReprocessFailedError) as raised:
        await ReprocessLibraryUseCase(sources, importer)(library_job(), Progress())

    assert [j.version for j in importer.seen] == ["v1.0.0", "main"]
    assert raised.value.refs == ("v1.0.0",)
    assert raised.value.code == "no_articles"
    assert "v1.0.0" in str(raised.value)


async def test_different_failures_share_a_generic_code(sources):
    importer = Importer(
        failures={"v1.0.0": NoArticlesError(), "main": RepositoryUnreachableError("down")}
    )

    with pytest.raises(ReprocessFailedError) as raised:
        await ReprocessLibraryUseCase(sources, importer)(library_job(), Progress())

    assert raised.value.code == "reprocess_failed"
    assert raised.value.refs == ("v1.0.0", "main")


# ------------------------------------------------------------------ RetagLibrary


@dataclass
class Store:
    """An ``ImportedTagStore`` over a dict of versions."""

    versions: dict[str, StoredTags]
    manual: dict[str, tuple[str, ...]] = field(default_factory=dict)
    writes: list[tuple[str, dict[str, tuple[str, ...]]]] = field(default_factory=list)

    async def stored_tags(self, library: str, ref: str) -> StoredTags | None:
        del library
        return self.versions.get(ref)

    async def set_imported_tags(
        self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        self.writes.append((manifest_id, dict(tags)))
        return {p: (*t, *self.manual.get(p, ())) for p, t in tags.items()}


@dataclass
class Index:
    """A ``ChunkIndex`` that only records re-tagging: a re-tag never chunks or indexes."""

    retagged: list[tuple[str, dict[str, tuple[str, ...]]]] = field(default_factory=list)

    async def retag(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> None:
        self.retagged.append((manifest_id, dict(tags)))

    async def known(self, config_hash: str, blob_shas: Sequence[str]) -> Mapping[str, Any]:
        raise NotImplementedError

    async def index(self, manifest_id: str, version: object) -> None:
        raise NotImplementedError

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        raise NotImplementedError

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        raise NotImplementedError


def article(
    path: str, tags: tuple[str, ...] = (), front_matter: dict[str, Any] | None = None
) -> StoredArticleTags:
    return StoredArticleTags(path=path, front_matter=front_matter or {}, tags=tags)


async def test_retag_rewrites_only_changed_articles_and_copies_every_tag_to_chunks(sources):
    sources.sources[LIBRARY] = replace(SOURCE, tag_rules=TagRule.many([("docs/api/**", "api")]))
    store = Store(
        {
            "v1.0.0": StoredTags(
                manifest_id="m1",
                articles=(
                    article("docs/api/auth.md", ("auth",), {"tags": ["Auth"]}),
                    article("docs/guide/a.md", ("old",)),  # an old rule's tag goes
                    article("docs/api/same.md", ("api",)),
                ),
            )
        },
        manual={"docs/api/auth.md": ("mine",)},
    )
    index = Index()
    progress = Progress()

    await RetagLibraryUseCase(sources, store, index, TagLocks())(library_job(RETAG_JOB), progress)

    assert store.writes == [("m1", {"docs/api/auth.md": ("api", "auth"), "docs/guide/a.md": ()})]
    assert index.retagged == [
        ("m1", {"docs/api/auth.md": ("api", "auth", "mine"), "docs/guide/a.md": ()})
    ]
    assert progress.reports == [(0, 2), (1, 2), (2, 2)]  # "main" serves nothing: skipped
    assert progress.counters[-1] == (0, 3)  # nothing chunked, every stored article reused


async def test_retag_writes_nothing_when_no_tag_changes(sources):
    store = Store({"main": StoredTags(manifest_id="m", articles=(article("docs/a.md"),))})
    index = Index()

    await RetagLibraryUseCase(sources, store, index, TagLocks())(library_job(RETAG_JOB), Progress())

    assert (store.writes, index.retagged) == ([], [])


# ------------------------------------------------------------------ models


@pytest.mark.parametrize(
    ("front_matter", "tags"),
    [
        ({}, ()),
        ({"tags": "Auth, API"}, ("auth", "api")),
        ({"tags": ["x", 3, "x"]}, ("x",)),
        ({"tags": 7}, ()),
    ],
)
def test_front_matter_tags_are_derived_like_the_parser_does(front_matter, tags):
    assert front_matter_tags(front_matter)[0] == tags


def test_a_stored_article_is_retagged_with_rule_tags_first():
    rules = TagRule.many([("docs/**", "docs")])

    assert article("docs/a.md", front_matter={"tags": ["b"]}).retagged(rules) == ("docs", "b")
