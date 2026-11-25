# Declare and sync libraries

!!! abstract "TL;DR"
    - List libraries in an `exactdocs.sources.yaml` so changes to the set of imported docs go
      through code review. `sources plan` shows the changes, `sources apply` makes them, and nothing
      is removed without `--prune`.
    - A tag version stays at its commit. A branch version is as fresh as its last sync: by hand, on
      a schedule (auto-sync) or on push (a webhook).
    - A webhook needs an `admin` session to turn on. Its secret is shown once, and the job checks
      the branch tip itself instead of trusting the payload.
    - Add the webhook's host name to `EXACTDOCS_ALLOWED_HOSTS` and rate-limit the route in your
      reverse proxy before exposing it.

## Declare libraries in a file

Instead of adding libraries one by one, you can list them in an `exactdocs.sources.yaml` and keep
it in a repository, so that changes to the set of imported docs go through code review. The same
file can rebuild a second instance, such as staging or a fresh volume after a restore.

```yaml
version: 1
libraries:
  - url: https://github.com/acme/payments
    refs: [main, v1.4.0]
    include_paths: [docs/]
    auto_sync: {tag_pattern: "v*", keep_last: 3}
```

- `exactdocs sources plan` shows what would change and writes nothing: the libraries it would
  create or update, the ones that already match and the ones the file does not declare.
- `exactdocs sources apply` makes those changes, one library at a time, and removes nothing
  unless you add `--prune`.
- Settings that an entry leaves out are not managed, so you can still tune them in the UI.
- Only admins may plan or apply, with a session or an API token, which suits a CI job.

!!! note "No credentials in the file"
    The file holds no credentials. Add a private library in the UI with its token or key first,
    then manage it with the file.

[Sources file](../sources.md) has every field, the JSON Schema for editor completion, and what plan
and apply compare.

## Keep branch versions fresh

A tag version stays at the commit it was imported from (a moved tag is only re-imported when you
confirm it, see [Exit codes](cli.md#exit-codes)). A branch version is as fresh as its last sync,
which happens in one of three ways:

- by hand: the **Sync** button or `exactdocs sync`;
- on a schedule: a library's auto-sync (`PUT /api/v1/libraries/{owner}/{repo}/auto-sync`)
  imports new matching tags, prunes old automatic versions and re-syncs branches on its own
  interval;
- on push: the forge calls a webhook.

### Sync on push (webhooks)

1. Turn on the library's webhook. This needs an `admin` signed in with a session; an API token is
   refused.

    ```bash
    curl -X PUT -b "exactdocs_session=..." http://localhost:3000/api/v1/libraries/acme/docs/webhook
    # {"library": "/acme/docs", "enabled": true, "url": "http://localhost:3000/api/v1/webhooks/acme/docs",
    #  "created_at": "...", "secret": "kN0..."}
    ```

    - The `secret` (32 random bytes, URL-safe) is shown once, in this answer.
    - `GET .../webhook` only says whether the webhook is on, its URL and when it was made.
    - `PUT` again rotates the secret, and the old one stops working at once.
    - `DELETE` turns the webhook off, and removing the library removes it.
    - The `url` is built from the address the request came to, so behind a reverse proxy, use the
      public one.

2. Add a webhook on the forge, with that URL and secret, for push events:

    === "GitHub"

        Also GitHub Enterprise. Signature: `X-Hub-Signature-256`.

        - *Settings → Webhooks → Add webhook*
        - Payload URL: the `url`
        - Content type: `application/json`
        - Secret: the `secret`
        - *Just the push event*

    === "GitLab"

        Signature: token in `X-Gitlab-Token`.

        - *Settings → Webhooks → Add new webhook*
        - URL: the `url`
        - Secret token: the `secret`
        - Triggers: *Push events* and *Tag push events*

    === "Bitbucket Cloud"

        Signature: `X-Hub-Signature: sha256=...`.

        - *Repository settings → Webhooks → Add webhook*
        - URL: the `url`
        - Secret: the `secret`
        - Trigger: *Repository push*

    === "Bitbucket Data Center"

        Signature: `X-Hub-Signature: sha256=...`.

        - *Repository settings → Webhooks → Create webhook*
        - The same URL and secret
        - Event: *Repository: Push*

    Gitea and Forgejo send GitHub-compatible headers but are not tested.

#### What a push does

- A push to a branch that is a version of the library queues a sync of that branch only, as
  `POST .../sync` would.
    - The job asks the repository for the branch's tip itself, with the library's stored
      credential; it never trusts a commit from the payload.
    - A deleted branch is recorded as `ref_deleted` on its version.
- A pushed tag that matches the library's auto-sync `tag_pattern` runs the tag part of the
  scheduled check (new `auto` versions, old ones pruned) without moving the schedule.
- Anything else, such as an untracked branch, a tag without auto-import or a ping, answers 202
  `ignored`.

#### How the request is answered

- The request itself does no git work. It answers 202 (`queued`, `duplicate` or `ignored`) after a
  few database reads and writes.
- The sync runs as a `push` job, within a second when the library has no other job running.
- A burst of pushes to one branch queues one job, and a redelivered webhook (same delivery ID,
  remembered for 7 days) answers `duplicate`.
- Every refusal gets the same 401 `invalid_signature`: no signature, a wrong one, a SHA-1
  signature, an unknown forge, a library without a webhook, no such library.
- A body above 5 MiB gets 413.

!!! warning "Before you expose the webhook"
    The host name in the webhook URL, the one the forge calls, must be in
    `EXACTDOCS_ALLOWED_HOSTS`, or every delivery gets a 400 `Invalid host header` before it reaches
    the webhook. ExactDocs does not rate-limit this route: if it is reachable from the internet, put
    a per-address limit on it in your reverse proxy.
