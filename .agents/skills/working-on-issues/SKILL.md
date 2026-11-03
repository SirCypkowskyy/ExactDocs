---
name: working-on-issues
description: Use when implementing a GitHub issue in ExactDocs end to end, from reading and claiming it to an open PR into develop. Covers branch naming, the test-first order (behave, then pytest), checks and the PR.
---

# Working on an issue

## 1. Understand and claim

```bash
gh issue view <n> --comments
```

- The issue must have *Context*, *Expected behavior* and *Criteria of success* (feature) or
  *Context* and *Why is it bad* (bug). If they are missing or contradictory, ask in a comment
  and stop. Don't guess business rules.
- Claim it with the **claiming-issues** skill before touching code.

## 2. Branch

From an up-to-date `develop`:

```bash
git switch develop && git pull --ff-only
git switch -c feature/<n>-<short-slug>     # or bugfix/<n>-<slug>, docs/<n>-<slug>, chore/<n>-<slug>
```

When several agents run in parallel, each one uses its own git worktree
(`git worktree add ../exactdocs-<n> -b feature/<n>-<slug> develop`).

## 3. Test first, then code

Follow the **testing** skill. In order:

1. **Acceptance:** translate *Expected behavior* into a behave scenario in
   `packages/exactdocs/features/<domain>.feature` (bugs: a scenario that reproduces the bug).
   Run `uv run behave`; it must fail for the right reason.
2. **Unit:** tests for the use case / model in `packages/exactdocs/tests/<domain>/`, using
   in-memory adapters and Protocol-shaped fakes.
3. **Implement** following `docs/architecture.md` (the **backend-architecture** skill):
   model → errors → dtos → ports → use case → module → adapters → wiring in `bootstrap`.
   UI changes follow the **web-features** skill.
4. Make every *Criteria of success* item true and tick it off mentally; if one can't be met,
   say so in the PR and the issue.

## 4. Checks (all must pass, same as CI)

```bash
uv run ruff format . && uv run ruff check . && uv run ty check
uv run pytest && uv run behave
(cd web && pnpm lint && pnpm test && pnpm build)     # if web/ changed
```

Don't silence a rule with `noqa` / `ty: ignore` / a skipped test to get green. Fix the cause,
or explain the exception in the PR.

## 5. Commit and PR

- Conventional commits: `feat(retrieval): refuse unindexed versions (#<n>)`, `fix(...)`, `chore(...)`.
- No AI attribution or co-author trailers in commits or PRs.
- PR into **`develop`** using `.github/pull_request_template.md`, with `Closes #<n>`:

```bash
git push -u origin HEAD
gh pr create --base develop --fill-first --body-file <filled template>
```

Then hand off with `claiming-issues/scripts/handoff.sh <n> review <pr-url> "<summary>"`.

## Labels and repository setup

Labels are defined in `.github/labels.yml`; apply them with `scripts/sync-labels.sh`.
