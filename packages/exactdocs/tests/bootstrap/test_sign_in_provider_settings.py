"""Provider-kind configuration defaults and fail-closed admission."""

import httpx2
import pytest
from pydantic import ValidationError

from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.settings import Settings, SignInProviderSettings
from exactdocs.bootstrap.sign_in import sign_in_providers
from exactdocs_kernel import SystemClock


def test_oauth2_requires_endpoints_and_defaults_to_token_origin_including_port() -> None:
    settings = SignInProviderSettings(
        kind="oauth2",
        client_id="docs",
        allow_any_user=True,
        authorization_url="https://corp.example/auth",
        token_url="https://corp.example:8443/token",
        userinfo_url="https://corp.example/user",
    )
    assert settings.issuer == "https://corp.example:8443"
    assert settings.scopes == ["offline_access"]
    assert settings.subject_claim == "sub"


@pytest.mark.parametrize("kind", ["oidc", "oauth2", "github"])
def test_no_provider_silently_admits_everyone(kind: str) -> None:
    with pytest.raises(ValidationError):
        SignInProviderSettings.model_validate(
            {
                "kind": kind,
                "client_id": "docs",
                "issuer": "https://corp.example",
                "authorization_url": "https://corp.example/auth",
                "token_url": "https://corp.example/token",
                "userinfo_url": "https://corp.example/user",
            }
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_teams": ["acme/../oops"]},
        {"allowed_teams": ["acme"]},
        {"allowed_orgs": ["acme/other"]},
        {"base_url": "http://github.example.com"},
        {"api_url": "http://api.example.com"},
    ],
)
def test_invalid_github_endpoints_and_membership_paths_are_refused(changes: dict) -> None:
    with pytest.raises(ValidationError):
        SignInProviderSettings.model_validate(
            {"kind": "github", "client_id": "docs", "allowed_teams": ["acme/docs"], **changes}
        )


def test_github_membership_filter_is_sufficient_admission_and_scopes_are_fixed() -> None:
    settings = SignInProviderSettings(kind="github", client_id="docs", allowed_teams=["acme/docs"])
    assert settings.allow_any_user is False
    assert settings.scopes == ["read:user", "read:org"]


# ---------------------------------------------------------------- presets (#506)

TENANT = "11111111-2222-3333-4444-555555555555"


def preset(kind: str, **changes: object) -> SignInProviderSettings:
    return SignInProviderSettings.model_validate(
        {"kind": kind, "client_id": "docs", "client_secret": "s", **changes}
    )


def test_discord_needs_only_the_client() -> None:
    discord = preset("discord")

    assert (discord.protocol, discord.issuer, discord.display_name) == (
        "oauth2",
        "https://discord.com",
        "Discord",
    )
    assert discord.userinfo_url == "https://discord.com/api/users/@me"
    assert (discord.subject_claim, discord.username_claim) == ("id", "username")
    assert discord.scopes == ["identify", "email"]  # Discord knows no offline_access
    assert discord.built_in_icon == "discord"


def test_google_needs_only_the_client() -> None:
    google = preset("google")

    assert (google.protocol, google.issuer, google.display_name) == (
        "oidc",
        "https://accounts.google.com",
        "Google",
    )
    assert google.scopes == ["openid", "email", "profile"]
    assert google.discovery_url == "https://accounts.google.com/.well-known/openid-configuration"


@pytest.mark.parametrize(
    ("tenant", "issuer", "discovery"),
    [
        (
            TENANT,
            f"https://login.microsoftonline.com/{TENANT}/v2.0",
            f"https://login.microsoftonline.com/{TENANT}/v2.0/.well-known/openid-configuration",
        ),
        (
            "organizations",
            "https://login.microsoftonline.com/{tenantid}/v2.0",
            "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration",
        ),
        (
            "Common",
            "https://login.microsoftonline.com/{tenantid}/v2.0",
            "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        ),
        (
            "consumers",
            "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0",
            "https://login.microsoftonline.com/consumers/v2.0/.well-known/openid-configuration",
        ),
    ],
)
def test_microsoft_needs_the_client_and_a_tenant(tenant: str, issuer: str, discovery: str) -> None:
    microsoft = preset("microsoft", tenant=tenant)

    assert (microsoft.protocol, microsoft.issuer, microsoft.discovery_url) == (
        "oidc",
        issuer,
        discovery,
    )
    assert microsoft.display_name == "Microsoft"
    assert "offline_access" in microsoft.scopes


@pytest.mark.parametrize("tenant", [None, "", "contoso.onmicrosoft.com", "../common"])
def test_microsoft_without_a_usable_tenant_is_refused(tenant: str | None) -> None:
    with pytest.raises(ValidationError, match="tenant"):
        preset("microsoft", **({} if tenant is None else {"tenant": tenant}))


@pytest.mark.parametrize(
    ("kind", "changes"),
    [
        ("google", {"issuer": "https://evil.example"}),
        ("discord", {"token_url": "https://evil.example/token"}),
        ("microsoft", {"tenant": TENANT, "issuer": "https://evil.example"}),
        ("google", {"tenant": TENANT}),
        ("oidc", {"issuer": "https://idp.example.com/{tenantid}", "allow_any_user": True}),
    ],
)
def test_a_preset_keeps_its_own_endpoints(kind: str, changes: dict) -> None:
    with pytest.raises(ValidationError):
        preset(kind, **changes)


def test_presets_link_people_by_default_and_create_no_accounts() -> None:
    google = preset("google")
    assert (google.creates_accounts, google.admits_anyone) == (False, True)

    # Creating accounts through Google is a choice, and then admission is too.
    with pytest.raises(ValidationError, match="allow_any_user"):
        preset("google", auto_create_users=True)
    opened = preset("google", auto_create_users=True, allow_any_user=True)
    assert (opened.creates_accounts, opened.admits_anyone) == (True, True)
    grouped = preset("microsoft", tenant=TENANT, allowed_groups=["docs"])
    assert (grouped.creates_accounts, grouped.admits_anyone) == (False, False)


def test_a_generic_provider_creates_accounts_unless_told_otherwise() -> None:
    base = {"issuer": "https://idp.example.com", "client_id": "docs"}
    oidc = SignInProviderSettings.model_validate({"kind": "oidc", **base, "allow_any_user": True})
    linking = SignInProviderSettings.model_validate(
        {"kind": "oidc", **base, "auto_create_users": False}
    )

    assert (oidc.creates_accounts, oidc.built_in_icon) == (True, None)
    assert (linking.creates_accounts, linking.admits_anyone) == (False, True)


def test_icons_are_built_in_or_the_operators_own_not_both(tmp_path) -> None:
    github = SignInProviderSettings(kind="github", client_id="docs", allowed_teams=["acme/docs"])
    own = preset("discord", icon_file=tmp_path / "icon.svg")
    other = preset("discord", icon="google")

    assert (github.built_in_icon, own.built_in_icon, other.built_in_icon) == (
        "github",
        None,
        "google",
    )
    with pytest.raises(ValidationError, match="icon"):
        preset("google", icon="google", icon_file=tmp_path / "icon.svg")


OIDC = {
    "kind": "oidc",
    "client_id": "docs",
    "issuer": "https://corp.example",
    "allow_any_user": True,
}


@pytest.mark.parametrize(
    ("changes", "rule"),
    [
        ({}, {"grant": "viewer"}),
        ({}, {"group": "a", "role": "b", "grant": "viewer"}),
        ({}, {"role": "ExactDocs.Reader", "grant": "viewer"}),
        ({"role_claim": "roles"}, {"github_org": "acme", "grant": "viewer"}),
        ({"role_claim": "roles"}, {"group": "a", "grant": "creator"}),
    ],
)
def test_a_configured_rule_names_one_source_its_provider_can_match(
    changes: dict, rule: dict
) -> None:
    with pytest.raises(ValidationError):
        SignInProviderSettings.model_validate({**OIDC, **changes, "rules": [rule]})


def test_github_has_no_role_claim() -> None:
    with pytest.raises(ValidationError, match="role_claim"):
        SignInProviderSettings(
            kind="github", client_id="docs", allowed_orgs=["acme"], role_claim="roles"
        )


def test_configured_rules_for_entra_app_roles() -> None:
    settings = SignInProviderSettings.model_validate(
        {
            **OIDC,
            "role_claim": "roles",
            "configured_rules_only": True,
            "rules": [
                {"role": "ExactDocs.Admin", "grant": "instance_admin"},
                {"role": "ExactDocs.Reader", "grant": "viewer", "libraries": ["/acme/docs"]},
            ],
        }
    )

    assert [rule.source for rule in settings.rules] == [
        ("role", "ExactDocs.Admin"),
        ("role", "ExactDocs.Reader"),
    ]


def _policies(rules: list[dict], **changes: object) -> dict:
    settings = Settings.model_validate(
        {
            "public_url": "https://docs.example.com",
            "auth": {
                "providers": {"corp": {**OIDC, "role_claim": "roles", "rules": rules, **changes}}
            },
        }
    )
    return sign_in_providers(settings, httpx2.AsyncClient(), SystemClock())[1]


def test_configured_rules_become_read_only_domain_rules() -> None:
    policy = _policies(
        [{"role": "ExactDocs.Reader", "grant": "viewer", "libraries": ["/Acme/Docs"]}],
        admin_groups=["ops"],
        configured_rules_only=True,
    )["corp"]

    assert policy.configured_rules_only
    assert [(r.id, r.value, r.grant.value, r.libraries) for r in policy.configured_role_rules] == [
        ("config:corp:admin_groups:ops", "ops", "instance_admin", None),
        ("config:corp:1", "ExactDocs.Reader", "viewer", frozenset({"/acme/docs"})),
    ]
    assert all(rule.configured for rule in policy.configured_role_rules)


def test_a_configured_rule_that_can_match_nobody_stops_the_start() -> None:
    with pytest.raises(StartupError, match="rule 1"):
        _policies([{"group": "a", "grant": "instance_admin", "libraries": ["/acme/docs"]}])
