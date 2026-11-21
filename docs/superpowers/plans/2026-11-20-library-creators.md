# Library creation permission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators restrict library creation to stable users or mapped identity-provider groups while retaining creator ownership.

**Architecture:** Add an identity driving use case resolving the instance permission from account state and verified request identity. Bootstrap bridges expose it through catalog and ingestion AccessPolicy ports. Check before remote access and catalog persistence; retain the existing ownership claim.

**Tech Stack:** Python 3.14, Pydantic settings, Protocol ports, pytest, behave.

**Spec:** GitHub #110; docs/plan.md E12-07; docs/user-stories.md ACL-03 (depends on #108).

## Global Constraints

- Work on feature/110-library-creators from develop; PR targets develop.
- Domains never import each other or bootstrap. No cross-domain foreign keys.
- Preserve existing operator and no-caller local CLI/stdio/jobs access.
- `auth.library_creation` is optional: absent allows existing authenticated callers; configured empty users/groups permits operators only.
- `users` contains exact stable account IDs (including synthetic provider:subject OAuth IDs), never display names; `groups` contains exact mapped names including configured provider prefixes.
- Ordinary local/session/token callers use current stored account role and groups. Verified OAuth callers use the request's role/groups, reject identity mismatches, disabled accounts, and missing linked accounts. Unlinked verified identities remain supported.
- Configuration is operator-managed TOML/environment; no new UI or mutable REST configuration.

## Review Focus

- Verified token groups must override stale stored groups in both directions.
- Unknown/disabled ordinary users and missing linked OAuth accounts must fail closed.
- Explicit empty lists must differ from omitted configuration.
- Denials must create no library, credentials, job, or owner grant, and must precede Git access.
- REST addition, source apply, direct catalog creation share checks; MCP has no creation tool today, and existing stdio/local internal paths remain open.

### Task 1: Creation permission and enforcement

**Files:** Modify identity models/dtos/ports/driving/use_cases/module; bootstrap settings/container/bridges/open_access; catalog and ingestion ports/driven/use_cases/module; shared FakeAccess. Add features/library_creation.feature and steps/library_creation_steps.py; tests/identity/test_library_creation.py and tests/bootstrap/test_library_creation_api.py. Update docs/configuration.md.

**Interfaces:** `LibraryCreationPolicy(users: frozenset[str], groups: frozenset[str])`; `LibraryCreationQuery(account_id: str, external_identity: ExternalTokenIdentity | None)`; `CanCreateLibrary.__call__(query: LibraryCreationQuery) -> bool`; `AccessPolicy.can_create(library: str | None = None) -> bool` for catalog/ingestion. `IdentityModule.build(library_creation: LibraryCreationPolicy | None = None)` wires the use case. Settings `auth.library_creation.users/groups` default to empty sets when the optional section is supplied.

- [ ] Write behave scenarios for group-denied user and successful authorized group creator; run and record expected failure.
- [ ] Write parametrized identity tests for omitted/empty/user/group/admin/unknown/disabled and verified-principal mismatch, stale groups, missing linked account, unlinked stable ID; run to confirm failure.
- [x] Implement permission resolution, settings wiring and AccessPolicy checks before Git work and catalog writes; keep existing owner claim.
- [ ] Add REST session/API-token integration tests for denial/no side effects and allowed ownership, configured/omitted/admin/internal cases; verified OAuth tests exercise request identity through the bridge and catalog.
- [ ] Document exact TOML/environment configuration, IDs, mapped groups, compatibility default, operator and internal behavior.
- [ ] Run focused pytest/behave, ruff format/check, ty, full pytest and behave (PATH=/usr/bin:$PATH to select compatible Git). Confirm architecture and public MCP snapshot unchanged.
- [ ] Commit, request independent access review, push normally and open PR into develop; hand issue to review with actual verification summaries.


Implementation intake amendment: catalog's previous `get_library` availability probe required read
access before existence lookup and therefore treated absent IDs as occupied for ordinary users.
Added `IsLibraryIdTaken(GetLibraryQuery) -> bool`, guarded by `can_create(query.id)`, to query
availability without granting library read access. AddLibrary supplies the pure derived/explicit
ID to `can_create` before existence probing, Git or embedded context7 preview. This optional ID
also supports the separately scoped API credentials in #111. Standalone read-only previews are
unchanged. Sources apply is already operator-only over REST; its additions still use AddLibrary.

Ruling: Preserve the existing general CatalogLibraryIds adapter for repository checks and
credential access reads. A separate CatalogCreationIds uses the creation-authorized probe only
for AddLibrary, injected as optional creation_library_ids. Reusing the guarded probe everywhere
would wrongly deny readers without creation permission (regression reproduced as HTTP 403).
