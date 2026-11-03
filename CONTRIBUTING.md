# Contributing

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.14), Node 26 LTS, pnpm 12.

```bash
uv sync                                   # Python workspace + dev tools
(cd web && pnpm install)
uv run exactdocs serve --reload           # API + MCP on :3000
(cd web && pnpm dev)                      # UI on :5173, proxies /api and /mcp to :3000
```

## Checks (the same ones CI runs)

```bash
uv run ruff format . && uv run ruff check .
uv run ty check
uv run pytest                              # unit, integration, architecture
uv run behave                              # acceptance scenarios
(cd web && pnpm lint && pnpm test && pnpm build)
```

## Workflow

1. Every change starts from an issue written with the templates (Feature or Bug). See
   [.agents/skills/writing-issues](.agents/skills/writing-issues/SKILL.md).
2. Branch from `develop`: `feat/<issue>-<slug>` or `fix/<issue>-<slug>`.
3. Turn the issue's *Expected behavior* into a behave scenario, then unit tests, then code.
4. Open a PR into `develop` with `Closes #<issue>`. CI must be green.

Read [docs/architecture.md](docs/architecture.md) before adding a domain, port or adapter, and
[docs/releasing.md](docs/releasing.md) for versions and tags.
