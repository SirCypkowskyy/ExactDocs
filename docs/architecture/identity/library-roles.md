# Library roles

!!! abstract "TL;DR"
    - Roles are `viewer < contributor < admin < creator`; the effective role is the highest held
      directly or through a group, and operators are `creator` of every library.
    - Viewers read, contributors import, admins configure and remove versions, the creator removes
      the library; a refusal is a 403 `forbidden`.
    - No caller means the instance's own work (command line, `serve --stdio`, jobs, webhooks), which
      no role limits.
    - Sharing needs `admin`, an `admin` grant needs `creator`, and `POST .../transfer` hands a
      library over.
    - Every role change is logged in the append-only `identity_access_events`; libraries that exist
      at the upgrade get no grant.

Docs belong to teams, not to whoever imported them (ACL-02, E12-05). `identity` owns the roles.
`catalog`, `ingestion` and `retrieval` ask it through an `AccessPolicy` driven port each, declared in
their own words and implemented once by `bootstrap/bridges.py:IdentityAccessPolicy` over identity's
`ResolveLibraryRoles`, `ClaimLibrary` and `DropLibraryGrants`.

## Roles

- `viewer < contributor < admin < creator` (`identity.models.LibraryRole`).
- A grant (`identity_library_grants`, one row per library, user-or-group and subject) gives a role
  to an account or to every member of a group. Groups are those of `identity_account_groups`, so
  only external accounts have any.
- An account's **effective role** is the highest it holds, directly or through a group.
- An operator (account role `admin`) is `creator` of every library, so a library nobody holds is
  still managed.
- A disabled account holds nothing.

## What each role may do

`Access.READ`, `CONTRIBUTE`, `ADMINISTER`, `OWN` of each domain:

| Role | May |
|---|---|
| `viewer` | search and read: search, read, outline, `query-docs`, articles, tags, renames, jobs,<br/>the schedule and retrieval settings |
| `contributor` | also import: add or reimport a version, sync, tag articles |
| `admin` | also configure: paths, tag rules, chunking, title and description, pinned default version,<br/>retrieval settings, schedule; and remove versions |
| `creator` | also remove the library |

- A refusal is a 403 `forbidden` (a tool error over MCP).
- Listings (`list_libraries`, `resolve-library-id`, `search_all_docs`, the latest jobs) hold only the
  libraries the caller holds a role on.
- Hiding a library entirely (answering like a missing one) is E12-08.

## Every use case a caller reaches checks

The check comes first, in:

- `catalog`: read, list, update, settings, pin, remove;
- `ingestion`: add version, sync, reimport, settings, tag, remove, schedule, jobs;
- `retrieval`: search, outline, read chunk, `query-docs`, retrieval settings.

Use cases that only other domains call (store a manifest, index it) do not check: they run for the
one that did. `tests/catalog/test_library_access.py` and `tests/bootstrap/test_library_roles_api.py`
hold the role × action matrix.

## Who is the caller for roles

- The caller is the account of the request. `bootstrap/caller.py` holds it in a context variable
  that the REST `protected` router binds (session or API token), and reads the MCP token otherwise.
- **No caller means the instance's own work**: the command line, `serve --stdio`, a scheduled check,
  a job, a push webhook. No role limits it, as the process owner already has the data directory.

!!! warning "Bind the caller"

    An entry point that proves who calls must bind them. Otherwise its requests run as the
    instance's own work.

## The creator

- Creating a library (`catalog.CreateLibrary`) records the caller as `creator` and drops any grant
  left on that ID.
- Removing or discarding a library drops its grants.
- A library created with no caller (the command line, the sources file applied by the CLI) has no
  creator: operators manage it and share it.

## Sharing

- `GET/PUT /libraries/{owner}/{repo}/grants` and `DELETE .../grants/{user|group}/{subject}`
  (identity's `GrantLibraryRole`, `RevokeLibraryRole`, `ListLibraryGrants`).
- They need `admin` on the library. Giving, changing or removing an `admin` needs `creator`. The
  creator's own role is neither given nor changed there.
- `POST .../transfer` (identity's `TransferLibrary`) is how a library changes hands:
    - only the `creator` (or an operator) may;
    - the new user becomes the creator and the creators before become admins;
    - all in one step of the grant repository (`transfer`, which answers who they were).

## The access log (ACL-05)

`identity_access_events` is append-only, behind the `AccessLog` driven port.

- `ClaimLibrary`, `GrantLibraryRole`, `RevokeLibraryRole`, `TransferLibrary` and
  `DropLibraryGrants` each record an `AccessEvent` (actor, change, subject, role, previous role,
  time) after their change.
- Every account or group whose role changed gets exactly one event. A transfer records:
    1. a `granted` event per creator before (`admin`, previous role `creator`);
    2. then one `ownership_transferred` event with the new creator as its subject (role `creator`,
       previous role whatever they held), so it reads first in the newest-first log.

    The new creator's grant is not also logged as `granted`.
- A grant of the role already held changes nothing and records nothing.

Reading it:

| Use case | Route | Who | Shows |
|---|---|---|---|
| `ListLibraryAccessLog` | `GET /libraries/{owner}/{repo}/access-log` | library admins | for a non-operator, only the events since the library's last removal[^reused] |
| `ListAccessLog` | `GET /access-log` | operators | every library's events, removed ones included |

[^reused]: ../So a library created again under an old ID does not reveal who had access to the one
    before.

- Both lists (#514) page in the database through `AccessLog.search`, a keyset over
  `(sort value, id)` (`at`, `library` or `change`; `AccessEvent.sort_value`).
- An `AccessLogFilter` also holds the actor (an account ID), the subjects (`(kind, subject)` pairs)
  and a time range.
- The use cases turn the request's `actor` and `subject`, which name people as the log shows them (a
  username, or the ID of an account that is gone), into account IDs (`Sharing.account_id_of`). A
  `subject` matches the user and the group of that name.
- Indexes on `(at, id)`, `(library, at, id)`, `(actor, at, id)` and `(subject, at, id)` serve the
  default newest-first order.

!!! note "Not in the same transaction"

    The event is written after the grant, not in the same transaction: a crash between the two
    loses that entry.

## Upgrading

Libraries that exist when the migration runs get no grant. Operators keep full access; other
accounts hold no role until an operator or the creator shares the library.
