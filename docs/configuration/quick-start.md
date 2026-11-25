# Quick start

!!! abstract "TL;DR"

    - With no settings at all, ExactDocs serves on port 3000 with SQLite and BM25.
    - Most instances set only a handful of settings: the hosts, the public URL, the secret key, and maybe the database and a search mode.
    - One example per install method is below; [Detailed setup](detailed-setup.md) walks through a production setup.

## The settings most instances set

| Setting | Default | Set it when |
|---|---|---|
| `EXACTDOCS_ALLOWED_HOSTS` | unset: localhost only | People reach the server by another name: behind a reverse proxy, or on a LAN address |
| `EXACTDOCS_PUBLIC_URL` | unset | A sign-in provider is configured (then it is required) |
| `EXACTDOCS_FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | A reverse proxy runs on another address: list only the proxy |
| `EXACTDOCS_SECRET_KEY` | generated into `<data dir>/secret.key` | You keep the key outside the data volume, or run on PostgreSQL (the same key in every process) |
| `EXACTDOCS_DATA_DIR` | `/data` in the image, else the user-data directory | You want the data somewhere else |
| `EXACTDOCS_DATABASE_URL` | `exactdocs.db` in the data directory | The database is PostgreSQL or a libSQL server |
| `EXACTDOCS_CONFIG_FILE` | unset | You configure sign-in providers, model profiles or index backends in a TOML file |
| `EXACTDOCS_AI__MODE` | unset (`auto`, BM25 today) | Searches should use a model, such as `hybrid` |

Every one of them is described in full on its reference page: [Storage and database](storage.md),
[Security and the secret key](security.md) and [Search and AI settings](ai.md).

Make a secret key with:

```bash
openssl rand -base64 32
```

## One example per install method

An instance at `https://docs.example.com`, behind a reverse proxy at `172.30.0.2`:

=== "Docker Compose"

    ```yaml
    services:
      exactdocs:
        image: ghcr.io/sircypkowskyy/exactdocs:latest
        environment:
          EXACTDOCS_ALLOWED_HOSTS: "docs.example.com"
          EXACTDOCS_PUBLIC_URL: "https://docs.example.com"
          EXACTDOCS_FORWARDED_ALLOW_IPS: "172.30.0.2"
          EXACTDOCS_SECRET_KEY: ${EXACTDOCS_SECRET_KEY}
        volumes: ["exactdocs-data:/data"]
    volumes:
      exactdocs-data:
    ```

=== "docker run"

    ```bash
    docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data \
      -e EXACTDOCS_ALLOWED_HOSTS=docs.example.com \
      -e EXACTDOCS_PUBLIC_URL=https://docs.example.com \
      -e EXACTDOCS_FORWARDED_ALLOW_IPS=172.30.0.2 \
      -e EXACTDOCS_SECRET_KEY \
      ghcr.io/sircypkowskyy/exactdocs:latest
    ```

=== "uvx with a .env file"

    ```bash
    # .env in the working directory; the environment wins over it
    EXACTDOCS_ALLOWED_HOSTS=docs.example.com
    EXACTDOCS_PUBLIC_URL=https://docs.example.com
    EXACTDOCS_HOST=0.0.0.0
    ```

    ```bash
    export EXACTDOCS_SECRET_KEY=$(openssl rand -base64 32)
    uvx exactdocs serve
    ```

    `serve` binds `127.0.0.1` unless `EXACTDOCS_HOST` (or `--host`) says otherwise.

The hardened container setup is on [Deployment](../deployment/quick-start.md), and the reverse proxy
side on [Behind a reverse proxy](../deployment/reverse-proxy.md).
