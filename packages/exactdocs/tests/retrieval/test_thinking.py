"""#421: the thinking level of the llm and judge roles.

A role's level resolves as its model does: the library's own, else the instance's; a judge that
is the LLM thinks as the LLM does. The instance's level comes from the configuration, else from
the REST API. A level a model is known not to take is refused when saved; every call of a role
gets its level through the ``ModelFactory`` port. Test doubles: a factory that records the
levels it is asked for and knows one model that cannot think.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemoryRoleThinkingLevels,
    InMemorySearchIndex,
)
from exactdocs.retrieval.adapters.driven.sqlite import (
    SqliteLibraryModes,
    SqliteRoleThinkingLevels,
)
from exactdocs.retrieval.dtos import (
    GetLibraryRetrievalQuery,
    SetLibraryRetrievalCommand,
    SetRoleThinkingCommand,
)
from exactdocs.retrieval.errors import (
    RoleConfiguredError,
    RoleTakesNoThinkingError,
    ThinkingUnsupportedError,
)
from exactdocs.retrieval.models import (
    CatalogLibrary,
    InstanceRoles,
    LibraryAi,
    ModelCheck,
    ModelRef,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RerankWith,
    RoleSource,
    ThinkingLevel,
    bind_role,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import LibraryModes, Reranker, RoleThinkingLevels
from exactdocs.retrieval.use_cases import AiProviders

LIB = "/acme/payments"
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
GEMINI = ModelRef(profile="corp", model="gemini-4-hydrogen")
JUDGE = ModelRef(profile="corp", model="judge-mini")
FLAT = ModelRef(profile="corp", model="flat-1")
"""A model the fake factory knows cannot take a thinking level."""
LOW, MINIMAL, HIGH = ThinkingLevel.LOW, ThinkingLevel.MINIMAL, ThinkingLevel.HIGH


@dataclass(slots=True)
class RecordingFactory:
    """Records each chat model and check with its level; ``flat-1`` cannot think."""

    chats: list[tuple[str, ThinkingLevel | None]] = field(default_factory=list)
    checks: list[tuple[ModelRole, str, ThinkingLevel | None]] = field(default_factory=list)

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile
        return None

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        del profile
        return "it has no thinking setting" if model == FLAT.model else None

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        del profile
        self.chats.append((model, thinking))
        return object()

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        raise AssertionError((profile, model))

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        raise AssertionError((profile, model))

    async def release(self, name: str) -> None:
        del name

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        self.checks.append((role, model, thinking))
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


class _NoVersions:
    async def find(self, library: str, ref: str | None) -> None:
        del library, ref

    async def active_id(self, target: object) -> None:
        del target

    async def statuses(self, manifest_ids: object) -> dict:
        del manifest_ids
        return {}


@dataclass(slots=True)
class World:
    module: RetrievalModule
    factory: RecordingFactory
    modes: InMemoryLibraryModes
    levels: InMemoryRoleThinkingLevels


def _world(roles: InstanceRoles) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    factory, modes, levels = (
        RecordingFactory(),
        InMemoryLibraryModes(),
        InMemoryRoleThinkingLevels(),
    )
    library = CatalogLibrary(
        id=LIB,
        title="Payments",
        description="Payment SDK",
        source_url="https://github.com/acme/payments",
        default_version="v1",
        versions=("v1",),
        version_count=1,
    )
    module = RetrievalModule.build(
        searchable=_NoVersions(),
        libraries=InMemoryLibraries(libraries=[library]),
        defaults=InMemoryDefaultVersions(),
        manifests=_NoVersions(),
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=(CORP,),
        instance_roles=roles,
        models=factory,
        thinking_levels=levels,
    )
    return World(module=module, factory=factory, modes=modes, levels=levels)


# ---------------------------------------------------------------- resolution


def test_a_role_without_a_level_keeps_the_providers_default() -> None:
    binding = bind_role(ModelRole.LLM, InstanceRoles(llm=GEMINI), LibraryAi())

    assert binding is not None
    assert binding.thinking is None


def test_the_librarys_level_wins_over_the_instances() -> None:
    instance = InstanceRoles(llm=GEMINI, llm_thinking=LOW)

    own = bind_role(ModelRole.LLM, instance, LibraryAi(llm_thinking=HIGH))
    other = bind_role(ModelRole.LLM, instance, LibraryAi())

    assert own is not None
    assert own.thinking is HIGH
    assert other is not None
    assert other.thinking is LOW


def test_a_judge_that_is_the_llm_thinks_as_the_llm_unless_it_has_its_own_level() -> None:
    instance = InstanceRoles(llm=GEMINI, llm_thinking=LOW)

    as_llm = bind_role(ModelRole.JUDGE, instance, LibraryAi())
    own = bind_role(ModelRole.JUDGE, instance, LibraryAi(judge_thinking=MINIMAL))

    assert as_llm is not None
    assert (as_llm.source, as_llm.thinking) == (RoleSource.LLM, LOW)
    assert own is not None
    assert (own.source, own.thinking) == (RoleSource.LLM, MINIMAL)


def test_a_judge_of_its_own_does_not_take_the_llms_level() -> None:
    instance = InstanceRoles(llm=GEMINI, llm_thinking=LOW, judge=JUDGE)

    binding = bind_role(ModelRole.JUDGE, instance, LibraryAi())

    assert binding is not None
    assert (binding.ref, binding.thinking) == (JUDGE, None)


def test_only_the_chat_roles_think() -> None:
    assert [r for r in ModelRole if r.thinks] == [ModelRole.LLM, ModelRole.JUDGE]
    assert LibraryAi(llm_thinking=LOW).thinking(ModelRole.EMBEDDING) is None
    assert not LibraryAi(judge_thinking=LOW).is_default


# ---------------------------------------------------------------- calls


async def test_every_call_of_a_role_gets_the_level_that_applies_to_the_library() -> None:
    roles = InstanceRoles(llm=GEMINI, llm_thinking=LOW)
    world = _world(roles)
    providers = AiProviders(  # what an AI pipeline holds, as the module builds it
        configured=(CORP,),
        roles=roles,
        library_modes=world.modes,
        factory=world.factory,
        thinking_levels=world.levels,
    )

    await providers.model_for(ModelRole.LLM, LIB)
    await world.modes.save(LIB, None, LibraryAi(llm_thinking=MINIMAL))
    await providers.model_for(ModelRole.LLM, LIB)
    await providers.model_for(ModelRole.LLM, "/other/lib")

    assert world.factory.chats == [
        (GEMINI.model, LOW),
        (GEMINI.model, MINIMAL),
        (GEMINI.model, LOW),
    ]


async def test_ai_check_calls_each_role_with_its_level() -> None:
    world = _world(InstanceRoles(llm=GEMINI, llm_thinking=LOW, judge=JUDGE))
    await world.levels.save(ModelRole.JUDGE, MINIMAL)

    await world.module.check_roles()

    assert world.factory.checks == [
        (ModelRole.LLM, GEMINI.model, LOW),
        (ModelRole.JUDGE, JUDGE.model, MINIMAL),
    ]


# ---------------------------------------------------------------- instance roles


async def test_the_roles_show_each_level_and_where_it_is_set() -> None:
    world = _world(InstanceRoles(llm=GEMINI, llm_thinking=LOW))

    roles = {r.role: r for r in (await world.module.list_roles()).roles}

    assert (roles[ModelRole.LLM].thinking, roles[ModelRole.LLM].thinking_configured) == (
        LOW,
        True,
    )
    assert (roles[ModelRole.JUDGE].thinking, roles[ModelRole.JUDGE].thinking_configured) == (
        LOW,
        False,
    )
    assert roles[ModelRole.EMBEDDING].thinking is None
    # The judge thinks as the LLM, with no level of its own to edit.
    assert (roles[ModelRole.LLM].own_thinking, roles[ModelRole.JUDGE].own_thinking) == (LOW, None)


async def test_an_admin_sets_and_clears_a_roles_level_over_the_api() -> None:
    world = _world(InstanceRoles(llm=GEMINI, judge=JUDGE))
    set_level = world.module.set_role_thinking

    shown = await set_level(SetRoleThinkingCommand(role=ModelRole.JUDGE, thinking=MINIMAL))
    assert (shown.thinking, shown.thinking_configured) == (MINIMAL, False)
    await world.module.check_roles()
    cleared = await set_level(SetRoleThinkingCommand(role=ModelRole.JUDGE, thinking=None))

    assert cleared.thinking is None
    assert await world.levels.levels() == {}
    assert (ModelRole.JUDGE, JUDGE.model, MINIMAL) in world.factory.checks


async def test_a_level_set_in_the_configuration_cannot_be_changed_over_the_api() -> None:
    world = _world(InstanceRoles(llm=GEMINI, llm_thinking=LOW))

    with pytest.raises(RoleConfiguredError, match="EXACTDOCS_AI__LLM__THINKING"):
        await world.module.set_role_thinking(
            SetRoleThinkingCommand(role=ModelRole.LLM, thinking=HIGH)
        )
    assert await world.levels.levels() == {}


async def test_a_role_that_does_not_think_takes_no_level() -> None:
    world = _world(InstanceRoles(llm=GEMINI))

    with pytest.raises(RoleTakesNoThinkingError):
        await world.module.set_role_thinking(
            SetRoleThinkingCommand(role=ModelRole.RERANKER, thinking=LOW)
        )


async def test_a_level_the_roles_model_cannot_take_is_refused_naming_role_and_model() -> None:
    world = _world(InstanceRoles(llm=FLAT))

    with pytest.raises(ThinkingUnsupportedError) as refused:
        await world.module.set_role_thinking(
            SetRoleThinkingCommand(role=ModelRole.LLM, thinking=HIGH)
        )

    assert "the llm role's model 'corp:flat-1'" in str(refused.value)
    assert await world.levels.levels() == {}


async def test_the_roles_say_when_a_configured_level_cannot_be_taken() -> None:
    world = _world(InstanceRoles(llm=FLAT, llm_thinking=HIGH))

    roles = {r.role: r for r in (await world.module.list_roles()).roles}

    assert roles[ModelRole.LLM].thinking_unsupported == "it has no thinking setting"


# ---------------------------------------------------------------- a library's own level


async def test_a_library_stores_its_own_levels_and_shows_them() -> None:
    world = _world(InstanceRoles(llm=GEMINI, llm_thinking=LOW))

    saved = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(
            library=LIB, judge=str(JUDGE), judge_thinking=MINIMAL, rerank_with=RerankWith.JUDGE
        )
    )
    shown = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))

    assert (saved.llm_thinking, saved.judge_thinking) == (None, MINIMAL)
    assert shown == saved
    assert (await world.modes.ai_of(LIB)).judge_thinking is MINIMAL


async def test_a_librarys_level_its_model_cannot_take_is_refused() -> None:
    world = _world(InstanceRoles(llm=GEMINI))

    with pytest.raises(ThinkingUnsupportedError) as refused:
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library=LIB, llm=str(FLAT), llm_thinking=HIGH)
        )

    assert "the llm role's model 'corp:flat-1'" in str(refused.value)
    assert await world.modes.ai_of(LIB) == LibraryAi()


async def test_a_library_is_not_refused_for_the_instances_level() -> None:
    # The instance's level was checked when it was set; a library's own model that cannot take
    # it is not the library's mistake: its calls leave the level out.
    world = _world(InstanceRoles(llm=GEMINI, llm_thinking=LOW))

    saved = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, llm=str(FLAT))
    )

    assert saved.llm == str(FLAT)


# ---------------------------------------------------------------- stores


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def stores(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[RoleThinkingLevels, LibraryModes]]:
    if request.param == "memory":
        yield InMemoryRoleThinkingLevels(), InMemoryLibraryModes()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield (
            SqliteRoleThinkingLevels(engine=container.engine),
            SqliteLibraryModes(engine=container.engine),
        )


async def test_the_roles_levels_are_stored_and_cleared(
    stores: tuple[RoleThinkingLevels, LibraryModes],
) -> None:
    levels, _ = stores

    await levels.save(ModelRole.LLM, LOW)
    await levels.save(ModelRole.JUDGE, HIGH)
    await levels.save(ModelRole.JUDGE, MINIMAL)
    assert await levels.levels() == {ModelRole.LLM: LOW, ModelRole.JUDGE: MINIMAL}
    await levels.save(ModelRole.LLM, None)

    assert await levels.levels() == {ModelRole.JUDGE: MINIMAL}


async def test_a_librarys_own_levels_are_stored_with_it(
    stores: tuple[RoleThinkingLevels, LibraryModes],
) -> None:
    _, modes = stores
    ai = LibraryAi(llm_thinking=LOW, judge_thinking=ThinkingLevel.XHIGH)

    await modes.save(LIB, None, ai)

    assert await modes.ai_of(LIB) == ai
