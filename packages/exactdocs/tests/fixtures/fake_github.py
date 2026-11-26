"""GitHub OAuth App and membership API, using the same code/PKCE issuer harness."""

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fake_oidc import FakeIssuer


@dataclass(slots=True)
class FakeGithub(FakeIssuer):
    api_url: str = "https://github.example.com/api/v3"
    orgs: set[str] = field(default_factory=lambda: {"acme"})
    teams: list[tuple[str, str]] = field(default_factory=lambda: [("acme", "docs-readers")])
    restricted: str | None = None
    restricted_orgs: set[str] = field(default_factory=set)
    """Organizations that refuse the app (OAuth App access restrictions), whatever `restricted`."""
    pages: int = 1
    requests: list[str] = field(default_factory=list)
    numeric_id: object = 123
    membership_state: object = "active"
    fallback_state: object = "active"
    fallback_active: bool = False
    fail_teams: bool = False

    @property
    def app(self) -> Starlette:
        prefix = urlsplit(self.api_url).path
        return Starlette(
            routes=[
                Route("/login/oauth/access_token", self._token, methods=["POST"]),
                Route(prefix + "/user", self._user),
                Route(prefix + "/user/memberships/orgs/{org}", self._membership),
                Route(prefix + "/user/teams", self._teams),
                Route(prefix + "/orgs/{org}/teams/{team}/memberships/{username}", self._fallback),
            ]
        )

    def authorize(self, url: str, subject: str) -> str:
        parts = urlsplit(url)
        params = parse_qs(parts.query)
        assert params["scope"] == ["read:user read:org"]
        params["scope"] = ["openid"]
        normalized = urlunsplit(
            (parts.scheme, parts.netloc, "/authorize", urlencode(params, doseq=True), "")
        )
        return super(FakeGithub, self).authorize(normalized, subject)

    async def _token(self, request: Request) -> Response:
        form = {key: str(value) for key, value in (await request.form()).items()}
        self.token_requests.append(form)
        if (
            form.get("client_id") != self.client_id
            or form.get("client_secret") != self.client_secret
        ):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        return self._code_grant(form)

    async def _user(self, request: Request) -> Response:
        self.requests.append(request.url.path)
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        subject = self.access_tokens.get(token)
        if subject is None:
            return JSONResponse({}, status_code=401)
        user = self.users[subject]
        return JSONResponse({"id": self.numeric_id, "login": user.username, "email": user.email})

    async def _membership(self, request: Request) -> Response:
        self.requests.append(request.url.path)
        if self.restricted == "sso":
            return JSONResponse(
                {"message": "Resource protected by organization SAML enforcement."},
                status_code=403,
                headers={"X-GitHub-SSO": "required; url=https://github.example.com/sso"},
            )
        if self.restricted == "app" or request.path_params["org"] in self.restricted_orgs:
            return JSONResponse(
                {"message": "The organization has enabled OAuth App access restrictions."},
                status_code=403,
            )
        if self.restricted == "rate":
            return JSONResponse(
                {"message": "API rate limit exceeded"},
                status_code=403,
                headers={"X-RateLimit-Remaining": "0"},
            )
        if self.restricted == "unknown":
            return JSONResponse({"message": "Refused"}, status_code=403)
        org = request.path_params["org"]
        return JSONResponse(
            {"state": self.membership_state} if org in self.orgs else {},
            status_code=200 if org in self.orgs else 404,
        )

    async def _teams(self, request: Request) -> Response:
        self.requests.append(str(request.url))
        if self.fail_teams:
            return JSONResponse({}, status_code=404)
        page = int(request.query_params.get("page", "1"))
        headers = (
            {"Link": f'<https://evil.example/steal?page={page + 1}>; rel="next"'}
            if page < self.pages
            else {}
        )
        teams = self.teams if page == self.pages else []
        return JSONResponse(
            [{"organization": {"login": org}, "slug": team} for org, team in teams], headers=headers
        )

    async def _fallback(self, request: Request) -> Response:
        self.requests.append(request.url.path)
        active = (
            self.fallback_active
            and (request.path_params["org"], request.path_params["team"]) in self.teams
        )
        return JSONResponse(
            {"state": self.fallback_state} if active else {}, status_code=200 if active else 404
        )
