# Role rules

!!! abstract "TL;DR"

    - A rule maps a provider's group, role value, GitHub organization or GitHub team to instance
      admin, library creation, or a library role on every library or on chosen ones.
    - Rules only add to what an account was given directly; the highest role counts.
    - "Every library" leaves out private libraries.

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
- `instance_admin` takes effect at the next sign-in or membership check (`revalidate_minutes`).
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
