# Security and the secret key

!!! abstract "TL;DR"

    - Behind a reverse proxy or on a LAN address, set `EXACTDOCS_ALLOWED_HOSTS`, or the server answers only to localhost.
    - A sign-in provider needs `EXACTDOCS_PUBLIC_URL`.
    - The secret key is generated into `<data dir>/secret.key` unless you set one. On PostgreSQL, set the same key in every process.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_SECRET_KEY` | generated into `<data dir>/secret.key` (mode 0600) on first run | Encrypts the stored tokens and deploy keys of private repositories (Fernet).<br/>See [The secret key](#the-secret-key) |
| `EXACTDOCS_SECRET_KEY_PREVIOUS` | unset | The old key during a rotation |
| `EXACTDOCS_ALLOWED_HOSTS` | unset | Host names besides localhost that the server answers to, comma-separated (for example `docs.example.com,*.corp.example`).<br/>Needed behind a reverse proxy or on a LAN address |
| `EXACTDOCS_ALLOWED_ORIGINS` | unset | Browser origins allowed to make state-changing requests, comma-separated |
| `EXACTDOCS_SECURE_COOKIES` | `false` | The session cookie is always `Secure` over HTTPS, and whenever `EXACTDOCS_PUBLIC_URL` is `https://`.<br/>Set `true` when TLS ends at a proxy that does not forward `X-Forwarded-Proto` from a trusted address and no public URL is set |
| `EXACTDOCS_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Proxies whose `X-Forwarded-*` headers are trusted, for the scheme and for the client address the sign-in throttle counts.<br/>See [Behind a reverse proxy](../deployment/reverse-proxy.md) |
| `EXACTDOCS_PUBLIC_URL` | unset | The URL people reach the server at, without a path (`https://docs.example.com`).<br/>Required once a sign-in provider is configured: the redirect URI to register at the provider is `<public_url>/api/v1/auth/<name>/callback`, never built from a request's `Host` |

## The secret key

`EXACTDOCS_SECRET_KEY` encrypts the stored tokens and deploy keys of private repositories and the
refresh tokens of identity providers, and keys the HMACs of the agentic answer cache. Unset, ExactDocs generates one into `<data dir>/secret.key`
(mode 0600) on first run.

It must be random and at least 32 characters:

```bash
openssl rand -base64 32
```

It is stretched with HKDF, not with a password hash, so a passphrase is not safe. Without the key
the stored credentials cannot be read: libraries keep serving their docs and ask for the token
again (`credentials_required`), and accounts of an identity provider lose access at their next
check until they sign in again.

On PostgreSQL, set it explicitly and use the same value in every process. Otherwise each process
generates its own key and cannot open the credentials another one stored.

To change the key without losing the stored credentials, see [Rotating the secret key](advanced.md#rotating-the-secret-key).

Backups and the secret key are covered in [Backup and restore](../deployment/backup.md).
