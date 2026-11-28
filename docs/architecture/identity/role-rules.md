# Role rules

!!! abstract "TL;DR"

    - A `RoleRule` (#577) gives everyone with one membership at a provider an instance or library
      role. Rules come from the configuration file and from `identity_role_rules`.
    - Library roles and creation use them at every request; instance admin at sign-in and at every
      membership check.
    - A rule for every library leaves out private libraries, which ingestion reports to identity.

Why rules work this way, and what else was weighed: [the role rules decision](../../decisions/role-rules.md).

A `RoleRule` (#577) gives everyone with one membership at a provider a role. Its source is a
`group`, a `role` value, a `github_org` or a `github_team`; its grant `instance_admin`,
`create_libraries`, or a library role (`viewer`, `contributor`, `admin`; never `creator`) on every
library or on chosen ones.

- **Where rules come from.** `RoleRules.in_force` reads, in order: each provider's configured
  rules (`admin_groups` as `instance_admin` rules, then `[[rules]]`), `[auth.library_creation].groups`
  as `create_libraries` rules of any provider, `[auth].default_library_role` as the one
  `everyone` rule (`RoleRules.default_role`), and `identity_role_rules` (`RoleRuleRepository`).
  The configured ones are `configured`, so read-only.
- **The default role.** `default_library_role_rule` builds a rule of source `everyone`, no
  provider and grant `viewer` on every library; `RoleRule` refuses any other `everyone` rule
  (stored, of a provider, on chosen libraries, or another grant). It matches every account, local
  ones too (`RoleRules.matching` skips local accounts only while it is unset), so it goes through
  the same path as the other rules: private libraries left out, disabled accounts and unknown
  callers get nothing (`_caller_memberships`), never creation or instance admin.
- **Matching.** `RoleRule.matches` compares the account's `Memberships`: its origin's provider,
  its stored groups and its stored role values. A rule matches only accounts of its provider, while
  that provider is configured; a stored rule not at all while the provider has
  `configured_rules_only`. Group values get the provider's `group_prefix`; GitHub values compare
  without case, and only for a GitHub provider. OAuth (MCP) callers are matched by their token's
  `ExternalTokenIdentity` (provider, groups and roles), as for group grants.
- **When they apply.**
    - Library roles: at every request, in `_library_roles` (`ResolveLibraryRoles`, sharing): the
      highest of direct grants, group grants and matching rules.
    - Creation: at every request, in `CanCreateLibrary`, beside `[auth.library_creation]`.
      `IdentityAccessPolicy.can_create` is unchanged.
    - Instance admin: at sign-in and revalidation (`_policy_role`), stored as the account's role.
- **Private libraries.** A rule for every library leaves out private ones
  (`identity_private_libraries`, the `PrivateLibraries` port). Ingestion tells identity
  (`AccessPolicy.set_private`, bridged to `MarkLibraryPrivate`) before it stores a token or deploy
  key, so the library is never reachable meanwhile. A removed library stays marked (fail closed)
  until ingestion adds that ID again.
  The migration copies the libraries that already hold a credential. Without the port, a rule for
  every library reaches no library (fails closed).
- **GitHub.** `GithubProvider.watched` reads the organizations and teams the rules name at every
  check. Their active memberships (organizations checked like the filters, restricted ones counted
  as none) become `github:<org>` and `github:<org>/<team>`; admission stays with `allowed_orgs` and
  `allowed_teams`.
- **Managing rules.** `ListRoleRules`, `AddRoleRule` and `RemoveRoleRule` (`/role-rules`, operators
  with a session) share `RuleAdmin`. A stored rule needs a configured provider without
  `configured_rules_only`, a source the provider can have (GitHub names for GitHub, role values
  with `role_claim`) and no duplicate (checked in the repository's write turn).
- **Instance roles at once.** Adding or removing an `instance_admin` rule sets the role of every
  account its provider created from `memberships_by_account` (`set_roles`; a local account's role
  never changes), for the changed rule's provider only. A change that would leave no enabled admin
  is refused (`LastOperatorError`); adding one can demote too, when a role went stale after a
  configuration change.
  The check runs before the removal, not in its transaction: a sign-in or disable in between can
  still race it.
- **Provenance.** `UserSummary.rules` lists the rules that match each account, and a library's
  grants list carries the rules that reach the library (`RoleRules.reaching`).
- **Access log.** `rule_added` and `rule_removed` events (`AccessEvent.rule`, stored as JSON in
  `identity_access_events.rule`) have the actor and the rule as it was, and an empty library.

