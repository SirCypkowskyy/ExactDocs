# exactdocs-kernel

Shared kernel of [ExactDocs](https://github.com/SirCypkowskyy/ExactDocs).

The only code every domain of the `exactdocs` modular monolith may import. It must stay
small, stable and framework-free (no FastAPI, FastMCP, Pydantic or database drivers), and it
must never import `exactdocs`.
