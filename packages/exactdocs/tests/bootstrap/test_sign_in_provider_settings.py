"""Provider-kind configuration defaults and fail-closed admission."""

import pytest
from pydantic import ValidationError

from exactdocs.bootstrap.settings import SignInProviderSettings


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
