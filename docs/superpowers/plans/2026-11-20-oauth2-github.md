# OAuth2 and GitHub Sign-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete #383 provider kinds and the dependent #106 MCP provider coverage.

**Architecture:** Add two driven identity adapters behind existing SignInProvider. Preserve existing shared account linking, policies, sealed credential revalidation and typed MCP identities. Bootstrap selects provider implementations and OAuthProxy versus OIDCProxy; no new domain dependency or permission semantics.

**Tech Stack:** Python 3.14, existing httpx2/Authlib/FastMCP, pytest and behave; no dependencies added.

**Spec:** GitHub issues #383 and #106; docs/decisions/ai-retrieval.md, Sign-in for the Teams milestone.

## Global Constraints

- Stable linking: OAuth2 configured issuer (default token URL origin); GitHub API URL plus numeric user ID, never login/email.
- Preserve PKCE S256, state/browser binding, sealed credentials, grace, disabled accounts, demotion and local break-glass admin.
- GitHub scopes read:user read:org; OAuth2 offline_access; HTTPS or loopback development URLs only.
- Domains never import each other; all shared identity and MCP DTO interfaces remain unchanged.
- No added dependencies; PR targets develop; no direct main/develop push or force push.

## Review Focus

- Org/team configuration: check every org from allowed_orgs and allowed_teams first; any allowed team required when teams configured.
- Hostile pagination: never send credentials to Link hosts; request numbered pages on configured API only, bound traversal.
- Identity substitution: reject bool/nonpositive/noninteger GitHub IDs and refresh subject changes.
- GitHub restriction versus outage: distinguish SSO and app-approval 403; explicit denials revoke on revalidation while outage gets existing bounded grace.
- MCP opaque tokens: reuse typed external identity, roles and credential caches; re-read userinfo/membership at every request.

### Task 1: Generic OAuth2 adapter and configuration

**Files:** create identity/adapters/driven/oauth2.py; modify bootstrap/settings.py and bootstrap/sign_in.py; add tests/identity/test_oauth2_provider.py and fixtures/fake_oauth2.py; add features/oauth2_github.feature and steps/oauth2_github_steps.py; extend tests/bootstrap/test_settings.py (all paths under packages/exactdocs).

**Interfaces:** OAuth2ClaimNames(subject='sub', username='preferred_username', email='email', groups='groups'); OAuth2Provider(issuer, authorization_endpoint, token_endpoint, userinfo_endpoint, client_id, client_secret, redirect_uri, scopes, claims, client) implements existing SignInProvider. Its verify_id_token(token) reads userinfo for the opaque access token, preserving the current port name for compatibility. Refresh issues a refresh grant and refuses subject substitution.

- [ ] Add acceptance scenario for configured nested subject/groups claim paths; run behave feature and confirm missing provider kind fails.
- [ ] Add units for PKCE/state, offline_access, nested/literal claim paths, missing/invalid subject, code rejection, rotating refresh token, invalid_grant, changed subject, HTTP failure, malformed/oversized responses and no redirect following; confirm red.
- [ ] Implement bounded JSON HTTP helper within oauth2.py and adapter. Validate required endpoints and defaults per kind in SignInProviderSettings; preserve OIDC defaults/validation.
- [ ] Select OAuth2Provider in sign_in_providers returning dict[str, SignInProvider]; keep policies and all domain ports unchanged.
- [ ] Run targeted settings/provider tests and acceptance; commit feat(identity): add generic OAuth2 sign-in (#383).

### Task 2: GitHub/GHE adapter and membership policy

**Files:** create identity/adapters/driven/github.py and tests/identity/test_github_provider.py, fixtures/fake_github.py; modify identity/errors.py, identity/use_cases.py, bootstrap/settings.py, bootstrap/sign_in.py and task-1 acceptance feature/steps; update README.md and docs/configuration.md.

**Interfaces:** github_api_url(base_url: str, api_url: str | None) -> str; GithubProvider(base_url, api_url, client_id, client_secret, redirect_uri, allowed_orgs, allowed_teams, client) implements SignInProvider. Uses OAuth2Provider for authorization/code exchange, maps userinfo and API numeric ID to ExternalClaims, stores access token in ExternalGrant.refresh_token, rechecks it on refresh. New GitHub denial errors inherit ProviderAccessRevokedError so existing revalidation revokes; messages distinguish team/org/app approval/SSO.

- [ ] Add behave scenarios for team refusal, app approval, SSO and lost team ending browser/API-token access; run red.
- [ ] Add units for github.com, GHE /api/v3, *.ghe.com, override; numeric ID strictness/login rename; org union checks precede teams; active/pending/404 membership; paginated teams; fallback; malicious links; distinct 403 header/body handling; revoked token/outage behavior; confirm red.
- [ ] Implement endpoint derivation and GitHub API mapping, numbered-page traversal with bounded pages, fallback per allowed active org/team absent from teams. Refuse team configuration with invalid org/slug. Policy admission is adapter's verified GitHub admission plus any configured allowed_groups; when no generic allowed_groups, bootstrap admits verified GitHub users through existing policy.
- [ ] Document OAuth Apps (not GitHub Apps), callback URLs, scopes, approval and SSO setup, groups/admin_groups and revalidation.
- [ ] Run provider, existing identity regression, settings, acceptance and architecture checks; commit feat(identity): add GitHub Enterprise membership sign-in (#383).

### Task 3: MCP provider coverage and complete verification

**Files:** modify bootstrap/mcp_oauth.py; extend tests/bootstrap/test_mcp_oauth.py, fixtures/mcp_oauth_host.py, features/mcp_oauth.feature and steps/mcp_oauth_steps.py; docs/mcp.md and README.md.

**Interfaces:** build_mcp_auth(settings, identity) unchanged. OAuthProxy(upstream_authorization_endpoint, upstream_token_endpoint, upstream_client_id, upstream_client_secret, token_verifier=ExternalTokenVerifier(...)) for oauth2/github; OIDCProxy unchanged. OAuth2/GitHub adapter verify_id_token implements the shared opaque-token verification behind IdentifyExternalToken.

- [ ] Add failing real host flows against fake OAuth2/GitHub including GHE team refusal, membership loss, both restriction errors, linked identity roles and API-token coexistence.
- [ ] Build OAuthProxy from configured/derived endpoints, existing encrypted storage and signing key; scopes match each provider kind. Preserve typed identity and credential-scoped cache contract without changes to caller/bridges.
- [ ] Run targeted tests green; run PATH=/usr/bin:$PATH uv run ruff format --check ., uv run ruff check ., uv run ty check, uv run pytest and uv run behave; run just check requirements that apply. No web source changes expected because provider buttons already consume display_name generically.
- [ ] Request independent whole-branch review; fix findings and rerun impacted checks; commit, push branch, create PR to develop with evidence and Closes #383 (and Closes #106 only if all criteria pass). Hand off claims to review; coordinator handles merge.
