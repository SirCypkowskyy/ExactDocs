"""Role rules (#577): GitHub organizations, teams, groups and role values mapped to roles."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccessLog,
    InMemoryAccountRepository,
    InMemoryExternalIdentityRepository,
    InMemoryFailedSignInLog,
    InMemoryLibraryGrantRepository,
    InMemoryPreferencesRepository,
    InMemoryPrivateLibraries,
    InMemoryRoleRuleRepository,
    InMemorySessionRepository,
    InMemorySignInAttemptRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.dtos import (
    DropLibraryGrantsCommand,
    ExternalTokenIdentity,
    FinishExternalSignInCommand,
    GrantLibraryRoleCommand,
    LibraryCreationQuery,
    LibraryRolesQuery,
    MarkLibraryPrivateCommand,
    StartExternalSignInCommand,
)
from exactdocs.identity.errors import InvalidRoleRuleError
from exactdocs.identity.models import (
    AccountId,
    ExternalClaims,
    ExternalGrant,
    LibraryCreationPolicy,
    Memberships,
    Role,
    RoleRule,
    RuleGrant,
    RuleSource,
    SignInPolicy,
)
from exactdocs.identity.module import IdentityModule

ISSUER = "https://idp.example.com"
DOCS, OTHER, SECRET = "/acme/docs", "/acme/other", "/acme/secret"


@dataclass(slots=True)
class Clock:
    at: datetime = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.at


class Hasher:
    async def hash(self, password: str) -> str:
        return password

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == password


class Box:
    def seal(self, plaintext: str) -> str:
        return plaintext

    def open(self, sealed: str) -> str:
        return sealed


@dataclass(slots=True)
class Provider:
    """Trusts any code; answers with whoever the test scripted, now."""

    people: dict[str, ExternalClaims] = field(default_factory=dict)
    next_subject: str = ""

    def add(self, subject: str, *, groups: frozenset[str] = frozenset(), roles=frozenset()):
        self.people[subject] = ExternalClaims(
            issuer=ISSUER, subject=subject, username=subject, groups=groups, roles=roles
        )
        self.next_subject = subject

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        del nonce, code_verifier
        return f"{ISSUER}/authorize?state={state}"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> ExternalGrant:
        del code, code_verifier, nonce
        return ExternalGrant(claims=self.people[self.next_subject], refresh_token="refresh")

    async def verify_id_token(self, id_token: str) -> ExternalClaims:
        return self.people[id_token]

    async def refresh(self, refresh_token: str, *, subject: str) -> ExternalGrant:
        return ExternalGrant(claims=self.people[subject], refresh_token=refresh_token)


@dataclass(slots=True)
class World:
    identity: IdentityModule
    provider: Provider
    rules: InMemoryRoleRuleRepository
    private: InMemoryPrivateLibraries
    clock: Clock
    accounts: InMemoryAccountRepository
    grants: InMemoryLibraryGrantRepository

    async def sign_in(self, subject: str, **claims: Any) -> str:
        self.provider.add(subject, **claims)
        begun = await self.identity.start_external_sign_in(
            StartExternalSignInCommand(provider="corp", return_to="/")
        )
        state = begun.redirect_url.rsplit("=", 1)[-1]
        result = await self.identity.finish_external_sign_in(
            FinishExternalSignInCommand(
                provider="corp", binding=begun.binding, state=state, code="code"
            )
        )
        assert result.session is not None
        return result.session.account.id

    async def roles(self, account: str, *libraries: str) -> dict[str, str]:
        found = await self.identity.resolve_library_roles(
            LibraryRolesQuery(account_id=account, libraries=list(libraries))
        )
        return found.roles

    async def role(self, account: str) -> Role:
        found = await self.accounts.get_by_id(AccountId(account))
        assert found is not None
        return found.role

    async def add(self, source: RuleSource, value: str, grant: RuleGrant, **more: Any) -> RoleRule:
        rule = RoleRule(
            id=f"r{len(self.rules.rules)}",
            provider=more.pop("provider", "corp"),
            source=source,
            value=value,
            grant=grant,
            **more,
        )
        assert await self.rules.add(rule)
        return rule


def corp(**overrides: Any) -> SignInPolicy:
    values: dict[str, Any] = {
        "name": "corp",
        "display_name": "Corp",
        "allow_any_user": True,
        "revalidate_every": timedelta(minutes=60),
        "grace": timedelta(minutes=1440),
    }
    return SignInPolicy(**{**values, **overrides})


def build(
    policy: SignInPolicy | None = None, creation: LibraryCreationPolicy | None = None
) -> World:
    clock = Clock()
    accounts = InMemoryAccountRepository()
    provider = Provider()
    rules = InMemoryRoleRuleRepository()
    private = InMemoryPrivateLibraries()
    grants = InMemoryLibraryGrantRepository()
    policy = policy or corp()
    identity = IdentityModule.build(
        repository=accounts,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=Hasher(),
        failures=InMemoryFailedSignInLog(),
        externals=InMemoryExternalIdentityRepository(accounts=accounts),
        library_grants=grants,
        preferences=InMemoryPreferencesRepository(),
        access_log=InMemoryAccessLog(),
        attempts=InMemorySignInAttemptRepository(),
        box=Box(),
        clock=clock,
        providers={"corp": provider},
        policies={"corp": policy},
        library_creation=creation,
        role_rules=rules,
        private_libraries=private,
    )
    return World(identity, provider, rules, private, clock, accounts, grants)


# ---------------------------------------------------------------- the rule itself


@pytest.mark.parametrize(
    ("source", "value", "more"),
    [
        (RuleSource.GITHUB_ORG, "acme/team", {}),
        (RuleSource.GITHUB_TEAM, "acme", {}),
        (RuleSource.GROUP, " writers", {}),
        (RuleSource.GROUP, "", {}),
        (RuleSource.ROLE, "Reader", {"provider": None}),
    ],
)
def test_a_rule_that_could_match_nobody_is_refused(
    source: RuleSource, value: str, more: dict[str, Any]
) -> None:
    with pytest.raises(InvalidRoleRuleError):
        RoleRule(
            id="r",
            provider=more.get("provider", "corp"),
            source=source,
            value=value,
            grant=RuleGrant.VIEWER,
        )


@pytest.mark.parametrize("libraries", [frozenset(), frozenset({"/Acme/Docs"}), frozenset({"x"})])
def test_chosen_libraries_are_lower_case_library_ids(libraries: frozenset[str]) -> None:
    with pytest.raises(InvalidRoleRuleError):
        RoleRule(
            id="r",
            provider="corp",
            source=RuleSource.GROUP,
            value="g",
            grant=RuleGrant.VIEWER,
            libraries=libraries,
        )


def test_an_instance_grant_names_no_library() -> None:
    with pytest.raises(InvalidRoleRuleError):
        RoleRule(
            id="r",
            provider="corp",
            source=RuleSource.GROUP,
            value="g",
            grant=RuleGrant.INSTANCE_ADMIN,
            libraries=frozenset({DOCS}),
        )


def test_a_group_never_satisfies_a_role_rule_nor_a_role_a_group_rule() -> None:
    policies = {"corp": corp()}
    group = RoleRule(
        id="g", provider="corp", source=RuleSource.GROUP, value="x", grant=RuleGrant.VIEWER
    )
    role = RoleRule(
        id="r", provider="corp", source=RuleSource.ROLE, value="x", grant=RuleGrant.VIEWER
    )

    as_group = Memberships(provider="corp", groups=frozenset({"x"}))
    as_role = Memberships(provider="corp", roles=frozenset({"x"}))

    assert group.matches(as_group, policies)
    assert not role.matches(as_group, policies)
    assert role.matches(as_role, policies)
    assert not group.matches(as_role, policies)


def test_a_rule_matches_only_its_providers_accounts_with_its_prefix() -> None:
    policies = {"corp": corp(group_prefix="corp:"), "other": corp(name="other")}
    rule = RoleRule(
        id="g", provider="corp", source=RuleSource.GROUP, value="w", grant=RuleGrant.VIEWER
    )

    assert rule.matches(Memberships(provider="corp", groups=frozenset({"corp:w"})), policies)
    assert not rule.matches(Memberships(provider="corp", groups=frozenset({"w"})), policies)
    assert not rule.matches(Memberships(provider="other", groups=frozenset({"corp:w"})), policies)
    assert not rule.matches(Memberships(provider="gone", groups=frozenset({"corp:w"})), {})


def test_github_names_match_without_case_and_only_on_github() -> None:
    rule = RoleRule(
        id="t",
        provider="corp",
        source=RuleSource.GITHUB_TEAM,
        value="acme/writers",
        grant=RuleGrant.VIEWER,
    )
    member = Memberships(provider="corp", groups=frozenset({"github:Acme/Writers"}))

    assert rule.matches(member, {"corp": corp(github=True)})
    assert not rule.matches(member, {"corp": corp()})


def test_a_provider_with_configured_rules_only_ignores_stored_ones() -> None:
    policies = {"corp": corp(configured_rules_only=True)}
    stored = RoleRule(
        id="s", provider="corp", source=RuleSource.GROUP, value="w", grant=RuleGrant.VIEWER
    )
    member = Memberships(provider="corp", groups=frozenset({"w"}))

    assert not stored.matches(member, policies)
    assert RoleRule(
        id="c",
        provider="corp",
        source=RuleSource.GROUP,
        value="w",
        grant=RuleGrant.VIEWER,
        configured=True,
    ).matches(member, policies)


def test_admin_groups_and_library_creation_groups_show_as_configured_rules() -> None:
    admins = corp(admin_groups=frozenset({"ops"})).configured_role_rules
    creators = LibraryCreationPolicy(groups=frozenset({"corp:writers"})).role_rules

    assert [(r.source, r.value, r.grant, r.configured) for r in admins] == [
        (RuleSource.GROUP, "ops", RuleGrant.INSTANCE_ADMIN, True)
    ]
    assert [(r.provider, r.value, r.grant) for r in creators] == [
        (None, "corp:writers", RuleGrant.CREATE_LIBRARIES)
    ]


# ---------------------------------------------------------------- library roles


async def test_a_teams_rule_reaches_every_library_including_later_ones_but_not_private() -> None:
    world = build()
    await world.add(RuleSource.GROUP, "writers", RuleGrant.CONTRIBUTOR)
    await world.identity.mark_library_private(
        MarkLibraryPrivateCommand(library=SECRET, private=True)
    )
    member = await world.sign_in("u1", groups=frozenset({"writers"}))
    outsider = await world.sign_in("u2", groups=frozenset({"readers"}))

    assert await world.roles(member, DOCS, OTHER, SECRET, "/new/library") == {
        DOCS: "contributor",
        OTHER: "contributor",
        "/new/library": "contributor",
    }
    assert await world.roles(outsider, DOCS) == {}


async def test_a_rule_reaches_a_private_library_it_names() -> None:
    world = build()
    await world.add(RuleSource.GROUP, "w", RuleGrant.VIEWER, libraries=frozenset({SECRET}))
    await world.identity.mark_library_private(
        MarkLibraryPrivateCommand(library=SECRET, private=True)
    )
    member = await world.sign_in("u1", groups=frozenset({"w"}))

    assert await world.roles(member, DOCS, SECRET) == {SECRET: "viewer"}


async def test_a_removed_private_library_stays_private_until_added_again() -> None:
    world = build()
    await world.add(RuleSource.GROUP, "w", RuleGrant.VIEWER)
    await world.identity.mark_library_private(
        MarkLibraryPrivateCommand(library=SECRET, private=True)
    )
    await world.identity.drop_library_grants(DropLibraryGrantsCommand(library=SECRET))
    member = await world.sign_in("u1", groups=frozenset({"w"}))
    assert await world.roles(member, SECRET) == {}

    await world.identity.mark_library_private(
        MarkLibraryPrivateCommand(library=SECRET, private=False)
    )

    assert await world.roles(member, SECRET) == {SECRET: "viewer"}


async def test_odd_admin_group_names_of_the_configuration_still_sign_people_in() -> None:
    world = build(corp(admin_groups=frozenset({"Docs Admins ", ""})))

    admin = await world.sign_in("u1", groups=frozenset({"Docs Admins "}))

    assert await world.role(admin) is Role.ADMIN


def test_only_the_library_creation_groups_apply_to_every_provider() -> None:
    with pytest.raises(InvalidRoleRuleError):
        RoleRule(
            id="r",
            provider=None,
            source=RuleSource.GROUP,
            value="g",
            grant=RuleGrant.INSTANCE_ADMIN,
            configured=True,
        )
    with pytest.raises(InvalidRoleRuleError):
        RoleRule(
            id="r",
            provider=None,
            source=RuleSource.GROUP,
            value="g",
            grant=RuleGrant.CREATE_LIBRARIES,
        )


async def test_the_highest_of_a_direct_grant_and_the_rules_counts() -> None:
    world = build(corp(admin_groups=frozenset({"ops"})))
    admin = await world.sign_in("boss", groups=frozenset({"ops"}))
    await world.add(RuleSource.ROLE, "Reader", RuleGrant.VIEWER)
    member = await world.sign_in("u1", roles=frozenset({"Reader"}))
    await world.identity.grant_library_role(
        GrantLibraryRoleCommand(
            caller_id=admin, library=DOCS, kind="user", subject="u1", role="admin"
        )
    )

    assert await world.roles(member, DOCS, OTHER) == {DOCS: "admin", OTHER: "viewer"}


async def test_removing_a_rule_takes_effect_at_the_next_request() -> None:
    world = build()
    rule = await world.add(RuleSource.GROUP, "writers", RuleGrant.CONTRIBUTOR)
    member = await world.sign_in("u1", groups=frozenset({"writers"}))
    assert await world.roles(member, DOCS) == {DOCS: "contributor"}

    await world.rules.remove(rule.id)

    assert await world.roles(member, DOCS) == {}


async def test_an_unknown_account_gets_nothing_from_rules() -> None:
    world = build()
    await world.add(RuleSource.GROUP, "writers", RuleGrant.VIEWER)

    assert await world.roles("nobody", DOCS) == {}


async def test_an_oauth_caller_is_matched_by_its_tokens_role_values() -> None:
    world = build()
    await world.add(RuleSource.ROLE, "Reader", RuleGrant.VIEWER)
    world.provider.add("u1", roles=frozenset({"Reader"}))

    caller = await world.identity.identify_external_token("corp", "u1")
    found = await world.identity.resolve_library_roles(
        LibraryRolesQuery(account_id=caller.account.id, libraries=[DOCS], external_identity=caller)
    )

    assert caller.roles == frozenset({"Reader"})
    assert caller.provider == "corp"
    assert found.roles == {DOCS: "viewer"}


async def test_an_oauth_identity_cannot_claim_another_providers_rules() -> None:
    world = build()
    await world.add(RuleSource.GROUP, "w", RuleGrant.VIEWER)
    forged = ExternalTokenIdentity.model_validate(
        {
            "account": {"id": "other:1", "username": "x", "role": "user"},
            "groups": frozenset({"w"}),
            "linked": False,
            "provider": "other",
        }
    )

    found = await world.identity.resolve_library_roles(
        LibraryRolesQuery(account_id="other:1", libraries=[DOCS], external_identity=forged)
    )

    assert found.roles == {}


# ---------------------------------------------------------------- instance roles


async def test_an_admin_rule_makes_an_admin_and_the_next_check_takes_it_back() -> None:
    world = build()
    await world.add(RuleSource.GROUP, "platform-admins", RuleGrant.INSTANCE_ADMIN)
    account = await world.sign_in("u1", groups=frozenset({"platform-admins"}))
    assert await world.role(account) is Role.ADMIN

    world.provider.add("u1", groups=frozenset())
    world.clock.at += timedelta(minutes=61)
    report = await world.identity.revalidate_external_accounts()

    assert report.extended == 1
    assert await world.role(account) is Role.USER


async def test_a_configured_role_rule_makes_an_admin() -> None:
    rule = RoleRule(
        id="config:corp:1",
        provider="corp",
        source=RuleSource.ROLE,
        value="ExactDocs.Admin",
        grant=RuleGrant.INSTANCE_ADMIN,
        configured=True,
    )
    world = build(corp(rules=(rule,), configured_rules_only=True))

    admin = await world.sign_in("u1", roles=frozenset({"ExactDocs.Admin"}))
    reader = await world.sign_in("u2", roles=frozenset({"ExactDocs.Reader"}))

    assert await world.role(admin) is Role.ADMIN
    assert await world.role(reader) is Role.USER


async def test_a_creation_rule_lets_a_member_create_libraries() -> None:
    world = build(creation=LibraryCreationPolicy())
    await world.add(RuleSource.GROUP, "writers", RuleGrant.CREATE_LIBRARIES)
    member = await world.sign_in("u1", groups=frozenset({"writers"}))
    outsider = await world.sign_in("u2", groups=frozenset({"readers"}))

    assert await world.identity.can_create_library(LibraryCreationQuery(account_id=member))
    assert not await world.identity.can_create_library(LibraryCreationQuery(account_id=outsider))
    assert not await world.roles(member, DOCS)


async def test_the_stored_rules_refuse_a_duplicate() -> None:
    world = build()
    await world.add(RuleSource.GROUP, "w", RuleGrant.VIEWER)

    again = RoleRule(
        id="x", provider="corp", source=RuleSource.GROUP, value="w", grant=RuleGrant.VIEWER
    )

    assert not await world.rules.add(again)
    assert await world.rules.add(
        RoleRule(id="y", provider="corp", source=RuleSource.GROUP, value="w", grant=RuleGrant.ADMIN)
    )
