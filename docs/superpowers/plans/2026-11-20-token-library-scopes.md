# Token Library Scopes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement #111: tokens act as their user with an optional library subset, and inaccessible libraries behave like missing libraries.

**Architecture:** Persist a nullable library selection on API tokens (`None` means all libraries the user can access; empty means none). Return a typed API principal at authentication, propagate it independently of the OAuth principal, and intersect live grants with the selection in the identity access bridge. Hide inaccessible resources using each domain's existing not-found error while preserving forbidden for readable resources with insufficient edit roles.

**Tech Stack:** Python 3.14, immutable Pydantic DTOs/dataclasses, SQLAlchemy Core/Alembic, FastAPI/FastMCP, React/TanStack Query, pytest/behave/vitest.

**Spec:** GitHub issues #111 and #108; `docs/architecture.md`; #407's typed OAuth principal and resource partition contract.

## Global Constraints

- Tokens scoped to their user and optionally to chosen libraries; listings, `resolve-library-id`, errors and caches filtered.
- No access looks like not found; library roles are intersected with scopes, never granted by scopes.
- Legacy tokens remain unrestricted within current user grants; disabled accounts, expired and revoked tokens are refused at every new request.
- Domains never import each other or bootstrap; ports remain Protocols. Do not change account IDs used for spend budgets or audit.
- Branch from develop, normal pushes only, PR targets develop, no AI attribution.

## Review Focus

- Two API credentials for the same account with different library subsets cannot reuse a broader resource snapshot.
- JSON claims, wrong-account typed principals and a bound REST caller must not inherit a different credential's scope or OAuth groups.
- Scope `None`, an empty selection, duplicate IDs and mixed-case IDs have distinct, canonical behavior; legacy rows stay unrestricted.
- Hidden libraries, chunks, articles, assets and edits match their corresponding missing-resource responses; readable viewers still receive forbidden for edits.
- User grants can shrink after issuance and token revocation/account disable take effect without a cache bypass; budgets still use the actual account ID.

---

### Task 1: Scoped credential persistence and identity

**Files:** `identity/models.py`, `dtos.py`, `ports/driving.py`, `use_cases.py`, `adapters/driven/sqlite.py`; new Alembic revision; `features/tokens.feature`, `features/steps/tokens_steps.py`; `tests/identity/test_tokens.py`, `test_token_repository.py`; new migration test.

**Interfaces:** `ApiToken.library_ids: frozenset[str] | None = None`; command and summary `library_ids` fields with the same semantics. `ApiTokenIdentity(AccountSummary)` adds `token_id: str` and `library_ids: frozenset[str] | None`; `IdentifyToken.__call__(token: str) -> ApiTokenIdentity`. IDs are casefolded; empty remains empty. No token secret is carried past authentication.

- [ ] Add an HTTP acceptance scenario creating a scoped token and demonstrating one granted library is hidden by its selection. Run the scenario and record the failure before implementation.
- [ ] Add identity tests for selected/empty/unrestricted scopes, normalization, grant summary and authenticated principal; adapter contracts round-trip all three selections, including last-use touch.
- [ ] Run focused pytest and confirm failures for the absent fields.
- [ ] Add nullable JSON-encoded TEXT column `library_ids` to identity_api_tokens and query metadata; SQL NULL means unrestricted, JSON `[]` means no access. Add legacy-row migration test and reversible downgrade.
- [ ] Populate selection on creation/login and return typed principal on identify while preserving the current live account/external-access checks and touch behavior.
- [ ] Run token identity, repository, migration tests and acceptance scenario; commit the tested identity change.

### Task 2: Trusted scope propagation, authorization intersection and cache partition

**Files:** `identity/adapters/driving/http.py`, `identity/adapters/driving/mcp.py`; `bootstrap/caller.py`, `http.py`, `bridges.py`, `container.py`, `mcp.py`; `identity/dtos.py`, `use_cases.py` for grant operations; `tests/bootstrap/test_oauth_caller_context.py`, new API principal tests, `test_mcp_browse.py`, `test_library_roles_api.py`.

**Interfaces:** `bind_caller(account_id: str, *, api_identity: ApiTokenIdentity | None = None) -> None`; `current_api_identity() -> ApiTokenIdentity | None`. HTTP binds the typed authenticated principal; MCP inserts only that typed object as `api_identity`. `IdentityAccessPolicy` consumes an optional `api_identity: Callable[[], ApiTokenIdentity | None]`; readable/allows intersect selection with live resolve_library_roles result. Grant route commands carry the trusted selection so direct identity sharing endpoints cannot bypass it.

- [ ] Add failing unit tests rejecting JSON scope claims and mismatched account principals, preventing same-account REST/session inheritance of MCP credentials, and preserving MultiAuth original IDs.
- [ ] Add failing REST/MCP tests for two same-account tokens with disjoint scopes and broad-then-narrow resource list/read cache calls; confirm current snapshot reuse fails the expectation.
- [ ] Propagate authenticated API identity, preserving OAuth typed identity handling and actual account IDs for retrieval budgets.
- [ ] Intersect readable/allows with selected IDs and apply the same intersection to identity grant list/create/revoke authorization; canonical resource key includes credential kind, account, token ID and sorted selected IDs. OAuth key remains role/groups-sensitive.
- [ ] Exercise live grant removal with a warm resource snapshot before TTL (same token must stop listing/reading the revoked library), account disable, token revocation and empty scopes over both transports; run focused access/OAuth/resource tests and commit.

### Task 3: Indistinguishable hidden resources

**Files:** `catalog/use_cases.py`, `retrieval/use_cases.py`, `ingestion/use_cases.py`, identity sharing errors/use cases as needed; `features/library_roles.feature`, `features/steps/library_roles_steps.py`; domain access tests and `tests/bootstrap/test_library_roles_api.py`.

**Interfaces:** Existing `_require(access, library, needed)` helpers first check READ: absent read produces domain library-not-found (`LibraryNotFoundError` or `UnknownLibraryError`); readable callers below `needed` keep `LibraryAccessDeniedError`. Opaque chunk/asset/article identifiers use their existing resource-not-found error before exposing associated library metadata. Tests compare error code and detail against missing-resource responses, including grant endpoints, rather than asserting status alone.

- [ ] Add acceptance comparison of hidden versus nonexistent `query-docs`, plus REST library read and edit; assert library absent from listings and resolve results. Run red before implementation.
- [ ] Add precise tests for hidden/missing chunks, resources and assets (including unknown versions), scoped mutation/grants, readable viewer forbidden edits, and list/search/resolve filtering. Update prior no-role 403 expectations to the new 404 contract while retaining the role-action matrix.
- [ ] Implement hidden-resource error mapping in domain access checks and resource-specific lookups, ensuring hidden version/article/asset existence is never revealed before access checks.
- [ ] Run domain access matrices, bootstrap REST/MCP tests, and acceptance scenarios; commit.

### Task 4: Token creation surfaces and full review

**Files:** token CLI commands/helpers and their tests; `web/src/features/tokens/{model/token.ts,api/tokens-query.ts,components/create-token-dialog.tsx,components/token-list.tsx,tokens.test.tsx}`; token documentation.

**Interfaces:** REST creation accepts optional `library_ids`; CLI token creation and login accept repeatable `--library` to select IDs, omitting it means unrestricted. Token UI offers an optional library-ID selection with an explicit unrestricted default and shows the chosen scope in token rows; feature imports obey vertical-slice architecture.

- [ ] Add failing CLI serialization tests and token UI creation/summary tests for omitted versus selected IDs.
- [ ] Implement selection without changing current default behavior; document the distinction and live user-grant intersection.
- [ ] Run `uv run ruff format .`, `uv run ruff check .`, `uv run ty check`, full `uv run pytest`, `uv run behave`; run `pnpm lint`, `pnpm test`, `pnpm build` in web. Use ephemeral PATH preferring /usr/bin Git 2.47 for fixture flags; do not change global Git configuration.
- [ ] Obtain independent access review plus coordinator final review; fix findings and repeat only affected checks, retaining complete full-check evidence.
- [ ] Commit, normal push, create PR targeting develop with Closes #111 and actual check summaries; hand off issue using repository script. Merge only after coordinator review and required PR checks.
