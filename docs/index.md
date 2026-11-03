# ExactDocs

**Self-hosted, version-accurate documentation for AI coding agents.**
An MCP server that serves the right docs for the right library version, verbatim and with
sources, from infrastructure you control.

```bash
docker run -d -p 3000:3000 -v exactdocs-data:/data ghcr.io/sircypkowskyy/exactdocs:latest
# or, without Docker
uvx exactdocs serve
```

Point your agent at `http://localhost:3000/mcp` (Streamable HTTP) or run `uvx exactdocs serve --stdio`.

## This site

| Section | What is in it |
|---|---|
| [User stories](user-stories.md) | Who uses ExactDocs, what they need and why: the product backlog in "As X, I want Y, because Z" form |
| [Architecture](architecture.md) | Modular monolith, ports & adapters, vertical slices, and the tests that enforce them |
| [Branching and releases](releasing.md) | `main` / `develop`, SemVer + PEP 440 versions, tag-driven releases to PyPI and ghcr.io |

The project README, contributing guide and agent skills live in the
[repository](https://github.com/SirCypkowskyy/ExactDocs).
