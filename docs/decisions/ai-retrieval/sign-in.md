# Sign-in for the Teams milestone

!!! abstract "TL;DR"
    - Several named providers run next to local accounts, each with a `kind`: `oidc` (ADFS
      included), `oauth2` or `github` (github.com, Enterprise Server or `*.ghe.com`).
    - `github` access needs an active membership in an allowed organization and, when teams are
      listed, an allowed team; each team becomes the group `github:<org>/<team>`. A 403 is
      reported as an unapproved app or missing SSO, never as "not a member".
    - Groups are refreshed at sign-in and every `revalidate_minutes` (60). When the provider
      cannot be reached, the session lasts at most `revalidate_grace_minutes` (1,440).
    - Authlib handles web sign-in; MCP (#106) uses FastMCP `OIDCProxy` or `OAuthProxy` with
      `MultiAuth`. SAML, GitHub Apps and SCIM are out of scope.

Recorded now so the PostgreSQL and provider work does not paint it into a corner; built in #105
and #106.

- **Several named providers** at once, next to local accounts (the local admin stays as
  break-glass). Each has a `kind`:
    - **`oidc`**: discovery from `<issuer>/.well-known/openid-configuration`, authorization code
      with PKCE, the ID token checked against the JWKS, configurable claims for username, email and
      groups. Works for Keycloak, Entra ID, Okta, Google, Auth0 and the like.
    - **ADFS is `oidc`** (ADFS 2016 and later; issuer `https://<host>/adfs`). Its quirks are
      configuration: the username from `upn` or `unique_name`, groups from the `group` claim that an
      issuance transform rule must emit (documented).
    - **`oauth2`**: for providers without OIDC; authorize, token and userinfo URLs and claim paths
      for subject, username, email and groups.
    - **`github`**: an OAuth App at a configurable `base_url`, one of:
        - `https://github.com`
        - a **GitHub Enterprise Server** host (API derived as `<base>/api/v3`)
        - GitHub Enterprise Cloud with data residency (`https://<subdomain>.ghe.com`, whose API is
          `https://api.<subdomain>.ghe.com`)

        An optional `api_url` overrides the derived one. Scopes `read:user read:org`.

        - Access requires an `active` membership in an allowed organization
          (`GET /user/memberships/orgs/{org}`, checked **first**, per organization) and, when teams
          are listed, in an allowed team.
        - Teams are then read with one paginated `GET /user/teams` and matched against the allowed
          list. It silently omits teams of organizations that restrict the app or need SSO, so
          only the per-org check can produce the 403 messages below.
        - The per-team `GET /orgs/{org}/teams/{team_slug}/memberships/{username}` is the fallback
          for one team.
        - Each allowed team becomes the ExactDocs group `github:<org>/<team>`.
    - **GitHub 403s are not "not a member".**
        - An organization with OAuth App access restrictions must approve the OAuth App, and a
          SAML-enforced organization needs the token authorized for SSO. Otherwise the membership
          call answers 403.
        - Those answers are refused as "organization *acme* has not approved this app" or
          "authorize SSO for *acme*", with the setup documented, never as "not a member".
- **Membership follows the provider.**
    - Groups and memberships are refreshed at every sign-in and every `revalidate_minutes`
      (default 60) with the user's provider token, sealed by the secret box (#248).
    - A revoked token or a lost membership ends the session.
    - When the provider cannot be reached, the session lasts at most `revalidate_grace_minutes`
      (default 1,440), then access is refused (fail closed).
    - `github`: OAuth App tokens do not expire, so the stored access token is enough.
    - `oidc`, `oauth2` and ADFS need a **refresh token** to fetch fresh groups. ExactDocs asks for
      `offline_access` (ADFS: refresh tokens enabled on the application group) and refreshes,
      then re-reads the ID token or userinfo claims.
    - A provider that issues **no refresh token** cannot be revalidated. Such a session is limited
      to `revalidate_grace_minutes` after sign-in, then the user signs in again (and groups are
      refreshed then). The UI and the docs say so.
- **Libraries:**
    - Authlib for the web sign-in. It is already in the lock through FastMCP, at 1.9.3 from
      2026-11-03; the floor `authlib>=1.9.1` is the version released 2026-10-14.
    - For MCP (#106), one provider is chosen (`EXACTDOCS_MCP_OAUTH_PROVIDER`):
        - FastMCP `OIDCProxy` for `oidc` (ADFS included)
        - `OAuthProxy` with the provider's endpoints for `oauth2` and `github` (FastMCP's
          `GitHubProvider` hard-codes github.com)

        Each comes with our token verifier applying the same membership checks, combined with API
        tokens through `MultiAuth`.
- **Out of scope:** SAML, GitHub Apps (instead of OAuth Apps), SCIM provisioning.
