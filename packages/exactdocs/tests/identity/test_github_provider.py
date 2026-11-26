"""GitHub OAuth membership behavior including enterprise endpoint and restriction cases."""

from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from exactdocs.identity.adapters.driven.github import GithubProvider, github_api_url
from exactdocs.identity.errors import (
    ExternalSignInFailedError,
    GithubAccessDeniedError,
    ProviderAccessRevokedError,
    ProviderUnavailableError,
)
from fake_github import FakeGithub
from fake_oidc import CLIENT_ID, CLIENT_SECRET


def provider(
    client: httpx2.AsyncClient,
    fake: FakeGithub,
    allowed_orgs: tuple[str, ...] = ("acme",),
    rules: tuple[set[str], set[str]] | None = None,
) -> GithubProvider:
    async def watched() -> tuple[frozenset[str], frozenset[str]]:
        assert rules is not None
        return frozenset(rules[0]), frozenset(rules[1])

    return GithubProvider(
        base_url=fake.issuer,
        api_url=fake.api_url,
        client_id=CLIENT_ID,
        client_secret=lambda: CLIENT_SECRET,
        redirect_uri="https://docs.example.com/callback",
        allowed_orgs=allowed_orgs,
        allowed_teams=("acme/docs-readers",),
        client=client,
        watched=None if rules is None else watched,
    )


@pytest.mark.parametrize(
    ("base", "override", "api"),
    [
        ("https://github.com", None, "https://api.github.com"),
        ("https://github.example.com", None, "https://github.example.com/api/v3"),
        ("https://acme.ghe.com", None, "https://api.acme.ghe.com"),
        (
            "https://github.example.com",
            "https://api.example.com/custom/",
            "https://api.example.com/custom",
        ),
    ],
)
def test_api_derivation(base: str, override: str | None, api: str) -> None:
    assert github_api_url(base, override) == api


async def sign_in(p: GithubProvider, fake: FakeGithub):
    url = await p.authorization_url(state="s", nonce="n", code_verifier="v" * 64)
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == ["read:user read:org"]
    assert query["code_challenge_method"] == ["S256"]
    callback = fake.authorize(url, "123")
    return await p.exchange(
        code=parse_qs(urlsplit(callback).query)["code"][0], code_verifier="v" * 64, nonce="n"
    )


@pytest.fixture
async def setup():
    fake = FakeGithub(issuer="https://github.example.com")
    fake.add_user("123", "alice")
    async with httpx2.AsyncClient(transport=fake.transport()) as client:
        yield fake, provider(client, fake), client


async def test_code_flow_links_by_api_numeric_id_and_keeps_access_token(setup) -> None:
    fake, p, _ = setup
    grant = await sign_in(p, fake)
    assert grant.claims.issuer == fake.api_url
    assert grant.claims.subject == "123"
    assert grant.claims.groups == {"github:acme/docs-readers"}
    assert grant.refresh_token in fake.access_tokens
    fake.users["123"].username = "renamed"
    refreshed = await p.refresh(grant.refresh_token, subject="123")
    assert refreshed.claims.subject == "123"
    assert refreshed.claims.username == "renamed"


async def test_team_required_even_with_active_org_and_losing_it_revokes(setup) -> None:
    fake, p, _ = setup
    grant = await sign_in(p, fake)
    fake.teams.clear()
    with pytest.raises(GithubAccessDeniedError, match="not a member of an allowed team"):
        await p.refresh(grant.refresh_token, subject="123")


@pytest.mark.parametrize(
    ("restriction", "message"),
    [
        ("app", "organization acme has not approved this app"),
        ("sso", "authorize SSO for acme"),
        ("unknown", "organization acme refused access"),
    ],
)
async def test_org_restrictions_are_distinct_from_missing_membership(
    setup, restriction: str, message: str
) -> None:
    fake, p, _ = setup
    fake.restricted = restriction
    with pytest.raises(GithubAccessDeniedError, match=message):
        await sign_in(p, fake)
    assert not any("/user/teams" in path for path in fake.requests)


async def test_rate_limit_is_transient(setup) -> None:
    fake, p, _ = setup
    fake.restricted = "rate"
    with pytest.raises(ProviderUnavailableError):
        await sign_in(p, fake)


async def test_pagination_uses_only_configured_api_and_checks_organizations_first(setup) -> None:
    fake, _, client = setup
    fake.pages = 2
    p = provider(client, fake, allowed_orgs=("other",))
    grant = await sign_in(p, fake)
    assert grant.claims.groups == {"github:acme/docs-readers"}
    assert any("/memberships/orgs/other" in path for path in fake.requests)
    assert any("/memberships/orgs/acme" in path for path in fake.requests)
    assert all("evil.example" not in path for path in fake.requests)
    assert "page=2" in next(path for path in reversed(fake.requests) if "/user/teams" in path)


async def test_fallback_reads_single_team_membership(setup) -> None:
    fake, p, _ = setup
    fake.fail_teams = True
    fake.fallback_active = True
    assert (await sign_in(p, fake)).claims.groups == {"github:acme/docs-readers"}
    assert any("/teams/docs-readers/memberships/alice" in path for path in fake.requests)


@pytest.mark.parametrize("bad_id", [True, False, "123", 0, -1, 1.5, None])
async def test_numeric_id_is_strict(setup, bad_id: object) -> None:
    fake, p, _ = setup
    fake.numeric_id = bad_id
    with pytest.raises(ExternalSignInFailedError):
        await sign_in(p, fake)


async def test_revoked_token_and_subject_substitution_are_refused(setup) -> None:
    fake, p, _ = setup
    grant = await sign_in(p, fake)
    with pytest.raises(ExternalSignInFailedError):
        await p.refresh(grant.refresh_token, subject="456")
    fake.access_tokens.clear()
    with pytest.raises(ProviderAccessRevokedError):
        await p.refresh(grant.refresh_token, subject="123")


@pytest.mark.parametrize("endpoint", ["org", "team"])
@pytest.mark.parametrize("state", [None, 123, "unexpected", [], {}])
async def test_malformed_membership_is_an_outage_not_revocation(setup, endpoint, state) -> None:
    fake, p, _ = setup
    grant = await sign_in(p, fake)
    if endpoint == "org":
        fake.membership_state = state
    else:
        fake.fail_teams = True
        fake.fallback_active = True
        fake.fallback_state = state
    with pytest.raises(ProviderUnavailableError):
        await p.refresh(grant.refresh_token, subject="123")


async def test_pending_organization_is_not_active_membership(setup) -> None:
    fake, p, _ = setup
    fake.membership_state = "pending"
    with pytest.raises(GithubAccessDeniedError, match="not a member of an allowed organization"):
        await sign_in(p, fake)


async def test_organizations_and_teams_named_in_rules_become_groups(setup) -> None:
    fake, _, client = setup
    fake.orgs.add("beta")
    fake.teams += [("acme", "docs-writers"), ("acme", "unnamed")]
    p = provider(client, fake, rules=({"acme", "beta"}, {"acme/docs-writers"}))

    grant = await sign_in(p, fake)

    assert grant.claims.groups == {
        "github:acme/docs-readers",
        "github:acme",
        "github:beta",
        "github:acme/docs-writers",
    }


async def test_a_team_named_only_in_a_rule_admits_nobody(setup) -> None:
    fake, _, client = setup
    fake.teams[:] = [("acme", "docs-writers")]
    p = provider(client, fake, rules=(set(), {"acme/docs-writers"}))

    with pytest.raises(GithubAccessDeniedError, match="not a member of an allowed team"):
        await sign_in(p, fake)


async def test_a_restricted_organization_named_only_in_a_rule_gives_no_group(setup) -> None:
    fake, _, client = setup
    fake.orgs.add("locked")
    fake.restricted_orgs.add("locked")
    fake.teams.append(("locked", "writers"))
    p = provider(client, fake, rules=({"locked"}, {"locked/writers"}))

    grant = await sign_in(p, fake)

    assert grant.claims.groups == {"github:acme/docs-readers"}
    assert any("/memberships/orgs/locked" in path for path in fake.requests)


async def test_a_rules_organization_its_member_left_gives_no_group(setup) -> None:
    fake, _, client = setup
    p = provider(client, fake, rules=({"gone"}, {"gone/team"}))

    assert (await sign_in(p, fake)).claims.groups == {"github:acme/docs-readers"}
