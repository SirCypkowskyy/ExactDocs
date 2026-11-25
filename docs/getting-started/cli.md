# Use the command line

!!! abstract "TL;DR"
    - Most of the CLI is a client of the REST API and works against any instance you can reach.
      `serve`, `reindex`, `backup`, `restore`, `ai`, `models`, `admin` and `user` open the database
      directly and run where the server runs.
    - `exactdocs login` stores the server URL and a 90-day API token in `config.json` (mode 0600).
      `logout` only forgets them locally; revoke the token in the web UI.
    - Repository credentials and every `token` command need your password, not an API token.
    - `library` and `docs` mirror context7's `ctx7`. Exit codes and sync error codes are stable, so
      scripts can rely on them.

Apart from `serve`, `reindex`, `backup`, `restore`, `ai`, `models` and the `admin` and `user`
commands, which open the database directly and run where the server runs, the CLI is a client of
the REST API. It works against any instance you can reach.

## Sign in

```bash
uvx exactdocs login https://docs.example.com    # asks for username and password
echo "$TOKEN" | uvx exactdocs login https://docs.example.com --token-stdin   # reuse an API token
EXACTDOCS_TOKEN=exd_... uvx exactdocs login https://docs.example.com         # same, from the env
uvx exactdocs logout                            # forget the stored credentials
```

What `login` does:

- It creates an API token named after your machine.
- It stores the server URL and the token in `config.json` in your user config directory, with mode
  0600. The token is never printed, and `EXACTDOCS_CLIENT_CONFIG` names another file.
- The new token expires after 90 days. Change that with `--expires-in DAYS`, or pass `--no-expiry`
  for a token that lives until you revoke it in the web UI.

!!! warning "Keep tokens out of your shell history"
    Prefer `--token-stdin` or `EXACTDOCS_TOKEN` to `--token`, which ends up in your shell history
    and in `ps`. `logout` only forgets the credentials on your machine: the token stays valid on the
    server until you revoke it on the web UI's **Account** page.

Where the CLI finds the server and token, in this order:

1. flags
2. `EXACTDOCS_URL` and `EXACTDOCS_TOKEN`
3. that file

- A stored token is only sent to the server it came from.
- Plain `http://` is accepted for loopback (`localhost`, `127.0.0.1`, `::1`) only; anything else
  needs `https://`.
- Proxy variables (`HTTPS_PROXY`, `NO_PROXY` and the like, or their `EXACTDOCS_` overrides) and a
  CA bundle are honoured for remote servers and ignored for loopback. The proxy sees where you
  connect but not your HTTPS traffic
  ([Outbound connections](../configuration/outbound.md)).

## Manage libraries and tokens

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

### `--wait`

- `--wait` only watches. It follows an import for `--wait-timeout` seconds (600 by default) and
  retries a poll that hiccups.
- If it times out, loses track of the job or you press Ctrl-C (exit 130), it says so and the job
  keeps running on the server.

### `add --dry-run`

- It sends the URL, `--ref`, `--path`, `--exclude` and any credential to
  `POST /repositories/preview`.
- It prints the files the import would take, how many there are and, past 1000, `truncated`.
  Nothing is stored.
- `--id` and `--wait` have no effect. `--tag-rule` is only checked, so a malformed rule fails the
  dry run just as it would fail `add`.
- File sizes are not shown, since knowing them would mean downloading every file.
- A server already running as many previews as it allows answers "try again" (exit 1).

### Commands that need your password

Setting a private repository's credential (`--git-token-file`, `--ssh-key`) and every `token`
command need your password, not an API token.

- The REST API only lets a signed-in session do these things, so a leaked token can neither mint
  itself a successor nor replace a repository credential.
- The CLI signs in for that one command and signs out again (`--username`, `--password-stdin`), and
  ignores `--token` for it.
- A token or key is read from a file of at most 64 KB, never from the command line, and a file that
  others can read gets a warning.
- Because the CLI's own `--token` is the API token, the repository token is `--git-token-file`.

## See what an agent would get

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
  the `search_all_docs` MCP tool or `GET /api/v1/search` ([REST API](../rest-api/search.md#search-across-libraries)).

## Exit codes

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
