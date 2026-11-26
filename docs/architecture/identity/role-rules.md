# Role rules

!!! abstract "TL;DR"

    - A `RoleRule` (#577) gives everyone with one membership at a provider an instance or library
      role. Rules come from the configuration file and from `identity_role_rules`.
    - Library roles and creation use them at every request; instance admin at sign-in and at every
      membership check.
    - A rule for every library leaves out private libraries, which ingestion reports to identity.

A `RoleRule` (#577) gives everyone with one membership at a provider a role. Its source is a
`group`, a `role` value, a `github_org` or a `github_team`; its grant `instance_admin`,
`create_libraries`, or a library role (`viewer`, `contributor`, `admin`; never `creator`) on every
library or on chosen ones.

- **Where rules come from.** `RoleRules.in_force` reads, in order: each provider's configured
  rules (`admin_groups` as `instance_admin` rules, then `[[rules]]`), `[auth.library_creation].groups`
  as `create_libraries` rules of any provider, and `identity_role_rules` (`RoleRuleRepository`).
  The configured ones are `configured`, so read-only.
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
