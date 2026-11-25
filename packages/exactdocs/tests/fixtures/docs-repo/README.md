# Fixture docs repository

A small, fictional documentation repository ("Acme Payments") that import, chunking, search and
sync tests run against. It is **built into a real git repository** at test time, so the commit
SHAs are the same on every machine and in CI.

| What | Value |
|---|---|
| Tags | `v1.3.0`, `v1.4.0` (lightweight) |
| Branches | `main` (= `v1.4.0`), `next` (one commit ahead of `v1.4.0`) |
| Article paths | repo-relative, e.g. `docs/guide/install.md`; the root has `README.md` and `AGENTS.md` |

## Layout

```
history.toml           the commits, oldest first: name, message, date, tags, branches, delete, generated
commits/<name>/        the files that commit adds or changes (everything else is inherited)
expected-queries.yaml  query -> expected top section, per version
.gitattributes         `* -text`: nothing here may be normalised, some files are invalid UTF-8 on purpose
```

The tree of a commit is the previous commit's tree, plus the files under `commits/<name>/`, minus
the paths in its `delete` list. `generated` files are written by the builder (the oversized one is
2.2 MB; it is not kept in git).

## Using it

```python
def test_something(docs_repo):  # pytest, session scoped: tests/conftest.py
    docs_repo.path, docs_repo.file_url, docs_repo.http_url
```

In behave, `context.fixture_repo` has the same three attributes (`features/environment.py`). A test that
changes or deletes the repository serves its own copy with `serve_copy(base)` (behave:
`context.fixture_serve_copy`), whose `token` can be changed to make the server refuse the old one.
`file_url` is `file:///.../fixture/docs-repo`; `http_url` is
`http://127.0.0.1:<port>/fixture/docs-repo.git`, served by `git http-backend`, with filters and
fetching commits by SHA enabled. To build it by hand, for example for a smoke test with the repository mounted into a container:

```bash
python packages/exactdocs/tests/fixtures/fixture_repo.py /tmp/out/fixture/docs-repo   # prints the refs
```

`git` must be on `PATH`; it is run with an isolated configuration (no global or system config).

## What is in it

| Need | Where |
|---|---|
| code blocks, tables | `docs/guide/setup.md` (`install.md` from v1.4.0), `docs/guide/auth.md` |
| front matter `title`, `tags`, `description` | `docs/guide/setup.md`, `docs/api/auth.md` |
| title from the first H1; title from the file name | `docs/guide/auth.md`; `docs/notes.md` |
| MDX with JSX | `docs/api/client.mdx` |
| both admonition syntaxes | `docs/guide/callouts.md` (GitHub alerts, Docusaurus fences) |
| `snake_case`, `camelCase`, `--flag`, `pkg.mod.fn` | `docs/reference/naming.md` |
| `retry_policy`, only in `v1.4.0` and `next` | `docs/guide/resilience.md` |
| root README, `AGENTS.md` | `README.md`, `AGENTS.md` |
| root `context7.json` (folders `docs`, excludes `archive` and `CHANGELOG.md`, rules, `previousVersions`) | `context7.json` (`next` only) |
| file renamed between tags | `docs/guide/setup.md` -> `docs/guide/install.md` |
| Latin-1 file | `docs/legacy/latin1.md` |
| undecodable file (no NUL, invalid as UTF-8, ASCII and cp1252) | `docs/legacy/undecodable.md` |
| binary files | `docs/assets/logo.png`, `docs/legacy/binary.md` (a PNG named `.md`) |
| oversized file (> 2 MiB) | `docs/reference/oversized.md` (generated, `v1.3.0` on) |
| path to exclude | `docs/archive/` |
| images referenced by an article: inside `docs/`, outside it, SVG, missing, external | `docs/guide/diagrams.md` (`next` only), `docs/assets/logo.png`, `docs/assets/flow.svg`, `img/flow.png` |
| a project logo the importer finds (#504), an SVG with a script it cleans out; an image too small to be a logo | `.github/logo.svg` (`next` only); `docs/assets/logo.png` (1 x 1 pixel, every version) |

The words *retry*, *retries* and *policy* appear in `v1.3.0` nowhere, on purpose: a search for
`retry_policy` must come back empty there even when a tokenizer splits it into parts.

## Adding content without breaking the SHAs

A commit's SHA covers its tree, its parent and its message, so **any change to a file or to
`history.toml` changes the SHA of that commit and of every later one**. There is no way around
that; the golden SHAs in `tests/fixtures/test_fixture_repo.py` (`GOLDEN_SHAS`) are the guard
against changing it by accident. Pick the cheapest option:

1. **A new file or an edit that only a later version needs**: put it under the *latest* commit
   you can (`commits/next/` or a new commit appended to `history.toml`), so earlier SHAs stay
   as they are. Appending a commit never changes older ones.
2. **A file every version needs**: add it under `commits/v1.3.0/`. Every SHA changes; that is fine.
3. Then update `GOLDEN_SHAS`: run the build by hand (above) and copy the printed `refs`. Mention
   in the PR why they changed.

Rules for content:

- Never use the words *retry*, *retries* or *policy* (or `retry_policy`) in `commits/v1.3.0/`.
- Keep a renamed file similar enough (git needs ~50%) that `git diff -M` still reports a rename.
- Keep files byte-exact: no editors that fix encodings, line endings or trailing newlines in
  `docs/legacy/`. `.gitattributes` protects git, not your editor.
- Do not add Python files below this directory (ruff and pytest would pick them up).
- Anything that has to be bigger than a few KB is *generated* (`generated` in `history.toml`).

## Adding a query to `expected-queries.yaml`

```yaml
  - query: connection_pool
    expected:
      v1.3.0: {article: docs/guide/configuration.md, heading_path: [Configuration, Connection pool]}
      v1.4.0: {article: docs/guide/configuration.md, heading_path: [Configuration, Connection pool]}
```

- `heading_path` starts at the H1 and ends at the section that must rank first. Decoys are
  deliberate: other articles mention the same terms (`retry_policy` is also a row of the
  `client.mdx` table), so ranking has something to get wrong.
- `null` means the version has no hit at all; leave a version out to not assert it.
- Optional keys on a query entry, read by the ranking suite:
  - `tags: [api, auth]` (with `tags_match: any|all`, default `any`) searches with a tag filter;
  - `top_n: 3` accepts the section anywhere in the first three hits (default: first);
  - `xfail: "<reason and #issue>"` marks a known gap; the suite expects it to fail (strict), so
    delete the key when the issue is fixed.
- Add the same case to the retrieval eval dataset
  (`packages/exactdocs/evals/retrieval_eval/dataset.yaml`, `kind: identifier`); a test fails until
  the two agree. See [docs/evals/suite.md](../../../../../docs/evals/suite.md#the-dataset).
- Versions are `v1.3.0`, `v1.4.0` and `next`. `test_fixture_repo.py` checks that every entry
  points at a heading that exists and contains the query, so a typo fails fast. Whether the
  section really ranks first is asserted by the ranking suite, not here.

## The ranking suite

`tests/retrieval/ranking/` imports this repository with the real importer and runs every table
entry through the `SearchDocs` port (`pytest packages/exactdocs/tests/retrieval/ranking`); the
behave scenario "Every expected query ranks its section first" does the same over HTTP. A failure
prints the actual top 5. To add a case, add an entry to `expected-queries.yaml` (above); if the
content it needs is missing, add it under the *latest* commit that can hold it (see "Adding content
without breaking the SHAs") and update `GOLDEN_SHAS`. To run the suite on another engine, add it to
`ENGINES` and to `open_container` in `tests/retrieval/ranking/conftest.py`: the cases stay the same.
With `EXACTDOCS_TEST_POSTGRES_URL` set it also runs on PostgreSQL full-text search (`postgres_fts`,
`postgres_fts_c`) and, with `EXACTDOCS_TEST_PG_SEARCH=1` (a server with the extension), on
ParadeDB's BM25 (`pg_search`); CI runs all of them on ParadeDB.
