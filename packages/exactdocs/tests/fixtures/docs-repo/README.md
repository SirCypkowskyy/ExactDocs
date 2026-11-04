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

In behave, `context.fixture_repo` has the same three attributes (`features/environment.py`).
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
| file renamed between tags | `docs/guide/setup.md` -> `docs/guide/install.md` |
| Latin-1 file | `docs/legacy/latin1.md` |
| undecodable file (no NUL, invalid as UTF-8, ASCII and cp1252) | `docs/legacy/undecodable.md` |
| binary files | `docs/assets/logo.png`, `docs/legacy/binary.md` (a PNG named `.md`) |
| oversized file (> 2 MiB) | `docs/reference/oversized.md` (generated, `v1.3.0` on) |
| path to exclude | `docs/archive/` |

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
- Optional keys on a query entry are the extension point for the ranking suite (E5-04), for
  example `tags: [api, auth]` (a tag-filtered query) or `top_n: 3` (the section must be among the
  first three). They are not implemented yet and unknown keys are ignored.
- Versions are `v1.3.0`, `v1.4.0` and `next`. `test_fixture_repo.py` checks that every entry
  points at a heading that exists and contains the query, so a typo fails fast. Whether the
  section really ranks first is asserted by the ranking suite (E5-04), not here.
