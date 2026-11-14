"""External sign-in wiring: identity providers from the settings, and the revalidation loop.

Each ``[auth.providers.<name>]`` becomes the identity domain's ``SignInPolicy`` (who is admitted,
with which role and groups, for how long) and an ``OidcProvider`` (the protocol). The redirect
URI is built from ``EXACTDOCS_PUBLIC_URL``, never from a request. The client secret is read at
every use, so a rotated ``client_secret_file`` needs no restart.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

import httpx2

from exactdocs.bootstrap.constants import SIGN_IN_STOP_SECONDS, V1_PREFIX
from exactdocs.bootstrap.settings import Settings, SignInProviderSettings
from exactdocs.identity.adapters.driven.oidc import OidcClaimNames, OidcProvider
from exactdocs.identity.constants import OIDC_TIMEOUT
from exactdocs.identity.models import SignInPolicy
from exactdocs.identity.ports.driving import RevalidateExternalAccounts
from exactdocs_kernel import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SignInStandIns:
    """What tests put in place of the identity domain's time and its providers' network."""

    clock: Clock | None = None
    """The identity domain's time (sessions, sign-in attempts, revalidation)."""
    transport: httpx2.AsyncBaseTransport | None = None
    """Carries the calls to the identity providers (an in-process fake issuer)."""


def sign_in_client(transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
    """Return the HTTP client every identity provider is called through.

    The environment's proxy variables are honoured (an IdP is often reached through the
    corporate proxy); redirects are never followed.

    Args:
        transport: Replaces the network (tests: an in-process fake issuer).

    Returns:
        The client; the caller closes it.
    """
    return httpx2.AsyncClient(timeout=OIDC_TIMEOUT, transport=transport, follow_redirects=False)


def sign_in_providers(
    settings: Settings, client: httpx2.AsyncClient, clock: Clock
) -> tuple[dict[str, OidcProvider], dict[str, SignInPolicy]]:
    """Build the configured identity providers and their policies, by name.

    Args:
        settings: The runtime configuration (``auth.providers`` and ``public_url``).
        client: The HTTP client the providers are called through.
        clock: The current time.

    Returns:
        The providers and their policies, under the same names.
    """
    providers: dict[str, OidcProvider] = {}
    policies: dict[str, SignInPolicy] = {}
    for name, config in settings.auth.providers.items():
        policies[name] = SignInPolicy(
            name=name,
            display_name=config.display_name or name,
            allowed_groups=frozenset(config.allowed_groups),
            allow_any_user=config.allow_any_user,
            admin_groups=frozenset(config.admin_groups),
            group_prefix=config.group_prefix,
            revalidate_every=timedelta(minutes=config.revalidate_minutes),
            grace=timedelta(minutes=config.revalidate_grace_minutes),
        )
        providers[name] = OidcProvider(
            issuer=config.issuer,
            client_id=config.client_id,
            client_secret=_client_secret(name, config),
            redirect_uri=f"{settings.public_url}{V1_PREFIX}/auth/{name}/callback",
            scopes=tuple(config.scopes),
            claims=OidcClaimNames(
                username=config.username_claim,
                email=config.email_claim,
                groups=config.groups_claim,
            ),
            client=client,
            clock=clock,
        )
    return providers, policies


def _client_secret(name: str, config: SignInProviderSettings) -> Callable[[], str | None]:
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
