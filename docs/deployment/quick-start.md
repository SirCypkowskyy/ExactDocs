# Quick start

!!! abstract "TL;DR"

    - The image runs as UID 10001 and needs only `/data` and `/tmp` to be writable.
    - The Compose file below is the hardened setup CI runs.

## A single container

This hardened setup works today, and CI runs the image this way. The image runs as UID 10001 and
needs nothing but `/data` and `/tmp` to be writable.

```yaml
# docker-compose.yml
services:
  exactdocs:
    image: ghcr.io/sircypkowskyy/exactdocs:latest
    ports: ["3000:3000"]
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { cpus: "2", memory: 1g }
    volumes: ["exactdocs-data:/data"]
volumes:
  exactdocs-data:
```

## Other ways to start

=== "docker run"

    ```bash
    docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data \
      ghcr.io/sircypkowskyy/exactdocs:latest
    ```

=== "uvx"

    ```bash
    uvx exactdocs serve
    ```

    `uvx exactdocs serve` needs `git` on your `PATH`. For models, use
    `uvx --from 'exactdocs[ai]' exactdocs serve` or `uvx --from 'exactdocs[ai,local]' exactdocs serve`
    (see [Image variants](index.md#image-variants)).

Then open <http://localhost:3000>. [Getting started](../getting-started.md) creates the first admin
and adds the first library. For production, put the server
[behind a reverse proxy](reverse-proxy.md) and add
[health checks](health-checks.md) and [backups](backup.md).
