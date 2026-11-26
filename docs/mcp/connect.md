# Connect a client

!!! abstract "TL;DR"
    - `uvx exactdocs config --client <client>` prints the snippet to paste; it refers to
      `EXACTDOCS_TOKEN` unless you pass `--show-token`, and `--new-token` makes a token for that
      client alone (90 days).
    - MCP over HTTP needs an `exd_` API token, which acts as the account that created it, or OAuth
      for web hosts, chosen with `EXACTDOCS_MCP_OAUTH_PROVIDER`.
    - OAuth callers pass the provider's `allowed_groups`, `allow_any_user` and `admin_groups` checks
      at every call; for OIDC a person who leaves a group keeps access until the ID token expires.
    - Behind Cloudflare Access a client sends only the Access service-token headers and acts as the
      account mapped in `service_tokens`.
    - stdio (`exactdocs serve --stdio`) needs no token or server, opens an existing database
      read-only, and must run the same release as the same user as the server.

The quickest way is to let ExactDocs print the configuration for your client:

=== "Claude Code"

    ```bash
    uvx exactdocs config --client claude
    ```

=== "Claude Desktop"

    ```bash
    uvx exactdocs config --client claude-desktop
    ```

=== "Cursor"

    ```bash
    uvx exactdocs config --client cursor
    ```

=== "VS Code"

    ```bash
    uvx exactdocs config --client vscode
    ```

=== "Codex"

    ```bash
    uvx exactdocs config --client codex
    uvx exactdocs config --client codex --stdio     # local, read-only, no token
    ```

The agent usage skill comes from another command:

```bash
uvx exactdocs skill                             # prints the agent usage skill; redirect it to a SKILL.md
                                                # (also the MCP resource skill://exactdocs/SKILL.md)
```

`config` prints a snippet to paste into the client's configuration file.

- The snippet never holds your token: it refers to `EXACTDOCS_TOKEN` (VS Code asks for it
  instead) unless you pass `--show-token`.
- Claude Desktop reaches HTTP servers through `mcp-remote`, pinned to `0.16.0`. Replace the
  `<your-exactdocs-token>` placeholder there with your token.
- Desktop apps often lack `~/.local/bin` on their `PATH`. Put the absolute paths from
  `which uvx` or `which npx` in `command`.
- `--show-token` puts your real token in the snippet, so never commit the file it goes into;
  the command warns about this on stderr.

!!! tip "Prefer `--new-token`"
    It creates a token just for this client (asking for your password, like `token create`), so
    revoking it breaks nothing else.

    - The token is named `mcp-<client>`; `--name` changes that.
    - It expires after 90 days; `--expires-in` changes that.
    - The command prints its id on stderr, for `exactdocs token revoke <id>`.

## Over HTTP

```json
{
  "mcpServers": {
    "exactdocs": {
      "url": "http://localhost:3000/mcp",
      "headers": { "Authorization": "Bearer <your-token>" }
    }
  }
}
```

MCP over HTTP needs an API token, or [OAuth](#oauth-for-web-hosts) for hosts that cannot paste
one. The token acts as the account that created it.

- Tokens start with `exd_`.
- They are shown once when created and stored only as a hash.
- They may expire, and stop working the moment they are revoked.
- Create, list and revoke them on the **Account** page of the web UI, with `exactdocs token`, or
  over the REST API with a signed-in session.
- The token routes do not accept a token, so a leaked token cannot mint successors.

<figure class="xd-shot" markdown>

![The Account page on its API tokens tab: one token for every library the account can read, with the start of the token; below it, the MCP client config to paste, with the server's /mcp URL and a placeholder where the token goes.](../assets/screenshots/connect-light.webp#only-light){ loading=lazy }
![The Account page on its API tokens tab: one token for every library the account can read, with the start of the token; below it, the MCP client config to paste, with the server's /mcp URL and a placeholder where the token goes.](../assets/screenshots/connect-dark.webp#only-dark){ loading=lazy }

<figcaption>The <strong>Account</strong> page: the tokens, and the config for this server with a
placeholder for the token.</figcaption>

</figure>

??? example "Manage tokens over REST"

    ```bash
    curl -c jar.txt -H 'content-type: application/json' http://localhost:3000/api/v1/session \
      -d '{"username": "ada", "password": "a long passphrase"}'
    curl -b jar.txt -H 'content-type: application/json' http://localhost:3000/api/v1/tokens \
      -d '{"name": "laptop", "expires_at": "2027-01-01T00:00:00Z"}'    # `expires_at` is optional
    curl -b jar.txt http://localhost:3000/api/v1/tokens                  # list (never the secrets)
    curl -b jar.txt -X DELETE http://localhost:3000/api/v1/tokens/<id>   # revoke
    ```

REST clients and scripts send the same token as `Authorization: Bearer exd_...` to any `/api/v1`
route except the token routes themselves.

## OAuth for web hosts

Web hosts such as Claude and ChatGPT cannot paste an API token, so they connect with OAuth. Choose
one of your [sign-in providers](../getting-started/accounts.md#sign-in-through-an-identity-provider)
for them (an MCP client discovers a single authorization server):

```bash
EXACTDOCS_MCP_OAUTH_PROVIDER=corp
```

The host then:

1. finds the OAuth metadata at `/.well-known/oauth-authorization-server` and
   `/.well-known/oauth-protected-resource/mcp` on the server's root;
2. registers itself;
3. shows the person a consent page on your server;
4. sends them to the provider.

API tokens keep working next to it, so the CLI and coding agents are unaffected.

### Register a second redirect URI

At the provider, add `<EXACTDOCS_PUBLIC_URL>/auth/callback` to the client's redirect URIs, next to
the one for the web sign-in. The provider needs a client secret (the proxy derives its token
signing key from it).

### Same membership checks

The provider's `allowed_groups`, `allow_any_user` and `admin_groups` apply, and a disabled account
is refused. The check runs at every call, not only at sign-in. For OIDC it reads the ID token the
server holds for the host, so what it sees depends on the change:

- A person who signs in to the web UI as well acts as that account. **Disabling the account gives
  a `401` at the next call**, with the same token.
- A person who **leaves a group at the provider** keeps access until the ID token expires (usually
  about an hour), because the token itself does not change. Then:
    - the host gets a `401` and renews with its refresh token;
    - the provider's current groups apply, so a person outside the allowed groups gets no working
      token.

Who the caller is, and which grants apply:

- Anyone who never signed in to the web UI acts as `<provider>:<subject>`, and no account is
  created.
- Library group grants use the verified provider groups with the provider's `group_prefix`,
  including for these OAuth-only callers.
- Members of `admin_groups` can manage every library.
- A linked caller can also use grants to their account.
- The request's verified groups and role are used without changing stored web-account memberships
  or refresh tokens.

### What the host sees when the ID token expires

A `401` with the usual `WWW-Authenticate` header.

- A host that keeps its refresh token trades it for a new token and carries on.
- One that does not sends the person through the sign-in again.

### OIDC groups must be in the ID token

The check reads the provider's ID token (always a JWT), not userinfo. Make sure the `groups_claim`
is in it:

| Provider | How |
|---|---|
| ADFS | an issuance transform rule for `group` |
| Entra ID | the groups optional claim |

### OAuth2 and GitHub use opaque access tokens

| Provider type | What each MCP request checks | Proxy |
|---|---|---|
| `oauth2` | current userinfo | FastMCP `OAuthProxy` with the configured endpoints |
| `github` | the current user, with the organization/team checks of browser sign-in[^gh-checks] | FastMCP `OAuthProxy` with the configured endpoints |
| OIDC / ADFS | the ID token (above) | `OIDCProxy` |

[^gh-checks]: ../The same organization/team checks and app-approval/SSO refusals as browser sign-in.

- Lost membership is refused at the next MCP request.
- The presets follow their protocol:
    - `discord` is OAuth2;
    - `google` and `microsoft` are OIDC (a multi-tenant Microsoft provider checks each token
      against its own tenant's issuer).
- A provider that creates no accounts (`auto_create_users = false`, the presets' default) refuses a
  person whose identity no account has linked. A linked identity acts as its account, with the
  account's own role and groups.
- GitHub `base_url`/`api_url` support GitHub.com, Enterprise Server and `*.ghe.com`, as in
  [GitHub setup](../configuration/sign-in/providers.md#github-and-github-enterprise-sign-in).
- GitHub OAuth Apps accept one callback URL. Use a separate OAuth App/provider for MCP with
  `/auth/callback` as its callback, and choose that provider with `EXACTDOCS_MCP_OAUTH_PROVIDER`.

### Hosts, origins and stored state

- The `Host` and `Origin` allowlist (`EXACTDOCS_ALLOWED_HOSTS`, `EXACTDOCS_ALLOWED_ORIGINS`)
  applies to the OAuth routes too.
- The proxy keeps its registrations and tokens, encrypted, in `<data dir>/mcp-oauth`.
- Changing the client secret makes hosts sign in again, and the state kept under the old secret is
  deleted at the next start.

## Behind Cloudflare Access

When ExactDocs runs [behind Cloudflare Access](../deployment/reverse-proxy.md#behind-cloudflare-access) with
[`[auth.cloudflare_access]`](../configuration/sign-in/cloudflare-access.md) configured, an MCP client needs
no ExactDocs token. It sends only the Access service-token headers:

1. Access checks them and adds its signed token to the request.
2. ExactDocs runs the call as the account the service token's client ID is mapped to in
   `service_tokens`, with that account's library roles.

```json
{
  "mcpServers": {
    "exactdocs": {
      "url": "https://docs.acme.com/mcp",
      "headers": {
        "CF-Access-Client-Id": "<client id>.access",
        "CF-Access-Client-Secret": "<client secret>"
      }
    }
  }
}
```

- A client that also sends `Authorization: Bearer exd_...` acts as that token's account instead.
  A wrong token is refused, never replaced by the Access identity.
- A service token that is not mapped, or whose account is missing or disabled, gets a `401`.

## Without a network port: stdio

```json
{
  "mcpServers": {
    "exactdocs": { "command": "uvx", "args": ["exactdocs", "serve", "--stdio"] }
  }
}
```

stdio needs no token and no running server, but it does need an existing database. Run
`exactdocs serve` (or `exactdocs admin create`) once first; otherwise it exits with an error on
stderr naming the path it expected.

- It uses the same data directory (`EXACTDOCS_DATA_DIR`).
- It opens the SQLite file read-only (`mode=ro` and `query_only`), which is safe next to a running
  server that keeps importing.
- It runs no worker, no identity and no migration, and it exposes the same read-only tools. Manage
  libraries through the server.
- `--host`, `--port` and `--reload` only apply to HTTP and are rejected with `--stdio`.

!!! note "One write: AI spend"
    When an LLM step or a paid reranker runs in a stdio process, its spend is added to the shared
    `retrieval_ai_spend` ledger (with its replay tokens), so the server's budgets and
    `GET /api/v1/ai/usage` count it. That write goes through a second connection of its own.

    - On SQLite it opens the existing file with `mode=rw` under an authorizer that refuses every
      write to any other table, every schema change and every `PRAGMA` but a few reads.
    - On PostgreSQL it is the same role without `default_transaction_read_only`, used by the spend
      ledger alone.

    If that write fails (a read-only file system, a lock held too long), the process logs a warning
    and keeps the spend in memory until it exits; the AI call never fails because of it. While the
    server holds the SQLite write lock, a stdio call that spent can wait up to 5 s for it before
    falling back to memory.

!!! warning "Same release, same user"
    - Keep stdio and the server on the same release: if the server has been
      upgraded and has migrated the database, upgrade the stdio command too.
    - Run stdio as the same user as the server. With the server stopped, SQLite
      creates `exactdocs.db-wal` and `-shm` next to the database (the directory must be writable
      for that), and files owned by another user can stop the server from starting later.
    - The same goes for every other command, since all of them except
      `serve --stdio` migrate:
        - the first one creates `exactdocs.db-migration.lock` next to the database (mode 0600);
        - processes that start together take turns on that lock to migrate;
        - a server that cannot open it stops with an error naming it.
