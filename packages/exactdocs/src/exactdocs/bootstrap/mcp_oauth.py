"""OAuth for MCP hosts that cannot paste an API token (Claude, ChatGPT).

One sign-in provider of ``[auth.providers]`` is chosen (``EXACTDOCS_MCP_OAUTH_PROVIDER``): an MCP
client discovers a single authorization server. FastMCP's OAuth proxy serves the discovery
documents, dynamic client registration, the consent page and the token endpoint, and signs the
person in at the provider; our ``ExternalTokenVerifier`` then vouches for the provider credential
at every call, applying the provider's policy (allowed groups, disabled accounts). It is combined
with the API-token verifier by ``MultiAuth``, so both credentials open ``/mcp``.

OIDC (ADFS included) uses ``OIDCProxy``; OAuth2 and GitHub use ``OAuthProxy`` with the configured
provider endpoints and opaque access-token verification.
"""

import hashlib
import shutil
from pathlib import Path

from cryptography.fernet import Fernet
from fastmcp.server.auth import AuthProvider, MultiAuth, OAuthProxy, OIDCProxy
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from exactdocs.bootstrap.constants import MCP_OAUTH_SUBDIR
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import client_secret_reader
from exactdocs.identity import IdentityModule
from exactdocs.identity.adapters.driving.mcp import ApiTokenVerifier, ExternalTokenVerifier


def build_mcp_auth(settings: Settings, identity: IdentityModule) -> AuthProvider:
    """Return what guards ``/mcp``: API tokens, plus OAuth when a provider is chosen.

    Args:
        settings: The runtime configuration.
        identity: The identity domain.

    Returns:
        The API-token verifier alone, or the OAuth proxy combined with it.

    Raises:
        ValueError: The chosen provider's client secret cannot be read.
    """
    api_tokens = ApiTokenVerifier(identify_token=identity.identify_token)
    name = settings.mcp_oauth_provider
    if name is None:
        return api_tokens
    provider = settings.auth.providers[name]
    secret = client_secret_reader(name, provider)()
    if secret is None:
        message = f"sign-in provider {name!r}: its client secret cannot be read"
        raise ValueError(message)
    verifier = ExternalTokenVerifier(
        provider=name, identify_external_token=identity.identify_external_token
    )
    storage = _storage(settings.data_dir / MCP_OAUTH_SUBDIR, secret)
    signing_key = derive_jwt_key(
        high_entropy_material=secret, salt="exactdocs-mcp-oauth-jwt-signing-key"
    )
    if provider.kind != "oidc":
        github = provider.kind == "github"
        base = provider.base_url.rstrip("/")
        proxy = OAuthProxy(
            upstream_authorization_endpoint=(
                f"{base}/login/oauth/authorize" if github else provider.authorization_url or ""
            ),
            upstream_token_endpoint=(
                f"{base}/login/oauth/access_token" if github else provider.token_url or ""
            ),
            upstream_client_id=provider.client_id,
            upstream_client_secret=secret,
            token_endpoint_auth_method=(
                "client_secret_post" if github else provider.client_auth_method
            ),
            base_url=f"{settings.public_url}",
            token_verifier=verifier,
            valid_scopes=provider.scopes,
            client_storage=storage,
            jwt_signing_key=signing_key,
        )
        return MultiAuth(server=proxy, verifiers=[api_tokens])
    config_url = f"{provider.issuer.rstrip('/')}/.well-known/openid-configuration"
    proxy = OIDCProxy(
        config_url=config_url,
        strict=False,  # the web sign-in does not insist on every optional metadata field either
        client_id=provider.client_id,
        client_secret=secret,
        base_url=f"{settings.public_url}",  # set: Settings requires it once a provider exists
        # The provider's ID token is what is checked (always a JWT, unlike many access tokens);
        # the scopes are those of the web sign-in, `openid` and `offline_access` among them.
        verify_id_token=True,
        token_verifier=verifier,
        valid_scopes=provider.scopes,
        client_storage=storage,
        jwt_signing_key=signing_key,
    )
    return MultiAuth(server=proxy, verifiers=[api_tokens])


def _storage(directory: Path, secret: str) -> AsyncKeyValue:
    """Keep the proxy's registrations and tokens encrypted under the data directory.

    FastMCP's own default would put them in the user's data folder, which a container does not
    keep. A rotated client secret changes the key: stored state then reads as missing and hosts
    register and sign in again, and the directories of earlier keys are removed.

    Args:
        directory: Where the files go.
        secret: The provider's client secret, from which the encryption key is derived.

    Returns:
        The store.
    """
    key = derive_jwt_key(high_entropy_material=secret, salt="exactdocs-mcp-oauth-storage")
    current = directory / hashlib.sha256(key).hexdigest()[:12]
    if directory.is_dir():
        for stale in directory.iterdir():
            if stale.is_dir() and stale != current:
                shutil.rmtree(stale, ignore_errors=True)
    directory = current
    directory.mkdir(parents=True, exist_ok=True)
    return FernetEncryptionWrapper(
        key_value=FileTreeStore(
            data_directory=directory,
            key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
            collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
        ),
        fernet=Fernet(key=key),
        raise_on_decryption_error=False,
    )
