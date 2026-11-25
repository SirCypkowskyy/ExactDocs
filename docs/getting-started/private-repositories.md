# Private repositories

!!! abstract "TL;DR"
    - A private repository needs an access token (with an https address) or a deploy key without a
      passphrase (with an ssh address).
    - Credentials are stored encrypted with `EXACTDOCS_SECRET_KEY`, never returned by the API, never
      logged, and only ever sent to the repository's own host.
    - Sending a credential needs a signed-in session; an API token is refused with 401.
    - Back up with `exactdocs backup`, or keep the secret key outside the data volume: a copy of the
      whole volume holds both the key and the database.

## In the web UI

On the add-library form, tick **This repository is private** and give either:

- an access token, for an https address. Optionally give the user name the host expects
  (`x-token-auth` for Bitbucket).
- a deploy key without a passphrase, for an ssh address. Paste it or choose the key file.

How the form handles it:

- The check, the branch and tag list (`POST /repositories/refs`), the preview and the add all send
  it in the request body.
- The form keeps it in memory only and drops it once the library is added.
- For an ssh address the check shows the server's host-key fingerprint: compare it with the one
  your git host publishes before you add the library.

On a library's settings page, **Add a version** of a private library takes a replacement token or
key. Use it when the stored one can no longer be read (`credentials_required`, after the secret key
changed) or was refused.

## Over REST

Send the credential next to the URL in `POST /api/v1/repositories/check`,
`POST /api/v1/libraries` or `POST /api/v1/libraries/{owner}/{repo}/versions`:

```json
{"url": "https://github.com/acme/docs", "credential": {"kind": "token", "token": "ghp_..."}}
{"url": "git@github.com:acme/docs.git", "credential": {"kind": "ssh_key", "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n..."}}
```

## How credentials are handled

- Which credential goes with which URL:
    - A token goes with an `https://` URL (`http://` only for localhost).
    - `username` defaults to `x-access-token`, which GitHub and GitLab accept; Bitbucket repository
      tokens use `x-token-auth`.
    - A deploy key, a private key without a passphrase, goes with an SSH URL.
- How it is stored and used:
    - Credentials are stored encrypted with `EXACTDOCS_SECRET_KEY`, never returned by the API and
      never written to logs or error messages.
    - They reach git through `GIT_ASKPASS` (a token) or a temporary key file named in
      `GIT_SSH_COMMAND` (a key, deleted after each git call), never in the URL or on the command
      line.
    - They are used only for the repository's own host: a redirect to another host fails.
- SSH host keys live in `<data dir>/known_hosts`.
    - GitHub, GitLab and Bitbucket are pinned to their published keys; any other host is trusted on
      first use and remembered.
    - A host whose key changed is refused with `host_key_changed` until you remove its line from
      that file.
    - `POST /api/v1/repositories/check` returns the `host_key_fingerprint` to compare with the one
      the host publishes.
- Where a credential applies:
    - A credential is stored for the library and for the host it was given for. It is never offered
      to another host.
    - A library added again never inherits an earlier one, and removing a library deletes it.
    - Sending a `credential` needs a signed-in session; an API token, such as an MCP client's, is
      refused with 401 for these requests.
- If the secret key is lost or changed, the library's docs stay available and adding a version answers
  `credentials_required`. Send the credential again with the new version request.

!!! warning "Backups and the secret key"
    The generated key file and the database live in the same data volume, so a backup of the whole
    volume holds both and defeats the encryption.

    - Use `exactdocs backup`, which leaves `secret.key` out unless asked (see
      [Backup and restore](../deployment.md#backup-and-restore)), or keep `EXACTDOCS_SECRET_KEY`
      outside the volume.
    - A key file that others could read is made private again but logged as exposed: rotate it.
    - A symlink, or a file owned by another user, is refused.

## How ExactDocs runs git

ExactDocs reads repositories with the system `git` binary.

- The Docker image includes it. With `uvx` it must be on `PATH`, and `exactdocs serve` refuses to
  start without it.
- Only where that check is skipped, as with `--stdio` (which never imports), is a missing git just
  a warning, and repository checks then answer `git_not_installed`.
- Git 2.30 or newer is recommended; a server without partial-clone support just sends more data.

URLs and fetching:

- URLs may be `https://`, `http://`, `ssh://`, `user@host:path` or `file://`.
- Credentials never go in the URL: such a URL is refused and never echoed or logged.
- `POST /api/v1/repositories/check` runs git with prompts, the user's git config and ssh keys
  switched off, and a 15 s timeout.
- An import fetches only the pinned commit (no history, no unselected files) into a temporary
  folder under the data directory (`work/`), with hooks, submodules and symlinks off.
