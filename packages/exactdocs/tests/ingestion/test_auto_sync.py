"""The scheduled check (SYNC-02): which tags become ``auto`` versions, which go, and when.

The clock is the kernel ``Clock`` port, moved by hand: a library is checked when its interval is
up, whatever the schedule's own tick.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryAutoSyncStore,
    InMemoryJobRepository,
    InMemoryLibrarySources,
)
from exactdocs.ingestion.dtos import (
    DisableAutoSyncCommand,
    EnqueueJobCommand,
    GetAutoSyncQuery,
    RemoveLibraryCommand,
    SetAutoSyncCommand,
)
from exactdocs.ingestion.errors import InvalidAutoSyncError, RepositoryUnreachableError
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    REFRESH_JOB,
    AutoSync,
    ImportedRef,
    ImportedVersion,
    ImportSource,
    JobState,
    PathSelection,
    ProposedId,
    RefKind,
    RemoteRef,
    RemoteRefs,
    Removed,
    RepositoryHost,
    RepositoryUrl,
    ResolvedRef,
    VersionOrigin,
    plan_auto_imports,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs_kernel import NotFoundError

LIBRARY = "/acme/docs"
SHA = {name: f"{i:x}" * 40 for i, name in enumerate(["v1.2.0", "v1.3.0", "v1.4.0", "v1.5.0"], 1)}
OLD, NEW = "a" * 40, "b" * 40
URL = RepositoryUrl(
    url="https://example.com/acme/docs",
    host_kind=RepositoryHost.GIT,
    library_id=ProposedId(LIBRARY),
)
SOURCE = ImportSource(url=URL, selection=PathSelection.of([]), tag_rules=())
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


class HandClock:
    """A kernel ``Clock`` that stands still until moved."""

    def __init__(self) -> None:
        self.moment = T0

    def now(self) -> datetime:
        return self.moment

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)


@dataclass
class Remote:
    heads: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    error: Exception | None = None
    calls: int = 0
    meanwhile: Callable[[], Awaitable[None]] | None = None

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        del repository

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: object = None
    ) -> RemoteRefs:
        del repository, patterns, credential
        self.calls += 1
        if self.meanwhile:
            await self.meanwhile()
        if self.error:
            raise self.error
        return RemoteRefs(
            default_branch="main",
            refs=(
                *(RemoteRef(name=f"refs/heads/{n}", sha=s) for n, s in self.heads.items()),
                *(RemoteRef(name=f"refs/tags/{n}", sha=s) for n, s in self.tags.items()),
            ),
        )


@dataclass
class Catalog:
    """The library's versions; ``Removals`` and a do-nothing chunk index over them."""

    versions: list[ImportedRef]
    removed: list[str] = field(default_factory=list)

    async def remove_version(self, library: str, ref: str) -> Removed:
        if ref not in {v.ref for v in self.versions}:
            message = f"version {ref!r} not found"
            raise NotFoundError(message)
        self.versions[:] = [v for v in self.versions if v.ref != ref]
        self.removed.append(ref)
        return Removed(library=library, ref=ref, manifest_ids=(), default_ref=None)

    async def remove_library(self, library: str) -> Removed:
        self.versions.clear()
        return Removed(library=library, ref=None, manifest_ids=(), default_ref=None)

    async def known(self, config_hash: str, blob_shas: Sequence[str]) -> dict:
        del config_hash, blob_shas
        return {}

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        del manifest_id, version

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        del manifest_id, library

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        del manifest_ids

    async def retag(self, manifest_id: str, tags: object) -> None:
        del manifest_id, tags


class NoLibraryIds:
    async def is_taken(self, library_id: str) -> bool:
        del library_id
        return True


class NoLibraries:
    async def add(self, library: object) -> str:
        raise NotImplementedError

    async def discard(self, library_id: str) -> None:
        raise NotImplementedError


async def _noop(job: object, progress: object, /) -> None: ...


def tag(ref: str, origin: VersionOrigin = VersionOrigin.MANUAL) -> ImportedRef:
    return ImportedRef(ref=ref, kind=RefKind.TAG, commit_sha=SHA[ref], origin=origin)


def auto(ref: str) -> ImportedRef:
    return tag(ref, VersionOrigin.AUTO)


def tip(name: str, kind: RefKind = RefKind.TAG, sha: str | None = None) -> ResolvedRef:
    return ResolvedRef(name=name, kind=kind, commit_sha=sha or SHA.get(name, OLD))


@pytest.fixture
def clock() -> HandClock:
    return HandClock()


@pytest.fixture
def remote() -> Remote:
    return Remote(heads={"main": OLD}, tags={t: SHA[t] for t in ("v1.2.0", "v1.3.0", "v1.4.0")})


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(versions=[tag("v1.2.0")])  # added by hand


@pytest.fixture
def schedules() -> InMemoryAutoSyncStore:
    return InMemoryAutoSyncStore()


@pytest.fixture
def jobs() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def module(
    remote: Remote,
    catalog: Catalog,
    schedules: InMemoryAutoSyncStore,
    jobs: InMemoryJobRepository,
    clock: HandClock,
) -> IngestionModule:
    return IngestionModule.build(
        jobs=jobs,
        clock=clock,
        remote=remote,
        library_ids=NoLibraryIds(),
        libraries=NoLibraries(),
        sources=InMemoryLibrarySources({LIBRARY: SOURCE}, {LIBRARY: catalog.versions}),
        removals=catalog,
        index=catalog,
        handlers={IMPORT_JOB: _noop, REFRESH_JOB: _noop},
        auto_syncs=schedules,
    )


def schedule(**fields: object) -> SetAutoSyncCommand:
    return SetAutoSyncCommand.model_validate(
        {"library": LIBRARY, "tag_pattern": "v*", "keep_last": 2, "interval_minutes": 60} | fields
    )


def imports(jobs: InMemoryJobRepository) -> dict[str, VersionOrigin]:
    return {j.version or "": j.origin for j in jobs.jobs.values() if j.kind == IMPORT_JOB}


# ---------------------------------------------------------------- the plan (pure)


def test_matching_tags_become_imports_and_only_the_newest_are_kept() -> None:
    plan = plan_auto_imports(
        AutoSync(library=LIBRARY, tag_pattern="v*", keep_last=2),
        [tip("v1.3.0"), tip("v1.4.0"), tip("v1.5.0"), tip("main", RefKind.BRANCH)],
        [tag("v1.2.0"), auto("v1.3.0"), auto("v1.4.0")],
    )

    assert [t.name for t in plan.imports] == ["v1.5.0"]
    assert plan.removals == ("v1.3.0",)  # the oldest auto version; v1.2.0 is manual


def test_imports_are_queued_oldest_first_and_capped_by_keep_last() -> None:
    plan = plan_auto_imports(
        AutoSync(library=LIBRARY, tag_pattern="v*", keep_last=2),
        [tip("v1.2.0"), tip("v1.4.0"), tip("v1.3.0")],
        [],
    )

    assert [t.name for t in plan.imports] == ["v1.3.0", "v1.4.0"]
    assert plan.removals == ()


def test_versions_are_ordered_by_number_not_by_text() -> None:
    plan = plan_auto_imports(
        AutoSync(library=LIBRARY, tag_pattern="v*", keep_last=1),
        [tip("v1.10", sha=NEW), tip("v1.9", sha=NEW)],
        [],
    )

    assert [t.name for t in plan.imports] == ["v1.10"]


def test_unordered_tags_other_patterns_and_manual_versions_are_left_alone() -> None:
    plan = plan_auto_imports(
        AutoSync(library=LIBRARY, tag_pattern="v1.*", keep_last=1),
        [tip("v1.6.0-rc.1", sha=NEW), tip("V1.7.0", sha=NEW), tip("v2.0.0", sha=NEW)],
        [tag("v1.2.0"), tag("v1.3.0")],
    )

    assert plan.imports == ()
    assert plan.removals == ()


def test_a_tag_whose_import_failed_is_skipped_until_it_moves() -> None:
    sync = AutoSync(library=LIBRARY, tag_pattern="v*", keep_last=3)
    failed = {("v1.5.0", SHA["v1.5.0"])}

    stuck = plan_auto_imports(sync, [tip("v1.5.0")], [], failed=failed)
    moved = plan_auto_imports(sync, [tip("v1.5.0", sha=NEW)], [], failed=failed)

    assert stuck.imports == ()
    assert [t.commit_sha for t in moved.imports] == [NEW]


def test_without_a_pattern_no_tag_is_imported_or_removed() -> None:
    plan = plan_auto_imports(AutoSync(library=LIBRARY), [tip("v1.5.0")], [auto("v1.3.0")])

    assert plan == plan.__class__()


@pytest.mark.parametrize(
    "fields",
    [
        {"tag_pattern": ""},
        {"tag_pattern": "v *"},
        {"keep_last": 0},
        {"keep_last": 101},
        {"interval_minutes": 0},
        {"interval_minutes": 7 * 24 * 60 + 1},
    ],
)
def test_an_unusable_schedule_is_refused(fields: dict) -> None:
    with pytest.raises(InvalidAutoSyncError):
        AutoSync(library=LIBRARY, **fields)


def test_a_library_is_due_once_its_interval_is_up() -> None:
    sync = AutoSync(library=LIBRARY, interval_minutes=30)
    assert sync.is_due(T0)
    checked = sync.checked(T0, None)

    assert checked.next_check_at == T0 + timedelta(minutes=30)
    assert not checked.is_due(T0 + timedelta(minutes=29, seconds=59))
    assert checked.is_due(T0 + timedelta(minutes=30))


# ---------------------------------------------------------------- the use cases


async def test_setting_a_schedule_checks_nothing_until_the_tick(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    out = await module.set_auto_sync(schedule(library="/ACME/Docs"))

    assert (out.library, out.enabled, out.tag_pattern, out.next_check_at) == (
        LIBRARY,
        True,
        "v*",
        None,
    )
    assert remote.calls == 0
    assert not jobs.jobs
    assert await module.get_auto_sync(GetAutoSyncQuery(library=LIBRARY)) == out


async def test_a_tick_imports_new_tags_as_auto_and_prunes_old_auto_versions(
    module: IngestionModule,
    remote: Remote,
    catalog: Catalog,
    jobs: InMemoryJobRepository,
    clock: HandClock,
) -> None:
    await module.set_auto_sync(schedule())

    first = await module.run_scheduled_checks()

    assert first.checked == [LIBRARY]
    assert imports(jobs) == {"v1.3.0": VersionOrigin.AUTO, "v1.4.0": VersionOrigin.AUTO}
    queued = [j for j in jobs.jobs.values() if j.version == "v1.4.0"]
    assert [(j.commit_sha, j.ref_kind) for j in queued] == [(SHA["v1.4.0"], RefKind.TAG)]

    # The imports ran; a new tag is pushed; the interval is up.
    for job in list(jobs.jobs.values()):
        await jobs.save(job.started(clock.now()).succeeded(clock.now()))
    catalog.versions += [auto("v1.3.0"), auto("v1.4.0")]
    remote.tags["v1.5.0"] = SHA["v1.5.0"]
    clock.advance(minutes=60)

    second = await module.run_scheduled_checks()

    assert [j.version for j in jobs.jobs.values() if j.state is JobState.QUEUED] == ["v1.5.0"]
    assert second.removed == [f"{LIBRARY}/v1.3.0"]
    assert catalog.removed == ["v1.3.0"]
    assert [v.ref for v in catalog.versions] == ["v1.2.0", "v1.4.0"]  # manual v1.2.0 stays


async def test_a_library_is_not_checked_again_before_its_interval_is_up(
    module: IngestionModule, remote: Remote, clock: HandClock
) -> None:
    await module.set_auto_sync(schedule(interval_minutes=15))
    await module.run_scheduled_checks()

    clock.advance(minutes=14)
    early = await module.run_scheduled_checks()
    clock.advance(minutes=1)
    due = await module.run_scheduled_checks()

    assert (early.checked, due.checked, remote.calls) == ([], [LIBRARY], 2)
    out = await module.get_auto_sync(GetAutoSyncQuery(library=LIBRARY))
    assert out.checked_at == T0 + timedelta(minutes=15)
    assert out.next_check_at == T0 + timedelta(minutes=30)


async def test_an_unreachable_remote_is_recorded_and_tried_after_the_interval(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository, clock: HandClock
) -> None:
    await module.set_auto_sync(schedule())
    remote.error = RepositoryUnreachableError("connection refused")

    await module.run_scheduled_checks()
    clock.advance(minutes=1)
    await module.run_scheduled_checks()

    out = await module.get_auto_sync(GetAutoSyncQuery(library=LIBRARY))
    assert out.last_error is not None
    assert "connection refused" in out.last_error
    assert out.checked_at == T0
    assert remote.calls == 1
    assert not jobs.jobs


async def test_branches_are_re_synced_when_asked(
    module: IngestionModule, remote: Remote, catalog: Catalog, jobs: InMemoryJobRepository
) -> None:
    catalog.versions.append(ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha=OLD))
    remote.heads["main"] = NEW
    await module.set_auto_sync(schedule(tag_pattern=None, sync_branches=True))

    await module.run_scheduled_checks()

    [job] = jobs.jobs.values()
    assert (job.kind, job.version, job.commit_sha, job.origin) == (
        REFRESH_JOB,
        "main",
        NEW,
        VersionOrigin.MANUAL,
    )


async def test_a_tag_being_imported_is_not_queued_twice(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    await module.enqueue_job(
        EnqueueJobCommand(
            kind=IMPORT_JOB,
            library=LIBRARY,
            version="v1.4.0",
            commit_sha=SHA["v1.4.0"],
            ref_kind=RefKind.TAG,
        )
    )
    await module.set_auto_sync(schedule())

    await module.run_scheduled_checks()

    assert imports(jobs) == {"v1.3.0": VersionOrigin.AUTO, "v1.4.0": VersionOrigin.MANUAL}


async def test_a_schedule_changed_during_a_check_is_kept(
    module: IngestionModule,
    remote: Remote,
    schedules: InMemoryAutoSyncStore,
) -> None:
    await module.set_auto_sync(schedule())
    changed = AutoSync(library=LIBRARY, tag_pattern="release-*")

    async def save_new_settings() -> None:  # the owner saves new settings meanwhile
        await schedules.save(changed)

    remote.meanwhile = save_new_settings
    await module.run_scheduled_checks()

    assert await schedules.get(LIBRARY) == changed  # still due: checked at the next tick


async def test_a_removed_library_loses_its_schedule(
    module: IngestionModule, schedules: InMemoryAutoSyncStore
) -> None:
    await module.set_auto_sync(schedule())

    await module.remove_library(RemoveLibraryCommand(library=LIBRARY))

    assert await schedules.get(LIBRARY) is None


async def test_a_schedule_of_a_library_that_is_gone_is_dropped_by_the_tick(
    module: IngestionModule, schedules: InMemoryAutoSyncStore
) -> None:
    await schedules.save(AutoSync(library="/acme/gone", tag_pattern="v*"))

    result = await module.run_scheduled_checks()

    assert result.checked == []
    assert await schedules.get("/acme/gone") is None


async def test_disabling_keeps_every_version(
    module: IngestionModule, catalog: Catalog, schedules: InMemoryAutoSyncStore
) -> None:
    await module.set_auto_sync(schedule())

    out = await module.disable_auto_sync(DisableAutoSyncCommand(library=LIBRARY))

    assert not out.enabled
    assert await schedules.get(LIBRARY) is None
    assert [v.ref for v in catalog.versions] == ["v1.2.0"]


async def test_an_unknown_library_has_no_schedule(module: IngestionModule) -> None:
    with pytest.raises(NotFoundError):
        await module.set_auto_sync(schedule(library="/acme/unknown"))
    with pytest.raises(NotFoundError):
        await module.get_auto_sync(GetAutoSyncQuery(library="/acme/unknown"))
