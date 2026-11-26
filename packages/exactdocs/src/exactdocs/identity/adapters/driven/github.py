"""GitHub OAuth App provider, including Enterprise Server and data-residency Cloud."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from urllib.parse import quote, urlsplit

import httpx2

from exactdocs.identity.adapters.driven.oauth2 import OAuth2Provider, request_json, text
from exactdocs.identity.constants import GITHUB_MAX_TEAM_PAGES, OAUTH_CLIENT_POST
from exactdocs.identity.errors import (
    ExternalSignInFailedError,
    GithubAccessDeniedError,
    ProviderAccessRevokedError,
    ProviderUnavailableError,
)
from exactdocs.identity.models import ExternalClaims, ExternalGrant


def github_api_url(base_url: str, api_url: str | None = None) -> str:
    """Derive the GitHub API namespace used for both calls and stable identity linking.

    Args:
        base_url: The configured web origin.
        api_url: An optional explicit API URL.

    Returns:
        The API URL without a trailing slash.
    """
    if api_url:
        return api_url.rstrip("/")
    base = base_url.rstrip("/")
    parts = urlsplit(base)
    if parts.hostname == "github.com":
        return "https://api.github.com"
    if parts.hostname and parts.hostname.endswith(".ghe.com"):
        return f"{parts.scheme}://api.{parts.netloc}"
    return f"{base}/api/v3"


@dataclass(frozen=True, slots=True, kw_only=True)
class GithubProvider:
    """Verify GitHub identity and membership using its non-expiring OAuth App token."""

    base_url: str
    """The GitHub web origin."""
    api_url: str
    """The canonical API URL and stable linking issuer."""
    client_id: str
    """Registered OAuth App client ID."""
    client_secret: Callable[[], str | None] = field(repr=False)
    """Reads the current OAuth App secret."""
    redirect_uri: str
    """The registered browser callback."""
    allowed_orgs: tuple[str, ...]
    """Organizations with active membership that can admit a person."""
    allowed_teams: tuple[str, ...]
    """Teams in org/slug form; at least one is mandatory when configured."""
    client: httpx2.AsyncClient = field(repr=False)
    """Bootstrap's timeout-bound provider HTTP client."""
    watched: Callable[[], Awaitable[tuple[frozenset[str], frozenset[str]]]] | None = field(
        default=None, repr=False
    )
    """The organizations and ``org/team`` names role rules name (case folded), read at every
    check; their active memberships become groups without deciding admission."""

    def _oauth(self) -> OAuth2Provider:
        """Return the authorization-code protocol adapter for this OAuth App.

        Returns:
            The shared PKCE/code-exchange implementation.
        """
        return OAuth2Provider(
            issuer=self.api_url,
            authorization_endpoint=f"{self.base_url}/login/oauth/authorize",
            token_endpoint=f"{self.base_url}/login/oauth/access_token",
            userinfo_endpoint=f"{self.api_url}/user",
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scopes=("read:user", "read:org"),
            client=self.client,
            client_auth_method=OAUTH_CLIENT_POST,
        )

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """Build the PKCE S256 authorization URL with read:user and read:org.

        Args:
            state: The browser-bound attempt state.
            nonce: Unused by OAuth2.
            code_verifier: The secret verifier.

        Returns:
            GitHub's authorization URL.
        """
        return await self._oauth().authorization_url(
            state=state, nonce=nonce, code_verifier=code_verifier
        )

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> ExternalGrant:
        """Trade a code for an OAuth App token and verify membership before admission.

        Args:
            code: GitHub's single-use code.
            code_verifier: The server-held verifier.
            nonce: Unused by OAuth2.

        Returns:
            Current identity with its access token as the sealed revalidation credential.

        Raises:
            ExternalSignInFailedError: The exchange was refused or no access token exists.
        """
        del nonce
        status, body = await self._oauth().token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": self.redirect_uri,
            }
        )
        access = text(body, "access_token")
        if status != HTTPStatus.OK or body.get("error") is not None or access is None:
            raise ExternalSignInFailedError
        return ExternalGrant(claims=await self.verify_id_token(access), refresh_token=access)

    async def verify_id_token(self, id_token: str) -> ExternalClaims:
        """Verify the opaque access token against the GitHub user and membership APIs.

        Args:
            id_token: GitHub's opaque OAuth App token (the shared port's historic name).

        Returns:
            API URL and numeric ID identity, with verified configured team groups.

        Raises:
            ExternalSignInFailedError: The user identity is malformed.
            ProviderUnavailableError: An API response is unusable.
        """
        status, _, user = await self._get("/user", id_token)
        if status != HTTPStatus.OK or not isinstance(user, dict):
            raise ProviderUnavailableError
        identifier, login = user.get("id"), user.get("login")
        if (
            type(identifier) is not int
            or identifier <= 0
            or not isinstance(login, str)
            or not login
        ):
            raise ExternalSignInFailedError
        groups = await self._membership_groups(id_token, login)
        email = user.get("email")
        return ExternalClaims(
            issuer=self.api_url,
            subject=str(identifier),
            username=login,
            email=email if isinstance(email, str) and email else None,
            groups=frozenset(groups),
        )

    async def _active_orgs(self, token: str) -> set[str]:
        """Check all organization filters, including organizations of allowed teams.

        Args:
            token: The verified user's access token.

        Returns:
            The active organizations, case folded.

        Raises:
            ProviderUnavailableError: An organization response cannot be read.
            GithubAccessDeniedError: No configured organization is active.
        """
        orgs = set(self.allowed_orgs) | {team.split("/", 1)[0] for team in self.allowed_teams}
        active: set[str] = set()
        # This must precede /user/teams: that endpoint silently omits restricted organizations.
        for org in sorted(orgs):
            status, _, membership = await self._get(
                f"/user/memberships/orgs/{quote(org, safe='')}", token, org=org
            )
            if status == HTTPStatus.OK and _active_membership(membership):
                active.add(org.casefold())
            elif status not in {HTTPStatus.OK, HTTPStatus.NOT_FOUND}:
                raise ProviderUnavailableError
        if orgs and not active:
            message = "not a member of an allowed organization"
            raise GithubAccessDeniedError(message, refusal_code="github_org_required")
        return active

    async def _membership_groups(self, token: str, login: str) -> frozenset[str]:
        """Check organization admission before teams and map configured memberships.

        The filters (``allowed_orgs``, ``allowed_teams``) decide admission. Organizations and
        teams that role rules name only add groups: a restriction there means no group, never
        a refusal.

        Args:
            token: The verified user's access token.
            login: The current login for fallback membership calls.

        Returns:
            Verified groups: ``github:<org>`` for organizations rules name, and
            ``github:<org>/<team>`` for allowed teams and teams rules name.

        Raises:
            GithubAccessDeniedError: No configured membership admits the user.
        """
        active = await self._active_orgs(token)
        rule_orgs, rule_teams = (
            (frozenset(), frozenset()) if self.watched is None else await self.watched()
        )
        filters = {org.casefold() for org in self.allowed_orgs} | {
            team.split("/", 1)[0].casefold() for team in self.allowed_teams
        }
        wanted = rule_orgs | {team.split("/", 1)[0] for team in rule_teams}
        active |= await self._rule_orgs(token, wanted - filters)
        groups = {f"github:{org}" for org in rule_orgs if org in active}
        found = await self._listed_teams(token, rule_teams)
        if self.allowed_teams:
            allowed = {
                f"github:{team}"
                for team in self.allowed_teams
                if team.split("/", 1)[0].casefold() in active
                and await self._in_team(token, login, team, found, admits=True)
            }
            if not allowed:
                message = "not a member of an allowed team"
                raise GithubAccessDeniedError(message, refusal_code="github_team_required")
            groups |= allowed
        named = {team.casefold() for team in self.allowed_teams}
        for team in sorted(rule_teams - named):
            if team.split("/", 1)[0] in active and await self._in_team(
                token, login, team, found, admits=False
            ):
                groups.add(f"github:{team}")
        return frozenset(groups)

    async def _listed_teams(self, token: str, rule_teams: frozenset[str]) -> set[str]:
        """Read ``/user/teams`` when a team is configured or named by a rule.

        Args:
            token: The verified user's access token.
            rule_teams: The teams role rules name.

        Returns:
            The listed teams; for rule teams alone, none when the list cannot be read (each is
            then asked on its own), so a rule never blocks a sign-in the filters admit.
        """
        if self.allowed_teams:
            return await self._teams(token)
        if not rule_teams:
            return set()
        try:
            return await self._teams(token)
        except ProviderUnavailableError, GithubAccessDeniedError:
            return set()

    async def _rule_orgs(self, token: str, orgs: frozenset[str] | set[str]) -> set[str]:
        """Check the organizations only role rules name; a restricted one counts as none.

        Args:
            token: The verified user's access token.
            orgs: The organizations, case folded.

        Returns:
            Those with an active membership. An organization that refuses, cannot be read or
            answers oddly counts as none: a rule never blocks a sign-in the filters admit.
        """
        active: set[str] = set()
        for org in sorted(orgs):
            try:
                status, _, membership = await self._get(
                    f"/user/memberships/orgs/{quote(org, safe='')}", token, org=org
                )
                if status == HTTPStatus.OK and _active_membership(membership):
                    active.add(org)
            except GithubAccessDeniedError, ProviderUnavailableError:
                continue
        return active

    async def _in_team(
        self, token: str, login: str, team: str, found: set[str], *, admits: bool
    ) -> bool:
        """Check one team membership: the listed teams first, then the membership API.

        Args:
            token: The verified user's access token.
            login: The current login.
            team: ``org/team-slug``.
            found: The teams ``/user/teams`` listed, case folded.
            admits: Whether the team decides admission (a restriction then refuses).

        Returns:
            Whether the membership is active.

        Raises:
            GithubAccessDeniedError: An admitting team's organization restricts access.
            ProviderUnavailableError: A membership response cannot be read.
        """
        if team.casefold() in found:
            return True
        org, slug = team.split("/", 1)
        path = (
            f"/orgs/{quote(org, safe='')}/teams/{quote(slug, safe='')}"
            f"/memberships/{quote(login, safe='')}"
        )
        try:
            status, _, membership = await self._get(path, token, org=org)
            return _member(status, membership)
        except GithubAccessDeniedError, ProviderUnavailableError:
            if admits:
                raise
            return False

    async def refresh(self, refresh_token: str, *, subject: str) -> ExternalGrant:
        """Revalidate the stored non-expiring access token and every membership.

        Args:
            refresh_token: The unsealed GitHub access token.
            subject: The numeric user ID of the linked account.

        Returns:
            Current identity and the same credential.

        Raises:
            ExternalSignInFailedError: GitHub describes a different numeric ID.
        """
        claims = await self.verify_id_token(refresh_token)
        if claims.subject != subject:
            raise ExternalSignInFailedError
        return ExternalGrant(claims=claims, refresh_token=refresh_token)

    async def _teams(self, token: str) -> set[str]:
        """Read configured-origin numbered team pages without trusting provider Link URLs.

        Args:
            token: The access token.

        Returns:
            Team names in case-insensitive org/slug form, or empty for an unsupported endpoint.

        Raises:
            ProviderUnavailableError: Bad response or unfinished pagination at the bound.
        """
        teams: set[str] = set()
        for page in range(1, GITHUB_MAX_TEAM_PAGES + 1):
            status, headers, body = await self._get(f"/user/teams?per_page=100&page={page}", token)
            if status == HTTPStatus.NOT_FOUND:
                return teams
            if status != HTTPStatus.OK or not isinstance(body, list):
                raise ProviderUnavailableError
            for team in body:
                if not isinstance(team, dict) or not isinstance(team.get("organization"), dict):
                    raise ProviderUnavailableError
                org, slug = team["organization"].get("login"), team.get("slug")
                if not isinstance(org, str) or not isinstance(slug, str):
                    raise ProviderUnavailableError
                teams.add(f"{org}/{slug}".casefold())
            if not any(
                'rel="next"' in link or "rel=next" in link
                for link in headers.get("link", "").split(",")
            ):
                return teams
        raise ProviderUnavailableError

    async def _get(
        self, path: str, token: str, *, org: str | None = None
    ) -> tuple[int, httpx2.Headers, object]:
        """Read a GitHub API response, distinguishing restrictions from revocation/outage.

        Args:
            path: An internally constructed API path.
            token: The opaque access token.
            org: The configured organization for restriction messages.

        Returns:
            HTTP status, headers and JSON response.

        Raises:
            ProviderAccessRevokedError: The token is refused.
            ProviderUnavailableError: Rate limiting or server failure.
            GithubAccessDeniedError: App approval, SSO or another explicit access restriction.
        """
        status, headers, body = await request_json(
            self.client,
            "GET",
            f"{self.api_url}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        if status == HTTPStatus.UNAUTHORIZED:
            raise ProviderAccessRevokedError
        if status == HTTPStatus.FORBIDDEN:
            message = body.get("message", "") if isinstance(body, dict) else ""
            if (
                headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in headers
                or "rate limit" in str(message).lower()
            ):
                raise ProviderUnavailableError
            organization = org or "the configured organization"
            if headers.get("x-github-sso", "").lower().startswith("required"):
                message = f"authorize SSO for {organization}"
                raise GithubAccessDeniedError(
                    message, refusal_code=f"github_sso_required:{organization}"
                )
            if (
                "oauth app access restrictions" in str(message).lower()
                or "third-party application access" in str(message).lower()
            ):
                message = f"organization {organization} has not approved this app"
                raise GithubAccessDeniedError(
                    message, refusal_code=f"github_app_not_approved:{organization}"
                )
            message = f"organization {organization} refused access"
            raise GithubAccessDeniedError(
                message, refusal_code=f"github_access_denied:{organization}"
            )
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailableError
        return status, headers, body


def _active_membership(membership: object) -> bool:
    """Distinguish a real membership decision from an unusable provider response.

    Args:
        membership: The successful organization or team membership response.

    Returns:
        Whether membership is active; pending membership does not admit access.

    Raises:
        ProviderUnavailableError: The membership state is missing or unrecognized.
    """
    state = membership.get("state") if isinstance(membership, dict) else None
    if not isinstance(state, str) or state not in {"active", "pending"}:
        raise ProviderUnavailableError
    return state == "active"


def _member(status: int, membership: object) -> bool:
    """Read a team membership answer.

    Args:
        status: The HTTP status.
        membership: The JSON response.

    Returns:
        Whether the membership is active; 404 means none.

    Raises:
        ProviderUnavailableError: Any other status, or an unusable membership.
    """
    if status not in {HTTPStatus.OK, HTTPStatus.NOT_FOUND}:
        raise ProviderUnavailableError
    return status == HTTPStatus.OK and _active_membership(membership)
