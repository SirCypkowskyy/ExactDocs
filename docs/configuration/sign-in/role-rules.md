# Role rules

!!! abstract "TL;DR"

    - A rule maps a provider's group, role value, GitHub organization or GitHub team to instance
      admin, library creation, or a library role on every library or on chosen ones.
    - Rules only add to what an account was given directly; the highest role counts.
    - "Every library" leaves out private libraries.
    - Operators add and remove rules from the Users page or over [REST](../../rest-api/users-and-access.md#role-rules);
      rules of the configuration file show there read-only.

A role rule gives everyone with one membership at a provider a role in ExactDocs. It pairs a
**source** with a **grant**:

| Source | Matches |
|---|---|
| `group` | members of a group of the groups claim, named as the provider sends it (without `group_prefix`) |
| `role` | holders of a value of the provider's `role_claim` |
| `github_org` | active members of a GitHub organization (GitHub providers only) |
| `github_team` | active members of a GitHub team, `org/team-slug` (GitHub providers only) |

| Grant | Gives |
|---|---|
| `instance_admin` | the account role `admin`, decided at every sign-in and membership check, like `admin_groups` |
| `create_libraries` | creating libraries where [`[auth.library_creation]`](index.md#who-may-create-libraries) restricts it |
| `viewer`, `contributor`, `admin` | that role on every library that is not private, or only on `libraries` |

```toml
[auth.providers.entra]
kind = "microsoft"
tenant = "00000000-0000-0000-0000-000000000000"
client_id = "your-client-id"
role_claim = "roles"
configured_rules_only = true

[[auth.providers.entra.rules]]
role = "ExactDocs.Admin"
grant = "instance_admin"

[[auth.providers.entra.rules]]
role = "ExactDocs.Reader"
grant = "viewer"

[[auth.providers.entra.rules]]
group = "docs-writers"
grant = "contributor"
libraries = ["/acme/handbook"]
```

Operators also add and remove rules from the Users page (or `POST` and `DELETE /role-rules`),
for any provider without `configured_rules_only`. Every such change goes to the access log with
who made it. A change to an `instance_admin` rule that would leave no enabled admin is refused;
as for disabling an account, an admin counts while the account is enabled.

How rules combine with everything else:

- A rule only adds. An account's access is the highest of what it was given directly (the Users
  page, a library's access page) and what its rules give; removing a rule never takes away a role
  given directly.
- A rule matches only accounts created through its provider. A group never matches a `role`
  rule, and a role value never matches a `group` rule or a library shared with a group.
- Library roles from rules are worked out at every request: a library created after the rule is
  covered at once.
- "Every library" leaves out private libraries (imported with a token or a deploy key). A rule
  reaches a private library only by naming it in `libraries`, so it stays its creator's to share.
- `instance_admin` follows a person's memberships at the next sign-in or membership check
  (`revalidate_minutes`). Adding or removing such a rule applies at once to the accounts the
  provider created, from their memberships at their latest check. A GitHub organization or team
  becomes a stored group only once a rule names it, so a new rule naming one reaches its members
  at their next sign-in or membership check.
- `admin_groups` and `[auth.library_creation].groups` keep working unchanged; they count as rules
  of the configuration file.
- On GitHub, every organization and team a rule names is checked like `allowed_teams` (active
  membership, restricted organizations), and the active ones become groups `github:<org>` and
  `github:<org>/<team>`. Who signs in stays with `allowed_orgs` and `allowed_teams` (and with
  `allowed_groups`, which can name these groups too). An organization or team that only a rule
  names never refuses a sign-in: when it restricts the app, or GitHub cannot say, it just gives
  no group. Organizations and teams named in no rule and no filter are not stored. Each one a
  rule names costs one more GitHub API call at every sign-in and membership check.
- A rule of the configuration file that could match nobody (a malformed GitHub name, a library ID
  that is not `/owner/repo`, `libraries` on an instance grant) stops the server at start.
