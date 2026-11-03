---
name: web-features
description: Use when adding or changing UI in web/ (React, TanStack Router/Query, shadcn). Explains the vertical slice layout, the import rules enforced by fallow and Biome, and the commands to verify.
---

# Web features (vertical slices)

Read `web/README.md` first. Reference slice: `web/src/features/libraries/`.

## Layout and rules

```
src/app/              composition: providers, router, QueryClient
src/routes/           TanStack file routes: thin; loaders call feature queryOptions; render feature components
src/features/<name>/  api/ (queryOptions + fetchers), components/, hooks/, model/ (types, schemas), index.ts
src/shared/           ui/ (shadcn), lib/ (http client, utils), config/
```

- A feature never imports another feature. `shared` never imports `features`, `routes` or `app`.
- Everything outside a feature imports it only through `@/features/<name>` (its `index.ts`).
- Server state goes through TanStack Query `queryOptions` in `api/`; one place per endpoint.
  No `fetch` in components.
- A feature usually maps to one backend domain or use case and uses its REST DTO shapes
  (`/api/v1/...`) in `model/`.

`pnpm lint:arch` (fallow) and `pnpm check` (Biome `noRestrictedImports`) fail on violations.

## Add a feature

1. `src/features/<name>/model/` types → `api/` queryOptions → `components/` → `index.ts` exports.
2. A route in `src/routes/` that uses only the public API.
3. shadcn components: `pnpm dlx shadcn@latest add <component>`. They land in `src/shared/ui`;
   check the generated imports point to `@/shared/lib/utils`.
4. Test with vitest next to the code (`*.test.tsx`).

## Verify

```bash
cd web
pnpm lint      # biome + fallow architecture + fallow dead-code + react-doctor
pnpm test
pnpm build     # typecheck + vite build (commit the regenerated routeTree.gen.ts)
```
