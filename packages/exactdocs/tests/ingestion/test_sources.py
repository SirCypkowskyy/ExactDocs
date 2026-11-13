"""The sources file (TEAM-02): its schema, the pure plan and apply over driving-port doubles."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryAutoSyncStore,
    InMemoryJobRepository,
    InMemoryLibrarySources,
)
from exactdocs.ingestion.constants import IMPORT_JOB, MAX_SOURCES
from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddedVersion,
    AddLibraryCommand,
    AddVersionCommand,
    ApplySourcesCommand,
    AutoSyncOut,
    ChunkingIn,
    DisableAutoSyncCommand,
    PlanSourcesCommand,
    RemovalResult,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    SetAutoSyncCommand,
    SourcesFile,
    UpdatedLibrarySettings,
    UpdateLibrarySettingsCommand,
    sources_json_schema,
)
from exactdocs.ingestion.errors import InvalidSourcesError, UnknownRefError
from exactdocs.ingestion.models import (
    AutoSync,
    ChunkingConfig,
    CurrentLibrary,
    DeclaredLibrary,
    ImportedRef,
    ImportSource,
    Job,
    JobId,
    JobState,
    KnownLibrary,
    PathSelection,
    RefKind,
    RepositoryUrl,
    SettingsChange,
    SourcesField,
    TagRule,
    VersionOrigin,
    plan_sources,
)
from exactdocs.ingestion.use_cases import (
    ApplySourcesUseCase,
    PlanSourcesUseCase,
    SourcesReader,
)

URL = "https://github.com/acme/docs"
LIBRARY = "/acme/docs"
SHA = "a" * 40
SCHEMA = Path(__file__).parents[4] / "docs" / "schemas" / "exactdocs.sources.schema.json"


def _source(
    url: str = URL,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    rules: Sequence[tuple[str, str]] = (),
    chunking: ChunkingConfig | None = None,
) -> ImportSource:
    return ImportSource(
        url=RepositoryUrl.parse(url),
        selection=PathSelection.of(include, exclude),
        tag_rules=TagRule.many(list(rules)),
        chunking=chunking or ChunkingConfig(),
    )


def _version(ref: str, origin: VersionOrigin = VersionOrigin.MANUAL) -> ImportedRef:
    return ImportedRef(ref=ref, kind=RefKind.TAG, commit_sha=SHA, origin=origin)


def _current(
    *,
    library_id: str = LIBRARY,
    source: ImportSource | None = None,
    versions: tuple[ImportedRef, ...] = (_version("main"),),
    busy_refs: frozenset[str] = frozenset(),
    auto_sync: AutoSync | None = None,
) -> CurrentLibrary:
    return CurrentLibrary(
        library_id=library_id,
        source=source or _source(),
        versions=versions,
        busy_refs=busy_refs,
        auto_sync=auto_sync,
    )


def _declared(
    *,
    url: RepositoryUrl | None = None,
    refs: tuple[str, ...] = ("main",),
    include: tuple[str, ...] | None = None,
    exclude: tuple[str, ...] | None = None,
    tag_rules: tuple[TagRule, ...] | None = None,
    chunking: ChunkingConfig | None = None,
    manages_auto_sync: bool = False,
    auto_sync: AutoSync | None = None,
) -> DeclaredLibrary:
    return DeclaredLibrary(
        library_id=LIBRARY,
        url=url or RepositoryUrl.parse(URL),
        refs=refs,
        include=include,
        exclude=exclude,
        tag_rules=tag_rules,
        chunking=chunking,
        manages_auto_sync=manages_auto_sync,
        auto_sync=auto_sync,
    )


# --- the pure plan --------------------------------------------------------------------------


def test_a_declared_library_that_does_not_exist_is_created() -> None:
    plan = plan_sources([_declared()], [])

    assert [d.library_id for d in plan.create] == [LIBRARY]
    assert (plan.update, plan.unchanged, plan.undeclared) == ((), (), ())


def test_a_library_that_matches_its_declaration_is_unchanged() -> None:
    plan = plan_sources([_declared()], [_current()])

    assert plan.unchanged == (LIBRARY,)
    assert plan.update == ()


def test_settings_the_file_leaves_out_are_not_managed() -> None:
    current = _current(
        source=_source(
            include=["docs/"], rules=[("docs/**", "api")], chunking=ChunkingConfig(split_depth=2)
        ),
        auto_sync=AutoSync(library=LIBRARY, tag_pattern="v*"),
    )

    assert plan_sources([_declared()], [current]).unchanged == (LIBRARY,)


@pytest.mark.parametrize(
    ("declared", "field", "change"),
    [
        ({"include": ("guide/",)}, SourcesField.INCLUDE_PATHS, SettingsChange.PATHS),
        ({"exclude": ("docs/old/",)}, SourcesField.EXCLUDE_PATHS, SettingsChange.PATHS),
        (
            {"tag_rules": TagRule.many([("docs/**", "web")])},
            SourcesField.TAG_RULES,
            SettingsChange.TAGS,
        ),
        (
            {"chunking": ChunkingConfig(split_depth=3)},
            SourcesField.CHUNKING,
            SettingsChange.CHUNKING,
        ),
    ],
)
def test_each_managed_setting_that_differs_is_an_update_with_its_job(
    declared: dict, field: SourcesField, change: SettingsChange
) -> None:
    current = _current(source=_source(include=["docs/"], rules=[("docs/**", "api")]))

    (update,) = plan_sources([_declared(**declared)], [current]).update

    assert (update.changed, update.reprocess, update.writes) == ((field,), change, True)


def test_paths_and_chunking_together_queue_the_widest_job() -> None:
    declared = _declared(include=("guide/",), chunking=ChunkingConfig(split_depth=3))

    (update,) = plan_sources([declared], [_current()]).update

    assert update.reprocess is SettingsChange.PATHS


def test_a_settings_change_of_a_library_without_versions_queues_no_job() -> None:
    current = _current(versions=())

    (update,) = plan_sources([_declared(include=("guide/",))], [current]).update

    assert (update.changed, update.reprocess) == ((SourcesField.INCLUDE_PATHS,), None)


def test_reordered_paths_and_differently_spelled_tags_are_no_change() -> None:
    current = _current(
        source=_source(include=["a/", "b/"], rules=[("docs/**", "api"), ("x/**", "x")])
    )
    declared = _declared(
        include=PathSelection.of(["b/", "a/"]).include,
        tag_rules=TagRule.many([("x/**", "X"), ("docs/**", " API ")]),
    )

    assert plan_sources([declared], [current]).unchanged == (LIBRARY,)


def test_managed_empty_paths_differ_from_stored_ones() -> None:
    current = _current(source=_source(include=["docs/"]))

    (update,) = plan_sources([_declared(include=())], [current]).update

    assert update.changed == (SourcesField.INCLUDE_PATHS,)
    assert update.selection == PathSelection()


def test_an_update_sends_the_stored_value_of_what_it_does_not_manage() -> None:
    current = _current(
        source=_source(include=["docs/"], exclude=["docs/old/"], rules=[("a/**", "a")])
    )

    (update,) = plan_sources([_declared(exclude=())], [current]).update

    assert update.selection == PathSelection.of(["docs/"], [])
    assert update.tag_rules == TagRule.many([("a/**", "a")])


def test_declared_refs_that_are_neither_versions_nor_importing_are_added() -> None:
    current = _current(busy_refs=frozenset({"v1.4.0"}))

    (update,) = plan_sources([_declared(refs=("main", "v1.4.0", "v1.5.0"))], [current]).update

    assert update.refs_to_add == ("v1.5.0",)


def test_a_ref_whose_import_is_queued_counts_as_present() -> None:
    current = _current(versions=(), busy_refs=frozenset({"main"}))

    assert plan_sources([_declared()], [current]).unchanged == (LIBRARY,)


@pytest.mark.parametrize(
    ("declared", "current"),
    [
        (AutoSync(library=LIBRARY, tag_pattern="v*"), None),  # on
        (None, AutoSync(library=LIBRARY, tag_pattern="v*")),  # off
        (
            AutoSync(library=LIBRARY, tag_pattern="v*", keep_last=3),
            AutoSync(library=LIBRARY, tag_pattern="v*"),
        ),
    ],
)
def test_turning_the_schedule_on_off_or_changing_it_is_an_update(
    declared: AutoSync | None, current: AutoSync | None
) -> None:
    plan = plan_sources(
        [_declared(manages_auto_sync=True, auto_sync=declared)], [_current(auto_sync=current)]
    )

    (update,) = plan.update
    assert (update.auto_sync_changes, update.reprocess) == (True, None)


def test_the_same_schedule_is_no_change_whatever_its_last_check() -> None:
    current = AutoSync(
        library=LIBRARY, tag_pattern="v*", checked_at=datetime.now(UTC), revision="r"
    )
    declared = _declared(
        manages_auto_sync=True, auto_sync=AutoSync(library=LIBRARY, tag_pattern="v*")
    )

    assert plan_sources([declared], [_current(auto_sync=current)]).unchanged == (LIBRARY,)


def test_undeclared_libraries_are_listed_and_marked_only_with_prune() -> None:
    other = _current(library_id="/acme/other", source=_source("https://github.com/acme/other"))

    kept = plan_sources([_declared()], [_current(), other])
    pruned = plan_sources([_declared()], [_current(), other], prune=True)

    assert [c.library_id for c in kept.undeclared] == ["/acme/other"]
    assert (kept.prune, pruned.prune) == (False, True)


def test_undeclared_manual_versions_are_listed_auto_ones_never() -> None:
    current = _current(
        versions=(_version("main"), _version("v0.9"), _version("v2.0", VersionOrigin.AUTO))
    )

    (kept,) = plan_sources([_declared()], [current]).update
    (pruned,) = plan_sources([_declared()], [current], prune=True).update

    assert kept.undeclared_versions == ("v0.9",)
    assert (kept.writes, pruned.writes) == (False, True)


def test_an_id_that_exists_with_another_url_is_a_source_mismatch() -> None:
    current = _current(source=_source("https://github.com/elsewhere/docs"))

    plan = plan_sources([_declared(include=("x/",))], [current])

    (error,) = plan.errors
    assert (error.library_id, error.code) == (LIBRARY, "source_mismatch")
    assert (plan.create, plan.update, plan.unchanged, plan.undeclared) == ((), (), (), ())


def test_a_trailing_git_suffix_or_slash_is_the_same_repository() -> None:
    current = _current(source=_source(URL + ".git"))

    assert plan_sources([_declared(url=RepositoryUrl.parse(URL + "/"))], [current]).unchanged


# --- the schema -----------------------------------------------------------------------------


def _file(**entry: object) -> dict:
    return {"version": 1, "libraries": [{"url": URL, "refs": ["main"], **entry}]}


@pytest.mark.parametrize(
    ("document", "field"),
    [
        (_file(include_path=["docs/"]), "include_path"),  # a typo
        ({"version": 1, "libraries": [{"url": URL, "refs": ["main"]}], "extra": 1}, "extra"),
        (_file(refs=["abc1234"]), "refs"),  # a short SHA
        (_file(refs=[]), "refs"),
        (_file(refs=["main", "main"]), "refs"),
        (_file(credential={"kind": "token", "token": "x"}), "credential"),
        ({"version": 2, "libraries": []}, "version"),
        (_file(auto_sync=True), "auto_sync"),
    ],
)
def test_an_invalid_file_is_refused_naming_the_field(document: dict, field: str) -> None:
    with pytest.raises(ValidationError) as refused:
        SourcesFile.model_validate(document)

    assert field in str(refused.value)


def test_duplicate_ids_are_refused_also_when_derived_from_the_url() -> None:
    document = {
        "version": 1,
        "libraries": [
            {"url": URL, "refs": ["main"]},
            {"url": "https://gitlab.com/x/y", "id": "/Acme/Docs", "refs": ["main"]},
        ],
    }

    with pytest.raises(ValidationError, match="declared twice"):
        SourcesFile.model_validate(document)


def test_a_full_sha_is_a_ref_and_names_and_digits_are_not_short_shas() -> None:
    entry = SourcesFile.model_validate(_file(refs=[SHA.upper(), "deadbeef", "20240101"]))

    assert entry.libraries[0].refs == [SHA, "deadbeef", "20240101"]


def test_the_number_of_libraries_is_capped() -> None:
    libraries = [
        {"url": f"https://github.com/acme/d{i}", "refs": ["main"]} for i in range(MAX_SOURCES + 1)
    ]

    with pytest.raises(ValidationError):
        SourcesFile.model_validate({"version": 1, "libraries": libraries})


def test_auto_sync_false_turns_the_schedule_off() -> None:
    assert SourcesFile.model_validate(_file(auto_sync=False)).libraries[0].auto_sync is False


def test_the_committed_json_schema_is_the_models() -> None:
    committed = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert committed == sources_json_schema(), "run `just sources-schema`"


# --- plan and apply over doubles ------------------------------------------------------------


@dataclass
class _World:
    """An instance in memory, and the write ports that change it (they count their calls)."""

    sources: InMemoryLibrarySources = field(default_factory=InMemoryLibrarySources)
    jobs: InMemoryJobRepository = field(default_factory=InMemoryJobRepository)
    schedules: InMemoryAutoSyncStore = field(default_factory=InMemoryAutoSyncStore)
    writes: list[str] = field(default_factory=list)
    unknown_refs: set[str] = field(default_factory=set)

    async def all(self) -> list[KnownLibrary]:
        return [
            KnownLibrary(library_id=i, source_url=s.url.url)
            for i, s in self.sources.sources.items()
        ]

    async def queue(self, library: str, ref: str) -> str:
        if ref in self.unknown_refs:
            raise UnknownRefError(ref)
        job_id = f"job-{len(self.writes)}"
        await self.jobs.add(
            Job(
                id=JobId(job_id),
                kind=IMPORT_JOB,
                library=library,
                version=ref,
                state=JobState.QUEUED,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        return job_id

    def reader(self) -> SourcesReader:
        return SourcesReader(
            known=self, sources=self.sources, jobs=self.jobs, schedules=self.schedules
        )


@dataclass
class _AddLibrary:
    world: _World

    async def __call__(self, command: AddLibraryCommand) -> AddedLibrary:
        self.world.writes.append(f"add_library {command.library_id}")
        library = command.library_id or ""
        job_id = await self.world.queue(library, command.ref or "")
        self.world.sources.sources[library] = ImportSource(
            url=RepositoryUrl.parse(command.url),
            selection=PathSelection.of(command.include_paths, command.exclude_paths),
            tag_rules=TagRule.many([(r.pattern, r.tag) for r in command.tag_rules]),
            chunking=ChunkingConfig()
            if command.chunking is None
            else ChunkingConfig(split_depth=command.chunking.split_level),
        )
        self.world.sources.versions[library] = []
        return AddedLibrary(
            library_id=library,
            ref=command.ref or "",
            ref_kind=RefKind.BRANCH,
            commit_sha=SHA,
            job_id=job_id,
        )


@dataclass
class _AddVersion:
    world: _World

    async def __call__(self, command: AddVersionCommand) -> AddedVersion:
        self.world.writes.append(f"add_version {command.library} {command.ref}")
        job_id = await self.world.queue(command.library, command.ref)
        return AddedVersion(
            library_id=command.library,
            ref=command.ref,
            ref_kind=RefKind.TAG,
            commit_sha=SHA,
            job_id=job_id,
        )


@dataclass
class _UpdateSettings:
    world: _World

    async def __call__(self, command: UpdateLibrarySettingsCommand) -> UpdatedLibrarySettings:
        self.world.writes.append(f"update_settings {command.library}")
        stored = self.world.sources.sources[command.library]
        chunking = stored.chunking
        if command.chunking is not None:
            chunking = ChunkingConfig(split_depth=command.chunking.split_level)
        self.world.sources.sources[command.library] = ImportSource(
            url=stored.url,
            selection=PathSelection.of(command.include_paths, command.exclude_paths),
            tag_rules=TagRule.many([(r.pattern, r.tag) for r in command.tag_rules]),
            chunking=chunking,
        )
        return UpdatedLibrarySettings(
            library_id=command.library,
            include_paths=command.include_paths,
            exclude_paths=command.exclude_paths,
            tag_rules=command.tag_rules,
            chunking=ChunkingIn.of(chunking),
            reprocess=None,
            job_id="reprocess-1",
            versions=[],
        )


@dataclass
class _SetAutoSync:
    world: _World

    async def __call__(self, command: SetAutoSyncCommand) -> AutoSyncOut:
        self.world.writes.append(f"set_auto_sync {command.library}")
        schedule = AutoSync(library=command.library, tag_pattern=command.tag_pattern)
        await self.world.schedules.save(schedule)
        return AutoSyncOut.from_model(schedule)


@dataclass
class _DisableAutoSync:
    world: _World

    async def __call__(self, command: DisableAutoSyncCommand) -> AutoSyncOut:
        self.world.writes.append(f"disable_auto_sync {command.library}")
        await self.world.schedules.delete(command.library)
        return AutoSyncOut.disabled(command.library)


@dataclass
class _RemoveVersion:
    world: _World

    async def __call__(self, command: RemoveVersionCommand) -> RemovalResult:
        self.world.writes.append(f"remove_version {command.library} {command.ref}")
        versions = self.world.sources.versions[command.library]
        versions[:] = [v for v in versions if v.ref != command.ref]
        return RemovalResult(
            library=command.library, ref=command.ref, default_version=None, collection_job_id="gc-v"
        )


@dataclass
class _RemoveLibrary:
    world: _World

    async def __call__(self, command: RemoveLibraryCommand) -> RemovalResult:
        self.world.writes.append(f"remove_library {command.library}")
        del self.world.sources.sources[command.library]
        return RemovalResult(
            library=command.library, ref=None, default_version=None, collection_job_id="gc"
        )


def _apply(world: _World) -> ApplySourcesUseCase:
    return ApplySourcesUseCase(
        reader=world.reader(),
        add_library=_AddLibrary(world),
        add_version=_AddVersion(world),
        update_library_settings=_UpdateSettings(world),
        set_auto_sync=_SetAutoSync(world),
        disable_auto_sync=_DisableAutoSync(world),
        remove_version=_RemoveVersion(world),
        remove_library=_RemoveLibrary(world),
    )


def _with_library(world: _World, library: str, url: str, refs: Sequence[str] = ("main",)) -> None:
    world.sources.sources[library] = _source(url)
    world.sources.versions[library] = [_version(r) for r in refs]


FILE = SourcesFile.model_validate(
    {
        "version": 1,
        "libraries": [
            {
                "url": URL,
                "refs": ["main", "v1.4.0"],
                "include_paths": [],
                "chunking": {"split_level": 2},
                "auto_sync": {"tag_pattern": "v*"},
            }
        ],
    }
)


async def test_plan_writes_nothing() -> None:
    world = _World()
    _with_library(world, "/acme/other", "https://github.com/acme/other")

    plan = await PlanSourcesUseCase(reader=world.reader())(
        PlanSourcesCommand(sources=FILE, prune=True)
    )

    assert [c.id for c in plan.create] == [LIBRARY]
    assert [(u.library_id, u.will_be_removed) for u in plan.undeclared] == [("/acme/other", True)]
    assert plan.changes
    assert world.writes == []


async def test_apply_creates_then_a_second_apply_writes_nothing() -> None:
    world = _World()

    first = await _apply(world)(ApplySourcesCommand(sources=FILE))
    writes = list(world.writes)
    second = await _apply(world)(ApplySourcesCommand(sources=FILE))

    assert writes == [
        f"add_library {LIBRARY}",
        f"add_version {LIBRARY} v1.4.0",
        f"set_auto_sync {LIBRARY}",
    ]
    assert [(r.library_id, r.action, len(r.jobs)) for r in first.results] == [
        (LIBRARY, "created", 2)
    ]
    assert world.sources.sources[LIBRARY].chunking.split_depth == 2
    assert world.writes == writes  # the imports are still queued: present already
    assert [(r.action, r.jobs) for r in second.results] == [("unchanged", [])]
    assert not second.plan.changes


async def test_apply_creates_with_empty_paths_that_context7_does_not_fill() -> None:
    world = _World()
    seen: list[AddLibraryCommand] = []
    add = _AddLibrary(world)

    @dataclass
    class Spy:
        async def __call__(self, command: AddLibraryCommand) -> AddedLibrary:
            seen.append(command)
            return await add(command)

    await replace(_apply(world), add_library=Spy())(ApplySourcesCommand(sources=FILE))

    assert (seen[0].context7_paths, seen[0].include_paths) == (False, [])


async def test_an_update_sends_only_changes_and_stored_values_for_the_rest() -> None:
    world = _World()
    world.sources.sources[LIBRARY] = _source(include=["docs/"], rules=[("a/**", "a")])
    world.sources.versions[LIBRARY] = [_version("main")]
    file = SourcesFile.model_validate(_file(exclude_paths=["docs/old/"], auto_sync=False))

    applied = await _apply(world)(ApplySourcesCommand(sources=file))

    assert world.writes == [f"update_settings {LIBRARY}"]  # the schedule is off already
    stored = world.sources.sources[LIBRARY]
    assert (stored.selection, stored.tag_rules) == (
        PathSelection.of(["docs/"], ["docs/old/"]),
        TagRule.many([("a/**", "a")]),
    )
    assert [(r.action, r.jobs) for r in applied.results] == [("updated", ["reprocess-1"])]


async def test_without_prune_nothing_is_removed_with_prune_it_is() -> None:
    world = _World()
    _with_library(world, LIBRARY, URL, refs=("main", "v0.9"))
    _with_library(world, "/acme/other", "https://github.com/acme/other")
    file = SourcesFile.model_validate(_file())

    kept = await _apply(world)(ApplySourcesCommand(sources=file))
    assert world.writes == []
    assert {r.action for r in kept.results} == {"unchanged"}

    pruned = await _apply(world)(ApplySourcesCommand(sources=file, prune=True))

    assert world.writes == [f"remove_version {LIBRARY} v0.9", "remove_library /acme/other"]
    assert [(r.library_id, r.action, r.jobs) for r in pruned.results] == [
        (LIBRARY, "updated", ["gc-v"]),
        ("/acme/other", "removed", ["gc"]),
    ]


async def test_one_failing_library_does_not_stop_the_others() -> None:
    world = _World(unknown_refs={"v9"})
    file = SourcesFile.model_validate(
        {
            "version": 1,
            "libraries": [
                {"url": URL, "refs": ["v9"]},
                {"url": "https://github.com/acme/api", "refs": ["main", "v9"]},
                {"url": "https://github.com/acme/web", "refs": ["main"]},
            ],
        }
    )

    applied = await _apply(world)(ApplySourcesCommand(sources=file))

    assert [(r.library_id, r.action, r.error_code) for r in applied.results] == [
        (LIBRARY, "failed", "unknown_ref"),
        ("/acme/api", "created", "unknown_ref"),  # created; its second ref failed
        ("/acme/web", "created", None),
    ]
    assert applied.failed == 2


async def test_a_source_mismatch_is_reported_and_left_alone() -> None:
    world = _World()
    _with_library(world, LIBRARY, "https://github.com/elsewhere/docs")

    applied = await _apply(world)(ApplySourcesCommand(sources=SourcesFile.model_validate(_file())))

    assert world.writes == []
    assert [(r.action, r.error_code) for r in applied.results] == [("failed", "source_mismatch")]


async def test_a_setting_the_server_cannot_store_names_the_entry() -> None:
    world = _World()
    file = SourcesFile.model_validate(_file(include_paths=["../etc"]))

    with pytest.raises(InvalidSourcesError, match=r"libraries\[0\] \(/acme/docs\)"):
        await PlanSourcesUseCase(reader=world.reader())(PlanSourcesCommand(sources=file))
