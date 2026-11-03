# AGENTS.md

Guidance for AI coding agents working in this repository. Humans: see CONTRIBUTING.md.

## Project

ExactDocs: a self-hosted MCP server that serves version-accurate, verbatim documentation.
Python 3.14 uv workspace (`packages/exactdocs`, `packages/exactdocs-kernel`) + React client (`web/`),
shipped as one Docker image and as `uvx exactdocs`.

## Skills

Read the matching skill **before** starting the task. They live in `.agents/skills/`:

| Skill | When |
|---|---|
| [working-on-issues](.agents/skills/working-on-issues/SKILL.md) | implementing any issue, start to PR |
| [claiming-issues](.agents/skills/claiming-issues/SKILL.md) | before you start / when you stop work on an issue (mandatory for subagents) |
| [writing-issues](.agents/skills/writing-issues/SKILL.md) | filing or rewriting a feature/bug issue |
| [testing](.agents/skills/testing/SKILL.md) | what and how to test, verification before a PR |
| [backend-architecture](.agents/skills/backend-architecture/SKILL.md) | any Python change: domains, ports, adapters |
| [web-features](.agents/skills/web-features/SKILL.md) | any change in `web/` |
| [releasing](.agents/skills/releasing/SKILL.md) | tags, versions, the release workflow |

## Hard rules

- Domains never import each other or `bootstrap`; ports are `Protocol`s; no `abc.ABC`
  (docs/architecture.md). Architecture tests must stay green.
- Work happens on `feat/<issue>-<slug>` / `fix/<issue>-<slug>` branches from `develop`; PRs go to
  `develop`. Never push to `main` or `develop` directly, never delete them, never force-push them.
- Claim an issue before working on it; release it when you stop.
- No AI attribution in commits, PRs or issues (no `Co-Authored-By`, no "Generated with").
- Do not create tags or publish releases unless a human asked.

## Commands

```bash
uv sync
uv run ruff format . && uv run ruff check . && uv run ty check
uv run pytest && uv run behave
cd web && pnpm install && pnpm lint && pnpm test && pnpm build
uv run exactdocs serve --reload        # :3000 (API, /mcp, UI if built)
```
