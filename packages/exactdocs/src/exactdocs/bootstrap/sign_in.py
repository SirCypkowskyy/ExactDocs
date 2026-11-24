"""External sign-in wiring: identity providers from the settings, and the revalidation loop.

Each ``[auth.providers.<name>]`` becomes the identity domain's ``SignInPolicy`` (who is admitted,
with which role and groups, for how long) and its OIDC, OAuth2 or GitHub protocol adapter.
The redirect URI comes from ``EXACTDOCS_PUBLIC_URL``. Secrets are read at every use,
so a rotated ``client_secret_file`` needs no restart.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType

import httpx2

from exactdocs.bootstrap.constants import (
    GOOGLE_AUTHORIZATION_PARAMS,
    SIGN_IN_STOP_SECONDS,
    V1_PREFIX,
)
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.outbound import routed_transport
from exactdocs.bootstrap.settings import Settings, SignInProviderSettings
from exactdocs.identity.adapters.driven.cloudflare_access import CloudflareAccessVerifier
from exactdocs.identity.adapters.driven.github import GithubProvider, github_api_url
from exactdocs.identity.adapters.driven.icons import read_icon
from exactdocs.identity.adapters.driven.oauth2 import OAuth2ClaimNames, OAuth2Provider
from exactdocs.identity.adapters.driven.oidc import OidcClaimNames, OidcProvider
from exactdocs.identity.constants import OIDC_TIMEOUT
from exactdocs.identity.models import (
    AccessPolicy,
    BuiltInIcon,
    ProviderIcon,
    SignInPolicy,
    Username,
)
from exactdocs.identity.ports.driven import SignInProvider
from exactdocs.identity.ports.driving import RevalidateExternalAccounts
from exactdocs_kernel import Clock, OutboundNetwork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SignInStandIns:
    """What tests put in place of the identity domain's time and its providers' network."""

    clock: Clock | None = None
    """The identity domain's time (sessions, sign-in attempts, revalidation)."""
    transport: httpx2.AsyncBaseTransport | None = None
    """Carries the calls to the identity providers (an in-process fake issuer)."""


def sign_in_client(
    transport: httpx2.AsyncBaseTransport | None = None,
    network: OutboundNetwork | None = None,
) -> httpx2.AsyncClient:
    """Return the HTTP client every identity provider is called through.

    It follows the outbound settings (#538): an IdP is often reached through the corporate
    proxy, an internal one directly through ``NO_PROXY``, and a company CA may sign either.
    Discovery, the token, user-info and JWKS calls all go through it; redirects are never
    followed, and a failure on the way through the proxy names the proxy and the host.

    Args:
        transport: Replaces the network (tests: an in-process fake issuer).
        network: The outbound settings; direct, with the system's trust, when None.

    Returns:
        The client; the caller closes it.
    """
    if transport is None:
        transport = routed_transport(network or OutboundNetwork())
    return httpx2.AsyncClient(
        timeout=OIDC_TIMEOUT, transport=transport, follow_redirects=False, trust_env=False
    )


def sign_in_providers(
    settings: Settings, client: httpx2.AsyncClient, clock: Clock
) -> tuple[dict[str, SignInProvider], dict[str, SignInPolicy]]:
    """Build the configured identity providers and their policies, by name.

    Args:
        settings: The runtime configuration (``auth.providers`` and ``public_url``).
        client: The HTTP client the providers are called through.
        clock: The current time.

    Returns:
        The providers and their policies, under the same names.
    """
    providers: dict[str, SignInProvider] = {}
    policies: dict[str, SignInPolicy] = {}
    for name, config in settings.auth.providers.items():
        icon = config.built_in_icon
        policies[name] = SignInPolicy(
            name=name,
            display_name=config.display_name or name,
            allowed_groups=frozenset(config.allowed_groups),
            allow_any_user=config.admits_anyone,
            admin_groups=frozenset(config.admin_groups),
            group_prefix=config.group_prefix,
            revalidate_every=timedelta(minutes=config.revalidate_minutes),
            grace=timedelta(minutes=config.revalidate_grace_minutes),
            auto_create_users=config.creates_accounts,
            icon=None if icon is None else BuiltInIcon(icon),
            icon_file=None if config.icon_file is None else _icon(name, config.icon_file),
        )
        if config.protocol == "github":
            providers[name] = GithubProvider(
                base_url=config.base_url.rstrip("/"),
                api_url=github_api_url(config.base_url, config.api_url),
                client_id=config.client_id,
                client_secret=client_secret_reader(name, config),
                redirect_uri=f"{settings.public_url}{V1_PREFIX}/auth/{name}/callback",
                allowed_orgs=tuple(config.allowed_orgs),
                allowed_teams=tuple(config.allowed_teams),
                client=client,
            )
            continue
        if config.protocol == "oauth2":
            providers[name] = OAuth2Provider(
                issuer=config.issuer,
                authorization_endpoint=config.authorization_url or "",
                token_endpoint=config.token_url or "",
                userinfo_endpoint=config.userinfo_url or "",
                client_id=config.client_id,
                client_secret=client_secret_reader(name, config),
                redirect_uri=f"{settings.public_url}{V1_PREFIX}/auth/{name}/callback",
                scopes=tuple(config.scopes),
                claims=OAuth2ClaimNames(
                    subject=config.subject_claim,
                    username=config.username_claim,
                    email=config.email_claim,
                    groups=config.groups_claim,
                ),
                client_auth_method=config.client_auth_method,
                client=client,
            )
            continue
        providers[name] = OidcProvider(
            issuer=config.issuer,
            client_id=config.client_id,
            client_secret=client_secret_reader(name, config),
            redirect_uri=f"{settings.public_url}{V1_PREFIX}/auth/{name}/callback",
            scopes=tuple(config.scopes),
            claims=OidcClaimNames(
                username=config.username_claim,
                email=config.email_claim,
                groups=config.groups_claim,
            ),
            client=client,
            clock=clock,
            discovery_url=config.discovery_url,
            authorization_params=GOOGLE_AUTHORIZATION_PARAMS if config.kind == "google" else {},
        )
    return providers, policies


def _icon(name: str, path: Path) -> ProviderIcon:
    """Read and check a provider's own icon file.

    Args:
        name: The provider's name, for the message.
        path: The ``icon_file`` setting.

    Returns:
        The icon, an SVG sanitised.

    Raises:
        StartupError: The file cannot be read, or it is not an acceptable icon.
    """
    try:
        return read_icon(path)
    except ValueError as error:
        message = f"sign-in provider {name!r}: icon_file {str(path)!r}: {error}"
        raise StartupError(message) from None


def cloudflare_access(
    settings: Settings, client: httpx2.AsyncClient, clock: Clock
) -> tuple[CloudflareAccessVerifier, AccessPolicy] | None:
    """Build the Cloudflare Access verifier and policy, when ``[auth.cloudflare_access]`` is set.

    Args:
        settings: The runtime configuration.
        client: The HTTP client the team's certs are fetched through.
        clock: The current time.

    Returns:
        The verifier and the policy; ``None`` while Access is not configured.
    """
    config = settings.auth.cloudflare_access
    if config is None:
        return None
    policy = AccessPolicy(
        team_domain=config.team_domain,
        admin_emails=frozenset(config.admin_emails),
        auto_create_users=config.auto_create_users,
        service_tokens=MappingProxyType(
            {client_id: Username(name) for client_id, name in config.service_tokens.items()}
        ),
    )
    verifier = CloudflareAccessVerifier(
        team_domain=policy.team_domain,
        audiences=frozenset(config.audience),
        client=client,
        clock=clock,
    )
    return verifier, policy


def client_secret_reader(name: str, config: SignInProviderSettings) -> Callable[[], str | None]:
    """Return what reads a provider's client secret at each use.

    Args:
        name: The provider's name, for the log.
        config: The provider's settings.

    Returns:
        A function giving the secret, or ``None`` for a public client (or an unreadable file,
        which the provider then refuses as an unknown client).
    """
    secret, path = config.client_secret, config.client_secret_file
    if secret is not None:
        return secret.get_secret_value
    if path is None:
        return lambda: None

    def read() -> str | None:
        """Read the secret file.

        Returns:
            Its content without surrounding whitespace, or ``None`` when it cannot be read.
        """
        try:
            return path.read_text("utf-8").strip() or None
        except OSError as error:
            logger.warning("sign-in provider %s: client_secret_file unreadable (%s)", name, error)
            return None

    return read


@asynccontextmanager
async def revalidating(
    revalidate: RevalidateExternalAccounts, *, every: float
) -> AsyncGenerator[None]:
    """Check due external identities in the background, every ``every`` seconds, while serving.

    A failing pass is logged and the next one runs on time. Access fails closed without this
    loop too (sessions and tokens check ``access_until``); it is what moves access forward.

    Args:
        revalidate: The identity domain's revalidation.
        every: Seconds between passes.

    Yields:
        Nothing: the block runs while the passes go on.
    """

    async def loop() -> None:
        """Run a pass, then wait, until cancelled."""
        while True:
            try:
                report = await revalidate()
            except Exception:
                logger.exception("revalidating external sign-ins failed; retried on the next pass")
            else:
                if report.revoked or report.unreachable:
                    logger.info(
                        "external sign-ins revalidated: %d extended, %d revoked, %d unreachable",
                        report.extended,
                        report.revoked,
                        report.unreachable,
                    )
            await asyncio.sleep(every)

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        # Bounded, and never raising: a pass that does not stop must not hold the server's stop.
        done, _ = await asyncio.wait({task}, timeout=SIGN_IN_STOP_SECONDS)
        if not done:
            logger.warning("a revalidation pass did not stop in time; the server stops without it")
