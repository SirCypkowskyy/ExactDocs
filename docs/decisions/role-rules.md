# Role rules

!!! abstract "TL;DR"
    - A role rule gives everyone with one membership at a sign-in provider (a group, a role value,
      a GitHub organization or team) an instance role or a library role.
    - Library roles from rules are computed at every request. Instance admin is stored on the
      account and recomputed at sign-in and at each membership check.
    - A rule for every library leaves out private libraries, and a rule matches only accounts of
      its own provider.

| | |
|---|---|
| **Status** | Accepted, 2026-11-27 |
| **Scope** | Identity: `RoleRules`, library roles, creation and instance admin; see [Role rules](../architecture/identity/role-rules.md) and their [configuration](../configuration/sign-in/role-rules.md) |
| **Issue** | Refs #577 (rules in #627, REST in #628, UI in #629) |
| **Decided by** | Proposed in #627 |

## Context

Before #577, roles from a provider came only from `admin_groups` and
`[auth.library_creation].groups`. An operator who wanted everyone in a GitHub team to read every
library, or an Entra app role to make someone an admin, had to grant those roles library by
library or account by account. Those
two settings still apply: they show up as read-only rules, and a provider can be set to take its
rules only from the configuration file (`configured_rules_only`).

## Decision

**Private libraries are left out.** A rule for every library never reaches a private one.
Identity can't ask ingestion (the bridge runs from ingestion to identity), so ingestion tells
identity that a library is private before it stores the library's credential. A removed library
stays marked private until it is added again. Without that wiring, a rule for every library
reaches no library.

**Library roles are computed, not granted.** Library roles and creation come from the rules at
every request and are never written as grants. Removing a rule takes effect at once, and a rule
covers libraries created after it. Each access check costs one small extra query.

**Instance admin is stored.** It is kept on the account and recomputed at sign-in, at each
membership check and whenever an admin rule changes. Computing it on every request was rejected,
because every operator check would then go through the rules.

**Role values have their own table.** Role-claim values go to `identity_account_roles`. A prefix
on group names could collide with a real group, and that group would then satisfy a role rule.

**Rules match only their provider's accounts.** A rule matches only accounts created through its
own provider. The exception is the read-only rules from `[library_creation].groups`, which match
on any provider.

**GitHub is checked softly.** An organization or team named only in a rule gives no group when
the app is restricted there or GitHub doesn't answer, and it never blocks a sign-in. Each named
organization or team costs one extra GitHub API call per check.

**Last admin.** The check that an instance keeps at least one admin runs before the change, not in
the same transaction, so a concurrent disable can race it.

**Access log.** Rule events have an empty library, so they show only in the operators' log.
