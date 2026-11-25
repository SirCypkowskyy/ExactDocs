# Contributing

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.14), Node 26 LTS, pnpm 12,
[just](https://just.systems). On Windows, recipes run in Git Bash.

```bash
just setup        # uv sync --all-groups + pnpm install
just dev          # API + MCP on :3000 and the UI on :5173 (proxies /api and /mcp)
just              # list every recipe
```

## Checks (the same ones CI runs)

```bash
just check        # lint (ruff, ty, biome, fallow, react-doctor), pytest, behave, vitest, builds
just fmt          # auto-format Python and web code
just test -k version     just bdd     just arch     just docs
```

`just test` and `just bdd` need nothing but the checkout: the **integration tests** (anything that
needs PostgreSQL, a search or vector server, Docker or the network) are left out by default, and
the run says how many. Turn them on with one switch, `--integration` for pytest or
`EXACTDOCS_INTEGRATION=1` for both:

```bash
just test-integration -m integration          # pytest: only the integration tests
just bdd-integration --tags=@integration      # behave: only the @integration scenarios
```

Each one runs when its service's `EXACTDOCS_TEST_<NAME>_URL` is set and is skipped, naming the
variable, when it is not; [docs/releasing/tests.md](docs/releasing/tests.md) lists
them and the helper scripts that start the servers. Pull request CI runs the fast checks only.
In GitHub Actions the integration and end-to-end jobs run only when a maintainer starts them by
hand, never on a pull request, a push or a tag: *Actions → CI → Run workflow* with `integration`,
*Actions → Integration → Run workflow*, or a release dry run with `integration`. They take 45 to 60
minutes of runner time, so a maintainer starts them for a PR that touches PostgreSQL, an index
backend on a server, the Dockerfile, the wheel or the end-to-end flow. Locally,
`just test --integration` or `EXACTDOCS_INTEGRATION=1` runs them.

## Workflow

1. Every change starts from an issue written with the templates (Feature or Bug). See
   [.agents/skills/writing-issues](.agents/skills/writing-issues/SKILL.md).
2. Branch from `develop`: `feature/<issue>-<slug>`, `bugfix/<issue>-<slug>` or `docs/<issue>-<slug>`.
   PRs into `develop` are **squash-merged**; `develop` → `main` uses a merge commit or rebase.
3. Turn the issue's *Expected behavior* into a behave scenario, then unit tests, then code.
4. Open a PR into `develop` with `Closes #<issue>`. CI must be green.

Diagrams in the README, `docs/` and `web/README.md` are [Mermaid](https://mermaid.js.org) code blocks,
never ASCII art; `just docs-build` parses every one (`deploy/mermaid-check`) and builds the site in
strict mode, as CI does. The check is a syntax gate (the site pins the same mermaid version through
`extra_javascript`), so look at a new diagram in `just docs` too.

Read [docs/architecture/](docs/architecture/index.md) before adding a domain, port or adapter, and
[docs/releasing/](docs/releasing/index.md) for versions and tags.
