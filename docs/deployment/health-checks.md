# Health checks

!!! abstract "TL;DR"

    - `/healthz` is liveness: `200` while the process runs.
    - `/readyz` is readiness: `200` only when the database answers at this version's schema.
    - Both answer without sign-in, whatever the `Host` header says.

Two probes answer `GET` and `HEAD` without sign-in, even before the first account exists, for
Docker, Kubernetes or a load balancer:

| Path | Answers | Use it for |
|---|---|---|
| `/healthz` | `200` while the process runs, whatever the database does, within about 0.3 s, with the fields below | liveness: restart the process when it stops answering |
| `/readyz` | `200 {"status": "ready"}` when the database file exists, answers within 2 s and is at this version's schema; else `503 {"status": "not_ready", "reason": ...}` | readiness: send traffic only while it is ready |

`/healthz` answers with:

- `status`, `version` and `database_reachable`;
- when the database answered in time, also `schema_revision`, `search_index_format`,
  `reindex_required`, `search_engine` (`null` when unknown) and `vector_store_missing` (the
  extension hybrid search needs and cannot load once an embedding model is configured,
  `sqlite-vec` or `vector`; `null` otherwise).

`/api/health` is an alias of `/healthz`, kept for existing clients. Neither probe creates a missing
database file (an existing empty one gets SQLite's header and WAL files on connect). To wait for a
starting instance, poll `/readyz`: liveness answers before the database does.

```yaml
livenessProbe:  {httpGet: {path: /healthz, port: 3000}, timeoutSeconds: 1, periodSeconds: 10}
readinessProbe: {httpGet: {path: /readyz, port: 3000}, timeoutSeconds: 3, periodSeconds: 10}
```

The probes answer whatever the `Host` header says, so a Kubernetes `httpGet` probe, which sends the
pod IP, needs no extra header. Only exact `GET` and `HEAD` requests on these three paths skip the
DNS-rebinding guard, and `/healthz` then answers just `{"status": "ok"}`. The version and the
database details go only to a `Host` the instance trusts (`localhost` or
`EXACTDOCS_ALLOWED_HOSTS`).

The Docker image's `HEALTHCHECK` asks `/readyz`, so `docker compose`'s
`depends_on: condition: service_healthy` waits for a usable database. Plain Docker only marks the
container unhealthy. Docker Swarm, or an autoheal sidecar, restarts an unhealthy container, so
there a database outage longer than a few checks turns into restarts. With SQLite on a local
volume, that is what you want: a restart reopens the file.

??? note "How a probe waits for a stuck database"
    A probe stops waiting for the database when its time budget is up, even while a statement still
    runs. That check finishes in the background, and later probes wait for it instead of starting
    another, so however often they are called, a stuck database holds at most one connection for
    each probe. A probe may therefore get the result of a check an earlier probe started.

    A stopping instance waits up to 2 s for such a check, then cancels it and waits up to 2 s more
    before it closes its database connections. A statement stuck in the driver's thread cannot be
    interrupted: if the check still runs after those 4 s, the instance logs a warning and stops
    without it, and that connection may be finalized, unclosed, later.
