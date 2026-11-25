# Backup and restore

!!! abstract "TL;DR"

    - `exactdocs backup` writes one archive of a SQLite instance while the server keeps serving.
    - `exactdocs restore` needs an empty data directory and the server stopped.
    - The secret key is not in the archive unless you pass `--include-secret-key`.
    - On PostgreSQL use `pg_dump`; on a libSQL server, its own backups.

This page is about the SQLite database. On PostgreSQL, use `pg_dump` (see
[PostgreSQL](postgresql.md)); on a libSQL server, its own backups. `exactdocs backup` refuses a
non-SQLite `EXACTDOCS_DATABASE_URL`.

`exactdocs backup` writes one archive of the instance while the server keeps serving. It holds:

- a consistent snapshot of the database, taken with SQLite's online backup API so writers are not
  stopped: libraries, versions, articles, images, settings, accounts and API tokens;
- DBOS's durable job steps (`jobs.sqlite`), so an import that was running resumes after a restore;
- `known_hosts`.

Run it where the server runs:

=== "Docker"

    ```bash
    docker exec exactdocs exactdocs backup - > exactdocs-$(date +%F).tar.gz   # or a path in the volume
    ```

=== "uvx"

    ```bash
    uvx exactdocs backup ~/exactdocs-backup.tar.gz
    ```

`exactdocs restore` puts an archive into a data directory that holds no instance yet (it refuses to
overwrite one), with the server stopped. It checks every file against the archive's checksums, then
migrates the schema: a backup from an older release is brought up to this version, and one from a
newer release is refused before anything is written. Then start the server as usual.

=== "Docker"

    ```bash
    docker run --rm -v exactdocs-data:/data -v "$PWD:/backup:ro" \
      ghcr.io/sircypkowskyy/exactdocs:latest restore /backup/exactdocs-2026-11-07.tar.gz
    ```

=== "uvx"

    ```bash
    uvx exactdocs restore ~/exactdocs-backup.tar.gz      # into EXACTDOCS_DATA_DIR
    ```

!!! warning "The secret key is not in the archive"
    Unless you pass `--include-secret-key`, the archive leaves the secret key out. Whoever holds the
    archive then cannot read the encrypted repository credentials in it, and the restored instance
    needs the original key to read them: set the same `EXACTDOCS_SECRET_KEY`, or copy the old
    `secret.key` into the new data directory (before or after the restore, but before `serve`).
    Without the key every library keeps serving its docs, and adding a version asks for its
    credential again (`credentials_required`).

    With `--include-secret-key` the archive opens those credentials by itself, so store it as
    carefully as the key.

Archives and restored files are created with mode `0600`; they also hold the password and token
hashes. Files a running server creates itself, such as `exactdocs.db`, are `0644` inside the `0700`
data directory, and a restored instance's are `0600`. Both keep other users out.

A backup stages its copies next to the archive (for `-`, in the data directory) before writing it,
so that file system needs room for about two copies of the database while it runs. A backup that
was killed leaves a `.exactdocs-backup-*` folder behind; the next backup removes those older than a
day. A restore checks each file's size against its manifest, and the free space (keeping 64 MiB to
spare), before it writes anything.
