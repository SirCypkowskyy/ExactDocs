"""An OAuth2-only variant of the fake issuer: userinfo is the sole source of identity."""

import json
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fake_oidc import FakeIssuer


@dataclass(slots=True)
class FakeOAuth2(FakeIssuer):
    nested_claims: bool = False

    def authorize(self, url: str, subject: str) -> str:
        parts = urlsplit(url)
        params = parse_qs(parts.query)
        assert "offline_access" in params["scope"][0].split()
        params["scope"] = ["openid"]
        normalized = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(params, doseq=True), "")
        )
        return super(FakeOAuth2, self).authorize(normalized, subject)

    def _code_grant(self, form: dict[str, str]) -> Response:
        response = super(FakeOAuth2, self)._code_grant(form)
        body = json.loads(bytes(response.body))
        body.pop("id_token", None)
        return JSONResponse(body, status_code=response.status_code)

    async def _userinfo(self, request: Request) -> Response:
        response = await super(FakeOAuth2, self)._userinfo(request)
        body = json.loads(bytes(response.body))
        if self.nested_claims and response.status_code == 200:
            body = {
                "person": {
                    "subject": body.get("sub"),
                    "name": body.get("preferred_username"),
                    "groups": body.get("groups"),
                }
            }
        return JSONResponse(body, status_code=response.status_code)
