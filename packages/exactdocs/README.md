<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/assets/logo/exactdocs-lockup-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/assets/logo/exactdocs-lockup-light.svg">
  <img src="https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/assets/logo/exactdocs-lockup-light.svg" alt="ExactDocs" width="220">
</picture>

# exactdocs

Self-hosted, version-accurate documentation for AI coding agents: an MCP server that serves
the right docs for the right library version, verbatim and with sources.

```bash
uvx exactdocs serve            # HTTP: web UI + MCP on http://localhost:3000
uvx exactdocs serve --stdio    # MCP over stdio
```

See the [project README](https://github.com/SirCypkowskyy/ExactDocs) for the full documentation.
