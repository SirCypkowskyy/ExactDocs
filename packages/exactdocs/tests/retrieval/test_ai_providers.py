"""RET-01..03, RET-06: AI provider profiles, model roles and per-library overrides (#241).

Retrieval owns the profiles (configured ones read-only, stored ones over the REST API), resolves
which profile and model a role uses for a library, and reaches models only through the
``ModelFactory`` port. Test doubles: a fake factory and a reversible secret box.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemoryProviderProfiles,
    InMemorySearchIndex,
)
from exactdocs.retrieval.adapters.driven.sqlite import SqliteLibraryModes, SqliteProviderProfiles
from exactdocs.retrieval.dtos import (
    CheckProviderCommand,
    GetLibraryRetrievalQuery,
    ProviderNameQuery,
    SaveProviderCommand,
    SetLibraryRetrievalCommand,
)
from exactdocs.retrieval.errors import (
    InvalidModelRefError,
    InvalidProviderError,
    NothingToCheckError,
    ProviderExistsError,
    ProviderInUseError,
    ProviderReadOnlyError,
    ProviderUnsupportedError,
    SecretKeyRequiredError,
    UnavailableModeError,
    UnknownProviderError,
)
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    AzureAuth,
    BudgetLimit,
    CatalogLibrary,
    InstanceRoles,
    KeySource,
    LibraryAi,
    ModelCheck,
    ModelRef,
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RerankWith,
    RetrievalMode,
    RoleSource,
    SpendWindow,
    ThinkingLevel,
    bind_role,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import LibraryModes, ProviderProfiles
from exactdocs.retrieval.use_cases import AiProviders

LIB = "/acme/payments"
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
EMBED = ModelRef(profile="corp", model="text-embedding-3-small")
CHAT = ModelRef(profile="corp", model="gpt-4.1-mini")


# ---------------------------------------------------------------- profiles


def _profile(**fields: Any) -> ProviderProfile:
    values: dict[str, Any] = {"name": "p", "kind": ProviderKind.OPENAI_COMPATIBLE}
    values.update(fields)
    return ProviderProfile(**values)


VALID = {
    "gateway without a key": {"base_url": "https://llm.example.com/v1"},
    "openai with a key": {"kind": ProviderKind.OPENAI, "key": KeySource.ENVIRONMENT},
    "azure with a key": {
        "kind": ProviderKind.AZURE,
        "base_url": "https://x.openai.azure.com",
        "api_version": "2024-10-21",
        "key": KeySource.FILE,
        "key_file": "/run/secrets/k",
    },
    "azure with entra": {
        "kind": ProviderKind.AZURE,
        "origin": ProfileOrigin.CONFIGURATION,
        "resource": "acme",
        "api_version": "2024-10-21",
        "auth": AzureAuth.ENTRA,
    },
    "vertex with a service account": {
        "kind": ProviderKind.GOOGLE_VERTEX,
        "origin": ProfileOrigin.CONFIGURATION,
        "project": "acme-ml",
        "location": "europe-west4",
        "credentials_file": "/run/secrets/vertex.json",
    },
    "vertex with adc": {
        "kind": ProviderKind.GOOGLE_VERTEX,
        "origin": ProfileOrigin.CONFIGURATION,
        "project": "acme-ml",
        "location": "global",
        "adc": True,
    },
    "vertex express": {"kind": ProviderKind.GOOGLE_VERTEX, "key": KeySource.ENVIRONMENT},
    "claude": {"kind": ProviderKind.ANTHROPIC, "key": KeySource.ENVIRONMENT},
    "claude on vertex": {
        "kind": ProviderKind.ANTHROPIC,
        "origin": ProfileOrigin.CONFIGURATION,
        "platform": AnthropicPlatform.VERTEX,
        "project": "acme-ml",
        "location": "us-east5",
        "adc": True,
    },
    "claude on foundry with entra": {
        "kind": ProviderKind.ANTHROPIC,
        "origin": ProfileOrigin.CONFIGURATION,
        "platform": AnthropicPlatform.FOUNDRY,
        "resource": "acme",
        "auth": AzureAuth.ENTRA,
    },
    "claude on bedrock": {
        "kind": ProviderKind.ANTHROPIC,
        "origin": ProfileOrigin.CONFIGURATION,
        "platform": AnthropicPlatform.BEDROCK,
        "location": "eu-central-1",
    },
    "local": {"kind": ProviderKind.LOCAL},
}


@pytest.mark.parametrize("fields", VALID.values(), ids=VALID.keys())
def test_a_valid_profile_of_each_kind_is_accepted(fields: dict[str, object]) -> None:
    assert _profile(**fields).name == "p"


INVALID = {
    "upper-case name": ({"name": "Corp", "base_url": "https://x"}, "the name"),
    "gateway without base_url": ({}, "needs base_url"),
    "ftp base_url": ({"base_url": "ftp://x"}, "base_url must be"),
    "hosted without a key": ({"kind": ProviderKind.OPENAI}, "needs a key"),
    "azure without api_version": (
        {"kind": ProviderKind.AZURE, "base_url": "https://x", "key": KeySource.ENVIRONMENT},
        "api_version",
    ),
    "azure entra with a key": (
        {
            "origin": ProfileOrigin.CONFIGURATION,
            "kind": ProviderKind.AZURE,
            "resource": "acme",
            "api_version": "v",
            "auth": AzureAuth.ENTRA,
            "key": KeySource.ENVIRONMENT,
        },
        "takes no key",
    ),
    "vertex with two credentials": (
        {
            "origin": ProfileOrigin.CONFIGURATION,
            "kind": ProviderKind.GOOGLE_VERTEX,
            "project": "p",
            "location": "l",
            "adc": True,
            "credentials_file": "/f",
        },
        "exactly one",
    ),
    "vertex without project": (
        {
            "origin": ProfileOrigin.CONFIGURATION,
            "kind": ProviderKind.GOOGLE_VERTEX,
            "location": "l",
            "adc": True,
        },
        "project and location",
    ),
    "claude on vertex with a key": (
        {
            "origin": ProfileOrigin.CONFIGURATION,
            "kind": ProviderKind.ANTHROPIC,
            "platform": AnthropicPlatform.VERTEX,
            "project": "p",
            "location": "l",
            "key": KeySource.ENVIRONMENT,
        },
        "exactly one",
    ),
    "foundry with base_url and resource": (
        {
            "kind": ProviderKind.ANTHROPIC,
            "platform": AnthropicPlatform.FOUNDRY,
            "base_url": "https://x",
            "resource": "r",
            "key": KeySource.ENVIRONMENT,
        },
        "not both",
    ),
    "a field of another kind": (
        {"base_url": "https://x", "project": "acme"},
        "project does not apply",
    ),
    "platform on another kind": (
        {"base_url": "https://x", "platform": AnthropicPlatform.API},
        "platform applies",
    ),
    "header with a line break": (
        {"base_url": "https://x", "headers": (("X-Team", "a\r\nInjected: 1"),)},
        "line break",
    ),
    "adc over the api": (
        {"kind": ProviderKind.GOOGLE_VERTEX, "project": "p", "location": "l", "adc": True},
        "configure them in the environment",
    ),
    "a service-account file over the api": (
        {
            "kind": ProviderKind.GOOGLE_VERTEX,
            "project": "p",
            "location": "l",
            "credentials_file": "/etc/shadow",
        },
        "configure them in the environment",
    ),
    "entra over the api": (
        {"kind": ProviderKind.AZURE, "resource": "r", "api_version": "v", "auth": AzureAuth.ENTRA},
        "configure them in the environment",
    ),
    "adc with a base_url": (
        {
            "kind": ProviderKind.GOOGLE_VERTEX,
            "origin": ProfileOrigin.CONFIGURATION,
            "base_url": "https://evil.example/",
            "project": "p",
            "location": "l",
            "adc": True,
        },
        "takes no base_url",
    ),
    "entra with a base_url": (
        {
            "kind": ProviderKind.AZURE,
            "origin": ProfileOrigin.CONFIGURATION,
            "base_url": "https://evil.example/",
            "api_version": "v",
            "auth": AzureAuth.ENTRA,
        },
        "takes no base_url",
    ),
    "foundry entra with a base_url": (
        {
            "kind": ProviderKind.ANTHROPIC,
            "origin": ProfileOrigin.CONFIGURATION,
            "platform": AnthropicPlatform.FOUNDRY,
            "base_url": "https://evil.example/",
            "auth": AzureAuth.ENTRA,
        },
        "takes no base_url",
    ),
    "azure with base_url and resource": (
        {
            "kind": ProviderKind.AZURE,
            "base_url": "https://x",
            "resource": "r",
            "api_version": "v",
            "key": KeySource.ENVIRONMENT,
        },
        "not both",
    ),
    "an authorization header": (
        {"base_url": "https://x", "headers": (("Authorization", "Bearer s"),)},
        "use the key field",
    ),
    "a key header": (
        {"base_url": "https://x", "headers": (("X-Portkey-Api-Key", "s"),)},
        "use the key field",
    ),
    "a token header": (
        {"base_url": "https://x", "headers": (("X-Gateway-Token", "s"),)},
        "use the key field",
    ),
    "a cookie": ({"base_url": "https://x", "headers": (("Cookie", "s=1"),)}, "use the key field"),
    "timeout too long": ({"base_url": "https://x", "request_timeout": 6000.0}, "request_timeout"),
}


@pytest.mark.parametrize(("fields", "reason"), INVALID.values(), ids=INVALID.keys())
def test_an_invalid_profile_is_refused_with_its_reason(
    fields: dict[str, object], reason: str
) -> None:
    with pytest.raises(InvalidProviderError, match=reason):
        _profile(**fields)


INJECTIONS = ["evil.example/x?", "a.evil.com", "x@evil", "x%2Fevil", "evil.example#", "-x"]
DERIVED = {
    "azure resource": (
        {"kind": ProviderKind.AZURE, "api_version": "v", "key": KeySource.ENVIRONMENT},
        "resource",
    ),
    "foundry resource": (
        {
            "kind": ProviderKind.ANTHROPIC,
            "platform": AnthropicPlatform.FOUNDRY,
            "key": KeySource.ENVIRONMENT,
        },
        "resource",
    ),
    "vertex location": (
        {
            "kind": ProviderKind.GOOGLE_VERTEX,
            "origin": ProfileOrigin.CONFIGURATION,
            "project": "p",
            "adc": True,
        },
        "location",
    ),
    "vertex project": (
        {
            "kind": ProviderKind.GOOGLE_VERTEX,
            "origin": ProfileOrigin.CONFIGURATION,
            "location": "global",
            "adc": True,
        },
        "project",
    ),
    "claude on vertex location": (
        {
            "kind": ProviderKind.ANTHROPIC,
            "origin": ProfileOrigin.CONFIGURATION,
            "platform": AnthropicPlatform.VERTEX,
            "project": "p",
            "adc": True,
        },
        "location",
    ),
    "bedrock region": (
        {
            "kind": ProviderKind.ANTHROPIC,
            "origin": ProfileOrigin.CONFIGURATION,
            "platform": AnthropicPlatform.BEDROCK,
        },
        "location",
    ),
}


@pytest.mark.parametrize("injection", INJECTIONS)
@pytest.mark.parametrize(("fields", "field_name"), DERIVED.values(), ids=DERIVED.keys())
def test_a_field_that_builds_an_endpoint_is_one_dns_label(
    fields: dict[str, Any], field_name: str, injection: str
) -> None:
    with pytest.raises(InvalidProviderError, match=f"{field_name} must be a single name"):
        _profile(**fields, **{field_name: injection})


def test_claude_on_bedrock_is_the_servers_aws_identity_so_configuration_only() -> None:
    bedrock = {
        "kind": ProviderKind.ANTHROPIC,
        "platform": AnthropicPlatform.BEDROCK,
        "location": "eu-central-1",
    }

    with pytest.raises(InvalidProviderError, match="configure them in the environment"):
        _profile(**bedrock)
    with pytest.raises(InvalidProviderError, match="takes no base_url"):
        _profile(**bedrock, origin=ProfileOrigin.CONFIGURATION, base_url="https://evil.example")
    assert _profile(**bedrock, origin=ProfileOrigin.CONFIGURATION).uses_ambient_identity


def test_a_kind_whose_sdk_is_not_included_points_to_the_openai_compatible_endpoint() -> None:
    with pytest.raises(InvalidProviderError, match="openai-compatible"):
        ProviderKind.parse("p", "groq")


def test_the_repr_of_a_profile_shows_no_secret() -> None:
    profile = _profile(
        base_url="https://x",
        key=KeySource.SEALED,
        sealed_key="sealed-secret",
        headers=(("X-Team", "header-secret"),),
        proxy="http://user:proxy-secret@proxy.example.com:3128",
    )

    shown = repr(profile)

    assert not {"sealed-secret", "header-secret", "proxy-secret"} & set(shown.split("'"))
    assert "proxy-secret" not in shown
    assert profile.shown_proxy == "http://user:***@proxy.example.com:3128"
    assert profile.header_names == ("X-Team",)


# ---------------------------------------------------------------- roles


def test_a_model_ref_keeps_colons_in_the_model() -> None:
    assert ModelRef.parse("Ollama:llama3.1:8b") == ModelRef(profile="ollama", model="llama3.1:8b")


@pytest.mark.parametrize("text", ["gpt-4.1", ":gpt", "corp:", "bad name:gpt"])
def test_a_model_ref_must_be_profile_colon_model(text: str) -> None:
    with pytest.raises(InvalidModelRefError):
        ModelRef.parse(text)


def test_the_judge_defaults_to_the_llm() -> None:
    binding = bind_role(ModelRole.JUDGE, InstanceRoles(llm=CHAT), LibraryAi())

    assert binding is not None
    assert (binding.ref, binding.source) == (CHAT, RoleSource.LLM)


def test_a_library_override_wins_except_for_the_embedding() -> None:
    own = ModelRef(profile="other", model="small")
    roles = InstanceRoles(embedding=EMBED, llm=CHAT)
    library = LibraryAi(llm=own)

    llm = bind_role(ModelRole.LLM, roles, library)
    judge = bind_role(ModelRole.JUDGE, roles, library)
    embedding = bind_role(ModelRole.EMBEDDING, roles, library)

    assert llm is not None
    assert llm.ref == own
    assert judge is not None
    assert judge.ref == own  # the library's LLM, as its judge
    assert embedding is not None
    assert embedding.ref == EMBED


def test_a_library_with_ai_off_has_no_role() -> None:
    roles = InstanceRoles(embedding=EMBED, reranker=CHAT, llm=CHAT, judge=CHAT)

    assert not [r for r in ModelRole if bind_role(r, roles, LibraryAi(enabled=False))]


# ---------------------------------------------------------------- the module


class ReversibleBox:
    """Seals by wrapping: enough to see that only sealed text is stored."""

    def seal(self, plaintext: str) -> str:
        return f"sealed({plaintext[::-1]})"

    def open(self, sealed: str) -> str:
        return sealed.removeprefix("sealed(").removesuffix(")")[::-1]


@dataclass(slots=True)
class FakeFactory:
    """Records the profiles it builds models from; answers every check with ``ok``."""

    built: list[tuple[ProviderProfile, str]] = field(default_factory=list)
    unsupported_kinds: set[ProviderKind] = field(default_factory=set)
    released: list[str] = field(default_factory=list)

    async def release(self, name: str) -> None:
        self.released.append(name)

    def unsupported(self, profile: ProviderProfile) -> str | None:
        return "not installed" if profile.kind in self.unsupported_kinds else None

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        """Know of no model that cannot think.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            ``None``.
        """
        del profile, model
        return None

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        del thinking
        self.built.append((profile, model))
        return ("chat", profile.base_url, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        self.built.append((profile, model))
        return ("embedder", profile.base_url, model)

    async def reranker(self, profile: ProviderProfile, model: str) -> NamedReranker:
        self.built.append((profile, model))
        return NamedReranker(base_url=profile.base_url, model=model)

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        del thinking
        self.built.append((profile, model))
        dimensions = 3 if role is ModelRole.EMBEDDING else None
        return ModelCheck(
            role=role,
            profile=profile.name,
            model=model,
            ok=True,
            latency_ms=1.0,
            served_model=model,
            dimensions=dimensions,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class NamedReranker:
    """A reranker that says which profile endpoint and model it was built for."""

    base_url: str | None
    model: str

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        del query
        return [0.0] * len(documents)


class StandIn:
    """Answers ``hybrid`` (no hits) and records that it ran: what a hybrid pipeline would send."""

    def __init__(self) -> None:
        self.runs: list[PipelineRequest] = []

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        self.runs.append(request)
        return PipelineAnswer(
            mode=RetrievalMode.HYBRID, hits=(), candidates=0, reranked=0, complete=True
        )


@dataclass(slots=True)
class World:
    module: RetrievalModule
    factory: FakeFactory
    stored: InMemoryProviderProfiles
    modes: InMemoryLibraryModes
    hybrid: StandIn


def _world(
    *,
    roles: InstanceRoles | None = None,
    box: ReversibleBox | None = None,
    configured: tuple[ProviderProfile, ...] = (CORP,),
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    factory, stored, modes, hybrid = (
        FakeFactory(),
        InMemoryProviderProfiles(),
        InMemoryLibraryModes(),
        StandIn(),
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
        configured_profiles=configured,
        stored_profiles=stored,
        instance_roles=roles or InstanceRoles(),
        models=factory,
        secret_box=box,
        pipelines={RetrievalMode.HYBRID: hybrid},
    )
    return World(module=module, factory=factory, stored=stored, modes=modes, hybrid=hybrid)


class _NoVersions:
    async def find(self, library: str, ref: str | None) -> None:
        del library, ref

    async def active_id(self, target: object) -> None:
        del target

    async def statuses(self, manifest_ids: object) -> dict:
        del manifest_ids
        return {}


def _save(name: str = "gw", **fields: object) -> SaveProviderCommand:
    values: dict[str, object] = {
        "name": name,
        "kind": "openai-compatible",
        "base_url": "https://gw.example.com/v1",
    }
    values.update(fields)
    return SaveProviderCommand.model_validate(values)


async def test_a_key_sent_over_the_api_is_stored_sealed_and_never_returned() -> None:
    world = _world(box=ReversibleBox())

    shown = await world.module.save_provider(_save(api_key=SecretStr("sk-live-123")))

    stored = await world.stored.get("gw")
    assert stored is not None
    assert (stored.key, stored.sealed_key) == (KeySource.SEALED, "sealed(321-evil-ks)")
    assert shown.key is KeySource.SEALED
    assert "sk-live-123" not in shown.model_dump_json()


async def test_a_key_is_refused_when_nothing_can_seal_it() -> None:
    world = _world(box=None)

    with pytest.raises(SecretKeyRequiredError):
        await world.module.save_provider(_save(api_key=SecretStr("sk")))

    assert await world.stored.get("gw") is None


async def test_a_profile_without_a_key_needs_no_secret_key() -> None:
    world = _world(box=None)

    shown = await world.module.save_provider(_save())

    assert (shown.key, shown.origin, shown.read_only) == (KeySource.NONE, ProfileOrigin.API, False)


async def test_a_replaced_profile_keeps_its_key_while_the_endpoint_stays() -> None:
    world = _world(box=ReversibleBox())
    await world.module.save_provider(_save(api_key=SecretStr("sk")))

    await world.module.save_provider(_save(request_timeout=10))

    stored = await world.stored.get("gw")
    assert stored is not None
    assert stored.key is KeySource.SEALED
    assert stored.request_timeout == 10


async def test_the_stored_key_never_follows_a_profile_to_another_endpoint() -> None:
    world = _world(box=ReversibleBox())
    await world.module.save_provider(_save(api_key=SecretStr("sk")))

    with pytest.raises(InvalidProviderError, match="endpoint changed"):
        await world.module.save_provider(_save(base_url="https://attacker.example.com/v1"))

    moved = await world.module.save_provider(
        _save(base_url="https://attacker.example.com/v1", keep_key=False)
    )
    assert moved.key is KeySource.NONE


async def test_a_configured_profile_is_read_only_over_the_api() -> None:
    world = _world()

    with pytest.raises(ProviderReadOnlyError):
        await world.module.save_provider(_save(name="corp"))
    with pytest.raises(ProviderReadOnlyError):
        await world.module.delete_provider(ProviderNameQuery(name="corp"))


async def test_creating_an_existing_profile_conflicts() -> None:
    world = _world()
    await world.module.save_provider(_save())

    with pytest.raises(ProviderExistsError):
        await world.module.save_provider(_save(create=True))


async def test_a_profile_this_installation_cannot_call_is_refused() -> None:
    world = _world()
    world.factory.unsupported_kinds.add(ProviderKind.LOCAL)

    with pytest.raises(ProviderUnsupportedError):
        await world.module.save_provider(SaveProviderCommand(name="offline", kind="local"))


async def test_the_list_shows_configured_profiles_first_with_their_roles() -> None:
    world = _world(roles=InstanceRoles(llm=CHAT))
    await world.module.save_provider(_save(name="aaa"))

    listed = (await world.module.list_providers()).providers

    assert [(p.name, p.read_only, p.roles) for p in listed] == [
        ("corp", True, [ModelRole.LLM, ModelRole.JUDGE]),
        ("aaa", False, []),
    ]


async def test_a_profile_an_instance_role_uses_cannot_be_deleted() -> None:
    gateway = ModelRef(profile="gw", model="m")
    world = _world(roles=InstanceRoles(reranker=gateway))
    await world.module.save_provider(_save())

    with pytest.raises(ProviderInUseError, match="reranker"):
        await world.module.delete_provider(ProviderNameQuery(name="gw"))


async def test_deleting_a_profile_releases_its_client() -> None:
    world = _world()
    await world.module.save_provider(_save())

    await world.module.delete_provider(ProviderNameQuery(name="gw"))

    assert world.factory.released == ["gw"]


async def test_deleting_an_unknown_profile_is_not_found() -> None:
    with pytest.raises(UnknownProviderError):
        await _world().module.delete_provider(ProviderNameQuery(name="nope"))


async def test_ai_check_calls_every_role_once_and_reports_dimensions() -> None:
    world = _world(roles=InstanceRoles(embedding=EMBED, llm=CHAT))

    checks = (await world.module.check_roles()).checks

    assert [(c.role, c.status, c.model, c.dimensions) for c in checks] == [
        (ModelRole.EMBEDDING, "ok", "text-embedding-3-small", 3),
        (ModelRole.LLM, "ok", "gpt-4.1-mini", None),
        (ModelRole.JUDGE, "ok", "gpt-4.1-mini", None),
    ]


async def test_a_role_naming_a_missing_profile_fails_its_check_without_calling() -> None:
    world = _world(roles=InstanceRoles(llm=ModelRef(profile="ghost", model="m")))

    (check, _judge) = (await world.module.check_roles()).checks

    assert (check.status, check.error) == ("error", "no AI provider 'ghost'")
    assert world.factory.built == []


async def test_checking_a_profile_no_role_uses_needs_a_model() -> None:
    world = _world()

    with pytest.raises(NothingToCheckError):
        await world.module.check_provider(CheckProviderCommand(name="corp"))
    named = await world.module.check_provider(
        CheckProviderCommand(name="corp", role=ModelRole.EMBEDDING, model="e5")
    )
    assert [c.dimensions for c in named.checks] == [3]


async def test_a_profile_edited_over_the_api_counts_at_the_next_call() -> None:
    roles = InstanceRoles(llm=ModelRef(profile="gw", model="m"))
    world = _world(roles=roles)
    providers = _providers(world, roles)
    await world.module.save_provider(_save(base_url="https://one.example.com/v1"))
    assert await providers.model_for(ModelRole.LLM, LIB) == (
        "chat",
        "https://one.example.com/v1",
        "m",
    )

    await world.module.save_provider(_save(base_url="https://two.example.com/v1"))

    assert await providers.model_for(ModelRole.LLM, LIB) == (
        "chat",
        "https://two.example.com/v1",
        "m",
    )


def _providers(world: World, roles: InstanceRoles | None = None) -> AiProviders:
    """What an AI pipeline holds: the same stored profiles, overrides and factory as the module."""
    return AiProviders(
        configured=(CORP,),
        stored=world.stored,
        roles=roles or InstanceRoles(),
        library_modes=world.modes,
        factory=world.factory,
    )


# ---------------------------------------------------------------- per-library overrides


async def test_a_library_with_ai_off_answers_bm25_and_sends_nothing() -> None:
    world = _world(roles=InstanceRoles(embedding=EMBED, llm=CHAT))
    before = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))
    assert RetrievalMode.HYBRID in before.available_modes

    after = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, ai_enabled=False)
    )

    assert (after.effective_mode, after.configured_roles, after.ai_enabled) == (
        RetrievalMode.BM25,
        [],
        False,
    )
    pipeline_view = _providers(world, InstanceRoles(embedding=EMBED, llm=CHAT))
    assert await pipeline_view.model_for(ModelRole.EMBEDDING, LIB) is None
    assert world.factory.built == []


async def test_a_mode_is_checked_against_the_overrides_set_with_it() -> None:
    world = _world(roles=InstanceRoles(embedding=EMBED))

    with pytest.raises(UnavailableModeError):
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library=LIB, mode="hybrid", ai_enabled=False)
        )

    assert await world.modes.ai_of(LIB) == LibraryAi()


async def test_a_library_override_names_an_existing_profile() -> None:
    world = _world(roles=InstanceRoles(llm=CHAT))

    with pytest.raises(UnknownProviderError):
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library=LIB, llm="ghost:gpt")
        )
    shown = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, judge="corp:o3")
    )

    assert (shown.llm, shown.judge) == (None, "corp:o3")


async def test_a_library_override_names_a_profile_this_installation_can_call() -> None:
    world = _world(roles=InstanceRoles(llm=CHAT))
    world.factory.unsupported_kinds.add(ProviderKind.OPENAI_COMPATIBLE)

    with pytest.raises(ProviderUnsupportedError, match="not installed") as raised:
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library=LIB, reranker="corp:bge")
        )

    assert raised.value.code == "provider_unsupported"
    assert await world.modes.ai_of(LIB) == LibraryAi()  # nothing was stored


async def test_a_library_override_brings_a_role_the_instance_lacks() -> None:
    world = _world()

    shown = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, llm="corp:gpt")
    )

    assert shown.configured_roles == [ModelRole.LLM, ModelRole.JUDGE]


# ---------------------------------------------------------------- the stores (adapter contract)


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def stores(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[ProviderProfiles, LibraryModes]]:
    if request.param == "memory":
        yield InMemoryProviderProfiles(), InMemoryLibraryModes()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield (
            SqliteProviderProfiles(engine=container.engine),
            SqliteLibraryModes(engine=container.engine),
        )


async def test_a_stored_profile_comes_back_as_it_was(
    stores: tuple[ProviderProfiles, LibraryModes],
) -> None:
    profiles, _ = stores
    profile = ProviderProfile(
        name="claude",
        kind=ProviderKind.ANTHROPIC,
        platform=AnthropicPlatform.FOUNDRY,
        resource="acme",
        auth=AzureAuth.KEY,
        key=KeySource.SEALED,
        sealed_key="gAAAA-sealed",
        headers=(("X-Team", "docs"), ("X-Env", "prod")),
        proxy="http://proxy.example.com:3128",
        request_timeout=12.5,
        max_retries=0,
    )

    await profiles.save(profile)
    await profiles.save(replace(profile, name="other", sealed_key="gAAAA-other"))

    assert await profiles.get("claude") == profile
    assert [p.name for p in await profiles.all()] == ["claude", "other"]
    assert await profiles.delete("claude")
    assert not await profiles.delete("claude")
    assert await profiles.get("claude") is None


async def test_library_overrides_are_stored_and_forgotten(
    stores: tuple[ProviderProfiles, LibraryModes],
) -> None:
    _, modes = stores
    ai = LibraryAi(
        enabled=False,
        llm=CHAT,
        reranker=ModelRef(profile="tei", model="bge:v2"),
        rerank_top_n=8,
        rerank_with=RerankWith.JUDGE,
    )

    await modes.save("/Acme/Payments", None, ai)

    assert await modes.ai_of("/acme/payments") == ai
    assert await modes.mode_of("/acme/payments") is None
    await modes.forget("/acme/PAYMENTS")
    assert await modes.ai_of("/acme/payments") == LibraryAi()


async def test_a_librarys_own_budgets_are_stored_with_it(
    stores: tuple[ProviderProfiles, LibraryModes],
) -> None:
    _, modes = stores
    usd = 5_000_000_000  # 5,000 US dollars in millionths: past a 32-bit column
    ai = LibraryAi(
        budgets=(
            BudgetLimit(scope_kind="library", window=SpendWindow.DAY, usd_micros=usd),
            BudgetLimit(
                scope_kind="library", window=SpendWindow.MONTH, usd_micros=usd, tokens=10**10
            ),
        )
    )

    await modes.save("/Acme/Payments", None, ai)
    await modes.save("/acme/no-budget", None, LibraryAi(rerank_top_n=4))

    assert await modes.ai_of("/acme/payments") == ai
    assert await modes.budgets() == {"/acme/payments": ai.budgets}  # one read, every library
    await modes.save("/acme/payments", None, LibraryAi())
    assert await modes.budgets() == {}
    assert await modes.ai_of("/acme/payments") == LibraryAi()


async def test_a_stored_profile_that_no_longer_validates_is_skipped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        profiles = SqliteProviderProfiles(engine=container.engine)
        await profiles.save(_profile(name="good", base_url="https://gw.example.com/v1"))
        async with container.engine.begin() as connection:  # a row written by an older release
            await connection.execute(
                text(
                    "INSERT INTO retrieval_ai_providers (name, kind, settings) VALUES "
                    "('old', 'azure', :settings)"
                ),
                {"settings": '{"resource": "evil.example/x?", "api_version": "v"}'},
            )

        listed = [p.name for p in await profiles.all()]
        old = await profiles.get("old")

    assert (listed, old) == (["good"], None)
    assert "stored AI provider 'old' is no longer valid" in caplog.text
