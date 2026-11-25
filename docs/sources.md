# Sources file

!!! abstract "TL;DR"
    - `exactdocs.sources.yaml` declares an instance's libraries in a file you review and keep in
      git.
    - `exactdocs sources plan` shows the diff and writes nothing; `exactdocs sources apply` makes
      the change and is idempotent.
    - What an entry leaves out is not managed, and nothing is removed without `--prune`.
    - Only operators (the `admin` role) may plan or apply. The file has no credential field.

`exactdocs.sources.yaml` declares the libraries an instance should have.

- The set of imported docs goes through code review like the rest of your infrastructure.
- A second instance (staging, a fresh volume after a restore) can be rebuilt from it.
- `exactdocs sources plan` shows what would change; `exactdocs sources apply` makes the change.

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/schemas/exactdocs.sources.schema.json
version: 1
libraries:
  - url: https://github.com/acme/payments
    refs: [main, v1.4.0]          # tags, branches or full commit SHAs
    include_paths: [docs/]
    exclude_paths: [docs/archive/]
    tag_rules:
      - {pattern: "docs/api/**", tag: api}
    chunking: {split_level: 2}
    title: Payments            # default: named after the repository's README
    description: Payment APIs and the ledger.
    auto_sync: {tag_pattern: "v*", keep_last: 3}
  - url: https://gitlab.com/acme/ledger.git
    id: /acme/ledger-docs         # default: the ID derived from the URL, as when adding a library
    refs: ["2.1"]                 # quote what YAML would read as a number
    auto_sync: false              # turn the scheduled check off
```

The JSON Schema is generated from the server's model:

- committed as [`docs/schemas/exactdocs.sources.schema.json`](schemas/exactdocs.sources.schema.json)
  (`just sources-schema` regenerates it; a test fails when it drifts);
- served at `GET /api/v1/sources/schema`.

With the `yaml-language-server` modeline above, which points at the committed file on GitHub,
editors that use it (VS Code's YAML extension, for one) complete and check the file.

!!! tip "Pin the schema to the version you run"
    Point the modeline at a copy of the file in your repository instead (a relative path works).
    Do not point it at your instance: the endpoint is operator-only like plan and apply, and the
    editor sends no session or token.

!!! note "Operators only"
    Only operators (accounts with the `admin` role) may plan or apply a sources file, with a
    session or an API token; anyone else gets 403 (CLI exit code 5).

## What the file says

- `version: 1` and `libraries`, a list of at most 300 entries. Unknown keys are
  refused, so a typo is a 422 naming the field (CLI exit code 2).
- Each entry has a `url` and `refs` (at least one).
    - A commit is declared by its full SHA: 40 hex characters, or 64 in a SHA-256 repository, in
      any letter case.
    - A short SHA is refused because the version would be named after the full SHA and every plan
      would show it again.
    - `id` defaults to the ID derived from the URL; one ID may appear once.
- `include_paths`, `exclude_paths`, `tag_rules`, `chunking`, `title`,
  `description` and `auto_sync` are optional.
    - **What an entry leaves out is not managed**: plan never reports it and apply never changes
      it, so a library can be tuned in the UI for the settings the file does not declare.
    - Path lists and tag rules are compared as sets after the server's normalization: reordering
      them or spelling a tag in other letter case is no change.
    - A declared empty `include_paths` means every file: the repository's `context7.json` does not
      fill it in.
- `title` (one line, at most 120 characters) and `description` (at
  most 500; empty means none) name a library that the repository README would name wrongly, for
  example six libraries from one repository limited by `include_paths`.
    - A declared value is stored like an edit by hand (`PATCH /libraries/{owner}/{repo}`, with the
      same cleaning), so a later import keeps it.
    - Plan shows a changed one as an update of the library, and it queues no job.
    - Left out, the README (or `context7.json`) still names and describes the library.
- Supported formats: Markdown (`.md`, `.mdx`) and reStructuredText (`.rst`, the Sphinx source
  of `doc/build/` or `docs/`).
    - A `.txt` file is read as reStructuredText, but only when an `include_paths` entry names
      `.txt` (`doc/**/*.txt`), so a folder never brings in `requirements.txt`.
    - Both formats in one library are imported into the same version.
    - Files that reStructuredText `include` / `literalinclude` must be inside the selected paths to
      be read; one that is not is listed as a `markup` problem and the article is imported without
      it.
- `chunking` takes the fields of the library settings' `chunking` as a whole set: what it
  leaves out takes its default, `split_level` 3 and `max_chars` 4,000 since #381 (6 and no bound
  before).
    - A file that declares only `split_level: 2` therefore means `max_chars` 4,000 now, and `plan`
      shows the change for a library stored without a bound.
    - Declare `max_chars: null` to keep none.
- `auto_sync` takes the fields of `PUT /libraries/{owner}/{repo}/auto-sync` as a whole set
  (what it leaves out takes its default), or `false` to turn the check off. `auto` versions belong
  to the check and are never listed.
- There is no credential field: secrets do not belong in a reviewed file. Add a private library in the
  UI with its credential, then manage it with the file.

## Plan

```bash
uvx exactdocs sources plan exactdocs.sources.yaml            # readable diff
uvx exactdocs sources plan exactdocs.sources.yaml --json     # the server's answer
```

The CLI reads the YAML locally and sends it as JSON to `POST /api/v1/sources/plan`; the server
never parses YAML.

- The file may be at most 1 MB.
- It may not use anchors or aliases (`&a`, `*a`): a few hundred bytes of nested aliases expand to
  gigabytes, and a sources file has no use for them (exit code 2).
- Plan writes nothing and queues nothing, and it does not ask the git remote, so it is fast and
  works offline: a ref that does not exist fails at apply.

The diff has four parts:

- `create`: declared libraries that do not exist.
- `update`: per library,
    - each managed setting that changes (before and after);
    - the refs to add;
    - the scheduled-check change;
    - the job the settings change queues (`reprocess`, `rechunk` or `retag`);
    - the `manual` versions the file does not declare.
- `unchanged`.
- `undeclared`: libraries the file does not declare.

`errors` lists entries apply leaves alone, such as `source_mismatch`: the `id` exists with another
repository URL.

- A trailing `/` or `.git` and the letter case of the scheme and host do not count.
- The path's letter case does, because forges differ on whether it matters.
- A declared ref counts as present when it is a version or its import is queued or running.

## Apply

```bash
uvx exactdocs sources apply exactdocs.sources.yaml
uvx exactdocs sources apply exactdocs.sources.yaml --prune   # also removes what is undeclared
```

Apply computes the plan again and applies it one library at a time, in this order:

1. **Creations.** The first ref is imported with the declared paths, tag rules and chunking, then
   the other refs are added, then the scheduled check is set.
2. **Updates.**
3. **Removals, only with `--prune`** (`"prune": true`): undeclared libraries and undeclared
   `manual` versions. Without it nothing is ever removed.

- When a setting changes, the settings the file does not manage are sent as stored.
- One library failing does not stop the others. Each result has its `action` (`created`,
  `updated`, `unchanged`, `removed`, `failed`), the jobs it queued and its `error`.
- The CLI exits 1 when any library failed.

Apply is idempotent: a second apply of the same file, also while the first one's imports are still
queued or running, reports every library as unchanged and writes nothing. Apply does not wait for
the imports; follow them in the UI or with `GET /api/v1/jobs/{id}`.

!!! note "How long the CLI waits"
    The server answers once the whole file is applied, about a second or two per new library, so
    the CLI's `sources plan` and `sources apply` wait 15 s plus 15 s per declared library for that
    answer (other commands wait 15 s). If even that runs out, the server may still be applying the
    file: run `sources plan` to see what is left, or `sources apply` again.

Out of scope for now:

- a drift check between plan and apply;
- a lock against two concurrent applies;
- waiting for the queued jobs;
- the pinned default version;
- retrieval settings;
- manual tags;
- webhooks.
