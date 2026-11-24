<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/assets/logo/exactdocs-lockup-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/assets/logo/exactdocs-lockup-light.svg">
  <img src="https://raw.githubusercontent.com/SirCypkowskyy/ExactDocs/main/docs/assets/logo/exactdocs-lockup-light.svg" alt="ExactDocs" width="220">
</picture>

# exactdocs-kernel

Shared kernel of [ExactDocs](https://github.com/SirCypkowskyy/ExactDocs).

The only code every domain of the `exactdocs` modular monolith may import. It must stay
small, stable and framework-free (no FastAPI, FastMCP, Pydantic or database drivers), and it
must never import `exactdocs`.
