<picture>
  <source media="(prefers-color-scheme: dark)" srcset="public/brand/exactdocs-lockup-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="public/brand/exactdocs-lockup-light.svg">
  <img src="public/brand/exactdocs-lockup-light.svg" alt="ExactDocs" width="220">
</picture>

# ExactDocs web UI

React client served by the ExactDocs backend from `web/dist` in production.

Stack: Vite 8, React 19, TypeScript (strict), TanStack Router (file-based) and TanStack Query, shadcn/ui on Tailwind v4, Recharts (only in the overview's lazily loaded chart chunk), Biome, react-doctor, fallow, Vitest.

Requires Node 26 LTS (`.nvmrc`) and pnpm 12 (`packageManager` in `package.json`).

```bash
pnpm install
pnpm dev          # http://localhost:5173, proxies /api and /mcp to http://localhost:3000 (override: EXACTDOCS_API_URL)
pnpm build        # typecheck + production build into dist/ (with dist/THIRD_PARTY_NOTICES.txt)
pnpm test         # Vitest
pnpm lint         # Biome + fallow (architecture, dead code) + react-doctor
```

The build writes `dist/THIRD_PARTY_NOTICES.txt` (`scripts/third-party-notices.ts`): the licence
of every package the production `dependencies` pull in (the IBM Plex fonts' SIL Open Font License
among them), of the build tools whose code is in the bundle (Tailwind CSS, Vite), and of the
source adapted into `src/` (shadcn/ui, and the Shadcnblocks.com free blocks named in `DESIGN.md`).
It ships with the UI in the wheel and the image. A bundled module from any other package (say, a
devDependency imported by the app) fails the build: make it a production dependency.

## Layout: vertical slices

```mermaid
flowchart TD
    subgraph src [src/]
        app["app/<br/>composition root: main.tsx, router, QueryClient, global styles, devtools"]
        routes["routes/<br/>TanStack Router file routes (thin: loader + component from a feature)<br/>routeTree.gen.ts is generated, committed, never edited by hand"]
        subgraph feature ["features/(feature)/"]
            index["index.ts<br/>the only public API of the slice"]
            parts["api/ queryOptions, mutations, HTTP calls<br/>components/ UI owned by the feature<br/>hooks/ React hooks<br/>model/ types and pure logic"]
            index --> parts
        end
        shared["shared/<br/>ui (shadcn/ui), lib (cn, HTTP client), config (constants)"]
    end
    app -->|builds the router from| routes
    routes -->|"@/features/(name) only"| index
    routes -. "types only (router context)" .-> app
    routes --> shared
    parts --> shared
```

The features are `access-log`, `ai`, `auth`, `browse`, `instance-status`, `leaderboard`, `libraries`, `library-settings`, `overview`, `playground`, `search`, `sharing`, `tokens` and `users`. An
arrow is an allowed import; anything not drawn is forbidden (a feature never imports another
feature, `app/` or `routes/`; `shared/` imports nothing from the rest).

## Rules (enforced in CI)

| Rule | Enforced by |
|---|---|
| A feature imports only `shared/` and its own files (relative imports); never another feature, `app/` or `routes/` | fallow (`.fallowrc.json` boundaries, one zone per feature) and Biome `noRestrictedImports` |
| `shared/` imports nothing from `features/`, `app/` or `routes/` | fallow and Biome |
| Outside a feature, import it only through `@/features/<name>`, never a deep path | Biome `noRestrictedImports` |
| `routes/` composes features; it may import `app/` for types only (router context) | fallow `allowTypeOnly` |
| Every file in `src/` belongs to a zone | fallow `boundaries.coverage.requireAllFiles` |

When two features need the same thing, move it to `shared/` or compose both in a route; do not import one feature from another.
