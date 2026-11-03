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

## Workflow

1. Every change starts from an issue written with the templates (Feature or Bug). See
   [.agents/skills/writing-issues](.agents/skills/writing-issues/SKILL.md).
2. Branch from `develop`: `feature/<issue>-<slug>`, `bugfix/<issue>-<slug>` or `docs/<issue>-<slug>`.
   PRs into `develop` are **squash-merged**; `develop` → `main` uses a merge commit or rebase.
3. Turn the issue's *Expected behavior* into a behave scenario, then unit tests, then code.
4. Open a PR into `develop` with `Closes #<issue>`. CI must be green.

Read [docs/architecture.md](docs/architecture.md) before adding a domain, port or adapter, and
[docs/releasing.md](docs/releasing.md) for versions and tags.
