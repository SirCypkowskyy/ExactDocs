# Getting started

This page takes you from nothing to an agent that answers from your own docs: start the server,
create the first account, import a library and connect an MCP client. It ends with the command
line, private repositories, declaring libraries in a file, keeping branch versions fresh, adding
more accounts and signing in through an identity provider.

## Start the server

=== "Docker"

    ```bash
    docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data \
      ghcr.io/sircypkowskyy/exactdocs:latest
    ```

=== "uvx"

    ```bash
    uvx exactdocs serve
    ```

Then open <http://localhost:3000>.

`uvx exactdocs serve` needs `git` on your `PATH` and refuses to start without it, because imports
run `git`. `uv` fetches Python 3.14 if it is missing. SQLite 3.35 or newer is required; uv's Python
and the Docker image both have it, and ExactDocs refuses to start on an older one. An agent that
only reads an existing database can use `uvx exactdocs serve --stdio`, which needs neither `git`
nor a port (see [stdio](mcp.md#without-a-network-port-stdio)).

The image comes in three variants. All of them run plain BM25 search until you configure a model;
[Deployment](deployment.md#image-variants) explains which one to pick.

## Create the first admin

A fresh instance does nothing but offer its setup: until the first admin account exists, every
`/api/v1` request is refused with `403 setup_required`. Create the admin on the setup page at
<http://localhost:3000>, or from the command line, or over the API:

```bash
docker exec -it exactdocs exactdocs admin create   # prompts for username and password
# or, without Docker
uvx exactdocs admin create
# or, over the API (the password must be 12 to 1024 characters)
curl -X POST http://localhost:3000/api/v1/setup -H 'content-type: application/json' \
  -d '{"username": "ada", "password": "a long passphrase"}'
```

`admin create` opens the database directly, so it works before the server is up and against the
same data directory. For scripts, `--password-stdin` reads the password from stdin. Passwords are
stored as argon2id hashes, and at most 4 are checked at once.

## Add your first library

In the web UI, choose **Add library** and give a git URL, a ref (tag, branch or commit) and the
paths to import. **Preview** shows the files that match as a folder tree with counts, what the
repository's `context7.json` says (its paths fill the empty path boxes, which you can still edit)
and its `previousVersions` as checkboxes. The tags you tick are imported after the library is
added.

The import runs as a background job; the UI shows its progress, the files it skipped and any
problems. ExactDocs splits every article at its headings. A branch version is re-synced on demand
and only the files that changed are chunked again.

A `context7.json` at the repository root pre-fills the library. Added without paths, the library
takes its folders and exclusions; its title and description win over the README's; and its rules
come first in every `query-docs` answer. The [REST API](rest-api.md) page has the details.

## From `docker run` to a searchable library, over REST

CI runs this flow on every change ([`deploy/smoke.sh`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/deploy/smoke.sh),
`sh` and `curl` only, against a fixture repository). It takes well under five minutes and needs
no model and no API key. The example imports [encode/httpx](https://github.com/encode/httpx) at
tag `0.28.1`, so the machine needs outbound access to GitHub.[^ci]

```bash
docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data ghcr.io/sircypkowskyy/exactdocs:latest
H='content-type: application/json'; U=http://localhost:3000
curl -X POST $U/api/v1/setup -H "$H" -d '{"username":"ada","password":"a long passphrase"}'    # 1. admin
curl -c jar.txt $U/api/v1/session -H "$H" -d '{"username":"ada","password":"a long passphrase"}' # 2. sign in
curl -b jar.txt $U/api/v1/tokens -H "$H" -d '{"name":"laptop"}'                                  # 3. token (shown once)
curl -b jar.txt $U/api/v1/libraries -H "$H" \
  -d '{"url":"https://github.com/encode/httpx","ref":"0.28.1","include_paths":["docs/"]}'         # 4. add; returns job_id
curl -b jar.txt $U/api/v1/jobs/<job_id>                                                          # 5. until "succeeded"
TOKEN=<token from step 3>; A="authorization: Bearer $TOKEN"   # reads below use the token, as an agent would
curl -H "$A" "$U/api/v1/libraries/encode/httpx/articles?ref=0.28.1"                              # 6. list ...
curl -H "$A" -G "$U/api/v1/libraries/encode/httpx/article" -d ref=0.28.1 -d path=docs/index.md   # ... and read
curl -H "$A" -G "$U/api/v1/libraries/encode/httpx/search" -d ref=0.28.1 -d q=timeout             # 7. search
```

Step 8: point your agent at `http://localhost:3000/mcp` with the token, as described in
[MCP](mcp.md), and call `query-docs` with `libraryId` `/encode/httpx/0.28.1`.

[^ci]: CI itself needs no network for this: it imports a fixture repository served locally.

## Connect an agent

```bash
uvx exactdocs config --client claude            # claude, claude-desktop, cursor, vscode, codex
uvx exactdocs config --client codex --stdio     # local, read-only, no token
```

`config` prints a snippet to paste into the client's configuration. [MCP](mcp.md) covers the
snippet, tokens, stdio and every tool.

## Use the command line

Apart from `serve`, `reindex`, `backup`, `restore`, `ai`, `models` and the `admin` and `user`
commands, which open the database directly and run where the server runs, the CLI is a client of
the REST API. It works against any instance you can reach.

### Sign in

```bash
uvx exactdocs login https://docs.example.com    # asks for username and password
echo "$TOKEN" | uvx exactdocs login https://docs.example.com --token-stdin   # reuse an API token
EXACTDOCS_TOKEN=exd_... uvx exactdocs login https://docs.example.com         # same, from the env
uvx exactdocs logout                            # forget the stored credentials
```

`login` creates an API token named after your machine and stores the server URL and the token in
`config.json` in your user config directory, with mode 0600. The token is never printed, and
`EXACTDOCS_CLIENT_CONFIG` names another file. The new token expires after 90 days; change that
with `--expires-in DAYS`, or pass `--no-expiry` for a token that lives until you revoke it in the
web UI. Prefer `--token-stdin` or `EXACTDOCS_TOKEN` to `--token`, which ends up in your shell
history and in `ps`. `logout` only forgets the credentials on your machine: the token stays valid
on the server until you revoke it on the web UI's **Account** page.

The CLI looks for the server and token in this order: flags, then `EXACTDOCS_URL` and
`EXACTDOCS_TOKEN`, then that file. A stored token is only sent to the server it came from. Plain
`http://` is accepted for loopback (`localhost`, `127.0.0.1`, `::1`) only; anything else needs
`https://`. Proxy variables (`HTTPS_PROXY`, `NO_PROXY` and the like, or their `EXACTDOCS_`
overrides) and a CA bundle are honoured for remote servers, where the proxy sees where you connect
but not your HTTPS traffic, and ignored for loopback
([Outbound connections](configuration.md#outbound-connections)).

### Manage libraries and tokens

Every command takes `--url` and `--token` and, for scripts, `--json`. The progress of `--wait`
goes to stderr.

```bash
uvx exactdocs add https://github.com/acme/docs --ref v1.4.0 --path docs/ --exclude docs/archive/ --wait
uvx exactdocs add https://github.com/acme/docs --id /acme/docs --tag-rule 'docs/api/**=api'
uvx exactdocs add https://github.com/acme/docs --ref v1.4.0 --path 'docs/**' --dry-run  # lists the files, stores nothing
uvx exactdocs libraries --json
uvx exactdocs version add /acme/docs v1.5.0 --wait
uvx exactdocs sync /acme/docs --wait             # re-syncs the branch versions, checks the tags
uvx exactdocs sync /acme/docs --confirm --wait   # also re-imports every tag that moved upstream
uvx exactdocs sync /acme/docs --confirm-tag v1.4.0  # ... or only the moved tags named
uvx exactdocs remove /acme/docs/v1.4.0           # asks first; --yes skips the question
uvx exactdocs remove /acme/docs --yes
uvx exactdocs add git@github.com:acme/private.git --ssh-key ./deploy_key
uvx exactdocs token create ci --expires-in 30    # asks for your password
uvx exactdocs token list
uvx exactdocs token revoke 0198f2c1
uvx exactdocs sources plan exactdocs.sources.yaml   # what a declared set of libraries would change
uvx exactdocs sources apply exactdocs.sources.yaml --prune  # apply it; --prune removes the rest
```

`--wait` only watches. It follows an import for `--wait-timeout` seconds (600 by default) and
retries a poll that hiccups. If it times out, loses track of the job or you press Ctrl-C (exit
130), it says so and the job keeps running on the server.

`add --dry-run` sends the URL, `--ref`, `--path`, `--exclude` and any credential to
`POST /repositories/preview` and prints the files the import would take, how many there are and,
past 1000, `truncated`. Nothing is stored. `--id` and `--wait` have no effect, and `--tag-rule` is
only checked, so a malformed rule fails the dry run just as it would fail `add`. File sizes are not
shown, since knowing them would mean downloading every file. A server already running as many
previews as it allows answers "try again" (exit 1).

Setting a private repository's credential (`--git-token-file`, `--ssh-key`) and every `token`
command need your password, not an API token. The REST API only lets a signed-in session do
these things, so a leaked token can neither mint itself a successor nor replace a repository
credential. The CLI signs in for that one command and signs out again (`--username`,
`--password-stdin`), and ignores `--token` for it. A token or key is read from a file of at most
64 KB, never from the command line, and a file that others can read gets a warning. Because the
CLI's own `--token` is the API token, the repository token is `--git-token-file`.

### See what an agent would get

`library` and `docs` take the commands and flags of context7's `ctx7`
(`library <name> [query]`, `docs <libraryId> <query> [--language L] [--json]`):

```bash
uvx exactdocs library acme "retry policy"
uvx exactdocs docs /acme/docs "retry policy"
uvx exactdocs docs /acme/docs@v1.4.0 "retry policy" --language go --json
```

They differ from `ctx7` in a few ways:

- The output starts with the untrusted-content notice. With `library --json`, the notice goes to
  stderr so that stdout stays the plain list.
- Control characters are stripped.
- Failures go to stderr with the exit codes below; `ctx7` prints them to stdout and always exits 1.
- The query may be given as several words.
- A library lists its default version, articles and chunks, with no stars or trust score.
- There is no `ctx7 search` command yet. To search every library at once, use the web UI's search,
  the `search_all_docs` MCP tool or `GET /api/v1/search` ([REST API](rest-api.md)).

### Exit codes

| Code | Meaning |
|---|---|
| 0 | done |
| 1 | other failure |
| 2 | usage error or rejected input, including `remove` without a terminal and without `--yes` |
| 3 | not found |
| 4 | conflict: an import is running, or the ID is taken |
| 5 | not signed in, or refused |
| 6 | an import or a sync failed, or `--wait` lost track of it |
| 130 | interrupted |

A failed sync says why with a stable code, and every version keeps serving what it had. The same
codes are on the jobs, as `error_code`:

| Code | What happened |
|---|---|
| `repo_unreachable` | the repository was deleted, made private or is down |
| `auth_failed` | the token or key was refused |
| `ref_deleted` | the branch or tag is gone |
| `tag_moved` | the tag points to another commit now |

A sync never re-imports a moved tag on its own. `--confirm` (every moved tag) or
`--confirm-tag REF` re-imports it at the new commit and prints each tag's old and new commit.

## Private repositories

In the web UI, tick **This repository is private** on the add-library form and give either an
access token (https address; optionally the user name the host expects, `x-token-auth` for
Bitbucket) or a deploy key without a passphrase (ssh address; paste it or choose the key file).
The check, the branch and tag list (`POST /repositories/refs`), the preview and the add all send
it in the request body. The form keeps it in memory only and drops it once the library is added.
For an ssh address the check shows the server's host-key fingerprint: compare it with the one your
git host publishes before you add the library.

On a library's settings page, **Add a version** of a private library takes a replacement token or
key. Use it when the stored one can no longer be read (`credentials_required`, after the secret
key changed) or was refused.

Over REST, send the credential next to the URL in `POST /api/v1/repositories/check`,
`POST /api/v1/libraries` or `POST /api/v1/libraries/{owner}/{repo}/versions`:

```json
{"url": "https://github.com/acme/docs", "credential": {"kind": "token", "token": "ghp_..."}}
{"url": "git@github.com:acme/docs.git", "credential": {"kind": "ssh_key", "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n..."}}
```

- A token goes with an `https://` URL (`http://` only for localhost). `username` defaults to
  `x-access-token`, which GitHub and GitLab accept; Bitbucket repository tokens use
  `x-token-auth`. A deploy key, a private key without a passphrase, goes with an SSH URL.
- Credentials are stored encrypted with `EXACTDOCS_SECRET_KEY`, never returned by the API and
  never written to logs or error messages. They reach git through `GIT_ASKPASS` (a token) or a
  temporary key file named in `GIT_SSH_COMMAND` (a key, deleted after each git call), never in the
  URL or on the command line, and only for the repository's own host: a redirect to another host
  fails.
- SSH host keys live in `<data dir>/known_hosts`. GitHub, GitLab and Bitbucket are pinned to
  their published keys; any other host is trusted on first use and remembered. A host whose key
  changed is refused with `host_key_changed` until you remove its line from that file.
  `POST /api/v1/repositories/check` returns the `host_key_fingerprint` to compare with the one the
  host publishes.
- A credential is stored for the library and for the host it was given for. It is never offered
  to another host, a library added again never inherits an earlier one, and removing a library
  deletes it. Sending a `credential` needs a signed-in session; an API token, such as an MCP
  client's, is refused with 401 for these requests.
- The generated key file and the database live in the same data volume, so a backup of the whole
  volume holds both and defeats the encryption. Use `exactdocs backup`, which leaves `secret.key`
  out unless asked (see [Backup and restore](deployment.md#backup-and-restore)), or keep
  `EXACTDOCS_SECRET_KEY` outside the volume. A key file that others could read is made private
  again but logged as exposed: rotate it. A symlink, or a file owned by another user, is refused.
- If the secret key is lost or changed, the library's docs stay available and adding a version
  answers `credentials_required`. Send the credential again with the new version request.

### How ExactDocs runs git

ExactDocs reads repositories with the system `git` binary, which the Docker image includes; with
`uvx` it must be on `PATH`, and `exactdocs serve` refuses to start without it. Only where that
check is skipped, as with `--stdio` (which never imports), is a missing git just a warning, and
repository checks then answer `git_not_installed`.

URLs may be `https://`, `http://`, `ssh://`, `user@host:path` or `file://`. Credentials never go
in the URL: such a URL is refused and never echoed or logged. `POST /api/v1/repositories/check`
runs git with prompts, the user's git config and ssh keys switched off, and a 15 s timeout. An
import fetches only the pinned commit (no history, no unselected files) into a temporary folder
under the data directory (`work/`), with hooks, submodules and symlinks off. Git 2.30 or newer is
recommended; a server without partial-clone support just sends more data.

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

`exactdocs sources plan` shows what would change and writes nothing: the libraries it would
create or update, the ones that already match and the ones the file does not declare.
`exactdocs sources apply` makes those changes, one library at a time, and removes nothing unless
you add `--prune`. Settings that an entry leaves out are not managed, so you can still tune them
in the UI. Only admins may plan or apply, with a session or an API token, which suits a CI job.

The file holds no credentials. Add a private library in the UI with its token or key first, then
manage it with the file. [Sources file](sources.md) has every field, the JSON Schema for editor
completion, and what plan and apply compare.

## Keep branch versions fresh

A tag version stays at the commit it was imported from (a moved tag is only re-imported when you
confirm it, as above). A branch version is as fresh as its last sync, which happens in one of three
ways:

- by hand: the **Sync** button or `exactdocs sync`;
- on a schedule: a library's auto-sync (`PUT /api/v1/libraries/{owner}/{repo}/auto-sync`) imports
  new matching tags, prunes old automatic versions and re-syncs branches on its own interval;
- on push: the forge calls a webhook.

### Sync on push (webhooks)

1. Turn on the library's webhook. This needs an `admin` signed in with a session; an API token is
   refused.

    ```bash
    curl -X PUT -b "exactdocs_session=..." http://localhost:3000/api/v1/libraries/acme/docs/webhook
    # {"library": "/acme/docs", "enabled": true, "url": "http://localhost:3000/api/v1/webhooks/acme/docs",
    #  "created_at": "...", "secret": "kN0..."}
    ```

    The `secret` (32 random bytes, URL-safe) is shown once, in this answer. `GET .../webhook` only
    says whether the webhook is on, its URL and when it was made. `PUT` again rotates the secret,
    and the old one stops working at once; `DELETE` turns the webhook off, and removing the library
    removes it. The `url` is built from the address the request came to, so behind a reverse proxy,
    use the public one.

2. Add a webhook on the forge, with that URL and secret, for push events:

    | Forge | Where | Fields | Signature |
    |---|---|---|---|
    | GitHub, GitHub Enterprise | *Settings → Webhooks → Add webhook* | Payload URL: the `url`; Content type: `application/json`; Secret: the `secret`; *Just the push event* | `X-Hub-Signature-256` |
    | GitLab | *Settings → Webhooks → Add new webhook* | URL: the `url`; Secret token: the `secret`; triggers *Push events* and *Tag push events* | token in `X-Gitlab-Token` |
    | Bitbucket Cloud | *Repository settings → Webhooks → Add webhook* | URL: the `url`; Secret: the `secret`; trigger *Repository push* | `X-Hub-Signature: sha256=...` |
    | Bitbucket Data Center | *Repository settings → Webhooks → Create webhook* | the same URL and secret; event *Repository: Push* | `X-Hub-Signature: sha256=...` |

    Gitea and Forgejo send GitHub-compatible headers but are not tested.

A push to a branch that is a version of the library queues a sync of that branch only, as
`POST .../sync` would. The job asks the repository for the branch's tip itself, with the
library's stored credential; it never trusts a commit from the payload. A deleted branch is
recorded as `ref_deleted` on its version. A pushed tag that matches the library's auto-sync
`tag_pattern` runs the tag part of the scheduled check (new `auto` versions, old ones pruned)
without moving the schedule. Anything else, such as an untracked branch, a tag without
auto-import or a ping, answers 202 `ignored`.

The request itself does no git work. It answers 202 (`queued`, `duplicate` or `ignored`) after a
few database reads and writes, and the sync runs as a `push` job, within a second when the library
has no other job running. A burst of pushes to one branch queues one job, and a redelivered webhook
(same delivery ID, remembered for 7 days) answers `duplicate`.

Every refusal (no signature, a wrong one, a SHA-1 signature, an unknown forge, a library without a
webhook, no such library) gets the same 401 `invalid_signature`. A body above 5 MiB gets 413.

!!! warning "Before you expose the webhook"
    The host name in the webhook URL, the one the forge calls, must be in
    `EXACTDOCS_ALLOWED_HOSTS`, or every delivery gets a 400 `Invalid host header` before it reaches
    the webhook. ExactDocs does not rate-limit this route: if it is reachable from the internet, put
    a per-address limit on it in your reverse proxy.

## Accounts and sign-in

### Sessions and lost passwords

The web UI signs in with `POST /api/v1/session`. The session is an HttpOnly, SameSite=Lax cookie
that ends after 7 days without use or after 30 days at most, and it only works on `/api`, never on
`/mcp`.

Lost the admin password? Run `exactdocs admin reset-password` on the machine (same options as
`admin create`). It sets a new password, signs the admin out everywhere and revokes the API
tokens.

Password sign-in always stays available, also when you add an
[identity provider](#sign-in-through-an-identity-provider). The setup creates the first admin as a
local account, so it works as a break-glass account even while every provider is down.

### Failed sign-ins are throttled

The throttle covers the web UI's sign-in and `exactdocs login` alike. Every attempt counts against
its client address (for IPv6, its /64) and its username at once, before the password is checked,
so a burst of concurrent guesses gets no more tries than guesses sent one by one. After 5 failed
attempts, each further one must wait, 5 seconds at first and doubling up to 15 minutes, and is
answered 429 `rate_limited` with a `Retry-After` header in the meantime. A right password gives
back its own attempt (without restarting the address's wait) and clears its username's count.

An address that has signed into a username in the last 30 days is held only to its own count, not
to the username's. Others failing for the admin's username therefore cannot lock the admin out of
a machine they already use; a new address still waits. `admin reset-password` forgets every
address remembered for the username, so one that signed in with the old password is held to the
username's count again.

Behind a reverse proxy, list the proxy in `EXACTDOCS_FORWARDED_ALLOW_IPS` so that the throttle
counts the client's address rather than the proxy's ([Deployment](deployment.md#behind-a-reverse-proxy)).

Where the counts live depends on the database:

| | SQLite | PostgreSQL |
|---|---|---|
| Counts and remembered addresses | in the server's memory | in the database (`identity_failed_sign_ins`, `identity_known_sign_ins`), shared by every process |
| A restart | clears them; nothing else does | keeps them |
| `admin reset-password` | runs in another process and cannot clear them | drops the username's count and its remembered addresses on every process |
| Old counts | gone at restart | each dropped once an hour has passed without a failure |

If the database is too busy to count an attempt within 5 seconds, the attempt is refused (429).

If sign-ins are throttled while you reset a password (429), or the old password may have leaked:

- On SQLite, restart the server. That clears the throttle and the addresses it remembers.
  Otherwise an address that signed in with the old password is not held to the username's count.
- On PostgreSQL, the reset also clears the username's count and forgets every address remembered
  for it, so the new password works at once on every process and every address is held to the
  username's count again (other addresses' and other usernames' counts stay). If the command warns
  that the sign-in throttle was busy or failed, the password has still changed: run the command
  again, which is safe, or wait out the `Retry-After`.

### Local user accounts

The setup creates the first admin. After that, an operator (any account with role `admin`) adds
more local accounts. There is no sign-up page or route, so nobody creates their own account.

```bash
exactdocs user create bob                      # prompts for the password (or --password-stdin)
exactdocs user create carol --operator         # an admin, who also manages accounts
exactdocs user disable bob                     # signs bob out everywhere and revokes his API tokens
exactdocs user enable bob                      # lets him sign in again (with the same password)
exactdocs user reset-password bob              # new password; his sessions end, his tokens are revoked
```

Like `admin create`, these open the database directly (in Docker,
`docker exec -it exactdocs exactdocs user create bob`). An admin can do the same on the **Users**
page of the web UI (`/users`; the API is `/api/v1/users`, see [REST API](rest-api.md)), which
other accounts neither see nor reach (403).

- A disabled account cannot sign in; it gets the same answer as a wrong password. Its sessions and
  tokens are refused at once. The last enabled admin cannot be disabled.
- Enabling an account ends any session or token stored while it was disabled, so nothing that raced
  the disable comes back.
- The Users page offers no reset of your own password, since it would sign you out. Anyone with a
  local account changes their own password under **Account settings** instead (the current one
  first, checked like a sign-in and throttled the same way; `PUT /api/v1/account/password`): their
  other sessions end, this one stays, and their API tokens keep working. A lost password still
  needs `exactdocs user reset-password <you>` or another admin. A reset also clears the username's
  sign-in throttle, as `admin reset-password` does.
- The Users page also lists the accounts made by a first sign-in through an identity provider,
  with their provider and groups.

### Sign in through an identity provider

People can sign in with the identity they already have, through any OpenID Connect provider
(Keycloak, Entra ID, Okta, Google, ADFS 2016+). Access follows the provider: someone who leaves an
allowed group loses access to ExactDocs without anyone touching it. Configure the provider in the
TOML file that `EXACTDOCS_CONFIG_FILE` names, and set the public URL:

```toml
# exactdocs.toml (EXACTDOCS_CONFIG_FILE); the client secret never goes in this file
public_url = "https://docs.example.com"

[auth.providers.corp]            # the name: lower-case letters, digits, hyphens
kind = "oidc"
display_name = "Corp SSO"        # the button says "Sign in with Corp SSO"
issuer = "https://idp.example.com/realms/corp"   # exactly as discovery's `issuer`
client_id = "exactdocs"
# client_secret: EXACTDOCS_AUTH__PROVIDERS__CORP__CLIENT_SECRET, or client_secret_file = "/run/secrets/corp"
allowed_groups = ["docs-readers"]   # or allow_any_user = true; one of the two is required
admin_groups = ["exactdocs-admins"] # role admin while in one of them, else user
# groups_claim = "groups"           # a dotted path: Keycloak "realm_access.roles", ADFS "group"
```

At the provider, register `https://docs.example.com/api/v1/auth/corp/callback` as the client's
redirect URI. The client can be confidential (with a secret) or public (without one). The sign-in
page then shows a **Sign in with Corp SSO** button next to the password form. You can configure
several providers at once. [Configuration](configuration.md#sign-in-providers) lists every field,
and [Deployment](deployment.md#behind-a-reverse-proxy) explains the public URL behind a proxy.

The flow is the authorization code flow with PKCE (`S256`), `state` and `nonce`. ExactDocs reads
the provider's discovery document from the issuer's `/.well-known/openid-configuration` on the
first sign-in and caches it for an hour; its `issuer` must equal the configured one exactly. The ID
token must be signed by a key from the provider's JWKS with an asymmetric algorithm the provider
advertises (never `none` or `HS*`), and carry the configured issuer, the client ID in `aud` (and in
`azp` when it is present or `aud` names several audiences), the attempt's `nonce`, and times that
are valid within 60 s of leeway. A new signing key is fetched when a token first names it, at most
once a minute. The issuer must be HTTPS. [REST API](rest-api.md) and
[Architecture](architecture.md#external-sign-in-oidc) describe the sign-in routes and the stored
data.

**Accounts.** The first allowed sign-in creates an account with the role `user`, or `admin` through
`admin_groups`. The account is linked to the identity by its issuer and subject only, never by
email or username, so a sign-in can never take over an existing account. It is named after the
provider's username (or the local part of the email). When another account already has that name,
local or from another provider, it is named `<username>@<provider>` instead, and when that is taken
too, the sign-in is refused with `username_unavailable` until an operator frees a name. A rename at
the provider does not rename the account.

An account from a provider has no password. Password sign-in and `exactdocs login` treat it as
unknown, and a password reset is refused with `external_account`. Its owner creates API tokens on
the **Account** page in the web UI.

**Groups and role.** The groups are read at every sign-in and every revalidation, and they decide
the role: someone who leaves the admin group is demoted at once, even if they were the last admin.
Only members of `allowed_groups` get in, unless `allow_any_user = true` admits everyone the
provider vouches for.

**Revalidation.** ExactDocs asks for `offline_access` and keeps the refresh token, encrypted with
the [secret key](configuration.md#the-secret-key). Every `revalidate_minutes` (60 by default) it
asks the provider again:

- still allowed: the groups and role are refreshed;
- a lost group or a revoked refresh token: the account's sessions end and its API tokens are
  refused until its next allowed sign-in;
- the provider cannot be reached: access continues for at most `revalidate_grace_minutes` (a day
  by default), then ends.

A provider that issues no refresh token limits each session to `revalidate_grace_minutes` after
sign-in. Disabling an account deletes its refresh token, and a disabled account stays disabled
whatever the provider says. Signing out ends the ExactDocs session only, so the session at the
provider may sign you straight back in.

??? note "ADFS and Entra ID"
    **ADFS** (2016+) is an `oidc` provider with the issuer `https://<adfs host>/adfs`. Create an
    application group with a server application (client ID and secret) and the redirect URI above,
    and enable refresh tokens. Set `username_claim = "upn"` (or `unique_name`) and
    `groups_claim = "group"`, and add an issuance transform rule on the web API that sends the
    groups, for example *Send LDAP Attributes as Claims* from Active Directory, mapping
    `Token-Groups - Unqualified Names` to the outgoing claim type `group`.

    **Entra ID** puts at most 200 groups in a token. Beyond that, filter the groups sent to the app
    on the Entra side, or use app roles with `groups_claim = "roles"`.

Two more kinds of provider sit next to `oidc`: `oauth2`, for a provider without OpenID Connect,
and `github`, for GitHub or GitHub Enterprise with organization and team checks.
[OAuth2-only sign-in](configuration.md#oauth2-only-sign-in) and
[GitHub and GitHub Enterprise sign-in](configuration.md#github-and-github-enterprise-sign-in)
list their fields.

### Library roles and sharing

Each library has four roles, granted to users and to identity-provider groups:

| Role | Can |
|---|---|
| viewer | see the library in the UI and in MCP |
| contributor | also edit it: tags, paths, chunking, versions, re-sync |
| admin | also delete it and manage access |
| creator | the single owner (whoever created it): also remove admins and transfer ownership |

A library you add makes you its creator. Share it from its **Share** button (the library's
*Sharing* page) or with `PUT /api/v1/libraries/{owner}/{repo}/grants`. Only the creator gives or
removes `admin` and hands the library over to another user (*Transfer ownership*), who becomes its
creator while you stay an admin. Operators (admins) hold every library and manage the accounts.
Libraries that existed before roles have no creator, so other accounts see them only once an
operator shares them. The AI providers and instance settings stay open to every signed-in account.

Every grant, revocation, ownership transfer and removal is recorded. A library's admins read its
access log from its *Sharing* page or the Sharing section of its settings, and operators read every
library's on the *Access log* page (`/access-log`).

Every signed-in account may add libraries unless an operator limits that to chosen users or groups
([Who may create libraries](configuration.md#who-may-create-libraries)). API tokens and MCP clients
act as their user, so an agent sees exactly the libraries its user may view. A token can also be
narrowed to chosen libraries: `--library` on `exactdocs token create`, or `library_ids` in the
[REST API](rest-api.md). [Architecture](architecture.md#library-roles) explains how the roles are
checked.
