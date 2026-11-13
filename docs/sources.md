# Sources file

`exactdocs.sources.yaml` declares the libraries an instance should have, so that the set of
imported docs goes through code review like the rest of your infrastructure, and a second
instance (staging, a fresh volume after a restore) can be rebuilt from it. `exactdocs sources plan`
shows what would change; `exactdocs sources apply` makes the change.

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/schemas/exactdocs.sources.schema.json
version: 1
libraries:
  - url: https://github.com/acme/payments
    refs: [main, v1.4.0]          # tags, branches or full 40-character commit SHAs
    include_paths: [docs/]
    exclude_paths: [docs/archive/]
    tag_rules:
      - {pattern: "docs/api/**", tag: api}
    chunking: {split_level: 2}
    auto_sync: {tag_pattern: "v*", keep_last: 3}
  - url: https://gitlab.com/acme/ledger.git
    id: /acme/ledger-docs         # default: the ID derived from the URL, as when adding a library
    refs: ["2.1"]                 # quote what YAML would read as a number
    auto_sync: false              # turn the scheduled check off
```

The JSON Schema is generated from the server's model, committed as
[`docs/schemas/exactdocs.sources.schema.json`](schemas/exactdocs.sources.schema.json) (`just
sources-schema` regenerates it; a test fails when it drifts) and served at
`GET /api/v1/sources/schema`. With the `yaml-language-server` modeline above, editors that use it
(VS Code's YAML extension, for one) complete and check the file. Point the modeline at a local copy
or your instance's URL if you prefer.

Only operators (accounts with the `admin` role) may plan or apply a sources file, with a session
or an API token; anyone else gets 403 (CLI exit code 5).

## What the file says

- `version: 1` and `libraries`, a list of at most 300 entries. Unknown keys are refused, so a typo
  is a 422 naming the field (CLI exit code 2).
- Each entry has a `url` and `refs` (at least one; a short SHA is refused because the version would
  be named after the full SHA and every plan would show it again). `id` defaults to the ID derived
  from the URL; one ID may appear once.
- `include_paths`, `exclude_paths`, `tag_rules`, `chunking` and `auto_sync` are optional. **What
  an entry leaves out is not managed**: plan never reports it and apply never changes it, so a
  library can be tuned in the UI for the settings the file does not declare. Path lists and tag
  rules are compared as sets after the server's normalization: reordering them or spelling a tag
  in other letter case is no change. A declared empty `include_paths` means every file: the
  repository's `context7.json` does not fill it in.
- `auto_sync` takes the fields of `PUT /libraries/{owner}/{repo}/auto-sync` as a whole set (what
  it leaves out takes its default), or `false` to turn the check off. `auto` versions belong to
  the check and are never listed.
- There is no credential field: secrets do not belong in a reviewed file. Add a private library in
  the UI with its credential, then manage it with the file.

## Plan

```bash
uvx exactdocs sources plan exactdocs.sources.yaml            # readable diff
uvx exactdocs sources plan exactdocs.sources.yaml --json     # the server's answer
```

The CLI reads the YAML locally (`safe_load`, at most 1 MB) and sends it as JSON to
`POST /api/v1/sources/plan`; the server never parses YAML. Plan writes nothing and queues nothing,
and it does not ask the git remote, so it is fast and works offline: a ref that does not exist
fails at apply. The diff has four parts:

- `create`: declared libraries that do not exist.
- `update`: per library, each managed setting that changes (before and after), the refs to add,
  the scheduled-check change, the job the settings change queues (`reprocess`, `rechunk` or
  `retag`) and the `manual` versions the file does not declare.
- `unchanged`.
- `undeclared`: libraries the file does not declare.

`errors` lists entries apply leaves alone, such as `source_mismatch`: the `id` exists with
another repository URL (a trailing `/` or `.git` does not count). A declared ref counts as present
when it is a version or its import is queued or running.

## Apply

```bash
uvx exactdocs sources apply exactdocs.sources.yaml
uvx exactdocs sources apply exactdocs.sources.yaml --prune   # also removes what is undeclared
```

Apply computes the plan again and applies it one library at a time: creations (the first ref is
imported with the declared paths, tag rules and chunking, then the other refs are added, then the
scheduled check is set), then updates, then, only with `--prune` (`"prune": true`), removals of
undeclared libraries and undeclared `manual` versions. Without it nothing is ever removed. When a
setting changes, the settings the file does not manage are sent as stored. One library failing
does not stop the others: each result has its `action` (`created`, `updated`, `unchanged`,
`removed`, `failed`), the jobs it queued and its `error`. The CLI exits 1 when any library failed.

Apply is idempotent: a second apply of the same file, also while the first one's imports are still
queued or running, reports every library as unchanged and writes nothing. Apply does not wait for
the imports; follow them in the UI or with `GET /api/v1/jobs/{id}`.

Out of scope for now: a drift check between plan and apply, a lock against two concurrent applies,
waiting for the queued jobs, library titles, descriptions, the pinned default version, retrieval
settings, manual tags and webhooks.
