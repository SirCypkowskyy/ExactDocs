# Web client: vertical slices

!!! abstract "TL;DR"

    - The React client is split into features, each mirroring a backend use case or domain view.
    - Features never import each other. Routes are thin and use a feature's public API only.
    - Shared code moves to `shared` when it is generic; business logic that only looks the same
      stays duplicated.

```mermaid
flowchart TD
    app["app/<br/>providers, router, QueryClient"]
    routes["routes/<br/>TanStack Router file routes: thin"]
    subgraph features ["features/(name) (auth, browse, libraries, library-settings, search, tokens)"]
        index["index.ts<br/>public API"] --> inner["api/ components/ hooks/ model/"]
    end
    shared["shared/<br/>ui, lib, config"]
    app --> routes
    routes -->|public API only| index
    routes -. "types only" .-> app
    features --> shared
    routes --> shared
```

- A feature mirrors a backend use case or domain view.
- Features never import each other. If two need the same thing, it:
    - moves to `shared` when it is generic;
    - stays duplicated when it is business logic that only looks the same.

Details: [web/README.md](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/web/README.md).
