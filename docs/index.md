# ExactDocs

**Self-hosted, version-accurate documentation for AI coding agents.**

Point ExactDocs at a git repository (GitHub, Bitbucket, GitLab or any git server), pick the
folder or Markdown files you care about, and browse and search them, in the web UI and from
your AI agent over MCP, pinned to the exact tag, branch or commit you imported.

```bash
docker run -d -p 3000:3000 -v exactdocs-data:/data ghcr.io/sircypkowskyy/exactdocs:latest
# or, without Docker
uvx exactdocs serve
```

Point your agent at `http://localhost:3000/mcp` (Streamable HTTP) or run `uvx exactdocs serve --stdio`.

## This site

| Section | What is in it |
|---|---|
| [User stories](user-stories.md) | The main use case (git repo → Markdown → browse) as user stories, plus what comes next and later |
| [Architecture](architecture.md) | Modular monolith, ports & adapters, the data model, background jobs, vertical slices, and the tests that enforce them |
| [Flows](flows.md) | Import, re-sync, query, retrieval modes and authentication as diagrams |
| [REST API](rest-api.md) | Conventions, authentication, errors and the library, version, sync and job endpoints |
| [Delivery plan](plan.md) | The issues behind the user stories, by epic and milestone |
| [Branching and releases](releasing.md) | `main` / `develop`, SemVer + PEP 440 versions, tag-driven releases to PyPI and ghcr.io, CI runners, size budgets |

This site describes ExactDocs as built in **MVP-1 (v0.2.0)**. Anything not built yet is marked
*planned* or *MVP-2* / *Next*. The diagrams are [Mermaid](https://mermaid.js.org); CI parses every
one of them. The site loads Mermaid from unpkg (pinned to 12.3.0, the version CI checks
with), a request made by this documentation site only, never by the running app.

The project README, contributing guide and agent skills live in the
[repository](https://github.com/SirCypkowskyy/ExactDocs).
